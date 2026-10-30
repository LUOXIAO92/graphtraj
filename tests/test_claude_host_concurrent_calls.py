"""Claude hosts serve several calls at once without changing any call's result (404)."""
from __future__ import annotations

from io import StringIO, TextIOBase
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from agent_swarm import AgentsError, AgentsResult
from conftest import run_process
from graphtraj.execution.approved_recovery import review_proposal
from graphtraj.runtimes.claude.host import NativeCalls, adoption_material
from graphtraj.runtimes.claude.mcp import serve
from test_task_integration import accepted_document  # noqa: F401  (fixture)

try:
    from agent_swarm.calls import Call, CallCancelled, current_call, on_discard, pause, run_stoppable
except ImportError:  # The code before 404: the tests below fail by behaviour, not by import.
    Call = CallCancelled = current_call = on_discard = run_stoppable = None
    pause = time.sleep

# Every wait is bounded, so the serial host fails these tests quickly.
QUICK = 3.0
LONG = 20.0


class Client:
    """A client on OS pipes; it reads the host's messages while it writes."""

    def __init__(self, target, *arguments, **options) -> None:
        host_in, self.requests = (os.fdopen(fd, mode, buffering=1) for fd, mode in zip(os.pipe(), 'rw'))
        self.replies, host_out = (os.fdopen(fd, mode, buffering=1) for fd, mode in zip(os.pipe(), 'rw'))
        self.messages: queue.Queue = queue.Queue()
        self.lines: list[str] = []
        self.host = threading.Thread(target=target, args=(host_in, host_out, *arguments), kwargs=options, daemon=True)
        self.host.start()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.replies:
            self.lines.append(line)
            self.messages.put(json.loads(line))

    def send(self, message: dict) -> None:
        self.requests.write(json.dumps({'jsonrpc': '2.0', **message}) + '\n')

    def call(self, identity: object, feature: str, tool: str = 'tasks', **arguments: object) -> None:
        self.send({'id': identity, 'method': 'tools/call', 'params': {'name': tool, 'arguments': {
            'action': 'execute', 'feature': feature, 'arguments': arguments}}})

    def next(self, timeout: float = QUICK) -> dict:
        try:
            return self.messages.get(timeout=timeout)
        except queue.Empty:
            pytest.fail(f'the host sent nothing within {timeout} s')

    def close(self) -> None:
        self.requests.close()


@pytest.fixture
def clients():
    """Close every client's input, so each host thread ends with its test."""
    opened: list[Client] = []

    def start(*arguments, **options) -> Client:
        opened.append(Client(serve, *arguments, **options))
        return opened[-1]

    yield start
    for client in opened:
        client.close()


def blocked_until(release: threading.Event, started: threading.Event | None = None):
    """Return a native call whose ``wait`` holds until released; others answer at once."""
    def native_call(request: dict, tool: str = 'agents') -> AgentsResult:
        if request['feature'] == 'wait':
            if started is not None:
                started.set()
            release.wait(LONG)
        return AgentsResult({'feature': request['feature']})
    return native_call


def test_short_call_returns_while_a_long_call_runs(clients, tmp_path: Path) -> None:
    """Required result 1: the second call does not wait for the first."""
    release, started = threading.Event(), threading.Event()
    client = clients(tmp_path, native_call=blocked_until(release, started))
    try:
        client.call(1, 'wait')
        assert started.wait(QUICK)
        client.call(2, 'status')
        first = client.next()
        assert first['id'] == 2, first
        assert client.messages.empty()
    finally:
        release.set()
    assert client.next()['id'] == 1


def test_independent_host_uses_the_concurrent_loop(tmp_path: Path) -> None:
    """The independent host's entry serves its calls the same way."""
    from agent_swarm.mcp import respond, result_response, serve_concurrent, tool_documents

    release = threading.Event()
    native = blocked_until(release)

    def call(identity: object, params: dict) -> dict:
        return result_response(identity, {'isError': False, 'structuredContent': native(params['arguments']).document})

    client = Client(serve_concurrent, lambda message: respond(message, tool_documents, call, {'name': 'agents'}))
    try:
        client.call(1, 'wait', tool='agents')
        client.call(2, 'status', tool='agents')
        assert client.next()['id'] == 2
    finally:
        release.set()
    assert client.next()['id'] == 1
    client.close()


