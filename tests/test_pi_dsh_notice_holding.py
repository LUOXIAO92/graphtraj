"""The Pi and DSH hosts hold what a stopped parent cannot receive and deliver it once (403).

Each ``native_host`` is one host process's state, through the host's own
``start``: a later one for the same Session and data root is the process that
replaces it. Fake drivers report through the public ``ExecutionEvents``. No
network, no real model.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Callable

import pytest

from agent_swarm import AgentControl, Caller, bind
from agent_swarm.dsh import host as dsh_host
from agent_swarm.pi import host as pi_host


SOURCE = Path(__file__).resolve().parents[1] / 'src'


class Driver:
    """Keeps an execution running until the test ends it or it is interrupted."""

    def __init__(self) -> None:
        self.runs: dict[str, Any] = {}
        self.finish: tuple[str, str | None, dict | None] | None = ('completed', 'the answer', None)

    def prepare(self, runtime, caller, **options):
        """Accept any selection."""
        return {'runtime': runtime}

    def require_available(self, connection) -> None:
        """Every declared connection is installed and logged in here."""

    def start(self, run) -> None:
        """Bind a Session, then end at once unless the test keeps it running."""
        run.events.session('native-' + run.agent[-6:])
        self.runs[run.agent] = run
        if self.finish is not None:
            outcome, message, error = self.finish
            threading.Thread(target=run.events.finished, args=(outcome,),
                             kwargs={'last_message': message, 'error': error}).start()

    def interrupt(self, run) -> bool:
        """End the run as interrupted, with a body the next host can deliver."""
        threading.Thread(target=run.events.finished, args=('interrupted',),
                         kwargs={'last_message': 'partial work'}).start()
        return True

    def requests(self, run) -> list:
        """The core keeps the reported requests itself."""
        return []

    def reply(self, run, request, response) -> dict:
        """Record nothing; answer with a receipt."""
        return {'request_id': request.get('request_id'), 'reply_status': 'sent'}


class Pipe:
    """The extension or plugin side of a host's notice pipe."""

    def __init__(self, shown: bool | None = True) -> None:
        """``shown`` is the acknowledgement to send; ``None`` sends none."""
        self.lines: list[dict] = []
        self.shown = shown
        self.notices = None
        self.on_write: Callable[[dict], None] | None = None

    def write(self, text: str) -> None:
        """Record one notice line and acknowledge it the way the native side does."""
        document = json.loads(text)
        self.lines.append(document['notice'])
        if self.on_write is not None:
            self.on_write(document['notice'])
        if self.shown is not None:
            threading.Thread(target=self.notices.acknowledge, args=(document['notice']['id'], self.shown)).start()

    def flush(self) -> None:
        """Lines are recorded at once."""


class Process:
    """One host process's state, built by that host's own ``start``."""

    def __init__(
        self,
        kind: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        shown: bool | None,
        timeout: float,
        driver: Driver,
    ) -> None:
        """Start the host for the fixed Session ``main`` on this test's data root."""
        self.kind = kind
        self.driver = driver
        self.pipe = Pipe(shown)
        self.host = {'pi': pi_host, 'dsh': dsh_host}[kind]
        monkeypatch.setattr(self.host, 'verify_native_parent', lambda *_: None)
        monkeypatch.setattr(self.host, 'runtime_drivers', lambda *_: {'claude': driver})
        (tmp_path / 'host.json').write_text(json.dumps({'root': str(tmp_path / 'data')}))
        monkeypatch.chdir(tmp_path)
        with monkeypatch.context() as started:
            # The host keeps sys.stdout as its pipe; pytest gets it back after start.
            started.setattr(sys, 'stdout', self.pipe)
            if kind == 'pi':
                started.setenv('AGENT_SWARM_PI_ENTRY', sys.executable)
                started.setattr(pi_host, 'pi_request', lambda *_: {})
                started.setattr(pi_host, 'current_connection', lambda: {
                    'runtime': 'pi', 'session': 'main', 'session_file': str(tmp_path / 's.jsonl')})
                header = {'type': 'session', 'version': 3, 'id': 'main', 'cwd': str(tmp_path)}
                started.setattr(sys, 'stdin', io.StringIO(json.dumps({'header': header, 'entries': []}) + '\n'))
                _, self.notices, self.call, self.inner, self.control, self.caller = pi_host.start(tmp_path / 'host.json')
            else:
                header = {'version': 4, 'id': 'main', 'cwd': str(tmp_path), 'isSeeded': False}
                _, _, self.notices, self.call, self.inner, self.control, self.caller = dsh_host.start(
                    tmp_path / 'host.json', {'header': header})
        self.notices.timeout = timeout
        self.pipe.notices = self.notices

    def flush(self, **options) -> list[dict]:
        """Run this process's flush to its end; return what it wrote."""
        if self.kind == 'dsh':
            options.setdefault('attempts', 1)
        self.notices.flush(self.control, self.caller, **options)
        return self.pipe.lines

    def create(self, instruction: str = 'work') -> str:
        """Create one Claude child through the model-facing entry; return its Agent."""
        result = self.call({'action': 'create', 'runtime': 'claude', 'instruction': instruction})
        assert not result.failed, result.document
        return result.document['agent']

    def last(self, agent: str) -> dict:
        """Read the Agent's last result once it has one."""
        return wait_until(lambda: self.call({'action': 'status', 'agent': agent}).document['result'].get('last_result'))

    def shutdown(self) -> None:
        """What ``main`` does when the native side closes its pipe."""
        self.control.close_notices()
        self.notices.close()
        self.host.stop_children(self.inner)


