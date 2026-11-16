"""496: a zombie Runtime does not block reconciliation; a pre-exec child is judged after exec.

1. A dead owner's Runtime is reparented, and its new parent may reap it late.
   Until then it is a zombie: it answers ``kill(pid, 0)`` but runs nothing.
   Reconciliation ends the execution ``owner-exited`` and stops its recorded
   tools then, as it does once the zombie is reaped.
2. Between fork and exec a child shows its parent's argv and environment.
   When that parent is readable without this execution's marker, the child
   looked foreign. It is judged again once it has executed, so a tool process
   is recorded and stopped; another execution's process is still neither.

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

from graftling.member_processes import MEMBER_RUN_ENV, _process_view
from graftling.tool_descendants import DescendantSampler, Identity, identity, read_sidecar
from test_owner_exited_notice_451 import dead_pid
from test_tool_descendants_459 import (
    SH, SLEEP, bystander, call, child_with, is_alive, point_at_dead_owner, record_path, stop_own, wait_for,
)

pytestmark = pytest.mark.skipif(not (sys.platform == 'darwin' or sys.platform.startswith('linux')),
                                reason='macOS and Linux process tables')

SCRIPT  = ': "Authorization: Bearer abcdef123456" XYZ_API_KEY=supersecret123; /bin/sleep 300; :'
SECRETS = ('abcdef123456', 'supersecret123')

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


def own_zombie() -> subprocess.Popen:
    """A child of this test that has exited and is not reaped: a zombie until ``wait``."""
    process = subprocess.Popen([SH, '-c', 'exit 0'])
    assert wait_for(lambda: identity(process.pid) is None, 10)
    os.kill(process.pid, 0)  # still answers: exited, not reaped
    return process


def test_a_dead_owners_runtime_still_a_zombie_is_reconciled_and_its_tools_stopped(tmp_path: Path) -> None:
    root, sidecar, marker = tmp_path / 'data-root', tmp_path / 'tool-descendants.json', uuid.uuid4().hex
    tool, user = subprocess.Popen([SLEEP, '496'], start_new_session=True), bystander()
    runtime = own_zombie()
    try:
        now = wait_for(lambda: identity(tool.pid), 10)
        sidecar.write_text(json.dumps({'version': 1, 'runtime_pid': runtime.pid, 'entries': [
            {'pid': tool.pid, 'ppid': now.ppid, 'pgid': now.pgid, 'uid': now.uid, 'start': now.start,
             'argv': f'{SLEEP} 496'}]}))
        caller, child, control = child_with(root, {'tool_marker': marker, 'tool_descendants': str(sidecar)})
        point_at_dead_owner(root, child, dead_pid(), runtime.pid)

        status = call(control, caller, action='status', agent=child)
        execution = json.loads(record_path(root, child).read_text())['executions'][-1]
        print('execution:', json.dumps(execution))
        assert status['result']['last_result']['error']['code'] == 'owner-exited'
        assert execution['state'] == 'ended' and 'diagnostic' not in execution
        assert [item['pid'] for item in execution['escaped_processes']['stopped']] == [tool.pid]
        assert tool.wait(5) is not None
        assert user.poll() is None, "the user's own /bin/sleep is untouched"
        assert runtime.poll() is not None  # the zombie was this test's to reap, and only now is
    finally:
        for process in (tool, user, runtime):
            if process.poll() is None:
                process.kill()
            process.wait(5)


def test_a_pre_exec_child_of_a_runtime_without_the_marker_is_judged_after_exec(
        tmp_path: Path, monkeypatch) -> None:
    import graftling.review

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
        def copies() -> bool:
            return _process_view(tool) == _process_view(other) == _process_view(runtime.pid) is not None

        assert wait_for(copies, 10)
        sampler.sample()
        assert {entry['pid'] for entry in sampler.entries.values()} & {tool, other} == set()

        runtime.stdin.write(b'xx')
        runtime.stdin.flush()

        def recorded():
            sampler.sample()
            return [entry for entry in sampler.entries.values() if entry['pid'] == tool
                    and entry['argv'].startswith('/bin/sh -c ')
                    and any(item['argv'] == f'{SLEEP} 300' for item in sampler.entries.values())]

        assert wait_for(recorded, 10), f'the tool shell was not judged after exec: {sampler.entries}'
        text = sampler.path.read_text()
        print('sidecar:', text)
        assert not any(secret in text for secret in SECRETS) and '[redacted]' in text
        # The other execution's process, readable without this marker after its exec, is not recorded.
        assert wait_for(lambda: 'time.sleep(300)' in ' '.join((_process_view(other) or ([], []))[0]), 10)
        sampler.sample()
        assert other not in {entry['pid'] for entry in read_sidecar(sampler.path)}
        own += [Identity(entry['pid'], 0, 0, entry['uid'], entry['start']) for entry in sampler.entries.values()]

        # Reconciliation stops the tool shell and its sleep, not the other execution's process.
        monkeypatch.setattr(graftling.review, 'redact', lambda value: value)
        root = tmp_path / 'data-root'
        caller, child, control = child_with(root, {'tool_marker': marker, 'tool_descendants': str(sampler.path)})
        point_at_dead_owner(root, child, dead_pid(), dead_pid())
        call(control, caller, action='status', agent=child)
        report = json.loads(record_path(root, child).read_text())['executions'][-1]['escaped_processes']
        print('escaped_processes:', json.dumps(report))
        assert tool in [item['pid'] for item in report['stopped']]
        assert other not in [item['pid'] for item in report['found']]
        assert is_alive(own[1]), "the other execution's process is untouched"
        serialized = json.dumps(report)
        assert not any(secret in serialized for secret in SECRETS) and '[redacted]' in serialized
    finally:
        stop_own([item for item in own if item is not None])
        runtime.kill()
        runtime.wait(5)
