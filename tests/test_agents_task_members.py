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