def test_cancel_stops_the_wait_at_once_and_sends_no_response(clients, tmp_path: Path) -> None:
    """Required result 2: the wait ends now, nothing answers it and the host keeps serving."""
    started, ended = threading.Event(), threading.Event()

    def native_call(request: dict, tool: str = 'agents') -> AgentsResult:
        if request['feature'] == 'wait':
            started.set()
            try:
                for _ in range(int(LONG / 0.05)):
                    pause(0.05)
            finally:
                ended.set()
        return AgentsResult({'feature': request['feature']})

    client = clients(tmp_path, native_call=native_call)
    client.call(1, 'wait')
    assert started.wait(QUICK)
    client.send({'method': 'notifications/cancelled', 'params': {'requestId': 1, 'reason': 'user'}})
    assert ended.wait(QUICK), 'the wait still runs after its cancellation'
    client.call(2, 'status')
    reply = client.next()
    assert reply['id'] == 2 and reply['result']['structuredContent'] == {'feature': 'status'}
    # A cancelled id can be used again, and nothing ever answered the first one.
    client.send({'id': 3, 'method': 'ping'})
    assert client.next()['id'] == 3
    assert client.messages.empty()


def test_cancelled_call_returns_what_its_result_had_claimed(clients, tmp_path: Path) -> None:
    """A result nobody reads gives its claimed notices back through ``on_discard``."""
    claimed, returned, release = threading.Event(), threading.Event(), threading.Event()

    def native_call(request: dict, tool: str = 'agents') -> AgentsResult:
        on_discard(returned.set)
        claimed.set()
        release.wait(LONG)
        return AgentsResult({'main_notices': ['claimed']})

    client = clients(tmp_path, native_call=native_call)
    client.call(1, 'status')
    assert claimed.wait(QUICK)
    client.send({'method': 'notifications/cancelled', 'params': {'requestId': 1}})
    client.send({'id': 2, 'method': 'ping'})
    assert client.next()['id'] == 2
    release.set()
    assert returned.wait(QUICK)
    assert client.messages.empty()


def test_input_eof_wakes_every_wait_and_the_host_returns(tmp_path: Path) -> None:
    """A client that went away holds nothing: a review and a wait both end."""
    states: list[str] = []

    def native_call(request: dict, tool: str = 'agents') -> AgentsResult:
        try:
            if request['feature'] == 'approved_recovery':
                review_proposal(proposal('eof'), tmp_path, tmp_path)
            else:
                for _ in range(int(LONG / 0.05)):
                    pause(0.05)
        finally:
            states.append(request['feature'])
        return AgentsResult({})

    client = Client(serve, tmp_path, native_call=native_call)
    client.send({'id': 1, 'method': 'initialize', 'params': {'capabilities': {'elicitation': {}}}})
    assert client.next()['id'] == 1
    client.call(2, 'approved_recovery')
    assert client.next()['method'] == 'elicitation/create'
    client.call(3, 'wait')
    client.close()
    client.host.join(QUICK)
    assert not client.host.is_alive() and sorted(states) == ['approved_recovery', 'wait']


def test_call_that_ignores_its_stop_cannot_hold_the_host_past_close(tmp_path: Path, monkeypatch, capfd) -> None:
    """EOF ends serve within its bound, so the host's shutdown still removes its channel file."""
    from agent_swarm import mcp as agents_mcp

    monkeypatch.setattr(agents_mcp, 'CLOSE_SECONDS', 0.2, raising=False)
    release, started = threading.Event(), threading.Event()
    client = Client(serve, tmp_path, native_call=blocked_until(release, started))
    try:
        client.call(1, 'wait')
        assert started.wait(QUICK)
        client.close()
        client.host.join(QUICK)
        assert not client.host.is_alive(), 'serve still waits for the stuck call'
        assert 'agents-call still-running-at-close id=1 tool=tasks feature=wait' in capfd.readouterr().err
    finally:
        release.set()


