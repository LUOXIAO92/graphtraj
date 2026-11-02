"""A refused reply is answered at once and leaves the agents channel working (435).

Each test speaks stdio JSON-RPC to the real MCP entry against the real channel,
control and driver. The child is the controlled Claude CLI or DSH service, which
holds a real pending request. Every wait is bounded, so the old code fails
these tests instead of hanging them.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time
from typing import Callable, Iterator
from uuid import uuid4

import pytest

import agent_swarm
from agent_swarm import AgentsResult
from agent_swarm.claude.driver import ClaudeDriver
from agent_swarm.claude.execution import ClaudeExecution
from agent_swarm.codex.host import CodexHost
from agent_swarm.connection import agents_connection
from agent_swarm.dsh import execution as dsh_execution
from agent_swarm.process import authenticate_process
from agent_swarm.runtime import RuntimeAdapterError
from dsh_standalone_peer import FakeDshService
from test_claude_runtime import claude_environment  # noqa: F401 - pytest fixture
from test_codex_independent_control import native_settings  # noqa: F401 - pytest fixture
from test_dsh_standalone_child import declare, dsh  # noqa: F401 - pytest fixture
from test_pi_dsh_notice_holding import Process

# Far longer than a refusal takes; the old code never answers at all.
PROMPT = 10.0
WAIT = 30.0
AGENT_ENV = ('AGENT_SWARM_CONNECTION', 'GRAPHTRAJ_CLI_CONNECTION', 'GRAPHTRAJ_NATIVE_RUNTIME',
             'DSH_SESSION_ID', 'DSH_AGENT_SOURCE')
SOURCE = str(Path(agent_swarm.__file__).parents[1])
ALLOWED = {'behavior': 'allow', 'updatedInput': {'command': 'echo approved'}}


def bounded_environment(**extra: str) -> dict:
    """The MCP entry's environment, with no other host's binding."""
    env = {name: value for name, value in os.environ.items() if name not in AGENT_ENV}
    return {**env, 'PYTHONPATH': SOURCE, **extra}


class Client:
    """One stdio MCP peer; every read is bounded and the process never outlives the test."""

    def __init__(self, command: list[str], env: dict, cwd: Path, meta: dict | None = None,
                 prepare: Callable[[dict], None] | None = None, stderr: Path | None = None) -> None:
        """Start the entry and read its messages from a thread, so a silent one cannot block the test."""
        self.meta = meta
        self.prepare = prepare
        self.counter = 0
        self.messages: queue.Queue = queue.Queue()
        sink = stderr.open('a') if stderr is not None else subprocess.DEVNULL
        self.process = subprocess.Popen(command, env=env, cwd=cwd, text=True, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=sink,
                                        preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
        if stderr is not None:
            sink.close()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.process.stdout:
            self.messages.put(json.loads(line))

    def send(self, document: dict, timeout: float) -> dict:
        """Exchange one JSON-RPC message; silence fails the test at ``timeout``."""
        self.counter += 1
        self.process.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': self.counter, **document}) + '\n')
        self.process.stdin.flush()
        try:
            reply = self.messages.get(timeout=timeout)
        except queue.Empty:
            pytest.fail(f"{document.get('params', {}).get('arguments', {}).get('feature', document['method'])}: "
                        f'the MCP entry sent nothing within {timeout} s')
        assert reply['id'] == self.counter, reply
        return reply

    def call(self, feature: str, *, timeout: float = PROMPT, **arguments: object) -> tuple[dict, bool]:
        """Call one agents feature as the model does; return its document and isError."""
        request = {'action': 'execute', 'feature': feature, 'arguments': arguments}
        if self.prepare is not None:
            self.prepare(request)
        params = {'name': 'agents', 'arguments': request}
        if self.meta is not None:
            params['_meta'] = self.meta
        result = self.send({'method': 'tools/call', 'params': params}, timeout)['result']
        return result['structuredContent'], result['isError']

    def ok(self, feature: str, *, timeout: float = PROMPT, **arguments: object) -> dict:
        """Call one feature that must succeed."""
        document, failed = self.call(feature, timeout=timeout, **arguments)
        assert not failed, document
        return document

    def close(self) -> None:
        """Close stdin and leave no process behind."""
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


@contextmanager
def channel(directory: Path, operate: Callable, cwd: Path, *, native_context=None, env: dict | None = None,
            meta: dict | None = None) -> Iterator[Client]:
    """The real channel and kernel caller proof, with the real MCP entry as the only client."""
    holder: list[Client] = []
    with agents_connection(directory, operate, lambda pid: authenticate_process(holder[0].process, pid),
                           native_context=native_context) as address:
        client = Client([sys.executable, '-m', 'agent_swarm.mcp'],
                        bounded_environment(AGENT_SWARM_CONNECTION=address, **(env or {})), cwd, meta=meta)
        holder.append(client)
        try:
            yield client
        finally:
            client.close()


@contextmanager
def native_host(kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Client, Process]]:
    """The Pi or DSH host's own ``start`` and ``operate``, owning a real Claude driver."""
    host = Process(kind, tmp_path, monkeypatch, True, 2.0, ClaudeDriver(tmp_path, {}))
    try:
        if kind == 'pi':
            with channel(tmp_path / 'data' / 'live' / 'pi-host', host.call, tmp_path) as client:
                yield client, host
        else:
            expected = {'runtime': 'dsh', 'session': 'main', 'source': 'main', 'cwd': str(tmp_path)}
            with channel(tmp_path / 'data' / 'live' / 'dsh-host', host.call, tmp_path,
                         native_context=lambda: expected,
                         env={'DSH_SESSION_ID': 'main', 'DSH_AGENT_SOURCE': 'main'}) as client:
                yield client, host
    finally:
        host.shutdown()


