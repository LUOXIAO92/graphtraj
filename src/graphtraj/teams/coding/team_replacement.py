"""Replace an actual Team member while retaining its Ticket and Session evidence."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

from graphtraj.configuration.project_roles import logical_role
from graphtraj.execution.runner_batch import read_batch
from graphtraj.execution.runner_control import _require_project_events, _session_report_paths
from graphtraj.execution.runner_models import Project, RunnerError
from graphtraj.workspace.runner_project import discover_project, run_git
from graphtraj.execution.runner_status import (
    read_alias_mapping,
    require_replacement_authority,
    require_stopped_subtree,
)
from graphtraj.teams.coding.team_round import (
    _run_agent,
    _trace_ref,
)
from graphtraj.graph.ticket_graph import _load_states
from graphtraj.graph.delivery_state import read_team


def require_active_session(project: Project, alias: str) -> dict | None:
    """Read the active Team without confusing members that share a role."""
    mapping, _ = read_alias_mapping(project.runner_directory, alias)
    directory, ticket = _load_states(project.state_directory / "tickets")[mapping["ticket_id"]]
    team_file = directory / "teams" / str(mapping["team_generation"]) / "team.yml"
    # A newly launched Leader registers its first Batch before Team start.
    if not team_file.exists():
        return
    team = read_team(team_file)
    if (not ticket["active"]
            or team["status"] != "active"
            or ticket["active_team_ordinal"] != mapping["team_generation"]):
        raise RunnerError("team-not-active", "The Team has stopped starting new work.")
    seats = [member for member in team["members"].values()
             if logical_role(member["role"]) == logical_role(mapping["role"])]
    if seats and all(member["session_ref"] not in {None, alias} for member in seats):
        raise RunnerError("seat-replaced", "This Session no longer occupies its Team seat.")
    return team


def replace_session(
    alias: str, actor: str | None, caused_by_event_ids: tuple[str, ...], cwd: Path
) -> dict:
    """Check ownership, then execute this replacement via native approval if needed.

    The Runner's recorded direct relation decides who may replace the target;
    the retained actor argument grants no authority. Every role uses the same
    actual-member replacement path.
    """
    project = discover_project(cwd, require_clean_integration=False)
    mapping, _ = read_alias_mapping(project.runner_directory, alias)
    # Native approval executes the concrete remaining operation, not a replay of
    # the public entry or a command carrying an approved/skip-authority flag.
    script = (
        "from pathlib import Path; import yaml; "
        "from graphtraj.teams.coding.team_replacement import _replace_stopped_session; "
        "print(yaml.safe_dump(_replace_stopped_session("
        + repr(alias) + ", " + repr(actor) + ", "
        + repr(tuple(caused_by_event_ids)) + ", Path(" + repr(str(cwd))
        + ")), sort_keys=False))"
    )
    result = require_replacement_authority(
        project.runner_directory, alias, mapping, [sys.executable, "-I", "-c", script]
    )
    if result is not None:
        return result
    return _replace_stopped_session(alias, actor, caused_by_event_ids, cwd)


def _replace_stopped_session(
    alias: str, actor: str | None, caused_by_event_ids: tuple[str, ...], cwd: Path
) -> dict:
    """Perform the replacement after relation/native approval; recheck stopped state."""
    project = discover_project(cwd, require_clean_integration=False)
    mapping, _ = read_alias_mapping(project.runner_directory, alias)
    require_stopped_subtree(project.runner_directory, alias)
    if not caused_by_event_ids or len(caused_by_event_ids) != len(set(caused_by_event_ids)):
        raise RunnerError("invalid-input", "Replacement requires unique causal Project Worldline event IDs.")
    _require_project_events(cwd, caused_by_event_ids)
    directory, ticket = _load_states(project.state_directory / "tickets")[mapping["ticket_id"]]
    generation = mapping["team_generation"]
    team_file = directory / "teams" / str(generation) / "team.yml"
    team = read_team(team_file)
    seats = [
        name
        for name, member in team["members"].items()
        if member["session_ref"] == alias
        or (
            member["session_ref"] is None
            and logical_role(member["role"]) == logical_role(mapping["role"])
        )
    ]
    seat = seats[0] if len(seats) == 1 else None
    if seat is None or ticket["active_team_ordinal"] != generation:
        raise RunnerError("seat-replaced", "The alias must identify a current Team seat.")
    if not ticket["active"] or ticket["status"] in {"integrating", "resolving-integration", "integrated"}:
        raise RunnerError("team-not-active", "This Ticket is inactive or has entered integration.")
    worktree = project.harness_root / ticket["worktree"]
    traces = team_file.parent / "traces"
    retained = Path(mapping["retained_batch_file"])
    batch = read_batch(retained, cwd)
    task = next(task for task in batch.tasks if task.ticket_id == ticket["ticket_id"] and task.role == mapping["role"])
    definition = directory / ticket["current_definition"]
    task = replace(task, ticket_file=definition, ticket_content=definition.read_text())
    require_active_session(project, alias)
    current_commit = run_git(worktree, "rev-parse", "HEAD")
    prior_trace = _trace_ref(project, traces, alias)
    reports = "\n\n".join(
        f"{path.name}:\n{path.read_text(encoding='utf-8')}"
        for path in _session_report_paths(alias, cwd, collected=True) if path.is_file()
    )
    replacement, _ = _run_agent(
        project, task, task.role, worktree, directory, traces,
        None, None, None, mapping["parent"], retained,
        "Continue this Team seat from previous Session {0} and Trace {1}.\n"
        "Accepted Ticket and constraints:\n{2}\n"
        "Current commit: {3}\n"
        "Valid retained evidence: {1}\n"
        "Previous Session reports supplied by the authorized replacement:\n{5}\n"
        "Remaining work: continue only the current {4} Team seat, preserving closed Team Round evidence."
        .format(alias, prior_trace, task.ticket_content, current_commit, task.role, reports),
        register_member=True, replaces_alias=alias, wait_for_completion=False,
    )
    return {"alias": alias, "replacement_alias": replacement, "team_ordinal": generation}
