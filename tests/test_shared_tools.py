"""Shared definitions execute through both transports without an MCP dependency."""

import asyncio
import io
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

import pytest

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.interfaces import mcp, tools
from graphtraj.runtimes.codex.app_server import CodexAppServer, CodexServerRequest
from graphtraj.runtimes.codex.codex_adapter import native_runner_tools
from graphtraj.runtimes.codex.managed_session import run_native_operation
from test_codex_app_server import peer


@pytest.fixture(autouse=True)
def configure_project(tmp_path: Path) -> None:
    """Provide the real project binding used by native operation authorization."""
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


def native_request(root: Path, name: str, arguments: dict) -> dict:
    """Invoke the callback with its bound owning Session identity."""
    request = CodexServerRequest(1, 'item/tool/call', {
        'threadId': 'owner', 'tool': name, 'arguments': arguments,
    })
    return asyncio.run(run_native_operation(
        CodexAppServer(cwd=root), 'owner', None, root, request,
    ))


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
    monkeypatch.setitem(tools.TOOLS, 'alias_status', replace(
        tools.TOOLS['alias_status'], input_schema=schema, handler=handler,
    ))
    monkeypatch.chdir(tmp_path)
    listed = mcp_request('tools/list', {})['tools']
    native = native_runner_tools()
    assert len(listed) == 30
    assert [tool['name'] for tool in native] == ['graphtraj']
    assert next(t for t in listed if t['name'] == 'alias_status')['inputSchema'] == schema
    described = native_request(tmp_path, 'graphtraj', {'action': 'describe', 'feature': 'alias_status'})
    assert json.loads(described['contentItems'][0]['text'])['input_schema'] == schema

    arguments = {'sample': 'shared'}
    result = mcp_request('tools/call', {'name': 'alias_status', 'arguments': arguments})
    response = native_request(tmp_path, 'graphtraj', {
        'action': 'execute', 'feature': 'alias_status', 'arguments': arguments,
    })
    assert result['structuredContent'] == json.loads(response['contentItems'][0]['text'])
    assert result['isError'] is failed
    assert response['success'] is not failed
    assert calls == [arguments, arguments]


def test_both_transports_preserve_handler_input_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The existing argument error survives each transport's error formatting."""
    monkeypatch.chdir(tmp_path)
    arguments = {'alias': 'child', 'instruction': 42}
    result = mcp_request('tools/call', {'name': 'send_instruction', 'arguments': arguments})
    response = native_request(tmp_path, 'graphtraj_send', arguments)
    assert result['isError'] is True
    assert response['success'] is False
    error = json.loads(response['contentItems'][0]['text'])['error']
    assert error == {'code': 'invalid-input', 'message': 'instruction must be a string'}
    assert result['content'][0]['text'] == error['message']


def test_main_native_callback_runs_when_mcp_import_is_unavailable(
    tmp_path: Path, peer: Path,
) -> None:
    """A fresh process runs a real native peer callback while MCP imports fail."""
    exchange = {'method': 'item/tool/call', 'params': {
        'threadId': 'thread-1', 'tool': 'graphtraj', 'arguments': {
            'action': 'execute', 'feature': 'alias_status', 'arguments': {}}},
        'response': {'contentItems': [{'type': 'inputText', 'text': '{"agents": []}'}],
                     'success': True}}
    environment = {**os.environ, 'PEER_REQUEST_EXCHANGE': json.dumps(exchange),
                   'PEER_NATIVE_ROLLOUT': str(tmp_path / 'native')}
    source = Path(__file__).resolve().parents[1] / 'src'
    script = '''
import asyncio
import importlib.abc
import sys
from pathlib import Path

class NoMcp(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'graphtraj.interfaces.mcp':
            raise ModuleNotFoundError('MCP is unavailable')

sys.meta_path.insert(0, NoMcp())
sys.path.insert(0, sys.argv[1])
from graphtraj.interfaces import tools
from graphtraj.runtimes.codex import main_session
assert Path(tools.__file__).is_relative_to(Path(sys.argv[1]))
main_session.runtime_executable = lambda runtime: Path(sys.argv[3])
async def unexpected(request):
    raise AssertionError(request.method)
result = asyncio.run(main_session.run_main(Path(sys.argv[2]), 'configured-request', None, unexpected))
assert result['last_agent_message'] == 'request accepted', result
assert result['native_operations'] == [{'tool': 'graphtraj', 'success': True,
                                       'from_main': True, 'aliases': []}], result
'''
    completed = subprocess.run(
        [sys.executable, '-c', script, str(source), str(tmp_path), str(peer)],
        env=environment, cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
