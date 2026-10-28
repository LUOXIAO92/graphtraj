"""Task 375, Driver path: a Driver-launched child's error reaches its parent at once (F10)."""
from __future__ import annotations

from pathlib import Path

import pytest

from graphtraj.execution import runner_control

from test_notice_delivery_372 import DELIVERED, MAPPINGS, _deliver_received, records, runner  # noqa: F401


@pytest.mark.parametrize('terminal', [
    {'outcome': 'failed', 'error': {'code': 'X', 'message': 'broke'}},
    {'outcome': 'interrupted'},
    {'outcome': 'runtime-error', 'error': {'code': 'RUNTIME_PROVIDER_FAILED', 'message': 'down'}},
])
def test_a_driver_launched_childs_error_reaches_its_parent_at_once(
        runner: Path, monkeypatch: pytest.MonkeyPatch, terminal: dict) -> None:
    """F10: only a completed end waits for the Driver's aggregate; an error is delivered once now."""
    DELIVERED.clear()
    monkeypatch.setattr(runner_control, 'deliver_parent_event', _deliver_received)
    engineer = runner / 'sessions' / 'engineer'
    receipt = runner_control.deliver_execution_end(
        engineer, MAPPINGS['engineer'], terminal, parent_input=True, driver_reports_end=True)
    assert receipt['delivery'] == 'received'
    assert [(alias, kind) for alias, kind, _ in DELIVERED] == [('engineer', terminal['outcome'])]
    # Nothing is held, so neither the aggregate nor a continuation shows it again.
    assert runner_control.held_ends(runner, 'leader') == []
    runner_control.deliver_held_ends(runner_control.held_ends(runner, 'leader'))
    assert len(DELIVERED) == 1


def test_a_driver_launched_childs_completed_end_still_waits_for_the_aggregate(
        runner: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Q7 is unchanged for a completed end: held for the Driver, shown once there."""
    DELIVERED.clear()
    monkeypatch.setattr(runner_control, 'deliver_parent_event', _deliver_received)
    receipt = runner_control.deliver_execution_end(
        runner / 'sessions' / 'engineer', MAPPINGS['engineer'], {'outcome': 'completed'},
        parent_input=True, driver_reports_end=True)
    assert receipt['held'] == 'driver' and DELIVERED == []


def test_an_aggregate_failure_entry_names_its_child_and_only_refers_to_a_delivered_end(
        runner: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Item 7 and F10: the entry names the alias and execution id; an end shown at once is not repeated."""
    import sys

    import yaml

    from graphtraj.teams import team_round
    from graphtraj.execution.runner_models import RunnerError

    DELIVERED.clear()
    monkeypatch.setattr(runner_control, 'deliver_parent_event', _deliver_received)
    engineer = runner / 'sessions' / 'engineer'
    task = type('T', (), {'task_id': '153', 'task_name': 'research', 'role': 'engineer'})()

    def deliver_task(project, requested, retained, capacity_fd, parent_alias, registered=None):
        registered.update(alias='engineer', execution_id='e1')
        runner_control.deliver_execution_end(
            engineer, MAPPINGS['engineer'], {'outcome': 'runtime-error'},
            parent_input=True, driver_reports_end=True)
        raise RunnerError('RUNTIME_PROVIDER_FAILED', 'The engineer Team member ended with runtime-error.')

    monkeypatch.setattr(team_round, 'read_batch', lambda *_: type('B', (), {'tasks': (task,)})())
    monkeypatch.setattr(team_round, 'discover_project',
                        lambda *_, **__: type('P', (), {'runner_directory': runner})())
    monkeypatch.setattr(team_round, '_deliver_task', deliver_task)
    monkeypatch.setattr(sys, 'argv', ['team_round', 'batch.yml', '0', '0', 'leader'])
    monkeypatch.setattr(team_round.signal, 'signal', lambda *_: None)
    team_round._worker_main()
    entry = yaml.safe_load(capsys.readouterr().out)
    assert (entry['alias'], entry['execution_id'], entry['launch_status']) == ('engineer', 'e1', 'failed')
    assert entry['end'] == 'delivered'
    error = RunnerError('RUNTIME_PROVIDER_FAILED', 'x').as_document()
    assert entry['error'] == {'code': error['code']}       # the body was the end notice
    assert [(alias, kind) for alias, kind, _ in DELIVERED] == [('engineer', 'runtime-error')]


def test_an_aggregate_failure_entry_keeps_an_end_that_was_not_delivered(
        runner: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Item 7: an undelivered or absent end keeps the full error; the entry is then its only carrier."""
    from graphtraj.teams import team_round
    from graphtraj.execution.runner_models import RunnerError

    task = type('T', (), {'task_id': '153', 'task_name': 'research', 'role': 'engineer'})()
    runner_control._append_notice_record(runner / 'sessions' / 'engineer', {
        'identity': {'type': 'failed', 'session': 's-e', 'execution_id': 'e1'}, 'delivery': 'not-delivered'})
    entry = team_round._failed_task(task, RunnerError('RUNTIME_PROVIDER_FAILED', 'ended with failed'),
                                    {'alias': 'engineer', 'execution_id': 'e1'}, runner)
    assert entry['alias'] == 'engineer' and entry['execution_id'] == 'e1'
    assert entry['error'] == RunnerError('RUNTIME_PROVIDER_FAILED', 'ended with failed').as_document()
    assert 'end' not in entry


def _hold_completed_end(runner: Path) -> None:
    runner_control.deliver_execution_end(
        runner / 'sessions' / 'engineer', MAPPINGS['engineer'], {'outcome': 'completed'},
        parent_input=True, driver_reports_end=True)


def test_a_continuation_leaves_a_live_drivers_held_end_to_its_aggregate(
        runner: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """F3: a continuation pushing a 'driver' hold the live Driver then also aggregates shows it twice."""
    from graphtraj import file_lock
    from graphtraj.teams import team_round

    DELIVERED.clear()
    monkeypatch.setattr(runner_control, 'deliver_parent_event', _deliver_received)
    _hold_completed_end(runner)
    with (runner / 'sessions' / 'leader' / 'driver.lock').open('ab') as driver:
        file_lock.flock(driver, file_lock.LOCK_SH)               # the root's Driver is alive
        team_round.deliver_released_ends(runner, 'leader', frozenset({'budget-stop'}))
        assert DELIVERED == []
        held = runner_control.held_ends(runner, 'leader')
        assert [record['held'] for _, record in held] == ['driver']
        runner_control.mark_ends_aggregated(held)                # the Driver's results turn
    team_round.deliver_released_ends(runner, 'leader', frozenset({'budget-stop'}))
    assert DELIVERED == []


def test_a_dead_drivers_held_end_reaches_its_parent_exactly_once(
        runner: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Gap (a): the Driver died between the child's end and its results turn."""
    from graphtraj.teams import team_round

    DELIVERED.clear()
    monkeypatch.setattr(runner_control, 'deliver_parent_event', _deliver_received)
    _hold_completed_end(runner)                                  # no Driver holds the lock
    team_round.deliver_released_ends(runner, 'leader', frozenset({'budget-stop'}))
    team_round.deliver_released_ends(runner, 'leader')           # e.g. the next Driver, repeated
    assert [(alias, kind) for alias, kind, _ in DELIVERED] == [('engineer', 'completed')]
    assert runner_control.held_ends(runner, 'leader') == []
