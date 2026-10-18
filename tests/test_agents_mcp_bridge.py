"""Independent MCP uses the existing file transport and real kernel caller proof."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from agent_swarm import AgentsError, AgentsResult
from agent_swarm.connection import agents_connection
from agent_swarm.process import authenticate_process


def exchange(process: subprocess.Popen, document: dict) -> dict:
    """Send one MCP protocol request to a controlled local Python process."""
    process.stdin.write(json.dumps(document) + '\n')
    process.stdin.flush()
    return json.loads(process.stdout.readline())


def test_mcp_bridge_verifies_process_and_projects_selected_schema(tmp_path: Path) -> None:
    """An allowed MCP descendant reaches only its bound callback, never supplied identity."""
    calls = []
    child = None

    def call(request: dict) -> AgentsResult:
        """Stand in for the existing host-bound business callback only."""
        calls.append(request)
        return AgentsResult({'action': request['action'], 'result': {'seen': 'bound-agent'}})

    with agents_connection(tmp_path, call, lambda pid: authenticate_process(child, pid)) as address:
        env = {**os.environ, 'AGENT_SWARM_CONNECTION': address,
               'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
        env.pop('GRAPHTRAJ_CLI_CONNECTION', None)
        child = subprocess.Popen([sys.executable, '-m', 'agent_swarm.mcp'], env=env,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True)
        try:
            listed = exchange(child, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
            assert [tool['name'] for tool in listed['result']['tools']] == ['agents']
            assert 'runtime' not in listed['result']['tools'][0]['inputSchema']['properties']
            for feature in ('create', 'status'):
                described = exchange(child, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                    'params': {'name': 'agents', 'arguments': {'action': 'describe', 'feature': feature}}})
                schema = described['result']['structuredContent']['input_schema']
                assert ('runtime' in schema['properties']) == (feature == 'create')
            assert calls == []
            response = exchange(child, {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                'params': {'name': 'agents', 'arguments': {'action': 'execute', 'feature': 'status', 'arguments': {}}}})
            assert response['result']['structuredContent']['result']['seen'] == 'bound-agent'
            assert calls == [{'action': 'status'}]
            rejected = exchange(child, {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call',
                'params': {'name': 'agents', 'arguments': {'action': 'execute', 'feature': 'status',
                                                         'arguments': {'caller': 'other'}}}})
            assert rejected['result']['isError']
            assert calls == [{'action': 'status'}]
            # Same channel path does not authorize a sibling process.
            attacker = subprocess.run([sys.executable, '-m', 'agent_swarm.mcp'], env=env, text=True,
                input=json.dumps({'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call',
                    'params': {'name': 'agents', 'arguments': {'action': 'execute', 'feature': 'status', 'arguments': {}}}})+'\n',
                capture_output=True, check=True, timeout=10)
            assert json.loads(attacker.stdout)['result']['structuredContent']['error']['code'] == 'authority-denied'
            assert calls == [{'action': 'status'}]
        finally:
            child.stdin.close()
            child.wait(timeout=10)
        with pytest.raises(AgentsError, match='live native process'):
            authenticate_process(child, child.pid)
    assert not Path(address).exists()


@pytest.mark.parametrize('case', ['match', 'wrong-session', 'child', 'unknown', 'wrong-cwd', 'both-connections', 'empty-independent'])
def test_dsh_native_assertions_constrain_the_existing_bound_caller(tmp_path: Path, case: str) -> None:
    """Native environment never chooses identity or bypasses the owned-process check."""
    calls = []
    child = None
    expected = {'runtime': 'dsh', 'session': 'verified-native-session', 'source': 'main',
                'cwd': str(tmp_path)}

    def call(request: dict) -> AgentsResult:
        """Native source main still reaches this already-bound child identity."""
        calls.append(request)
        return AgentsResult({'result': {'bound_agent': 'actual-child'}})

    with agents_connection(tmp_path / 'channel', call, lambda pid: authenticate_process(child, pid),
                           native_context=lambda: expected) as address:
        env = {**os.environ, 'AGENT_SWARM_CONNECTION': address,
               'DSH_SESSION_ID': expected['session'], 'DSH_AGENT_SOURCE': expected['source'],
               'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
        env.pop('GRAPHTRAJ_CLI_CONNECTION', None)
        if case == 'wrong-session':
            env['DSH_SESSION_ID'] = 'another-session'
        if case in {'child', 'unknown'}:
            env['DSH_AGENT_SOURCE'] = case
        if case in {'both-connections', 'empty-independent'}:
            env['GRAPHTRAJ_CLI_CONNECTION'] = '/unrelated-parent-channel'
            if case == 'empty-independent':
                env['AGENT_SWARM_CONNECTION'] = ''
        child = subprocess.Popen([sys.executable, '-m', 'agent_swarm.mcp'], env=env,
                                 cwd=tmp_path.parent if case == 'wrong-cwd' else tmp_path,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            result = exchange(child, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                'params': {'name': 'agents', 'arguments': {'action': 'execute', 'feature': 'status', 'arguments': {}}}})['result']
            if case == 'match':
                assert result['structuredContent']['result']['bound_agent'] == 'actual-child'
                assert calls == [{'action': 'status'}]
            else:
                assert result['isError']
                assert result['structuredContent']['error']['code'] == 'authority-denied'
                assert calls == []
        finally:
            child.stdin.close()
            child.wait(timeout=10)


def test_codex_metadata_uses_the_shared_owner_connection(tmp_path: Path) -> None:
    """Request metadata constrains the bound caller even with a different env locator."""
    calls = []
    child = None
    expected = {'runtime': 'codex', 'session': 'verified-codex-session', 'cwd': str(tmp_path)}

    def call(request: dict) -> AgentsResult:
        """Record requests that passed both process and native Session verification."""
        calls.append(request)
        return AgentsResult({'result': {'bound_agent': 'actual-child'}})

    with agents_connection(tmp_path / 'channel', call, lambda pid: authenticate_process(child, pid),
                           native_context=lambda: expected) as address:
        env = {**os.environ, 'AGENT_SWARM_CONNECTION': address,
               'GRAPHTRAJ_NATIVE_RUNTIME': 'codex', 'CODEX_THREAD_ID': 'other-session',
               'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
        for name in ('GRAPHTRAJ_CLI_CONNECTION', 'DSH_SESSION_ID', 'DSH_AGENT_SOURCE'):
            env.pop(name, None)
        child = subprocess.Popen([sys.executable, '-m', 'agent_swarm.mcp'], env=env, cwd=tmp_path,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            for session in (expected['session'], 'forged-session'):
                result = exchange(child, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                    'params': {'name': 'agents', '_meta': {'threadId': session},
                               'arguments': {'action': 'execute', 'feature': 'status', 'arguments': {}}}})['result']
                assert result['isError'] is (session != expected['session'])
                if result['isError']:
                    assert result['structuredContent']['error']['code'] == 'authority-denied'
            assert calls == [{'action': 'status'}]
        finally:
            child.stdin.close()
            child.wait(timeout=10)
