"""496: an exiting or unreaped Runtime does not block reconciliation; the boundary holds in an exec window.

1. A dead owner's Runtime is reparented, and its new parent reaps it late.
   From the moment its identity is gone it is first exiting (the kernel tears
   it down), then a zombie; both answer ``kill(pid, 0)`` but run nothing.
   Reconciliation ends the execution ``owner-exited`` and stops its recorded
   tools then, as it does once the Runtime is reaped.
2. A process of another execution, sampled as a fork copy of a Runtime whose
   readable environment lacks the marker, is never recorded or stopped, even
   when reads right after its exec are unreadable or empty.

Real ``/bin/sh`` and ``/bin/sleep`` here. Every test stops only processes it
started, and only after checking their pid and start time.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

import graftling.tool_descendants
from graftling.member_processes import MEMBER_RUN_ENV, _process_view
from graftling.tool_descendants import DescendantSampler, Identity, identity, read_sidecar
from test_owner_exited_notice_451 import dead_pid
from test_tool_descendants_459 import (
    SLEEP, bystander, call, child_with, is_alive, point_at_dead_owner, record_path, stop_own, wait_for,
)

pytestmark = pytest.mark.skipif(not (sys.platform == 'darwin' or sys.platform.startswith('linux')),
                                reason='macOS and Linux process tables')

SCRIPT = ': "Authorization: Bearer abcdef123456" XYZ_API_KEY=supersecret123; /bin/sleep 300; :'

# A stand-in Runtime whose readable environment lacks the marker. It forks a tool
# process (execs /bin/sh -c SCRIPT with the marker) and another execution's
# process (execs a readable Python without it). Each waits for one byte on
# stdin before its exec, so the test samples both while they are fork copies.
FORKER = r'''
import os, sys
marker, script = sys.argv[1], sys.argv[2]
plain = {k: v for k, v in os.environ.items() if k != "GRAFTLING_MEMBER_RUN"}
targets = [("/bin/sh", ["/bin/sh", "-c", script], {**plain, "GRAFTLING_MEMBER_RUN": marker}),
           (sys.executable, [sys.executable, "-c", "import time; time.sleep(300)"], plain)]
pids = []
for path, argv, env in targets:
    pid = os.fork()
    if pid == 0:
        os.read(0, 1)
        os.execve(path, argv, env)
    pids.append(pid)
print(*pids, flush=True)
for pid in pids:
    os.waitpid(pid, 0)
'''
# A Runtime whose exit takes the kernel a while to tear down (400 MB touched).
EXITING = 'b = bytearray(400_000_000); b[::4096] = b"x" * len(b[::4096])'


def ended_unreaped() -> subprocess.Popen:
    """A child of this test caught as soon as its identity is gone: exiting or a zombie, not reaped."""
    process = subprocess.Popen([sys.executable, '-c', EXITING])
    assert wait_for(lambda: identity(process.pid) is None, 30)
    os.kill(process.pid, 0)  # still answers: not reaped until this test waits for it
    return process


def test_a_dead_owners_runtime_exiting_or_unreaped_is_reconciled_and_its_tools_stopped(tmp_path: Path) -> None:
    root, sidecar, marker = tmp_path / 'data-root', tmp_path / 'tool-descendants.json', uuid.uuid4().hex
    tool, user = subprocess.Popen([SLEEP, '496'], start_new_session=True), bystander()
    runtime = None
    try:
        now = wait_for(lambda: identity(tool.pid), 10)
        sidecar.write_text(json.dumps({'version': 1, 'runtime_pid': None, 'entries': [
            {'pid': tool.pid, 'ppid': now.ppid, 'pgid': now.pgid, 'uid': now.uid, 'start': now.start,
             'argv': f'{SLEEP} 496'}]}))
        caller, child, control = child_with(root, {'tool_marker': marker, 'tool_descendants': str(sidecar)})
        runtime = ended_unreaped()
        point_at_dead_owner(root, child, dead_pid(), runtime.pid)

        status = call(control, caller, action='status', agent=child)
        execution = json.loads(record_path(root, child).read_text())['executions'][-1]
        print('execution:', json.dumps(execution))
        assert status['result']['last_result']['error']['code'] == 'owner-exited'
        assert execution['state'] == 'ended' and 'diagnostic' not in execution
        assert [item['pid'] for item in execution['escaped_processes']['stopped']] == [tool.pid]
        assert tool.wait(5) is not None
        assert user.poll() is None, "the user's own /bin/sleep is untouched"
    finally:
        for process in (tool, user, runtime):
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.wait(10)


def test_another_executions_process_stays_unrecorded_when_its_exec_window_reads_are_unreadable(
        tmp_path: Path, monkeypatch) -> None:
    marker = uuid.uuid4().hex
    plain  = {key: value for key, value in os.environ.items() if key != MEMBER_RUN_ENV}
    runtime = subprocess.Popen([sys.executable, '-c', FORKER, marker, SCRIPT], env=plain,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    own: list[Identity] = []
    try:
        tool, other = map(int, runtime.stdout.readline().split())
        own = [identity(tool), identity(other)]
        sampler = DescendantSampler(tmp_path / 'tool-descendants.json', marker)
        sampler.runtime_pid, sampler._runtime_start = runtime.pid, identity(runtime.pid).start

        # Both are still fork copies of the Runtime (readable, no marker): neither is recorded.
        assert wait_for(lambda: _process_view(tool) == _process_view(other) == _process_view(runtime.pid)
                        is not None, 10)
        sampler.sample()
        assert {entry['pid'] for entry in sampler.entries.values()} & {tool, other} == set()

        # After its exec the other process reads unreadable, then empty, then its real view.
        reads = iter([None, ([], []), None])
        real  = _process_view
        monkeypatch.setattr(graftling.tool_descendants, '_process_view',
                            lambda pid: next(reads, None) if pid == other else real(pid))
        runtime.stdin.write(b'xx')
        runtime.stdin.flush()
        assert wait_for(lambda: 'time.sleep(300)' in ' '.join((real(other) or ([], []))[0]), 10)
        for _ in range(3):
            sampler.sample()
        monkeypatch.setattr(graftling.tool_descendants, '_process_view', real)
        sampler.sample()
        print('entries:', json.dumps(list(sampler.entries.values())))
        assert other not in {entry['pid'] for entry in sampler.entries.values()}
        if sampler.path.exists():
            assert other not in {entry['pid'] for entry in read_sidecar(sampler.path)}
        own += [Identity(entry['pid'], 0, 0, entry['uid'], entry['start']) for entry in sampler.entries.values()]
        assert is_alive(own[1]), "the other execution's process is untouched"
    finally:
        stop_own([item for item in own if item is not None])
        runtime.kill()
        runtime.wait(5)
