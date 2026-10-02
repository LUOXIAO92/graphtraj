"""Replace an actual Team member while retaining its Ticket and Session evidence."""

from __future__ import annotations

import fcntl

import yaml
from dataclasses import replace
from pathlib import Path

from graphtraj.configuration.project_roles import configured_role_name
from graphtraj.execution.runner_batch import read_session_task
from graphtraj.execution.runner_control import _require_project_events, _session_report_paths
from graphtraj.execution.runner_connection import current_parent_connection, parent_connection
from graphtraj.execution.runner_models import Project, RunnerError
from graphtraj.execution.runner_retirement import retire_session
from graphtraj.workspace.runner_project import discover_project, run_git
from graphtraj.execution.runner_status import (
    read_alias_mapping,
    require_stopped_subtree,
)
from graphtraj.teams.team_round import (
    _run_agent,
    _trace_ref,
)
from graphtraj.graph.ticket_graph import _load_states
from graphtraj.graph.delivery_state import read_team
from graphtraj.runtimes import runtime_adapter


def require_active_session(
    project: Project, alias: str, *, reports_only: bool = False,
) -> dict | None:
    """Read the active Team without confusing members that share a role."""
    mapping, session_directory = read_alias_mapping(project.runner_directory, alias)
    record_file = session_directory / "session.yml"
    if record_file.is_file() and yaml.safe_load(record_file.read_text()).get("retirement"):
        raise RunnerError("session-retired", "This Session has retired from its task.")
    directory, ticket = _load_states(project.state_directory / "tickets")[mapping["ticket_id"]]
    if (Path(mapping["worktree_path"]) == project.integration_worktree
            and ticket["status"] != "resolving-integration" and not reports_only):
        raise RunnerError("authority-denied", "Integration Worktree work requires an active conflict assignment.")
    team_file = directory / "teams" / str(mapping["team_generation"]) / "team.yml"
    # The newly launched parent Session registers its first Batch before Team start.
    if not team_file.exists():
        return
    team = read_team(team_file)
    if (not ticket["active"]
            or team["status"] != "active"
            or ticket["active_team_ordinal"] != mapping["team_generation"]):
        raise RunnerError("team-not-active", "The Team has stopped starting new work.")
    seats = [member for member in team["members"].values()
             if configured_role_name(member["role"]) == configured_role_name(mapping["role"])]
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
    return _replace_stopped_session(alias, actor, caused_by_event_ids, cwd)


def _replace_stopped_session(
    alias: str, actor: str | None, caused_by_event_ids: tuple[str, ...], cwd: Path
) -> dict:
    """Check stopped state and serialize retirement plus member registration."""
    project = discover_project(cwd, require_clean_integration=False)
    _, directory = read_alias_mapping(project.runner_directory, alias)
    require_stopped_subtree(project.runner_directory, alias)
    if not caused_by_event_ids or len(caused_by_event_ids) != len(set(caused_by_event_ids)):
        raise RunnerError("invalid-input", "Replacement requires unique causal Project Worldline event IDs.")
    with (directory / "launch.yml").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _replace_member(alias, caused_by_event_ids, cwd)


def _replace_member(alias: str, caused_by_event_ids: tuple[str, ...], cwd: Path) -> dict:
    """Compose retirement and existing registration, allowing a vacant-seat retry."""
    project = discover_project(cwd, require_clean_integration=False)
    mapping, session_directory = read_alias_mapping(project.runner_directory, alias)
    require_stopped_subtree(project.runner_directory, alias)
    if not caused_by_event_ids or len(caused_by_event_ids) != len(set(caused_by_event_ids)):
        raise RunnerError("invalid-input", "Replacement requires unique causal Project Worldline event IDs.")
    _require_project_events(cwd, caused_by_event_ids)
    directory, ticket = _load_states(project.state_directory / "tickets")[mapping["ticket_id"]]
    generation = mapping["team_generation"]
    team_file = directory / "teams" / str(generation) / "team.yml"
    team = read_team(team_file)
    retirement = yaml.safe_load((session_directory / "session.yml").read_text()).get("retirement")
    seats = [
        name
        for name, member in team["members"].items()
        if member["session_ref"] == alias
        or (
            member["session_ref"] is None
            and configured_role_name(member["role"]) == configured_role_name(mapping["role"])
        )
    ]
    seat = retirement["member"] if retirement else (seats[0] if len(seats) == 1 else None)
    if retirement and seat in team["members"] and team["members"][seat]["session_ref"] is not None:
        successor = team["members"][seat]["session_ref"]
        _, successor_directory = read_alias_mapping(project.runner_directory, successor)
        launch = yaml.safe_load((successor_directory / "launch.yml").read_text())
        if launch.get("member_registration", {}).get("replaces") == alias:
            return {"alias": alias, "replacement_alias": successor, "team_ordinal": generation}
        raise RunnerError("seat-replaced", "Another Session already occupies the retired member seat.")
    if seat is None or ticket["active_team_ordinal"] != generation:
        raise RunnerError("seat-replaced", "The alias must identify a current Team seat.")
    if not ticket["active"] or ticket["status"] in {"integrating", "resolving-integration", "integrated"}:
        raise RunnerError("team-not-active", "This Ticket is inactive or has entered integration.")
    worktree = project.harness_root / ticket["worktree"]
    traces = team_file.parent / "traces"
    retained = Path(mapping["retained_batch_file"])
    task = read_session_task(mapping, cwd)
    definition = directory / ticket["current_definition"]
    # Replacement selects current explicit resources; old Skill names stay in
    # the retained Batch and must not become a fresh preflight selection.
    task = replace(task, ticket_file=definition, ticket_content=definition.read_text(),
                   requested_skills=())
    if not retirement:
        require_active_session(project, alias)
    current_commit = run_git(worktree, "rev-parse", "HEAD")
    prior_trace = _trace_ref(project, traces, alias)
    reports = "\n\n".join(
        f"{path.name}:\n{path.read_text(encoding='utf-8')}"
        for path in _session_report_paths(alias, cwd) if path.is_file()
    )
    # Replacing a root seat keeps its original owning host.
    host = (mapping.get("parent_connection") or current_parent_connection()
            or (runtime_adapter.current_host_connection() if mapping["parent"] is None else None))
    retire_session(alias, cwd)
    try:
        with parent_connection(host):
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
    except (RunnerError, runtime_adapter.RuntimeAdapterError, OSError, ValueError, yaml.YAMLError) as error:
        return {
            "alias": alias, "replace_status": "failed", "completed_actions": ["retired"],
            "error": (error.as_document() if isinstance(error, RunnerError)
                      else RunnerError(error.code, error.message).as_document()
                      if isinstance(error, runtime_adapter.RuntimeAdapterError)
                      else {"code": "operation-failed", "message": str(error)}),
            "retry": "Retry replace with this alias and causal event IDs; the old Session stays retired.",
        }
    return {"alias": alias, "replacement_alias": replacement, "team_ordinal": generation}
