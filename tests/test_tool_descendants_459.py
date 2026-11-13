"""459: a Claude child's platform-binary tool processes are stopped by recorded descent.

macOS hides the environment of Apple platform binaries, so 457's marker scan
never sees a Claude Bash tool shell (``/bin/zsh -c``) or its ``/bin/sleep``.
The owner now samples the Runtime's descendants by parent pid while it lives
and keeps them in a sidecar file (``tool_descendants``). After the end, only
recorded processes still alive with the same uid and start time, and their
current descendants, are stopped. Real ``/bin/sh`` and ``/bin/sleep`` here.

Every test stops only processes it started, and only after checking their
pid and start time.
"""
from __future__ import annotations

from contextlib import ExitStack
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

import pytest
import yaml

import graftling
from graftling import AgentControl, Caller
from graftling.member_processes import MEMBER_RUN_ENV
from graftling.tool_descendants import Identity, identity, read_sidecar, stop_tool_processes
from test_agent_control import ScriptedDriver
from test_claude_runtime import claude_environment, execution  # noqa: F401
from test_owner_exited_notice_451 import dead_pid
from test_result_submission import result_project

pytestmark = pytest.mark.skipif(not (sys.platform == 'darwin' or sys.platform.startswith('linux')),
                                reason='macOS and Linux process tables')

SH, SLEEP = '/bin/sh', '/bin/sleep'

# The stand-in owner: the real sampler, a stand-in Runtime (own session, marker)
# that starts a tool shell in its own session and two readable processes of
# other executions, each with a /bin/sleep child. Killing the owner closes the
# Runtime's stdin, so the Runtime exits as a SIGKILLed owner's would.
OWNER = r'''
import os, subprocess, sys, time
from graftling.tool_descendants import DescendantSampler
path, marker = sys.argv[1], sys.argv[2]
sampler = DescendantSampler(path, marker)
sampler.prepare()
environment = {**os.environ, "GRAFTLING_MEMBER_RUN": marker}
runtime = subprocess.Popen([sys.executable, "-c", sys.argv[3]], env=environment, stdin=subprocess.PIPE,
                           start_new_session=True)
sampler.start(runtime.pid)
runtime.wait()
'''
RUNTIME = r'''
import os, subprocess, sys
own = os.environ["GRAFTLING_MEMBER_RUN"]
plain = {k: v for k, v in os.environ.items() if k != "GRAFTLING_MEMBER_RUN"}
spawn = "import subprocess, sys; subprocess.Popen(['/bin/sleep', '303']).wait()"
subprocess.Popen(["/bin/sh", "-c", "/bin/sleep 459; :"], start_new_session=True)
subprocess.Popen([sys.executable, "-c", spawn], env=plain, start_new_session=True)
subprocess.Popen([sys.executable, "-c", spawn], env={**plain, "GRAFTLING_MEMBER_RUN": own[::-1]},
                 start_new_session=True)
sys.stdin.read()
'''


class Recording(ScriptedDriver):
    """Records the facts a Claude driver records before its Runtime starts."""

    def __init__(self, facts: dict) -> None:
        super().__init__()
        self.facts = facts

    def start(self, run):
        super().start(run)
        if self.facts:
            run.events.process(**self.facts)


def call(control, caller, **request):
    return graftling.bind(control, caller)(request).document


def child_with(root: Path, facts: dict) -> tuple[Caller, str, AgentControl]:
    control = AgentControl(root, {'scripted': Recording(facts)})
    lead = call(control, Caller('test-host', None), action='create', runtime='scripted', instruction='lead')
    caller = Caller('test-host', lead['agent'])
    child = call(control, caller, action='create', runtime='scripted', instruction='work')
    return caller, child['agent'], control


def record_path(root: Path, agent: str) -> Path:
    return root / 'control/agents' / f'{agent}.json'


def point_at_dead_owner(root: Path, agent: str, worker: int, runtime: int) -> None:
    path = record_path(root, agent)
    record = json.loads(path.read_text())
    record['executions'][-1]['process'].update(worker_pid=worker, runtime_pid=runtime)
    path.write_text(json.dumps(record))


