"""agents controls Task members and shows Main only its own dispatched hierarchy."""

from __future__ import annotations

from pathlib import Path

import yaml

from graphtraj.execution.runner_status import read_alias_mapping
from test_managed_sessions import ManagedProject, launch_document, managed_project, observe  # noqa: F401


def _dispatched_by(root: Path, alias: str, session: str) -> None:
    """Record the native Main that dispatched a top-level member, as launch does."""
    mapping_file = root / '.graphtraj/runner/sessions' / alias / 'mapping.yml'
    mapping = yaml.safe_load(mapping_file.read_text(encoding='utf-8'))
    mapping['parent_connection'] = {'runtime': 'codex', 'session': session}
    mapping_file.write_text(yaml.safe_dump(mapping), encoding='utf-8')


def test_main_default_status_lists_only_its_dispatched_members(
    managed_project: ManagedProject,
) -> None:
    """Another Main's member and an unreadable record stay out of the default view."""
    root, _, call, _ = managed_project
    own   = call('launch', launch_document('hold', 'first-probe'))['tasks'][0]['alias']
    other = call('launch', launch_document('hold', 'second-probe'))['tasks'][0]['alias']
    _dispatched_by(root, own, 'main-a')
    _dispatched_by(root, other, 'main-b')
    broken = root / '.graphtraj/runner/sessions/broken-history'
    broken.mkdir()
    (broken / 'mapping.yml').write_text('not: a mapping\n', encoding='utf-8')

    status = call('agents', ['status', {}, 'main-a'])
    nodes  = status['result']['task_sessions']['agents']
    assert [node['alias'] for node in nodes] == [own]
    assert not status['failed'] and 'error' not in nodes[0]

    # The other Main's member is still readable by explicit reference.
    explicit = call('agents', ['status', {'agent': other}, 'main-a'])
    assert explicit['result']['aliases'][0]['alias'] == other
    for alias in (own, other):
        call('interrupt', [alias])


def test_task_member_agent_reference_uses_its_session_controls(
    managed_project: ManagedProject,
) -> None:
    """A member's core reference reads, answers, waits for and continues the same Session."""
    root, _, call, _ = managed_project
    alias   = call('launch', launch_document('request:approval'))['tasks'][0]['alias']
    observe(call, alias, 'running', waiting_for='runtime-request')
    mapping = read_alias_mapping(root / '.graphtraj/runner', alias)[0]
    agent   = mapping['agent']
    assert agent.startswith('agent-')

    status = call('agents', ['status', {'agent': agent}, 'main-a'])
    assert status['agent'] == agent and status['result']['aliases'][0]['alias'] == alias

    # A pending native request ends a wait; the reply goes through agents too.
    waited = call('agents', ['wait', {'agent': agent, 'timeout_seconds': 10}, 'main-a'])
    assert waited['result']['timed_out'] is False
    request, = call('agents', ['requests', {'agent': agent}, 'main-a'])['result']['requests']
    call('agents', ['reply', {'agent': agent, 'request': request, 'response': {'decision': 'decline'}}, 'main-a'])
    waited = call('agents', ['wait', {'agent': alias, 'timeout_seconds': 10}, 'main-a'])
    assert waited['result']['timed_out'] is False and waited['result']['activity'] == 'idle'

    sent = call('agents', ['send', {'agent': agent, 'message': 'hold'}, 'main-a'])
    assert sent['result']['send_status'] == 'sent'
    assert read_alias_mapping(root / '.graphtraj/runner', alias)[0]['session'] == mapping['session']
    observe(call, alias, 'running')
    resumed = call('agents', ['resume', {'agent': alias, 'message': 'hold'}, 'main-a'])
    assert resumed['result']['send_status'] == 'sent'
    call('agents', ['interrupt', {'agent': agent}, 'main-a'])


def test_default_tree_keeps_current_seats_and_bounds_messages(tmp_path: Path, monkeypatch) -> None:
    """Main sees current seats and their subtrees; a member sees its own subtree."""
    from graphtraj.execution import runner_status
    from graphtraj.interfaces.agents import PREVIEW_CHARACTERS, _preview

    main = {'runtime': 'codex', 'session': 'main-a'}
    records = {
        'current-leader': {'parent': None, 'parent_connection': main},
        'replaced-leader': {'parent': None, 'parent_connection': main},
        'completed-member': {'parent': None, 'parent_connection': main},
        'current-engineer': {'parent': 'current-leader'},
        'old-engineer': {'parent': 'replaced-leader'},
    }
    monkeypatch.setattr(runner_status, 'discover_runner_directory', lambda cwd: tmp_path)
    monkeypatch.setattr(runner_status, '_recorded_sessions', lambda runner: (records, []))
    monkeypatch.setattr(runner_status, '_status_alias', lambda runner, alias, **kwargs: (
        {'error': {'code': 'x'}} if alias == 'replaced-leader' else {'activity': 'idle'}))
    monkeypatch.setattr(runner_status, 'caller_alias', lambda runner: None)
    tree = runner_status.status_tree(tmp_path, owner_connection=main, current_members={'current-leader'})
    assert [node['alias'] for node in tree.document['agents']] == ['current-leader', 'current-engineer']
    assert tree.succeeded  # the replaced Leader's old error is not in the default view
    monkeypatch.setattr(runner_status, 'caller_alias', lambda runner: 'current-engineer')
    assert [node['alias'] for node in runner_status.status_tree(tmp_path).document['agents']] == ['current-engineer']

    long = 'm' * 1000
    bounded = _preview({'agents': [{'last_agent_message': long, 'summary': long}]})['agents'][0]
    assert len(bounded['last_agent_message']) == PREVIEW_CHARACTERS + 1 and bounded['summary'] == long