@contextmanager
def codex_host(settings: dict, tmp_path: Path) -> Iterator[tuple[Client, CodexHost]]:
    """A real CodexHost's control, ``_call_agents`` and ``bind_connection``; no native Codex runs."""
    host = CodexHost(settings, tmp_path / 'host', 'unused')
    host.native_session = 'thread-435'
    holder: list[Client] = []
    # The real rule needs a running service; this keeps the kernel proof on the MCP entry.
    host._authenticate_mcp = lambda pid: authenticate_process(holder[0].process, pid)
    try:
        with ExitStack() as connections:
            address, name, module = host.bind_connection(connections, {}, tmp_path)
            client = Client([sys.executable, '-m', module],
                            bounded_environment(**{name: address, 'GRAPHTRAJ_NATIVE_RUNTIME': 'codex'}),
                            tmp_path, meta={'threadId': host.native_session})
            holder.append(client)
            try:
                yield client, host
            finally:
                client.close()
    finally:
        stop_owned(host.control)


def stop_owned(control) -> None:
    """Stop what the test's host still owns."""
    for owned in control.interrupt_owned():
        deadline = time.monotonic() + 10
        while control.owns_running(owned) and time.monotonic() < deadline:
            time.sleep(0.05)


@contextmanager
def claude_host(tmp_path: Path) -> Iterator[tuple[Client, Path]]:
    """The real Claude host process, whose verified native parent is this test's process."""
    project = tmp_path / 'project'
    root = project / '.agents-control'
    root.mkdir(parents=True)
    config = root / 'claude-host.json'
    config.write_text(json.dumps({'root': str(root), 'cwd': str(project), 'claude': sys.executable,
                                  'channel_file': str(root / 'live' / 'channel.json'), 'settings': {}}))
    session = str(uuid4())
    env = bounded_environment()

    def prepare(request: dict) -> None:
        """The native mod's per-call context step, as a direct child of the same parent."""
        native = {'operation': 'prepare', 'tool': 'agents', 'session': session, 'cwd': str(project),
                  'agent': None, 'request': request}
        done = subprocess.run([sys.executable, '-m', 'agent_swarm.claude.host', 'context', '--config', str(config)],
                              input=json.dumps(native), capture_output=True, text=True, timeout=PROMPT, env=env)
        assert done.returncode == 0, done.stderr

    client = Client([sys.executable, '-m', 'agent_swarm.claude.host', 'serve', '--config', str(config)],
                    env, project)
    try:
        assert client.send({'method': 'initialize', 'params': {}}, WAIT)['result']['serverInfo']['name'] == 'agents'
        client.prepare = prepare
        yield client, root
    finally:
        client.process.send_signal(signal.SIGINT)
        try:
            client.process.wait(timeout=WAIT)
        except subprocess.TimeoutExpired:
            client.process.kill()
            client.process.wait(timeout=5)


