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
