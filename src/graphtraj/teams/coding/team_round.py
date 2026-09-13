"""Run-free delivery of one registered Ticket through one Team Round."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
from contextvars import copy_context
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any, Callable

import yaml

from graphtraj.runtimes.codex.codex_project import ignore_worktree_documents
from graphtraj.runtimes.codex.codex_adapter import (
    codex_connection_environment,
    preflight_runtime_context,
    refresh_codex_report_paths,
)
from graphtraj.execution.execution_budget import (
    ExecutionBudgetMonitor,
    caller_notice_fd,
    execution_budget_monitor,
    execution_budget_stage,
)
from graphtraj.configuration.role_definitions import resolve_child_role
from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.graph.delivery_state import apply_delivery_state_request, confirmed_rework
from graphtraj.graph.delivery_worldline import append_project_worldline_event, read_worldline
from graphtraj.configuration.project_roles import ROLE_REFERENCES
from graphtraj.execution.runner_batch import (
    read_batch,
    resolved_role_preset,
    retain_batch,
    valid_ticket_id,
)
from graphtraj.execution.runner_capacity import capacity_positions
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.execution.runner_models import (
    Batch,
    LaunchResponse,
    RunnerError,
    Task,
    role_alias_marker,
)
from graphtraj.workspace.runner_project import (
    discover_project,
    git_succeeds,
    provision_worktree,
    run_git,
    runtime_executable,
)
from graphtraj.execution.runner_status import read_alias_mapping, read_terminal_outcome
from graphtraj.execution.runner_transport import record_runtime_identity
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError
from graphtraj.graph.ticket_graph import _load_states


_COMMIT = re.compile(r"[0-9a-f]{40}")
_ENGINEER_ROLES = frozenset({"engineer-junior", "engineer-senior", "engineer-expert"})
_REVIEWER_ROLES = frozenset({"standards-reviewer", "spec-reviewer"})
_CHILD_ROLES = _ENGINEER_ROLES | _REVIEWER_ROLES
_AGENT_EVIDENCE_ERROR = "AGENT_EVIDENCE_INVALID"


def register_child_batch(batch: Batch, cwd: Path, registration: Path) -> LaunchResponse:
    """Retain and register the Team Leader's one direct child Batch."""

    parent_ticket = os.environ.get("GRAPHTRAJ_TICKET_ID")
    if any(
        task.ticket_id != parent_ticket
        or (
            _task_policy(task) not in _CHILD_ROLES
            and not _is_inline_specialist(task)
        )
        for task in batch.tasks
    ):
        raise RunnerError("BATCH_SCHEMA_INVALID", "A direct child Batch must contain formal roles for its parent Ticket.")
    engineers = [task for task in batch.tasks if _task_policy(task) in _ENGINEER_ROLES]
    reviewers = [task for task in batch.tasks if _task_policy(task) in _REVIEWER_ROLES]
    if not (
        (len(batch.tasks) == 1 and len(engineers) == 1)
        or len(reviewers) == len(batch.tasks) and 1 <= len(reviewers) <= 2
        or len(batch.tasks) == 1 and _is_inline_specialist(batch.tasks[0])
    ):
        raise RunnerError("BATCH_SCHEMA_INVALID", "A direct child Batch must contain one Engineer, one or both Reviewers, or one temporary specialist.")
    project = discover_project(
        Path(os.environ.get("GRAPHTRAJ_HARNESS_ROOT", cwd)),
        require_clean_integration=False,
    )
    limit = load_project_configuration(project.harness_root).dispatch_depth
    depth = 1
    parent_alias = os.environ["GRAPHTRAJ_PARENT_ALIAS"]
    # Count retained Session ancestry, not Batches or resumptions.
    while parent_alias is not None:
        depth += 1
        if depth > limit:
            raise RunnerError(
                "authority-denied",
                f"The child Batch exceeds project dispatch_depth={limit}. No child registered.",
            )
        parent, _ = read_alias_mapping(project.runner_directory, parent_alias)
        parent_alias = parent["parent"]
    from graphtraj.teams.coding.team_replacement import require_active_session

    team = require_active_session(project, os.environ["GRAPHTRAJ_PARENT_ALIAS"])
    members = {seat["role"]: seat["session_ref"] for seat in team["members"].values()} if team else {}
    children = [
        {"ticket_id": task.ticket_id, "role": task.role,
         "alias": members.get(task.role) or _agent_alias(project, task, task.role, int(os.environ.get("GRAPHTRAJ_TEAM_GENERATION", "1"))), "launch_status": "registered"}
        for task in batch.tasks
    ]
    try:
        with registration.open("x", encoding="utf-8") as stream:
            retained = retain_batch(project.state_directory, batch)
            yaml.safe_dump({"retained_batch_file": str(retained), "tasks": children}, stream)
    except (OSError, yaml.YAMLError) as error:
        raise RunnerError("BATCH_RETENTION_FAILED", "The parent worker could not register the child Batch.") from error
    return LaunchResponse(
        document={
            "retained_batch_file": str(retained),
            "tasks": children,
        },
        succeeded=True,
    )


def _is_inline_specialist(task: Task) -> bool:
    """Return whether a task uses the fixed non-Team temporary policy."""

    return task.inline_preset is not None and task.policy_role == "temporary-role"


def _task_policy(task: Task, role: str | None = None) -> str:
    """Return the fixed policy applied to this invocation."""

    if role is None or task.role == role:
        return task.policy_role or task.role
    return role


def launch_team_batch(batch: Batch, cwd: Path) -> LaunchResponse:
    """Deliver each Main-selected registered Ticket through generation 1."""

    if all(task.role == "team-leader" for task in batch.tasks):
        return _run_batch_workers(
            discover_project(cwd, require_clean_integration=False), batch
        )
    if any(task.policy_role != "temporary-role" for task in batch.tasks):
        raise RunnerError("ROLE_NOT_CONFIGURED", "A Main Batch must select the team-leader preset.")
    project = discover_project(cwd)
    with capacity_positions(project, len(batch.tasks)) as positions:
        retained = retain_batch(project.state_directory, batch)
        traces = project.runner_directory / "traces"
        evidence = project.runner_directory / "inline-evidence"
        traces.mkdir(parents=True, exist_ok=True)
        evidence.mkdir(parents=True, exist_ok=True)
        results = []
        for requested, position in zip(batch.tasks, positions):
            task = _registered_ticket_task(project, requested)
            alias, session = _run_agent(
                project,
                task,
                task.role,
                project.integration_worktree,
                evidence,
                traces,
                None,
                None,
                None,
                None,
                retained,
                capacity_fd=position.fileno(),
                wait_for_completion=False,
            )
            results.append(
                {
                    "ticket_id": task.ticket_id,
                    "ticket_name": task.ticket_name,
                    "role": task.role,
                    "launch_status": "launched",
                    "alias": alias,
                    "session": session,
                }
            )
        return LaunchResponse(
            document={"retained_batch_file": str(retained), "tasks": results},
            succeeded=True,
        )


def continue_stopped_ticket(
    ticket_id: str,
    caused_by_event_ids: tuple[str, ...],
    cwd: Path,
) -> dict[str, Any]:
    """Continue one stopped current Team from its retained Batch and Sessions."""

    if os.environ.get("GRAPHTRAJ_ROLE") or os.environ.get("GRAPHTRAJ_PARENT_ALIAS"):
        raise RunnerError(
            "authority-denied",
            "Only Main or the user may continue a stopped Team.",
        )
    if not valid_ticket_id(ticket_id):
        raise RunnerError("invalid-input", "Ticket identity is invalid.")
    if (
        not caused_by_event_ids
        or len(caused_by_event_ids) != len(set(caused_by_event_ids))
        or any(not event_id for event_id in caused_by_event_ids)
    ):
        raise RunnerError(
            "invalid-input",
            "Continuation requires unique causal Project Worldline event IDs.",
        )
    project = discover_project(cwd, require_clean_integration=False)
    try:
        ticket_directory, state = _load_states(project.state_directory / "tickets")[
            ticket_id
        ]
    except KeyError:
        raise RunnerError("invalid-input", "The supplied Ticket is not registered.") from None
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as error:
        raise RunnerError(
            "TICKET_FILE_INVALID", "The selected registered Ticket is invalid."
        ) from error
    generation = state["active_team_ordinal"]
    if (
        not state["active"]
        or state["status"] not in {"implementing", "reviewing", "reworking"}
        or not isinstance(generation, int)
    ):
        raise RunnerError(
            "invalid-input", "Explicit continuation requires the current active Team."
        )
    try:
        team = yaml.safe_load(
            (ticket_directory / "teams" / str(generation) / "team.yml").read_text(
                encoding="utf-8"
            )
        )
        leader_alias = team["members"]["team_leader"]["session_ref"]
        if team["status"] != "active" or not isinstance(leader_alias, str):
            raise ValueError("Team is not active")
        leader_mapping, _ = read_alias_mapping(
            project.runner_directory, leader_alias
        )
        if (
            leader_mapping["ticket_id"] != ticket_id
            or leader_mapping["team_generation"] != generation
            or leader_mapping["role"] != "team-leader"
        ):
            raise ValueError("Leader mapping does not match the current Team")
        for member in team["members"].values():
            alias = member.get("session_ref")
            if isinstance(alias, str):
                _, session_directory = read_alias_mapping(project.runner_directory, alias)
                read_terminal_outcome(session_directory / "execution.yml")
        retained_batch = Path(leader_mapping["retained_batch_file"])
        retained_tasks = [
            task
            for task in read_batch(retained_batch, cwd).tasks
            if task.ticket_id == ticket_id
            and task.ticket_name == state["ticket_name"]
            and task.role == "team-leader"
        ]
        if len(retained_tasks) != 1:
            raise ValueError("Retained Team Batch is invalid")
    except (OSError, TypeError, ValueError, yaml.YAMLError, RunnerError) as error:
        if isinstance(error, RunnerError):
            raise
        raise RunnerError(
            "operation-failed", "The stopped Team cannot resume its retained lifecycle."
        ) from error
    monitor = execution_budget_monitor(ticket_directory, ticket_id, state["ticket_name"])
    if monitor is None or not monitor.is_stopped():
        raise RunnerError(
            "invalid-input", "Explicit continuation requires a sampled stopped Ticket."
        )
    try:
        events = read_worldline(project.state_directory, project.harness_root)
    except (OSError, ValueError) as error:
        raise RunnerError(
            "operation-failed", "The Project Worldline could not be read."
        ) from error
    decisions = [
        event for event in events if event["event_id"] in caused_by_event_ids
    ]
    if len(decisions) != len(caused_by_event_ids):
        raise RunnerError(
            "invalid-input",
            "causal Project Worldline event IDs must identify retained events.",
        )
    try:
        continuation = append_project_worldline_event(
            project.state_directory,
            project.harness_root,
            {
                "kind": "team-continuation-started",
                "caused_by_event_ids": list(caused_by_event_ids),
                "evidence_refs": list(
                    dict.fromkeys(
                        reference
                        for event in decisions
                        for reference in event["evidence_refs"]
                    )
                ),
                "ticket_id": ticket_id,
                "team_ordinal": generation,
                "team_round": team["current_round"],
            },
        )
    except (OSError, ValueError) as error:
        raise RunnerError(
            "operation-failed", "The continuation could not be recorded in the Project Worldline."
        ) from error
    monitor.continue_after_stop()
    try:
        with capacity_positions(project, 1) as positions:
            result = _deliver_ticket(
                project,
                retained_tasks[0],
                retained_batch,
                positions[0].fileno(),
            )
    except RuntimeAdapterError as error:
        raise RunnerError(error.code, error.message) from error
    return {**result, "continuation_event_id": continuation["event_id"]}


def _run_batch_workers(
    project: Any,
    batch: Batch,
    retained: Path | None = None,
    parent_alias: str = "",
    capacity_fd: int | None = None,
    *,
    recover_reports: bool = False,
) -> LaunchResponse:
    """Dispatch the retained Batch, identifying report recovery to its workers."""
    notice_fd, close_notice_fd = caller_notice_fd()
    try:
        workers = []
        with capacity_positions(project, len(batch.tasks), capacity_fd) as positions:
            if retained is None:
                retained = retain_batch(project.state_directory, batch)
            for index, position in enumerate(positions):
                try:
                    environment = dict(os.environ)
                    if notice_fd is not None:
                        environment["GRAPHTRAJ_BUDGET_NOTICE_FD"] = str(notice_fd)
                    worker = subprocess.Popen(
                        [sys.executable, "-m", "graphtraj.teams.coding.team_round",
                         str(retained), str(index), str(position.fileno()), parent_alias,
                         "recover-reports" if recover_reports else ""],
                        cwd=project.harness_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                        env=environment,
                        pass_fds=(position.fileno(),) if notice_fd is None else (position.fileno(), notice_fd),
                    )
                except OSError as error:
                    worker = RunnerError("RUNTIME_WORKER_START_FAILED", str(error))
                workers.append(worker)
                position.close()
        results = []
        for task, worker in zip(batch.tasks, workers):
            if isinstance(worker, RunnerError):
                results.append(_failed_task(task, worker))
                continue
            output, diagnostic = worker.communicate()
            if worker.returncode == 0:
                results.append(yaml.safe_load(output))
            else:
                results.append(_failed_task(task, RunnerError("RUNTIME_WORKER_FAILED", diagnostic.strip())))
        return LaunchResponse(
            document={"retained_batch_file": str(retained), "tasks": results},
            succeeded=all("error" not in result for result in results),
        )
    finally:
        if close_notice_fd and notice_fd is not None:
            os.close(notice_fd)


