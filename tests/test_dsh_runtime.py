"""DSH native lifecycle through the selected Runtime and public CLI boundaries."""

from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import io
from typing import Any

import pytest
import yaml

from graphtraj.configuration.project_roles import RolePreset
from graphtraj.configuration.role_definitions import ResolvedChildRole
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError, select_runtime_adapter


def request(tmp_path: Path) -> dict:
    """Provide nonsecret native launch inputs to the public Runtime contract."""
    return {
        'executable': 'dsh', 'package': '/installed/dsh/package.json', 'tool': 'graphtraj-tool',
        'worktree_path': str(tmp_path), 'harness_root': str(tmp_path),
        'provider': 'deepseek-official', 'model': 'deepseek-flash',
        'reasoning_effort': 'low', 'api_key_env': 'DSH_TEST_KEY',
        'base_url': 'https://api.deepseek.com/anthropic', 'sandbox': 'workspace-write',
        'instructions': 'Assigned responsibility', 'reports': ['.state/report.md'],
    }


class NativePeer:
    """Controlled native service, including cancel ACK before actual quiescence."""

    instances = []

    def __init__(self, executable: str, cwd: Path, environment: dict) -> None:
        """Start with independent per-service state and a raw native record."""
        self.process = type('Process', (), {'pid': os.getpid()})()
        self.calls = []
        self.frames = []
        self.running = False
        self.inbox = {'next-turn': [], 'next-step': []}
        self.cancelled = threading.Event()
        self.release_cancel = threading.Event()
        self.reason = 'completed'
        self.closed = False
        self.session = 'native-dsh'
        self.event_data = {}
        self.event_frames = []
        self.event_lock = threading.Lock()
        self.answers = []
        home = Path(environment['DSH_HOME'])
        config = yaml.safe_load((home / 'profiles/web/cordis.patch.yml').read_text())
        root = next(row['config']['root'] for row in config if row.get('id') == 'session-persistence-jsonl')
        log = Path(root) / 'workspace' / self.session / 'v4.jsonl'
        log.parent.mkdir(parents=True)
        log.write_text('{"type":"session/header","data":{"id":"native-dsh"}}\n')
        self.instances.append(self)

    def start(self) -> None:
        """The fixture service is ready without invoking a model."""

    def follow(self, session: str) -> dict:
        """Observe this exact session before input."""
        self.calls.append(('follow', session))
        return {'type': 'snapshot'}

    def open_events(self) -> str:
        """Bind the forwarded approval channel before any native work starts."""
        self.calls.append(('open_events', None))
        return 'native-client'

    def take_events(self) -> list:
        """Deliver approval-channel frames the test scheduled."""
        with self.event_lock:
            frames, self.event_frames = self.event_frames, []
        return frames

    def answer_approval(self, event_id: str, outcome: str) -> None:
        """Record the exact one-shot native outcome returned to the request."""
        self.calls.append(('answer_approval', event_id, outcome))
        self.answers.append((event_id, outcome))

    def push_approval(self, event_id: str, **request: Any) -> None:
        """Schedule one native approval waterfall for the runtime to pick up."""
        with self.event_lock:
            self.event_frames.append({'type': 'waterfall', 'event': 'approval/request',
                                      'eventId': event_id, 'agentId': 'native-agent', 'request': request})

    def push_cancel(self, event_id: str) -> None:
        """Withdraw one native approval before the parent answers it."""
        with self.event_lock:
            self.event_frames.append({'type': 'cancel', 'eventId': event_id})

    def rpc(self, method: str, body: dict | None = None) -> dict:
        """Respond using native receipts, inbox and running-state shapes."""
        self.calls.append((method, body))
        if method == 'session/create':
            return {'sessionId': body.get('sessionId', self.session)}
        if method == 'session/projections':
            return {'values': {'inbox': self.inbox}}
        if method == 'session/list':
            if self.cancelled.is_set() and self.release_cancel.is_set():
                self.running = False
            return {'items': [{'sessionId': self.session, 'running': self.running}]}
        if method == 'session/prompt':
            self.running = True
        if method == 'session/updateQueue':
            for key in self.inbox:
                self.inbox[key] = [value for value in self.inbox[key] if value['id'] != body['itemId']]
        if method == 'session/cancel':
            assert not any(self.inbox.values())
            self.cancelled.set()
        return {'accepted': True}

    def receive(self, timeout: float = 1) -> dict:
        """Deliver explicitly scheduled native events, never promote prompt receipts."""
        time.sleep(0.005)
        if self.frames:
            kind = self.frames.pop(0)
            if kind == 'turn/end':
                self.running = False
            return {'type': 'event', 'event': {'type': kind, 'data': {
                **self.event_data,
                'reason': {'kind': self.reason},
                'message': {'content': [{'type': 'text', 'text': 'Native response'}]},
            }}}
        return {}

    def close(self) -> None:
        """Only this native service is closed."""
        self.closed = True


