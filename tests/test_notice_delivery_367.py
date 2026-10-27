"""Task 367: notices reach the parent that must handle them, once, without loss."""
from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from agent_swarm.notices import needs_parent
from graphtraj.configuration.project_configuration import runner_directory
from graphtraj.execution import main_continuity as mc


SESSION = str(uuid4())


def _claude(runner: Path) -> dict:
    return {'runtime': 'claude', 'session': SESSION, 'runner': str(runner)}


@pytest.mark.parametrize(('outcome', 'facts', 'expected'), [
    ('completed', {}, True),                                    # leaf child: stall guard
    ('completed', {'active_members': 2}, False),                # routine Leader round
    ('completed', {'active_members': 1, 'submitted': True}, True),
    ('completed', {'active_members': 1, 'pending_requests': 1}, True),
    ('completed', {'active_members': 1, 'budget': True}, True),
    ('interrupted', {'active_members': 1}, True),
    ('failed', {'active_members': 1}, True),
    ('runtime-error', {'active_members': 1}, True),
])
def test_only_rounds_the_parent_must_handle_notify(outcome: str, facts: dict, expected: bool) -> None:
    assert needs_parent(outcome, **facts) is expected


def test_main_created_root_end_is_queued_for_the_current_main(tmp_path: Path) -> None:
    """Q1: a core child that Main created writes its end into Main's queue."""
    from graphtraj.interfaces.agents import GraphTrajAgents

    runner = runner_directory(tmp_path)
    mc.claim_main(runner, _claude(runner), 'claude:first-control')
    agents = GraphTrajAgents.__new__(GraphTrajAgents)
    agents.root = tmp_path
    notice = {'parent': None, 'agent': 'agent-probe', 'execution': 'e1', 'session': 's',
              'outcome': 'completed', 'body': 'PONG', 'error': None,
              'creator': {'host': 'claude-native', 'agent': None, 'session': SESSION}}
    assert agents._main_notice(notice) == 'queued'
    failed = {**notice, 'execution': 'e2', 'outcome': 'failed', 'body': None,
              'error': {'code': 'X', 'message': 'broke'}}
    assert agents._main_notice(failed) == 'queued'
    # A grandchild or a root another caller created is not Main's to handle.
    assert agents._main_notice({**notice, 'parent': 'agent-other'}) is False
    assert agents._main_notice({**notice, 'creator': {'agent': None, 'session': 'other'}}) is False
    claimed = mc.claim_notices(runner, 'claude', SESSION)
    assert [(item['id'], item['event']['message']) for item in claimed] == [
        ('e1:completed', 'PONG'), ('e2:failed', 'broke')]


def test_a_continued_main_receives_root_ends_after_the_handover(tmp_path: Path) -> None:
    from graphtraj.interfaces.agents import GraphTrajAgents

    runner = runner_directory(tmp_path)
    mc.claim_main(runner, _claude(runner), 'claude:first-control')
    successor = str(uuid4())
    mc.claim_main(runner, {**_claude(runner), 'session': successor}, 'claude:first-control')
    agents = GraphTrajAgents.__new__(GraphTrajAgents)
    agents.root = tmp_path
    assert agents._main_notice({
        'parent': None, 'agent': 'agent-probe', 'execution': 'e1', 'session': 's',
        'outcome': 'completed', 'body': 'PONG', 'error': None,
        'creator': {'host': 'claude-native', 'agent': None, 'session': SESSION}}) == 'queued'
    assert mc.claim_notices(runner, 'claude', SESSION) == []
    assert [item['id'] for item in mc.claim_notices(runner, 'claude', successor)] == ['e1:completed']


def test_push_and_tool_result_never_show_one_notice_twice(tmp_path: Path) -> None:
    """Q3 reproduction: the push and the next tool result both read; only one gets it."""
    runner = runner_directory(tmp_path)
    mc.queue_notice(runner, _claude(runner), {'alias': 'child', 'event': 'completed',
                                               'message': 'PONG', 'execution': 'e1'})
    pushed = mc.claim_notices(runner, 'claude', SESSION)      # the mod's push claims
    attached = mc.claim_notices(runner, 'claude', SESSION)    # the next agents/tasks result
    assert [item['event']['message'] for item in pushed + attached] == ['PONG']


