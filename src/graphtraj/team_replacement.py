"""Replace a Team seat while retaining its Ticket and Session evidence."""

from __future__ import annotations

import os
import time
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path

import yaml

from .runner_batch import read_batch
from .runner_capacity import capacity_positions
from .runner_control import _require_project_events, interrupt_session
from .runner_models import RunnerError
from .runner_process import OPERATION_TIMEOUT_SECONDS
from .runner_project import discover_project, run_git
from .runner_status import read_alias_mapping
from .team_round import _deliver_ticket, _request_state, _run_agent, _trace_ref
from .ticket_graph import _load_states


def require_active_session(project, alias):
    mapping, _ = read_alias_mapping(project.runner_directory, alias)
    directory, ticket = _load_states(project.state_directory / "tickets")[mapping["ticket_id"]]
    team_file = directory / "teams" / str(mapping["team_generation"]) / "team.yml"
    # A newly launched Leader registers its first Batch before Team start.
    if not team_file.exists():
        return
    team = yaml.safe_load(team_file.read_text())
    if team["status"] != "active" or ticket["active_team_ordinal"] != mapping["team_generation"]:
        raise RunnerError("team-not-active", "The Team has stopped starting new work.")
    seats = [seat for seat in team["members"].values() if seat["role"] == mapping["role"]]
    if seats and seats[0]["session_ref"] not in {None, alias}:
        raise RunnerError("seat-replaced", "This Session no longer occupies its Team seat.")
    return team


def replace_session(alias, actor, caused_by_event_ids, cwd):
    if os.environ.get("GRAPHTRAJ_ROLE") or os.environ.get("GRAPHTRAJ_PARENT_ALIAS"):
        raise RunnerError("authority-denied", "Only Main or the user may initiate Team replacement.")
    if not caused_by_event_ids or len(caused_by_event_ids) != len(set(caused_by_event_ids)):
        raise RunnerError("invalid-input", "Replacement requires unique causal Project Worldline event IDs.")
    project = discover_project(cwd)
    _require_project_events(cwd, caused_by_event_ids)
    mapping, session_directory = read_alias_mapping(project.runner_directory, alias)
    directory, ticket = _load_states(project.state_directory / "tickets")[mapping["ticket_id"]]
    generation = mapping["team_generation"]
    team_file = directory / "teams" / str(generation) / "team.yml"
    team = yaml.safe_load(team_file.read_text())
    seats = [
        name
        for name, member in team["members"].items()
        if member["session_ref"] == alias
        or (
            member["session_ref"] is None
            and member["role"] == mapping["role"]
        )
    ]
    seat = seats[0] if len(seats) == 1 else None
    if seat is None or ticket["active_team_ordinal"] != generation:
        raise RunnerError("seat-replaced", "The alias must identify a current Team seat.")
    if ticket["status"] in {"integrating", "resolving-integration", "integrated"}:
        raise RunnerError("team-not-active", "This Ticket has already entered integration.")
    worktree = project.harness_root / ticket["worktree"]
    traces = team_file.parent / "traces"
    retained = Path(mapping["retained_batch_file"])
    batch = read_batch(retained, cwd)
    task = next(task for task in batch.tasks if task.ticket_id == ticket["ticket_id"] and task.role == mapping["role"])
    definition = directory / ticket["current_definition"]
    task = replace(task, ticket_file=definition, ticket_content=definition.read_text())
    leader = team["members"]["team_leader"]["session_ref"]
    state_alias = state_session = None
    capacity_fd = None

    def record(phase, evidence, **facts):
        nonlocal state_alias, state_session, caused_by_event_ids
        state_alias, state_session, event = _request_state(
            project, task, worktree, directory, traces, state_alias, state_session,
            leader, retained,
            {"phase": phase, "ticket_id": task.ticket_id,
             "caused_by_event_ids": list(caused_by_event_ids), "evidence_refs": evidence, **facts},
            phase, capacity_fd=capacity_fd,
        )
        caused_by_event_ids = (event["event_id"],)

    def stop(current_alias):
        _, current_directory = read_alias_mapping(project.runner_directory, current_alias)
        if not (current_directory / "execution.yml").exists():
            interrupt_session(current_alias, cwd)
            return True
        return False

    if seat == "team_leader":
        if team["status"] not in {"active", "retiring"}:
            raise RunnerError("team-not-active", "The Team is already retired.")
        # Interrupting makes the owning Team worker stop instead of scheduling
        # subsequent work. Release its execution capacity before Delivery State
        # records retirement; a fully occupied project needs no spare position.
        # A running child already has a mapping before its completed seat is recorded.
        interrupted = False
        for path in (project.runner_directory / "sessions").glob("*/mapping.yml"):
            current = yaml.safe_load(path.read_text())
            if (current.get("ticket_id") == task.ticket_id
                    and current.get("team_generation") == generation):
                interrupted = stop(current["alias"]) or interrupted
        with ExitStack() as stack:
            # Wait only for interrupted outer Team workers to release their
            # inherited positions; no state request or Batch is retried.
            deadline = time.monotonic() + OPERATION_TIMEOUT_SECONDS
            while True:
                try:
                    positions = stack.enter_context(capacity_positions(project, 1))
                    break
                except RunnerError as error:
                    if not interrupted or error.code != "insufficient-capacity" or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
            capacity_fd = positions[0].fileno()
            if team["status"] == "active":
                record("retiring", [_trace_ref(project, traces, alias)], actor=actor)
            os.environ["GRAPHTRAJ_RETIRING"] = "1"
            try:
                _run_agent(
                    project, task, "team-leader", worktree, directory, traces, alias,
                    mapping["session"], None, None, retained,
                    "Main or the user has retired this Team. Stop all new work and freeze the current state. "
                    "Use $handoff in your final Session response. Keep the handoff only in that response "
                    "and its append-only Trace; do not write a separate handoff artifact.",
                    capacity_fd=capacity_fd, retiring=True,
                )
            finally:
                os.environ.pop("GRAPHTRAJ_RETIRING", None)
            trace_ref = _trace_ref(project, traces, alias)
            record("retired", [trace_ref], session_ref=alias, trace_ref=trace_ref)
            result = _deliver_ticket(project, task, retained, capacity_fd)
        return {"alias": alias, "replacement_alias": result["alias"], "team_ordinal": generation + 1}

    require_active_session(project, alias)
    stop(alias)
    if task.role.endswith("reviewer"):
        task = replace(task, report_file=Path(".state/reviews") / (alias + "-replacement.md"))
    current_commit = run_git(worktree, "rev-parse", "HEAD")
    prior_trace = _trace_ref(project, traces, alias)
    replacement, _ = _run_agent(
        project, task, task.role, worktree, directory, traces,
        None, None, None, leader, retained,
        "Continue this Team seat from previous Session {0} and Trace {1}.\n"
        "Accepted Ticket and constraints:\n{2}\n"
        "Current commit: {3}\n"
        "Valid retained evidence: {1}\n"
        "Failed attempts: inspect the previous Session Trace before changing work.\n"
        "Remaining work: continue only the current {4} Team seat, preserving closed Team Round evidence."
        .format(alias, prior_trace, task.ticket_content, current_commit, task.role),
    )
    record("replace-member", [_trace_ref(project, traces, replacement)], member=seat, role=task.role, session_ref=replacement)
    return {"alias": alias, "replacement_alias": replacement, "team_ordinal": generation}
