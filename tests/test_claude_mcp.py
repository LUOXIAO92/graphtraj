"""Public Claude stdio function registration and existing caller authorization."""
from io import StringIO
import json
from pathlib import Path

import pytest

from conftest import HeldInput
from graphtraj.execution.runner_status import runtime_caller
from graphtraj.runtimes.claude.mcp import serve
from test_agents_native_claude import project, claude_environment  # noqa: F401


def exchange(project: Path, requests: list[dict]) -> list[dict]:
    """Exercise the public stdio server, including serialization and schemas."""
    output = StringIO()
    expected = sum('id' in request for request in requests)
    serve(HeldInput([json.dumps(r) + '\n' for r in requests],
                    lambda: output.getvalue().count('\n') >= expected), output, project)
    return [json.loads(line) for line in output.getvalue().splitlines()]


def test_register_agents_and_reject_unbound_main(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An env locator or tool argument cannot turn registration into Main authority."""
    monkeypatch.delenv('GRAPHTRAJ_CLI_CONNECTION', raising=False)
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', 'unverified-startup-session')
    with runtime_caller(project / '.graphtraj/runner', None):
        responses = exchange(project, [
            {'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}},
            {'method': 'notifications/initialized'},
            {'id': 2, 'method': 'tools/list'},
            {'id': 3, 'method': 'tools/call', 'params': {'name': 'agents', 'arguments': {'action': 'execute', 'feature': 'status', 'arguments': {}}}},
        ])
    assert len(responses) == 3
    descriptor = responses[1]['result']['tools'][0]
    assert descriptor['name'] == 'agents'
    assert descriptor['inputSchema']['additionalProperties'] is False
    assert responses[2]['result']['isError']
    assert responses[2]['result']['structuredContent']['error']['code'] == 'authority-unavailable'


def test_registered_agents_uses_verified_callback_scope(
    project: Path, claude_environment: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Registration routes create/wait through the existing caller scope, without aliases in input."""
    monkeypatch.delenv('GRAPHTRAJ_CLI_CONNECTION', raising=False)
    with runtime_caller(project / '.graphtraj/runner', 'verified-main'):
        created = exchange(project, [{'id': 1, 'method': 'tools/call', 'params': {
            'name': 'agents', 'arguments': {'action': 'execute', 'feature': 'create', 'arguments': {'runtime': 'claude', 'instruction': 'hello'}}}}])[0]['result']
        assert not created['isError'], created
        agent = created['structuredContent']['agent']
        waited = exchange(project, [{'id': 2, 'method': 'tools/call', 'params': {
            'name': 'agents', 'arguments': {'action': 'execute', 'feature': 'wait', 'arguments': {'agent': agent, 'timeout_seconds': 20}}}}])[0]['result']
    assert not waited['isError'], waited
    assert waited['structuredContent']['result']['state'] == 'standby'
    assert waited['structuredContent']['result']['parent'] == 'verified-main'


def test_failed_host_channel_never_falls_back_and_malformed_input_is_bounded(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lost owned transport remains an explicit failure even with a caller scope."""
    monkeypatch.setenv('GRAPHTRAJ_CLI_CONNECTION', '')
    with runtime_caller(project / '.graphtraj/runner', 'verified-main'):
        reply = exchange(project, [{'id': 1, 'method': 'tools/call', 'params': {
            'name': 'agents', 'arguments': {'action': 'execute', 'feature': 'status', 'arguments': {}}}}])[0]['result']
    assert reply['isError']
    assert reply['structuredContent']['error']['code'] == 'operation-unavailable'
    output = StringIO()
    serve(StringIO('{invalid\n' + json.dumps({'id': 2, 'method': 'tools/list'}) + '\n'), output, project)
    replies = [json.loads(line) for line in output.getvalue().splitlines()]
    assert replies[0]['error']['code'] == -32700
    assert replies[1]['result']['tools'][0]['name'] == 'agents'


def test_progressive_discovery_is_lightweight_and_server_validates_execution(project: Path) -> None:
    """Only the selected schema is expanded, and old flat calls are rejected."""
    replies = exchange(project, [
        {'id': 1, 'method': 'tools/list'},
        {'id': 2, 'method': 'tools/call', 'params': {'name': 'agents',
            'arguments': {'action': 'discover', 'query': 'create'}}},
        {'id': 3, 'method': 'tools/call', 'params': {'name': 'agents',
            'arguments': {'action': 'describe', 'feature': 'create', 'schema': True}}},
        {'id': 4, 'method': 'tools/call', 'params': {'name': 'agents',
            'arguments': {'action': 'create', 'runtime': 'claude', 'instruction': 'must not execute'}}},
    ])
    assert [tool['name'] for tool in replies[0]['result']['tools']] == ['agents', 'tasks']
    assert replies[0]['result']['tools'][0]['inputSchema']['properties']['action']['enum'] == [
        'discover', 'describe', 'execute']
    assert replies[1]['result']['structuredContent']['features'][0]['feature'] == 'create'
    schema = replies[2]['result']['structuredContent']['input_schema']
    assert set(schema['required']) == {'runtime', 'instruction'}
    assert 'configuration' in schema['properties']
    assert replies[3]['result']['isError'] is True
