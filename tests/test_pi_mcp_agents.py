"""Pi progressive MCP entries reuse the public server and gateway."""
import io
import json

import pytest

from agent_swarm import tool_descriptor
from graphtraj.interfaces import mcp
from graphtraj.interfaces.tools import ToolResult


def test_pi_mcp_registers_core_schema_and_forwards_bound_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """The MCP function passes no model-selected caller identity to the host."""
    monkeypatch.setenv('GRAPHTRAJ_NATIVE_RUNTIME', 'pi')
    requests = []

    def forward(request: dict, cwd: object) -> ToolResult:
        """Stand in only for the already authenticated host boundary."""
        requests.append(request)
        return ToolResult({'action': 'status', 'result': {'agents': []}})

    monkeypatch.setattr('graphtraj.interfaces.hosted_cli.forward_request', forward)
    output = io.StringIO()
    mcp.serve(io.StringIO('\n'.join(json.dumps(request) for request in [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
         'params': {'name': 'agents', 'arguments': {'action': 'execute', 'feature': 'agents', 'arguments': {'action': 'status'}}}},
    ])), output)
    listed, called = [json.loads(line) for line in output.getvalue().splitlines()]
    descriptor = next(tool for tool in listed['result']['tools'] if tool['name'] == 'agents')
    assert [tool['name'] for tool in listed['result']['tools']] == ['agents', 'tasks']
    assert descriptor['inputSchema'] == mcp.gateway.INPUT_SCHEMA
    assert 'runtime' not in descriptor['inputSchema']['properties']
    assert requests == [{'action': 'execute', 'feature': 'agents', 'arguments': {'action': 'status'}}]
    assert called['result']['structuredContent'] == {'action': 'status', 'result': {'agents': []}}
    assert called['result']['isError'] is False


def test_pi_mcp_progressive_discovery_schema_and_entry_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only an explicit selected describe reveals the business schema."""
    monkeypatch.setenv('GRAPHTRAJ_NATIVE_RUNTIME', 'pi')
    monkeypatch.delenv('GRAPHTRAJ_CLI_CONNECTION', raising=False)
    calls = [
        ('agents', {'action': 'discover'}),
        ('tasks', {'action': 'discover'}),
        ('agents', {'action': 'describe', 'feature': 'agents', 'schema': True}),
        ('tasks', {'action': 'describe', 'feature': 'agents', 'schema': True}),
        ('graphtraj', {'action': 'discover'}),
        ('agents', {'action': 'execute', 'feature': 'agents', 'arguments': {'unknown': True}}),
    ]
    output = io.StringIO()
    mcp.serve(io.StringIO('\n'.join(json.dumps({
        'jsonrpc': '2.0', 'id': index, 'method': 'tools/call',
        'params': {'name': name, 'arguments': arguments},
    }) for index, (name, arguments) in enumerate(calls))), output)
    discovered, tasks, described, wrong, old, invalid = [
        json.loads(line) for line in output.getvalue().splitlines()
    ]
    assert [item['feature'] for item in discovered['result']['structuredContent']['features']] == ['agents']
    assert all(item['feature'] != 'agents' for item in tasks['result']['structuredContent']['features'])
    assert described['result']['structuredContent']['input_schema'] == tool_descriptor()['input_schema']
    assert wrong['result']['isError']
    assert old['error']['code'] == -32602
    assert invalid['result']['isError']