def wait_until(check, seconds: float = 5.0):
    """Poll ``check`` until it returns a truthy value."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError('condition not reached')


@pytest.fixture(params=['pi', 'dsh'])
def native_host(request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Build one host process of the Pi or DSH host for this test's Session."""
    def build(shown: bool | None = True, timeout: float = 2.0, driver: Driver | None = None) -> Process:
        """One more host process for the same Session and data root."""
        return Process(request.param, tmp_path, monkeypatch, shown, timeout, driver or Driver())

    yield build


def stopped_end(build: Callable) -> tuple[str, Driver]:
    """A child still running when its host shuts down: its end arrives while the parent is stopped."""
    driver = Driver()
    driver.finish = None
    process = build(driver=driver)
    agent = process.create()
    process.shutdown()
    assert process.pipe.lines == []
    return agent, driver


def read_record(tmp_path: Path, agent: str) -> dict:
    """The core's durable record, to tell a held end from a shown one."""
    return json.loads((tmp_path / 'data' / 'control' / 'agents' / f'{agent}.json').read_text())


def test_an_end_arriving_while_stopped_is_held_and_delivered_once_by_the_next_host(native_host: Callable, tmp_path: Path) -> None:
    """Stopped: held, not pushed. New host: pushed once. A further restart: nothing."""
    agent, _ = stopped_end(native_host)
    assert read_record(tmp_path, agent)['executions'][-1]['notification'] == 'held'

    resumed = native_host()
    written = resumed.flush()
    assert [line['event'] for line in written] == ['interrupted']
    assert written[0]['agent'] == agent and written[0]['message'] == 'partial work'
    assert read_record(tmp_path, agent)['executions'][-1]['notification'] == 'delivered'
    assert resumed.flush() == written  # the same process's second flush adds nothing

    assert native_host().flush() == []
    assert resumed.last(agent)['last_message'] is None


def test_a_notice_refused_by_the_session_stays_held_for_the_next_host(native_host: Callable, tmp_path: Path) -> None:
    """``shown: false`` is not delivery: it stays held and readable, and a later host delivers it."""
    agent, _ = stopped_end(native_host)
    refused = native_host(shown=False)
    assert len(refused.flush()) == 1
    assert read_record(tmp_path, agent)['executions'][-1]['notification'] == 'held'

    later = native_host()
    assert [line['agent'] for line in later.flush()] == [agent]
    assert read_record(tmp_path, agent)['executions'][-1]['notification'] == 'delivered'


def test_an_unacknowledged_notice_is_unconfirmed_and_not_repeated(native_host: Callable, tmp_path: Path) -> None:
    """Written with no acknowledgement may have been shown: never repeated."""
    agent, _ = stopped_end(native_host)
    silent = native_host(shown=None, timeout=0.05)
    assert len(silent.flush()) == 1
    assert read_record(tmp_path, agent)['executions'][-1]['notification'] == 'unconfirmed'
    assert native_host().flush() == []


def test_an_end_shown_by_status_is_not_pushed(native_host: Callable, tmp_path: Path) -> None:
    """A held end the Main already read through status or wait is settled, not pushed."""
    agent, _ = stopped_end(native_host)
    resumed = native_host()
    shown = resumed.call({'action': 'status', 'agent': agent}).document['result']['last_result']
    assert shown['last_message'] == 'partial work' and shown['notification'] == 'held'
    assert read_record(tmp_path, agent)['executions'][-1]['notification'] == 'delivered'
    assert resumed.flush() == []


def test_a_hierarchy_status_settles_every_held_end_it_shows(native_host: Callable) -> None:
    """The plain status lists all roots; what it shows is read, so nothing is pushed."""
    driver = Driver()
    driver.finish = None
    process = native_host(driver=driver)
    process.create('one'), process.create('two')
    process.shutdown()
    resumed = native_host()
    assert not resumed.call({'action': 'status'}).failed
    assert resumed.flush() == []