@pytest.fixture
def peer(monkeypatch: pytest.MonkeyPatch) -> list:
    """Replace only the native service and unrelated host-channel creation."""
    from graphtraj.runtimes.dsh import execution
    from graphtraj.interfaces import hosted_cli

    NativePeer.instances = []
    monkeypatch.setattr(execution, 'DshService', NativePeer)
    monkeypatch.setattr(hosted_cli, 'cli_connection', lambda *args, **kwargs: nullcontext('/bound-channel'))
    return NativePeer.instances


def run_turn(tmp_path: Path, *, expected: str | None = None, trace_file: Path | None = None) -> tuple:
    """Run the public RuntimeTurn asynchronously so controls overlap active work."""
    bindings = []
    turn = select_runtime_adapter('dsh').managed_execution(
        request(tmp_path), 'Original instruction', tmp_path,
        lambda session, pid: bindings.append(('started', session)), {},
        trace_file=trace_file or tmp_path / 'trace.jsonl', expected_session=expected,
        session_created=lambda session, pid: bindings.append(('created', session)),
    )
    outcome = {}

    def execute() -> None:
        """Retain the public result or exact adapter failure."""
        try:
            outcome['result'] = turn.run()
        except Exception as error:
            outcome['error'] = error

    thread = threading.Thread(target=execute)
    thread.start()
    deadline = time.monotonic() + 3
    while len(bindings) < 2 and time.monotonic() < deadline and thread.is_alive():
        time.sleep(0.005)
    assert bindings == [('created', expected or 'native-dsh'), ('started', expected or 'native-dsh')]
    return turn, thread, outcome


def turn_identity(turn: Any) -> dict:
    """Return the exact Session/execution pair the public controls must carry."""
    return {'session': turn.session, 'execution_id': turn.execution_id}


def wait_for_request(turn: Any, timeout: float = 3) -> dict:
    """Poll the public requests operation until the native request is published."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pending = turn.operate({**turn_identity(turn), 'operation': 'requests'})['requests']
        if pending:
            return pending[0]
        time.sleep(0.01)
    raise AssertionError('The native approval request never became public.')


@pytest.fixture
def notices(monkeypatch: pytest.MonkeyPatch) -> list:
    """Retain the direct-parent notices without a real Runner mapping."""
    from graphtraj.execution import runner_control

    recorded = []

    def notify(directory: Path, notice: str, identity: dict | None = None, **kwargs: Any) -> dict:
        """Record the existing channel call and claim acknowledgement."""
        recorded.append({'directory': directory, 'notice': notice, 'identity': identity})
        return {'delivery': 'received', 'parent': 'parent@x1',
                'parent_session': 'parent-session', 'parent_execution_id': 'parent-exec'}

    monkeypatch.setattr(runner_control, 'notify_direct_parent', notify)
    return recorded


def test_receipt_active_input_and_native_completion(tmp_path: Path, peer: list) -> None:
    """A prompt ACK stays running; active input targets the same native Session."""
    turn, thread, outcome = run_turn(tmp_path, expected='native-dsh')
    assert thread.is_alive() and not outcome
    identity = {'session': turn.session, 'execution_id': turn.execution_id}
    turn.operate({**identity, 'operation': 'send', 'instruction': 'Remember followup'})
    prompts = [body for method, body in peer[0].calls if method == 'session/prompt']
    assert [body['mode'] for body in prompts] == ['queue', 'steer']
    assert {body['sessionId'] for body in prompts} == {'native-dsh'}
    with pytest.raises(RuntimeAdapterError):
        turn.operate({**identity, 'session': 'other', 'operation': 'send', 'instruction': 'wrong'})
    peer[0].frames.extend(['assistant/message', 'turn/end'])
    thread.join(3)
    assert outcome['result']['outcome'] == 'completed'
    assert outcome['result']['last_agent_message'] == 'Native response'
    assert peer[0].closed and (tmp_path / 'trace.jsonl').is_symlink()


def test_cancel_drains_both_queues_and_waits_for_native_stop(tmp_path: Path, peer: list) -> None:
    """Cancellation cannot acknowledge stopped until the native Agent is idle."""
    turn, thread, outcome = run_turn(tmp_path)
    service = peer[0]
    service.inbox = {'next-turn': [{'id': 'queued'}], 'next-step': [{'id': 'steered'}]}
    stop = {}

    def interrupt() -> None:
        """Capture the public control return separately from run's terminal result."""
        stop['result'] = turn.operate({'session': turn.session, 'execution_id': turn.execution_id,
                                      'operation': 'interrupt'})

    control = threading.Thread(target=interrupt)
    control.start()
    assert service.cancelled.wait(3)
    assert control.is_alive() and thread.is_alive() and not stop
    with pytest.raises(RuntimeAdapterError):
        turn.operate({'session': turn.session, 'execution_id': turn.execution_id,
                      'operation': 'send', 'instruction': 'Must not restart'})
    service.release_cancel.set()
    thread.join(3)
    control.join(3)
    assert outcome['result']['outcome'] == 'interrupted'
    assert stop == {'result': {}} and service.closed


