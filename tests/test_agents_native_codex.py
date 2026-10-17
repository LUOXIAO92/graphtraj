"""Task-free Codex wiring through a controlled stdio peer, not real-host evidence."""

import asyncio
import json
from pathlib import Path

import pytest
import yaml

from agent_swarm import Caller
from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.interfaces.agents import agents_callback
from graphtraj.runtimes.codex.app_server import CodexAppServer, CodexServerRequest
from graphtraj.runtimes.codex.managed_session import run_native_operation
from test_codex_app_server import peer  # noqa: F401


@pytest.mark.parametrize('saving', [False, True])
def test_connection_only_role_preserves_configuration_and_archive_policy(
    tmp_path: Path, peer: Path, monkeypatch: pytest.MonkeyPatch, saving: bool,
) -> None:
    """The public agents function resolves connections and binds the chosen archive."""
    from agent_swarm import write_config, read_config
    from graphtraj.configuration import runtime_connections
    from graphtraj.interfaces.agents import swarm_root
    from graphtraj.interfaces.local_tool import bind
    from graphtraj.sessions.archive import JsonlSessionStore, archive_path
    from graphtraj.workspace import runner_project

    root = tmp_path / 'project'
    (root / '.graphtraj').mkdir(parents=True)
    (root / '.graphtraj/config.yml').write_text(default_configuration_content(root, root))
    (root / 'instructions.txt').write_text('Keep the selected role resource.')
    role = {'connection': 'configured/provider/model', 'reasoning_effort': 'medium',
            'instructions': 'instructions.txt', 'codex': {'approval': {
                'model': 'review-model', 'base_url': 'https://provider.example/v1',
                'api_key_env': 'TASK331_TEST_API_KEY',
            }}}
    roles = root / '.graphtraj/roles.yml'
    roles.write_text(yaml.safe_dump({'roles': {'worker': role}}))
    monkeypatch.setattr(runtime_connections, 'connections_file', lambda: tmp_path / 'connections.yml')
    call_settings = bind(root, recovery_reviewer=lambda proposal: {'decision': 'accept'})
    current = call_settings({'action': 'execute', 'feature': 'runtime_connections',
                             'arguments': {'action': 'read'}})
    catalog = {'version': 1, 'runtimes': {'configured': {
        'runtime': 'codex', 'home': str(tmp_path / 'native-home'),
        'providers': {'provider': {'base_url': 'https://provider.example/v1',
            'api_key_env': 'TASK331_TEST_API_KEY', 'models': {'model': {
                'id': 'actual-model', 'source': 'manual', 'supported_efforts': ['medium'],
            }}}},
    }}}
    saved = call_settings({'action': 'execute', 'feature': 'runtime_connections', 'arguments': {
        'action': 'save', 'expected_revision': current.document['revision'], 'catalog': catalog,
    }})
    assert not saved.failed, saved.document
    monkeypatch.setattr(runner_project, 'runtime_executable', lambda runtime: peer)
    monkeypatch.setenv('TASK331_TEST_API_KEY', 'controlled-value')
    monkeypatch.setenv('PEER_NATIVE_ROLLOUT', str(tmp_path / 'native-rollouts'))
    monkeypatch.setenv('PEER_CONFIGURATION_HOME', str(tmp_path / 'observed-home'))
    write_config(swarm_root(root), save_normalized_sessions=saving, backfill_history=True)
    call = agents_callback(root, Caller('controlled-native-host', 'parent'), root)
    created = call({'action': 'create', 'runtime': 'codex', 'instruction': 'configuration'})
    assert not created.failed, created.document
    done = call({'action': 'wait', 'agent': created.document['agent'], 'timeout_seconds': 10})
    assert not done.failed, done.document
    assert (tmp_path / 'observed-home').read_text() == str(tmp_path / 'native-home')
    observed = json.loads(done.document['result']['last_result']['last_message'])
    assert observed['model'] == 'actual-model'
    assert observed['config']['model_reasoning_effort'] == 'medium'
    assert 'Keep the selected role resource.' in observed['developerInstructions']
    provider = observed['config']['model_providers']['graphtraj-role']
    assert provider['base_url'] == 'https://provider.example/v1'
    assert provider['env_key'] == 'TASK331_TEST_API_KEY'
    assert not provider['requires_openai_auth']
    path = archive_path(swarm_root(root), 'codex:' + created.document['session'])
    assert path.exists() is saving
    if saving:
        assert JsonlSessionStore(path).header['graphtraj']['agentId'] == created.document['agent']
    assert read_config(swarm_root(root))['backfill_history'] is True
    assert read_config(swarm_root(root))['save_normalized_sessions'] is saving

    removed = call_settings({'action': 'execute', 'feature': 'runtime_connections', 'arguments': {
        'action': 'save', 'expected_revision': saved.document['revision'],
        'catalog': {'version': 1, 'runtimes': {}},
    }})
    assert not removed.failed, removed.document
    resumed = call({'action': 'resume', 'agent': created.document['agent'], 'message': 'configuration'})
    assert not resumed.failed and resumed.document['session'] == created.document['session']
    done = call({'action': 'wait', 'agent': created.document['agent'], 'timeout_seconds': 10})
    assert json.loads(done.document['result']['last_result']['last_message'])['model'] == 'actual-model'
    assert (tmp_path / 'observed-home').read_text() == str(tmp_path / 'native-home')
    restored = call_settings({'action': 'execute', 'feature': 'runtime_connections', 'arguments': {
        'action': 'save', 'expected_revision': removed.document['revision'], 'catalog': catalog,
    }})
    assert not restored.failed, restored.document

    roles.write_text(yaml.safe_dump({'roles': {'first': role, 'second': role}}))
    ambiguous = call({'action': 'create', 'runtime': 'codex', 'instruction': 'must not launch'})
    assert ambiguous.failed and ambiguous.document['error']['code'] == 'invalid-config'
    assert all(name in ambiguous.document['error']['message'] for name in ('first', 'second'))


