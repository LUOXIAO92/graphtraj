"""Codex-owned stdio MCP discovery, authority and configuration through a peer."""
import asyncio
import json
from pathlib import Path

import pytest
import yaml

from agent_swarm import Caller
from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.interfaces.agents import agents_callback
from graphtraj.runtimes.codex import main_session
from graphtraj.runtimes.codex.app_server import CodexServerRequest
from test_codex_app_server import peer


@pytest.mark.parametrize('host', ['main', 'independent'])
@pytest.mark.parametrize('issuer', ['thread-1', 'helper'])
def test_codex_uses_progressive_mcp_with_native_session_authority(
    tmp_path: Path,
    peer: Path,
    monkeypatch: pytest.MonkeyPatch,
    host: str,
    issuer: str,
) -> None:
    """A native descendant really starts MCP; only its bound Session can execute.

    The external Codex peer is controlled. This verifies transport and wiring,
    not model inference or a CLI/IDE screen.
    """
    from graphtraj.workspace import runner_project

    (tmp_path / '.graphtraj').mkdir()
    (tmp_path / '.graphtraj/config.yml').write_text(default_configuration_content(tmp_path, tmp_path))
    (tmp_path / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'codex': {'runtime': 'codex', 'model': 'selected-model'}},
    }))
    monkeypatch.setattr(main_session, 'runtime_executable', lambda runtime: peer)
    monkeypatch.setattr(runner_project, 'runtime_executable', lambda runtime: peer)
    monkeypatch.setenv('PYTHONPATH', str(Path(__file__).resolve().parents[1] / 'src'))
    monkeypatch.setenv('PEER_MCP_ISSUER', issuer)
    monkeypatch.setenv('PEER_THREAD_PARENTS', json.dumps({'helper': 'thread-1'}))
    monkeypatch.setenv('PEER_NATIVE_ROLLOUT', str(tmp_path / 'native'))
    protocol = tmp_path / 'protocol.jsonl'
    monkeypatch.setenv('PEER_PROTOCOL_LOG', str(protocol))
    requests = [{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}]
    for index, arguments in enumerate([
        {'action': 'discover', 'query': 'status'},
        {'action': 'describe', 'feature': 'status', 'schema': True},
        {'action': 'execute', 'feature': 'status', 'arguments': {}},
    ], 2):
        requests.append({'jsonrpc': '2.0', 'id': index, 'method': 'tools/call',
                         'params': {'name': 'agents', 'arguments': arguments}})
    if host == 'main':
        directory = tmp_path / '.graphtraj/runner/sessions/child@e1'
        directory.mkdir(parents=True)
        (directory / 'mapping.yml').write_text(yaml.safe_dump({
            'alias': 'child@e1', 'parent': None, 'session': 'private-native-session',
            'execution_id': 'private-turn', 'worker_pid': 1, 'runtime_pid': 1,
            'runtime': 'codex', 'task_id': '133', 'team_generation': 2,
            'role': 'engineer', 'retained_batch_file': 'batch.yml',
            'worktree_path': str(tmp_path), 'trace_file': 'unused',
        }))
        (directory / 'execution.yml').write_text(yaml.safe_dump({
            'outcome': 'completed', 'terminal_confirmed': True,
        }))
        requests.append({'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call',
                         'params': {'name': 'tasks', 'arguments': {'action': 'execute',
                         'feature': 'alias_status', 'arguments': {'aliases': ['child@e1']}}}})
    monkeypatch.setenv('PEER_MCP_REQUESTS', json.dumps(requests))

    async def native_request(request: CodexServerRequest) -> dict:
        """No custom native tool callback is part of this path."""
        raise AssertionError(request.method)

    if host == 'main':
        result = asyncio.run(main_session.run_main(tmp_path, 'mcp-requests', None, native_request))
        observed = json.loads(result['last_agent_message'])
    else:
        call = agents_callback(tmp_path, Caller('test-host', 'parent'))
        result = call({'action': 'create', 'runtime': 'codex', 'instruction': 'mcp-requests'})
        assert not result.failed, result.document
        done = call({'action': 'wait', 'agent': result.document['agent'], 'timeout_seconds': 10})
        assert not done.failed, done.document
        observed = json.loads(done.document['result']['last_result']['last_message'])
    tools = observed[0]['result']['tools']
    assert {tool['name'] for tool in tools} == ({'agents', 'tasks'} if host == 'main' else {'agents'})
    assert all(set(tool['inputSchema']['properties']) == {'action', 'query', 'feature', 'schema', 'arguments'}
               for tool in tools)
    if issuer == 'thread-1':
        assert observed[1]['result']['structuredContent']['features'][0]['feature'] == 'status'
        assert set(observed[2]['result']['structuredContent']['input_schema']['properties']) == {'agent'}
        assert observed[3]['result']['isError'] is False
    else:
        # The formal gateway may disclose schemas locally; execution still
        # reaches the owner and must reject another native Session.
        assert observed[3]['result']['isError'] is True
    if host == 'main':
        assert observed[4]['result']['isError'] is False, observed[4]
        assert ('private-native-session' in json.dumps(observed[4])) is (issuer == 'thread-1')
    start = next(json.loads(line)['params'] for line in protocol.read_text().splitlines()
                 if json.loads(line).get('method') == 'thread/start')
    assert not start.get('dynamicTools')
    assert 'graphtraj' in start['config']['mcp_servers']
