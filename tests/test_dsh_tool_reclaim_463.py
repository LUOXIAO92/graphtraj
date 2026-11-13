"""463: a DSH child's tool processes are stopped after both kinds of end.

On macOS DSH 0.2.2-alpha.2 starts every Bash tool detached, in its own session
and group (dsh-subprocess-local ``spawnSubprocess``, ``detached: true``), and
on SIGINT/SIGTERM disposes those groups itself. A process the tool moved into
yet another session (``setsid``) is reached by no one: not by DshService.close
or the watcher (they signal the ``dsh web`` group), not by DSH. These tests run
the real DshExecution with a stand-in ``dsh web`` that does exactly that, and a
real ``/bin/zsh`` tool shell whose ``/usr/bin/perl`` calls setsid and execs
``/bin/sleep``. After a normal end, and after the owner is SIGKILLed and the
execution reconciled, that sleep must be gone while three bystanders live.

Every test signals only processes it started, after checking pid and start time.
"""
from __future__ import annotations

from contextlib import nullcontext
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

import pytest

import graftling
from graftling import AgentControl, Caller
from graftling.tool_descendants import identity
from test_dsh_runtime import NativePeer, run_turn
from test_owner_exited_notice_451 import dead_pid
from test_reconcile_escaped_tools_457 import record_of, set_owner, sleeper
from test_tool_descendants_459 import Recording

pytestmark = pytest.mark.skipif(sys.platform != 'darwin' or not Path('/usr/bin/perl').exists(),
                                reason='macOS platform binaries: /bin/zsh, /usr/bin/perl, /bin/sleep')

TESTS = Path(__file__).resolve().parent
SRC = TESTS.parent / 'src'

# The tool command a model would run: the setsid'd sleep leaves every group.
TOOL = ("unsetopt BG_NICE; /usr/bin/perl -MPOSIX -e 'setsid(); exec \"/bin/sleep\",\"463\"' & "
        "echo $! > {pidfile}.tmp && /bin/mv {pidfile}.tmp {pidfile}; /bin/sleep 4631")

# Stand-in ``dsh web``: one detached tool, disposed on SIGINT/SIGTERM as DSH does
# (createProcessShutdown -> disposeManagedProcesses), and on its owner's death,
# which the real watcher turns into that SIGINT.
WEB = r'''
import os, signal, subprocess, sys
tool = subprocess.Popen(["/bin/zsh", "-c", sys.argv[1]], start_new_session=True)
def stop(*_):
    try:
        os.killpg(tool.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    tool.wait()
    os._exit(0)
signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)
sys.stdin.read()
stop()
'''


class ToolPeer(NativePeer):
    """The scripted native protocol, with a real process tree behind ``process``."""

    def __init__(self, executable: str, cwd: Path, environment: dict) -> None:
        super().__init__(executable, cwd, environment)
        self.environment = environment
        self.pidfile = Path(environment['DSH_HOME']).parent / f'escaped-{uuid.uuid4().hex[:8]}.pid'

    def start(self) -> None:
        self.process = subprocess.Popen([sys.executable, '-c', WEB, TOOL.format(pidfile=self.pidfile)],
                                        env=self.environment, stdin=subprocess.PIPE, start_new_session=True)

    def close(self) -> None:
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGINT)
            self.process.wait(10)
        self.closed = True


def escaped_identity(pidfile: Path):
    """Wait for the setsid'd sleep, then long enough for two samples."""
    deadline = time.monotonic() + 10
    while not pidfile.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    found = identity(int(pidfile.read_text()))
    assert found is not None and found.pgid == found.pid, 'the tool did not leave its group'
    time.sleep(2.5)
    return found


def alive(item) -> bool:
    now = identity(item.pid)
    return now is not None and now.start == item.start


def bystanders() -> list[subprocess.Popen]:
    """Another execution's marked tool, an unmarked one, and an unrelated /bin/sleep."""
    plain = subprocess.Popen(['/bin/sleep', '120'], start_new_session=True)
    return [sleeper(uuid.uuid4().hex), sleeper(None), plain]


def cleanup(escaped, others: list[subprocess.Popen]) -> None:
    if escaped is not None and alive(escaped):
        os.kill(escaped.pid, signal.SIGKILL)
    for process in others:
        if process.poll() is None:
            process.kill()
        process.wait(5)


@pytest.fixture
def tool_peer(monkeypatch: pytest.MonkeyPatch) -> list:
    from graphtraj.runtimes.dsh import execution
    from graphtraj.interfaces import hosted_cli

    monkeypatch.setenv('DSH_TEST_KEY', 'controlled-peer-key')
    NativePeer.instances = []
    monkeypatch.setattr(execution, 'DshService', ToolPeer)
    monkeypatch.setattr(hosted_cli, 'cli_connection', lambda *args, **kwargs: nullcontext('/bound-channel'))
    return NativePeer.instances


def test_a_normal_end_stops_the_setsid_tool_process(tmp_path: Path, tool_peer: list) -> None:
    others, escaped = bystanders(), None
    try:
        turn, thread, outcome = run_turn(tmp_path)
        escaped = escaped_identity(tool_peer[0].pidfile)
        tool_peer[0].frames.append('turn/end')
        thread.join(30)
        print('outcome:', outcome, '| escaped', escaped.pid, 'alive', alive(escaped))
        assert outcome['result']['outcome'] == 'completed'
        assert not alive(escaped), 'the setsid tool process outlived a normal DSH end'
        assert all(process.poll() is None for process in others)
    finally:
        cleanup(escaped, others)


