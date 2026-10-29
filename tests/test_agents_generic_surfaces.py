"""Generic agents interfaces that replaced GraphTraj-only surfaces (388)."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from agent_swarm import AgentControl, Caller, bind
from agent_swarm.codex.app_server import CodexAppServer
from agent_swarm.codex.context import CodexAdapterError
from agent_swarm.connection import agents_connection
from agent_swarm.discovery import handle_request
from agent_swarm.pi.session import session_source
from agent_swarm.process import authenticate_process
from agent_swarm.tool import INPUT_SCHEMA
from graphtraj.execution.runner_models import RunnerError
from graphtraj.interfaces.hosted_cli import forward_request
from graphtraj.runtimes.pi import session_entry
from test_agent_control import ScriptedDriver
from test_codex_app_server import peer  # noqa: F401

SOURCE = Path(__file__).resolve().parents[1] / 'src'

MAIN = {'id': 'parent', 'model': 'same', 'modelProvider': 'same', 'configuration': {
    'sandbox': {'type': 'workspaceWrite', 'writableRoots': [], 'networkAccess': False},
    'activePermissionProfile': {'id': ':workspace', 'extends': None},
}}
WIDENED = {'type': 'workspaceWrite', 'writableRoots': [], 'networkAccess': True}


def fork(tmp_path: Path, peer: Path, reported: dict, **options) -> dict:
    """Fork MAIN through the public method; return the native request it sent."""
    sent = tmp_path / 'fork.json'

    async def exercise() -> None:
        """Run one owned connection against the external peer."""
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path, environment={
            'PEER_FORK_RESULT': json.dumps(reported), 'PEER_FORK_PARAMS': str(sent),
        }) as adapter:
            await adapter.fork_session(MAIN, **options)

    asyncio.run(exercise())
    return json.loads(sent.read_text())


def test_fork_uses_the_callers_network_profile_and_socket(tmp_path: Path, peer: Path) -> None:
    """The caller names the extending profile; only networkAccess may then differ."""
    sent = fork(tmp_path, peer, {'sandbox': WIDENED, 'activePermissionProfile': {
        'id': 'caller_profile', 'extends': ':workspace'}},
        network_profile='caller_profile', unix_socket='/run/owner.sock')
    assert sent['permissions'] == 'caller_profile' and 'sandbox' not in sent
    assert sent['config']['permissions.caller_profile'] == {
        'extends': ':workspace', 'network': {'enabled': True, 'unix_sockets': {'/run/owner.sock': 'allow'}},
    }


def test_fork_without_a_network_profile_selects_mains_own(tmp_path: Path, peer: Path) -> None:
    """No caller profile: Main's profile is selected and no override is sent."""
    sent = fork(tmp_path, peer, {'sandbox': MAIN['configuration']['sandbox'],
                                 'activePermissionProfile': {'id': ':workspace', 'extends': None}})
    assert sent['permissions'] == ':workspace' and 'config' not in sent


@pytest.mark.parametrize(('options', 'reported', 'reason'), [
    # Without the caller's profile, managed network is not an accepted difference.
    ({}, {'sandbox': WIDENED, 'activePermissionProfile': {'id': ':workspace'}}, 'sandbox'),
    # With it, any other sandbox difference still fails.
    ({'network_profile': 'caller_profile', 'unix_socket': '/run/owner.sock'},
     {'sandbox': {**WIDENED, 'writableRoots': ['/elsewhere']},
      'activePermissionProfile': {'id': 'caller_profile'}}, 'sandbox'),
    ({'network_profile': 'caller_profile', 'unix_socket': '/run/owner.sock'},
     {'sandbox': WIDENED, 'activePermissionProfile': {'id': ':workspace'}}, 'permission profile'),
    ({'network_profile': 'caller_profile', 'unix_socket': '/run/owner.sock'},
     {'sandbox': WIDENED, 'activePermissionProfile': {'id': 'caller_profile'}, 'model': 'other'}, 'model'),
])
def test_fork_checks_stay_strict(tmp_path: Path, peer: Path, options: dict, reported: dict, reason: str) -> None:
    """A fork reporting anything beyond the authorized difference is refused."""
    with pytest.raises(CodexAdapterError, match=reason):
        fork(tmp_path, peer, reported, **options)


