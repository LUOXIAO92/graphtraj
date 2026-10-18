"""Pi's registered agents function reuses the public MCP server and gateway."""
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
         'params': {'name': 'agents', 'arguments': {'action': 'status'}}},
    ])), output)
    listed, called = [json.loads(line) for line in output.getvalue().splitlines()]
    descriptor = next(tool for tool in listed['result']['tools'] if tool['name'] == 'agents')
    assert descriptor['inputSchema'] == tool_descriptor()['input_schema']
    assert requests == [{'action': 'execute', 'feature': 'agents', 'arguments': {'action': 'status'}}]
    assert called['result']['structuredContent'] == {'action': 'status', 'result': {'agents': []}}
    assert called['result']['isError'] is False