def test_current_members_follow_the_current_seat_holders(tmp_path: Path, monkeypatch) -> None:
    """Handed-over and retired Leaders and their Engineers are history, not current seats.

    The records mirror Task 344 (team_leader standby, _3 and _4 retired, _5
    current) and 337 (two unretired top-level Leaders registered in turn).
    """
    from graphtraj.execution import desktop_activity
    from graphtraj.execution.runner_models import RunnerError

    sessions = tmp_path / 'runner/sessions'
    records = {
        # alias: (task, role, parent, live)
        'tl': ('344', 'team-leader', None, True), 'e': ('344', 'engineer', 'tl', True),
        'tl3': ('344', 'team-leader', None, False), 'e2': ('344', 'engineer', 'tl3', True),
        'tl4': ('344', 'team-leader', None, False), 'e3': ('344', 'engineer', 'tl4', True),
        'tl5': ('344', 'team-leader', None, True), 'e4': ('344', 'engineer', 'tl5', True),
        'e5': ('344', 'engineer', 'tl5', True),
        'c-tl': ('337', 'team-leader', None, True), 'c-e': ('337', 'engineer', 'c-tl', True),
        'c-tl2': ('337', 'team-leader', None, True),
    }
    for alias, (_, _, _, live) in records.items():
        (sessions / alias).mkdir(parents=True)
        if live:
            (sessions / alias / 'mapping.yml').touch()

    def mapping(runner, alias):
        if alias not in records:
            raise RunnerError('unknown-alias', alias)
        task, role, parent, _ = records[alias]
        return {'task_id': task, 'team_generation': 1, 'role': role, 'parent': parent}, sessions / alias

    monkeypatch.setattr(desktop_activity, 'read_alias_mapping', mapping)

    def team(task: str, seats: dict) -> tuple[Path, dict]:
        directory = tmp_path / 'tasks' / task
        (directory / 'teams/1').mkdir(parents=True)
        (directory / 'teams/1/team.yml').write_text(yaml.safe_dump({
            'team_ordinal': 1, 'status': 'active', 'current_round': 1, 'started_at': 'x',
            'members': {name: {'role': role, 'session_ref': ref} for name, (role, ref) in seats.items()},
        }, sort_keys=False))
        return directory, {'active_team_ordinal': 1}

    # Retirement empties a seat; a later Leader takes a seat of its own.
    first = team('344', {'team_leader': ('team-leader', 'tl'), 'engineer': ('engineer', 'e'),
                         'tl3': ('team-leader', None), 'e2': ('engineer', 'e2'),
                         'tl4': ('team-leader', None), 'e3': ('engineer', 'e3'),
                         'tl5': ('team-leader', 'tl5'), 'e4': ('engineer', 'e4'), 'e5': ('engineer', 'e5')})
    order = {alias: index for index, alias in enumerate(['tl', 'e', 'tl3', 'e2', 'tl4', 'e3', 'tl5', 'e4', 'e5'])}
    aliases, current = desktop_activity._task_aliases(*first, tmp_path, (order, {'tl'}))
    assert current == {'tl5', 'e4', 'e5'}
    assert {'tl', 'e', 'e2', 'e3'} <= aliases

    # The Worldline registration order, not the seat position or alias, picks the holder.
    second = team('337', {'team_leader': ('team-leader', 'c-tl'), 'engineer': ('engineer', 'c-e'),
                          'c-tl2': ('team-leader', 'c-tl2')})
    registered = {'c-tl': 1, 'c-e': 2, 'c-tl2': 3}
    assert desktop_activity._task_aliases(*second, tmp_path, (registered, {'c-tl'}))[1] == {'c-tl2'}
    reversed_order = {'c-tl': 3, 'c-e': 4, 'c-tl2': 1}
    assert desktop_activity._task_aliases(*second, tmp_path, (reversed_order, {'c-tl2'}))[1] == {'c-tl', 'c-e'}
    # Parallel top-level members outside the lead role all stay current.
    assert desktop_activity._task_aliases(*second, tmp_path, (registered, set()))[1] == {'c-tl', 'c-e', 'c-tl2'}


def test_registration_order_reads_the_worldline_member_evidence(tmp_path: Path, monkeypatch) -> None:
    """Registration events name the Session by its mapping evidence; later ones rank higher."""
    from graphtraj.execution import desktop_activity
    from graphtraj.graph import delivery_worldline

    events = [
        {'event': 'team-started', 'evidence_refs': ['.graphtraj/runner/sessions/tl/mapping.yml']},
        {'event': 'team-round-accepted', 'evidence_refs': ['.graphtraj/runner/sessions/x/mapping.yml']},
        {'event': 'team-member-started', 'evidence_refs': ['.graphtraj/runner/sessions/tl2/mapping.yml']},
    ]
    monkeypatch.setattr(delivery_worldline, 'read_worldline', lambda state: events)
    assert desktop_activity.registration_order(tmp_path) == ({'tl': 0, 'tl2': 2}, {'tl'})
