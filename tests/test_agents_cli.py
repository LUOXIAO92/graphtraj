"""CLI and MCP consume the same independent core without Task or Git state."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from agent_swarm import AgentControl, Caller, bind
from agent_swarm.connection import agents_connection
from agent_swarm.process import authenticate_process
from test_agent_control import ScriptedDriver


@pytest.mark.parametrize('surface', ['cli', 'mcp'])
def test_independent_entry_controls_same_core(tmp_path: Path, surface: str) -> None:
    """An owned process creates, reads and stops through the public bound core."""
    driver = ScriptedDriver()
    core = AgentControl(tmp_path / 'data', {'controlled': driver})
    callback = bind(core, Caller('controlled-test-host', 'existing-parent'))
    child = None
    with agents_connection(tmp_path / 'pipe', callback,
                           lambda pid: authenticate_process(child, pid)) as address:
        env = {**os.environ, 'AGENT_SWARM_CONNECTION': address,
               'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
        for key in ('GRAPHTRAJ_CLI_CONNECTION', 'DSH_SESSION_ID', 'DSH_AGENT_SOURCE'):
            env.pop(key, None)

        def request(document: dict) -> dict:
            """Exercise the installed module interface, never private control state."""
            nonlocal child
            command = [sys.executable, '-m', 'agent_swarm.' + surface]
            payload = None
            if surface == 'cli':
                command.append(json.dumps(document))
            else:
                payload = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                      'params': {'name': 'agents', 'arguments': document}}) + '\n'
            child = subprocess.Popen(command, cwd=tmp_path, env=env, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = child.communicate(payload, timeout=10)
            assert child.returncode == 0, stderr or stdout
            result = json.loads(stdout)
            if surface == 'mcp':
                assert not result['result']['isError'], result
                result = result['result']['structuredContent']
            assert 'error' not in result, result
            return result

        described = request({'action': 'describe', 'feature': 'status'})
        assert set(described['input_schema']['properties']) == {'agent'}
        created = request({'action': 'execute', 'feature': 'create', 'arguments': {
            'runtime': 'controlled', 'instruction': 'remember this controlled input'}})
        agent = created['agent']
        try:
            status = request({'action': 'execute', 'feature': 'status', 'arguments': {'agent': agent}})
            assert status['result']['state'] == 'active'
            assert callback({'action': 'status', 'agent': agent}).document == status
            request({'action': 'execute', 'feature': 'interrupt', 'arguments': {'agent': agent}})
            ended = request({'action': 'execute', 'feature': 'wait',
                             'arguments': {'agent': agent, 'timeout_seconds': 5}})
            assert ended['result']['state'] == 'standby'
            assert ended['session'] == status['session']
        finally:
            callback({'action': 'interrupt', 'agent': agent})
        assert not (tmp_path / '.graphtraj').exists()
        assert not (tmp_path / '.git').exists()


def test_cli_does_not_adopt_graphtraj_owner(tmp_path: Path) -> None:
    """An inherited Task channel cannot supply an independent caller implicitly."""
    env = {**os.environ, 'GRAPHTRAJ_CLI_CONNECTION': '/unrelated/task/owner',
           'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
    env.pop('AGENT_SWARM_CONNECTION', None)
    result = subprocess.run([sys.executable, '-m', 'agent_swarm.cli',
                             '{"action":"execute","feature":"status","arguments":{}}'],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert json.loads(result.stdout)['error']['code'] == 'authority-denied'
