"""Budget delivery uses real process locks alongside Session recovery."""

import fcntl
import json
import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, run_process, wait_for_file
from graphtraj.execution.execution_budget import ExecutionBudgetMonitor
from graphtraj.execution.runner_heartbeat import ownership_is_held
from graphtraj.execution.runner_process import process_is_alive
from runner_fixtures import configure_harness
from test_execution_budgets import _budget_body
from test_session_alias_control import _register_ready_ticket


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


RECOVERY = '''
import json, os, sys, threading, time
from pathlib import Path
from graphtraj.execution import runner_control, runner_worker
from graphtraj.execution.execution_budget import ExecutionBudgetMonitor
root, alias, cause, mode, barriers, ticket = sys.argv[1:]
root, barriers, ticket = Path(root), Path(barriers), Path(ticket)
directory = root / '.graphtraj/runner/sessions' / alias

def wait(name: str) -> None:
    """Arrange the interleaving without taking or replacing a product lock."""
    deadline = time.monotonic() + 15
    while not (barriers / name).exists():
        assert time.monotonic() < deadline, name
        time.sleep(.01)

if mode in ('send', 'reports'):
    original = ExecutionBudgetMonitor.is_stopped
    def paused(self: ExecutionBudgetMonitor) -> bool:
        """Pause public recovery after its real Session lock is held."""
        (barriers / 'session-held').touch()
        wait('read-budget')
        (barriers / 'reading-budget').touch()
        return original(self)
    ExecutionBudgetMonitor.is_stopped = paused
    result = runner_control.send_instruction(alias, 'Return the retained result.', root, (cause,),
                                             reports_only=mode == 'reports')
    (barriers / 'sent.json').write_text(json.dumps(result))
else:
    wait('session-held')
    original = runner_control._send_session
    stop = threading.Event()
    def paused(*args: object, **kwargs: object) -> dict:
        """Expose entry to the actual member delivery callback."""
        (barriers / 'delivery-entered').touch()
        stop.set()
        return original(*args, **kwargs)
    runner_control._send_session = paused
    os.environ['GRAPHTRAJ_HARNESS_ROOT'] = str(root)
    monitor = ExecutionBudgetMonitor(ticket, '76', 'session-alias-control')
    errors = []
    def run() -> None:
        """Join the actual monitoring loop after this notification attempt."""
        try:
            runner_worker._monitor_execution_budget(monitor,
                {'role': 'coding-team.engineer', 'parent': alias},
                directory.parent / 'synthetic-child', stop, False)
        except BaseException as error:
            errors.append(error)
    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
    if mode == 'stopped-notice':
        assert len(errors) == 1 and errors[0].code == 'subtree-stopped', errors
    else:
        assert not errors, errors
    (barriers / 'delivery-done').touch()
    (barriers / 'monitor-joined').touch()
'''