def _failed_task(task: Task, error: RunnerError) -> dict[str, Any]:
    return {
        "ticket_id": task.ticket_id, "ticket_name": task.ticket_name,
        "role": task.role, "launch_status": "failed", "error": error.as_document(),
    }


def _registered_ticket_task(project: Any, requested: Task) -> Task:
    """Read one registered Ticket definition without changing its state."""

    ticket_directory = project.state_directory / "tickets" / (
        requested.ticket_id + "-" + requested.ticket_name
    )
    try:
        state = yaml.safe_load((ticket_directory / "ticket.yml").read_text(encoding="utf-8"))
        definition = ticket_directory / state["current_definition"]
        content = definition.read_text(encoding="utf-8")
    except (KeyError, OSError, TypeError, yaml.YAMLError) as error:
        raise RunnerError("TICKET_FILE_INVALID", "The selected registered Ticket is invalid.") from error
    if state.get("ticket_id") != requested.ticket_id or state.get("ticket_name") != requested.ticket_name:
        raise RunnerError("TICKET_FILE_INVALID", "The selected registered Ticket is invalid.")
    return replace(requested, ticket_file=definition.resolve(), ticket_content=content)


def _deliver_ticket(project: Any, requested: Task, retained_batch: Path, capacity_fd: int) -> dict[str, Any]:
    # The stopped Leader lends its worker-held position and resumes only after
    # the direct children have exited. PID values are never capacity positions.
    run_agent = partial(_run_agent, capacity_fd=capacity_fd)
    request_state = partial(_request_state, capacity_fd=capacity_fd)
    next_formal_batch = partial(_next_formal_batch, capacity_fd=capacity_fd)
    ticket_directory = project.state_directory / "tickets" / (
        requested.ticket_id + "-" + requested.ticket_name
    )
    state_file = ticket_directory / "ticket.yml"
    try:
        state = yaml.safe_load(state_file.read_text(encoding="utf-8"))
        definition = ticket_directory / state["current_definition"]
        ticket_content = definition.read_text(encoding="utf-8")
    except (KeyError, OSError, TypeError, yaml.YAMLError) as error:
        raise RunnerError("TICKET_FILE_INVALID", "The selected registered Ticket is invalid.") from error
    generation = state.get("active_team_ordinal")
    previous_team = None
    if generation is not None:
        previous_team = yaml.safe_load((ticket_directory / "teams" / str(generation) / "team.yml").read_text())
    budget_monitor = execution_budget_monitor(
        ticket_directory, requested.ticket_id, requested.ticket_name
    )
    if budget_monitor is not None and budget_monitor.is_stopped():
        leader_alias = (
            previous_team["members"]["team_leader"]["session_ref"]
            if previous_team is not None else None
        )
        if not isinstance(leader_alias, str):
            raise RunnerError(
                "EXECUTION_BUDGET_STOPPED",
                "Runner selected stopping before another Team dispatch.",
            )
        mapping = yaml.safe_load(
            (
                project.runner_directory / "sessions" / leader_alias / "mapping.yml"
            ).read_text(encoding="utf-8")
        )
        return {
            "ticket_id": requested.ticket_id,
            "ticket_name": requested.ticket_name,
            "role": "team-leader",
            "launch_status": "stopped",
            "worktree_path": str(project.harness_root / state["worktree"]),
            "alias": leader_alias,
            "session": mapping["session"],
        }
    replacing = previous_team is not None and previous_team["status"] == "retired"
    if previous_team is not None and previous_team["status"] == "active":
        return _resume_active_ticket(
            project,
            requested,
            capacity_fd,
            ticket_directory,
            state,
            definition,
            ticket_content,
            previous_team,
        )
    if not replacing and (
        state.get("ticket_id") != requested.ticket_id
        or state.get("ticket_name") != requested.ticket_name
        or state.get("status") != "ready"
        or state.get("active_team_ordinal") is not None
        or state.get("current_candidate") is not None
    ):
        raise RunnerError("TICKET_ALREADY_ACTIVE", "The selected Ticket is not ready for a first Team.")

    task = replace(requested, ticket_file=definition.resolve(), ticket_content=ticket_content)
    worktree = (project.worktree_root / (requested.ticket_id + "-" + requested.ticket_name)).resolve()
    branch = "agent/{0}-{1}".format(requested.ticket_id, requested.ticket_name)
    if replacing:
        worktree = project.harness_root / state["worktree"]
        branch = state["branch"]
    else:
        discover_project(project.harness_root)
        provision_worktree(project, task, branch, worktree)
    _link_worktree(project, worktree, ticket_directory)

    generation = generation + 1 if replacing else 1
    team_directory = ticket_directory / "teams" / str(generation)
    round_directory = team_directory / "rounds" / "1"
    traces = team_directory / "traces"
    # A failed launch can leave these directories before the Team is registered.
    round_directory.mkdir(parents=True, exist_ok=True)
    traces.mkdir(exist_ok=True)

    registration = project.runner_directory / "sessions" / (
        _agent_alias(project, task, "team-leader", generation)
    ) / "child-registration.yml"
    leader_alias, leader_session = run_agent(
        project, task, "team-leader", worktree, ticket_directory, traces, None, None, registration, None, retained_batch,
        (ticket_content + "\nContinue from the previous Leader's final Session "
         + previous_team["final_session_ref"] + " and Trace " + previous_team["final_trace_ref"]
         + ". Read that handoff before dispatching work.") if replacing else None,
    )

    def recover_evidence(
        child: Task,
        role: str,
        alias: str,
        session: str,
        child_batch: Path,
        error: RunnerError,
        expected: str,
    ) -> tuple[str, str]:
        if error.code != _AGENT_EVIDENCE_ERROR:
            raise error
        return run_agent(
            project,
            child,
            role,
            worktree,
            ticket_directory,
            traces,
            alias,
            session,
            registration if role == "team-leader" else None,
            None if role == "team-leader" else leader_alias,
            child_batch,
            _evidence_recovery_prompt(
                project, child, traces, alias, worktree, error, expected
            ),
        )

    engineer_batch, engineer_batch_path, leader_alias, leader_session = next_formal_batch(
        project,
        task,
        definition,
        ticket_content,
        worktree,
        ticket_directory,
        traces,
        leader_alias,
        leader_session,
        registration,
        retained_batch,
    )
    if (
        len(engineer_batch.tasks) != 1
        or _task_policy(engineer_batch.tasks[0]) not in _ENGINEER_ROLES
    ):
        raise RunnerError("BATCH_SCHEMA_INVALID", "The first direct child Batch must contain one Engineer.")
    engineer_task = replace(
        engineer_batch.tasks[0],
        ticket_file=definition.resolve(),
        ticket_content=ticket_content,
    )

    predecessor = (next(event["event_id"] for event in reversed(read_worldline(project.state_directory, project.harness_root))
                        if event.get("ticket_id") == task.ticket_id and event["kind"] == "team-retired")
                   if replacing else _readiness_predecessor(project, task.ticket_id))
    members = {
        "team_leader": {"role": "team-leader", "session_ref": leader_alias},
        "engineer": {"role": engineer_task.role, "session_ref": None},
        "standards_reviewer": {"role": "standards-reviewer", "session_ref": None},
        "spec_reviewer": {"role": "spec-reviewer", "session_ref": None},
    }
    state_alias, state_session, event = request_state(
        project,
        task,
        worktree,
        ticket_directory,
        traces,
        None,
        None,
        leader_alias,
        retained_batch,
        {
            "phase": "start",
            "ticket_id": task.ticket_id,
            "caused_by_event_ids": [predecessor],
            "evidence_refs": [retained_batch.relative_to(project.harness_root).as_posix()],
            "worktree": worktree.relative_to(project.harness_root).as_posix(),
            "branch": branch,
            "members": members,
        },
        "start",
    )
    predecessor = event["event_id"]

    engineer_alias = engineer_session = None
    first_round = True
    while True:
        try:
            engineer_alias, engineer_session = run_agent(
                project,
                engineer_task,
                engineer_task.role,
                worktree,
                ticket_directory,
                traces,
                engineer_alias,
                engineer_session,
                None,
                leader_alias,
                engineer_batch_path,
            )
        except RunnerError as error:
            if error.code != "EXECUTION_BUDGET_STOPPED":
                raise
            return _wrap_up_budget_stop(
                project, requested, task, engineer_task, worktree,
                ticket_directory, traces, engineer_alias, engineer_batch_path,
                leader_alias, leader_session, registration, retained_batch,
                capacity_fd,
            )
        if first_round:
            state_alias, state_session, event = request_state(
                project, task, worktree, ticket_directory, traces,
                state_alias, state_session, leader_alias, engineer_batch_path,
                {
                    "phase": "member", "ticket_id": task.ticket_id,
                    "caused_by_event_ids": [predecessor],
                    "evidence_refs": [_trace_ref(project, traces, engineer_alias)],
                    "member": "engineer", "role": engineer_task.role,
                    "session_ref": engineer_alias,
                },
                "member-engineer",
            )
            predecessor = event["event_id"]
        try:
            candidate = _candidate(round_directory, worktree)
        except RunnerError as error:
            engineer_alias, engineer_session = recover_evidence(
                engineer_task,
                engineer_task.role,
                engineer_alias,
                engineer_session,
                engineer_batch_path,
                error,
                "commit tracked project changes and write both current Round Engineer reports with the fixed candidate commit",
            )
            candidate = _candidate(round_directory, worktree)
        state_alias, state_session, event = request_state(
            project, task, worktree, ticket_directory, traces,
            state_alias, state_session, leader_alias, engineer_batch_path,
            {
                "phase": "candidate", "ticket_id": task.ticket_id,
                "caused_by_event_ids": [predecessor],
                "evidence_refs": [_trace_ref(project, traces, engineer_alias)],
                "candidate": candidate,
            },
            "candidate",
        )
        predecessor = event["event_id"]

        sessions = {engineer_task.role: (engineer_task, engineer_alias, engineer_session, engineer_batch_path)}

        def correct_process() -> None:
            nonlocal state_alias, state_session, predecessor, leader_alias, leader_session
            (
                leader_alias,
                leader_session,
                state_alias,
                state_session,
                predecessor,
            ) = _process_corrections(
                project,
                task,
                worktree,
                ticket_directory,
                traces,
                round_directory,
                leader_alias,
                leader_session,
                state_alias,
                state_session,
                predecessor,
                registration,
                retained_batch,
                sessions,
                capacity_fd=capacity_fd,
            )

        next_formal_batch = partial(next_formal_batch, correct_process=correct_process)

        leader_alias, leader_session = run_agent(
            project, task, "team-leader", worktree, ticket_directory, traces,
            leader_alias, leader_session, registration, None, retained_batch,
            "Engineer completed:\n" + yaml.safe_dump(
                {"role": engineer_task.role, "alias": engineer_alias, "session": engineer_session,
                 "trace": _trace_ref(project, traces, engineer_alias)},
                sort_keys=False,
            ),
        )
        child_results = []
        remaining = {"standards-reviewer", "spec-reviewer"}
        while remaining:
            reviewer_batch, reviewer_batch_path, leader_alias, leader_session = next_formal_batch(
                project, task, definition, ticket_content, worktree, ticket_directory,
                traces, leader_alias, leader_session, registration, retained_batch,
            )
            if not {child.role for child in reviewer_batch.tasks} <= remaining:
                raise RunnerError("BATCH_SCHEMA_INVALID", "The child Batch must select remaining Review axes for this candidate.")
            try:
                reviewed = _run_batch_workers(
                    project, reviewer_batch, reviewer_batch_path, leader_alias, capacity_fd,
                )
            except RunnerError as error:
                if error.code != "insufficient-capacity":
                    raise
                leader_alias, leader_session = run_agent(
                    project, task, "team-leader", worktree, ticket_directory, traces,
                    leader_alias, leader_session, registration, None, retained_batch,
                    "Child Batch did not start:\n" + yaml.safe_dump(error.as_document()),
                )
                correct_process()
                if not registration.exists():
                    raise error
                continue
            for child, result in zip(reviewer_batch.tasks, reviewed.document["tasks"]):
                if "error" in result:
                    raise RunnerError(result["error"]["code"], result["error"]["message"])
                report_name = (
                    "standards.md" if child.role == "standards-reviewer" else "spec.md"
                )
                alias, session = result["alias"], result["session"]
                reviewer_task = replace(
                    child,
                    ticket_file=definition,
                    ticket_content=ticket_content,
                    report_file=Path(".state") / "reviews" / report_name,
                )
                sessions[child.role] = (
                    reviewer_task,
                    alias, session, reviewer_batch_path,
                )
                try:
                    _collect_review_report(
                        ticket_directory,
                        round_directory,
                        report_name,
                        session_directory=project.runner_directory / "sessions" / alias,
                    )
                except RunnerError as error:
                    alias, session = recover_evidence(
                        reviewer_task,
                        child.role,
                        alias,
                        session,
                        reviewer_batch_path,
                        error,
                        "write the exact current Round raw Review report",
                    )
                    sessions[child.role] = (
                        reviewer_task, alias, session, reviewer_batch_path,
                    )
                    _collect_review_report(
                        ticket_directory,
                        round_directory,
                        report_name,
                        session_directory=project.runner_directory / "sessions" / alias,
                    )
                member = "standards_reviewer" if child.role == "standards-reviewer" else "spec_reviewer"
                if first_round:
                    state_alias, state_session, event = request_state(
                        project, task, worktree, ticket_directory, traces,
                        state_alias, state_session, leader_alias, reviewer_batch_path,
                        {
                            "phase": "member", "ticket_id": task.ticket_id,
                            "caused_by_event_ids": [predecessor],
                            "evidence_refs": [_trace_ref(project, traces, alias)],
                            "member": member, "role": child.role, "session_ref": alias,
                        },
                        "member-" + member,
                    )
                    predecessor = event["event_id"]
                remaining.remove(child.role)
                child_results.append({"role": child.role, "alias": alias, "session": session,
                                      "trace": _trace_ref(project, traces, alias)})

            current_monitor = execution_budget_monitor(
                ticket_directory, task.ticket_id, task.ticket_name
            )
            if current_monitor is not None and current_monitor.is_stopped():
                leader_alias, leader_session = run_agent(
                    project, task, "team-leader", worktree, ticket_directory,
                    traces, leader_alias, leader_session, registration, None,
                    retained_batch,
                    "Execution stopped while Reviewers were running. Their completed "
                    "reports were collected. Freeze the scene and report remaining work; "
                    "do not dispatch another Reviewer or decide acceptance.",
                    reports_only=True,
                )
                return {
                    "ticket_id": requested.ticket_id,
                    "ticket_name": requested.ticket_name,
                    "role": "team-leader",
                    "launch_status": "stopped",
                    "worktree_path": str(worktree),
                    "alias": leader_alias,
                    "session": leader_session,
                }

            leader_alias, leader_session = run_agent(
                project, task, "team-leader", worktree, ticket_directory, traces,
                leader_alias, leader_session, registration, None, retained_batch,
                "Reviewers completed:\n" + yaml.safe_dump(child_results, sort_keys=False),
            )
        _, _, leader_alias, leader_session = next_formal_batch(
            project, task, definition, ticket_content, worktree, ticket_directory,
            traces, leader_alias, leader_session, registration, retained_batch,
            allow_no_formal=True,
        )
        try:
            candidate = _validate_round(round_directory, worktree)
        except RunnerError as error:
            leader_alias, leader_session = recover_evidence(
                task,
                "team-leader",
                leader_alias,
                leader_session,
                retained_batch,
                error,
                "write the current Round Leader decision for the fixed candidate",
            )
            candidate = _validate_round(round_directory, worktree)
        decision = _leader_decision(round_directory / "leader.md")
        if decision == "rejected" and confirmed_rework(round_directory / "leader.md"):
            decision = "implementation-rejected"
        evidence = [
            path.relative_to(project.harness_root).as_posix()
            for path in sorted(round_directory.iterdir())
        ]
        state_alias, state_session, event = request_state(
            project, task, worktree, ticket_directory, traces,
            state_alias, state_session, leader_alias, retained_batch,
            {
                "phase": "final", "ticket_id": task.ticket_id,
                "caused_by_event_ids": [predecessor], "evidence_refs": evidence,
                "candidate": candidate, "decision": decision,
            },
            "final",
        )
        if decision != "implementation-rejected":
            break
        state_alias, state_session, event = request_state(
            project, task, worktree, ticket_directory, traces,
            state_alias, state_session, leader_alias, retained_batch,
            {
                "phase": "rework", "ticket_id": task.ticket_id,
                "caused_by_event_ids": [event["event_id"]], "evidence_refs": evidence,
            },
            "rework",
        )
        predecessor = event["event_id"]
        monitor = execution_budget_monitor(
            ticket_directory, task.ticket_id, task.ticket_name
        )
        if monitor is not None:
            monitor.record_correction(engineer_task.role)
        first_round = False
        round_directory = round_directory.parent / str(int(round_directory.name) + 1)
        leader_alias, leader_session = run_agent(
            project, task, "team-leader", worktree, ticket_directory, traces,
            leader_alias, leader_session, registration, None, retained_batch,
            "The confirmed implementation rejection is closed. Dispatch the same Engineer "
            "and tier for the small correction in the new Round.\n",
        )
        engineer_batch, engineer_batch_path, leader_alias, leader_session = next_formal_batch(
            project, task, definition, ticket_content, worktree, ticket_directory,
            traces, leader_alias, leader_session, registration, retained_batch,
        )
        if len(engineer_batch.tasks) != 1 or engineer_batch.tasks[0].role != engineer_task.role:
            raise RunnerError("BATCH_SCHEMA_INVALID", "Rework must retain the Engineer and tier; a changed seat requires a separate evidence-based decision.")
        engineer_task = replace(
            engineer_batch.tasks[0], ticket_file=definition.resolve(), ticket_content=ticket_content,
        )
    return {
        "ticket_id": requested.ticket_id,
        "ticket_name": requested.ticket_name,
        "role": "team-leader",
        "launch_status": "accepted" if decision == "accepted" else "not-accepted",
        "worktree_path": str(worktree),
        "alias": leader_alias,
        "session": leader_session,
    }


