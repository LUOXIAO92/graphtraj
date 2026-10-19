"""Shared definitions execute through both transports without an MCP dependency."""

import io
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

import pytest

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.interfaces import gateway, mcp, tools, local_tool


@pytest.fixture(autouse=True)
def configure_project(tmp_path: Path) -> None:
    """Provide the real project binding used by CLI and MCP operations."""
    configuration = tmp_path / '.graphtraj/config.yml'
    configuration.parent.mkdir()
    configuration.write_text(default_configuration_content(tmp_path, tmp_path))


def mcp_request(method: str, params: dict) -> dict:
    """Send a complete request through the MCP stream boundary."""
    output = io.StringIO()
    mcp.serve(io.StringIO(json.dumps({
        'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params,
    }) + '\n'), output)
    return json.loads(output.getvalue())['result']


def cli_request(root: Path, arguments: dict) -> dict:
    """Invoke the public JSON CLI bridge with its actual response format."""
    return local_tool.answer(arguments, cwd=root)


@pytest.mark.parametrize('failed', [False, True])
def test_both_transports_consume_shared_schema_and_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed: bool,
) -> None:
    """Changing one definition changes both descriptions and execution results."""
    calls = []

    def handler(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> tools.ToolResult:
        """Expose the actual arguments and operation outcome to both transports."""
        calls.append(dict(arguments))
        return tools.ToolResult({'received': dict(arguments)}, failed=failed)

    schema = {'type': 'object', 'properties': {'sample': {'type': 'string'}},
              'required': ['sample'], 'additionalProperties': False}
    monkeypatch.setitem(tools.TOOLS, 'task_graph', replace(
        tools.TOOLS['task_graph'], input_schema=schema, handler=handler,
    ))
    monkeypatch.chdir(tmp_path)
    listed = mcp_request('tools/list', {})['tools']
    assert [tool['name'] for tool in listed] == ['agents', 'tasks']
    discovered = mcp_request('tools/call', {
        'name': 'tasks', 'arguments': {'action': 'discover'},
    })['structuredContent']['features']
    assert 'approved_recovery' in {item['feature'] for item in discovered}
    assert {item['feature'] for item in discovered} == set(tools.TOOLS) - {'agents'}
    assert listed[0]['inputSchema'] == gateway.INPUT_SCHEMA
    described = mcp_request('tools/call', {
        'name': 'tasks',
        'arguments': {'action': 'describe', 'feature': 'task_graph', 'schema': True},
    })['structuredContent']
    cli_description = cli_request(tmp_path, {
        'action': 'describe', 'feature': 'task_graph', 'schema': True,
    })
    assert described['input_schema'] == schema
    assert cli_description['result']['input_schema'] == schema

    arguments = {'sample': 'shared'}
    result = mcp_request('tools/call', {
        'name': 'tasks',
        'arguments': {'action': 'execute', 'feature': 'task_graph',
                      'arguments': arguments},
    })
    response = cli_request(tmp_path, {
        'action': 'execute', 'feature': 'task_graph', 'arguments': arguments,
    })
    assert result['structuredContent'] == response['result']
    assert result['isError'] is failed
    assert response['failed'] is failed
    assert calls == [arguments, arguments]


def test_both_transports_preserve_handler_input_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both transports preserve the shared gateway's argument rejection."""
    monkeypatch.chdir(tmp_path)
    arguments = {'summary_task_id': 42}
    result = mcp_request('tools/call', {
        'name': 'tasks',
        'arguments': {'action': 'execute', 'feature': 'task_members',
                      'arguments': arguments},
    })
    response = cli_request(tmp_path, {
        'action': 'execute', 'feature': 'task_members', 'arguments': arguments,
    })
    assert result['isError'] is True
    assert response['failed'] is True
    document = response['result']
    assert result['structuredContent'] == document
    assert document['feature'] == 'task_members'
    assert 'summary_task_id' in document['error']
    assert 'summary_task_id' in result['content'][0]['text']