def read_record_at(root: Path, agent: str) -> dict:
    """The core's durable record under one host's data root."""
    return json.loads((root / 'control' / 'agents' / f'{agent}.json').read_text())


def pending_request(client: Client, runtime: str, instruction: str, method: str) -> tuple[str, dict]:
    """Create a child and return the one native request it is waiting on."""
    agent = client.ok('create', timeout=WAIT, runtime=runtime, instruction=instruction)['agent']
    waited = client.ok('wait', timeout=WAIT, agent=agent, timeout_seconds=20)
    assert waited['result']['pending_requests'] == 1, waited
    [request] = client.ok('requests', agent=agent)['result']['requests']
    assert request['method'] == method
    return agent, request


def refuse(client: Client, agent: str, request: dict, response: dict) -> str:
    """A wrong form is refused promptly and changes nothing; return the reason."""
    started = time.monotonic()
    refused, failed = client.call('reply', agent=agent, request=request, response=response)
    assert failed, refused
    assert time.monotonic() - started < PROMPT
    assert refused['error']['code'] == 'invalid-input', refused
    # The same MCP process still serves, and the request is still there to answer.
    status = client.ok('status', agent=agent)
    assert status['result']['state'] == 'active' and status['result']['pending_requests'] == 1, status
    [still] = client.ok('requests', agent=agent)['result']['requests']
    assert still['request_token'] == request['request_token']
    return refused['error']['message']


def answer_claude_once(client: Client, root: Path, sent: list | None = None) -> None:
    """Steps (a) to (c) on a Claude child: refused, still served, answered exactly once.

    The host may push the child's answer rather than show it, so the check reads
    the durable record. ``sent`` counts native writes where the host runs in this process.
    """
    agent, request = pending_request(client, 'claude', 'permission', 'claude/can_use_tool')
    reason = refuse(client, agent, request, {'decision': 'accept'})
    for named in ('claude/can_use_tool', '{"behavior": "allow"}', '{"behavior": "deny"}', 'still pending'):
        assert named in reason
    answered = client.ok('reply', agent=agent, request=request, response={'behavior': 'allow'})
    assert answered['result']['reply_status'] == 'submitted' and 'duplicate' not in answered['result'], answered
    done = client.ok('wait', timeout=WAIT, agent=agent, timeout_seconds=20)
    assert done['result']['state'] == 'standby', done
    [execution] = read_record_at(root, agent)['executions']
    assert len(execution['replies']) == 1, execution['replies']
    assert json.loads(execution['last_message']) == ALLOWED
    if sent is not None:
        assert sent == ['permission-1']


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list:
    """Every native permission answer written to the child, in this process."""
    answers: list[str] = []
    real = ClaudeExecution._reply

    def counted(self: ClaudeExecution, identity: str, response: dict) -> None:
        if identity.startswith('permission'):
            answers.append(identity)
        real(self, identity, response)

    monkeypatch.setattr(ClaudeExecution, '_reply', counted)
    return answers


@pytest.mark.parametrize('kind', ['pi', 'dsh'])
def test_pi_and_dsh_hosts_refuse_a_wrong_form_and_take_the_right_one(
        kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, claude_environment: None, sent: list) -> None:
    """392 step 80: the refusal reaches the model and the Session's agents tool keeps working."""
    with native_host(kind, tmp_path, monkeypatch) as (client, _):
        answer_claude_once(client, tmp_path / 'data', sent)


def test_codex_host_refuses_a_wrong_form_and_takes_the_right_one(
        tmp_path: Path, native_settings: dict, claude_environment: None, sent: list) -> None:
    """A Claude child under a Codex host goes through the same channel and fails the same way."""
    with codex_host({**native_settings, 'runtimes': {'claude': {}}}, tmp_path) as (client, _):
        answer_claude_once(client, tmp_path / 'host', sent)


