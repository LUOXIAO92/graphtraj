"""The Codex host runs Claude children beside Codex ones, and Codex reports model fallbacks.

Controlled peers stand in for both Runtimes (codex_stdio_peer.py and
claude_cli_fixture.py); no network or real model is used.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from agent_swarm import AgentControl, AgentsError, Caller, bind
from agent_swarm.codex.driver import CodexDriver
from agent_swarm.codex.host import CodexHost
from agent_swarm.control import ExecutionEvents
from test_claude_runtime import claude_environment  # noqa: F401 - pytest fixture
from test_codex_independent_control import native_settings  # noqa: F401 - pytest fixture

CONFIG = """connections:
  work-claude:
    runtime: claude
    home: {home}
    models:
      - id: claude-sonnet-5-5
        supported_efforts: [low, high]
"""


@pytest.fixture
def host_settings(tmp_path: Path, native_settings: dict, claude_environment: None) -> dict:
    """Codex host settings with a Claude entry and a declared Claude connection."""
    home = tmp_path / 'claude-home'
    home.mkdir()
    (home / '.credentials.json').write_text('{}')  # existence only; never read
    (tmp_path / 'host').mkdir()
    (tmp_path / 'host/config.yml').write_text(CONFIG.format(home=home))
    return {**native_settings, 'runtimes': {'claude': {}}}


def until(check, timeout: float = 20):
    """Return the first truthy ``check()`` result, failing after ``timeout``."""
    deadline = time.monotonic() + timeout
    while not (value := check()):
        assert time.monotonic() < deadline, 'condition not reached'
        time.sleep(0.02)
    return value


class Running:
    """Run one host invocation in the background while the test acts as its parent."""

    def __init__(self, host: CodexHost) -> None:
        """Start the host and wait for its held parent turn."""
        self.host = host
        self.result: dict = {}
        self.thread = threading.Thread(target=lambda: self.result.update(host.run()))
        self.thread.start()
        until(lambda: host.execution is not None)

    def call(self, action: str, **arguments: object) -> dict:
        """Call agents exactly as the parent's authenticated MCP entry does."""
        result = self.host._call_agents({'action': action, **arguments})
        assert not result.failed, result.document
        return result.document

    def stop(self) -> dict:
        """End the parent turn; the host stops only the children it still runs."""
        self.host.terminate()
        self.thread.join(20)
        return self.result


def events(path: Path) -> list[dict]:
    """Host events the parent's native Session received, in order."""
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def settled(running: Running, agent: str) -> dict:
    """Status of ``agent`` once its last end has a final notification state."""
    def check() -> dict | None:
        result = running.call('status', agent=agent)['result']
        last = result.get('last_result') or {}
        return result if result['state'] == 'standby' and last.get('notification') not in (
            None, 'pending', 'queueing') else None
    return until(check)