def _resume_active_ticket(
    project: Any,
    requested: Task,
    capacity_fd: int,
    ticket_directory: Path,
    state: dict[str, Any],
    definition: Path,
    ticket_content: str,
    team: dict[str, Any],
) -> dict[str, Any]:
    """Continue the current Team from retained member Sessions and evidence."""
    if state.get("status") not in {"implementing", "reviewing", "reworking"}:
        raise RunnerError("TICKET_ALREADY_ACTIVE", "The active Ticket cannot continue its current Team step.")
    generation = state["active_team_ordinal"]
    worktree = project.harness_root / state["worktree"]
    traces = ticket_directory / "teams" / str(generation) / "traces"
    round_directory = traces.parent / "rounds" / str(team["current_round"])
    task = replace(requested, ticket_file=definition.resolve(), ticket_content=ticket_content)

    def member_session(role: str, alias: str | None) -> tuple[str, str, dict[str, Any]]:
        candidates = [alias] if alias else [
            path.parent.name
            for path in (project.runner_directory / "sessions").glob("*/mapping.yml")
        ]
        matched = []
        for candidate in candidates:
            if candidate is None:
                continue
            try:
                mapping, _ = read_alias_mapping(project.runner_directory, candidate)
            except RunnerError:
                continue
            if (
                mapping["ticket_id"] == task.ticket_id
                and mapping["team_generation"] == generation
                and mapping["role"] == role
            ):
                matched.append((candidate, mapping["session"], mapping))
        if len(matched) != 1:
            raise RunnerError(
                "RUNTIME_WORKER_FAILED",
                "The interrupted {0} Session is unavailable; return the retained evidence to the caller or superior.".format(role),
            )
        return matched[0]

    leader_alias, leader_session, leader_mapping = member_session(
        "team-leader", team["members"]["team_leader"]["session_ref"]
    )
    team_batch = Path(leader_mapping["retained_batch_file"])
    engineer_role = team["members"]["engineer"]["role"]

    def has_member_mapping(role: str) -> bool:
        for path in (project.runner_directory / "sessions").glob("*/mapping.yml"):
            try:
                mapping, _ = read_alias_mapping(
                    project.runner_directory, path.parent.name
                )
            except RunnerError:
                continue
            if (
                mapping["ticket_id"] == task.ticket_id
                and mapping["team_generation"] == generation
                and mapping["role"] == role
            ):
                return True
        return False

    def session_task(
        role: str, mapping: dict[str, Any]
    ) -> tuple[Task, Path]:
        retained = Path(mapping["retained_batch_file"])
        try:
            child = next(
                child
                for child in read_batch(retained, worktree).tasks
                if child.ticket_id == task.ticket_id and child.role == role
            )
        except (RunnerError, StopIteration) as error:
            raise RunnerError(
                "BATCH_SCHEMA_INVALID",
                "The interrupted Team member has no retained child Batch.",
            ) from error
        report_file = (
            _review_report_file(role, mapping)
            if role in _REVIEWER_ROLES else child.report_file
        )
        return (
            replace(
                child,
                ticket_file=definition.resolve(),
                ticket_content=ticket_content,
                report_file=report_file,
            ),
            retained,
        )

    try:
        engineer_alias, engineer_session, engineer_mapping = member_session(
            engineer_role, team["members"]["engineer"]["session_ref"]
        )
    except RunnerError:
        if (
            team["members"]["engineer"]["session_ref"] is not None
            or has_member_mapping(engineer_role)
        ):
            raise
        registration = (
            project.runner_directory / "sessions" / leader_alias
            / "child-registration.yml"
        )
        engineer_batch, engineer_batch_path, leader_alias, leader_session = (
            _next_formal_batch(
                project, task, definition, ticket_content, worktree,
                ticket_directory, traces, leader_alias, leader_session,
                registration, team_batch, capacity_fd=capacity_fd,
            )
        )
        assert engineer_batch is not None and engineer_batch_path is not None
        if (
            len(engineer_batch.tasks) != 1
            or engineer_batch.tasks[0].role != engineer_role
        ):
            raise RunnerError(
                "BATCH_SCHEMA_INVALID",
                "The interrupted Team Engineer must retain its registered role.",
            )
        engineer_task = replace(
            engineer_batch.tasks[0],
            ticket_file=definition.resolve(),
            ticket_content=ticket_content,
        )
        try:
            engineer_alias, engineer_session = _run_agent(
                project, engineer_task, engineer_role, worktree, ticket_directory,
                traces, None, None, None, leader_alias, engineer_batch_path,
                capacity_fd=capacity_fd,
            )
        except RunnerError as error:
            if error.code != "EXECUTION_BUDGET_STOPPED":
                raise
            return _wrap_up_budget_stop(
                project, requested, task, engineer_task, worktree,
                ticket_directory, traces, None, engineer_batch_path,
                leader_alias, leader_session, registration, team_batch,
                capacity_fd,
            )
    else:
        engineer_task, engineer_batch_path = session_task(
            engineer_role, engineer_mapping
        )
    sessions = {
        engineer_role: (
            engineer_task, engineer_alias, engineer_session, engineer_batch_path
        )
    }
    try:
        state_alias, state_session, _ = member_session("delivery-state", None)
    except RunnerError:
        state_alias = state_session = None

    if state.get("status") == "reworking":
        predecessor = next(
            event["event_id"]
            for event in reversed(read_worldline(project.state_directory, project.harness_root))
            if event.get("ticket_id") == task.ticket_id
        )
        evidence = [
            path.relative_to(project.harness_root).as_posix()
            for path in sorted(round_directory.iterdir())
        ]
        state_alias, state_session, event = _request_state(
            project, task, worktree, ticket_directory, traces,
            state_alias, state_session, leader_alias, team_batch,
            {
                "phase": "rework", "ticket_id": task.ticket_id,
                "caused_by_event_ids": [predecessor], "evidence_refs": evidence,
            },
            "rework-recovery",
            capacity_fd=capacity_fd,
        )
        predecessor = event["event_id"]
        monitor = execution_budget_monitor(
            ticket_directory, task.ticket_id, task.ticket_name
        )
        if monitor is not None:
            monitor.record_correction(engineer_role)
        round_directory = round_directory.parent / str(
            int(round_directory.name) + 1
        )
        registration = (
            project.runner_directory / "sessions" / leader_alias
            / "child-registration.yml"
        )
        leader_alias, leader_session = _run_agent(
            project, task, "team-leader", worktree, ticket_directory, traces,
            leader_alias, leader_session, registration, None, team_batch,
            "The confirmed implementation rejection is closed. Dispatch the same "
            "Engineer and tier for the small correction in the new Round.\n",
            capacity_fd=capacity_fd,
        )
        engineer_batch, engineer_batch_path, leader_alias, leader_session = (
            _next_formal_batch(
                project, task, definition, ticket_content, worktree,
                ticket_directory, traces, leader_alias, leader_session,
                registration, team_batch, capacity_fd=capacity_fd,
            )
        )
        assert engineer_batch is not None and engineer_batch_path is not None
        if (
            len(engineer_batch.tasks) != 1
            or engineer_batch.tasks[0].role != engineer_role
        ):
            raise RunnerError(
                "BATCH_SCHEMA_INVALID",
                "Rework must retain the Engineer and tier; a changed seat requires "
                "a separate evidence-based decision.",
            )
        engineer_task = replace(
            engineer_batch.tasks[0],
            ticket_file=definition.resolve(),
            ticket_content=ticket_content,
        )
        try:
            engineer_alias, engineer_session = _run_agent(
                project, engineer_task, engineer_role, worktree, ticket_directory,
                traces, engineer_alias, engineer_session, None, leader_alias,
                engineer_batch_path, capacity_fd=capacity_fd,
            )
        except RunnerError as error:
            if error.code != "EXECUTION_BUDGET_STOPPED":
                raise
            return _wrap_up_budget_stop(
                project, requested, task, engineer_task, worktree,
                ticket_directory, traces, engineer_alias, engineer_batch_path,
                leader_alias, leader_session, registration, team_batch,
                capacity_fd,
            )
        try:
            candidate = _candidate(round_directory, worktree)
        except RunnerError as error:
            if error.code != _AGENT_EVIDENCE_ERROR:
                raise
            engineer_alias, engineer_session = _run_agent(
                project, engineer_task, engineer_role, worktree,
                ticket_directory, traces, engineer_alias, engineer_session,
                None, leader_alias, engineer_batch_path,
                _evidence_recovery_prompt(
                    project, engineer_task, traces, engineer_alias, worktree,
                    error,
                    "commit tracked project changes and write both current Round "
                    "Engineer reports with the fixed candidate commit",
                ),
                capacity_fd=capacity_fd,
            )
            candidate = _candidate(round_directory, worktree)
        state_alias, state_session, _ = _request_state(
            project, task, worktree, ticket_directory, traces,
            state_alias, state_session, leader_alias, engineer_batch_path,
            {
                "phase": "candidate", "ticket_id": task.ticket_id,
                "caused_by_event_ids": [predecessor],
                "evidence_refs": [_trace_ref(project, traces, engineer_alias)],
                "candidate": candidate,
            },
            "candidate-rework-recovery",
            capacity_fd=capacity_fd,
        )
        return _resume_active_ticket(
            project,
            requested,
            capacity_fd,
            ticket_directory,
            yaml.safe_load((ticket_directory / "ticket.yml").read_text()),
            definition,
            ticket_content,
            yaml.safe_load((traces.parent / "team.yml").read_text()),
        )

    try:
        candidate = _candidate(round_directory, worktree)
    except RunnerError as error:
        outcome = read_terminal_outcome(
            project.runner_directory / "sessions" / engineer_alias / "execution.yml"
        )
        if error.code != _AGENT_EVIDENCE_ERROR or outcome != "completed":
            raise RunnerError(
                error.code,
                "{0} Expected result: retry the interrupted {1} Session with its retained Trace.".format(
                    error.message, engineer_role
                ),
            ) from error
        engineer_alias, engineer_session = _run_agent(
            project, engineer_task, engineer_role, worktree, ticket_directory,
            traces, engineer_alias, engineer_session, None, leader_alias,
            engineer_batch_path,
            _evidence_recovery_prompt(
                project, engineer_task, traces, engineer_alias, worktree, error,
                "commit tracked project changes and write both current Round Engineer reports "
                "with the fixed candidate commit",
            ),
            capacity_fd=capacity_fd,
        )
        candidate = _candidate(round_directory, worktree)

    predecessor = next(
        event["event_id"]
        for event in reversed(read_worldline(project.state_directory, project.harness_root))
        if event.get("ticket_id") == task.ticket_id
    )
    if team["members"]["engineer"]["session_ref"] is None:
        state_alias, state_session, event = _request_state(
            project, task, worktree, ticket_directory, traces,
            state_alias, state_session, leader_alias, team_batch,
            {
                "phase": "member",
                "ticket_id": task.ticket_id,
                "caused_by_event_ids": [predecessor],
                "evidence_refs": [_trace_ref(project, traces, engineer_alias)],
                "member": "engineer",
                "role": engineer_role,
                "session_ref": engineer_alias,
            },
            "member-engineer-recovery",
            capacity_fd=capacity_fd,
        )
        predecessor = event["event_id"]
        team["members"]["engineer"]["session_ref"] = engineer_alias
    if state.get("current_candidate") != candidate:
        state_alias, state_session, event = _request_state(
            project, task, worktree, ticket_directory, traces,
            state_alias, state_session, leader_alias, team_batch,
            {
                "phase": "candidate",
                "ticket_id": task.ticket_id,
                "caused_by_event_ids": [predecessor],
                "evidence_refs": [_trace_ref(project, traces, engineer_alias)],
                "candidate": candidate,
            },
            "candidate-recovery",
            capacity_fd=capacity_fd,
        )
        predecessor = event["event_id"]
        state["current_candidate"] = candidate

    registration = project.runner_directory / "sessions" / leader_alias / "child-registration.yml"
    remaining = set()
    reviewer_results = []
    for role, report_name, seat in (
        ("standards-reviewer", "standards.md", "standards_reviewer"),
        ("spec-reviewer", "spec.md", "spec_reviewer"),
    ):
        target = round_directory / report_name
        try:
            alias, session, mapping = member_session(
                role, team["members"][seat]["session_ref"]
            )
        except RunnerError:
            if target.is_file():
                raise
            remaining.add(role)
            continue
        report_file = _review_report_file(role, mapping)
        reviewer_task, reviewer_batch_path = session_task(role, mapping)
        sessions[role] = (reviewer_task, alias, session, reviewer_batch_path)
        source = ticket_directory / "reviews" / report_file.name
        # An interrupted correction can leave old copies beside newly delivered work.
        for report in (target, source):
            if report.is_file():
                declared = [
                    line.removeprefix("Candidate commit:").strip()
                    for line in report.read_text(encoding="utf-8").splitlines()
                    if line.startswith("Candidate commit:")
                ]
                if declared != [candidate]:
                    report.unlink()
        if not target.is_file() and not source.is_file():
            remaining.add(role)
            continue
        if not target.is_file():
            _collect_review_report(
                ticket_directory,
                round_directory,
                report_file.name,
                report_name,
                project.runner_directory / "sessions" / alias,
            )
        if team["members"][seat]["session_ref"] is None:
            state_alias, state_session, event = _request_state(
                project, task, worktree, ticket_directory, traces,
                state_alias, state_session, leader_alias, reviewer_batch_path,
                {
                    "phase": "member",
                    "ticket_id": task.ticket_id,
                    "caused_by_event_ids": [predecessor],
                    "evidence_refs": [_trace_ref(project, traces, alias)],
                    "member": seat,
                    "role": role,
                    "session_ref": alias,
                },
                "member-" + seat + "-recovery",
                capacity_fd=capacity_fd,
            )
            predecessor = event["event_id"]
            team["members"][seat]["session_ref"] = alias
        remaining.discard(role)
        reviewer_results.append(
            {"role": role, "alias": alias, "session": session,
             "trace": _trace_ref(project, traces, alias)}
        )

    def correct_process() -> bool:
        """Correct retained members and report whether every Review is present."""
        nonlocal leader_alias, leader_session, state_alias, state_session, predecessor
        (
            leader_alias,
            leader_session,
            state_alias,
            state_session,
            predecessor,
        ) = _process_corrections(
            project,
            task,
            worktree,
            ticket_directory,
            traces,
            round_directory,
            leader_alias,
            leader_session,
            state_alias,
            state_session,
            predecessor,
            registration,
            team_batch,
            sessions,
            capacity_fd=capacity_fd,
        )
        remaining.difference_update(
            role for role in sessions
            if role in _REVIEWER_ROLES
            and (round_directory / _review_report_name(role)).is_file()
        )
        return not remaining

    correct_process()
    reviewers_dispatched = bool(remaining)
    if remaining and not registration.exists():
        leader_alias, leader_session = _run_agent(
            project, task, "team-leader", worktree, ticket_directory, traces,
            leader_alias, leader_session, registration, None, team_batch,
            "Engineer completed:\n" + yaml.safe_dump(
                {
                    "role": engineer_role,
                    "alias": engineer_alias,
                    "session": engineer_session,
                    "trace": _trace_ref(project, traces, engineer_alias),
                    "completed_reviews": reviewer_results,
                },
                sort_keys=False,
            ),
            capacity_fd=capacity_fd,
        )
    while remaining:
        reviewer_batch, reviewer_batch_path, leader_alias, leader_session = _next_formal_batch(
            project, task, definition, ticket_content, worktree, ticket_directory,
            traces, leader_alias, leader_session, registration, team_batch,
            capacity_fd=capacity_fd, correct_process=correct_process,
        )
        if reviewer_batch is None:
            break
        assert reviewer_batch_path is not None
        if not {child.role for child in reviewer_batch.tasks} <= remaining:
            raise RunnerError("BATCH_SCHEMA_INVALID", "The child Batch must select remaining Review axes for this candidate.")
        reviewed = _run_batch_workers(
            project, reviewer_batch, reviewer_batch_path, leader_alias, capacity_fd,
            recover_reports=True,
        )
        for child, result in zip(reviewer_batch.tasks, reviewed.document["tasks"]):
            if "error" in result:
                raise RunnerError(result["error"]["code"], result["error"]["message"])
            report_name = "standards.md" if child.role == "standards-reviewer" else "spec.md"
            alias, session = result["alias"], result["session"]
            mapping, _ = read_alias_mapping(project.runner_directory, alias)
            report_file = _review_report_file(child.role, mapping)
            reviewer_task = replace(
                child,
                ticket_file=definition.resolve(),
                ticket_content=ticket_content,
                report_file=report_file,
            )
            collect_report = partial(
                _collect_review_report,
                ticket_directory,
                round_directory,
                report_file.name,
                report_name,
                session_directory=project.runner_directory / "sessions" / alias,
            )
            try:
                collect_report()
            except RunnerError as error:
                if error.code != _AGENT_EVIDENCE_ERROR:
                    raise
                alias, session = _run_agent(
                    project, reviewer_task, child.role, worktree,
                    ticket_directory, traces, alias, session, None,
                    leader_alias, reviewer_batch_path,
                    _evidence_recovery_prompt(
                        project, reviewer_task, traces, alias, worktree, error,
                        "deliver the exact current Round raw Review report from retained work",
                    ),
                    capacity_fd=capacity_fd,
                )
                collect_report()
            sessions[child.role] = (
                reviewer_task, alias, session, reviewer_batch_path
            )
            seat = "standards_reviewer" if child.role == "standards-reviewer" else "spec_reviewer"
            if team["members"][seat]["session_ref"] is None:
                state_alias, state_session, event = _request_state(
                    project, task, worktree, ticket_directory, traces,
                    state_alias, state_session, leader_alias, reviewer_batch_path,
                    {
                        "phase": "member",
                        "ticket_id": task.ticket_id,
                        "caused_by_event_ids": [predecessor],
                        "evidence_refs": [_trace_ref(project, traces, alias)],
                        "member": seat,
                        "role": child.role,
                        "session_ref": alias,
                    },
                    "member-" + seat + "-recovery",
                    capacity_fd=capacity_fd,
                )
                predecessor = event["event_id"]
                team["members"][seat]["session_ref"] = alias
            remaining.remove(child.role)
            reviewer_results.append(
                {"role": child.role, "alias": alias, "session": session,
                 "trace": _trace_ref(project, traces, alias)}
            )

        current_monitor = execution_budget_monitor(
            ticket_directory, task.ticket_id, task.ticket_name
        )
        if current_monitor is not None and current_monitor.is_stopped():
            leader_alias, leader_session = _run_agent(
                project, task, "team-leader", worktree, ticket_directory,
                traces, leader_alias, leader_session, registration, None,
                team_batch,
                "Execution stopped while Reviewers were running. Their completed "
                "reports were collected. Freeze the scene and report remaining work; "
                "do not dispatch another Reviewer or decide acceptance.",
                capacity_fd=capacity_fd,
                reports_only=True,
            )
            return {
                "ticket_id": requested.ticket_id,
                "ticket_name": requested.ticket_name,
                "role": "team-leader",
                "launch_status": "stopped",
                "worktree_path": str(worktree),
                "alias": leader_alias,
                "session": leader_session,
            }

        leader_alias, leader_session = _run_agent(
            project, task, "team-leader", worktree, ticket_directory, traces,
            leader_alias, leader_session, registration, None, team_batch,
            "Reviewers completed:\n" + yaml.safe_dump(reviewer_results, sort_keys=False),
            capacity_fd=capacity_fd,
        )
    if not reviewers_dispatched and reviewer_results:
        leader_alias, leader_session = _run_agent(
            project, task, "team-leader", worktree, ticket_directory, traces,
            leader_alias, leader_session, registration, None, team_batch,
            "Reviewers completed:\n" + yaml.safe_dump(reviewer_results, sort_keys=False),
            capacity_fd=capacity_fd,
        )
    correct_process()
    _, _, leader_alias, leader_session = _next_formal_batch(
        project, task, definition, ticket_content, worktree, ticket_directory,
        traces, leader_alias, leader_session, registration, team_batch,
        capacity_fd=capacity_fd, allow_no_formal=True,
    )
    try:
        candidate = _validate_round(round_directory, worktree)
    except RunnerError as error:
        if error.code != _AGENT_EVIDENCE_ERROR:
            raise
        leader_alias, leader_session = _run_agent(
            project, task, "team-leader", worktree, ticket_directory, traces,
            leader_alias, leader_session, registration, None, team_batch,
            _evidence_recovery_prompt(
                project, task, traces, leader_alias, worktree, error,
                "write the current Round Leader decision for the fixed candidate",
            ),
            capacity_fd=capacity_fd,
        )
        candidate = _validate_round(round_directory, worktree)
    decision = _leader_decision(round_directory / "leader.md")
    if decision == "rejected" and confirmed_rework(round_directory / "leader.md"):
        decision = "implementation-rejected"
    evidence = [
        path.relative_to(project.harness_root).as_posix()
        for path in sorted(round_directory.iterdir())
    ]
    state_alias, state_session, event = _request_state(
        project, task, worktree, ticket_directory, traces,
        state_alias, state_session, leader_alias, team_batch,
        {
            "phase": "final",
            "ticket_id": task.ticket_id,
            "caused_by_event_ids": [predecessor],
            "evidence_refs": evidence,
            "candidate": candidate,
            "decision": decision,
        },
        "final-recovery",
        capacity_fd=capacity_fd,
    )
    if decision == "implementation-rejected":
        return _resume_active_ticket(
            project,
            requested,
            capacity_fd,
            ticket_directory,
            yaml.safe_load((ticket_directory / "ticket.yml").read_text()),
            definition,
            ticket_content,
            yaml.safe_load((traces.parent / "team.yml").read_text()),
        )
    return {
        "ticket_id": requested.ticket_id,
        "ticket_name": requested.ticket_name,
        "role": "team-leader",
        "launch_status": "accepted" if decision == "accepted" else "not-accepted",
        "worktree_path": str(worktree),
        "alias": leader_alias,
        "session": leader_session,
    }