def test_claude_host_refuses_a_wrong_form_and_takes_the_right_one(
        tmp_path: Path, claude_environment: None) -> None:
    """The Claude host is its own MCP entry: it answered before too, now with the form."""
    with claude_host(tmp_path) as (client, root):
        answer_claude_once(client, root)


class ApprovingDsh(FakeDshService):
    """The controlled DSH service, holding its turn on one native approval until it is answered."""

    def __init__(self, *arguments: object, **options: object) -> None:
        super().__init__(*arguments, **options)
        self.approvals: list[dict] = []
        self.answers: list[tuple] = []

    def rpc(self, method: str, body: dict | None = None) -> dict:
        if method != 'session/prompt':
            return super().rpc(method, body)
        self.calls.append((method, body))
        with self.lock:
            self.running = True
            self.frames.append(self._event('turn/start', {}))
            self.approvals.append({'type': 'waterfall', 'event': 'approval/request', 'eventId': 'native-event-435',
                                   'request': {'toolName': 'Bash', 'callId': 'call-435', 'reason': 'test'}})
        return {'accepted': True}

    def take_events(self) -> list:
        with self.lock:
            taken, self.approvals = self.approvals, []
        return taken

    def answer_approval(self, event_id: str, outcome: str) -> None:
        self.answers.append((event_id, outcome))
        with self.lock:
            self.frames += [self._event('assistant/message', {'message': {
                                'id': 'answer-435', 'role': 'assistant',
                                'content': [{'type': 'text', 'text': outcome}]}}),
                            self._event('turn/end', {'reason': self.end_reason})]


@pytest.fixture
def dsh_child(tmp_path: Path, dsh: dict, monkeypatch: pytest.MonkeyPatch) -> dict:
    """A DSH Runtime entry for the Codex host, with one connection and the approving service."""
    declare(tmp_path / 'host', tmp_path)
    monkeypatch.setattr(dsh_execution.DshExecution, 'service_type', ApprovingDsh)
    return dsh


def test_a_dsh_child_refuses_a_wrong_form_and_takes_the_right_one(
        tmp_path: Path, native_settings: dict, dsh_child: dict) -> None:
    """DSH raises AgentsError natively, so its refusal already kept the channel."""
    with codex_host({**native_settings, 'runtimes': {'dsh': dsh_child}}, tmp_path) as (client, _):
        agent, request = pending_request(client, 'dsh', 'work', 'dsh/approval-request')
        reason = refuse(client, agent, request, {'behavior': 'allow'})
        assert 'allow or reject' in reason
        answered = client.ok('reply', agent=agent, request=request, response={'decision': 'allow'})
        assert answered['result']['reply_status'] == 'submitted'
        done = client.ok('wait', timeout=WAIT, agent=agent, timeout_seconds=20)
        assert done['result']['state'] == 'standby', done
        assert FakeDshService.instances[0].answers == [('native-event-435', 'allowed-once')]


# -- The class: anything unexpected while handling a call ---------------------------------


class Exit(SystemExit):
    """A thread-ending failure that is not an Exception."""