def test_sigint_does_not_wait_for_a_call_that_ignores_its_stop(tmp_path: Path) -> None:
    """KeyboardInterrupt leaves serve at once, so the host reaches its channel unlink first."""
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    raised: list[float] = []

    def native_call(request: dict, tool: str = 'agents') -> AgentsResult:
        started.set()
        release.wait(LONG)
        finished.set()
        return AgentsResult({})

    class Interrupted(TextIOBase):
        """Send one call; then Claude Code ends the session while it runs."""
        def __init__(self) -> None:
            self.lines = [json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
                'name': 'tasks', 'arguments': {'action': 'execute', 'feature': 'wait', 'arguments': {}}}}) + '\n']

        def readline(self, size: int = -1) -> str:
            if self.lines:
                return self.lines.pop()
            assert started.wait(QUICK)
            raised.append(time.monotonic())
            raise KeyboardInterrupt

    try:
        with pytest.raises(KeyboardInterrupt):
            serve(Interrupted(), StringIO(), tmp_path, native_call=native_call)
        elapsed = time.monotonic() - raised[0]
        assert not finished.is_set(), 'serve only returned after the call ended'
        assert elapsed < 0.5, f'serve took {elapsed:.2f} s to leave after SIGINT'
    finally:
        release.set()


def proposal(alias: str) -> dict:
    """A reviewed budget increment for one Agent."""
    return {'request': {'alias': alias, 'additional_minutes': 15, 'resume': True, 'restore_active': False},
            'before': {'budget': {'approved_minutes': 90}}, 'after': {'budget': {'approved_minutes': 105}},
            'authority': []}


def reviewing(tmp_path: Path):
    """Return a native call whose ``alias`` argument names its reviewed change."""
    def native_call(request: dict, tool: str = 'agents') -> AgentsResult:
        return AgentsResult(review_proposal(proposal(request['arguments']['alias']), tmp_path, tmp_path))
    return native_call


def test_each_review_answer_returns_to_the_call_that_raised_it(clients, tmp_path: Path) -> None:
    """Answered in reverse order, the accept and the decline reach the right calls."""
    client = clients(tmp_path, native_call=reviewing(tmp_path))
    client.send({'id': 1, 'method': 'initialize', 'params': {'capabilities': {'elicitation': {}}}})
    assert client.next()['id'] == 1
    client.call(10, 'approved_recovery', alias='accept-this')
    first = client.next()
    client.call(11, 'approved_recovery', alias='decline-this')
    second = client.next()
    assert {first.get('method'), second.get('method')} == {'elicitation/create'}, (first, second)
    dialogs = {'accept-this' if 'accept-this' in message['params']['message'] else 'decline-this': message['id']
               for message in (first, second)}
    # An answer naming no waiting review decides nothing.
    client.send({'id': 'recovery-unknown', 'result': {'action': 'accept', 'content': {}}})
    client.send({'id': dialogs['decline-this'], 'result': {'action': 'decline', 'content': {}}})
    assert client.next()['id'] == 11
    client.send({'id': dialogs['accept-this'], 'result': {'action': 'accept', 'content': {}}})
    assert client.next()['id'] == 10
    # The first answer already decided; a second one for the same dialog is ignored.
    client.send({'id': dialogs['accept-this'], 'result': {'action': 'decline', 'content': {}}})
    client.send({'id': 2, 'method': 'ping'})
    assert client.next()['id'] == 2


def test_each_review_decision_is_returned_with_its_own_call_result(clients, tmp_path: Path) -> None:
    """The decisions themselves, read from the two call results."""
    client = clients(tmp_path, native_call=reviewing(tmp_path))
    client.send({'id': 1, 'method': 'initialize', 'params': {'capabilities': {'elicitation': {}}}})
    client.next()
    client.call(10, 'approved_recovery', alias='accept-this')
    client.call(11, 'approved_recovery', alias='decline-this')
    dialogs = [client.next(), client.next()]
    assert [dialog.get('method') for dialog in dialogs] == ['elicitation/create'] * 2, dialogs
    for dialog in sorted(dialogs, key=lambda item: 'accept-this' in item['params']['message']):
        client.send({'id': dialog['id'], 'result': {
            'action': 'accept' if 'accept-this' in dialog['params']['message'] else 'decline', 'content': {}}})
    results = {message['id']: message['result']['structuredContent'] for message in (client.next(), client.next())}
    assert results[10] == {'decision': 'accept'}
    assert results[11]['decision'] == 'decline'