def _registered_batch(registration: Path, worktree: Path) -> tuple[Batch, Path]:
    if not registration.is_file():
        raise RunnerError("BATCH_SCHEMA_INVALID", "The Team Leader did not register its required direct child Batch.")
    document = yaml.safe_load(registration.read_text(encoding="utf-8"))
    registration.unlink()
    retained = Path(document["retained_batch_file"])
    return read_batch(retained, worktree), retained


def _next_formal_batch(
    project: Any,
    task: Task,
    definition: Path,
    ticket_content: str,
    worktree: Path,
    ticket_directory: Path,
    traces: Path,
    leader_alias: str,
    leader_session: str,
    registration: Path,
    retained_batch: Path,
    *,
    capacity_fd: int,
    allow_no_formal: bool = False,
    correct_process: Callable[[], bool | None] | None = None,
) -> tuple[Batch | None, Path | None, str, str]:
    """Return the next Batch unless correction completes all remaining work.

    The correction callback may return True when no formal child is needed.
    """

    run_agent = partial(_run_agent, capacity_fd=capacity_fd)
    recovered_dispatch = False

    def recover_dispatch(error: RunnerError) -> None:
        nonlocal leader_alias, leader_session, recovered_dispatch
        if error.code != "BATCH_SCHEMA_INVALID" or recovered_dispatch:
            raise error
        recovered_dispatch = True
        leader_alias, leader_session = run_agent(
            project,
            task,
            "team-leader",
            worktree,
            ticket_directory,
            traces,
            leader_alias,
            leader_session,
            registration,
            None,
            retained_batch,
            _evidence_recovery_prompt(
                project,
                task,
                traces,
                leader_alias,
                worktree,
                error,
                "finish without another child Batch" if allow_no_formal else "register the required valid child Batch",
            ),
        )

    while True:
        corrected_all = correct_process() if correct_process is not None else False
        if not registration.exists():
            if allow_no_formal or corrected_all:
                return None, None, leader_alias, leader_session
            recover_dispatch(
                RunnerError(
                    "BATCH_SCHEMA_INVALID",
                    "The Team Leader did not register its required direct child Batch.",
                )
            )
            continue
        try:
            batch, batch_path = _registered_batch(registration, worktree)
        except RunnerError as error:
            recover_dispatch(error)
            continue
        if len(batch.tasks) != 1 or not _is_inline_specialist(batch.tasks[0]):
            if allow_no_formal:
                recover_dispatch(
                    RunnerError(
                        "BATCH_SCHEMA_INVALID",
                        "The completed Team Round cannot register another child Batch.",
                    )
                )
                continue
            return batch, batch_path, leader_alias, leader_session
        specialist = replace(
            batch.tasks[0],
            ticket_file=definition.resolve(),
            ticket_content=ticket_content,
        )
        alias, session = run_agent(
            project,
            specialist,
            specialist.role,
            worktree,
            ticket_directory,
            traces,
            None,
            None,
            None,
            leader_alias,
            batch_path,
        )
        leader_alias, leader_session = run_agent(
            project,
            task,
            "team-leader",
            worktree,
            ticket_directory,
            traces,
            leader_alias,
            leader_session,
            registration,
            None,
            retained_batch,
            "Specialist completed:\n"
            + yaml.safe_dump(
                {"role": specialist.role, "alias": alias, "session": session,
                 "trace": _trace_ref(project, traces, alias)},
                sort_keys=False,
            ),
        )