def test_a_failed_push_requeues_the_same_notice_once(tmp_path: Path) -> None:
    runner = runner_directory(tmp_path)
    mc.queue_notice(runner, _claude(runner), {'alias': 'child', 'event': 'completed',
                                               'message': 'PONG', 'execution': 'e1'})
    claimed = mc.claim_notices(runner, 'claude', SESSION)
    ids = [item['id'] for item in claimed]
    assert mc.requeue_notices(runner, 'claude', SESSION, ids) == 1
    assert mc.requeue_notices(runner, 'claude', SESSION, ids) == 0   # already waiting
    retried = mc.claim_notices(runner, 'claude', SESSION)
    assert [item['id'] for item in retried] == ['e1:completed']
    assert mc.claim_notices(runner, 'claude', SESSION) == []


def test_two_overlapping_completions_are_each_delivered_once(tmp_path: Path) -> None:
    runner = runner_directory(tmp_path)
    for execution in ('e1', 'e2'):
        mc.queue_notice(runner, _claude(runner), {'alias': execution, 'event': 'completed',
                                                   'message': execution, 'execution': execution})
    first = mc.claim_notices(runner, 'claude', SESSION)
    mc.queue_notice(runner, _claude(runner), {'alias': 'e3', 'event': 'completed',
                                               'message': 'e3', 'execution': 'e3'})
    # A retried delivery of an already queued event adds nothing.
    mc.queue_notice(runner, _claude(runner), {'alias': 'e1', 'event': 'completed',
                                               'message': 'e1', 'execution': 'e1'})
    second = mc.claim_notices(runner, 'claude', SESSION)
    assert [item['id'] for item in first + second] == ['e1:completed', 'e2:completed', 'e3:completed']


def test_an_end_returned_by_wait_is_not_pushed(tmp_path: Path) -> None:
    runner = runner_directory(tmp_path)
    mc.acknowledge_ends(runner, 'claude', SESSION, ['e1'])          # wait returned before the notice
    mc.queue_notice(runner, _claude(runner), {'alias': 'c', 'event': 'completed',
                                               'message': 'x', 'execution': 'e1'})
    mc.queue_notice(runner, _claude(runner), {'alias': 'c', 'event': 'report-submitted',
                                               'message': 'report', 'execution': 'e1'})
    assert [item['event']['event'] for item in mc.claim_notices(runner, 'claude', SESSION)] == [
        'report-submitted']


def test_wait_and_status_results_name_the_end_they_show() -> None:
    core = {'state': 'standby', 'last_result': {'id': 'e1'}}
    member = {'activity': 'idle', 'execution_id': 'e2'}
    status = {'aliases': [{'activity': 'idle', 'execution_id': 'e3'}]}
    running = {'state': 'active', 'last_result': {'id': 'e0'}}
    assert mc.shown_ends(core) == ['e1']
    assert mc.shown_ends(member) == ['e2']
    assert mc.shown_ends(status) == ['e3']
    assert mc.shown_ends(running) == []
    assert mc.shown_ends({'activity': 'running', 'execution_id': 'e4'}) == []


def test_runner_end_waits_for_registered_or_running_members(tmp_path: Path) -> None:
    """Stall guard input: a registered child Batch or an admitted child keeps the round quiet."""
    from graphtraj.execution.runner_control import active_members

    sessions = tmp_path / 'sessions'
    (sessions / 'leader').mkdir(parents=True)
    assert active_members(tmp_path, 'leader') == 0
    (sessions / 'leader' / 'child-registration.yml').write_text('execution_id: x\n')
    assert active_members(tmp_path, 'leader') == 1
    (sessions / 'engineer').mkdir()
    (sessions / 'engineer' / 'launch.yml').write_text(yaml.safe_dump(
        {'operation': 'launch', 'mapping': {'alias': 'engineer', 'parent': 'leader'}}))
    assert active_members(tmp_path, 'leader') == 2
    assert active_members(tmp_path, 'engineer') == 0


