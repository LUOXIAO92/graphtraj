"""Task 372: a stopped parent is not resumed by its children (U1); one end per parent (Q7)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from graphtraj.execution import execution_budget as budgets
from graphtraj.execution import runner_control, runner_status


BODY = '''---
difficulty: medium
difficulty_reason: Research and evidence
execution_budget:
  estimated_minutes: {research: 9, total: 10}
  planned_sessions: {researcher: 1}
  correction_rounds: 1
  estimation_note: One actual author
  on_exceed: Notify the parent
---
'''
MAPPINGS = {
    'leader': {'alias': 'leader', 'task_id': '153', 'parent': None, 'parent_connection': None},
    'engineer': {'alias': 'engineer', 'task_id': '153', 'parent': 'leader', 'session': 's-e',
                 'execution_id': 'e1'},
    'analyst': {'alias': 'analyst', 'task_id': '153', 'parent': 'leader', 'session': 's-a',
                'execution_id': 'a1'},
}


@pytest.fixture
def runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Session records of one Task: a root Leader and two direct children."""
    runner = tmp_path / 'runner'
    for alias, mapping in MAPPINGS.items():
        (runner / 'sessions' / alias).mkdir(parents=True)
        (runner / 'sessions' / alias / 'launch.yml').write_text(
            yaml.safe_dump({'operation': 'launch', 'mapping': mapping}))

    def read(directory: Path, alias: str) -> tuple[dict, Path]:
        return dict(MAPPINGS[alias]), directory / 'sessions' / alias

    monkeypatch.setattr(runner_status, 'read_alias_mapping', read)
    monkeypatch.setattr(runner_control, 'read_alias_mapping', read)
    return runner


def stopped_monitor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> budgets.ExecutionBudgetMonitor:
    path = tmp_path / 'task'
    path.mkdir()
    (path / 'task.yml').write_text('current_definition: task.md\n')
    (path / 'task.md').write_text(BODY)
    monitor = budgets.execution_budget_monitor(path, '153', 'research')
    monitor.record_session('researcher', 'researcher')
    monitor.observer = 'engineer'
    before = yaml.safe_load((path / 'execution-budget.yml').read_text())
    with monkeypatch.context() as patch:
        patch.setattr(budgets.time, 'time', lambda: before['started_at'] + 20 * 60)
        patch.setattr(budgets.random, 'random', lambda: .999)
        assert monitor.check('researcher', 'researcher')
    return monitor


def records(directory: Path) -> list[dict]:
    path = directory / 'parent-notices.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


