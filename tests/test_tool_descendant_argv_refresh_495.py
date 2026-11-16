"""495: a recorded tool process's command line is refreshed after exec or an unreadable read.

The sampler first records a process when it sees it. That first read can come
between fork and exec (it shows the parent's command line) or find the command
line unreadable (under load on macOS, right after exec). Later samples re-read
it; an unreadable read keeps the earlier one. Everything recorded or reported
still goes through redaction. Real ``/bin/sh`` and ``/bin/sleep`` here.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

from graftling.member_processes import MEMBER_RUN_ENV
from graftling.tool_descendants import DescendantSampler, Identity, identity, read_sidecar
from test_owner_exited_notice_451 import dead_pid
from test_tool_descendants_459 import (
    call, child_with, point_at_dead_owner, record_path, stop_own, wait_for,
)

pytestmark = pytest.mark.skipif(not (sys.platform == 'darwin' or sys.platform.startswith('linux')),
                                reason='macOS and Linux process tables')

SCRIPT = ': "Authorization: Bearer abcdef123456" XYZ_API_KEY=supersecret123; /bin/sleep 300; :'
SECRETS = ('abcdef123456', 'supersecret123')
# A stand-in Runtime (marker in its readable environment) that forks a tool process
# which waits on stdin before it execs /bin/sh -c SCRIPT.
FORKER = r'''
import os, sys
pid = os.fork()
if pid == 0:
    os.read(0, 1)
    os.execv("/bin/sh", ["/bin/sh", "-c", sys.argv[1]])
print(pid, flush=True)
os.waitpid(pid, 0)
'''


def sampler_under(tmp_path: Path, marker: str, runtime_pid: int) -> DescendantSampler:
    sampler = DescendantSampler(tmp_path / 'tool-descendants.json', marker)
    sampler.runtime_pid, sampler._runtime_start = runtime_pid, identity(runtime_pid).start
    return sampler


def entry_of(sampler: DescendantSampler, pid: int) -> dict | None:
    sampler.sample()
    return next((entry for entry in sampler.entries.values() if entry['pid'] == pid), None)


def assert_redacted_record(sampler: DescendantSampler, pid: int) -> None:
    text = sampler.path.read_text()
    print('sidecar:', text)
    assert not any(secret in text for secret in SECRETS)
    [shell] = [entry for entry in read_sidecar(sampler.path) if entry['pid'] == pid]
    assert shell['argv'].startswith('/bin/sh -c ') and '[redacted]' in shell['argv']
    assert 'XYZ_API_KEY=' in shell['argv']


def assert_redacted_stop_report(tmp_path: Path, sampler: DescendantSampler, marker: str, pid: int,
                                monkeypatch) -> None:
    import graftling.review

    # The reconciling caller's own redact of the whole result is off, as in 459.
    monkeypatch.setattr(graftling.review, 'redact', lambda value: value)
    root = tmp_path / 'data-root'
    caller, child, control = child_with(root, {'tool_marker': marker, 'tool_descendants': str(sampler.path)})
    point_at_dead_owner(root, child, dead_pid(), dead_pid())
    call(control, caller, action='status', agent=child)
    report = json.loads(record_path(root, child).read_text())['executions'][-1]['escaped_processes']
    print('escaped_processes:', json.dumps(report))
    assert pid in [item['pid'] for item in report['stopped']]
    serialized = json.dumps(report)
    assert not any(secret in serialized for secret in SECRETS) and '[redacted]' in serialized


def recorded(sampler: DescendantSampler) -> list[Identity]:
    return [Identity(entry['pid'], 0, 0, entry['uid'], entry['start']) for entry in sampler.entries.values()]


def test_a_process_sampled_between_fork_and_exec_gets_its_command_line_after_exec(
        tmp_path: Path, monkeypatch) -> None:
    marker = uuid.uuid4().hex
    runtime = subprocess.Popen([sys.executable, '-c', FORKER, SCRIPT], env={**os.environ, MEMBER_RUN_ENV: marker},
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    sampler, own = None, []
    try:
        tool = int(runtime.stdout.readline())
        own = [identity(tool)]
        sampler = sampler_under(tmp_path, marker, runtime.pid)
        before = wait_for(lambda: entry_of(sampler, tool), 10)
        # Not yet exec'd: the forked copy still shows the stand-in Runtime's command line.
        assert before and before['argv'].startswith(sys.executable)
        runtime.stdin.write(b'x')
        runtime.stdin.flush()
        assert wait_for(lambda: (entry_of(sampler, tool) or {}).get('argv', '').startswith('/bin/sh -c '), 10)
        assert_redacted_record(sampler, tool)
        assert_redacted_stop_report(tmp_path, sampler, marker, tool, monkeypatch)
    finally:
        if sampler is not None:
            sampler.sample()
            own += recorded(sampler)
        stop_own([item for item in own if item is not None])
        runtime.kill()
        runtime.wait(5)


def test_a_first_unreadable_command_line_is_refreshed_and_a_later_one_keeps_it(
        tmp_path: Path, monkeypatch) -> None:
    import graftling.tool_descendants as module

    marker = uuid.uuid4().hex
    shell = subprocess.Popen(['/bin/sh', '-c', SCRIPT], env={**os.environ, MEMBER_RUN_ENV: marker})
    unreadable = {shell.pid}
    real = module._process_view
    # Under load the real read can itself be unreadable (495's cause). Take the shell's real view once it
    # shows /bin/sh and serve that, so only this test decides when the shell is unreadable.
    view = wait_for(lambda: (found := real(shell.pid)) is not None and found[0][:1] == ['/bin/sh'] and found, 10)
    assert view
    monkeypatch.setattr(module, '_process_view',
                        lambda pid: real(pid) if pid != shell.pid else None if pid in unreadable else view)
    sampler = sampler_under(tmp_path, marker, os.getpid())
    try:
        # Revised by 498 (user decision 2026-11-17 ~01:20, direction A: judge only settled reads).
        # An unreadable read is not settled, so a first unreadable read no longer records the shell;
        # before 498 it was recorded with an empty command line, the same rule that recorded another
        # execution's process read in its exec window. The first settled read below records it.
        assert entry_of(sampler, shell.pid) is None

        unreadable.clear()
        assert entry_of(sampler, shell.pid)['argv'].startswith('/bin/sh -c ')
        assert_redacted_record(sampler, shell.pid)

        unreadable.add(shell.pid)
        good = entry_of(sampler, shell.pid)['argv']
        assert good.startswith('/bin/sh -c ') and '[redacted]' in good
        assert_redacted_record(sampler, shell.pid)

        unreadable.clear()
        assert_redacted_stop_report(tmp_path, sampler, marker, shell.pid, monkeypatch)
    finally:
        unreadable.clear()
        sampler.sample()
        stop_own(recorded(sampler))
        if shell.poll() is None:
            shell.kill()
        shell.wait(5)
