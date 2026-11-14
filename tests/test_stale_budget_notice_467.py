"""Task 467: a stop notice a recovery or continuation superseded is not a current stop."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from graphtraj.execution import execution_budget as budgets
from graphtraj.execution import runner_control
from test_notice_delivery_372 import MAPPINGS, runner, stopped_monitor  # noqa: F401

STOP = 'Execution has taken too long and must stop.'


@pytest.fixture
def parent_inputs(runner: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The Leader's received inputs, through the real notify_direct_parent record path."""
    received: list[str] = []

    def send(alias, message, directory, mapping, *_, **__) -> dict:
        received.append(json.loads(message)['message'])
        return {'session': 's-l', 'execution_id': 'l2'}

    monkeypatch.setattr(runner_control, '_send_session', send)
    monkeypatch.setattr(runner_control, 'runner_project_root', lambda _: runner.parent)
    return received


def _recover(monitor: budgets.ExecutionBudgetMonitor, minutes: int, at: float) -> None:
    """What approved_recovery writes: the reviewed budget, unstopped, with its window."""
    path = monitor.task_directory / 'execution-budget.yml'
    before = yaml.safe_load(path.read_text())
    after = {**before, 'approved_minutes': minutes, 'stopped': False}
    path.write_text(yaml.safe_dump(budgets.start_approved_window(before, after, at)))


def _stop_messages(inputs: list[str]) -> list[str]:
    return [message for message in inputs if STOP in message]


@pytest.mark.parametrize('resume', ['approved_recovery', 'continue'])
def test_superseded_stop_is_not_presented_as_current_and_new_notices_still_arrive(
        tmp_path: Path, runner: Path, parent_inputs: list[str],
        monkeypatch: pytest.MonkeyPatch, resume: str) -> None:
    monitor = stopped_monitor(tmp_path, monkeypatch)
    budget = monitor.task_directory / 'execution-budget.yml'
    stopped = yaml.safe_load(budget.read_text())
    engineer = runner / 'sessions' / 'engineer'
    assert [n['key'] for n in monitor.pending_parent_notices() if n['key'].startswith('stochastic_stop')]
    assert monitor.deliver_parent_notices(engineer) is True        # held while stopped
    assert parent_inputs == []

    at = stopped['started_at'] + 60 * 60
    if resume == 'approved_recovery':
        _recover(monitor, 10, at)
    else:
        monitor.continue_after_stop()
    monkeypatch.setattr(budgets.time, 'time', lambda: at)
    assert monitor.deliver_parent_notices(engineer) is False

    # The retained stop does not read as a stop of the current window.
    assert _stop_messages(parent_inputs) == []
    superseded = [m for m in parent_inputs if 'does not apply to the current window' in m]
    assert len(superseded) == 1 and stopped['parent_notices'][-1]['event']['occurred_at'] in superseded[0]
    # Still-valid notices of the same queue arrive unchanged.
    reminders = [m for m in parent_inputs if 'additional allowance' in m]
    assert reminders and 'does not apply' not in reminders[0]

    # History: every notice is kept, its outcome and the supersession readable.
    after = yaml.safe_load(budget.read_text())
    assert [n['key'] for n in after['parent_notices']] == [n['key'] for n in stopped['parent_notices']]
    assert all(n['delivered'] for n in after['parent_notices'])
    stop = next(n for n in after['parent_notices'] if n['key'].startswith('stochastic_stop'))
    assert stop['message'].endswith(STOP)                           # original text retained
    assert stop['superseded'] is True
    record = [json.loads(line) for line in (engineer / 'parent-notices.jsonl').read_text().splitlines()]
    assert [r['identity'].get('superseded') for r in record
            if r['identity']['key'] == stop['key']] == [True]

    # The current window's own thresholds still arrive as current notices.
    parent_inputs.clear()
    later = at + 40 * 60
    monkeypatch.setattr(budgets.time, 'time', lambda: later)
    monkeypatch.setattr(budgets.random, 'random', lambda: .999)
    assert monitor.check('researcher', 'researcher')               # a new stop, this window
    # A parent outside the stopped Task receives it at once (the hold covers only this Task).
    monkeypatch.setitem(MAPPINGS, 'leader', dict(MAPPINGS['leader'], task_id='other'))
    assert monitor.deliver_parent_notices(engineer) is False
    stops = _stop_messages(parent_inputs)
    assert len(stops) == 1 and stops[0].startswith('System notice: Elapsed time')
    assert 'does not apply' not in stops[0]
    if resume == 'approved_recovery':
        assert any('planned budget of 00:20:00 has been reached' in m for m in parent_inputs)
    final = yaml.safe_load(budget.read_text())['parent_notices']
    assert len(final) > len(after['parent_notices'])
    assert all(n['delivered'] for n in final)
    assert [n.get('superseded', False) for n in final if n['key'].startswith('stochastic_stop')] == [True, False]


def test_a_root_channel_write_after_continuation_carries_the_superseded_stop(
        tmp_path: Path, runner: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A root without a parent gets the event on its caller channel, marked superseded."""
    written: list[dict] = []
    channel = {'open': False}

    def emit(output: str) -> bool:
        if channel['open']:
            written.append(json.loads(output))
        return channel['open']

    monkeypatch.setattr(budgets, '_emit_notice', emit)
    monitor = stopped_monitor(tmp_path, monkeypatch)
    root = runner / 'sessions' / 'engineer'                        # the observer, here a root
    (root / 'launch.yml').write_text(yaml.safe_dump(
        {'operation': 'launch', 'mapping': dict(MAPPINGS['engineer'], parent=None)}))
    monitor.deliver_parent_notices(root)                           # channel unavailable
    monitor.continue_after_stop()
    channel['open'] = True
    monitor.deliver_parent_notices(root)
    stop = next(event for event in written if event['threshold']['kind'] == 'stochastic_stop')
    assert stop['superseded'] is True and STOP not in stop['message']
    assert [event.get('superseded') for event in written].count(True) == 1
    record = yaml.safe_load((monitor.task_directory / 'execution-budget.yml').read_text())
    kept = next(n for n in record['parent_notices'] if n['key'].startswith('stochastic_stop'))
    assert kept['channel_written'] and kept['superseded'] and kept['message'].endswith(STOP)
