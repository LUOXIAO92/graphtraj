"""Independent MCP uses the existing file transport and real kernel caller proof."""
from __future__ import annotations

import ast
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import agent_swarm
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


def test_independent_tool_runs_with_graphtraj_imports_blocked(tmp_path: Path) -> None:
    """agents never imports GraphTraj at import time, in any subpackage, even with a GraphTraj host variable."""
    probe = tmp_path / 'probe.py'
    probe.write_text('''
import importlib, io, json, pkgutil, sys

class Block:
    """Refuse every GraphTraj import for this process."""
    def find_spec(self, name, path=None, target=None):
        if name == 'graphtraj' or name.startswith('graphtraj.'):
            raise ImportError('GraphTraj import blocked: ' + name)

sys.meta_path.insert(0, Block())
import agent_swarm
def unimportable(name):
    raise ImportError('Cannot walk ' + name)

# Every module of every subpackage, not only the top level; walk_packages
# would otherwise skip a subpackage whose import fails.
for module in pkgutil.walk_packages(agent_swarm.__path__, 'agent_swarm.', onerror=unimportable):
    importlib.import_module(module.name)
from agent_swarm import mcp
sys.stdin = io.StringIO(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}) + '\\n')
mcp.main()
''')
    env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src'),
           'GRAPHTRAJ_CLI_CONNECTION': str(tmp_path / 'absent-host')}
    env.pop('AGENT_SWARM_CONNECTION', None)
    result = subprocess.run([sys.executable, str(probe)], env=env, text=True,
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert [tool['name'] for tool in json.loads(result.stdout)['result']['tools']] == ['agents']


def graphtraj_imports(source: str) -> list[int]:
    """Return the lines of one module that import GraphTraj, wherever they run.

    Covers module, function-local and conditional ``import``/``from`` statements
    and literal ``importlib.import_module``/``__import__`` names, none of which
    an import-time probe sees until that code runs.
    """
    def graphtraj(name: object) -> bool:
        """Match the graphtraj package and its submodules, not similar names."""
        return isinstance(name, str) and (name == 'graphtraj' or name.startswith('graphtraj.'))

    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import) and any(graphtraj(alias.name) for alias in node.names):
            lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and graphtraj(node.module):
            lines.append(node.lineno)
        elif (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant)
              and graphtraj(node.args[0].value)
              and (isinstance(node.func, ast.Name) and node.func.id in {'__import__', 'import_module'}
                   or isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module')):
            lines.append(node.lineno)
    return lines


def test_no_agent_swarm_module_imports_graphtraj() -> None:
    """No module in agent_swarm or any of its subpackages names a GraphTraj import."""
    package = Path(agent_swarm.__file__).parent
    modules = sorted(package.rglob('*.py'))
    assert {'claude', 'codex', 'dsh', 'pi', 'sessions'} <= {path.parent.name for path in modules}
    found = [f'{path.relative_to(package.parent)}:{line}' for path in modules
             for line in graphtraj_imports(path.read_text(encoding='utf-8'))]
    assert found == []


def test_graphtraj_import_scan_sees_hidden_forms() -> None:
    """The scan reports the forms an import-time probe misses, and nothing else."""
    hidden = """
def later():
    import graphtraj.tasks
    from graphtraj import interfaces
    importlib.import_module('graphtraj.runtimes')
    __import__('graphtraj')
from . import graphtraj_named_sibling
import graphtrajectory
"""
    assert graphtraj_imports(hidden) == [3, 4, 5, 6]


def test_mcp_server_version_is_the_single_package_version(tmp_path: Path) -> None:
    """MCP serverInfo reports agent_swarm.__version__, which the installed metadata matches."""
    env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
    env.pop('AGENT_SWARM_CONNECTION', None)
    result = subprocess.run([sys.executable, '-m', 'agent_swarm.mcp'], env=env, text=True,
                            input=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                                              'params': {}}) + '\n',
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    server = json.loads(result.stdout)['result']['serverInfo']
    assert server == {'name': 'agents', 'version': agent_swarm.__version__}
    assert agent_swarm.__version__ == version('agent-swarm')
    plugin = json.loads((Path(agent_swarm.__file__).parent / 'dsh' / 'package.json').read_text())
    assert plugin['version'] == agent_swarm.__version__
