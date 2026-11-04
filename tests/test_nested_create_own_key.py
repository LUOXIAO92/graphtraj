"""A child Agent's create of a grandchild on its own connection (Task 440).

A child's create runs in the owner that launched the child. The grandchild gets the
key the child's own connection uses; a key the child does not hold is refused unless
the user's own configuration declares it. All key values here are fake.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from graftling import AgentControl, AgentsResult, Caller, bind
from graftling.child_env import is_credential_name
from graftling.connection import agents_connection
from graftling.discovery import handle_request
from graftling.dsh.execution import DshExecution
from graftling.process import authenticate_process

OWN, OTHER = 'CHILD_OWN_KEY', 'OTHER_CONN_KEY'

CONFIG = f'''connections:
  own-dsh:
    runtime: dsh
    api_key_env: {OWN}
  other-dsh:
    runtime: dsh
    api_key_env: {OTHER}
  own-pi:
    runtime: pi
    api_key_env: {OWN}
  other-pi:
    runtime: pi
    api_key_env: {OTHER}
presets:
  own-dsh:
    connection: own-dsh
  other-dsh:
    connection: other-dsh
  own-pi:
    connection: own-pi
  other-pi:
    connection: other-pi
'''


@pytest.fixture(autouse=True)
def fake_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hold only fake keys, whatever the running shell exports."""
    for name in tuple(os.environ):
        if is_credential_name(name):
            monkeypatch.delenv(name)
    monkeypatch.setenv(OWN, 'fake-own')
    monkeypatch.setenv(OTHER, 'fake-other')


class RecordingDriver:
    """Return the selected connection's key as a real driver does; start nothing."""

    def __init__(self) -> None:
        """Start with no launches."""
        self.started: list[dict] = []
        self.lock = threading.Lock()

    def prepare(self, runtime: str, caller: Caller, *, selection=None, workspace=None) -> dict:
        """Name the connection's key, as the DSH and Pi drivers do."""
        return {'api_key_env': ((selection or {}).get('settings') or {}).get('api_key_env')}

    def start(self, run) -> None:
        """Keep the settings and leave the execution running so it can create."""
        with self.lock:
            self.started.append(dict(run.settings))


def control(tmp_path: Path, config: str = CONFIG) -> AgentControl:
    """A control with both Runtimes on the recording driver."""
    (tmp_path / 'config.yml').write_text(config)
    driver = RecordingDriver()
    return AgentControl(tmp_path, {'dsh': driver, 'pi': driver})


def create(agents: AgentControl, caller: Caller, runtime: str, preset: str) -> AgentsResult:
    """One create through the public tool."""
    return bind(agents, caller)({'action': 'create', 'runtime': runtime, 'instruction': 'pwd', 'preset': preset})


def child(agents: AgentControl, runtime: str, config: str = 'own') -> Caller:
    """Create a child from the host and return the caller its own agents tool has."""
    created = create(agents, Caller('h', None), runtime, f'{config}-{runtime}')
    assert not created.failed, created.document
    return Caller('runtime-mcp', created.document['agent'], session='s', runtime=runtime)


# --- DSH: the child's agents tool reaches its own owner --------------------------------------


def test_a_graphtraj_dsh_childs_tool_uses_the_channel_it_is_bound_to() -> None:
    """GraphTraj's DSH child launches the entry that reads GRAFTLING_CONNECTION.

    Before 440 it kept GraphTraj's own entry, which reads only GRAPHTRAJ_CLI_CONNECTION
    and so ran the create inside its MCP server: as the member, in an environment DSH's
    MCP client strips of every credential name, failing RUNTIME_CREDENTIAL_MISSING.
    """
    from graphtraj.runtimes.dsh.driver import bind_agents

    turn = SimpleNamespace(request={'mcp': {'command': sys.executable, 'args': ['-I', '-m', 'graphtraj.interfaces.mcp']}},
                           archive=None)
    run = SimpleNamespace(call=lambda request: None, settings={}, archive=None, agent='agent-x',
                          events=SimpleNamespace(receive_children=lambda receive: None))
    bind_agents(turn, run, SimpleNamespace(root=Path('.')))

    assert turn.connection_env == 'GRAFTLING_CONNECTION'
    assert turn.request['mcp']['args'] == ['-I', '-m', 'graftling.mcp']
    assert Path(turn.request['mcp']['command']).is_absolute()