@pytest.mark.parametrize(('failure', 'code', 'named'), [
    (RuntimeError('native wiring broke'), 'operation-failed', 'RuntimeError: native wiring broke'),
    (RuntimeAdapterError('invalid-input', 'kept reason'), 'invalid-input', 'kept reason'),
    (type('Odd', (Exception,), {'code': 7})('no usable code'), 'operation-failed', 'no usable code'),
    (Exit(1), 'operation-failed', 'Exit'),
], ids=['bare', 'adapter-error', 'non-string-code', 'not-an-exception'])
def test_an_unexpected_failure_is_answered_and_the_next_call_served(
        failure: BaseException, code: str, named: str, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """The reply keeps its format, the caller learns the failure and the host keeps the traceback."""
    calls = []

    def call(request: dict) -> AgentsResult:
        calls.append(request)
        if len(calls) == 1:
            raise failure
        return AgentsResult({'result': {'served': True}})

    with channel(tmp_path / 'channel', call, tmp_path) as client:
        document, failed = client.call('status')
        assert failed and document['error']['code'] == code, document
        assert named in document['error']['message']
        assert client.ok('status')['result'] == {'served': True}
    assert 'Traceback' in capsys.readouterr().err


def test_a_result_that_cannot_be_written_is_answered(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """An unserialisable result is a refusal; it leaves nothing that blocks the next call."""
    calls = []

    def call(request: dict) -> AgentsResult:
        calls.append(request)
        return AgentsResult({'result': {'value': object() if len(calls) == 1 else 'fine'}})

    with channel(tmp_path / 'channel', call, tmp_path) as client:
        document, failed = client.call('status')
        assert failed and document['error']['code'] == 'operation-failed', document
        assert 'TypeError' in document['error']['message']
        assert client.ok('status')['result'] == {'value': 'fine'}
    assert 'Traceback' in capsys.readouterr().err


# -- deliver: rejected versus unknown ------------------------------------------------------


def only_turn(driver: ClaudeDriver) -> ClaudeExecution:
    """The driver's one running native owner."""
    [turn] = driver.turns.values()
    return turn


def finish(client: Client, agent: str, request: dict) -> None:
    """Answer the held request, so the child ends within the test."""
    client.ok('reply', agent=agent, request=request, response={'behavior': 'deny'})
    client.ok('wait', timeout=WAIT, agent=agent, timeout_seconds=20)


def test_a_claude_input_refusal_is_rejected_with_its_reason(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, claude_environment: None) -> None:
    """A Runtime refusal is a known non-delivery, as on Pi, Codex and DSH, not an unknown one."""
    with native_host('pi', tmp_path, monkeypatch) as (client, host):
        agent, request = pending_request(client, 'claude', 'permission', 'claude/can_use_tool')
        turn = only_turn(host.driver)
        with monkeypatch.context() as closed:
            closed.setattr(turn, 'accepting', False)
            document, failed = client.call('send', agent=agent, message='late')
        assert failed and document['error']['code'] == 'runtime-input-closed', document
        [receipt] = read_record_at(tmp_path / 'data', agent)['executions'][-1]['inputs']
        assert receipt['delivery'] == 'rejected'
        assert receipt['error'] == document['error']
        finish(client, agent, request)


def test_a_claude_delivery_that_fails_unexpectedly_stays_unknown(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, claude_environment: None) -> None:
    """Only a refusal is rejected: anything else may have reached the Runtime, so it is never resent."""
    with native_host('pi', tmp_path, monkeypatch) as (client, host):
        agent, request = pending_request(client, 'claude', 'permission', 'claude/can_use_tool')
        turn = only_turn(host.driver)
        real = turn.operate

        def broken(native: dict) -> dict:
            if native['operation'] == 'send':
                raise RuntimeError('pipe state unknown')
            return real(native)

        with monkeypatch.context() as patched:
            patched.setattr(turn, 'operate', broken)
            document, failed = client.call('send', agent=agent, message='maybe')
        assert failed and document['result']['delivery']['delivery'] == 'unknown', document
        [receipt] = read_record_at(tmp_path / 'data', agent)['executions'][-1]['inputs']
        assert receipt['error'] == {'code': 'delivery-unknown', 'message': 'pipe state unknown'}
        finish(client, agent, request)


def test_a_dsh_input_refusal_is_rejected_with_its_reason(
        tmp_path: Path, native_settings: dict, dsh_child: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """DSH's own error type is an AgentsError, so its refusal was always rejected."""
    with codex_host({**native_settings, 'runtimes': {'dsh': dsh_child}}, tmp_path) as (client, host):
        agent, request = pending_request(client, 'dsh', 'work', 'dsh/approval-request')
        [turn] = host.control.drivers['dsh'].turns.values()
        with monkeypatch.context() as closed:
            closed.setattr(turn, 'active', False)
            document, failed = client.call('send', agent=agent, message='late')
        assert failed and document['error']['code'] == 'operation-unavailable', document
        [receipt] = read_record_at(tmp_path / 'host', agent)['executions'][-1]['inputs']
        assert receipt['delivery'] == 'rejected'
        client.ok('reply', agent=agent, request=request, response={'decision': 'reject'})
        client.ok('wait', timeout=WAIT, agent=agent, timeout_seconds=20)