@pytest.mark.parametrize('mode', ['send', 'reports'])
def test_budget_notice_and_session_recovery_finish(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    mode: str,
) -> None:
    """An actual monitor callback and public send cannot form the two-lock cycle."""
    root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register_ready_ticket(installed_commands, root, body=_budget_body(total=1))
    controls = tmp_path / 'controls'
    controls.mkdir()
    clock = controls / 'clock'
    clock.write_text(str(time.time()))
    (controls / 'sitecustomize.py').write_text(
        "import os\nfrom pathlib import Path\n"
        "import graphtraj.execution.execution_budget as budget\n"
        "budget.time.time = lambda: float(Path(os.environ['BUDGET_CLOCK']).read_text())\n"
        "budget.random.uniform = lambda a, b: a\n"
        # Schedule the resumed Leader's own notification handling after the
        # member callback. This isolates the two callers without changing locks.
        "pending = budget.ExecutionBudgetMonitor.pending_leader_notices\n"
        "def wait_for_member(self: budget.ExecutionBudgetMonitor) -> list[dict[str, str]]:\n"
        '    """Schedule parentless handling after the member callback."""\n'
        "    barrier = os.environ.get('NOTICE_DELIVERY_BARRIER')\n"
        "    if barrier and os.environ.get('GRAPHTRAJ_PARENT_ALIAS'):\n"
        "        import time\n"
        "        deadline = time.monotonic() + 20\n"
        "        while not Path(barrier).exists():\n"
        "            assert time.monotonic() < deadline\n"
        "            time.sleep(.01)\n"
        "    return pending(self)\n"
        "budget.ExecutionBudgetMonitor.pending_leader_notices = wait_for_member\n"
    )
    environment.update(
        BUDGET_CLOCK=str(clock), PYTHONPATH=str(controls),
        FAKE_CODEX_APPEND_LOG='1', FAKE_CODEX_CAPTURE_STDIN='1',
        FAKE_CODEX_CAPTURE_ROLE='1', FAKE_CODEX_LIFECYCLE_ACTION='complete-team-round',
        GRAPHTRAJ_AGENT_RUNNER=str(installed_commands.runner),
    )
    batch = root / 'batch.yml'
    batch.write_text(
        'tasks:\n  - ticket_id: "76"\n'
        '    ticket_name: session-alias-control\n    role: coding-team.team-leader\n'
    )
    initial = run_process(
        [str(installed_commands.runner), '--swarm-input', str(batch)],
        cwd=root, env=environment, timeout=30,
    )
    assert initial.returncode == 0, initial.stdout + initial.stderr
    identity = yaml.safe_load(initial.stdout)['tasks'][0]
    alias = identity['alias']
    directory = root / '.graphtraj/runner/sessions' / alias
    ticket = root / '.graphtraj/state/tickets/76-session-alias-control'
    usage = yaml.safe_load((ticket / 'execution-budget.yml').read_text())
    clock.write_text(str(usage['started_at'] + 61))
    cause = [
        json.loads(line)['event_id']
        for path in (root / '.graphtraj/state/worldline').glob('*.jsonl')
        for line in path.read_text().splitlines()
    ][-1]
    environment.pop('FAKE_CODEX_LIFECYCLE_ACTION')
    release = controls / 'release'
    environment['FAKE_CODEX_RELEASE_FILE'] = str(release)
    environment['NOTICE_DELIVERY_BARRIER'] = str(controls / 'delivery-done')
    python = str(installed_commands.runner.with_name('python'))
    command = [python, '-c', RECOVERY, str(root), alias, cause]
    try:
        with _process(command + [mode, str(controls), str(ticket)], root, environment) as sender:
            wait_for_file(controls / 'session-held')
            with _process(command + ['notice', str(controls), str(ticket)], root, environment) as notifier:
                wait_for_file(controls / 'delivery-entered')
                # The Session lock is real and still owned by the sending process.
                with (directory / 'launch.yml').open('rb') as lock:
                    with pytest.raises(BlockingIOError):
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                (controls / 'read-budget').touch()
                wait_for_file(controls / 'reading-budget')
                try:
                    sender.wait(timeout=10)
                    owners = [
                        int(path.stem.removeprefix('owner-'))
                        for path in directory.glob('owner-*.lock')
                    ]
                    assert sum(ownership_is_held(directory, pid) for pid in owners) <= 1
                    notifier.wait(timeout=10)
                    release.touch()
                except subprocess.TimeoutExpired:
                    # Record both actual locks at the arranged wait, without replacing either.
                    held = []
                    for path in (
                        directory / 'launch.yml', ticket / '.execution-budget.lock',
                    ):
                        with path.open('rb') as lock:
                            try:
                                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            except BlockingIOError:
                                held.append(path.name)
                    pytest.fail(f'{mode} recovery did not finish; held locks: {held}')
        result = json.loads((controls / 'sent.json').read_text())
        assert result['session'] == identity['session']
        assert (controls / 'monitor-joined').exists()
        usage_after = yaml.safe_load((ticket / 'execution-budget.yml').read_text())
        assert usage_after['leader_notices']
        assert all(notice['delivered'] for notice in usage_after['leader_notices'])
        assert not usage_after['stopped']
        assert usage_after['started_at'] == usage['started_at']
        assert usage_after['allowance_minutes'] == usage['allowance_minutes']
    finally:
        (controls / 'delivery-done').touch()
        release.touch()
        # Only temporary Harness Workers are touched; callers have already been reaped.
        interrupted = run_process(
            [str(installed_commands.runner), 'interrupt', alias],
            cwd=root, env=environment, timeout=15,
        )
        assert interrupted.returncode == 0, interrupted.stdout + interrupted.stderr
        owners = [
            int(path.stem.removeprefix('owner-'))
            for path in directory.glob('owner-*.lock')
        ]
        deadline = time.monotonic() + 10
        while any(process_is_alive(pid) for pid in owners) and time.monotonic() < deadline:
            time.sleep(.02)
        assert not any(process_is_alive(pid) for pid in owners), 'Temporary Worker did not exit'

    # A later notification cannot restart a subtree explicitly stopped above.
    clock.write_text(str(usage['started_at'] + 67))
    refused = run_process(
        command + ['stopped-notice', str(controls), str(ticket)],
        cwd=root, env=environment, timeout=10,
    )
    assert refused.returncode == 0, refused.stdout + refused.stderr
    retained = yaml.safe_load((ticket / 'execution-budget.yml').read_text())
    assert not retained['stopped']
    assert [notice['delivered'] for notice in retained['leader_notices']] == [True, False]
    assert not any(process_is_alive(pid) for pid in owners)


DELIVERY = '''
import sys, time
from pathlib import Path
from graphtraj.execution.execution_budget import ExecutionBudgetMonitor
root, label = Path(sys.argv[1]), sys.argv[2]
monitor = ExecutionBudgetMonitor(root, 'test', 'test')
(root / (label + '-started')).touch()
def deliver(messages: list[str]) -> None:
    """Hold a delivery open while other processes access the budget."""
    (root / (label + '-entered')).write_text(str(messages))
    deadline = time.monotonic() + 15
    while not (root / 'release').exists():
        assert time.monotonic() < deadline
        time.sleep(.01)
monitor.deliver_leader_notices(deliver)
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
    first = monitor.pending_leader_notices()

    def fail(messages: list[str]) -> None:
        """Model a caller that cannot deliver the batch."""
        assert messages == [notice['message'] for notice in first]
        raise RuntimeError('delivery failed')

    with pytest.raises(RuntimeError, match='delivery failed'):
        monitor.deliver_leader_notices(fail)
    assert monitor.pending_leader_notices() == first
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
    assert len(state['leader_notices']) == 3
    assert all(notice['delivered'] for notice in state['leader_notices'])
    assert (tmp_path / 'second-entered').exists()
    assert first[0]['message'] not in (tmp_path / 'second-entered').read_text()