@pytest.mark.parametrize('reason', ['error', 'cancelled'])
def test_native_error_is_not_success(reason: str, tmp_path: Path, peer: list) -> None:
    """Native turn/end reason wins over transport receipts and client exit codes."""
    turn, thread, outcome = run_turn(tmp_path)
    peer[0].reason = reason
    peer[0].frames.append('turn/end')
    thread.join(3)
    assert outcome['error'].code == 'RUNTIME_EXECUTION_FAILED'
    assert peer[0].closed


def test_non_approval_user_question_fails_explicitly_and_stops(tmp_path: Path, peer: list) -> None:
    """Unsupported non-approval interaction is never discarded as completion."""
    turn, thread, outcome = run_turn(tmp_path)
    peer[0].event_data = {'name': 'ask_user_question'}
    peer[0].frames.append('tool/call')
    peer[0].release_cancel.set()
    thread.join(3)
    assert outcome['error'].code == 'RUNTIME_REQUEST_UNHANDLED'
    assert peer[0].cancelled.is_set() and peer[0].closed


def test_approval_audit_event_is_not_terminal(tmp_path: Path, peer: list) -> None:
    """approval/asked is log-only; the turn keeps waiting for the real decision."""
    turn, thread, outcome = run_turn(tmp_path)
    peer[0].frames.append('approval/asked')
    time.sleep(0.05)
    assert thread.is_alive() and not outcome
    peer[0].frames.append('turn/end')
    thread.join(3)
    assert outcome['result']['outcome'] == 'completed'


def test_native_approval_waits_for_the_direct_parent_reply(
    tmp_path: Path, peer: list, notices: list,
) -> None:
    """The live request reaches the parent, and one explicit allow answers it once."""
    turn, thread, outcome = run_turn(tmp_path)
    peer[0].push_approval('native-event-1', toolName='bash', callId='call-9', reason='git add',
                          displayReason={'en': 'Allow this operation with workspace-write permissions: git add'})
    request = wait_for_request(turn)

    assert thread.is_alive() and not outcome
    assert request['session'] == turn.session and request['execution_id'] == turn.execution_id
    assert request['request_id'] == 'native-event-1' and request['request_token']
    assert (request['tool'], request['call_id'], request['reason']) == ('bash', 'call-9', 'git add')
    # The native frame carries no command/args, so the localized reason is the
    # widest safe action context the parent can review.
    assert request['display_reason'] == {'en': 'Allow this operation with workspace-write permissions: git add'}
    assert len(notices) == 1 and notices[0]['identity']['request_token'] == request['request_token']
    assert 'neither approves nor rejects it' in notices[0]['notice']

    receipt = turn.operate({**turn_identity(turn), 'operation': 'reply',
                            'request_token': request['request_token'], 'response': {'decision': 'allow'}})
    assert receipt == {'request_id': 'native-event-1', 'reply_status': 'submitted'}
    assert peer[0].answers == [('native-event-1', 'allowed-once')]
    assert turn.operate({**turn_identity(turn), 'operation': 'requests'})['requests'] == []

    with pytest.raises(RuntimeAdapterError) as duplicate:
        turn.operate({**turn_identity(turn), 'operation': 'reply',
                      'request_token': request['request_token'], 'response': {'decision': 'allow'}})
    assert duplicate.value.code == 'invalid-input' and peer[0].answers == [('native-event-1', 'allowed-once')]

    peer[0].frames.append('turn/end')
    thread.join(3)
    assert outcome['result']['outcome'] == 'completed'


