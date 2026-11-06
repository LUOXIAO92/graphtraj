"""Processes a member leaves behind are stopped by marker only (450)."""
from contextlib import ExitStack
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest
import yaml

from graftling.member_processes import MEMBER_RUN_ENV, new_marker, stop_marked_processes
from test_claude_runtime import claude_environment, execution  # noqa: F401
from test_result_submission import result_project

SLEEPER = [sys.executable, '-c', 'import time; time.sleep(300)']


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_gone(pid: int, seconds: float = 5) -> bool:
    deadline = time.monotonic() + seconds
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    return not alive(pid)


@pytest.fixture
def bystanders():
    """An unmarked process and one carrying another execution's marker."""
    plain = subprocess.Popen(SLEEPER, env={k: v for k, v in os.environ.items() if k != MEMBER_RUN_ENV})
    other = subprocess.Popen(SLEEPER, env={**os.environ, MEMBER_RUN_ENV: new_marker()})
    yield plain, other
    for process in (plain, other):
        process.kill()
        process.wait()


def test_detached_grandchild_with_marker_is_stopped_and_others_survive(tmp_path: Path, bystanders) -> None:
    marker = new_marker()
    record = tmp_path / 'pid'
    script = ('import os, sys, time\nif os.fork(): os._exit(0)\nos.setsid()\n'
              'open(sys.argv[1], "w").write(str(os.getpid()))\ntime.sleep(300)\n')
    subprocess.run([sys.executable, '-c', script, str(record)], env={**os.environ, MEMBER_RUN_ENV: marker},
                   start_new_session=True, check=True)
    deadline = time.monotonic() + 5
    while not record.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    pid = int(record.read_text())
    try:
        report = stop_marked_processes(marker)
        assert [item['pid'] for item in report['found']] == [pid]
        assert [item['pid'] for item in report['stopped']] == [pid] and report['remaining'] == []
        assert wait_gone(pid)
        assert all(process.poll() is None for process in bystanders)
        assert stop_marked_processes(marker)['found'] == []
    finally:
        if alive(pid):
            os.kill(pid, signal.SIGKILL)


def test_claude_member_escaped_process_is_stopped_and_recorded(
        tmp_path: Path, claude_environment: None, bystanders) -> None:
    result_project(tmp_path)
    record = tmp_path / 'escaped.pid'
    pid = None
    try:
        with ExitStack() as stack:
            turn, _, _ = execution(tmp_path, stack, f'escape {record}')
            result = turn.run()
        pid = int(record.read_text())
        assert result['outcome'] == 'completed' and result['terminal_confirmed'] is True
        assert [item['pid'] for item in result['escaped_processes']['stopped']] == [pid]
        termination = yaml.safe_load(
            (turn.directory / f'claude-termination-{turn.execution_id}.yml').read_text())
        escaped = termination['escaped_processes']
        assert [item['pid'] for item in escaped['found']] == [pid]
        assert escaped['remaining'] == []
        assert termination['process_group_closed'] is True
        assert wait_gone(pid)
        assert all(process.poll() is None for process in bystanders)
    finally:
        if pid is not None and alive(pid):
            os.kill(pid, signal.SIGKILL)


def test_claude_member_without_escape_records_none(tmp_path: Path, claude_environment: None) -> None:
    result_project(tmp_path)
    with ExitStack() as stack:
        turn, _, _ = execution(tmp_path, stack, 'plain')
        result = turn.run()
    assert 'escaped_processes' not in result
    termination = yaml.safe_load((turn.directory / f'claude-termination-{turn.execution_id}.yml').read_text())
    assert termination['escaped_processes'] == {'found': [], 'stopped': [], 'remaining': []}