def test_cancelled_review_closes_its_dialog_and_decides_nothing(clients, tmp_path: Path) -> None:
    """Cancelling one call closes its dialog; the other review keeps waiting for its answer."""
    client = clients(tmp_path, native_call=reviewing(tmp_path))
    client.send({'id': 1, 'method': 'initialize', 'params': {'capabilities': {'elicitation': {}}}})
    client.next()
    client.call(10, 'approved_recovery', alias='cancel-this')
    first = client.next()
    assert first.get('method') == 'elicitation/create', first
    client.call(11, 'approved_recovery', alias='keep-this')
    kept = client.next()
    assert kept.get('method') == 'elicitation/create', kept
    client.send({'method': 'notifications/cancelled', 'params': {'requestId': 10}})
    closed = client.next()
    assert closed['method'] == 'notifications/cancelled' and closed['params']['requestId'] == first['id']
    # A late accept of the closed dialog applies nothing, and only one call is answered.
    client.send({'id': first['id'], 'result': {'action': 'accept', 'content': {}}})
    client.send({'id': kept['id'], 'result': {'action': 'accept', 'content': {}}})
    reply = client.next()
    assert reply['id'] == 11 and reply['result']['structuredContent'] == {'decision': 'accept'}
    client.send({'id': 2, 'method': 'ping'})
    assert client.next()['id'] == 2


def test_concurrent_large_outputs_stay_whole_lines(clients, tmp_path: Path) -> None:
    """Results larger than a pipe buffer never interleave."""
    size = 300_000

    def native_call(request: dict, tool: str = 'agents') -> AgentsResult:
        return AgentsResult({'blob': request['feature'] * size})

    client = clients(tmp_path, native_call=native_call)
    features = [chr(ord('a') + index) for index in range(8)]
    for index, feature in enumerate(features):
        client.call(index, feature)
    replies = [client.next(LONG) for _ in features]
    assert {reply['id'] for reply in replies} == set(range(len(features)))
    for reply in replies:
        assert reply['result']['structuredContent']['blob'] == features[reply['id']] * size
    assert all(line.endswith('\n') for line in client.lines)


def test_call_log_names_each_call_without_its_arguments(clients, tmp_path: Path, capfd) -> None:
    """The real-host observable: ordered lines with id, tool and feature, and no arguments."""
    client = clients(tmp_path, native_call=blocked_until(threading.Event()))
    client.call(7, 'status', secret='do-not-log-this-value')
    assert client.next()['id'] == 7
    client.close()
    client.host.join(QUICK)
    logged = capfd.readouterr().err
    assert 'agents-call received id=7 tool=tasks feature=status' in logged
    assert 'agents-call finished id=7 tool=tasks feature=status seconds=' in logged
    assert 'outcome=ok' in logged and 'do-not-log-this-value' not in logged


# NativeCalls


def native_calls(tmp_path: Path, invocations: list | None = None) -> NativeCalls:
    """A host whose backend records which Session each request ran as."""
    def bind(session: str, cwd: Path):
        def call(tool: str, request: dict) -> AgentsResult:
            if invocations is not None:
                invocations.append((session, tool, request))
            return AgentsResult({'native': session})
        return call
    return NativeCalls(bind, tmp_path)


def prepared(host: NativeCalls, tmp_path: Path, feature: str, session: str, tool: str = 'agents') -> dict:
    """Prepare one native call as the mod does during Claude's permission check."""
    request = {'action': 'execute', 'feature': feature, 'arguments': {}}
    host.context({'operation': 'prepare', 'tool': tool, 'session': session, 'cwd': str(tmp_path),
                  'agent': None, 'request': request})
    return request


def test_several_associations_are_each_consumed_once(tmp_path: Path) -> None:
    """Parallel calls each match their own exact association, in any order, once."""
    host, session = native_calls(tmp_path), str(uuid4())
    first, second = prepared(host, tmp_path, 'status', session), prepared(host, tmp_path, 'wait', session)
    assert host.call(second).document == {'native': session}
    assert host.call(first).document == {'native': session}
    for request in (first, second):
        with pytest.raises(AgentsError, match='No matching'):
            host.call(request)
    # The same request through the other entry is a different call.
    tasks = prepared(host, tmp_path, 'status', session, tool='tasks')
    with pytest.raises(AgentsError, match='No matching'):
        host.call(tasks, 'agents')
    assert host.call(tasks, 'tasks').document == {'native': session}


def test_repeated_prepare_keeps_one_association_and_identical_calls_refuse(tmp_path: Path) -> None:
    """A repeat never adds a grant: the second identical call is refused and can repeat."""
    host, session = native_calls(tmp_path), str(uuid4())
    request = prepared(host, tmp_path, 'status', session)
    assert prepared(host, tmp_path, 'status', session) == request
    assert host.call(request).document == {'native': session}
    with pytest.raises(AgentsError, match='call it again'):
        host.call(request)
    prepared(host, tmp_path, 'status', session)
    assert host.call(request).document == {'native': session}


