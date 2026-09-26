"""Budget delivery serializes retries without locking accounting.

Native parent delivery, stopped wrap-up and interruption during a held notice
lock are exercised together through Runner in test_task_budget_control.py.
"""

import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest
import yaml

from conftest import run_process, wait_for_file
from graphtraj.execution.execution_budget import ExecutionBudgetMonitor
from test_execution_budgets import _budget_body


@contextmanager
def _process(
    command: list[str], cwd: Path, environment: dict[str, str],
) -> Iterator[subprocess.Popen]:
    """Reap each test caller even when an assertion finds the old deadlock."""
    with (cwd / (str(time.monotonic_ns()) + '.log')).open('w+') as output:
        process = subprocess.Popen(
            command, cwd=cwd, env=environment, stdout=output, stderr=output,
        )
        try:
            yield process
            output.seek(0)
            assert process.returncode == 0, output.read()
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            assert process.poll() is not None


DELIVERY = '''
import sys, time
from pathlib import Path
from graphtraj.execution.execution_budget import ExecutionBudgetMonitor
root, label = Path(sys.argv[1]), sys.argv[2]
monitor = ExecutionBudgetMonitor(root, 'test', 'test')
(root / (label + '-started')).touch()
def deliver(notices: list[dict]) -> list[str]:
    """Hold a delivery open while other processes access the budget."""
    (root / (label + '-entered')).write_text(str([notice['message'] for notice in notices]))
    deadline = time.monotonic() + 15
    while not (root / 'release').exists():
        assert time.monotonic() < deadline
        time.sleep(.01)
    return [notice['key'] for notice in notices]
monitor.deliver_notices(deliver)
'''


def test_delivery_serializes_retries_and_preserves_concurrent_budget_updates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure stays pending; a successful batch marks only its keys in current state."""
    import sys
    import graphtraj.execution.execution_budget as budget

    (tmp_path / 'ticket.yml').write_text('current_definition: definition.md\n')
    (tmp_path / 'definition.md').write_text(_budget_body(total=1))
    monkeypatch.setattr(budget.time, 'time', lambda: 1000)
    monkeypatch.setattr(budget.random, 'uniform', lambda a, b: a)
    monitor = ExecutionBudgetMonitor(tmp_path, 'test', 'test')
    monitor.record_session('engineer', 'implementation')
    monkeypatch.setattr(budget.time, 'time', lambda: 1061)
    assert not monitor.check('engineer', 'implementation')
    first = monitor.pending_parent_notices()

    def fail(notices: list[dict]) -> list[str]:
        """Model a caller that cannot deliver the batch."""
        assert notices == first
        raise RuntimeError('delivery failed')

    with pytest.raises(RuntimeError, match='delivery failed'):
        monitor.deliver_notices(fail)
    assert monitor.pending_parent_notices() == first
    environment = {**os.environ, 'PYTHONPATH': str(Path(budget.__file__).parents[2])}
    command = [sys.executable, '-c', DELIVERY, str(tmp_path)]
    with _process(command + ['first'], tmp_path, environment) as sender:
        wait_for_file(tmp_path / 'first-entered')
        with _process(command + ['second'], tmp_path, environment) as second:
            wait_for_file(tmp_path / 'second-started')
            # Budget access in a third process must complete while delivery is blocked.
            update = run_process([sys.executable, '-c', '''
import sys
from pathlib import Path
import graphtraj.execution.execution_budget as budget
budget.time.time = lambda: 1200
budget.random.random = lambda: .99
monitor = budget.ExecutionBudgetMonitor(Path(sys.argv[1]), 'test', 'test')
assert not monitor.is_stopped()
monitor.record_session('engineer', 'implementation')
monitor.record_correction('engineer')
assert monitor.is_stopped()
''', str(tmp_path)], cwd=tmp_path, env=environment, timeout=5)
            assert update.returncode == 0, update.stderr
            assert not (tmp_path / 'second-entered').exists()
            (tmp_path / 'release').touch()
            sender.wait(timeout=5)
            second.wait(timeout=5)
    state = yaml.safe_load((tmp_path / 'execution-budget.yml').read_text())
    assert state['stopped'] and state['stopping_checks'] == 1
    assert state['sessions']['engineer'] == 2 and state['corrections'] == 1
    assert state['started_at'] == 1000 and state['allowance_minutes'] == .1
    assert {notice['key'].split(':')[0] for notice in state['leader_notices']} == {
        'elapsed_minutes', 'additional_allowance', 'stochastic_stop', 'planned_sessions.engineer',
    }
    assert all(notice['delivered'] for notice in state['leader_notices'])
    assert (tmp_path / 'second-entered').exists()
    assert first[0]['message'] not in (tmp_path / 'second-entered').read_text()
