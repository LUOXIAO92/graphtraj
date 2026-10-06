"""Retire stopped task members without deleting their Session evidence."""

from __future__ import annotations

from pathlib import Path

import yaml

from graphtraj.execution.runner_heartbeat import execution_start_lock
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.execution.runner_models import Project, RunnerError
from graphtraj.execution.approved_recovery import review_proposal
from graphtraj.execution.runner_status import (
    caller_alias, is_direct_owner, read_alias_mapping, require_stopped_subtree,
)
from graphtraj.graph.delivery_state import apply_delivery_state_request, read_team
from graphtraj.graph.delivery_worldline import read_worldline
from graphtraj.graph.ticket_graph import _load_states
from graphtraj.workspace.runner_project import discover_project


def retire_session(alias: str, cwd: Path, *, replacement: dict | None = None) -> dict:
    """Review and retire a stopped member inside this public operation.

    The replacement caller supplies its concrete registration as part of the
    same review. This context is not a public tool argument or approval flag.
    """
    project = discover_project(cwd, require_clean_integration=False)
    mapping, directory = read_alias_mapping(project.runner_directory, alias)
    require_stopped_subtree(project.runner_directory, alias)
    caller = caller_alias(project.runner_directory)
    if not is_direct_owner(caller, mapping, project.runner_directory):
        from graphtraj.runtimes.replacement import caller_runtime

        runtime = (read_alias_mapping(project.runner_directory, caller)[0]['runtime']
                   if caller is not None else caller_runtime())
        # Keep the supported Runtime with no approval mechanism distinct from
        # an unavailable or refusing selected reviewer.
        if runtime != 'pi':
            retired = bool(yaml.safe_load((directory / 'session.yml').read_text()).get('retirement'))
            proposal = {
                'request': {'operation': 'replace' if replacement is not None else 'retire',
                            'alias': alias,
                            **({'registration': replacement} if replacement is not None else {})},
                'before': {'mapping': None if retired else mapping, 'retired': retired},
                'after': {'mapping': None, 'retired': True,
                          **({'registration': replacement} if replacement is not None else {})},
                'caller': caller, 'parent': mapping.get('parent'),
                'preserved': ['Session', 'Trace', 'parent relationships', 'Worktree'],
            }
            if review_proposal(proposal, cwd, project.runner_directory) != {'decision': 'accept'}:
                raise RunnerError('retirement-denied', 'Retirement was not approved; no retirement was applied.')
    return _retire_session(alias, cwd)


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
    if mapping.get("hosted"):
        record_file = directory / "session.yml"
        record = yaml.safe_load(record_file.read_text())
        if not record.get("retirement"):
            write_yaml_durably(record_file, {**record, "retirement": {"mapping": mapping, "member": None}})
        return {"alias": alias, "retire_status": "retired", "member": None}
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