def test_a_body_shown_while_the_flush_runs_is_not_pushed(native_host: Callable) -> None:
    """Two held ends: reading the other one during the first's push keeps it from being pushed."""
    driver = Driver()
    driver.finish = None
    process = native_host(driver=driver)
    first, second = process.create('one'), process.create('two')
    process.shutdown()
    resumed = native_host()
    resumed.pipe.on_write = lambda line: resumed.call({
        'action': 'status', 'agent': first if line['agent'] == second else second})
    assert len(resumed.flush()) == 1


def test_a_held_end_being_flushed_is_hidden_and_not_settled_as_read(native_host: Callable, tmp_path: Path) -> None:
    """During the push a status shows no body and settles nothing; the push settles it."""
    agent, _ = stopped_end(native_host)
    resumed = native_host()
    seen: list[dict] = []
    resumed.pipe.on_write = lambda line: seen.append(
        resumed.call({'action': 'status', 'agent': agent}).document['result']['last_result'])
    assert len(resumed.flush()) == 1
    assert seen[0]['notification'] == 'queueing' and seen[0]['last_message'] is None
    assert read_record(tmp_path, agent)['executions'][-1]['notification'] == 'delivered'


def test_a_refused_flush_does_not_lose_a_body_read_during_it(native_host: Callable, tmp_path: Path) -> None:
    """Hidden during the push and then refused: the body is still readable afterwards."""
    agent, _ = stopped_end(native_host)
    resumed = native_host(shown=False)
    resumed.pipe.on_write = lambda line: resumed.call({'action': 'status', 'agent': agent})
    resumed.flush()
    assert resumed.last(agent)['last_message'] == 'partial work'


def test_shutdowns_own_wait_does_not_settle_the_ends_it_causes(native_host: Callable, tmp_path: Path) -> None:
    """The internal wait is not the Main reading: those ends stay held for the next host."""
    agent, _ = stopped_end(native_host)
    record = read_record(tmp_path, agent)['executions'][-1]
    assert (record['outcome'], record['notification']) == ('interrupted', 'held')
    assert native_host().flush()


def test_a_live_end_is_pushed_once_with_the_host_up(native_host: Callable, tmp_path: Path) -> None:
    """The ordinary path is unchanged: pushed once, then no flush repeats it."""
    process = native_host()
    agent = process.create()
    wait_until(lambda: read_record(tmp_path, agent)['executions'][-1].get('notification') == 'delivered')
    assert [line['event'] for line in process.pipe.lines] == ['completed']
    assert process.flush() == process.pipe.lines
    assert native_host().flush() == []


def test_a_refused_request_stays_held_while_it_waits_and_is_flushed_once(native_host: Callable, tmp_path: Path) -> None:
    """A request refused live is delivered by the host's flush, and then not again."""
    driver = Driver()
    driver.finish = None
    process = native_host(shown=False, driver=driver)
    agent = process.create()
    run = wait_until(lambda: driver.runs.get(agent))
    run.events.request({'request_token': 'token-1', 'request_id': 7, 'method': 'claude/can_use_tool',
                        'params': {'tool_name': 'Bash'}})
    assert [line['id'] for line in process.pipe.lines] == [f'{run.execution}:request:token-1']
    assert process.call({'action': 'status', 'agent': agent}).document['result']['pending_requests'] == 1
    process.pipe.shown = True
    process.flush()
    assert [line['id'] for line in process.pipe.lines] == [f'{run.execution}:request:token-1'] * 2
    assert process.flush() == process.pipe.lines
    assert len(process.pipe.lines) == 2
    assert process.call({'action': 'status', 'agent': agent}).document['result']['pending_requests'] == 1


def requesting(build: Callable) -> tuple[Process, str, Any]:
    """A running child under a host that takes its notices."""
    driver = Driver()
    driver.finish = None
    process = build(driver=driver)
    agent = process.create()
    return process, agent, wait_until(lambda: driver.runs.get(agent))


def test_each_native_request_notifies_once_with_its_own_identity(native_host: Callable) -> None:
    """Two requests are two notices; a repeated report notifies nobody."""
    process, _, run = requesting(native_host)
    for token in ('token-1', 'token-1', 'token-2', 'token-2'):
        run.events.request({'request_token': token, 'request_id': token, 'method': 'claude/can_use_tool',
                            'params': {'tool_name': 'Bash', 'input': {'command': 'SECRET'}}})
    assert [line['id'] for line in process.pipe.lines] == [
        f'{run.execution}:request:token-1', f'{run.execution}:request:token-2']
    assert process.pipe.lines[0]['event'] == 'request'
    assert 'claude/can_use_tool for Bash' in process.pipe.lines[0]['message']
    assert 'SECRET' not in json.dumps(process.pipe.lines)


