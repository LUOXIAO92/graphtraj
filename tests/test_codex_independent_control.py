"""Independent control at the native stdio and authenticated MCP boundaries."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from agent_swarm import AgentControl, Caller, bind
from agent_swarm.codex.driver import CodexDriver


@pytest.fixture
def native_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Configure the controlled peer without loading any GraphTraj role or Task."""
    peer = tmp_path / 'codex'
    peer.write_text('#!' + sys.executable + '\n' + Path(__file__).with_name('codex_stdio_peer.py').read_text())
    peer.chmod(0o755)
    monkeypatch.setenv('PYTHONPATH', str(Path(__file__).resolve().parents[1] / 'src'))
    monkeypatch.setenv('PEER_NATIVE_ROLLOUT', str(tmp_path / 'native'))
    return {'adapter_request': {
        'arguments': [str(peer)], 'worktree_path': str(tmp_path),
        'session_parameters': {'cwd': str(tmp_path), 'model': 'chosen-model',
            'developerInstructions': 'Retain native settings.',
            'config': {'default_permissions': 'chosen', 'permissions': {
                'chosen': {'extends': ':workspace', 'filesystem': {str(tmp_path): 'write'}},
            }}},
    }}


def test_independent_lifecycle_requests_and_authentication(
    tmp_path: Path,
    native_settings: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One bound owner creates, steers, stops, resumes and retires the same native Session."""
    driver = CodexDriver(native_settings)
    control = AgentControl(tmp_path / 'agents', {'codex': driver})
    call = bind(control, Caller('controlled-host', 'actual-parent', 'parent-session', 'codex'))

    def invoke(action: str, **arguments: object) -> dict:
        """Fail at the public result rather than inspecting driver internals."""
        result = call({'action': action, **arguments})
        assert not result.failed, result.document
        return result.document

    try:
        created = invoke('create', runtime='codex', instruction='configuration')
        agent, session = created['agent'], created['session']
        done = invoke('wait', agent=agent, timeout_seconds=10)
        observed = json.loads(done['result']['last_result']['last_message'])
        assert observed['config']['approvals_reviewer'] == 'auto_review'
        assert observed['model'] == 'chosen-model'
        [member] = invoke('status')['result']['agents']
        assert member['parent'] == 'actual-parent'
        assert member['state'] == 'standby'

        invoke('resume', agent=agent, message='hold')
        invoke('send', agent=agent, message='body delivered')
        done = invoke('wait', agent=agent, timeout_seconds=10)
        assert done['result']['last_result']['last_message'] == 'body delivered'
        invoke('resume', agent=agent, message='hold')
        invoke('interrupt', agent=agent)
        stopped = invoke('wait', agent=agent, timeout_seconds=10)
        assert stopped['result']['last_result']['outcome'] == 'interrupted'
        assert stopped['result']['state'] == 'standby'
        resumed = invoke('resume', agent=agent, message='request:item/commandExecution/requestApproval')
        assert resumed['session'] == session
        assert invoke('wait', agent=agent, timeout_seconds=10)['result']['pending_requests'] == 1
        [request] = invoke('requests', agent=agent)['result']['requests']
        invoke('reply', agent=agent, request=request, response={'decision': 'accept'})
        assert invoke('wait', agent=agent, timeout_seconds=10)['result']['last_result']['last_message'] == 'request accepted'

        monkeypatch.setenv('PEER_MCP_REQUESTS', json.dumps([
            {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'agents',
             'arguments': {'action': 'describe', 'feature': 'status', 'schema': True}}},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'agents',
             'arguments': {'action': 'execute', 'feature': 'status', 'arguments': {}}}},
        ]))
        invoke('resume', agent=agent, message='mcp-requests')
        responses = json.loads(invoke('wait', agent=agent, timeout_seconds=10)['result']['last_result']['last_message'])
        assert [tool['name'] for tool in responses[0]['result']['tools']] == ['agents']
        assert 'input_schema' in responses[1]['result']['structuredContent']
        assert responses[2]['result']['structuredContent']['result']['agents'] == []
        invoke('retire', agent=agent)
        assert invoke('status')['result']['agents'] == []
        assert not (tmp_path / 'agents/sessions').exists()
        assert not (tmp_path / '.graphtraj').exists()
    finally:
        for owned in control.interrupt_owned():
            invoke('wait', agent=owned, timeout_seconds=10)


def test_packaged_host_owns_parent_mcp_and_resume(
    tmp_path: Path,
    native_settings: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A normal host owns the native process and binds calls to its actual Session."""
    from agent_swarm.codex.host import CodexHost

    monkeypatch.setenv('PEER_MCP_REQUESTS', json.dumps([
        {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'agents',
         'arguments': {'action': 'execute', 'feature': 'status', 'arguments': {}}}},
    ]))
    host = CodexHost(native_settings, tmp_path / 'host-state', 'mcp-requests')
    result = host.run()
    assert result['outcome'] == 'completed'
    assert result['operations'][0]['parent_session'] == result['parent_session']
    assert result['operations'][0]['result']['result']['agents'] == []
    with pytest.raises(Exception, match='Use --resume'):
        CodexHost(native_settings, tmp_path / 'host-state', 'must not launch')
    resumed = CodexHost(native_settings, tmp_path / 'host-state', 'continued', resume=True).run()
    assert resumed['session_id'] == result['session_id']
    assert resumed['last_agent_message'] == 'continued'