def test_stopped_parent_gets_held_budget_notices_once_after_continuation(
        tmp_path: Path, runner: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """U1: no send while the Task is stopped; each notice exactly once after it continues."""
    sent: list[str] = []

    def notify(directory: Path, message: str, identity: dict, **_: object) -> dict:
        sent.append(identity['key'])
        return {'delivery': 'received'}

    monkeypatch.setattr(runner_control, 'notify_direct_parent', notify)
    monitor = stopped_monitor(tmp_path, monkeypatch)
    keys = [notice['key'] for notice in monitor.pending_parent_notices()]
    assert keys
    engineer = runner / 'sessions' / 'engineer'
    assert monitor.deliver_parent_notices(engineer) is True     # held, the Worker stops retrying
    assert sent == []
    assert [notice['key'] for notice in monitor.pending_parent_notices()] == keys
    monitor.continue_after_stop()
    assert monitor.deliver_parent_notices(engineer) is False
    monitor.deliver_parent_notices(engineer)                    # a repeated or retried delivery
    assert sent == keys
    assert monitor.pending_parent_notices() == []


def test_a_parent_of_another_task_still_gets_the_notice_while_stopped(
        tmp_path: Path, runner: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The hold covers only a parent this same budget stop stopped."""
    sent: list[str] = []
    monkeypatch.setitem(MAPPINGS, 'leader', dict(MAPPINGS['leader'], task_id='other'))
    monkeypatch.setattr(runner_control, 'notify_direct_parent',
                        lambda directory, message, identity, **_: sent.append(identity['key'])
                        or {'delivery': 'received'})
    monitor = stopped_monitor(tmp_path, monkeypatch)
    assert monitor.deliver_parent_notices(runner / 'sessions' / 'engineer') is False
    assert sent and monitor.pending_parent_notices() == []


def _deliver_received(directory: Path, message: str, identity: dict) -> dict:
    """The ordinary event path, acknowledged, with its existing record."""
    record = {'at': 0, 'identity': dict(identity), 'delivery': 'received', 'parent': 'leader',
              'notice': json.dumps({'message': message})}
    runner_control._append_notice_record(directory, record)
    DELIVERED.append((directory.name, identity['type'], message))
    return record


DELIVERED: list[tuple[str, str, str]] = []


@pytest.mark.parametrize('terminal', [
    {'outcome': 'completed'},
    {'outcome': 'failed', 'error': {'code': 'X', 'message': 'broke'}},
    {'outcome': 'interrupted', 'budget_stopped': True},
])
def test_a_driver_reported_end_appears_once_on_the_parent(
        runner: Path, monkeypatch: pytest.MonkeyPatch, terminal: dict) -> None:
    """Q7: the Driver's aggregate keeps the end; the child's own notice is held, not pushed."""
    DELIVERED.clear()
    monkeypatch.setattr(runner_control, 'deliver_parent_event', _deliver_received)
    engineer = runner / 'sessions' / 'engineer'
    receipt = runner_control.deliver_execution_end(
        engineer, MAPPINGS['engineer'], terminal, parent_input=True, driver_reports_end=True)
    # A budget stop also withholds the Driver's turn, so that end waits for the stop.
    assert receipt['delivery'] == 'retained'
    assert receipt['held'] == ('budget-stop' if terminal.get('budget_stopped') else 'driver')
    assert DELIVERED == []
    held = runner_control.held_ends(runner, 'leader')
    assert [(directory.name, record['identity']['execution_id']) for directory, record in held] == [
        ('engineer', 'e1')]
    runner_control.mark_ends_aggregated(held)       # the aggregate turn was taken
    assert runner_control.held_ends(runner, 'leader') == []
    runner_control.deliver_held_ends(runner_control.held_ends(runner, 'leader'))
    assert DELIVERED == []                          # nothing is shown a second time


def test_a_failed_aggregate_or_continuation_delivers_each_held_end_once(
        runner: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No held end is lost: its own delivery follows, and a retry repeats nothing."""
    DELIVERED.clear()
    monkeypatch.setattr(runner_control, 'deliver_parent_event', _deliver_received)
    runner_control.deliver_execution_end(
        runner / 'sessions' / 'engineer', MAPPINGS['engineer'], {'outcome': 'completed'},
        parent_input=True, driver_reports_end=True)
    # A budget-stopped child of a same-Task parent is held without a Driver.
    runner_control.deliver_execution_end(
        runner / 'sessions' / 'analyst', MAPPINGS['analyst'],
        {'outcome': 'interrupted', 'budget_stopped': True}, parent_input=True)
    assert [record['held'] for _, record in runner_control.held_ends(runner, 'leader')] == [
        'budget-stop', 'driver']
    assert DELIVERED == []
    runner_control.deliver_held_ends(runner_control.held_ends(runner, 'leader'))
    runner_control.deliver_held_ends(runner_control.held_ends(runner, 'leader'))   # repeated
    assert sorted((alias, kind) for alias, kind, _ in DELIVERED) == [
        ('analyst', 'interrupted'), ('engineer', 'completed')]
    assert all(message.startswith('Session execution ended:') for _, _, message in DELIVERED)


def test_an_unheld_end_is_delivered_as_before(runner: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-Driver child's failure, not caused by a budget stop, still reaches its parent."""
    DELIVERED.clear()
    monkeypatch.setattr(runner_control, 'deliver_parent_event', _deliver_received)
    receipt = runner_control.deliver_execution_end(
        runner / 'sessions' / 'engineer', MAPPINGS['engineer'],
        {'outcome': 'failed', 'error': {'code': 'X', 'message': 'broke'}}, parent_input=True)
    assert receipt['delivery'] == 'received'
    assert [(alias, kind) for alias, kind, _ in DELIVERED] == [('engineer', 'failed')]


def test_a_session_waits_only_for_the_notices_it_delivers(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """6c: another timed Session's undelivered notice never keeps this Worker's delivery open."""
    monitor = stopped_monitor(tmp_path, monkeypatch)              # observed by 'engineer'
    keys = [notice['key'] for notice in monitor.pending_parent_notices()]
    assert [notice['key'] for notice in monitor.pending_parent_notices('engineer')] == keys
    assert monitor.pending_parent_notices('leader') == []
    state = yaml.safe_load((monitor.task_directory / 'execution-budget.yml').read_text())
    state['parent_notices'][0].pop('observer')                    # a record from before observers
    (monitor.task_directory / 'execution-budget.yml').write_text(yaml.safe_dump(state))
    assert [notice['key'] for notice in monitor.pending_parent_notices('leader')] == keys[:1]


def test_a_launch_reports_its_own_end_when_a_successor_already_replaced_it(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """B: a parent's send may start a successor between the launch's end and its result.

    The successor's Worker unlinks execution.yml and rewrites mapping.yml at
    registration (runner_worker). The launch still reports its own execution
    and outcome, never the successor's, and is not misreported as unstarted.
    """
    import io
    import subprocess

    from graphtraj.teams import team_round

    monkeypatch.delenv('GRAPHTRAJ_BUDGET_NOTICE_FD', raising=False)
    session = tmp_path / 'sessions' / 'engineer'
    session.mkdir(parents=True)

    class Worker:
        """The launch Worker registers, ends, and exits as a successor registers."""
        pid = 4242
        returncode = None

        def __init__(self, *_: object, **__: object) -> None:
            self.stdin, self.ticks = io.StringIO(), 0

        def poll(self) -> int | None:
            self.ticks += 1
            if self.ticks == 1:
                (session / 'mapping.yml').write_text(yaml.safe_dump(
                    {'session': 's1', 'worker_pid': self.pid, 'execution_id': 'e1'}))
            elif self.ticks == 2:
                (session / 'execution.yml').write_text(yaml.safe_dump({'outcome': 'completed'}))
            else:
                (session / 'execution.yml').unlink()
                (session / 'mapping.yml').write_text(yaml.safe_dump(
                    {'session': 's1', 'worker_pid': 5151, 'execution_id': 'e2'}))
                self.returncode = 0
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            if self.returncode is None:
                raise subprocess.TimeoutExpired('worker', timeout)
            return self.returncode

    monkeypatch.setattr(team_round.subprocess, 'Popen', Worker)
    registered: dict = {}
    assert team_round._run_session_worker(
        session, session / 'launch.yml', tmp_path, 'prompt', {}, 3, None, True, registered,
    ) == ('s1', 'completed')
    assert registered == {'execution_id': 'e1'}


def test_a_late_heartbeat_never_recreates_a_retired_session_directory(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """8: retirement may move the directory between any two steps of the write."""
    import os

    from graphtraj.execution import runner_heartbeat

    active, retained = tmp_path / 'sessions' / 'engineer', tmp_path / 'trace' / 'engineer'
    active.mkdir(parents=True)
    retained.parent.mkdir()
    runner_heartbeat.write_heartbeat(active, {'alias': 'engineer', 'worker_pid': 1})
    assert yaml.safe_load((active / 'heartbeat.yml').read_text())['worker_pid'] == 1
    replace = os.replace

    def retire_then_replace(source: object, target: object) -> None:
        active.rename(retained)                       # retirement wins the race here
        replace(source, target)

    monkeypatch.setattr(runner_heartbeat.os, 'replace', retire_then_replace)
    runner_heartbeat.write_heartbeat(active, {'alias': 'engineer', 'worker_pid': 2})
    monkeypatch.setattr(runner_heartbeat.os, 'replace', replace)
    runner_heartbeat.write_heartbeat(active, {'alias': 'engineer', 'worker_pid': 3})
    assert not active.exists()
    assert yaml.safe_load((retained / 'heartbeat.yml').read_text())['worker_pid'] == 1


def test_a_resumed_non_root_parent_gets_its_childrens_held_ends_once(
        tmp_path: Path, runner: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """(b): a stopped non-root parent's held child ends reach it when its parent resumes it.

    A continuation resumes only Task roots. The ends a Driver withheld for the
    stop are held again for the stop, so the parent's next own input delivers
    each held end exactly once; a notice, a Driver turn or a later input delivers nothing.
    """
    DELIVERED.clear()
    monkeypatch.setitem(MAPPINGS, 'engineer', dict(MAPPINGS['engineer'], worktree_path=str(tmp_path)))
    monkeypatch.setitem(MAPPINGS, 'analyst', dict(MAPPINGS['analyst'], parent='engineer'))
    monkeypatch.setitem(MAPPINGS, 'reviewer', {'alias': 'reviewer', 'task_id': '153', 'parent': 'engineer',
                                               'session': 's-r', 'execution_id': 'r1'})
    (runner / 'sessions' / 'reviewer').mkdir()
    monkeypatch.setattr(runner_control, 'deliver_parent_event', _deliver_received)
    monkeypatch.setattr(runner_control, 'require_execution_allowed', lambda *_, **__: None)
    sent: list[str] = []
    monkeypatch.setattr(runner_control, '_send_session_locked',
                        lambda alias, instruction, *_, **__: sent.append(instruction) or {'send_status': 'sent'})
    analyst, reviewer = runner / 'sessions' / 'analyst', runner / 'sessions' / 'reviewer'
    runner_control.deliver_execution_end(          # stopped by the budget
        analyst, MAPPINGS['analyst'], {'outcome': 'interrupted', 'budget_stopped': True},
        parent_input=True, driver_reports_end=True)
    runner_control.deliver_execution_end(          # completed before the stop
        reviewer, MAPPINGS['reviewer'], {'outcome': 'completed'}, parent_input=True,
        driver_reports_end=True)
    # The engineer's Driver then withholds its turn for the stop.
    runner_control.rehold_ends(runner_control.held_ends(runner, 'engineer', frozenset({'driver'})),
                               'budget-stop')
    assert DELIVERED == []
    engineer = runner / 'sessions' / 'engineer'

    def send(**options: object) -> None:
        runner_control._send_session('engineer', 'continue', engineer, MAPPINGS['engineer'], (),
                                     tmp_path, **options)

    send(system_notice=True)                       # a notice is not its parent's input
    send(parent_input=False)                       # nor a Driver results turn
    assert DELIVERED == []
    send()                                         # resumed by its own parent
    assert sorted((alias, kind) for alias, kind, _ in DELIVERED) == [
        ('analyst', 'interrupted'), ('reviewer', 'completed')]
    send()                                         # a second resume
    assert len(DELIVERED) == 2 and sent == ['continue'] * 4
    assert runner_control.held_ends(runner, 'engineer') == []


def test_a_launch_ignores_its_workers_early_pid_only_mapping(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """F1: the Worker first writes a mapping with only its pid, before its execution exists.

    That early record must not stand for the launch, or its result would fall
    back to the alias's current mapping, which a successor may already own.
    """
    import io
    import subprocess

    from graphtraj.teams import team_round

    monkeypatch.delenv('GRAPHTRAJ_BUDGET_NOTICE_FD', raising=False)
    session = tmp_path / 'sessions' / 'engineer'
    session.mkdir(parents=True)
    steps = [
        lambda: (session / 'mapping.yml').write_text(yaml.safe_dump(        # record_created
            {'session': 's1', 'worker_pid': 4242})),
        lambda: (session / 'mapping.yml').write_text(yaml.safe_dump(        # record_session
            {'session': 's1', 'worker_pid': 4242, 'execution_id': 'e1'})),
        lambda: (session / 'execution.yml').write_text(yaml.safe_dump({'outcome': 'completed'})),
    ]

    class Worker:
        """Each poll is one Worker step; after them a successor registers as it exits."""
        pid = 4242
        returncode = None

        def __init__(self, *_: object, **__: object) -> None:
            self.stdin = io.StringIO()

        def poll(self) -> int | None:
            if steps:
                steps.pop(0)()
            else:
                (session / 'execution.yml').unlink()
                (session / 'mapping.yml').write_text(yaml.safe_dump(
                    {'session': 's1', 'worker_pid': 5151, 'execution_id': 'e2'}))
                self.returncode = 0
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            if self.returncode is None:
                raise subprocess.TimeoutExpired('worker', timeout)
            return self.returncode

    monkeypatch.setattr(team_round.subprocess, 'Popen', Worker)
    registered: dict = {}
    assert team_round._run_session_worker(
        session, session / 'launch.yml', tmp_path, 'prompt', {}, 3, None, True, registered,
    ) == ('s1', 'completed')
    assert registered == {'execution_id': 'e1'}
