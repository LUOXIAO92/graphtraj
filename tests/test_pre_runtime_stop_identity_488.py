"""Task 488: a pre-Runtime stop skips ended processes and still refuses unclear identity.

An exiting or zombie current-user process refuses its argv (EINVAL on the real
host). It can never run again, so it is no Worker: the stop must skip it rather
than fail, and must never signal it. A live process whose identity is unclear or
does not match is still refused.
"""
from __future__ import annotations

import ctypes
import os
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

from graphtraj.execution import runner_process

darwin = pytest.mark.skipif(sys.platform != 'darwin', reason='Darwin process-state interface')
LIVE, INEXIT = (2, 0), (2, runner_process._PROC_FLAG_INEXIT)
_REAL_KILL = os.kill  # teardown must bypass the signal recorder


def _end(process: subprocess.Popen) -> None:
    if process.poll() is None:
        _REAL_KILL(process.pid, signal.SIGKILL)
    process.wait()


@pytest.fixture
def signals(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """Record every real signal; liveness probes (signal 0) still reach the kernel."""
    sent: list[tuple] = []
    def kill(pid: int, sig: int) -> None:
        if sig == 0:
            return _REAL_KILL(pid, 0)
        sent.append(('kill', pid, sig))

    monkeypatch.setattr(os, 'kill', kill)
    monkeypatch.setattr(os, 'killpg', lambda pid, sig: sent.append(('killpg', pid, sig)))
    return sent


@pytest.fixture
def child():
    process = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(60)'],
                               start_new_session=True)
    yield process
    _end(process)


def _expected(job_file: Path) -> list[str]:
    return [sys.executable, '-I', '-m', 'graphtraj.execution.runner_worker', str(job_file)]


def _only(monkeypatch: pytest.MonkeyPatch, *rows: tuple[int, int, int]) -> None:
    monkeypatch.setattr(runner_process, '_current_user_processes', lambda: list(rows))


def _state(monkeypatch: pytest.MonkeyPatch, pid: int, status_flags: tuple[int, int]) -> None:
    real = runner_process._short_bsd_info
    monkeypatch.setattr(runner_process, '_short_bsd_info',
                        lambda p: (p, 1, p, *status_flags) if p == pid else real(p))


@darwin
def test_a_real_zombie_is_classified_ended_and_skipped(tmp_path: Path, signals: list) -> None:
    job_file = tmp_path / 'launch.yml'
    zombie = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(60)', str(job_file)],
                              start_new_session=True)
    try:
        # Killed outside the recorder and not waited: it stays a zombie.
        subprocess.run(['/bin/kill', '-9', str(zombie.pid)], check=True)
        deadline = time.monotonic() + 5
        while (info := runner_process._short_bsd_info(zombie.pid)) is None or info[3] != runner_process._SZOMB:
            assert time.monotonic() < deadline, f'no zombie state observed: {info}'
            time.sleep(0.01)
        assert runner_process._process_ended(zombie.pid)
        with pytest.MonkeyPatch.context() as patch:
            _only(patch, (zombie.pid, os.getpid(), zombie.pid))
            assert runner_process.unstarted_worker_processes(job_file) == []
        assert signals == []
    finally:
        zombie.wait()


@darwin
def test_an_exiting_target_with_unreadable_argv_is_skipped_unsignalled(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, signals: list, child) -> None:
    _only(monkeypatch, (child.pid, os.getpid(), child.pid))
    _state(monkeypatch, child.pid, INEXIT)
    calls = []

    def unreadable(pid: int) -> list[str]:
        calls.append(pid)
        raise OSError(22, 'Process arguments are unavailable')

    monkeypatch.setattr(runner_process, '_process_arguments', unreadable)
    assert runner_process.unstarted_worker_processes(tmp_path / 'launch.yml') == []
    assert calls == [child.pid]  # no retry for an exiting process
    assert signals == []


@darwin
def test_a_live_unreadable_process_is_still_refused_after_a_bounded_retry(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, signals: list, child) -> None:
    _only(monkeypatch, (child.pid, os.getpid(), child.pid))
    _state(monkeypatch, child.pid, LIVE)
    calls = []

    def unreadable(pid: int) -> list[str]:
        calls.append(time.monotonic())
        raise OSError(22, 'Process arguments are unavailable')

    monkeypatch.setattr(runner_process, '_process_arguments', unreadable)
    started = time.monotonic()
    with pytest.raises(OSError, match='Process arguments are unavailable'):
        runner_process.unstarted_worker_processes(tmp_path / 'launch.yml')
    elapsed = time.monotonic() - started
    assert len(calls) > 1
    assert elapsed <= runner_process._ARGUMENT_RETRY_SECONDS + 0.25, elapsed
    assert signals == []


@darwin
def test_a_transient_unreadable_argv_then_an_exact_worker_is_matched(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, signals: list, child) -> None:
    job_file = tmp_path / 'launch.yml'
    _only(monkeypatch, (child.pid, os.getpid(), child.pid))
    _state(monkeypatch, child.pid, LIVE)
    failures = [OSError(5, 'Process arguments are unavailable')] * 2

    def flaky(pid: int) -> list[str]:
        if failures:
            raise failures.pop()
        return _expected(job_file)

    monkeypatch.setattr(runner_process, '_process_arguments', flaky)
    monkeypatch.setattr(runner_process, 'process_executable', lambda pid: Path(sys.executable).resolve())
    assert runner_process.unstarted_worker_processes(job_file) == [child.pid]
    assert signals == []