def test_a_waiting_parent_keeps_the_end_it_is_returning(tmp_path: Path) -> None:
    import time

    from graphtraj.execution.runner_control import awaited, mark_awaited

    assert not awaited(tmp_path, 'e1')
    mark_awaited(tmp_path, 'e1', time.time() + 5)
    assert awaited(tmp_path, 'e1')
    assert not awaited(tmp_path, 'e2')          # a later execution's end is still delivered
    mark_awaited(tmp_path, 'e1', time.time() - 1)
    assert not awaited(tmp_path, 'e1')


def test_budget_notice_goes_only_to_the_observing_sessions_parent(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Q4: the Leader's monitor never flushes the Engineer's notices to Main."""
    from graphtraj.execution import execution_budget, runner_control

    monitor = execution_budget.ExecutionBudgetMonitor(tmp_path, '1', 'task')
    pending = [{'key': 'k-engineer', 'message': 'm1', 'delivered': False, 'observer': 'engineer'},
               {'key': 'k-leader', 'message': 'm2', 'delivered': False, 'observer': 'leader'},
               {'key': 'k-legacy', 'message': 'm3', 'delivered': False}]
    sent: list[tuple[str, str]] = []
    received: list[list[str]] = []

    def notify(directory: Path, message: str, identity: dict, **_: object) -> dict:
        sent.append((directory.name, identity['key']))
        return {'delivery': 'received'}

    monkeypatch.setattr(runner_control, 'notify_direct_parent', notify)
    monkeypatch.setattr(monitor, 'deliver_notices', lambda deliver: received.append(deliver(pending)))
    for alias, parent in (('leader', None), ('engineer', 'leader')):
        directory = tmp_path / 'runner' / 'sessions' / alias
        directory.mkdir(parents=True)
        (directory / 'launch.yml').write_text(yaml.safe_dump({'mapping': {
            'alias': alias, 'parent': parent, 'parent_connection': {'runtime': 'claude'}}}))
    monitor.deliver_parent_notices(tmp_path / 'runner' / 'sessions' / 'leader')
    monitor.deliver_parent_notices(tmp_path / 'runner' / 'sessions' / 'engineer')
    assert sent == [('leader', 'k-leader'), ('leader', 'k-legacy'), ('engineer', 'k-engineer'),
                    ('engineer', 'k-legacy')]
    assert received[0] == ['k-leader', 'k-legacy'] and received[1] == ['k-engineer', 'k-legacy']


def test_a_failed_parent_notice_attempt_is_always_recorded(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """U2: an unexpected exception leaves a not-delivered record, not silence."""
    from graphtraj.execution import runner_control

    directory = tmp_path / 'runner' / 'sessions' / 'engineer'
    directory.mkdir(parents=True)

    def broken(*_: object, **__: object) -> None:
        raise KeyError('mapping')

    monkeypatch.setattr(runner_control, 'read_alias_mapping', broken)
    record = runner_control.notify_direct_parent(directory, 'm', {'type': 'execution-budget-exceeded'})
    assert record['delivery'] == 'not-delivered'
    lines = (directory / 'parent-notices.jsonl').read_text().splitlines()
    assert json.loads(lines[-1])['delivery'] == 'not-delivered'


def test_a_failed_host_queue_keeps_the_end_readable(tmp_path: Path) -> None:
    """A host receiver that raises never hides the body from wait/status."""
    from agent_swarm import AgentControl

    def broken(notice: dict) -> bool:
        raise OSError('queue unavailable')

    control = AgentControl(tmp_path, {}, event_receiver=broken)
    record = {'agent': 'agent-a', 'name': 'a', 'runtime': 'claude', 'host': 'h', 'parent': None,
              'creator': {'host': 'h', 'agent': None, 'session': 's'}, 'session': 'n', 'sessions': ['n'],
              'settings': {}, 'created_at': 0.0, 'retired_at': None, 'executions': [{
                  'id': 'e1', 'state': 'running', 'session': 'n', 'requests': [],
                  'process': {'worker_pid': os.getpid()},
                  'replies': {}}]}
    path = tmp_path / 'control' / 'agents' / 'agent-a.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record))
    from agent_swarm.control import ExecutionEvents
    ExecutionEvents(control, 'agent-a', 'e1').finished('completed', last_message='PONG')
    document = control._document(json.loads(path.read_text()))
    assert document['last_result']['notification'] == 'unavailable'
    assert document['last_result']['last_message'] == 'PONG'