def _request_state(
    project: Any,
    task: Task,
    worktree: Path,
    evidence: Path,
    traces: Path,
    alias: str | None,
    session: str | None,
    parent_alias: str,
    retained_batch: Path,
    facts: dict[str, Any],
    request_name: str,
    *,
    capacity_fd: int | None = None,
) -> tuple[str, str, dict[str, Any]]:
    state_alias = alias or "{0}-{1}@d1".format(task.ticket_id, task.ticket_name)
    runtime_request = worktree / ".scratch" / "delivery-state" / (request_name + ".yml")
    runtime_request.parent.mkdir(parents=True, exist_ok=True)
    environment = {
        "GRAPHTRAJ_STATE_FACTS": json.dumps(facts, separators=(",", ":")),
        "GRAPHTRAJ_STATE_REQUEST": str(runtime_request),
    }
    alias, session = _run_agent(
        project, task, "delivery-state", worktree, evidence, traces,
        alias, session, None, parent_alias, retained_batch,
        "Request the strict Delivery State change for these supplied facts:\n"
        + yaml.safe_dump(facts, sort_keys=False)
        + "\nWrite only that request to {0}.\n".format(runtime_request),
        capacity_fd=capacity_fd,
        task_environment=environment,
    )
    requests = project.runner_directory / "sessions" / alias / "requests"
    requests.mkdir(exist_ok=True)
    for attempt in range(2):
        failure = None
        request_file = _next_request_file(
            requests,
            request_name if not attempt else request_name + "-recovered",
        )
        if runtime_request.is_symlink() or not runtime_request.is_file():
            failure = RunnerError(
                _AGENT_EVIDENCE_ERROR,
                "Delivery State did not produce its requested state change.",
            )
        else:
            shutil.move(runtime_request, request_file)
            try:
                request = yaml.safe_load(request_file.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError):
                failure = RunnerError(
                    _AGENT_EVIDENCE_ERROR,
                    "Delivery State produced an invalid state change.",
                )
            else:
                if request != facts:
                    failure = RunnerError(
                        _AGENT_EVIDENCE_ERROR,
                        "Delivery State produced an invalid state change.",
                    )
                else:
                    try:
                        event = apply_delivery_state_request(
                            project.state_directory, project.harness_root,
                            request, facts,
                        )
                    except (OSError, ValueError) as error:
                        raise RunnerError(
                            _AGENT_EVIDENCE_ERROR,
                            "Delivery State could not apply its requested state change: "
                            + str(error),
                        ) from error
                    return alias, session, event
        assert failure is not None
        if attempt:
            raise failure
        alias, session = _run_agent(
            project,
            task,
            "delivery-state",
            worktree,
            evidence,
            traces,
            alias,
            session,
            None,
            parent_alias,
            retained_batch,
            _evidence_recovery_prompt(
                project,
                task,
                traces,
                alias,
                worktree,
                failure,
                "write exactly the supplied Delivery State request",
            ),
            capacity_fd=capacity_fd,
            task_environment=environment,
        )
    raise AssertionError("Delivery State recovery did not return")


def _next_request_file(directory: Path, name: str) -> Path:
    target = directory / (name + ".yml")
    suffix = 2
    while os.path.lexists(target):
        target = directory / (name + "-" + str(suffix) + ".yml")
        suffix += 1
    return target


def _trace_ref(project: Any, traces: Path, alias: str) -> str:
    return (traces / alias / "events.jsonl").relative_to(project.harness_root).as_posix()


def _evidence_recovery_prompt(
    project: Any,
    task: Task,
    traces: Path,
    alias: str,
    worktree: Path,
    error: RunnerError,
    expected: str,
) -> str:
    return (
        "Recovery required: correct your current Team step.\n"
        "Failure: {0}: {1}\n"
        "Evidence: {2}\n"
        "Expected result: {3}\n"
        "Current commit: {4}\n"
        "Preserve the accepted Ticket, current candidate, and valid completed evidence. "
        "Correct only this failed step; do not repeat completed Team work."
    ).format(
        error.code,
        error.message,
        _trace_ref(project, traces, alias),
        expected,
        run_git(worktree, "rev-parse", "HEAD"),
    )


def _process_corrections(
    project: Any,
    task: Task,
    worktree: Path,
    evidence: Path,
    traces: Path,
    round_directory: Path,
    leader_alias: str,
    leader_session: str,
    state_alias: str | None,
    state_session: str | None,
    predecessor: str,
    registration: Path,
    retained_batch: Path,
    sessions: dict[str, tuple[Task, str, str, Path]],
    *,
    capacity_fd: int,
) -> tuple[str, str, str | None, str | None, str]:
    """Apply supported Leader corrections without leaving the current Team."""
    leader_report = round_directory / "leader.md"
    # Consume the Leader's retained next action before an older judgment.
    while (
        not registration.exists()
        and leader_report.is_file()
        and "Decision: CORRECT" in leader_report.read_text().splitlines()
    ):
        judgment = leader_report.read_text(encoding="utf-8")
        fields = {}
        for name in ("Responsible", "Rule", "Reason"):
            values = [
                line[len(name) + 2:]
                for line in judgment.splitlines()
                if line.startswith(name + ": ")
            ]
            if len(values) != 1 or not values[0].strip():
                raise RunnerError(
                    "BATCH_SCHEMA_INVALID",
                    "Correction requires one responsible role, accepted rule, "
                    "and evidence-backed reason.",
                )
            fields[name] = values[0]
        role = ROLE_REFERENCES.get(fields["Responsible"], fields["Responsible"])
        if role not in sessions:
            raise RunnerError(
                "BATCH_SCHEMA_INVALID",
                "Correction must resume an existing member without registering "
                "a new Batch.",
            )
        child, alias, session, child_batch = sessions[role]
        state_alias, state_session, event = _request_state(
            project, task, worktree, evidence, traces,
            state_alias, state_session, leader_alias, retained_batch,
            {
                "phase": "correction", "ticket_id": task.ticket_id,
                "caused_by_event_ids": [predecessor],
                "evidence_refs": [
                    _trace_ref(project, traces, leader_alias),
                    _trace_ref(project, traces, alias),
                ],
                "responsible_role": role, "session_ref": alias,
            },
            "correction",
            capacity_fd=capacity_fd,
        )
        predecessor = event["event_id"]
        monitor = execution_budget_monitor(evidence, task.ticket_id, task.ticket_name)
        if monitor is not None:
            monitor.record_correction(role)
        previous_candidate = run_git(worktree, "rev-parse", "HEAD")
        affected = [role]
        leader_report.unlink()
        for affected_role in affected:
            member, _, _, _ = sessions[affected_role]
            names = (
                ("engineer.md", "validation.md")
                if _task_policy(member, affected_role) in _ENGINEER_ROLES
                else (_review_report_name(affected_role),)
            )
            for name in names:
                (round_directory / name).unlink(missing_ok=True)
        for affected_role in affected:
            member, alias, session, child_batch = sessions[affected_role]
            followup = (
                "Reflect on the Team Leader's judgment and correct your work "
                "against the accepted Ticket and review rules.\n" + judgment
                if affected_role == role else
                "Repeat your affected Review against the corrected fixed "
                "candidate and the accepted review rules.\n"
            )
            if affected_role == role:
                followup += "\n" + _evidence_recovery_prompt(
                    project, member, traces, alias, worktree,
                    RunnerError(_AGENT_EVIDENCE_ERROR, fields["Reason"]),
                    "deliver the corrected current Round report and reuse all still-valid work",
                )
            alias, session = _run_agent(
                project, member, affected_role, worktree, evidence, traces,
                alias, session, None, leader_alias, child_batch,
                followup + "\nCaused by Project Worldline event: " + predecessor,
                capacity_fd=capacity_fd,
            )
            sessions[affected_role] = (member, alias, session, child_batch)
            if _task_policy(member, affected_role) in _ENGINEER_ROLES:
                try:
                    candidate = _candidate(round_directory, worktree)
                except RunnerError as error:
                    if error.code != _AGENT_EVIDENCE_ERROR:
                        raise
                    alias, session = _run_agent(
                        project, member, affected_role, worktree, evidence, traces,
                        alias, session, None, leader_alias, child_batch,
                        _evidence_recovery_prompt(
                            project, member, traces, alias, worktree, error,
                            "commit tracked project changes and write both current Round Engineer reports "
                            "with the fixed candidate commit",
                        ),
                        capacity_fd=capacity_fd,
                    )
                    sessions[affected_role] = (member, alias, session, child_batch)
                    candidate = _candidate(round_directory, worktree)

                # Keep valid Review copies until the corrected candidate is known.
                # Only a changed candidate adds affected Reviews to this loop.
                if candidate != previous_candidate:
                    for review_role, (reviewer, _, _, _) in sessions.items():
                        if _task_policy(reviewer, review_role) in _REVIEWER_ROLES:
                            (round_directory / _review_report_name(review_role)).unlink(missing_ok=True)
                            affected.append(review_role)

                state_alias, state_session, event = _request_state(
                    project, task, worktree, evidence, traces,
                    state_alias, state_session, leader_alias, child_batch,
                    {
                        "phase": "candidate", "ticket_id": task.ticket_id,
                        "caused_by_event_ids": [predecessor],
                        "evidence_refs": [_trace_ref(project, traces, alias)],
                        "candidate": candidate,
                    },
                    "candidate",
                    capacity_fd=capacity_fd,
                )
                predecessor = event["event_id"]
            else:
                assert member.report_file is not None
                collect_report = partial(
                    _collect_review_report,
                    evidence,
                    round_directory,
                    member.report_file.name,
                    _review_report_name(affected_role),
                    project.runner_directory / "sessions" / alias,
                )
                try:
                    collect_report()
                except RunnerError as error:
                    if error.code != _AGENT_EVIDENCE_ERROR:
                        raise
                    alias, session = _run_agent(
                        project, member, affected_role, worktree, evidence, traces,
                        alias, session, None, leader_alias, child_batch,
                        _evidence_recovery_prompt(
                            project, member, traces, alias, worktree, error,
                            "deliver the exact current Round raw Review report from retained work",
                        ),
                        capacity_fd=capacity_fd,
                    )
                    sessions[affected_role] = (member, alias, session, child_batch)
                    collect_report()
        leader_alias, leader_session = _run_agent(
            project, task, "team-leader", worktree, evidence, traces,
            leader_alias, leader_session, registration, None, retained_batch,
            "Correction and affected Reviews completed in the same Team Round. "
            "Assess the current evidence.\n"
            + "Caused by Project Worldline event: " + predecessor,
            capacity_fd=capacity_fd,
        )
    return leader_alias, leader_session, state_alias, state_session, predecessor