def test_native_rejection_never_grants_the_action(tmp_path: Path, peer: list, notices: list) -> None:
    """An explicit reject returns the native refusal and runs no approved answer."""
    turn, thread, outcome = run_turn(tmp_path)
    peer[0].push_approval('native-event-2', toolName='bash')
    request = wait_for_request(turn)
    receipt = turn.operate({**turn_identity(turn), 'operation': 'reply',
                            'request_token': request['request_token'], 'response': {'decision': 'reject'}})
    assert receipt['reply_status'] == 'submitted'
    assert peer[0].answers == [('native-event-2', 'rejected')]
    peer[0].frames.append('turn/end')
    thread.join(3)
    assert outcome['result']['outcome'] == 'completed'


def test_wrong_identity_stale_and_malformed_replies_authorize_nothing(
    tmp_path: Path, peer: list, notices: list,
) -> None:
    """Only the exactly owned request token with one explicit decision can answer."""
    turn, thread, outcome = run_turn(tmp_path)
    peer[0].push_approval('native-event-3', toolName='bash')
    request = wait_for_request(turn)
    reply = {'operation': 'reply', 'request_token': request['request_token'],
             'response': {'decision': 'allow'}}
    for wrong in ({'session': 'other'}, {'execution_id': 'other'}):
        with pytest.raises(RuntimeAdapterError) as error:
            turn.operate({**turn_identity(turn), **wrong, **reply})
        assert error.value.code == 'operation-failed'
    with pytest.raises(RuntimeAdapterError) as stale:
        turn.operate({**turn_identity(turn), **{**reply, 'request_token': 'stale-token'}})
    assert stale.value.code == 'invalid-input'
    for response in ({'decision': 'maybe'}, {'allow': True}, {'decision': 'allow', 'extra': 1}):
        with pytest.raises(RuntimeAdapterError) as malformed:
            turn.operate({**turn_identity(turn), **{**reply, 'response': response}})
        assert malformed.value.code == 'invalid-input'
    assert peer[0].answers == []
    assert turn.operate({**turn_identity(turn), 'operation': 'requests'})['requests'] != []
    peer[0].release_cancel.set()
    turn.terminate()
    thread.join(3)


def test_interrupt_clears_the_pending_approval(tmp_path: Path, peer: list, notices: list) -> None:
    """Stopping the native work leaves no hidden request for a later consent."""
    turn, thread, outcome = run_turn(tmp_path)
    peer[0].push_approval('native-event-4', toolName='bash')
    request = wait_for_request(turn)
    peer[0].release_cancel.set()
    assert turn.operate({**turn_identity(turn), 'operation': 'interrupt'}) == {}
    assert outcome['result']['outcome'] == 'interrupted'
    assert turn.operate({**turn_identity(turn), 'operation': 'requests'})['requests'] == []
    with pytest.raises(RuntimeAdapterError) as late:
        turn.operate({**turn_identity(turn), 'operation': 'reply',
                      'request_token': request['request_token'], 'response': {'decision': 'allow'}})
    assert late.value.code == 'invalid-input' and peer[0].answers == []


def test_native_withdrawal_discards_a_late_reply(tmp_path: Path, peer: list, notices: list) -> None:
    """A withdrawn native request cannot be authorized by a later reply."""
    turn, thread, outcome = run_turn(tmp_path)
    peer[0].push_approval('native-event-5', toolName='bash')
    request = wait_for_request(turn)
    peer[0].push_cancel('native-event-5')
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and turn.operate(
        {**turn_identity(turn), 'operation': 'requests'}
    )['requests']:
        time.sleep(0.01)
    with pytest.raises(RuntimeAdapterError) as late:
        turn.operate({**turn_identity(turn), 'operation': 'reply',
                      'request_token': request['request_token'], 'response': {'decision': 'allow'}})
    assert late.value.code == 'invalid-input' and peer[0].answers == []
    peer[0].frames.append('turn/end')
    thread.join(3)
    assert outcome['result']['outcome'] == 'completed'