def test_codex_host_runs_a_claude_child_end_to_end(
    tmp_path: Path, host_settings: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create with model and effort, notices once, send, interrupt, host resume, child resume, retire."""
    log = tmp_path / 'host-events.jsonl'
    monkeypatch.setenv('PEER_HOST_EVENTS', str(log))
    running = Running(CodexHost(host_settings, tmp_path / 'host', 'hold'))
    parent = running.host.native_session
    try:
        created = running.call('create', runtime='claude', instruction='hello',
                               model='claude-sonnet-5-5', reasoning_effort='high')
        agent, session = created['agent'], created['session']
        child = settled(running, agent)
        assert child['runtime'] == 'claude' and child['parent'] is None
        assert child['creator']['session'] == parent
        assert (child['model'], child['reasoning_effort'], child['connection']) == (
            'claude-sonnet-5-5', 'high', 'work-claude')
        assert child['last_result']['outcome'] == 'completed'
        assert child['last_result']['notification'] == 'delivered'
        assert child['last_result']['last_message'] is None
        selection = json.loads((tmp_path / 'native-selection.json').read_text())
        assert (selection['model'], selection['effort']) == ('claude-sonnet-5-5', 'high')
        assert events(log) == [{'source': 'agents', 'alias': agent, 'event': 'completed', 'message': 'hello'}]

        # A repeated end report for the same execution notifies nobody again,
        # and reading the result through wait/status does not repeat it either.
        ExecutionEvents(running.host.control, agent, created['execution']).finished(
            'completed', last_message='hello')
        running.call('wait', agent=agent, timeout_seconds=5)
        assert len(events(log)) == 1

        sent = running.call('send', agent=agent, message='again')
        assert sent['session'] == session
        settled(running, agent)
        assert events(log)[-1]['message'] == 'hello|again'
        running.call('resume', agent=agent, message='wait-hold')
        running.call('interrupt', agent=agent)
        stopped = settled(running, agent)
        assert stopped['last_result']['outcome'] == 'interrupted'
        assert [event['event'] for event in events(log)] == ['completed', 'completed', 'interrupted']
    finally:
        first = running.stop()
    assert [call['action'] for call in first['operations']][:2] == ['create', 'status']
    assert first['deliveries'][0]['agent'] == agent

    # The parent continues its own Session; the Claude child resumes its own.
    running = Running(CodexHost(host_settings, tmp_path / 'host', 'hold', resume=True))
    try:
        assert running.host.native_session == parent
        resumed = running.call('resume', agent=agent, message='recall')
        assert resumed['session'] == session
        settled(running, agent)
        assert events(log)[-1]['message'].endswith('|recall')
        running.call('retire', agent=agent)
        assert running.call('status')['result']['agents'] == []
    finally:
        running.stop()


def test_codex_children_keep_working_beside_claude(tmp_path: Path, host_settings: dict) -> None:
    """The Codex driver still runs Codex children, with their own model and effort."""
    host = CodexHost(host_settings, tmp_path / 'host', 'unused')
    call = bind(host.control, Caller('codex', None, 'parent-session', 'codex'))
    created = call({'action': 'create', 'runtime': 'codex', 'instruction': 'configuration',
                    'reasoning_effort': 'low'})
    assert not created.failed, created.document
    try:
        done = call({'action': 'wait', 'agent': created.document['agent'], 'timeout_seconds': 10}).document
        observed = json.loads(done['result']['last_result']['last_message'])
        assert observed['config']['model_reasoning_effort'] == 'low'
        assert 'runtimes' not in json.dumps(observed)
        assert done['result']['runtime'] == 'codex'
    finally:
        host.control.interrupt_owned()


@pytest.mark.parametrize(('runtimes', 'code'), [
    ({'pi': {}}, 'invalid-config'),
    ({'gemini': {}}, 'unsupported-runtime'),
    ({'codex': {}}, 'invalid-config'),
    ({'claude': 'model'}, 'invalid-config'),
    ({'claude': {'colour': 'blue'}}, 'invalid-config'),
])
def test_runtimes_entries_are_checked_at_start(
    tmp_path: Path, host_settings: dict, runtimes: dict, code: str,
) -> None:
    """An entry the host cannot run is a startup error, before any native process."""
    with pytest.raises(AgentsError) as raised:
        CodexHost({**host_settings, 'runtimes': runtimes}, tmp_path / 'host', 'never runs')
    assert raised.value.code == code
    assert not (tmp_path / 'host/host/session.yml').exists()


def test_create_without_a_runtimes_entry_is_unsupported(tmp_path: Path, native_settings: dict) -> None:
    """No entry, no driver: a Claude create fails as before this release."""
    host = CodexHost(native_settings, tmp_path / 'plain', 'unused')
    call = bind(host.control, Caller('codex', None, 'parent-session', 'codex'))
    result = call({'action': 'create', 'runtime': 'claude', 'instruction': 'x'})
    assert result.failed and result.document['error']['code'] == 'unsupported-runtime'


@pytest.mark.parametrize(('arguments', 'code'), [
    ({'model': 'claude-unknown'}, 'invalid-model'),
    ({'model': 'claude-sonnet-5-5', 'reasoning_effort': 'max'}, 'invalid-reasoning-effort'),
    ({'reasoning_effort': 'extreme'}, 'invalid-reasoning-effort'),
])
def test_invalid_claude_selection_from_the_codex_host(
    tmp_path: Path, host_settings: dict, arguments: dict, code: str,
) -> None:
    """A refused selection writes no Agent and starts no Claude process."""
    host = CodexHost(host_settings, tmp_path / 'host', 'unused')
    call = bind(host.control, Caller('codex', None, 'parent-session', 'codex'))
    result = call({'action': 'create', 'runtime': 'claude', 'instruction': 'x', **arguments})
    assert result.failed and result.document['error']['code'] == code, result.document
    assert call({'action': 'status'}).document['result']['agents'] == []
    assert not (tmp_path / 'native-selection.json').exists()


@pytest.mark.parametrize(('connection', 'code'), [
    ('  other:\n    runtime: pi\n', 'unsupported-runtime'),
    ('  mine:\n    runtime: codex\n    home: {missing}\n', 'runtime-unavailable'),
])
def test_host_start_requires_declared_connections(
    tmp_path: Path, host_settings: dict, connection: str, code: str,
) -> None:
    """The CLI prints the startup error document and exits 1."""
    config = tmp_path / 'host/config.yml'
    config.write_text(config.read_text() + connection.format(missing=tmp_path / 'no-codex-home'))
    settings = tmp_path / 'settings.json'
    settings.write_text(json.dumps(host_settings))
    result = subprocess.run([
        sys.executable, '-m', 'agent_swarm.codex.host', '--settings', str(settings),
        '--directory', str(tmp_path / 'host'), 'never runs',
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads(result.stdout)['error']['code'] == code
    assert not (tmp_path / 'host/host/session.yml').exists()


@pytest.mark.parametrize(('observed', 'prompt', 'message'), [
    ('other-model', 'configuration',
     'requested model chosen-model, observed model other-model; Runtime reason: not provided in the native stream.'),
    (None, 'rerouted',
     'requested model chosen-model, observed model safer-model; Runtime reason: highRiskCyberActivity.'),
])
def test_codex_child_model_change_fails_with_both_models(
    tmp_path: Path, native_settings: dict, monkeypatch: pytest.MonkeyPatch,
    observed: str | None, prompt: str, message: str,
) -> None:
    """thread/start's model and model/rerouted both end the child failed, naming both models."""
    if observed is not None:
        monkeypatch.setenv('PEER_OBSERVED_MODEL', observed)
    control = AgentControl(tmp_path / 'agents', {'codex': CodexDriver(native_settings)})
    call = bind(control, Caller('host', None, 'parent-session', 'codex'))
    created = call({'action': 'create', 'runtime': 'codex', 'instruction': prompt})
    agent = created.document.get('agent')
    try:
        def ended() -> dict | None:
            result = call({'action': 'status', 'agent': agent}).document['result']
            return result if result['state'] == 'standby' else None
        result = until(ended)
        assert result['last_result']['outcome'] == 'failed'
        error = result['last_result']['error']
        assert error['code'] == 'RUNTIME_REQUEST_FAILED'
        assert error['message'].endswith(message), error
    finally:
        control.interrupt_owned()


@pytest.mark.parametrize(('runtime', 'instruction', 'response', 'named'), [
    ('claude', 'permission', {'behavior': 'allow'}, 'claude/can_use_tool for Bash'),
    ('codex', 'request:item/commandExecution/requestApproval', {'decision': 'accept'},
     'item/commandExecution/requestApproval'),
])
def test_child_permission_request_reaches_the_codex_parent_once(
    tmp_path: Path, host_settings: dict, monkeypatch: pytest.MonkeyPatch,
    runtime: str, instruction: str, response: dict, named: str,
) -> None:
    """One host event per native request, whatever the child's Runtime; the reply still goes through reply."""
    log = tmp_path / 'host-events.jsonl'
    monkeypatch.setenv('PEER_HOST_EVENTS', str(log))
    running = Running(CodexHost(host_settings, tmp_path / 'host', 'hold'))
    try:
        agent = running.call('create', runtime=runtime, instruction=instruction)['agent']
        [request] = until(lambda: running.call('requests', agent=agent)['result']['requests'])
        [event] = until(lambda: events(log))
        assert (event['alias'], event['event']) == (agent, 'request')
        assert named in event['message'] and 'reply' in event['message']
        assert running.call('status', agent=agent)['result']['pending_requests'] == 1
        running.call('reply', agent=agent, request=request, response=response)
        settled(running, agent)
        assert [item['event'] for item in events(log)] == ['request', 'completed']
    finally:
        running.stop()


@pytest.mark.parametrize('runtime', ['codex', 'claude'])
def test_grandchild_under_a_codex_child_keeps_its_parentage(
    tmp_path: Path, host_settings: dict, monkeypatch: pytest.MonkeyPatch, runtime: str,
) -> None:
    """A Codex child's own create (agent_call) records the child as parent, on either Runtime.

    The grandchild's end goes to that child, not to the host's root parent; the
    Claude grandchild matches the Codex one (test_codex_child_parent_notices.py).
    """
    log = tmp_path / 'host-events.jsonl'
    monkeypatch.setenv('PEER_HOST_EVENTS', str(log))
    monkeypatch.setenv('PEER_MCP_REQUESTS', json.dumps([
        {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'agents', 'arguments': {
            'action': 'execute', 'feature': 'create', 'arguments': {'runtime': runtime, 'instruction': 'hello'}}}},
    ]))
    running = Running(CodexHost(host_settings, tmp_path / 'host', 'hold'))
    try:
        child = running.call('create', runtime='codex', instruction='mcp-requests')['agent']
        [created] = until(lambda: running.call('status')['result']['agents'][0]['children'])
        grandchild = created['agent']
        assert created['parent'] == child and created['runtime'] == runtime
        session = running.call('status', agent=child)['result']['session']
        call = bind(running.host.control, Caller('codex', child, session, 'codex'))

        def ended() -> dict | None:
            result = call({'action': 'status', 'agent': grandchild}).document['result']
            return result if result.get('last_result', {}).get('notification') == 'delivered' else None
        result = until(ended)
        assert result['parent'] == child and result['last_result']['outcome'] == 'completed'
        assert {event['alias'] for event in events(log)} <= {child}
    finally:
        running.stop()