def _current_runtime_diagnostic(
    session_directory: Path, stderr_offset: int, event_offset: int
) -> str:
    diagnostics = [_diagnostic_since(session_directory / "stderr.log", stderr_offset)]
    try:
        diagnostics.append(
            (session_directory / "worker-stderr.log").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError):
        pass
    try:
        with (session_directory / "events.jsonl").open("rb") as events:
            events.seek(event_offset)
            diagnostics.extend(_runtime_event_errors(events.read()))
    except OSError:
        pass
    return "\n".join(diagnostic for diagnostic in diagnostics if diagnostic)


def _diagnostic_since(path: Path, offset: int) -> str:
    try:
        with path.open("rb") as diagnostic:
            diagnostic.seek(offset)
            return diagnostic.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _runtime_event_errors(events: bytes) -> list[str]:
    errors = []
    for line in events.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type in {"error", "turn.failed"}:
            error = _runtime_error_text(event)
        else:
            item = event.get("item")
            if event_type == "event_msg" and isinstance(event.get("payload"), dict):
                item = event["payload"].get("item")
            error = (
                _runtime_error_text(item)
                if isinstance(item, dict)
                and (
                    item.get("type") in {"error", "tool_error", "Error", "ToolError"}
                    or (
                        item.get("type") in {"command_execution", "CommandExecution", "FileChange"}
                        and (
                            item.get("status") in {"failed", "error"}
                            or isinstance(item.get("error"), (dict, str))
                            or (
                                isinstance(item.get("exit_code"), int)
                                and item["exit_code"] != 0
                            )
                        )
                    )
                )
                else ""
            )
        if error:
            errors.append(error)
    return errors


def _runtime_error_text(event: dict[str, Any]) -> str:
    values = []
    for key in ("aggregated_output", "stderr", "stdout", "message", "detail"):
        value = event.get(key)
        if isinstance(value, str) and value:
            values.append(value)
    error = event.get("error")
    if isinstance(error, str) and error:
        values.append(error)
    elif isinstance(error, dict):
        values.extend(
            value
            for key in ("message", "detail")
            if isinstance(value := error.get(key), str) and value
        )
    return "\n".join(values)


def _runtime_access_failure(
    diagnostic: str, reports: tuple[Path, ...]
) -> bool:
    observed = diagnostic.lower()
    if any(
        marker in observed
        for marker in (
            "permission denied",
            "operation not permitted",
            "filesystem sandbox",
        )
    ):
        return True
    if (
        "writable root" in observed
        and "symlink" in observed
        and "not supported" in observed
    ):
        return True
    condition = "the report target is not authorized for this role"
    return condition in observed and any(
        "resolved={0}; condition={1}".format(
            report.resolve(strict=False), condition
        ) in diagnostic
        for report in reports
    )


def _runtime_command_parse_error(diagnostic: str) -> str | None:
    observed = diagnostic.lower()
    for marker in ("cannot verify ", "cannot parse "):
        index = observed.rfind(marker)
        if index >= 0:
            return diagnostic[index:].splitlines()[0].strip()
    return None