def test_lost_host_connection_is_failure_and_reaps_owned_service(
    tmp_path: Path, peer: list, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lost event channel cannot become completion or leave its model running."""
    turn, thread, outcome = run_turn(tmp_path)

    def disconnected(timeout: float = 1) -> dict:
        """Inject the native transport's explicit connection-closed failure."""
        raise RuntimeAdapterError('RUNTIME_CONNECTION_CLOSED', 'DSH Session connection failed.')

    monkeypatch.setattr(peer[0], 'receive', disconnected)
    thread.join(3)
    assert outcome['error'].code == 'RUNTIME_CONNECTION_CLOSED'
    assert 'result' not in outcome and peer[0].closed
    assert (tmp_path / 'trace.jsonl').is_file()


def test_two_owned_services_stop_independently(tmp_path: Path, peer: list) -> None:
    """Stopping one Agent cannot stop a second service or finish its work."""
    left = tmp_path / 'left'
    right = tmp_path / 'right'
    left.mkdir()
    right.mkdir()
    a, at, ar = run_turn(left)
    b, bt, br = run_turn(right)
    peer[0].release_cancel.set()
    a.terminate()
    at.join(3)
    assert ar['result']['outcome'] == 'interrupted'
    assert bt.is_alive() and not peer[1].closed and not br
    peer[1].frames.append('turn/end')
    bt.join(3)
    assert br['result']['outcome'] == 'completed'


def test_native_trace_survives_control_directory_retirement(tmp_path: Path, peer: list) -> None:
    """Runner may move control records without losing the immutable native history."""
    control = tmp_path / 'control'
    control.mkdir()
    trace = tmp_path / 'traces' / 'events.jsonl'
    turn, thread, outcome = run_turn(control, trace_file=trace)
    peer[0].frames.append('turn/end')
    thread.join(3)
    assert outcome['result']['outcome'] == 'completed'
    content = trace.read_bytes()
    control.rename(tmp_path / 'retired')
    assert trace.read_bytes() == content


def test_public_json_cli_uses_host_identity_and_report_checks(tmp_path: Path) -> None:
    """The native tool's public CLI cannot impersonate another Session via arguments/env."""
    from graphtraj.execution.runner_heartbeat import hold_ownership
    from graphtraj.interfaces.hosted_cli import cli_connection, CONNECTION_ENV
    from graphtraj.runtimes.codex.managed_session import native_operation_features
    from test_result_submission import result_project
    from test_hosted_cli import own_process

    runner, _, _ = result_project(tmp_path)
    directory = own_process(runner)
    with hold_ownership(directory, os.getpid()), cli_connection(
        tmp_path, 'research@x1', native_operation_features(),
    ) as address:
        result = subprocess.run(
            [sys.executable, '-c', 'from graphtraj.interfaces.local_tool import main; main()'],
            cwd=tmp_path, env={**os.environ, CONNECTION_ENV: address,
                              'GRAPHTRAJ_CALLER_ALIAS': 'research@x2',
                              'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')},
            input=json.dumps({'action': 'execute', 'feature': 'session_reports',
                              'arguments': {'alias': 'research@x2'}}) + '\n',
            text=True, capture_output=True, timeout=20,
        )
    assert result.returncode == 0
    document = json.loads(result.stdout)
    assert document['failed']
    assert document.get('error') and 'reports' not in document


