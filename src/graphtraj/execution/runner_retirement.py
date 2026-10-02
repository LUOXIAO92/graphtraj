"""Retire stopped task members without deleting their Session evidence."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from graphtraj.execution.runner_heartbeat import execution_start_lock
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.execution.runner_models import Project
from graphtraj.execution.runner_status import (
    read_alias_mapping, require_replacement_authority, require_stopped_subtree,
)
from graphtraj.graph.delivery_state import apply_delivery_state_request, read_team
from graphtraj.graph.delivery_worldline import read_worldline
from graphtraj.graph.ticket_graph import _load_states
from graphtraj.workspace.runner_project import discover_project


def retire_session(alias: str, cwd: Path) -> dict:
    """Authorize retirement through the same native boundary as replacement."""
    project = discover_project(cwd, require_clean_integration=False)
    mapping, _ = read_alias_mapping(project.runner_directory, alias)
    script = (
        "from pathlib import Path; import yaml; "
        "from graphtraj.execution.runner_retirement import _retire_session; "
        "print(yaml.safe_dump(_retire_session(" + repr(alias)
        + ", Path(" + repr(str(cwd)) + ")), sort_keys=False))"
    )
    result = require_replacement_authority(
        project.runner_directory, alias, mapping, [sys.executable, "-I", "-c", script],
    )
    return result if result is not None else _retire_session(alias, cwd)


def _retire_session(alias: str, cwd: Path) -> dict:
    """Check the stopped subtree under the existing startup lock, then retire."""
    project = discover_project(cwd, require_clean_integration=False)
    with execution_start_lock(project.runner_directory):
        return retire_stopped_session(project, alias)


def retire_stopped_session(project: Project, alias: str) -> dict:
    """Retire an authorized member while the caller holds the startup lock.

    The Runtime Session record retains the complete last Runner binding before
    its active mapping is removed. Launch inputs, native records, results and
    Trace paths stay intact. Descendants keep their original parent and cannot
    start work through a retired ancestor.
    """
    mapping, directory = read_alias_mapping(project.runner_directory, alias)
    require_stopped_subtree(project.runner_directory, alias)
    record_file = directory / "session.yml"
    record = yaml.safe_load(record_file.read_text())
    retirement = record.get("retirement")
    ticket_directory, ticket = _load_states(project.state_directory / "tickets")[mapping["ticket_id"]]
    team_file = ticket_directory / "teams" / str(mapping["team_generation"]) / "team.yml"
    team = read_team(team_file)
    member = next((name for name, entry in team["members"].items()
                   if entry["session_ref"] == alias), None)
    if retirement is None:
        retirement = {"member": member, "mapping": mapping}
        write_yaml_durably(record_file, {**record, "retirement": retirement})
    (directory / "mapping.yml").unlink(missing_ok=True)
    retained_directory = Path(mapping["trace_file"]).parent / "runner"
    if directory != retained_directory:
        directory.rename(retained_directory)
        directory = retained_directory
        record_file = directory / "session.yml"
    if (member is not None and ticket["active_team_ordinal"] == mapping["team_generation"]
            and team["status"] == "active"):
        cause = next(event["event_id"] for event in reversed(
            read_worldline(project.state_directory, project.harness_root)
        ) if event.get("ticket_id") == mapping["ticket_id"])
        request = {
            "phase": "retire-member", "ticket_id": mapping["ticket_id"],
            "member": member, "session_ref": alias,
            "caused_by_event_ids": [cause],
            "evidence_refs": [record_file.relative_to(project.harness_root).as_posix()],
        }
        apply_delivery_state_request(project.state_directory, project.harness_root, request, request)
    return {"alias": alias, "retire_status": "retired", "member": retirement["member"],
            "session": mapping["session"], "team_ordinal": mapping["team_generation"],
            "worktree_path": mapping["worktree_path"]}