def snapshot() -> dict[int, Identity]:
    """This process's descendants (including those re-parented to 1 since), by identity."""
    from graftling.tool_descendants import _table

    return _table()


def descendants_of(table: dict[int, Identity], root: int) -> list[Identity]:
    found, pending = [], [root]
    while pending:
        parent = pending.pop()
        for item in table.values():
            if item.ppid == parent:
                found.append(item)
                pending.append(item.pid)
    return found


def argv(pid: int) -> list[str]:
    from graftling.member_processes import _process_view

    view = _process_view(pid)
    return view[0] if view else []


def is_alive(item: Identity) -> bool:
    now = identity(item.pid)
    return now is not None and now.start == item.start


def stop_own(items) -> None:
    """Stop only processes this test started, after checking pid and start time."""
    for item in items:
        if is_alive(item):
            os.kill(item.pid, signal.SIGKILL)
    deadline = time.monotonic() + 5
    while any(is_alive(item) for item in items) and time.monotonic() < deadline:
        time.sleep(0.05)


def wait_for(predicate, seconds: float = 20.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    return predicate()


def bystander() -> subprocess.Popen:
    """A user's own /bin/sleep in its own session: not a descendant of any Runtime."""
    return subprocess.Popen([SLEEP, '458'], start_new_session=True)


def test_owner_killed_then_reconciliation_stops_the_recorded_shell_and_sleep(tmp_path: Path) -> None:
    root, sidecar, marker = tmp_path / 'data-root', tmp_path / 'tool-descendants.json', uuid.uuid4().hex
    caller, child, control = child_with(root, {'tool_marker': marker, 'tool_descendants': str(sidecar)})
    owner = subprocess.Popen([sys.executable, '-c', OWNER, str(sidecar), marker, RUNTIME],
                             env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')})
    user = bystander()
    started: list[Identity] = []
    try:
        def recorded():
            try:
                entries = read_sidecar(sidecar)
            except (OSError, ValueError):
                return None
            commands = [entry['argv'] for entry in entries]
            return entries if ('/bin/sh -c /bin/sleep 459; :' in commands
                               and '/bin/sleep 459' in commands) else None

        entries = wait_for(recorded)
        assert entries, f'the sampler did not record the tool shell: {sidecar.read_text()}'
        runtime_pid = json.loads(sidecar.read_text())['runtime_pid']
        tree = snapshot()
        started = descendants_of(tree, owner.pid)
        by_argv = {' '.join(argv(item.pid)): item for item in started}
        shell, sleep = by_argv['/bin/sh -c /bin/sleep 459; :'], by_argv['/bin/sleep 459']
        others = [item for item in started if item.pid != runtime_pid and (
            argv(item.pid)[:1] == [sys.executable] or argv(item.pid) == [SLEEP, '303'])]
        assert len(others) == 4, 'two readable processes of other executions and their sleeps'
        # The boundary rule: readable without exactly this marker -> not recorded, not descended.
        assert {entry['pid'] for entry in entries} == {shell.pid, sleep.pid}
        assert {entry['start'] for entry in entries} == {shell.start, sleep.start}

        owner.send_signal(signal.SIGKILL)
        owner.wait(5)
        assert wait_for(lambda: identity(runtime_pid) is None or not is_alive(tree[runtime_pid]), 10)
        assert is_alive(shell) and is_alive(sleep), 'the tool shell outlived its owner, as on the real host'

        point_at_dead_owner(root, child, owner.pid, runtime_pid)
        status = call(control, caller, action='status', agent=child)
        execution = json.loads(record_path(root, child).read_text())['executions'][-1]
        report = execution.get('escaped_processes')
        print('escaped_processes:', json.dumps(report))
        assert status['result']['last_result']['error']['code'] == 'owner-exited'
        assert execution['process']['tool_descendants'] == str(sidecar)
        assert sorted(item['pid'] for item in report['found']) == sorted([shell.pid, sleep.pid])
        assert sorted(item['pid'] for item in report['stopped']) == sorted([shell.pid, sleep.pid])
        assert report['remaining'] == [] and 'error' not in report
        assert not is_alive(shell) and not is_alive(sleep)
        assert all(is_alive(item) for item in others), 'other executions are untouched'
        assert user.poll() is None, "the user's own /bin/sleep is untouched"

        # A later read changes nothing and signals nothing.
        call(control, caller, action='status', agent=child)
        assert json.loads(record_path(root, child).read_text())['executions'][-1]['escaped_processes'] == report
        assert all(is_alive(item) for item in others) and user.poll() is None
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(5)
        stop_own(started)
        user.kill()
        user.wait(5)


def test_a_reused_pid_is_not_signalled(tmp_path: Path) -> None:
    """A recorded pid now held by another process (different start time) is left alone."""
    root, sidecar = tmp_path / 'data-root', tmp_path / 'tool-descendants.json'
    user = bystander()
    try:
        now = wait_for(lambda: identity(user.pid))
        sidecar.write_text(json.dumps({'version': 1, 'runtime_pid': None, 'entries': [
            {'pid': user.pid, 'pgid': now.pgid, 'uid': now.uid, 'start': now.start - 1, 'argv': SLEEP}]}))
        caller, child, control = child_with(root, {'tool_descendants': str(sidecar)})
        point_at_dead_owner(root, child, dead_pid(), dead_pid())
        call(control, caller, action='status', agent=child)
        report = json.loads(record_path(root, child).read_text())['executions'][-1]['escaped_processes']
        print('escaped_processes:', json.dumps(report))
        assert report == {'found': [], 'stopped': [], 'remaining': []}
        assert user.poll() is None
        # The same entry with the right start time is stopped.
        assert stop_tool_processes([{'pid': user.pid, 'uid': now.uid, 'start': now.start}], None,
                                   grace=3.0)['stopped'] == [{'pid': user.pid, 'command': f'{SLEEP} 458'}]
        assert user.wait(5) is not None
    finally:
        if user.poll() is None:
            user.kill()
        user.wait(5)


def test_an_unreadable_record_is_reported_not_silent(tmp_path: Path) -> None:
    root = tmp_path / 'data-root'
    caller, child, control = child_with(root, {'tool_descendants': str(tmp_path / 'missing.json')})
    point_at_dead_owner(root, child, dead_pid(), dead_pid())
    call(control, caller, action='status', agent=child)
    report = json.loads(record_path(root, child).read_text())['executions'][-1]['escaped_processes']
    print('escaped_processes:', json.dumps(report))
    assert report['found'] == [] and 'FileNotFoundError' in report['error']


def test_owner_side_normal_end_stops_the_recorded_shell_and_sleep(
        tmp_path: Path, claude_environment: None) -> None:
    """The Worker's own reclaim after a completed turn reaches platform binaries too."""
    result_project(tmp_path)
    record = tmp_path / 'shell.pid'
    user = bystander()
    shell = sleep = None
    turn = None
    try:
        with ExitStack() as stack:
            turn, _, _ = execution(tmp_path, stack, f'tool-shell {record}')
            result = turn.run()
        entries = read_sidecar(turn.tool_descendants)
        print('sidecar:', json.dumps(entries))
        print('escaped_processes:', json.dumps(result.get('escaped_processes')))
        shell_pid = int(record.read_text())
        by_pid = {entry['pid']: entry for entry in entries}
        assert shell_pid in by_pid
        shell = Identity(shell_pid, 0, 0, by_pid[shell_pid]['uid'], by_pid[shell_pid]['start'])
        sleeps = [entry for entry in entries if entry['argv'] == f'{SLEEP} 300']
        assert len(sleeps) == 1
        sleep = Identity(sleeps[0]['pid'], 0, 0, sleeps[0]['uid'], sleeps[0]['start'])
        assert result['outcome'] == 'completed' and result['terminal_confirmed'] is True
        stopped = sorted(item['pid'] for item in result['escaped_processes']['stopped'])
        assert stopped == sorted([shell.pid, sleep.pid])
        assert result['escaped_processes']['remaining'] == []
        termination = yaml.safe_load(
            (turn.directory / f'claude-termination-{turn.execution_id}.yml').read_text())
        assert sorted(item['pid'] for item in termination['escaped_processes']['found']) == stopped
        assert not is_alive(shell) and not is_alive(sleep)
        assert user.poll() is None
    finally:
        stop_own([item for item in (shell, sleep) if item is not None])
        user.kill()
        user.wait(5)


def test_the_drivers_record_the_sidecar_path(tmp_path: Path, monkeypatch) -> None:
    import graftling.claude.binding as binding
    import graftling.claude.driver as module
    from graftling import Run
    from test_reconcile_escaped_tools_457 import Events

    class Turn:
        def __init__(self, *args, **kwargs):
            self.ready, self.created = args[3], args[4]
            self.member_marker = uuid.uuid4().hex
            self.tool_descendants = tmp_path / 'sub' / '..' / 'tool-descendants-x.json'
            self.unseen, self.archive = [], None

        def take_unseen(self):
            return []

        def run(self):
            self.created('session-459', 4242)
            self.ready('session-459', 4242)
            return {'outcome': 'completed'}

    monkeypatch.setattr(binding, 'bind_run', lambda turn, run: None)
    monkeypatch.setattr(module, 'ClaudeExecution', Turn)
    events = Events()
    run = Run(agent='child', execution='e459', runtime='claude', settings={'adapter_request': {}},
              message='hi', session=None, directory=tmp_path, archive=None, events=events)
    module.ClaudeDriver(tmp_path, {}).start(run)
    assert events.ended.wait(10)
    assert events.facts['tool_descendants'] == str((tmp_path / 'tool-descendants-x.json').resolve())


def test_graphtrajs_agents_driver_records_the_sidecar_path(tmp_path: Path, monkeypatch) -> None:
    import graphtraj.execution.agent_driver as module
    from graftling import Run
    from test_reconcile_escaped_tools_457 import Events

    class Turn:
        def __init__(self, request, message, directory, ready, evidence, *, session_created, **kwargs):
            self.request, self.directory = request, directory
            self.ready, self.created = ready, session_created
            self.native_id = 'session-459'
            self.member_marker = uuid.uuid4().hex
            self.tool_descendants = directory / 'tool-descendants-y.json'

        def configure_independent(self, **kwargs):
            pass

        def run(self):
            self.created('session-459', 4343)
            self.ready('session-459', 4343)
            return {'outcome': 'completed'}

    class Adapter:
        managed_execution = Turn

    monkeypatch.setattr(module, 'select_runtime_adapter', lambda runtime: Adapter())
    events = Events()
    run = Run(agent='child', execution='e459', runtime='claude',
              settings={'adapter_request': {'harness_root': str(tmp_path)}, 'evidence': {},
                        'cwd': str(tmp_path)},
              message='hi', session=None, directory=tmp_path, archive=None, events=events)
    module.AdapterDriver(tmp_path, tmp_path).start(run)
    assert events.ended.wait(10)
    assert events.facts['tool_descendants'] == str((tmp_path / 'tool-descendants-y.json').resolve())


def test_graphtrajs_claude_owner_inherits_the_sampler(tmp_path: Path) -> None:
    from graphtraj.runtimes.claude.execution import ClaudeExecution
    from graftling.claude import ClaudeExecution as Native

    assert issubclass(ClaudeExecution, Native)


def test_the_sampler_follows_the_runtime_pid_only_with_its_start_time(tmp_path: Path) -> None:
    """A Runtime pid now held by another process (different start time) is not a root."""
    from graftling.tool_descendants import DescendantSampler

    tool = subprocess.Popen([SLEEP, '457'])
    try:
        me = identity(os.getpid())
        wait_for(lambda: identity(tool.pid))
        sampler = DescendantSampler(tmp_path / 'record.json', uuid.uuid4().hex)
        sampler.runtime_pid, sampler._runtime_start = os.getpid(), me.start - 1
        sampler.sample()
        assert sampler.entries == {} and not (tmp_path / 'record.json').exists()
        sampler._runtime_start = me.start
        sampler.sample()
        assert tool.pid in {entry['pid'] for entry in read_sidecar(tmp_path / 'record.json')}
    finally:
        tool.kill()
        tool.wait(5)
