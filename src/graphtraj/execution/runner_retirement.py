"""Retire stopped task members without deleting their Session evidence."""

from __future__ import annotations

from pathlib import Path

import yaml

from graphtraj.execution.runner_heartbeat import execution_start_lock
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.execution.runner_models import Project, RunnerError
from graphtraj.execution.approved_recovery import review_proposal
from graphtraj.execution.runner_status import (
    _read_alias_record, _terminal_unestablished_launch, _unestablished_root_launch,
    _unstarted_allocation, caller_alias, is_direct_owner, read_active_legacy_hosted_mapping,
    read_alias_mapping, read_retired_legacy_hosted_mapping, require_stopped_subtree,
    retained_session_directories, session_record_directory,
)
from graphtraj.graph.delivery_state import apply_delivery_state_request, read_team
from graphtraj.graph.delivery_worldline import read_worldline
from graphtraj.graph.ticket_graph import _load_states
from graphtraj.workspace.runner_project import discover_project


def retire_session(alias: str, cwd: Path, *, replacement: dict | None = None) -> dict:
    """Review and retire a stopped member inside this public operation.

    The replacement caller supplies its concrete registration as part of the
    same review. This context is not a public tool argument or approval flag.
    A withdrawn hosted Main/checker record takes the limited legacy branch;
    every current record keeps the existing path unchanged.
    """
    project = discover_project(cwd, require_clean_integration=False)
    legacy = read_active_legacy_hosted_mapping(project.runner_directory, alias)
    if legacy is None:
        # A record already retired by this branch reports the same result again.
        legacy = read_retired_legacy_hosted_mapping(project.runner_directory, alias)
    if legacy is not None:
        if replacement is not None:
            raise RunnerError(
                'unsupported-operation', 'A withdrawn hosted record cannot be replaced.')
        mapping = legacy
        directory = session_record_directory(project.runner_directory, alias)
    else:
        mapping, directory = read_alias_mapping(project.runner_directory, alias)
        require_stopped_subtree(project.runner_directory, alias)
    caller = caller_alias(project.runner_directory)
    if not is_direct_owner(caller, mapping):
        from graphtraj.runtimes.replacement import caller_runtime

        from graphtraj.execution.runner_status import caller_runtime_name

        runtime = caller_runtime_name(project.runner_directory, caller) or caller_runtime()
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
    if legacy is not None:
        return _retire_legacy_session(alias, cwd)
    return _retire_session(alias, cwd)


def _retire_session(alias: str, cwd: Path) -> dict:
    """Check the stopped subtree under the existing startup lock, then retire."""
    project = discover_project(cwd, require_clean_integration=False)
    with execution_start_lock(project.runner_directory):
        return retire_stopped_session(project, alias)


def _retire_legacy_session(alias: str, cwd: Path) -> dict:
    """Retire a withdrawn hosted record under the existing startup lock."""
    project = discover_project(cwd, require_clean_integration=False)
    mapping = read_active_legacy_hosted_mapping(project.runner_directory, alias)
    if mapping is None:
        mapping = read_retired_legacy_hosted_mapping(project.runner_directory, alias)
    if mapping is None:
        raise RunnerError('operation-failed', 'The requested Agent alias mapping is invalid.')
    with execution_start_lock(project.runner_directory):
        return retire_legacy_hosted_session(project, alias, mapping)