def test_dsh_own_channel_is_projected_inside_the_session_worktree(
    tmp_path: Path, peer: list, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Session's own public CLI channel lives inside its sandboxed Worktree."""
    from graphtraj.interfaces import hosted_cli

    channels = []

    def record(root: Path, alias: str, features: Any, *args: Any, **kwargs: Any):
        """Capture the requested channel directory without opening a real host."""
        channels.append({'root': root, 'directory': kwargs.get('directory')})
        return nullcontext('/bound-channel')

    monkeypatch.setattr(hosted_cli, 'cli_connection', record)
    turn, thread, outcome = run_turn(tmp_path)
    peer[0].frames.append('turn/end')
    thread.join(3)
    assert outcome['result']['outcome'] == 'completed'
    worktree = Path(request(tmp_path)['worktree_path'])
    assert channels == [{'root': tmp_path, 'directory': worktree / '.scratch'}]
    assert channels[0]['directory'].is_relative_to(worktree)


def test_native_remote_envelopes_and_authentication_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The installed Remote's list argument differs from Session mutation arguments."""
    from graphtraj.runtimes.dsh.service import DshService
    import urllib.request
    import urllib.error

    service = DshService('dsh', tmp_path, {})
    service.origin = 'http://127.0.0.1:1'
    service.cookie = 'test-cookie=not-a-real-credential'
    fail = False

    class Remote:
        """Validate generated native HTTP envelopes at the transport boundary."""

        def open(self, call: Any, timeout: float) -> io.StringIO:
            """Return a native result only for an authenticated valid argument shape."""
            if fail:
                raise urllib.error.HTTPError(call.full_url, 401, 'Unauthorized', {}, None)
            assert call.get_header('Cookie') == service.cookie
            assert call.get_header('Origin') == service.origin
            body = json.loads(call.data)
            key = '_request' if body['method'] == 'session/list' else 'request'
            assert body['payload']['args'] == {key: {}}
            return io.StringIO(json.dumps({'rpcId': body['rpcId'], 'result': {'ok': True, 'value': {'accepted': True}}}))

    monkeypatch.setattr(urllib.request, 'build_opener', lambda *args: Remote())
    assert service.rpc('session/list', {}) == {'accepted': True}
    assert service.rpc('session/create', {}) == {'accepted': True}
    fail = True
    with pytest.raises(RuntimeAdapterError) as rejected:
        service.rpc('session/list', {})
    assert rejected.value.code == 'RUNTIME_CONNECTION_FAILED'
    assert service.cookie not in str(rejected.value)


def test_approval_result_uses_raw_event_arguments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The one-shot outcome must travel as the exact $events/result args object."""
    from graphtraj.runtimes.dsh.service import DshService
    import urllib.request

    service = DshService('dsh', tmp_path, {})
    service.origin = 'http://127.0.0.1:1'
    service.cookie = 'test-cookie=not-a-real-credential'
    service.client_id = 'native-client'
    seen = {}

    class Remote:
        """Capture the native result envelope without returning credential text."""

        def open(self, call: Any, timeout: float) -> io.StringIO:
            body = json.loads(call.data)
            seen.update(body)
            return io.StringIO(json.dumps({'rpcId': body['rpcId'], 'result': {'ok': True, 'value': {}}}))

    monkeypatch.setattr(urllib.request, 'build_opener', lambda *args: Remote())
    service.answer_approval('native-event-1', 'allowed-once')
    assert seen['method'] == '$events/result'
    assert seen['payload'] == {'args': {
        'clientId': 'native-client', 'eventId': 'native-event-1',
        'outcome': {'kind': 'result', 'value': 'allowed-once'},
    }}


def test_approval_result_confirms_a_value_less_native_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Gateway success envelope omits ``value``; that still confirms the reply."""
    from graphtraj.runtimes.dsh.service import DshService
    import urllib.request

    service = DshService('dsh', tmp_path, {})
    service.origin = 'http://127.0.0.1:1'
    service.cookie = 'test-cookie=not-a-real-credential'
    service.client_id = 'native-client'

    class Remote:
        """Return the exact one-shot success shape the Gateway produces."""

        def open(self, call: Any, timeout: float) -> io.StringIO:
            body = json.loads(call.data)
            return io.StringIO(json.dumps({'rpcId': body['rpcId'], 'result': {'ok': True}}))

    monkeypatch.setattr(urllib.request, 'build_opener', lambda *args: Remote())
    # A confirmed delivery must not raise; an omitted value is not a failure.
    assert service.answer_approval('native-event-1', 'allowed-once') is None


def test_remote_call_separates_protocol_and_transport_and_never_infers_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mismatched envelope and an unreachable request stay distinct and unconfirmed."""
    from graphtraj.runtimes.dsh.service import DshService
    import urllib.error
    import urllib.request

    service = DshService('dsh', tmp_path, {})
    service.origin = 'http://127.0.0.1:1'
    service.cookie = 'test-cookie=not-a-real-credential'
    state = {'mode': 'mismatch'}

    class Remote:
        """Return a wrong rpcId or fail the transport, never a native result."""

        def open(self, call: Any, timeout: float) -> io.StringIO:
            if state['mode'] == 'transport':
                raise urllib.error.HTTPError(call.full_url, 503, 'Unavailable', {}, None)
            return io.StringIO(json.dumps({'rpcId': 'other', 'result': {'ok': True, 'value': {}}}))

    monkeypatch.setattr(urllib.request, 'build_opener', lambda *args: Remote())
    with pytest.raises(RuntimeAdapterError) as mismatch:
        service.rpc('session/list', {})
    assert mismatch.value.code == 'RUNTIME_PROTOCOL_ERROR'
    state['mode'] = 'transport'
    with pytest.raises(RuntimeAdapterError) as transport:
        service.rpc('session/list', {})
    assert transport.value.code == 'RUNTIME_CONNECTION_FAILED'


def test_approval_channel_opens_with_ready_and_routes_frames(tmp_path: Path) -> None:
    """The forwarded-event stream proves readiness and never blocks the Session frames."""
    from graphtraj.runtimes.dsh.service import DshService

    class Socket:
        """Scripted multiplexed frames for the two native streams."""

        def __init__(self, messages: list) -> None:
            self.messages = list(messages)
            self.sent = []

        def send(self, text: str) -> None:
            self.sent.append(json.loads(text))

        def recv(self, timeout: float = 1) -> str:
            if not self.messages:
                raise TimeoutError()
            return json.dumps(self.messages.pop(0))

    service = DshService('dsh', tmp_path, {})
    service.socket = Socket([
        {'type': 'item', 'streamId': 'session', 'value': {'type': 'event', 'event': {'type': 'turn/start'}}},
        {'type': 'item', 'streamId': 'events', 'value': {'type': 'ready', 'clientId': 'native-client', 'host': {}}},
        {'type': 'item', 'streamId': 'events', 'value': {'type': 'waterfall', 'eventId': 'native-event-1'}},
    ])
    assert service.open_events() == 'native-client'
    assert service.socket.sent == [{'type': 'open', 'streamId': 'events', 'endpoint': '$events',
                                    'payload': {'args': {}}}]
    assert service.receive() == {'type': 'event', 'event': {'type': 'turn/start'}}
    assert service.receive() == {}
    assert service.take_events() == [{'type': 'waterfall', 'eventId': 'native-event-1'}]


def test_approval_channel_without_ready_is_explicit(tmp_path: Path) -> None:
    """An unanswerable approval channel fails instead of silently hanging a turn."""
    from graphtraj.runtimes.dsh.service import DshService

    class Socket:
        """Return one invalid approval frame instead of the native ready frame."""

        def send(self, text: str) -> None:
            """Ignore the open frame; recv supplies the wrong first frame."""

        def recv(self, timeout: float = 1) -> str:
            return json.dumps({'type': 'item', 'streamId': 'events', 'value': {'type': 'emit'}})

    service = DshService('dsh', tmp_path, {})
    service.socket = Socket()
    with pytest.raises(RuntimeAdapterError) as error:
        service.open_events()
    assert error.value.code == 'RUNTIME_PROTOCOL_ERROR'


def test_dsh_role_projection_keeps_secrets_out_of_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runtime selection translates access/model without persisting inherited secrets."""
    import shutil

    package = tmp_path / 'dsh'
    (package / 'lib').mkdir(parents=True)
    (package / 'package.json').write_text('{"version":"0.2.0-rc.2"}')
    monkeypatch.setattr(shutil, 'which', lambda name: str(package / 'lib' / 'bin.js')
                        if name == 'dsh' else '/installed/graphtraj-tool')
    monkeypatch.setenv('DSH_TEST_KEY', 'never-persist-this-secret')
    role = ResolvedChildRole('author', 'Task responsibility', RolePreset(
        runtime='dsh', model='deepseek-official/deepseek-flash', base_url=None,
        api_key_env='DSH_TEST_KEY', worktree_access='read', reasoning_effort='max',
    ))
    context = select_runtime_adapter('dsh').preflight_runtime_context(
        harness_root=tmp_path, git_common_directory=tmp_path / '.git', role=role,
        worktree=tmp_path / 'work', evidence=tmp_path / 'state', requested_skills=(),
        report_files=(Path('.state/evidence.md'),),
    ).finalize()
    launch = context.launch_document()
    assert launch['adapter_request']['sandbox'] == 'read-only'
    assert launch['adapter_request']['reasoning_effort'] == 'max'
    assert launch['adapter_request']['base_url'] == 'https://api.deepseek.com/anthropic'
    assert 'never-persist-this-secret' not in json.dumps(launch)
    assert context.evidence_document()['native_read_isolation'] is False