def test_owned_gateway_exposes_agents_without_granting_native_helpers_control(
    tmp_path: Path, peer: Path,
) -> None:
    """The registered gateway feature shares the owned function's caller boundary."""
    (tmp_path / '.graphtraj').mkdir()
    (tmp_path / '.graphtraj/config.yml').write_text(default_configuration_content(tmp_path, tmp_path))

    async def exercise() -> None:
        """Route the same public request with native owner and helper issuers."""
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path, environment={
            'PEER_THREAD_PARENTS': json.dumps({'helper': 'owner'}),
        }) as adapter:
            for thread, allowed in [('owner', True), ('helper', False)]:
                response = await run_native_operation(adapter, 'owner', 'agent-owner', tmp_path,
                    CodexServerRequest(thread, 'item/tool/call', {'threadId': thread, 'tool': 'graphtraj',
                        'arguments': {'action': 'execute', 'feature': 'agents', 'arguments': {'action': 'status'}}}))
                assert response['success'] is allowed, response
                if allowed:
                    assert json.loads(response['contentItems'][0]['text'])['result']['agents'] == []

    asyncio.run(exercise())


def test_independent_codex_lifecycle_and_callback_cwd(
    tmp_path: Path, peer: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create, steer, stop and resume without a Task mapping or Worker environment."""
    from graphtraj.workspace import runner_project

    root = tmp_path / 'project'
    cwd = root / 'scratch'
    cwd.mkdir(parents=True)
    (root / '.graphtraj').mkdir()
    (root / '.graphtraj/config.yml').write_text(default_configuration_content(root, root))
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'codex': {'runtime': 'codex', 'model': 'fixture-model'}},
        'role_tree': {'codex': {}},
    }))
    monkeypatch.setattr(runner_project, 'runtime_executable', lambda runtime: peer)
    protocol = tmp_path / 'protocol.jsonl'
    monkeypatch.setenv('PEER_PROTOCOL_LOG', str(protocol))
    monkeypatch.setenv('PEER_NATIVE_ROLLOUT', str(tmp_path / 'native'))

    async def create() -> dict:
        """Use the actual dynamic callback with a separate host working directory."""
        async with CodexAppServer(command=[str(peer)], cwd=cwd) as adapter:
            response = await run_native_operation(
                adapter, 'owner', 'agent-owner', root,
                CodexServerRequest(1, 'item/tool/call', {
                    'threadId': 'owner', 'tool': 'agents',
                    'arguments': {'action': 'create', 'runtime': 'codex', 'instruction': 'hold'},
                }), cwd=cwd,
            )
            assert response['success'], response
            return json.loads(response['contentItems'][0]['text'])

    created = asyncio.run(create())
    call = agents_callback(root, Caller('codex-dynamic-tools', 'agent-owner'), cwd)
    agent, session = created['agent'], created['session']
    assert session and created['result']['state'] == 'active'

    sent = call({'action': 'send', 'agent': agent, 'message': 'finished'})
    assert not sent.failed, sent.document
    done = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 10})
    assert done.document['result']['last_result']['last_message'] == 'finished'

    resumed = call({'action': 'resume', 'agent': agent, 'message': 'hold'})
    assert not resumed.failed and resumed.document['session'] == session, resumed.document
    assert resumed.document['execution'] != created['execution']
    stopped = call({'action': 'interrupt', 'agent': agent})
    assert not stopped.failed, stopped.document
    done = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 10})
    assert done.document['result']['last_result']['outcome'] == 'interrupted'
    assert done.document['result']['state'] == 'standby'
    status = call({'action': 'status'})
    assert not status.failed, status.document
    assert [item['agent'] for item in status.document['result']['agents']] == [agent]

    wire = [json.loads(line) for line in protocol.read_text().splitlines()]
    sessions = [item for item in wire if item.get('method') in {'thread/start', 'thread/resume'}]
    assert [item['method'] for item in sessions] == ['thread/start', 'thread/resume']
    assert all(item['params']['cwd'] == str(cwd) for item in sessions)
    assert sessions[1]['params']['threadId'] == session
    assert not (root / '.graphtraj/state/tasks').exists()

    approved = call({'action': 'resume', 'agent': agent,
                     'message': 'request:item/commandExecution/requestApproval'})
    assert not approved.failed, approved.document
    waiting = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 10})
    assert waiting.document['result']['pending_requests'] == 1
    pending = call({'action': 'requests', 'agent': agent})
    [request] = pending.document['result']['requests']
    replied = call({'action': 'reply', 'agent': agent, 'request': request,
                    'response': {'decision': 'accept'}})
    assert not replied.failed, replied.document
    done = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 10})
    assert done.document['result']['last_result']['last_message'] == 'request accepted'
    assert done.document['result']['state'] == 'standby'