def retire_legacy_hosted_session(project: Project, alias: str, mapping: dict) -> dict:
    """Retire a withdrawn hosted Main/checker mapping that is proven unused.

    The implementation that registered these mappings was withdrawn, so the
    record is not a current Runner identity. Retirement is fail-closed: it
    proceeds only while every condition holds, and any unmet or unverifiable
    condition leaves all records untouched and names the reason. It reuses the
    existing evidence mechanism, so it removes only the active mapping while
    the record keeps its native evidence, and it never signals a process or a
    native Session.
    """
    runner_directory = project.runner_directory
    directory        = session_record_directory(runner_directory, alias)
    reasons: list[str] = []

    # A live owner process still uses this record, so it is not obsolete.
    worker_pid  = mapping.get('worker_pid')
    runtime_pid = mapping.get('runtime_pid')
    if not _positive_int(worker_pid) or not _positive_int(runtime_pid):
        reasons.append('owner-process-unknown')
    elif _owner_processes_alive(worker_pid, runtime_pid):
        reasons.append('owner-process-alive')

    # Current Main integration stays in main-sessions records; a recorded
    # native Session one still references blocks this retirement.
    session = mapping.get('session')
    if session is not None and _main_association_references(runner_directory, session):
        reasons.append('main-association-active')

    # Another current record that names this alias as its parent still depends
    # on it. A record that already retired keeps its historical parent without
    # blocking, and an unreadable or unparented record cannot prove exclusion.
    descendant, unknown = _descendant_state(runner_directory, alias)
    if unknown:
        reasons.append('descendant-state-unknown')
    elif descendant is not None:
        reasons.append('descendant-record-present:' + descendant)

    if reasons:
        raise RunnerError(
            'retirement-refused',
            'The withdrawn hosted record cannot be retired: ' + ', '.join(reasons) + '.',
        )

    # Reuse the existing evidence mechanism: retire the active mapping in place
    # and keep the original mapping as evidence. This record owns no Trace
    # directory, so it is not relocated.
    record_file = directory / 'session.yml'
    record = yaml.safe_load(record_file.read_text(encoding='utf-8'))
    if not isinstance(record, dict):
        raise RunnerError(
            'retirement-refused', 'The withdrawn hosted record cannot be read.')
    if record.get('retirement') is None:
        write_yaml_durably(
            record_file, {**record, 'retirement': {'member': None, 'mapping': mapping}})
    (directory / 'mapping.yml').unlink(missing_ok=True)
    return {'alias': alias, 'retire_status': 'retired', 'member': None,
            'session': session, 'team_ordinal': None,
            'worktree_path': mapping.get('worktree_path')}


def _positive_int(value: object) -> bool:
    """Whether a value is a usable positive process identifier."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _owner_processes_alive(worker_pid: int, runtime_pid: int) -> bool:
    """Whether either recorded owner process identifier still resolves.

    Reuses the existing cleanup probe. Imported here because cleanup already
    imports this module at load time.
    """
    from graphtraj.execution.runner_cleanup import _process_alive

    return _process_alive(worker_pid) or _process_alive(runtime_pid)


def _main_association_references(runner_directory: Path, session: str) -> bool:
    """Whether any current Main association records this native Session."""
    main_root = runner_directory / 'main-sessions'
    records = [*main_root.glob('*/session.yml'), *main_root.glob('*/checks/*/session.yml')]
    for record_file in records:
        try:
            record = yaml.safe_load(record_file.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, yaml.YAMLError):
            # An unreadable Main association cannot prove exclusion.
            return True
        if isinstance(record, dict) and record.get('session') == session:
            return True
    return False


def _record_is_retired(directory: Path) -> bool:
    """Whether a record's active mapping is gone and its retirement is retained.

    Retirement removes only the active mapping, so a record that still has a
    mapping is current whatever directory it was read from; the retained
    retirement marker proves the retired state instead of the location.
    """
    if (directory / 'mapping.yml').is_file():
        return False
    try:
        record = yaml.safe_load((directory / 'session.yml').read_text(encoding='utf-8'))
    except (OSError, UnicodeError, yaml.YAMLError):
        return False
    return bool(isinstance(record, dict) and record.get('retirement'))


def _descendant_state(runner_directory: Path, alias: str) -> tuple[str | None, bool]:
    """Return the first current record naming this alias as parent, and uncertainty.

    The scan mirrors the stopped-subtree check: an allocation that never
    established an identity is skipped, a record that already retired keeps its
    historical parent without blocking, and an unreadable or unparented record
    cannot prove exclusion and is reported as unknown.
    """
    session_root = runner_directory / 'sessions'
    if session_root.is_symlink() or not session_root.is_dir():
        return None, False
    entries = list(session_root.iterdir()) + retained_session_directories(runner_directory)
    for path in entries:
        name = path.parent.name if path.name == 'runner' else path.name
        if name == alias:
            continue
        if not path.is_dir() and not path.is_symlink():
            continue
        if (_unstarted_allocation(path) or _terminal_unestablished_launch(path)
                or _unestablished_root_launch(path)):
            continue
        try:
            record, directory = _read_alias_record(runner_directory, name)
        except RunnerError:
            return None, True
        if not isinstance(record, dict) or 'parent' not in record:
            return None, True
        if record['parent'] == alias and not _record_is_retired(directory):
            return name, False
    return None, False


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