def test_fork_requires_profile_and_socket_together(tmp_path: Path) -> None:
    """Half of the network override is a request error before any native call."""
    for options in ({'network_profile': 'caller_profile'}, {'unix_socket': '/run/owner.sock'}):
        with pytest.raises(CodexAdapterError) as rejected:
            asyncio.run(CodexAppServer(command=['unused'], cwd=tmp_path).fork_session(MAIN, **options))
        assert rejected.value.code == 'RUNTIME_REQUEST_INVALID'


def test_pi_child_marker_is_supplied_by_the_caller() -> None:
    """agents knows no marker name; GraphTraj passes its completion checker type."""
    header = {'type': 'session', 'version': 3, 'id': 'fork', 'cwd': '/project'}
    entries = [{'type': 'custom', 'customType': 'host:checker', 'data': {'session': 'fork'}}]
    assert session_source(header, entries, {}) == 'main'
    assert session_source(header, entries, {}, ('host:checker',)) == 'child'
    copied = [{'type': 'custom', 'customType': 'host:checker', 'data': {'session': 'other'}}]
    assert session_source(header, copied, {}, ('host:checker',)) == 'main'

    checker = [{'type': 'custom', 'customType': 'graphtraj:completion-checker', 'data': {'session': 'fork'}}]
    assert session_source(header, checker, {}) == 'main'
    assert session_entry.session_source(header, checker, {}) == 'child'