def test_ask_parent_notifies_once_without_its_question(native_host: Callable) -> None:
    """A child's decision request reaches the Main like a native one; asking again is the same request."""
    process, agent, run = requesting(native_host)
    child = bind(process.control, Caller('runtime-mcp', agent))
    for _ in range(2):
        asked = child({'action': 'ask_parent', 'kind': 'decision', 'question': 'Secret option?',
                       'timeout_seconds': 0.05}).document['result']
    assert len(process.pipe.lines) == 1
    assert process.pipe.lines[0]['id'] == f"{run.execution}:request:{asked['request']['request_token']}"
    assert 'agents/decision' in process.pipe.lines[0]['message'] and 'Secret' not in process.pipe.lines[0]['message']


def test_dsh_flush_retries_a_refusal_within_its_bound_without_spinning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A Session not active yet refuses: retried with a pause, within the bound, then left held."""
    build = lambda **options: Process('dsh', tmp_path, monkeypatch, options.get('shown', True), 2.0,
                                      options.get('driver') or Driver())
    agent, _ = stopped_end(build)

    host = build(shown=False)
    pauses: list[float] = []
    real_wait = host.notices.closed.wait

    def counted(pause: float) -> bool:
        """Record the pause without waiting for it."""
        pauses.append(pause)
        return real_wait(0)

    monkeypatch.setattr(host.notices.closed, 'wait', counted)
    host.notices.flush(host.control, host.caller, attempts=3, pause=7.0)
    assert len(host.pipe.lines) == 3 and pauses == [7.0, 7.0]
    assert read_record(tmp_path, agent)['executions'][-1]['notification'] == 'held'

    # Accepted on the second attempt: exactly one more write, then the flush ends.
    host = build(shown=False)
    host.pipe.on_write = lambda line: setattr(host.pipe, 'shown', len(host.pipe.lines) > 1)
    pauses.clear()
    monkeypatch.setattr(host.notices.closed, 'wait', counted)
    host.notices.flush(host.control, host.caller, attempts=dsh_host.FLUSH_ATTEMPTS, pause=0.0)
    assert len(host.pipe.lines) == 2
    assert read_record(tmp_path, agent)['executions'][-1]['notification'] == 'delivered'
    assert dsh_host.FLUSH_ATTEMPTS == 6 and dsh_host.FLUSH_RETRY_SECONDS == 5.0


def test_dsh_flush_retry_stops_at_shutdown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Shutdown during the pause ends the flush at once, leaving the notice held."""
    build = lambda **options: Process('dsh', tmp_path, monkeypatch, options.get('shown', True), 2.0,
                                      options.get('driver') or Driver())
    agent, _ = stopped_end(build)
    host = build(shown=False)
    worker = threading.Thread(target=host.notices.flush, args=(host.control, host.caller),
                              kwargs={'attempts': 6, 'pause': 60.0})
    worker.start()
    wait_until(lambda: host.pipe.lines)
    wait_until(lambda: read_record(tmp_path, agent)['executions'][-1]['notification'] == 'held')
    time.sleep(0.05)
    host.notices.close()
    worker.join(5)
    assert not worker.is_alive() and len(host.pipe.lines) == 1


# The native parent for a real host process: it starts the host, says ready when
# told to, acknowledges notices as told, and reports what it saw.
NATIVE = '''
import json, os, subprocess, sys, threading, time
host = subprocess.Popen([sys.executable, '-m', os.environ['TEST_MODULE'], '--config', os.environ['TEST_CONFIG']],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
host.stdin.write(os.environ['TEST_LAUNCH'] + '\\n')
host.stdin.flush()
first = host.stdout.readline()
notices = []
def read():
    for line in host.stdout:
        document = json.loads(line)
        notices.append(document['notice'])
        if os.environ['TEST_SHOWN'] != 'none':
            host.stdin.write(json.dumps({'ack': document['notice']['id'], 'shown': os.environ['TEST_SHOWN'] == 'true'}) + '\\n')
            host.stdin.flush()
threading.Thread(target=read, daemon=True).start()
time.sleep(0.3)
before = len(notices)
if os.environ['TEST_READY'] == '1':
    host.stdin.write('{"ready": true}\\n')
    host.stdin.write('{"ready": true}\\n')
    host.stdin.flush()
    expect = int(os.environ['TEST_EXPECT'])
    deadline = time.monotonic() + (30 if expect else 1)
    while time.monotonic() < deadline and (not expect or len(notices) < expect):
        time.sleep(0.02)
host.stdin.close()
code = host.wait(30)
print(json.dumps({'first': first, 'before_ready': before, 'notices': notices, 'code': code, 'stderr': host.stderr.read()}))
'''


def seed_held(tmp_path: Path, caller: Caller) -> str:
    """One held end, recorded with no host running, as a stopped parent's child leaves it."""
    driver = Driver()
    control = AgentControl(tmp_path / 'data', {'claude': driver}, hold_notices=True)
    result = bind(control, caller)({'action': 'create', 'runtime': 'claude', 'instruction': 'work'})
    assert not result.failed, result.document
    agent = result.document['agent']
    wait_until(lambda: read_record(tmp_path, agent)['executions'][-1].get('notification') == 'held')
    return agent