def test_external_root_reply_uses_existing_receiver(tmp_path: Path) -> None:
    """An external native root receives body once, without a fake Agent identity."""
    notices = []

    class Driver:
        """Minimal controlled native outcome for the public root callback contract."""

        def prepare(self, runtime: str, caller: Caller, **kwargs: object) -> dict:
            """No launch settings are needed for this controlled result."""
            return {}

        def start(self, run: object) -> None:
            """Emit one native identity and completed body."""
            run.events.session('child-session')
            run.events.finished('completed', last_message='child body')

    control = AgentControl(tmp_path, {'codex': Driver()},
                           event_receiver=lambda notice: (notices.append(notice), True)[1])
    call = bind(control, Caller('verified-native-host', None, 'parent-session', 'codex'))
    created = call({'action': 'create', 'runtime': 'codex', 'instruction': 'first'})
    assert not created.failed, created.document
    assert [notice['body'] for notice in notices] == ['child body']
    result = call({'action': 'status', 'agent': created.document['agent']}).document['result']
    assert result['parent'] is None
    assert result['creator']['session'] == 'parent-session'
    assert result['last_result']['notification'] == 'delivered'
    assert result['last_result']['last_message'] is None


def test_lost_parent_acknowledgement_does_not_repeat_child_body(
    tmp_path: Path,
    native_settings: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A submitted native callback stays unconfirmed after its connection closes."""
    import time
    from agent_swarm.codex.host import CodexHost

    monkeypatch.setenv('PEER_DROP_HOST_REPLY', '1')
    host = CodexHost(native_settings, tmp_path / 'lost-reply', 'mcp-create-child')
    host.run()
    call = bind(host.control, Caller('codex', None, host.native_session, 'codex'))
    deadline = time.monotonic() + 5
    while True:
        result = call({'action': 'status'})
        assert not result.failed, result.document
        [child] = result.document['result']['agents']
        if child['last_result'].get('notification') != 'pending':
            break
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert child['last_result']['notification'] == 'unconfirmed'
    assert child['last_result']['last_message'] is None


def test_host_cli_reports_native_turn_failure(tmp_path: Path, native_settings: dict) -> None:
    """A native failed turn must not produce a successful product command exit."""
    import subprocess

    settings = tmp_path / 'settings.json'
    settings.write_text(json.dumps(native_settings))
    output = tmp_path / 'failed-result.json'
    result = subprocess.run([
        sys.executable, '-m', 'agent_swarm.codex.host', '--settings', str(settings),
        '--directory', str(tmp_path / 'failed-host'), '--output', str(output), 'failed-turn',
    ], capture_output=True, text=True, timeout=10)
    assert result.returncode == 1, result.stdout + result.stderr
    native = json.loads(output.read_text())
    assert native['outcome'] == 'runtime-error'
    assert native['error']['code'] == 'RUNTIME_EXECUTION_FAILED'
    assert 'native execution failed' in result.stderr