def test_the_entry_runs_the_create_in_the_owner_holding_the_childs_key(tmp_path: Path) -> None:
    """The MCP server holds no key; the create it forwards runs where the child's key is."""
    seen = {}
    server = None

    def call(request: dict) -> AgentsResult:
        """Record where the create is served."""
        seen.update(pid=os.getpid(), action=request.get('action'), key=os.environ.get(OWN) == 'fake-own')
        return AgentsResult({'action': request.get('action'), 'result': {}})

    messages = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'agents', 'arguments': {
            'action': 'execute', 'feature': 'create', 'arguments': {'runtime': 'dsh', 'instruction': 'pwd'}}}},
    ]
    # What DSH's MCP client leaves a stdio server: no credential-class name at all.
    environment = {'PATH': os.environ['PATH'], 'HOME': os.environ['HOME'],
                   'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
    with agents_connection(tmp_path / 'channel', call, lambda pid: authenticate_process(server, pid)) as address:
        server = subprocess.Popen([sys.executable, '-I', '-m', 'graftling.mcp'],
                                  env={**environment, 'GRAFTLING_CONNECTION': address}, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        output, errors = server.communicate(''.join(json.dumps(m) + '\n' for m in messages), timeout=30)

    replies = [json.loads(line) for line in output.splitlines() if line.strip()]
    assert replies[-1]['result']['isError'] is False, errors[-400:]
    assert seen == {'pid': os.getpid(), 'action': 'create', 'key': True}


def test_a_dsh_grandchild_on_the_childs_connection_gets_exactly_that_key(tmp_path: Path) -> None:
    """The create is allowed, and the grandchild's launch holds the child's key and no other."""
    agents = control(tmp_path)
    caller = child(agents, 'dsh')
    created = create(agents, caller, 'dsh', 'own-dsh')
    assert not created.failed, created.document
    assert agents.registration(created.document['agent'])['parent'] == caller.agent

    settings = agents.drivers['dsh'].started[-1]
    request = {'executable': 'dsh', 'package': str(tmp_path / 'package.json'), 'worktree_path': str(tmp_path),
               'provider': 'deepseek-official', 'model': 'deepseek-flash', 'reasoning_effort': None,
               'sandbox': 'read-only', 'instructions': '', **settings}
    environment = DshExecution(request, 'unused', tmp_path, lambda *a: None, lambda *a: None,
                               tmp_path / 'trace.jsonl', None).prepare_launch()
    assert sorted(name for name in environment if is_credential_name(name)) == [OWN]


# --- Pi: a child's agents tool offers create, on its own connection ---------------------------


def test_any_agents_caller_is_offered_create() -> None:
    """Discovery does not depend on who calls, so a Pi child and its grandchild both see create."""
    for query in (None, 'create', 'start a child'):
        request = {'action': 'discover', **({'query': query} if query else {})}
        found = handle_request(request, lambda request: AgentsResult({}))
        assert 'create' in [item['feature'] for item in found.document['features']], query


def test_a_pi_grandchild_on_the_childs_connection_gets_that_key(tmp_path: Path) -> None:
    """A Pi child's create on its own connection starts a grandchild naming the child's key."""
    agents = control(tmp_path)
    caller = child(agents, 'pi')
    created = create(agents, caller, 'pi', 'own-pi')
    assert not created.failed, created.document
    assert agents.drivers['pi'].started[-1]['api_key_env'] == OWN
    assert agents.registration(created.document['agent'])['parent'] == caller.agent


# --- A key the child does not hold ------------------------------------------------------------


@pytest.mark.parametrize('runtime', ['dsh', 'pi'])
def test_a_key_the_child_does_not_hold_is_refused(tmp_path: Path, runtime: str) -> None:
    """The refusal names the key and tells the user where to allow it; nothing starts."""
    agents = control(tmp_path)
    caller = child(agents, runtime)
    started = len(agents.drivers[runtime].started)
    refused = create(agents, caller, runtime, f'other-{runtime}')

    assert refused.failed
    error = refused.document['error']
    assert error['code'] == 'authority-denied'
    assert OTHER in error['message'] and 'pass_env' in error['message']
    assert 'your own configuration' in error['message']
    assert 'fake-' not in json.dumps(refused.document)
    assert len(agents.drivers[runtime].started) == started


@pytest.mark.parametrize('runtime', ['dsh', 'pi'])
def test_the_users_declaration_allows_it(tmp_path: Path, runtime: str) -> None:
    """Declaring the key on the child's connection lets the child pass it on."""
    declared = CONFIG.replace(f'  own-{runtime}:\n    runtime: {runtime}\n    api_key_env: {OWN}\n',
                              f'  own-{runtime}:\n    runtime: {runtime}\n    api_key_env: {OWN}\n'
                              f'    pass_env: [{OTHER}]\n')
    assert declared != CONFIG
    agents = control(tmp_path, declared)
    created = create(agents, child(agents, runtime), runtime, f'other-{runtime}')
    assert not created.failed, created.document
    assert agents.drivers[runtime].started[-1]['api_key_env'] == OTHER


def test_a_host_caller_is_not_checked(tmp_path: Path) -> None:
    """The host's and a Task member's own creates are unchanged: they have no Agent record."""
    agents = control(tmp_path)
    assert not create(agents, Caller('h', None), 'dsh', 'other-dsh').failed
    assert not create(agents, Caller('graphtraj-gateway', 'research@x1'), 'dsh', 'other-dsh').failed
