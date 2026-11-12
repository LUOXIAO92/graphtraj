"""A test run's detached processes are stopped at its end, and only those (454)."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time

from process_reclaim import TEST_RUN_ENV

TESTS = Path(__file__).resolve().parent


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        # Reap our own exited child so it does not linger as a zombie.
        return os.waitpid(pid, os.WNOHANG) == (0, 0)
    except ChildProcessError:
        return True


def _detached(value: str | None) -> subprocess.Popen:
    """A child in its own session, as idle timers and fake Runtimes are."""
    environment = {key: item for key, item in os.environ.items() if key != TEST_RUN_ENV}
    if value is not None:
        environment[TEST_RUN_ENV] = value
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], env=environment,
                            start_new_session=True, stdin=subprocess.DEVNULL)


def test_session_end_stops_only_this_runs_detached_processes(tmp_path: Path) -> None:
    value = f"reclaim-{os.getpid()}-{time.time_ns()}"
    other = _detached(value + "-other-shard")
    unmarked = _detached(None)
    pids = tmp_path / "pids"
    suite = tmp_path / "suite"
    suite.mkdir()
    # The inner test starts a detached grandchild that outlives its test and session.
    (suite / "test_spawn.py").write_text(
        "import subprocess, sys\n"
        "def test_spawn():\n"
        "    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'],\n"
        "                             start_new_session=True, stdin=subprocess.DEVNULL)\n"
        f"    open({str(pids)!r}, 'w').write(str(child.pid))\n")
    environment = {**os.environ, TEST_RUN_ENV: value,
                   "PYTHONPATH": os.pathsep.join([str(TESTS), os.environ.get("PYTHONPATH", "")])}
    try:
        finished = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "process_reclaim",
             str(suite / "test_spawn.py")],
            cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=120)
        assert finished.returncode == 0, finished.stdout + finished.stderr
        spawned = int(pids.read_text())
        assert f"{TEST_RUN_ENV}={value}: found=1 stopped=1 remaining=0" in finished.stdout
        deadline = time.monotonic() + 5
        while _alive(spawned) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _alive(spawned)
        # Another shard's value and an unmarked process are not this run's.
        assert _alive(other.pid) and _alive(unmarked.pid)
    finally:
        for process in (other, unmarked):
            process.kill()
            process.wait()


def test_a_plain_session_draws_its_own_value() -> None:
    assert os.environ.get(TEST_RUN_ENV)