def _current_command_parse_error(session_directory: Path) -> str | None:
    try:
        lines = (session_directory / "events.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    except (OSError, UnicodeError):
        return None
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "runner-execution-start":
            return None
        if event.get("type") == "runtime-command-parse":
            message = event.get("message")
            return message if isinstance(message, str) else None
    return None


def _readiness_predecessor(project: Any, ticket_id: str) -> str:
    event = next(
        (
            item
            for item in reversed(
                read_worldline(project.state_directory, project.harness_root)
            )
            if item.get("ticket_id") == ticket_id
            and item.get("to_status") == "ready"
        ),
        None,
    )
    if event is None:
        raise RunnerError(
            "TICKET_FILE_INVALID",
            "The ready Ticket has no causal readiness event.",
        )
    return event["event_id"]


def _run_agent(
    project: Any,
    task: Task,
    role: str,
    worktree: Path,
    evidence: Path,
    traces: Path,
    alias: str | None,
    expected_session: str | None,
    registration: Path | None,
    parent_alias: str | None,
    retained_batch: Path,
    prompt: str | None = None,
    *,
    capacity_fd: int | None = None,
    retiring: bool = False,
    reports_only: bool = False,
    wait_for_completion: bool = True,
    task_environment: dict[str, str] | None = None,
) -> tuple[str, str]:
    team_file = traces.parent / "team.yml"
    if role != "delivery-state" and team_file.exists():
        team = yaml.safe_load(team_file.read_text())
        if team["status"] != "active" and not (retiring and role == "team-leader" and team["status"] == "retiring"):
            raise RunnerError("team-not-active", "The Team has stopped starting new work.")
    with capacity_positions(project, 1, capacity_fd) as positions:
        return _execute_agent(
            project, task, role, worktree, evidence, traces, alias,
            expected_session, registration, parent_alias, retained_batch, prompt,
            positions[0].fileno(), reports_only,
            wait_for_completion=wait_for_completion,
            task_environment=task_environment,
        )


def _wrap_up_budget_stop(
    project: Any,
    requested: Task,
    task: Task,
    engineer_task: Task,
    worktree: Path,
    evidence: Path,
    traces: Path,
    engineer_alias: str | None,
    engineer_batch: Path,
    leader_alias: str,
    leader_session: str,
    registration: Path,
    retained_batch: Path,
    capacity_fd: int,
) -> dict[str, Any]:
    if engineer_alias is None:
        engineer_alias = next(
            path.parent.name
            for path in (project.runner_directory / "sessions").glob("*/mapping.yml")
            if yaml.safe_load(path.read_text(encoding="utf-8")).get("role")
            == engineer_task.role
            and yaml.safe_load(path.read_text(encoding="utf-8")).get("ticket_id")
            == task.ticket_id
        )
    engineer_mapping = yaml.safe_load(
        (
            project.runner_directory / "sessions" / engineer_alias / "mapping.yml"
        ).read_text(encoding="utf-8")
    )
    engineer_alias, _ = _run_agent(
        project, engineer_task, engineer_task.role, worktree, evidence, traces,
        engineer_alias, engineer_mapping["session"], None, leader_alias,
        engineer_batch,
        "Report the stopped implementation, unfinished work, and current commit. "
        "Commit only authorized changes already made before stopping.",
        capacity_fd=capacity_fd,
        reports_only=True,
    )
    leader_alias, leader_session = _run_agent(
        project, task, "team-leader", worktree, evidence, traces, leader_alias,
        leader_session, registration, None, retained_batch,
        "Execution has stopped. Freeze the current scene and report the current "
        "result and remaining work. Do not dispatch or decide acceptance.",
        capacity_fd=capacity_fd,
        reports_only=True,
    )
    return {
        "ticket_id": requested.ticket_id,
        "ticket_name": requested.ticket_name,
        "role": "team-leader",
        "launch_status": "stopped",
        "worktree_path": str(worktree),
        "alias": leader_alias,
        "session": leader_session,
    }


def _execute_agent(
    project: Any,
    task: Task,
    role: str,
    worktree: Path,
    evidence: Path,
    traces: Path,
    alias: str | None,
    expected_session: str | None,
    registration: Path | None,
    parent_alias: str | None,
    retained_batch: Path,
    prompt: str | None,
    capacity_fd: int,
    reports_only: bool = False,
    input_delivered: threading.Event | None = None,
    wait_for_completion: bool = True,
    task_environment: dict[str, str] | None = None,
) -> tuple[str, str]:
    generation = int(traces.parent.name) if traces.parent.name.isdigit() else 1
    if alias is None:
        alias = _agent_alias(project, task, role, generation)
        session_directory = project.runner_directory / "sessions" / alias
        session_directory.mkdir(parents=True, exist_ok=False)
        trace_directory = traces / alias
        trace_directory.mkdir()
        trace = trace_directory / "events.jsonl"
        trace.touch()
        os.link(trace, session_directory / "events.jsonl")
    else:
        session_directory = project.runner_directory / "sessions" / alias
        if not session_directory.is_dir():
            raise RunnerError("RUNTIME_WORKER_FAILED", "The mapped Session is unavailable.")

    policy_role = _task_policy(task, role)
    monitor = (
        None
        if reports_only
        else execution_budget_monitor(evidence, task.ticket_id, task.ticket_name)
    )
    budget_stage = execution_budget_stage(role)
    team_file = traces.parent / "team.yml"
    ordinal = yaml.safe_load(team_file.read_text())["current_round"] if team_file.exists() else 1
    report_files = _role_report_files(task, policy_role, role, generation, ordinal)
    if expected_session is None:
        preset = (
            resolved_role_preset(task, project.role_bindings)
            if task.inline_preset is not None and task.role == role
            else project.role_bindings[role]
        )
        context = preflight_runtime_context(
            runtime_store=project.runtime_store,
            executable=runtime_executable(preset.runtime),
            git_common_directory=project.common_directory,
            role=resolve_child_role(policy_role, preset),
            worktree=worktree,
            evidence=evidence,
            repository_skill_source=worktree,
            requested_skills=task.requested_skills if policy_role in _ENGINEER_ROLES else (),
            report_files=report_files,
            child_batch_write_paths=(registration, project.state_directory / "batches")
            if policy_role == "team-leader" and registration is not None else (),
        ).finalize()
        launch_file = session_directory / "launch.yml"
        write_yaml_durably(
            launch_file,
            {
                **context.launch_document(),
                "context_evidence": context.evidence_document(),
                "operation": "launch",
                "mapping": {
                    "alias": alias,
                    "runtime": context.runtime,
                    "ticket_id": task.ticket_id,
                    "team_generation": generation,
                    "role": role,
                    "parent": parent_alias,
                    "retained_batch_file": str(retained_batch),
                    "worktree_path": str(worktree),
                    "trace_file": str(session_directory / "events.jsonl"),
                    "report_file": (
                        task.report_file.as_posix()
                        if task.report_file is not None else None
                    ),
                },
            },
        )
        job_file = launch_file
        runtime_environment = context.runtime_environment()
    else:
        job_file, runtime_environment = _resume_job(
            session_directory, expected_session, role, worktree, evidence, report_files,
            reports_only=reports_only,
        )

    task_prompt = prompt or task.ticket_content
    if task.instruction:
        task_prompt += "\n## Additional instruction\n\n" + task.instruction + "\n"
    round_directory = traces.parent / "rounds" / str(ordinal)
    if reports_only:
        task_prompt += (
            "\nThis continuation has read-only Worktree access. New implementation "
            "and dispatch are prohibited. Use only the exact report paths and Git "
            "metadata already authorized by Runner.\n"
        )
    elif policy_role in _ENGINEER_ROLES and round_directory.stat().st_mode & 0o200:
        task_prompt += (
            "\nWrite the fixed candidate and self-review to "
            f".state/teams/{generation}/rounds/{ordinal}/engineer.md and its test results to "
            f".state/teams/{generation}/rounds/{ordinal}/validation.md. Include the candidate commit in both.\n"
        )
        if ordinal > 1:
            task_prompt += (
                f"Read the confirmed diagnosis and both Review reports in .state/teams/{generation}/rounds/{ordinal - 1}/. "
                "Implement only that correction and preserve the closed Round evidence.\n"
            )
    elif role == "team-leader" and not os.environ.get("GRAPHTRAJ_RETIRING"):
        task_prompt += (
            f"\nCurrent Team generation: {generation}. Write the decision to .state/teams/{generation}/rounds/{ordinal}/leader.md. "
            "Only a compliant implementation rejection may request rework: include exact lines "
            "Decision: REJECT, Diagnosis: implementation, Reviews: compliant, Action: rework "
            "and a nonempty Rationale: explaining the evidence and correction. "
            "Process corrections, Main decomposition/scope errors, and user product/Spec changes "
            "cannot authorize implementation rework. Keep a small correction with the same Engineer "
            "and tier; never replace or escalate from a failure count.\n"
        )
    elif policy_role in _REVIEWER_ROLES:
        if task.report_file is None:
            raise RunnerError(
                "REPORT_FILE_INVALID",
                "A Team Round Reviewer requires its writable report path.",
            )
        report = evidence / "reviews" / task.report_file.name
        report.parent.mkdir(exist_ok=True)
        if (
            report.parent.is_symlink()
            or not report.parent.is_dir()
            or os.path.lexists(report)
        ):
            raise RunnerError("REPORT_FILE_INVALID", "The Reviewer report path is not new.")
        comparison = project.dev_commit
        candidate = run_git(worktree, "rev-parse", "HEAD")
        brief = (
            "Review only for Repository Guidance and established project standards."
            if policy_role == "standards-reviewer"
            else "Review only against the accepted Ticket and its acceptance criteria."
        )
        task_prompt += (
            "\nCandidate: {0}\nComparison: {1}\nReview brief: {2}\n"
            "Inspect without modifying the candidate. Write the report only to {3}.\n".format(
                candidate, comparison, brief, task.report_file.as_posix()
            )
        )
        task_prompt += (
            "\nReport exact fields Candidate commit:, Comparison:, Axis: Standards or Spec, "
            "and Finding: none or one or more Finding: blocks. Each finding must name "
            "Rule:, Input:, Trace:, Failure:, and Evidence: with the exact accepted requirement, "
            "supported input, caller path, observable failure, and retained evidence. "
            "The Team Leader adjudicates report compliance and the implementation outcome.\n"
        )
    reports = (
        [round_directory / "engineer.md", round_directory / "validation.md"]
        if policy_role in _ENGINEER_ROLES else
        [report] if policy_role in _REVIEWER_ROLES else
        [round_directory / "leader.md"] if role == "team-leader" else []
    )
    events_file = session_directory / "events.jsonl"
    if expected_session is None:
        record_runtime_identity(events_file, context.runtime)
    try:
        stderr_offset = (session_directory / "stderr.log").stat().st_size
    except OSError:
        stderr_offset = 0
    with events_file.open("a", encoding="utf-8") as events:
        events.write(json.dumps({"type": "runner-execution-start"}) + "\n")
    event_offset = events_file.stat().st_size
    environment = {
        **runtime_environment,
        **(task_environment or {}),
        "GRAPHTRAJ_TEAM_ROUND": str(ordinal),
        "GRAPHTRAJ_ROLE": role,
        "GRAPHTRAJ_EVIDENCE": str(evidence),
        "GRAPHTRAJ_TICKET_ID": task.ticket_id,
        "GRAPHTRAJ_TICKET_NAME": task.ticket_name,
        "GRAPHTRAJ_HARNESS_ROOT": str(project.harness_root),
        "GRAPHTRAJ_TEAM_GENERATION": str(generation),
    }
    if policy_role in _REVIEWER_ROLES:
        environment.update(
            GRAPHTRAJ_REVIEW_CANDIDATE=candidate,
            GRAPHTRAJ_REVIEW_COMPARISON=comparison,
            GRAPHTRAJ_REVIEW_BRIEF=brief,
            GRAPHTRAJ_REVIEW_REPORT=str(report),
        )
    if registration is not None:
        environment["GRAPHTRAJ_PARENT_REGISTRATION"] = str(registration)
        environment["GRAPHTRAJ_PARENT_ALIAS"] = alias
    notice_threads: list[threading.Thread] = []
    notice_failures: list[BaseException] = []
    try:
        def deliver_budget_notices() -> None:
            if monitor is None or parent_alias is None:
                return
            def deliver(messages: list[str]) -> None:
                for prior in notice_threads:
                    prior.join()
                if notice_failures:
                    raise notice_failures[0]
                notice_threads.clear()
                leader_directory = project.runner_directory / "sessions" / parent_alias
                try:
                    leader_mapping = yaml.safe_load(
                        (leader_directory / "mapping.yml").read_text(encoding="utf-8")
                    )
                    leader_session = leader_mapping["session"]
                except (KeyError, OSError, TypeError, yaml.YAMLError) as error:
                    raise RunnerError(
                        "RUNTIME_WORKER_FAILED",
                        "The Team Leader Session could not receive an execution budget notice.",
                    ) from error
                delivered = threading.Event()

                def resume_leader() -> None:
                    try:
                        _execute_agent(
                            project, task, "team-leader", worktree, evidence, traces,
                            parent_alias, leader_session,
                            leader_directory / "child-registration.yml", None,
                            retained_batch,
                            "\n".join(messages)
                            + "\nReceive these system notices. Do not dispatch work or make a Team decision.",
                            capacity_fd,
                            reports_only=True,
                            input_delivered=delivered,
                        )
                        delivered.set()
                    except BaseException as error:
                        notice_failures.append(error)

                thread = threading.Thread(target=copy_context().run, args=(resume_leader,))
                thread.start()
                notice_threads.append(thread)
                while not delivered.wait(0.05):
                    if not thread.is_alive():
                        thread.join()
                        raise notice_failures[-1]

            monitor.deliver_leader_notices(deliver)

        session_id, outcome = _run_session_worker(
            session_directory,
            job_file,
            worktree,
            task_prompt,
            environment,
            capacity_fd,
            monitor,
            role,
            budget_stage,
            expected_session is None,
            deliver_budget_notices,
            input_delivered,
            wait_for_completion,
        )
        for thread in notice_threads:
            thread.join()
        if notice_failures:
            raise notice_failures[0]
        if (
            outcome == "completed"
            and role == "team-leader"
            and parent_alias is None
            and monitor is not None
        ):
            notices = monitor.pending_leader_notices()
            if notices:
                delivered = threading.Event()
                failure: list[BaseException] = []

                def finish_leader() -> None:
                    try:
                        _execute_agent(
                            project, task, role, worktree, evidence, traces, alias,
                            session_id, registration, None, retained_batch,
                            "\n".join(notice["message"] for notice in notices)
                            + "\nReceive these system notices, then finish the "
                            "current Leader work.",
                            capacity_fd,
                            input_delivered=delivered,
                        )
                    except BaseException as error:
                        failure.append(error)

                thread = threading.Thread(target=copy_context().run, args=(finish_leader,))
                thread.start()
                while not delivered.wait(0.05):
                    if not thread.is_alive():
                        thread.join()
                        raise failure[-1]
                monitor.mark_leader_notices_delivered(
                    [notice["key"] for notice in notices]
                )
                thread.join()
                if failure:
                    raise failure[0]
    finally:
        for thread in notice_threads:
            thread.join()
    if not wait_for_completion:
        return alias, session_id
    diagnostic = _current_runtime_diagnostic(
        session_directory, stderr_offset, event_offset
    )
    if outcome == "budget-stopped":
        if role == "team-leader" and monitor is not None:
            def report_stop(messages: list[str]) -> None:
                _execute_agent(
                    project, task, role, worktree, evidence, traces, alias,
                    session_id, registration, None, retained_batch,
                    "\n".join(messages)
                    + "\nExecution has stopped. Freeze the current scene and report "
                    "the current result and remaining work. Do not dispatch or decide "
                    "acceptance.",
                    capacity_fd,
                    reports_only=True,
                )

            monitor.deliver_leader_notices(report_stop)
        raise RunnerError(
            "EXECUTION_BUDGET_STOPPED",
            "Runner selected stopping for the Ticket execution budget.",
        )
    if outcome != "completed":
        if _runtime_access_failure(diagnostic, tuple(reports)):
            raise RunnerError(
                "RUNTIME_ACCESS_DENIED",
                "The {0} Team member encountered a Runtime access/configuration failure. "
                "Return it to the responsible operator; do not ask the Agent to self-correct. "
                "Evidence: {1}. {2}".format(
                    role, _trace_ref(project, traces, alias), diagnostic.strip()
                ),
            )
        raise RunnerError(
            "RUNTIME_PROVIDER_FAILED",
            "The {0} Team member ended with {1}. Return this system/provider failure "
            "to the caller or superior for a later retry; do not ask the Agent to "
            "self-correct. Evidence: {2}. {3}".format(
                role, outcome, _trace_ref(project, traces, alias), diagnostic.strip()
            ),
        )
    if (
        any(not path.is_file() for path in reports)
        and _runtime_access_failure(diagnostic, tuple(reports))
    ):
        raise RunnerError(
            "RUNTIME_ACCESS_DENIED",
            "The {0} Team member encountered a Runtime access/configuration failure. "
            "Return it to the responsible operator; do not ask the Agent to "
            "self-correct. Evidence: {1}. {2}".format(
                role, _trace_ref(project, traces, alias), diagnostic.strip()
            ),
        )
    if any(not path.is_file() for path in reports):
        command_error = _runtime_command_parse_error(diagnostic)
        if command_error is not None:
            with events_file.open("a", encoding="utf-8") as events:
                events.write(
                    json.dumps(
                        {
                            "type": "runtime-command-parse",
                            "message": command_error,
                        }
                    )
                    + "\n"
                )
    with (session_directory / "events.jsonl").open("a", encoding="utf-8") as trace:
        for path in reports:
            if path.is_file():
                trace.write(json.dumps({"type": "report-observed", "path": path.relative_to(evidence).as_posix(),
                                        "content": path.read_text(encoding="utf-8")}) + "\n")
    return alias, session_id


def _resume_job(
    session_directory: Path,
    expected_session: str,
    role: str,
    worktree: Path,
    evidence: Path,
    report_files: tuple[Path, ...],
    *,
    reports_only: bool = False,
) -> tuple[Path, dict[str, str]]:
    launch_file = session_directory / "launch.yml"
    mapping_file = session_directory / "mapping.yml"
    try:
        launch = yaml.safe_load(launch_file.read_text(encoding="utf-8"))
        mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise RunnerError("RUNTIME_WORKER_FAILED", "The mapped Session is unavailable.") from error
    if (
        not isinstance(launch, dict)
        or not isinstance(mapping, dict)
        or launch.get("runtime") != mapping.get("runtime")
        or not isinstance(launch.get("adapter_request"), dict)
        or mapping.get("session") != expected_session
        or not isinstance(launch.get("connection"), dict)
    ):
        raise RunnerError("RUNTIME_WORKER_FAILED", "The mapped Session is unavailable.")
    connection = launch["connection"]
    if any(
        key not in {"base_url", "api_key_env"}
        or not isinstance(value, str)
        or not value
        for key, value in connection.items()
    ):
        raise RunnerError("RUNTIME_WORKER_FAILED", "The mapped Session is unavailable.")
    try:
        adapter_request = refresh_codex_report_paths(
            launch["adapter_request"],
            worktree=worktree,
            evidence=evidence,
            report_files=report_files,
            role=role,
            reports_only=reports_only,
        )
    except RuntimeAdapterError as error:
        raise RunnerError(error.code, error.message) from error
    resume_file = session_directory / "resume.yml"
    write_yaml_durably(
        resume_file,
        {
            "operation": "resume",
            "runtime": mapping["runtime"],
            "adapter_request": adapter_request,
            "context_evidence": launch.get("context_evidence", {}),
            "expected_session": expected_session,
            "mapping": {
                key: value
                for key, value in mapping.items()
                if key not in {"worker_pid", "runtime_pid"}
            },
        },
    )
    return resume_file, dict(
        codex_connection_environment(
            connection.get("base_url"), connection.get("api_key_env")
        )
    )


def _run_session_worker(
    session_directory: Path,
    job_file: Path,
    worktree: Path,
    prompt: str,
    runtime_environment: object,
    capacity_fd: int,
    monitor: ExecutionBudgetMonitor | None,
    role: str,
    stage: str,
    new_session: bool,
    deliver_budget_notices: Callable[[], None],
    input_delivered: threading.Event | None,
    wait_for_completion: bool = True,
) -> tuple[str, str]:
    if not isinstance(runtime_environment, dict):
        raise RunnerError("RUNTIME_WORKER_FAILED", "The Runtime Session could not be started.")
    execution = session_directory / "execution.yml"
    error = session_directory / (
        "resume-error.yml" if job_file.name == "resume.yml" else "launch-error.yml"
    )
    error.unlink(missing_ok=True)
    worker_environment = dict(os.environ)
    worker_environment.update(runtime_environment)
    try:
        with (session_directory / "worker-stderr.log").open(
            "w", encoding="utf-8"
        ) as diagnostics:
            worker = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "graphtraj.execution.runner_worker",
                    str(job_file),
                ],
                cwd=worktree,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=diagnostics,
                text=True,
                start_new_session=True,
                env=worker_environment,
                pass_fds=(capacity_fd,),
            )
            assert worker.stdin is not None
            worker.stdin.write(prompt)
            worker.stdin.close()
            if not wait_for_completion:
                from graphtraj.execution.runner_control import _await_session_resume

                _await_session_resume(worker, session_directory, error, None)
                mapping, _ = read_alias_mapping(session_directory.parent.parent, session_directory.name)
                return mapping["session"], "running"
            try:
                session_recorded = not new_session
                budget_stopped = False
                while worker.poll() is None:
                    if input_delivered is not None and not input_delivered.is_set():
                        try:
                            current_mapping = yaml.safe_load(
                                (session_directory / "mapping.yml").read_text(
                                    encoding="utf-8"
                                )
                            )
                        except (OSError, UnicodeError, yaml.YAMLError):
                            current_mapping = None
                        if (
                            isinstance(current_mapping, dict)
                            and current_mapping.get("worker_pid") == worker.pid
                        ):
                            input_delivered.set()
                    if monitor is not None:
                        if not session_recorded and (session_directory / "mapping.yml").is_file():
                            monitor.record_session(role, stage)
                            session_recorded = True
                        stopped = monitor.check(role, stage)
                        deliver_budget_notices()
                        if stopped and (
                            role in _ENGINEER_ROLES or role == "team-leader"
                        ):
                            budget_stopped = True
                            worker.terminate()
                    try:
                        worker.wait(timeout=0.05)
                    except subprocess.TimeoutExpired:
                        pass
                if monitor is not None:
                    if not session_recorded and (session_directory / "mapping.yml").is_file():
                        monitor.record_session(role, stage)
                    stopped = monitor.check(role, stage)
                    deliver_budget_notices()
                    budget_stopped = budget_stopped or (
                        stopped
                        and (role in _ENGINEER_ROLES or role == "team-leader")
                    )
                if input_delivered is not None and not input_delivered.is_set():
                    try:
                        final_mapping = yaml.safe_load(
                            (session_directory / "mapping.yml").read_text(
                                encoding="utf-8"
                            )
                        )
                    except (OSError, UnicodeError, yaml.YAMLError):
                        final_mapping = None
                    if (
                        isinstance(final_mapping, dict)
                        and final_mapping.get("worker_pid") == worker.pid
                    ):
                        input_delivered.set()
                exit_code = worker.returncode
            except BaseException:
                worker.terminate()
                worker.wait()
                raise
        if exit_code != 0:
            raise OSError("Session worker failed")
        mapping = yaml.safe_load(
            (session_directory / "mapping.yml").read_text(encoding="utf-8")
        )
        terminal = yaml.safe_load(execution.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as failure:
        raise RunnerError("RUNTIME_WORKER_FAILED", "The Runtime Session could not be started.") from failure
    if (
        not isinstance(mapping, dict)
        or not isinstance(mapping.get("session"), str)
        or not mapping["session"]
        or not isinstance(terminal, dict)
        or terminal.get("outcome") not in {"completed", "interrupted", "runtime-error"}
    ):
        raise RunnerError("RUNTIME_WORKER_FAILED", "The Runtime Session could not be started.")
    return mapping["session"], (
        "budget-stopped" if budget_stopped else terminal["outcome"]
    )


def _agent_alias(project: Any, task: Task, role: str, generation: int = 1) -> str:
    marker = role_alias_marker(role)
    suffix = 2 if role == "spec-reviewer" else 1
    prefix = f"{task.ticket_id}-{task.ticket_name}"
    if generation > 1:
        prefix += f"-team{generation}"
    while (project.runner_directory / "sessions" / f"{prefix}@{marker}{suffix}").exists():
        suffix += 2 if marker == "r" else 1
    return f"{prefix}@{marker}{suffix}"


def _role_report_files(
    task: Task,
    policy_role: str,
    role: str,
    generation: int,
    ordinal: int,
) -> tuple[Path, ...]:
    if policy_role in _ENGINEER_ROLES:
        directory = Path(".state") / "teams" / str(generation) / "rounds" / str(ordinal)
        return (directory / "engineer.md", directory / "validation.md")
    if role == "team-leader":
        return (
            Path(".state") / "teams" / str(generation) / "rounds" / str(ordinal) / "leader.md",
        )
    return (task.report_file,) if policy_role in _REVIEWER_ROLES and task.report_file else ()


def _review_report_name(role: str) -> str:
    if role == "standards-reviewer":
        return "standards.md"
    if role == "spec-reviewer":
        return "spec.md"
    raise RunnerError("REPORT_FILE_INVALID", "The Team Reviewer role is invalid.")


def _review_report_file(role: str, mapping: dict[str, Any]) -> Path:
    default = Path(".state") / "reviews" / _review_report_name(role)
    value = mapping.get("report_file")
    if value is None:
        return default
    report = Path(value) if isinstance(value, str) else None
    if (
        report is None
        or report.is_absolute()
        or len(report.parts) != 3
        or report.parts[:2] != (".state", "reviews")
        or ".." in report.parts
        or report.suffix != ".md"
    ):
        raise RunnerError(
            "REPORT_FILE_INVALID",
            "The Reviewer Session report target is invalid.",
        )
    return report


def _link_worktree(project: Any, worktree: Path, evidence: Path) -> None:
    (worktree / ".scratch").mkdir(exist_ok=True)
    links = {
        ".state": evidence,
        "CONTEXT.md": project.harness_root / "CONTEXT.md",
        "docs": project.documents_directory,
    }
    created_documents = []
    for name, target in links.items():
        link = worktree / name
        if os.path.lexists(link):
            if (name == "docs" and (link.is_dir() or link.is_symlink())) or (
                name == "CONTEXT.md" and (link.is_file() or link.is_symlink())
            ):
                continue
            if not link.is_symlink() or link.resolve() != target.resolve():
                raise RunnerError("STATE_LINK_FAILED", "A Ticket Worktree retained path points elsewhere.")
            continue
        link.symlink_to(os.path.relpath(target, worktree), target_is_directory=target.is_dir())
        if name in {"docs", "CONTEXT.md"}:
            created_documents.append(name)
    ignore_worktree_documents(worktree, created_documents)


def _validate_round(round_directory: Path, worktree: Path) -> str:
    required = {"engineer.md", "validation.md", "standards.md", "spec.md", "leader.md"}
    try:
        paths = tuple(round_directory.iterdir())
    except OSError as error:
        raise RunnerError(
            _AGENT_EVIDENCE_ERROR,
            "The Team Round evidence is missing or unreadable.",
        ) from error
    if (
        {path.name for path in paths} != required
        or any(path.is_symlink() or not path.is_file() for path in paths)
    ):
        raise RunnerError(
            _AGENT_EVIDENCE_ERROR,
            "The Team Round did not produce its complete evidence.",
        )
    candidate = _candidate(round_directory, worktree)
    try:
        inspected = [
            (round_directory / name).read_text(encoding="utf-8")
            for name in required
        ]
    except (OSError, UnicodeError) as error:
        raise RunnerError(
            _AGENT_EVIDENCE_ERROR,
            "The Team Round evidence is missing or unreadable.",
        ) from error
    if any(candidate not in report for report in inspected):
        raise RunnerError(
            _AGENT_EVIDENCE_ERROR,
            "All Team evidence must inspect the same fixed candidate.",
        )
    return candidate


def _candidate(round_directory: Path, worktree: Path) -> str:
    try:
        engineer = (round_directory / "engineer.md").read_text(encoding="utf-8")
        validation = (round_directory / "validation.md").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RunnerError(
            _AGENT_EVIDENCE_ERROR,
            "The Engineer evidence is missing or unreadable.",
        ) from error
    match = _COMMIT.search(engineer)
    candidate = match.group(0) if match else ""
    if (
        not candidate
        or run_git(worktree, "rev-parse", "HEAD") != candidate
        or candidate not in validation
    ):
        raise RunnerError(
            _AGENT_EVIDENCE_ERROR,
            "The Engineer evidence does not identify the fixed candidate.",
        )
    if not (
        git_succeeds(worktree, "diff", "--quiet")
        and git_succeeds(worktree, "diff", "--cached", "--quiet")
    ):
        raise RunnerError(
            _AGENT_EVIDENCE_ERROR,
            "Tracked project changes must be committed before the Team handoff.",
        )
    return candidate


def _leader_decision(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    decisions = [
        line for line in lines if line in {"Decision: ACCEPT", "Decision: REJECT"}
    ]
    return "accepted" if decisions == ["Decision: ACCEPT"] else "rejected"


def _collect_review_report(
    evidence: Path,
    round_directory: Path,
    source_name: str,
    target_name: str | None = None,
    session_directory: Path | None = None,
) -> None:
    source = evidence / "reviews" / source_name
    target = round_directory / (target_name or source_name)
    if source.is_symlink() or not source.is_file() or target.exists():
        command_error = (
            _current_command_parse_error(session_directory)
            if session_directory is not None else None
        )
        raise RunnerError(
            _AGENT_EVIDENCE_ERROR,
            (
                "The Reviewer did not produce its exact report. Unsupported input: "
                + command_error
                if command_error is not None
                else "The Reviewer did not produce its exact report."
            ),
        )
    source.replace(target)
    if not any(source.parent.iterdir()):
        source.parent.rmdir()


def _worker_main() -> None:
    # Unwind the Session worker before releasing the Team worker's capacity.
    def stop(signum: int, frame: Any) -> None:
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, stop)
    retained = Path(sys.argv[1])
    task = read_batch(retained, Path.cwd()).tasks[int(sys.argv[2])]
    try:
        project = discover_project(Path.cwd(), require_clean_integration=False)
        capacity_fd = int(sys.argv[3])
        if task.role == "team-leader":
            result = _deliver_ticket(project, task, retained, capacity_fd)
        else:
            evidence = project.state_directory / "tickets" / (task.ticket_id + "-" + task.ticket_name)
            state = yaml.safe_load((evidence / "ticket.yml").read_text())
            definition = evidence / state["current_definition"]
            team = yaml.safe_load((evidence / "teams" / str(state["active_team_ordinal"]) / "team.yml").read_text())
            seat = "standards_reviewer" if task.role == "standards-reviewer" else "spec_reviewer"
            member = team["members"][seat]
            session = None
            report_file = Path(".state") / "reviews" / _review_report_name(task.role)
            if member["session_ref"]:
                mapping, _ = read_alias_mapping(
                    project.runner_directory, member["session_ref"]
                )
                session = mapping["session"]
                report_file = _review_report_file(task.role, mapping)
            task = replace(
                task, ticket_file=definition, ticket_content=definition.read_text(),
                report_file=report_file,
            )
            traces = evidence / "teams" / str(state["active_team_ordinal"]) / "traces"
            worktree = project.harness_root / state["worktree"]
            recovery_prompt = None
            if session is not None and sys.argv[5:] == ["recover-reports"]:
                recovery_prompt = _evidence_recovery_prompt(
                    project, task, traces, member["session_ref"], worktree,
                    RunnerError(_AGENT_EVIDENCE_ERROR, "The current Round Review report is missing."),
                    "deliver the exact current Round raw Review report from retained work; "
                    "finish only work that is not already valid for the current candidate",
                )
            alias, session = _run_agent(
                project, task, task.role, worktree, evidence, traces,
                member["session_ref"], session, None, sys.argv[4], retained,
                recovery_prompt, capacity_fd=capacity_fd,
            )
            result = {"role": task.role, "alias": alias, "session": session, "launch_status": "completed"}
    except (RunnerError, RuntimeAdapterError) as error:
        if error.code == "EXECUTION_BUDGET_STOPPED" and task.role == "team-leader":
            mappings = [
                yaml.safe_load(path.read_text(encoding="utf-8"))
                for path in project.runner_directory.glob("sessions/*/mapping.yml")
                if yaml.safe_load(path.read_text(encoding="utf-8")).get("ticket_id")
                == task.ticket_id
                and yaml.safe_load(path.read_text(encoding="utf-8")).get("role")
                == "team-leader"
            ]
            mapping = max(
                mappings, key=lambda value: value.get("team_generation", 0)
            )
            result = {
                "ticket_id": task.ticket_id,
                "ticket_name": task.ticket_name,
                "role": "team-leader",
                "launch_status": "stopped",
                "worktree_path": mapping["worktree_path"],
                "alias": mapping["alias"],
                "session": mapping["session"],
            }
        else:
            result = _failed_task(task, RunnerError(error.code, error.message))
    print(yaml.safe_dump(result, sort_keys=False), end="")


if __name__ == "__main__":
    _worker_main()