# The owner: the real graphtraj DshExecution on the stand-in, as test_dsh_runtime runs
# it; it writes the facts its driver records, then waits until it is SIGKILLed.
OWNER = r'''
import json, sys
from contextlib import nullcontext
from pathlib import Path
sys.path.insert(0, sys.argv[2])
import test_dsh_tool_reclaim_463 as here
from test_dsh_runtime import NativePeer, run_turn
from graphtraj.runtimes.dsh import execution
from graphtraj.interfaces import hosted_cli
execution.DshService = here.ToolPeer
hosted_cli.cli_connection = lambda *args, **kwargs: nullcontext('/bound-channel')
turn, thread, outcome = run_turn(Path(sys.argv[1]))
facts = {'runtime_pid': NativePeer.instances[0].process.pid,
         'pidfile': str(NativePeer.instances[0].pidfile)}
if getattr(turn, 'member_marker', None):
    facts['tool_marker'] = turn.member_marker
if getattr(turn, 'tool_descendants', None) is not None:
    facts['tool_descendants'] = str(Path(turn.tool_descendants).resolve())
Path(sys.argv[3] + '.tmp').write_text(json.dumps(facts))
Path(sys.argv[3] + '.tmp').rename(sys.argv[3])
thread.join()
'''


def test_reconciling_a_killed_owner_stops_the_setsid_tool_process(tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('DSH_TEST_KEY', 'controlled-peer-key')
    work, written = tmp_path / 'work', tmp_path / 'facts.json'
    work.mkdir()
    others, escaped = bystanders(), None
    owner = subprocess.Popen([sys.executable, '-c', OWNER, str(work), str(TESTS), str(written)],
                             env={**os.environ, 'PYTHONPATH': os.pathsep.join([str(SRC), str(TESTS)])})
    try:
        deadline = time.monotonic() + 30
        while not written.exists() and owner.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        facts = json.loads(written.read_text())
        escaped = escaped_identity(Path(facts['pidfile']))
        web = identity(facts['runtime_pid'])
        owner.kill()
        owner.wait(10)
        # The stand-in reads its owner's death as the watcher's SIGINT and disposes its tool.
        deadline = time.monotonic() + 10
        while web is not None and alive(web) and time.monotonic() < deadline:
            time.sleep(0.05)
        print('after the kill, before reconciliation: escaped', escaped.pid, 'alive', alive(escaped))
        assert alive(escaped), 'precondition: the setsid tool process is the residue'

        control = AgentControl(tmp_path / 'data-root', {'scripted': Recording(
            {key: facts[key] for key in ('tool_marker', 'tool_descendants') if key in facts})})
        call = lambda caller, **request: graftling.bind(control, caller)(request).document
        lead = call(Caller('test-host', None), action='create', runtime='scripted', instruction='lead')
        caller = Caller('test-host', lead['agent'])
        child = call(caller, action='create', runtime='scripted', instruction='work')['agent']
        set_owner(tmp_path / 'data-root', child, runtime_pid=dead_pid())
        status = call(caller, action='status', agent=child)
        execution = record_of(tmp_path / 'data-root', child)['executions'][-1]
        report = execution.get('escaped_processes')
        print('facts:', sorted(facts), '| escaped_processes:', json.dumps(report))
        assert status['result']['last_result']['error']['code'] == 'owner-exited'
        assert not alive(escaped), 'the setsid tool process survived reconciliation'
        assert escaped.pid in [item['pid'] for item in report['stopped']]
        assert report['remaining'] == [] and 'error' not in report
        assert all(process.poll() is None for process in others)
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(10)
        cleanup(escaped, others)


def test_the_dsh_drivers_record_both_facts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """graftling's DshDriver and GraphTraj's AdapterDriver record tool_marker and tool_descendants."""
    import graftling.dsh.binding as binding
    import graftling.dsh.driver as module
    import graphtraj.execution.agent_driver as adapter_module
    import graphtraj.runtimes.dsh.driver as graphtraj_dsh
    from graftling import Run
    from test_reconcile_escaped_tools_457 import Events

    class Turn:
        def __init__(self, *args, **kwargs):
            self.created = kwargs.get('session_created') or args[4]
            self.ready = args[3]
            self.request, self.directory = args[0], args[2]
            self.member_marker = uuid.uuid4().hex
            self.tool_descendants = tmp_path / f'tool-descendants-{self.member_marker}.json'
            self.archive = None

        def run(self):
            self.created('session-463', 4630)
            self.ready('session-463', 4630)
            return {'outcome': 'completed'}

    monkeypatch.setattr(binding, 'bind_run', lambda turn, run: None)
    monkeypatch.setattr(module, 'DshExecution', Turn)
    events = Events()
    run = Run(agent='child', execution='e463', runtime='dsh', settings={}, message='hi', session=None,
              directory=tmp_path, archive=None, events=events)
    module.DshDriver(tmp_path, {}).start(run)
    assert events.ended.wait(10)
    assert set(events.facts) == {'runtime_pid', 'tool_marker', 'tool_descendants'}
    assert Path(events.facts['tool_descendants']).is_absolute()

    class Adapter:
        managed_execution = Turn

    monkeypatch.setattr(adapter_module, 'select_runtime_adapter', lambda runtime: Adapter())
    monkeypatch.setattr(graphtraj_dsh, 'bind_agents', lambda turn, run, driver: None)
    events = Events()
    run = Run(agent='child', execution='e463b', runtime='dsh',
              settings={'adapter_request': {'harness_root': str(tmp_path)}, 'evidence': {},
                        'cwd': str(tmp_path)},
              message='hi', session=None, directory=tmp_path, archive=None, events=events)
    adapter_module.AdapterDriver(tmp_path, tmp_path).start(run)
    assert events.ended.wait(10)
    assert {'tool_marker', 'tool_descendants'} <= set(events.facts)
