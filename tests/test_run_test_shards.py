"""The shard runner bounds each shard and leaves no shard process behind (450)."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/run_test_shards.py'


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def hanging_suite(tmp_path: Path) -> tuple[Path, Path]:
    tests = tmp_path / 'suite'
    tests.mkdir()
    pids = tmp_path / 'pids'
    # The hanging test also starts a child, as a test's subprocess would.
    (tests / 'test_hang.py').write_text(
        'import os, subprocess, sys, time\n'
        'def test_hang():\n'
        '    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])\n'
        f'    open({str(pids)!r} + ".tmp", "w").write(f"{{os.getpid()}} {{child.pid}}")\n'
        f'    os.replace({str(pids)!r} + ".tmp", {str(pids)!r})\n'
        '    time.sleep(300)\n')
    (tests / 'test_quick.py').write_text('def test_quick():\n    assert True\n')
    return tests, pids


def wait_all_gone(pids: list[int], seconds: float = 5) -> bool:
    deadline = time.monotonic() + seconds
    while any(alive(pid) for pid in pids) and time.monotonic() < deadline:
        time.sleep(0.05)
    return not any(alive(pid) for pid in pids)


def test_hanging_shard_is_stopped_and_reported(tmp_path: Path) -> None:
    tests, pids = hanging_suite(tmp_path)
    started = time.monotonic()
    finished = subprocess.run(
        [sys.executable, str(SCRIPT), '--shards', '2', '--timeout', '5', '--tests-dir', str(tests),
         '--log-dir', str(tmp_path / 'logs')],
        capture_output=True, text=True, timeout=120)
    assert time.monotonic() - started < 60
    assert finished.returncode != 0
    assert 'timed out after 5 s' in finished.stdout and 'ABNORMAL' in finished.stdout
    assert '1 passed' in finished.stdout
    assert wait_all_gone([int(item) for item in pids.read_text().split()])


def test_terminated_runner_stops_its_shards(tmp_path: Path) -> None:
    tests, pids = hanging_suite(tmp_path)
    runner = subprocess.Popen(
        [sys.executable, str(SCRIPT), '--shards', '2', '--timeout', '600', '--tests-dir', str(tests),
         '--log-dir', str(tmp_path / 'logs')], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 30
        while len((pids.read_text() if pids.exists() else "").split()) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        shard_pids = [int(item) for item in pids.read_text().split()]
        runner.send_signal(signal.SIGTERM)
        assert runner.wait(timeout=30) != 0
        assert wait_all_gone(shard_pids)
    finally:
        if runner.poll() is None:
            runner.kill()
            runner.wait()


def test_detached_processes_of_a_shard_are_stopped_and_counted(tmp_path: Path) -> None:
    """A process a test detached into its own session is the run's leftover until stopped (454)."""
    import re

    tests = tmp_path / 'suite'
    tests.mkdir()
    pids = tmp_path / 'pids'
    # This suite has no conftest reclaim: only the script's own stop can find the child.
    (tests / 'test_leak.py').write_text(
        'import os, subprocess, sys\n'
        'def test_leak():\n'
        '    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"],\n'
        '                             start_new_session=True, stdin=subprocess.DEVNULL)\n'
        f'    open({str(pids)!r}, "w").write(f"{{child.pid}} {{os.environ[\'PYTEST_GRAPHTRAJ_RUN\']}}")\n')
    (tests / 'test_quick.py').write_text('def test_quick():\n    assert True\n')
    finished = subprocess.run(
        [sys.executable, str(SCRIPT), '--shards', '2', '--timeout', '120', '--tests-dir', str(tests),
         '--log-dir', str(tmp_path / 'logs')],
        capture_output=True, text=True, timeout=180)
    run_id = re.search(r'^test run id: (\w+)', finished.stdout, re.M).group(1)
    child, value = pids.read_text().split()
    assert re.fullmatch(rf'{run_id}-[01]', value)
    assert (f'leftover processes of run {run_id}: before=0 after-shards=1 stopped=1 remaining=0'
            in finished.stdout), finished.stdout
    assert finished.returncode == 0 and 'ABNORMAL' not in finished.stdout
    assert wait_all_gone([int(child)])