def test_agents_entry_ignores_a_graphtraj_connection(tmp_path: Path) -> None:
    """agents uses its own connection; another host's variable is not its concern."""
    calls = []
    child = None
    core = AgentControl(tmp_path / 'data', {'controlled': ScriptedDriver()})
    callback = bind(core, Caller('controlled-test-host', None))

    def call(request: dict):
        """Record requests that reached this owner."""
        calls.append(request)
        return callback(request)

    with agents_connection(tmp_path / 'pipe', call, lambda pid: authenticate_process(child, pid)) as address:
        env = {**os.environ, 'AGENT_SWARM_CONNECTION': address,
               'GRAPHTRAJ_CLI_CONNECTION': '/unrelated/other-host', 'PYTHONPATH': str(SOURCE)}
        for surface in ('cli', 'mcp'):
            command = [sys.executable, '-m', 'agent_swarm.' + surface]
            request = {'action': 'execute', 'feature': 'status', 'arguments': {}}
            payload = None
            if surface == 'cli':
                command.append(json.dumps(request))
            else:
                payload = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                      'params': {'name': 'agents', 'arguments': request}}) + '\n'
            child = subprocess.Popen(command, cwd=tmp_path, env=env, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = child.communicate(payload, timeout=10)
            assert child.returncode == 0, stderr or stdout
    assert calls == [{'action': 'status'}, {'action': 'status'}]


def test_graphtraj_forwarding_refuses_both_connections(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GraphTraj, not agents, refuses a process carrying both owners' connections."""
    monkeypatch.setenv('GRAPHTRAJ_CLI_CONNECTION', str(tmp_path / 'graphtraj-host'))
    monkeypatch.setenv('AGENT_SWARM_CONNECTION', str(tmp_path / 'agents-host'))
    with pytest.raises(RunnerError) as rejected:
        forward_request({'action': 'execute', 'feature': 'agents', 'arguments': {}}, tmp_path)
    assert rejected.value.code == 'authority-denied'


PI_START = '''
import { pathToFileURL } from 'node:url';
const module = await import(pathToFileURL(process.argv[1]).href);
const handlers = {};
const registered = [];
const pi = {
  registerFlag() {}, getFlag: name => process.env.FLAG_AGENTS_CONFIG && name === 'agents-config'
    ? process.env.FLAG_AGENTS_CONFIG : undefined,
  on: (kind, handler) => { handlers[kind] = handler; },
  registerMcpServer: name => registered.push(name),
};
const ctx = {hasUI: false, cwd: process.cwd(), sessionManager: {}};
try {
  if (process.argv[2] === 'agents') console.log(JSON.stringify({owned: await module.registerAgents(pi).start(ctx), registered}));
  else { module.default(pi); await handlers.session_start({reason: 'startup'}, ctx); console.log(JSON.stringify({registered})); }
} catch (error) { console.log(JSON.stringify({error: error.message})); }
'''


def start_pi(tmp_path: Path, module: str, entry: str, **environment: str) -> dict:
    """Start one Pi Session through an extension's session_start, without Pi itself."""
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required')
    env = {key: value for key, value in os.environ.items()
           if key not in {'AGENT_SWARM_CONNECTION', 'GRAPHTRAJ_CLI_CONNECTION', 'DSH_SESSION_ID', 'DSH_AGENT_SOURCE'}}
    result = subprocess.run([node, '--input-type=module', '-e', PI_START, str(SOURCE / module), entry],
                            cwd=tmp_path, env={**env, **environment}, capture_output=True, text=True,
                            check=True, timeout=20)
    return json.loads(result.stdout)


def test_pi_exclusion_moved_to_the_graphtraj_extension(tmp_path: Path) -> None:
    """agents' Pi entry adopts its own connection; GraphTraj's refuses mixing owners."""
    both = {'AGENT_SWARM_CONNECTION': '/agents-host', 'GRAPHTRAJ_CLI_CONNECTION': '/graphtraj-host',
            'AGENT_SWARM_PYTHON': sys.executable}
    assert start_pi(tmp_path, 'agent_swarm/pi/extension.mjs', 'agents', **both) == {
        'owned': True, 'registered': ['agents']}
    refused = start_pi(tmp_path, 'graphtraj/runtimes/pi/extension.mjs', 'graphtraj', **both)
    assert refused['error'].startswith('Conflicting existing Agent connections')
    refused = start_pi(tmp_path, 'graphtraj/runtimes/pi/extension.mjs', 'graphtraj',
                       GRAPHTRAJ_CLI_CONNECTION='/graphtraj-host', FLAG_AGENTS_CONFIG='/config.json')
    assert refused['error'].startswith('Standalone agents config cannot replace')


def test_reports_only_is_generic_and_the_core_refuses_it(tmp_path: Path) -> None:
    """The core cannot keep an Agent to held results, so it says so instead of starting work."""
    description = INPUT_SCHEMA['properties']['reports_only']['description']
    assert 'Task' not in description and 'not-implemented' in description

    core = AgentControl(tmp_path / 'data', {'controlled': ScriptedDriver()})
    call = bind(core, Caller('controlled-test-host', None))
    agent = call({'action': 'create', 'runtime': 'controlled', 'instruction': 'first'}).document['agent']
    call({'action': 'interrupt', 'agent': agent})
    assert call({'action': 'wait', 'agent': agent, 'timeout_seconds': 5}).document['result']['state'] == 'standby'

    refused = call({'action': 'send', 'agent': agent, 'message': 'reports?', 'reports_only': True})
    assert refused.failed and refused.document['error']['code'] == 'not-implemented'
    assert call({'action': 'status', 'agent': agent}).document['result']['state'] == 'standby'
    sent = call({'action': 'send', 'agent': agent, 'message': 'continue', 'reports_only': False})
    assert not sent.failed and sent.document['result']['state'] == 'active'
    call({'action': 'interrupt', 'agent': agent})


@pytest.mark.parametrize('request_document', [
    {'action': 'discover', 'feature': 'send'},
    {'action': 'describe', 'feature': 'unknown'},
    {'action': 'describe'},
    {'action': 'execute', 'feature': 'send', 'arguments': {'agent': 'a'}},
    {'action': 'execute', 'feature': 'status'},
])
def test_envelope_errors_are_coded(request_document: dict) -> None:
    """discover, describe and execute reject envelopes with the shared error structure."""
    result = handle_request(request_document, lambda request: pytest.fail('callback reached'))
    assert result.failed
    assert result.document['action'] == request_document['action']
    assert result.document['error']['code'] == 'invalid-input'
    assert result.document['error']['message']