def run_native(tmp_path: Path, kind: str, ready: bool = True, shown: str = 'true', expect: int = 1) -> dict:
    """Run a real host process below a stand-in native parent for this Session."""
    package = tmp_path / 'native' / 'dsh'
    (package / 'lib').mkdir(parents=True, exist_ok=True)
    (package / 'package.json').write_text(json.dumps({'name': '@deepseek-ai/dsh', 'version': '0.2.2-alpha.2'}))
    entry = package / 'lib' / 'bin.py'
    entry.write_text(NATIVE)
    (tmp_path / 'host.json').write_text(json.dumps({'root': str(tmp_path / 'data')}))
    env = {key: value for key, value in os.environ.items()
           if key not in {'AGENT_SWARM_CONNECTION', 'DSH_SESSION_ID', 'DSH_AGENT_SOURCE', 'DSH_AGENT_PACKAGE'}}
    env.update(TEST_CONFIG=str(tmp_path / 'host.json'), PYTHONPATH=str(SOURCE), TEST_SHOWN=shown,
               TEST_READY='1' if ready else '0', TEST_EXPECT=str(expect))
    if kind == 'pi':
        header = {'type': 'session', 'version': 3, 'id': 'main', 'cwd': str(tmp_path)}
        env.update(TEST_MODULE='agent_swarm.pi.host', TEST_LAUNCH=json.dumps({'header': header, 'entries': []}),
                   AGENT_SWARM_PI_ENTRY=sys.executable, AGENT_SWARM_PI_PROVIDER='anthropic',
                   AGENT_SWARM_PI_MODEL='parent-model', GRAPHTRAJ_NATIVE_RUNTIME='pi',
                   GRAPHTRAJ_NATIVE_SESSION='main', GRAPHTRAJ_NATIVE_SESSION_FILE=str(tmp_path / 's.jsonl'),
                   PI_CODING_AGENT_DIR=str(tmp_path / 'pi-home'))
    else:
        header = {'version': 4, 'id': 'main', 'cwd': str(tmp_path), 'isSeeded': False}
        env.update(TEST_MODULE='agent_swarm.dsh.host', TEST_LAUNCH=json.dumps({'header': header}),
                   AGENT_SWARM_DSH_NODE=sys.executable, AGENT_SWARM_DSH_ENTRY=str(entry))
    result = subprocess.run([sys.executable, str(entry)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


CALLERS = {'pi': Caller('pi-native', None, session='main', runtime='pi'),
           'dsh': Caller('dsh-native', None, session='main', runtime='dsh')}


@pytest.mark.parametrize('kind', ['pi', 'dsh'])
def test_a_real_host_process_flushes_once_after_ready_and_a_further_restart_delivers_nothing(tmp_path: Path, kind: str) -> None:
    """The real entry: connection first, nothing before ready, once after it, nothing on restart."""
    agent = seed_held(tmp_path, CALLERS[kind])
    outcome = run_native(tmp_path, kind)
    assert outcome['code'] == 0, outcome['stderr']
    assert json.loads(outcome['first'])['connection']
    assert outcome['before_ready'] == 0
    assert [notice['agent'] for notice in outcome['notices']] == [agent]
    assert read_record(tmp_path, agent)['executions'][-1]['notification'] == 'delivered'
    again = run_native(tmp_path, kind, expect=0)
    assert again['code'] == 0, again['stderr']
    assert again['notices'] == []


@pytest.mark.parametrize('kind', ['pi', 'dsh'])
def test_a_real_host_process_that_is_never_told_ready_keeps_its_notices_held(tmp_path: Path, kind: str) -> None:
    """A Session that never takes a turn: nothing is written, and the next host still has it."""
    agent = seed_held(tmp_path, CALLERS[kind])
    outcome = run_native(tmp_path, kind, ready=False)
    assert outcome['code'] == 0, outcome['stderr']
    assert outcome['notices'] == []
    assert read_record(tmp_path, agent)['executions'][-1]['notification'] == 'held'
    assert len(run_native(tmp_path, kind)['notices']) == 1


def test_a_real_host_refused_notice_stays_held(tmp_path: Path) -> None:
    """The Pi host's flush is once per process: refused stays held for the next one."""
    agent = seed_held(tmp_path, CALLERS['pi'])
    outcome = run_native(tmp_path, 'pi', shown='false')
    assert outcome['code'] == 0, outcome['stderr']
    assert len(outcome['notices']) == 1
    assert read_record(tmp_path, agent)['executions'][-1]['notification'] == 'held'


def test_a_real_host_unacknowledged_notice_ends_as_held_at_shutdown_and_is_replayed(tmp_path: Path) -> None:
    """Silence cut short by shutdown was never settled as shown: the next host replays it."""
    agent = seed_held(tmp_path, CALLERS['pi'])
    outcome = run_native(tmp_path, 'pi', shown='none')
    assert outcome['code'] == 0, outcome['stderr']
    assert len(outcome['notices']) == 1
    assert read_record(tmp_path, agent)['executions'][-1]['notification'] == 'held'
    assert len(run_native(tmp_path, 'pi')['notices']) == 1


# --- The native sides, with recording fakes ---

EXTENSION = '''
import { pathToFileURL } from 'node:url';
const module = await import(pathToFileURL(process.argv[1]).href);
const sent = [], handlers = {};
const entries = JSON.parse(process.env.TEST_ENTRIES);
const pi = {
  registerFlag() {}, getFlag: name => name === 'agents-config' ? process.env.TEST_CONFIG : undefined,
  on: (event, handler) => { handlers[event] = handler; }, registerMcpServer() {}, registerEntryRenderer() {},
  sendMessage: (message, options) => { sent.push({message, options}); },
};
process.argv[1] = process.env.TEST_ENTRY;
const ctx = {hasUI: process.env.TEST_UI === '1', cwd: process.cwd(), sessionManager: {
  getSessionId: () => 'pi-main', getSessionFile: () => '', getHeader: () => ({id: 'pi-main'}), getEntries: () => entries}};
const owner = module.registerAgents(pi);
await owner.start(ctx);
if (process.env.TEST_TURN === '1') setTimeout(() => { handlers.agent_start({type: 'agent_start'}, ctx); handlers.agent_start({type: 'agent_start'}, ctx); }, 200);
setTimeout(async () => { await owner.close(); console.log(JSON.stringify(sent)); }, Number(process.env.TEST_RUN_MS));
'''

FAKE_EXTENSION_HOST = '''
import json, os, sys
sys.stdin.readline()
print(json.dumps({'connection': '/fake/address'}), flush=True)
received = []
for line in sys.stdin:
    message = json.loads(line)
    received.append(message)
    if message == {'ready': True}:
        for identity in os.environ['TEST_NOTICES'].split(','):
            print(json.dumps({'notice': {'id': identity, 'alias': 'agent-1', 'agent': 'agent-1', 'event': 'completed',
                                         'message': 'the answer', 'execution': identity.split(':')[0]}}), flush=True)
with open(os.environ['TEST_LOG'], 'w') as log:
    json.dump(received, log)
'''


def run_extension(tmp_path: Path, *, entries: list | None = None, ui: bool = False, turn: bool = True,
                  notices: str = 'exec-1:completed', run_ms: int = 1500) -> tuple[list, list]:
    """Drive the real extension.mjs with a recording Pi and a scripted host."""
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required')
    fake = tmp_path / 'fake-python'
    fake.write_text('#!' + sys.executable + '\n' + FAKE_EXTENSION_HOST)
    fake.chmod(0o755)
    # A Session with a UI also loads the display from the owning Pi package.
    package = tmp_path / 'pi-package'
    package.mkdir(exist_ok=True)
    (package / 'package.json').write_text(json.dumps({'name': '@earendil-works/pi-coding-agent',
                                                      'exports': {'.': {'import': './index.mjs'}}}))
    (package / 'index.mjs').write_text('export class CustomMessageComponent {}')
    (package / 'cli.js').write_text('')
    env = {key: value for key, value in os.environ.items()
           if key not in {'AGENT_SWARM_CONNECTION', 'DSH_SESSION_ID', 'DSH_AGENT_SOURCE'}}
    env.update(AGENT_SWARM_PYTHON=str(fake), TEST_CONFIG=str(tmp_path / 'host.json'), TEST_LOG=str(tmp_path / 'log.json'),
               TEST_ENTRY=str(package / 'cli.js'),
               TEST_ENTRIES=json.dumps(entries or []), TEST_UI='1' if ui else '0', TEST_TURN='1' if turn else '0',
               TEST_NOTICES=notices, TEST_RUN_MS=str(run_ms))
    result = subprocess.run([node, '--input-type=module', '-e', EXTENSION, str(SOURCE / 'agent_swarm/pi/extension.mjs')],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout), json.loads((tmp_path / 'log.json').read_text())


def test_extension_does_not_inject_a_replayed_notice_and_acknowledges_it(tmp_path: Path) -> None:
    """A notice already in the Session's entries (crash before the ack) is shown, not injected again."""
    persisted = {'type': 'custom_message', 'customType': 'graphtraj:agent-communication', 'id': 'e1',
                 'content': 'x', 'display': True, 'details': {'fact': 'notice:exec-1:completed'}}
    sent, received = run_extension(tmp_path, entries=[persisted], notices='exec-1:completed,exec-2:completed')
    assert [item['message']['details']['fact'] for item in sent] == ['notice:exec-2:completed']
    assert received == [{'ready': True}, {'ack': 'exec-1:completed', 'shown': True},
                        {'ack': 'exec-2:completed', 'shown': True}]


@pytest.mark.parametrize('entry', [
    {'type': 'custom', 'customType': 'graphtraj:agent-communication', 'data': {'fact': 'notice:exec-1:completed'}},
    {'type': 'custom_message', 'customType': 'someone-else', 'details': {'fact': 'notice:exec-1:completed'}},
    {'type': 'custom_message', 'customType': 'graphtraj:agent-communication', 'details': {'fact': 'notice:other'}},
    {'type': 'custom_message', 'customType': 'graphtraj:agent-communication'},
])
def test_extension_dedupes_only_on_its_own_persisted_notice(tmp_path: Path, entry: dict) -> None:
    """Display entries, other extensions' messages and other notices do not count as this notice."""
    sent, _ = run_extension(tmp_path, entries=[entry])
    assert len(sent) == 1


def test_extension_says_ready_once_at_the_first_turn_and_not_before(tmp_path: Path) -> None:
    """In print mode the prompt must start first: ready follows agent_start, once."""
    _, received = run_extension(tmp_path, turn=True)
    assert received.count({'ready': True}) == 1
    (tmp_path / 'log.json').unlink()
    sent, received = run_extension(tmp_path, turn=False)
    assert sent == [] and received == []  # no UI and no turn: nothing flushes


def test_extension_with_a_ui_says_ready_after_its_grace_when_no_turn_starts(tmp_path: Path) -> None:
    """An interactive Session with no prompt on its way takes held notices by itself."""
    sent, received = run_extension(tmp_path, ui=True, turn=False, run_ms=4000)
    assert received[0] == {'ready': True} and len(sent) == 1
    (tmp_path / 'log.json').unlink()
    sent, received = run_extension(tmp_path, ui=True, turn=False, run_ms=500)
    assert sent == [] and received == []


COMMUNICATION = '''
import { pathToFileURL } from 'node:url';
const { installCommunication } = await import(pathToFileURL(process.argv[1]).href);
class TypertRemoteService { constructor(ctx) { this.ctx = ctx; } }
const Remote = () => {};
const createUserMessage = message => message;
// One native log across two processes; one inbox per process.
const log = [];
function process_(active) {
  const inbox = { nextTurn: [], nextStep: [] };
  const sent = [];
  const agent = { inbox, send(message, target, wake) { sent.push({ target, wake }); inbox.nextStep.push(message);
    log.push({ type: 'user/message', data: { source: message.source } }); inbox.nextStep.pop(); } };
  let service;
  const ctx = {
    agents: { get: id => active && id === 'main' ? agent : undefined },
    sessionQuery: { observeSession: async () => ({ events: log, [Symbol.dispose]() {} }) },
    plugin: Service => { service = new Service(ctx); return service; },
  };
  installCommunication(ctx, { TypertRemoteService, Remote, createUserMessage });
  return { service, sent };
}
const request = { id: 'agents-notice:exec-1:completed', sessionId: 'main', senderSessionId: 'child', sender: 'agent-1',
                  recipient: 'main', body: '[agents notice from agent-1 · completed]\\nthe answer' };
const outcomes = [];
const inactive = process_(false);
try { await inactive.service.receive(request); outcomes.push('accepted'); } catch (error) { outcomes.push(error.message); }
const first = process_(true);
outcomes.push(await first.service.receive(request));
outcomes.push(await first.service.receive(request));
const second = process_(true);
outcomes.push(await second.service.receive(request));
console.log(JSON.stringify({ outcomes, sent: [first.sent.length, second.sent.length], log: log.length }));
'''


def test_the_dsh_relay_admits_one_id_once_across_processes_and_refuses_an_inactive_session(tmp_path: Path) -> None:
    """The once-only guard the DSH flush relies on: communication.mjs, the shipped file."""
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required')
    result = subprocess.run([node, '--input-type=module', '-e', COMMUNICATION,
                             str(SOURCE / 'agent_swarm/dsh/communication.mjs')],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert document['outcomes'] == ['The native recipient Session is not active in this host',
                                    {'accepted': True, 'duplicate': False},
                                    {'accepted': True, 'duplicate': True},
                                    {'accepted': True, 'duplicate': True}]
    assert document['sent'] == [1, 0] and document['log'] == 1


def test_a_nested_dsh_parent_gives_each_request_its_own_relay_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The relay admits one id once: a second request, or the end after one, must not share it."""
    from agent_swarm.dsh import binding

    messages: list[dict] = []
    receivers: list = []

    class Turn:
        """An active native turn: only what ``receive`` reads."""

        lock = threading.Lock()
        active, session, execution_id = True, 'parent-session', 'parent-exec'
        stopping = finished = threading.Event()

        def operate(self, request: dict) -> dict:
            """Record the relay message; the relay admits it."""
            messages.append(request['message'])
            return {'accepted': True}

    class Events:
        """Keep the receiver the binding registers."""

        receive_children = staticmethod(receivers.append)

    class Run:
        """The parent execution's public fields the binding reads."""

        agent, call, archive, settings, events = 'parent', object(), None, {}, Events()

    binding.bind_run(Turn(), Run())
    event = {'parent': 'parent', 'agent': 'child', 'session': 'child-session', 'execution': 'exec-1', 'body': 'text'}
    for notice in ({**event, 'outcome': 'request', 'request': 'token-1'},
                   {**event, 'outcome': 'request', 'request': 'token-2'},
                   {**event, 'outcome': 'completed'}):
        assert receivers[0](notice) is True
    assert [message['id'] for message in messages] == ['exec-1:request:token-1', 'exec-1:request:token-2', 'exec-1']


STUBS = {
    'dsh-mcp-client': 'export default { name: "mcp-client" };',
    'schemastery': '''const chain = () => ({ default: () => chain(), required: () => chain() });
export default { object: () => ({}), string: chain, array: chain };''',
    'dsh-typert-protocol': 'export class TypertRemoteService {}\nexport function Remote() {}',
    'dsh-llm': 'export function createUserMessage(message) { return message; }',
}

PLUGIN = '''
import { pathToFileURL } from 'node:url';
const plugin = await import(pathToFileURL(process.argv[1]).href);
const handlers = {}, effects = [];
const ctx = {
  on: (event, handler) => { handlers[event] = handler; }, effect: effect => effects.push(effect),
  plugin: () => ({}), logger: { error() {} },
  get: () => ({ receive: async () => ({ accepted: true }) }),
};
const agent = {
  status: 'idle',
  session: { id: 'main', header: { version: 4, id: 'main', cwd: process.cwd(), isSeeded: false } },
  model: { current: () => ({ model: 'm' }) },
  ctx: { plugin: () => ({ await: async () => {} }) },
};
plugin.apply(ctx, {});
await handlers['agent/created']({ agent });
if (process.env.TEST_TURN_MS) setTimeout(() => { agent.status = 'running'; }, Number(process.env.TEST_TURN_MS));
await new Promise(done => setTimeout(done, Number(process.env.TEST_RUN_MS)));
await handlers['session/disposed']({ id: 'main' });
console.log('{}');
'''

FAKE_PLUGIN_HOST = '''
import json, os, sys, time
sys.stdin.readline()
print(json.dumps({'connection': '/fake/address'}), flush=True)
started = time.monotonic()
received = []
for line in sys.stdin:
    received.append({'message': json.loads(line), 'after': time.monotonic() - started})
with open(os.environ['TEST_LOG'], 'w') as log:
    json.dump(received, log)
'''


def run_plugin(tmp_path: Path, **environment: str) -> list:
    """Drive the real plugin.mjs's host row with stub DSH packages and a scripted host."""
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required')
    modules = tmp_path / 'stub' / 'node_modules' / '@deepseek-ai'
    for name, text in STUBS.items():
        (modules / name).mkdir(parents=True, exist_ok=True)
        (modules / name / 'package.json').write_text(json.dumps({'name': f'@deepseek-ai/{name}', 'type': 'module',
                                                                 'main': 'index.js'}))
        (modules / name / 'index.js').write_text(text)
    fake = tmp_path / 'fake-python'
    fake.write_text('#!' + sys.executable + '\n' + FAKE_PLUGIN_HOST)
    fake.chmod(0o755)
    env = {key: value for key, value in os.environ.items()
           if key not in {'AGENT_SWARM_CONNECTION', 'DSH_AGENT_PACKAGE', 'GRAPHTRAJ_CLI_CONNECTION'}}
    env.update(GRAPHTRAJ_DSH_PACKAGE=str(tmp_path / 'stub' / 'entry.js'), AGENT_SWARM_PYTHON=str(fake),
               AGENT_SWARM_DSH_CONFIG='/abs/dsh-host.json', TEST_LOG=str(tmp_path / 'log.json'), **environment)
    result = subprocess.run([node, '--input-type=module', '-e', PLUGIN, str(SOURCE / 'agent_swarm/dsh/plugin.mjs')],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads((tmp_path / 'log.json').read_text())


def test_plugin_says_ready_when_the_sessions_turn_begins_not_at_attach(tmp_path: Path) -> None:
    """A wake before the runner's task would run ahead of its permission settings."""
    received = run_plugin(tmp_path, TEST_TURN_MS='400', TEST_RUN_MS='1500')
    assert [item['message'] for item in received] == [{'ready': True}]
    assert received[0]['after'] >= 0.3


def test_plugin_says_ready_after_its_grace_in_a_session_with_no_turn(tmp_path: Path) -> None:
    """A long-lived profile starts no turn by itself: it takes held notices after the grace."""
    assert run_plugin(tmp_path, TEST_RUN_MS='500') == []
    (tmp_path / 'log.json').unlink()
    received = run_plugin(tmp_path, TEST_RUN_MS='4000')
    assert [item['message'] for item in received] == [{'ready': True}]