def test_another_session_cannot_prepare_or_consume_meanwhile(tmp_path: Path) -> None:
    """An MCP request names no Session, so associations of two Sessions never coexist."""
    host, session, other = native_calls(tmp_path), str(uuid4()), str(uuid4())
    invocations: list = []
    host = native_calls(tmp_path, invocations)
    request = prepared(host, tmp_path, 'status', session)
    with pytest.raises(AgentsError, match='already pending'):
        prepared(host, tmp_path, 'status', other)
    host.call(request)
    assert [item[0] for item in invocations] == [session]
    # Once nothing is prepared, the other Session prepares and runs as itself.
    prepared(host, tmp_path, 'status', other)
    host.call(request)
    assert [item[0] for item in invocations] == [session, other]
    # A subagent never adopts Main, also with other calls in flight.
    prepared(host, tmp_path, 'wait', other)
    with pytest.raises(AgentsError, match='subagent'):
        host.context({'operation': 'prepare', 'tool': 'agents', 'session': other, 'cwd': str(tmp_path),
                      'agent': 'native-child', 'request': request})


def test_end_names_its_own_call_and_a_bare_end_keeps_its_old_meaning(tmp_path: Path) -> None:
    """One call's end leaves the others; a mod adopted earlier still clears everything."""
    host, session = native_calls(tmp_path), str(uuid4())
    kept, ended = prepared(host, tmp_path, 'status', session), prepared(host, tmp_path, 'wait', session)
    host.context({'operation': 'end', 'tool': 'agents', 'session': session, 'request': ended})
    with pytest.raises(AgentsError, match='No matching'):
        host.call(ended)
    # An end naming another Session's or entry's call changes nothing.
    host.context({'operation': 'end', 'tool': 'tasks', 'session': session, 'request': kept})
    host.context({'operation': 'end', 'tool': 'agents', 'session': str(uuid4()), 'request': kept})
    assert host.call(kept).document == {'native': session}
    prepared(host, tmp_path, 'status', session)
    prepared(host, tmp_path, 'wait', session)
    host.context({'operation': 'end'})
    for request in (kept, ended):
        with pytest.raises(AgentsError, match='No matching'):
            host.call(request)
    with pytest.raises(AgentsError, match='per-call end'):
        host.context({'operation': 'end', 'tool': 'agents'})


def test_ended_association_waits_for_its_request_while_its_session_runs(tmp_path: Path) -> None:
    """A call moved to the background keeps its association only beside a running call."""
    release, running = threading.Event(), threading.Event()

    def bind(session: str, cwd: Path):
        def call(tool: str, request: dict) -> AgentsResult:
            if request['feature'] == 'wait':
                running.set()
                release.wait(LONG)
            return AgentsResult({'native': session})
        return call

    host, session = NativeCalls(bind, tmp_path), str(uuid4())
    waiting = prepared(host, tmp_path, 'wait', session)
    worker = threading.Thread(target=host.call, args=(waiting,))
    worker.start()
    assert running.wait(QUICK)
    late = prepared(host, tmp_path, 'status', session)
    host.context({'operation': 'end', 'tool': 'agents', 'session': session, 'request': late})
    assert host.call(late).document == {'native': session}
    # Another Session's preparation drops it.
    gone = prepared(host, tmp_path, 'requests', session)
    host.context({'operation': 'end', 'tool': 'agents', 'session': session, 'request': gone})
    prepared(host, tmp_path, 'status', str(uuid4()))
    release.set()
    worker.join()
    with pytest.raises(AgentsError, match='No matching'):
        host.call(gone)


def test_many_threads_each_run_exactly_once(tmp_path: Path) -> None:
    """Under contention, each prepared call runs once and nothing else does."""
    invocations: list = []
    host, session = native_calls(tmp_path, invocations), str(uuid4())
    requests = [prepared(host, tmp_path, f'feature-{index}', session) for index in range(32)]
    answers: list = []

    def run(request: dict) -> None:
        for _ in range(2):
            try:
                answers.append(host.call(request))
            except AgentsError:
                pass

    threads = [threading.Thread(target=run, args=(request,)) for request in requests]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(answers) == len(invocations) == len(requests)
    assert not host.prepared and not host.running


# The mod


