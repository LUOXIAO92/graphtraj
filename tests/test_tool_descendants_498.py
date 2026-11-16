"""498 acceptance tests: how a Runtime's tool descendants are told apart from other executions' processes.

Each test asserts the settled-read rule (direction A, user decision 2026-11-17). Every test
fails on dev 3eb312e7, except the one named ``test_guard_...``, which dev already passes.

1. An unreadable or empty first read counts as this execution. Another
   execution's process (readable, without this marker) whose first sample falls
   where its environment reads None or ``([], [])`` (its exec window) is
   recorded, stays recorded, stays a sampling root, so its own later tool shell
   (a platform binary whose environment is unreadable) is recorded too, and
   ``stop_tool_processes`` signals that shell. Desired: none of the three.
2. A pre-exec child is cached foreign for good. A tool process sampled as a
   fork copy of a Runtime whose readable environment lacks the marker, which
   then execs ``/bin/sh`` with the marker, is never recorded nor stopped.
   Desired: recorded and stopped.

Interleavings are fixed by stdin gates in real forked stand-ins and by
controlled reads of ``_process_view``, not by timing. The 496 guard (another
execution's fork copy whose exec-window reads are None or empty stays
unrecorded) is a constraint on any direction. Every test signals only processes
it started, after checking their pid and start time.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

import graftling.tool_descendants
from graftling.member_processes import MEMBER_RUN_ENV, _process_view
from graftling.tool_descendants import DescendantSampler, Identity, identity, stop_tool_processes
from test_tool_descendants_459 import argv, is_alive, stop_own, wait_for

pytestmark = pytest.mark.skipif(not (sys.platform == 'darwin' or sys.platform.startswith('linux')),
                                reason='macOS and Linux process tables')

# This execution's Runtime (with its marker) starts another execution's process
# (a readable Python without this marker, e.g. a managed launch), which after one
# stdin byte starts its own tool shell with the other execution's marker.
RUNTIME = r'''
import os, subprocess, sys
plain = {k: v for k, v in os.environ.items() if k != "GRAFTLING_MEMBER_RUN"}
other = subprocess.Popen([sys.executable, "-c", sys.argv[1], sys.argv[2]], env=plain)
print(other.pid, flush=True)
other.wait()
'''
OTHER = r'''
import os, subprocess, sys
os.read(0, 1)
shell = subprocess.Popen(["/bin/sh", "-c", "/bin/sleep 300; :"], env={**os.environ, "GRAFTLING_MEMBER_RUN": sys.argv[1]})
print(shell.pid, flush=True)
shell.wait()
'''
# A Runtime whose readable environment lacks the marker forks a tool process that
# waits for one stdin byte, then execs /bin/sh -c ... with the marker (496 round 1).
FORKER = r'''
import os, sys
marker = sys.argv[1]
plain = {k: v for k, v in os.environ.items() if k != "GRAFTLING_MEMBER_RUN"}
pid = os.fork()
if pid == 0:
    os.read(0, 1)
    os.execve("/bin/sh", ["/bin/sh", "-c", "/bin/sleep 300; :"], {**plain, "GRAFTLING_MEMBER_RUN": marker})
print(pid, flush=True)
os.waitpid(pid, 0)
'''


def recorded(sampler: DescendantSampler) -> set[int]:
    return {entry['pid'] for entry in sampler.entries.values()}


def own_tree(root: int) -> list[Identity]:
    from test_tool_descendants_459 import descendants_of, snapshot

    return descendants_of(snapshot(), root)


@pytest.mark.parametrize('first_read', [None, ([], [])], ids=['unreadable', 'empty'])
def test_another_executions_process_first_read_in_its_exec_window_is_not_recorded_nor_its_tools_signalled(
        tmp_path: Path, monkeypatch, first_read) -> None:
    marker, other_marker = uuid.uuid4().hex, uuid.uuid4().hex
    runtime = subprocess.Popen([sys.executable, '-c', RUNTIME, OTHER, other_marker],
                               env={**os.environ, MEMBER_RUN_ENV: marker},
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    own: list[Identity] = []
    try:
        other = int(runtime.stdout.readline())
        assert wait_for(lambda: OTHER.strip()[:20] in ' '.join(argv(other)), 10), 'other process exec'
        sampler = DescendantSampler(tmp_path / 'tool-descendants.json', marker)
        sampler.runtime_pid, sampler._runtime_start = runtime.pid, identity(runtime.pid).start

        # The other process's first read falls in its exec window; later reads are real.
        # Its tool shell stands in for a platform binary: its environment never reads.
        reads, real, shells = iter([first_read]), _process_view, set()
        controlled = lambda pid: (next(reads, real(pid)) if pid == other
                                  else None if pid in shells else real(pid))
        monkeypatch.setattr(graftling.tool_descendants, '_process_view', controlled)
        sampler.sample()
        other_first = other in recorded(sampler)
        sampler.sample()  # its environment is now readable without this marker
        other_later = other in recorded(sampler)

        runtime.stdin.write(b'x')
        runtime.stdin.flush()
        shell = int(runtime.stdout.readline())
        shells.add(shell)
        own = [identity(other), identity(shell)]
        sampler.sample()
        shell_recorded = shell in recorded(sampler)

        # As the owners do after the Runtime ended: the Runtime itself is excluded.
        report = stop_tool_processes(list(sampler.entries.values()), marker, {runtime.pid}, grace=1.0)
        signalled = {item['pid'] for item in report['found']} & {other, shell}
        observed = {'other recorded at first sample': other_first, 'other still recorded': other_later,
                    "its tool shell recorded": shell_recorded, 'signalled': sorted(signalled),
                    'other alive': is_alive(own[0]), 'its shell alive': is_alive(own[1])}
        print('observed:', observed, 'report:', report)
        assert observed == {'other recorded at first sample': False, 'other still recorded': False,
                            "its tool shell recorded": False, 'signalled': [],
                            'other alive': True, 'its shell alive': True}
    finally:
        own += own_tree(runtime.pid)
        stop_own([item for item in own if item is not None])
        runtime.kill()
        runtime.wait(5)


# The mirror of 2 (496 engineer note): a process with this marker (our tool's Python,
# e.g. a graphtraj command) forks; the copy is sampled before exec, carrying our
# marker, then execs a managed launch whose readable environment has another marker.
MIRROR = r'''
import os, sys
other = sys.argv[1]
plain = {k: v for k, v in os.environ.items() if k != "GRAFTLING_MEMBER_RUN"}
pid = os.fork()
if pid == 0:
    os.read(0, 1)
    os.execve(sys.executable, [sys.executable, "-c", "import time; time.sleep(300)"],
              {**plain, "GRAFTLING_MEMBER_RUN": other})
print(pid, flush=True)
os.waitpid(pid, 0)
'''


def test_a_fork_copy_with_this_marker_that_execs_another_execution_is_not_kept_nor_signalled(
        tmp_path: Path) -> None:
    marker, other_marker = uuid.uuid4().hex, uuid.uuid4().hex
    runtime = subprocess.Popen([sys.executable, '-c', MIRROR, other_marker], env={**os.environ, MEMBER_RUN_ENV: marker},
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    own: list[Identity] = []
    try:
        launch = int(runtime.stdout.readline())
        own = [identity(launch)]
        sampler = DescendantSampler(tmp_path / 'tool-descendants.json', marker)
        sampler.runtime_pid, sampler._runtime_start = runtime.pid, identity(runtime.pid).start
        assert wait_for(lambda: _process_view(launch) == _process_view(runtime.pid) is not None, 10)
        sampler.sample()  # a fork copy carrying this marker (dev records it here; that alone is not asserted)

        runtime.stdin.write(b'x')
        runtime.stdin.flush()
        assert wait_for(lambda: 'time.sleep(300)' in ' '.join(argv(launch)), 10), 'exec'
        sampler.sample()
        sampler.sample()
        report = stop_tool_processes(list(sampler.entries.values()), marker, {runtime.pid}, grace=1.0)
        print('entries:', list(sampler.entries.values()), 'report:', report)
        assert launch not in recorded(sampler), "another execution's process is still recorded after its exec"
        assert launch not in {item['pid'] for item in report['found']}
        assert is_alive(own[0])
    finally:
        own += own_tree(runtime.pid)
        stop_own([item for item in own if item is not None])
        runtime.kill()
        runtime.wait(5)


def test_a_tool_sampled_as_a_fork_copy_of_a_runtime_without_the_marker_is_recorded_and_stopped_after_exec(
        tmp_path: Path) -> None:
    marker = uuid.uuid4().hex
    plain = {key: value for key, value in os.environ.items() if key != MEMBER_RUN_ENV}
    runtime = subprocess.Popen([sys.executable, '-c', FORKER, marker], env=plain,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    own: list[Identity] = []
    try:
        tool = int(runtime.stdout.readline())
        own = [identity(tool)]
        sampler = DescendantSampler(tmp_path / 'tool-descendants.json', marker)
        sampler.runtime_pid, sampler._runtime_start = runtime.pid, identity(runtime.pid).start

        # Still a fork copy of the Runtime (readable, no marker) when sampled.
        assert wait_for(lambda: _process_view(tool) == _process_view(runtime.pid) is not None, 10)
        sampler.sample()
        assert tool not in recorded(sampler)

        runtime.stdin.write(b'x')
        runtime.stdin.flush()
        # After exec: /bin/sh runs, and its /bin/sleep child exists.
        assert wait_for(lambda: any(item.ppid == tool for item in own_tree(runtime.pid)), 10), 'exec'
        own += own_tree(runtime.pid)
        sampler.sample()
        sampler.sample()
        report = stop_tool_processes(list(sampler.entries.values()), marker, grace=1.0)
        print('entries:', list(sampler.entries.values()), 'report:', report)
        assert tool in recorded(sampler), 'the tool shell was not judged after exec'
        assert tool in {item['pid'] for item in report['stopped']}
        assert not is_alive(own[0])
    finally:
        own += own_tree(runtime.pid)
        stop_own([item for item in own if item is not None])
        runtime.kill()
        runtime.wait(5)


# Addition 1 (cascading drop): a fork copy with this marker (provisional) starts a /bin/sh
# (an Apple platform binary: ours by its own read) before it execs another execution.
CASCADE = r'''
import os, sys
other = sys.argv[1]
plain = {k: v for k, v in os.environ.items() if k != "GRAFTLING_MEMBER_RUN"}
copy = os.fork()
if copy == 0:
    os.read(0, 1)
    shell = os.fork()
    if shell == 0:
        os.execv("/bin/sh", ["/bin/sh", "-c", "/bin/sleep 300; :"])
    print(shell, flush=True)
    os.read(0, 1)
    os.execve(sys.executable, [sys.executable, "-c", "import time; time.sleep(300)"],
              {**plain, "GRAFTLING_MEMBER_RUN": other})
print(copy, flush=True)
os.waitpid(copy, 0)
'''


def test_a_provisional_entry_that_settles_foreign_is_dropped_with_everything_recorded_beneath_it(
        tmp_path: Path) -> None:
    marker, other_marker = uuid.uuid4().hex, uuid.uuid4().hex
    runtime = subprocess.Popen([sys.executable, '-c', CASCADE, other_marker], env={**os.environ, MEMBER_RUN_ENV: marker},
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    own: list[Identity] = []
    try:
        copy = int(runtime.stdout.readline())
        sampler = DescendantSampler(tmp_path / 'tool-descendants.json', marker)
        sampler.runtime_pid, sampler._runtime_start = runtime.pid, identity(runtime.pid).start
        assert wait_for(lambda: _process_view(copy) == _process_view(runtime.pid) is not None, 10)
        sampler.sample()
        assert copy in recorded(sampler), 'a fork copy carrying this marker is recorded (provisional)'

        runtime.stdin.write(b'x')
        runtime.stdin.flush()
        shell = int(runtime.stdout.readline())
        assert wait_for(lambda: any(item.ppid == shell for item in own_tree(runtime.pid)), 10), 'shell exec'
        sampler.sample()
        beneath = {item.pid for item in own_tree(copy)}
        assert shell in recorded(sampler) and shell in beneath

        runtime.stdin.write(b'x')
        runtime.stdin.flush()
        assert wait_for(lambda: 'time.sleep(300)' in ' '.join(argv(copy)), 10), 'exec of the copy'
        own = own_tree(runtime.pid)
        sampler.sample()
        report = stop_tool_processes(list(sampler.entries.values()), marker, {runtime.pid}, grace=1.0)
        print('entries:', list(sampler.entries.values()), 'report:', report)
        assert recorded(sampler) & ({copy} | beneath) == set()
        assert {item['pid'] for item in report['found']} & ({copy} | beneath) == set()
        assert all(is_alive(item) for item in own if item.pid in {copy} | beneath)
    finally:
        own += own_tree(runtime.pid)
        stop_own([item for item in own if item is not None])
        runtime.kill()
        runtime.wait(5)


# Addition 2 (guard: dev passes; it guards against dropping on an unsettled read): a provisional
# tool that reads unreadable right after its exec stays recorded, then is this execution's.
OWN_FORK = r'''
import os, sys
pid = os.fork()
if pid == 0:
    os.read(0, 1)
    os.execv("/bin/sh", ["/bin/sh", "-c", "/bin/sleep 300; :"])
print(pid, flush=True)
os.waitpid(pid, 0)
'''


def test_guard_a_provisional_entry_read_unreadable_after_exec_stays_recorded_and_is_stopped(
        tmp_path: Path, monkeypatch) -> None:
    marker = uuid.uuid4().hex
    runtime = subprocess.Popen([sys.executable, '-c', OWN_FORK], env={**os.environ, MEMBER_RUN_ENV: marker},
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    own: list[Identity] = []
    try:
        tool = int(runtime.stdout.readline())
        own = [identity(tool)]
        sampler = DescendantSampler(tmp_path / 'tool-descendants.json', marker)
        sampler.runtime_pid, sampler._runtime_start = runtime.pid, identity(runtime.pid).start
        assert wait_for(lambda: _process_view(tool) == _process_view(runtime.pid) is not None, 10)
        sampler.sample()
        assert tool in recorded(sampler)

        runtime.stdin.write(b'x')
        runtime.stdin.flush()
        assert wait_for(lambda: any(item.ppid == tool for item in own_tree(runtime.pid)), 10), 'exec'
        own += own_tree(runtime.pid)
        real = _process_view
        monkeypatch.setattr(graftling.tool_descendants, '_process_view', lambda pid: None if pid == tool else real(pid))
        sampler.sample()
        assert tool in recorded(sampler), 'an unsettled read after exec does not drop a provisional entry'
        monkeypatch.setattr(graftling.tool_descendants, '_process_view', real)
        sampler.sample()
        report = stop_tool_processes(list(sampler.entries.values()), marker, {runtime.pid}, grace=1.0)
        print('entries:', list(sampler.entries.values()), 'report:', report)
        assert tool in recorded(sampler) and tool in {item['pid'] for item in report['stopped']}
    finally:
        own += own_tree(runtime.pid)
        stop_own([item for item in own if item is not None])
        runtime.kill()
        runtime.wait(5)


# Addition 3 (stop-time verdict): a recorded process that reads unreadable, or empty without
# being a platform binary, at stop time is not signalled and is reported under remaining.
@pytest.mark.parametrize('stop_read', [None, ([], [])], ids=['unreadable', 'empty'])
def test_an_unsettled_recorded_process_is_reported_not_signalled_at_stop(monkeypatch, stop_read) -> None:
    marker = uuid.uuid4().hex
    plain = {key: value for key, value in os.environ.items() if key != MEMBER_RUN_ENV}
    process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'], env=plain)
    try:
        now = wait_for(lambda: identity(process.pid), 10)
        entries = [{'pid': now.pid, 'ppid': now.ppid, 'pgid': now.pgid, 'uid': now.uid, 'start': now.start,
                    'argv': 'python -c sleep'}]
        real = _process_view
        monkeypatch.setattr(graftling.tool_descendants, '_process_view',
                            lambda pid: stop_read if pid == process.pid else real(pid))
        report = stop_tool_processes(entries, marker, grace=1.0)
        print('report:', report)
        assert process.pid not in {item['pid'] for item in report['found']}
        assert process.pid in {item['pid'] for item in report['remaining']}
        assert process.poll() is None, 'not signalled'
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(5)