@darwin
@pytest.mark.parametrize('mismatch', ['argv-shape', 'executable', 'foreign-group', 'has-child', 'executable-unreadable'])
def test_a_live_process_whose_identity_does_not_match_is_refused_unsignalled(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, signals: list, child, mismatch: str) -> None:
    job_file = tmp_path / 'launch.yml'
    group = os.getpgid(child.pid) if mismatch != 'foreign-group' else os.getpgid(0)
    rows = [(child.pid, os.getpid(), group)]
    if mismatch == 'has-child':
        rows.append((child.pid + 100000, child.pid, child.pid))
        monkeypatch.setattr(runner_process, '_process_arguments',
                            lambda pid: _expected(job_file) if pid == child.pid else ['other'])
    elif mismatch != 'argv-shape':
        monkeypatch.setattr(runner_process, '_process_arguments', lambda pid: _expected(job_file))
    else:
        monkeypatch.setattr(runner_process, '_process_arguments',
                            lambda pid: [sys.executable, '-I', '-c', 'pass', str(job_file)])
    executable = {'executable': Path('/bin/sleep'), 'executable-unreadable': None}.get(
        mismatch, Path(sys.executable).resolve())
    monkeypatch.setattr(runner_process, 'process_executable', lambda pid: executable)
    _only(monkeypatch, *rows)
    _state(monkeypatch, child.pid, LIVE)
    with pytest.raises(OSError, match='ambiguous'):
        runner_process.unstarted_worker_processes(job_file)
    assert signals == []
    assert child.poll() is None


@darwin
def test_a_matching_worker_that_ends_before_its_executable_is_read_is_skipped(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, signals: list, child) -> None:
    job_file = tmp_path / 'launch.yml'
    _only(monkeypatch, (child.pid, os.getpid(), child.pid))
    _state(monkeypatch, child.pid, (runner_process._SZOMB, runner_process._PROC_FLAG_INEXIT))
    monkeypatch.setattr(runner_process, '_process_arguments', lambda pid: _expected(job_file))
    monkeypatch.setattr(runner_process, 'process_executable', lambda pid: None)
    assert runner_process.unstarted_worker_processes(job_file) == []
    assert signals == []


@darwin
def test_a_real_exact_worker_shape_is_matched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                              signals: list) -> None:
    """Positive control on real kernel reads: identity checks still accept the exact Worker."""
    job_file = tmp_path / 'launch.yml'
    # runner_worker blocks on stdin before reading the job file.
    worker = subprocess.Popen(_expected(job_file), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, start_new_session=True,
                              env={**os.environ, 'PYTHONPATH': os.pathsep.join(sys.path)})
    try:
        _only(monkeypatch, (worker.pid, os.getpid(), worker.pid))
        deadline = time.monotonic() + 5
        while True:
            try:
                arguments = runner_process._process_arguments(worker.pid)
            except OSError as error:
                pytest.skip(f'this host denies reading a child argv: {error}')
            if arguments[1:] == _expected(job_file)[1:]:
                break
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert runner_process.unstarted_worker_processes(job_file) == [worker.pid]
        assert signals == []
    finally:
        _end(worker)


class _FakeLibproc:
    """proc_listpids / proc_pidinfo for a fixed table; None marks an unreadable pid."""

    def __init__(self, table: dict[int, tuple[int, int, int, int] | None]):
        self.table = table
        self.args = []

    def proc_listpids(self, kind, uid, buffer, size):
        if buffer is None:
            return 4 * len(self.table)
        for index, pid in enumerate(self.table):
            buffer[index] = pid
        return 4 * len(self.table)

    def proc_pidinfo(self, pid, flavor, arg, record, size):
        self.args.append(arg)
        row = self.table[pid]
        if row is None:
            return 0
        ppid, pgid, status, flags = row
        raw = struct.pack('=4I16sI', pid, ppid, pgid, status, b'comm', flags).ljust(size, b'\0')
        ctypes.memmove(record, raw, size)
        return size


@darwin
def test_current_user_processes_leaves_out_ended_pids_and_refuses_unreadable_live_ones(
        monkeypatch: pytest.MonkeyPatch) -> None:
    table = {101: (1, 101, 2, 0), 102: (1, 102, 5, 4), 103: (1, 103, 2, 4), 104: None}
    library = _FakeLibproc(table)
    monkeypatch.setattr(runner_process, '_libproc', lambda: library)
    monkeypatch.setattr(runner_process, 'process_is_alive', lambda pid: False)
    assert runner_process._current_user_processes() == [(101, 1, 101)]
    assert set(library.args) == {1}  # zombie-inclusive query only

    monkeypatch.setattr(runner_process, 'process_is_alive', lambda pid: pid == 104)
    with pytest.raises(OSError, match='Native process identity is unavailable'):
        runner_process._current_user_processes()