def run_mod(tmp_path: Path, program: str) -> None:
    """Run ``program`` in node against the mod GraphTraj writes, with a recording host."""
    module = tmp_path / 'host_context.mjs'
    root = tmp_path.resolve()
    module.write_text(adoption_material(root, Path('/claude'))[
        str(root / '.claude/skills/graphtraj-claude-host/hooks/host_context.mjs')])
    header = r'''
import assert from 'node:assert/strict';
const {register} = await import(process.argv[1]);
const handlers = new Map();
register((name, matcher, fn) => {handlers.set(fn && matcher.tool ? `${name}:${matcher.tool}` : name, fn ?? matcher); return {catch() {}};});
const operations = [], submitted = [], timers = [];
let pending = [];
const host = {
 session: {id: async () => 'main-session', cwd: async () => '/p'},
 command: {register: async () => {}},
 env: {get: async key => key.endsWith('PYTHON') ? '/venv/python' : '/host/config'},
 process: {run: async (argv, options) => {
   const document = JSON.parse(options.stdin);
   operations.push(document);
   const reply = document.operation === 'notices' ? {notices: pending.splice(0), position: 0} : {};
   return {exitCode: 0, stdout: JSON.stringify(reply), stderr: ''};
 }},
 prompt: {submit: async input => { submitted.push(input.text); }},
 clock: {setTimeout: fn => timers.push(fn)},
 ui: {log: () => {}},
};
const call = name => handlers.get(`tool.call:mcp__agents__${name}`);
const check = name => handlers.get(`tool.check:mcp__agents__${name}`);
const held = () => { let release; const promise = new Promise(done => { release = done; }); return {promise, release}; };
const tick = () => new Promise(done => setTimeout(done, 5));
'''
    result = subprocess.run(['node', '--input-type=module', '-e', header + program, module.as_uri()],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_mod_lets_calls_overlap_and_each_ends_only_itself(tmp_path: Path) -> None:
    """The refusal is gone; prepare stays per call and the end names the same facts."""
    run_mod(tmp_path, r'''
const long = {action: 'execute', feature: 'wait', arguments: {agent: 'a', timeout_seconds: 5}};
const short = {action: 'describe', feature: 'status', schema: true};
const gate = held();
const running = call('agents')(host, {tool: 'mcp__agents__agents', ...long}, async () => {
  await check('agents')(host, {input: long}, async () => ({decision: 'allow'}));
  await gate.promise;
  return {result: '{}'};
});
await tick();
const second = await call('agents')(host, {tool: 'mcp__agents__agents', ...short}, async () => {
  await check('agents')(host, {input: short}, async () => ({decision: 'allow'}));
  return {result: '{}'};
});
assert.ok(!second.deny, 'the overlapping call was refused');
assert.deepEqual(operations, [
  {operation: 'prepare', tool: 'agents', session: 'main-session', cwd: '/p', agent: null, request: long},
  {operation: 'prepare', tool: 'agents', session: 'main-session', cwd: '/p', agent: null, request: short},
  {operation: 'end', tool: 'agents', request: short, session: 'main-session'},
]);
gate.release();
await running;
assert.deepEqual(operations.at(-1), {operation: 'end', tool: 'agents', request: long, session: 'main-session'});
''')


def test_mod_pushes_once_only_after_the_last_running_call(tmp_path: Path) -> None:
    """Notices wait for every running call to end; the single push holds."""
    run_mod(tmp_path, r'''
await handlers.get('session.start')(host, {}, async () => 'started');
const notice = {at: 1, id: 'e1:completed', event: {alias: 'leader@l1', event: 'completed', message: 'done'}};
const gates = [held(), held()];
const request = {action: 'execute', feature: 'status', arguments: {}};
const running = gates.map(gate => call('agents')(host, {tool: 'mcp__agents__agents', ...request}, async () => {
  await gate.promise; return {result: '{}'};
}));
await tick();
pending.push(notice);
// The timer does not read notices while a call runs.
await timers.shift()();
assert.equal(operations.filter(item => item.operation === 'notices').length, 0);
gates[0].release();
await running[0];
await tick();
assert.equal(operations.filter(item => item.operation === 'notices').length, 0, 'pushed while a call runs');
gates[1].release();
await running[1];
await tick();
assert.equal(operations.filter(item => item.operation === 'notices').length, 1);
assert.equal(submitted.length, 1);
assert.ok(submitted[0].includes('done'));
''')


# What a concurrent call can reach


def test_real_waits_stop_at_once(tmp_path: Path, monkeypatch) -> None:
    """``agents wait`` on a Task member stops polling, and its parent gets the end notice again."""
    from graphtraj.execution import runner_control, runner_status
    from graphtraj.interfaces.agents import GraphTrajAgents
    from graphtraj.workspace import runner_project

    call, cleared = Call(), []
    directory = tmp_path / 'session'
    directory.mkdir()
    monkeypatch.setattr(runner_project, 'discover_runner_directory', lambda root: tmp_path)
    monkeypatch.setattr(runner_status, 'read_alias_mapping', lambda runner, agent: ({'execution_id': 'e'}, directory))
    monkeypatch.setattr(runner_status, 'status_aliases', lambda agents, root: type('R', (), {
        'document': {'aliases': [{'activity': 'running'}]}, 'succeeded': True})())
    monkeypatch.setattr(runner_control, 'pending_requests', lambda agent, root: {})
    monkeypatch.setattr(runner_control, 'mark_awaited', lambda path, execution, until: cleared.append((execution, until)))
    agents = GraphTrajAgents.__new__(GraphTrajAgents)
    agents.root = tmp_path
    threading.Timer(0.05, call.stop.set).start()
    started = time.monotonic()
    with current_call(call), pytest.raises(CallCancelled):
        agents._wait('member', LONG)
    assert time.monotonic() - started < QUICK
    assert cleared[-1] == (None, 0)


def test_stopped_command_ends_with_its_whole_group(tmp_path: Path) -> None:
    """A long validation does not outlive its call; without a call it just runs."""
    child = tmp_path / 'child.pid'
    program = ("import os, subprocess, sys, time; p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
               f"open({str(child)!r}, 'w').write(str(p.pid)); time.sleep(60)")
    call = Call()
    outcome: list = []

    def run() -> None:
        with current_call(call):
            try:
                run_stoppable([sys.executable, '-c', program])
            except CallCancelled as error:
                outcome.append(error)

    worker = threading.Thread(target=run)
    worker.start()
    for _ in range(200):
        if child.exists() and child.read_text():
            break
        time.sleep(0.05)
    call.stop.set()
    worker.join(QUICK * 2)
    assert not worker.is_alive() and outcome
    pid = int(child.read_text())
    for _ in range(100):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        os.kill(pid, signal.SIGKILL)
        pytest.fail('the command group survived')
    assert run_stoppable([sys.executable, '-c', 'raise SystemExit(3)']).returncode == 3


def test_cancelled_validation_records_no_result_and_the_same_call_continues(
    accepted_document: tuple, monkeypatch, tmp_path: Path,  # noqa: F811
) -> None:
    """The merge finishes; a stopped validation is no failure and a repeat integrates."""
    from graphtraj.execution.runner_status import runtime_caller
    from graphtraj.graph.delivery_worldline import read_worldline
    from graphtraj.interfaces.gateway import handle_request as handle_task

    root, worktrees, _, candidate, environment = accepted_document
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(root)
    marker = tmp_path / 'validating'
    slow = [sys.executable, '-c', f"import pathlib, time; pathlib.Path({str(marker)!r}).touch(); time.sleep(60)"]
    call, outcome = Call(), []

    def integrate() -> None:
        with current_call(call), runtime_caller(root / '.graphtraj/runner', None):
            try:
                outcome.append(handle_task({'action': 'execute', 'feature': 'task_integrate', 'arguments': {
                    'task_id': '83', 'validation_command': slow}}, cwd=root))
            except CallCancelled as error:
                outcome.append(error)

    worker = threading.Thread(target=integrate)
    worker.start()
    for _ in range(600):
        if marker.exists():
            break
        time.sleep(0.05)
    assert marker.exists()
    call.stop.set()
    worker.join(QUICK * 2)
    assert not worker.is_alive()
    events = [event['event'] for event in read_worldline(root / '.graphtraj/state', root)
              if event.get('task_id') == '83' and event['event'].startswith('task-integration')]
    assert events == ['task-integration-started']
    task = yaml.safe_load((root / '.graphtraj/state/tasks/83-integration/task.yml').read_text())
    assert task['status'] == 'integrating'
    dev = worktrees / 'dev'
    assert run_process(['git', 'status', '--porcelain'], cwd=dev).stdout == ''
    assert run_process(['git', 'merge-base', '--is-ancestor', candidate, 'HEAD'], cwd=dev).returncode == 0
    with runtime_caller(root / '.graphtraj/runner', None):
        again = handle_task({'action': 'execute', 'feature': 'task_integrate', 'arguments': {
            'task_id': '83', 'validation_command': [sys.executable, '-c', 'pass']}}, cwd=root)
    assert again.document['status'] == 'integrated', again.document


def test_cancelled_main_call_does_not_lose_its_notices(tmp_path: Path) -> None:
    """A cancelled Main call claims nothing, and a discarded result gives its claim back."""
    from graphtraj.configuration.project_configuration import runner_directory
    from graphtraj.execution.main_continuity import claim_notices, queue_notice
    from graphtraj.runtimes.claude.host import main_calls

    root, session = tmp_path / 'project', str(uuid4())
    (root / '.graphtraj').mkdir(parents=True)
    runner = runner_directory(root)
    connection = {'runtime': 'claude', 'session': session}
    queue_notice(runner, connection, {'id': 'n1', 'execution': 'e1', 'event': 'completed'})
    run = main_calls(root, lambda *a, **k: None, None)(session, root)
    request = {'action': 'discover'}

    stopped = Call()
    stopped.stop.set()
    with current_call(stopped):
        assert 'main_notices' not in run('tasks', request).document

    delivered = Call()
    with current_call(delivered):
        result = run('tasks', request).document
    assert [notice['id'] for notice in result['main_notices']] == ['n1']
    assert claim_notices(runner, 'claude', session) == []
    for discard in delivered.discards:
        discard()
    assert [notice['id'] for notice in claim_notices(runner, 'claude', session)] == ['n1']


def test_independent_host_restores_a_discarded_results_notices(tmp_path: Path) -> None:
    """Its in-memory queue and seen ends return when the result is never read."""
    from agent_swarm.claude.host import IndependentCalls

    calls = IndependentCalls.__new__(IndependentCalls)
    calls.queue, calls.claimed, calls.ended, calls.lock = {}, {}, {'s': {'e1', 'e2'}}, threading.Lock()
    notice = {'id': 'n1', 'event': {'execution': 'e1', 'event': 'completed'}}
    calls.restore('s', [notice], ['e1'])
    assert calls.ended['s'] == {'e2'} and calls.claim('s') == [notice]


def test_retirement_refused_when_its_session_changed_during_review(tmp_path: Path, monkeypatch) -> None:
    """The reviewed mapping must still be current when the retirement applies."""
    from types import SimpleNamespace

    from graphtraj.execution import approved_recovery, runner_retirement, runner_status
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.runtimes.runtime_adapter import recovery_review
    from test_native_replacement import _record_direct_session

    runner = tmp_path / 'runner'
    parent, child = '404-task-handover0-team_leader@leader', '404-task-handover0-engineer@child'
    for alias, role, owner in ((parent, 'team-leader', None), (child, 'engineer', parent)):
        _record_direct_session(runner, alias, role, owner)
        (runner / 'sessions' / alias / 'session.yml').write_text('{}\n')
        (runner / 'sessions' / alias / 'execution.yml').write_text('outcome: completed\n')
    monkeypatch.setattr(runner_retirement, 'discover_project', lambda *a, **k: SimpleNamespace(runner_directory=runner))
    monkeypatch.setattr(runner_retirement, 'caller_alias', lambda directory: child)
    monkeypatch.setattr(approved_recovery, 'caller_alias', lambda directory: child)
    monkeypatch.setattr(runner_status, 'session_operation', lambda *a: {'activity': 'idle'})
    applied: list = []
    monkeypatch.setattr(runner_retirement, 'retire_stopped_session', lambda project, alias: applied.append(alias))

    def change_then_accept(proposal: dict) -> dict:
        """Another call changes the Session while the dialog is open."""
        path = runner / 'sessions' / parent / 'mapping.yml'
        path.write_text(yaml.safe_dump({**yaml.safe_load(path.read_text()), 'execution_id': 'changed-execution'}))
        return {'decision': 'accept'}

    with recovery_review(change_then_accept), pytest.raises(RunnerError, match='changed during its review') as refused:
        runner_retirement.retire_session(parent, tmp_path)
    assert refused.value.code == 'retirement-stale' and applied == []
    with recovery_review(lambda proposal: {'decision': 'accept'}):
        runner_retirement.retire_session(parent, tmp_path)
    assert applied == [parent]
