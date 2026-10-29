"""Task-free Codex wiring through a controlled stdio peer, not real-host evidence."""

import asyncio
import json
import os
import shutil
from pathlib import Path

import pytest
import yaml

from agent_swarm import Caller
from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.interfaces.agents import agents_callback
from graphtraj.runtimes.codex.app_server import CodexAppServer, CodexServerRequest
from test_codex_app_server import peer  # noqa: F401


@pytest.mark.parametrize('tool', ['graphtraj', 'agents', 'graphtraj_submit_report'])
def test_old_tool_callback_is_unavailable_on_same_session_resume(
    tmp_path: Path, peer: Path, monkeypatch: pytest.MonkeyPatch, tool: str,
) -> None:
    """A controlled stale native callback fails without invoking a new registration.

    This verifies current Adapter wiring, not a real historical Runtime call.
    """
    from graphtraj.workspace import runner_project

    root = tmp_path / 'project'
    (root / '.graphtraj').mkdir(parents=True)
    (root / '.graphtraj/config.yml').write_text(default_configuration_content(root, root))
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'codex': {'runtime': 'codex', 'model': 'fixture-model'}},
    }))
    monkeypatch.setattr(runner_project, 'runtime_executable', lambda runtime: peer)
    monkeypatch.setenv('PEER_NATIVE_ROLLOUT', str(tmp_path / 'native'))
    monkeypatch.setenv('PEER_REQUEST_EXCHANGE', json.dumps({
        'method': 'item/tool/call', 'params': {'tool': tool, 'arguments': {}},
        'response_success': False,
    }))
    call = agents_callback(root, Caller('controlled-native-host', 'owner'), root)
    created = call({'action': 'create', 'runtime': 'codex', 'instruction': 'first'}).document
    assert not call({'action': 'wait', 'agent': created['agent'], 'timeout_seconds': 10}).failed
    resumed = call({'action': 'resume', 'agent': created['agent'], 'message': 'configured-request'})
    assert not resumed.failed and resumed.document['session'] == created['session']
    done = call({'action': 'wait', 'agent': created['agent'], 'timeout_seconds': 10})
    assert not done.failed, done.document
    assert done.document['result']['state'] == 'standby'
    assert done.document['result']['last_result']['outcome'] == 'completed'


@pytest.mark.parametrize('saving,configuration', [
    (False, None), (True, None), (True, 'astra_coding_team.engineer'),
])
def test_connection_only_role_preserves_configuration_and_archive_policy(
    tmp_path: Path,
    peer: Path,
    monkeypatch: pytest.MonkeyPatch,
    saving: bool,
    configuration: str | None,
) -> None:
    """The public agents function resolves connections and binds the chosen archive."""
    from agent_swarm import write_config, read_config
    from graphtraj.configuration import runtime_connections
    from graphtraj.interfaces.agents import swarm_root
    from graphtraj.interfaces.local_tool import bind
    from agent_swarm.sessions.archive import JsonlSessionStore, archive_path
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
    if configuration is not None:
        roles.write_text(yaml.safe_dump({'roles': {
            'astra_coding_team': {'engineer': role},
            'other_team': {'engineer': {'runtime': 'codex', 'model': 'wrong-model'}},
            'codex': {'runtime': 'codex', 'model': 'wrong-default'},
            'claude': {'runtime': 'claude', 'model': 'wrong-runtime'},
            'unavailable': {'connection': 'missing/provider/model'},
        }}))
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
    selection = {} if configuration is None else {'configuration': configuration}
    if configuration is not None:
        for rejected in ('absent.engineer', 'engineer', 'claude', '', {'role': configuration}):
            result = call({'action': 'create', 'runtime': 'codex', 'instruction': 'must not launch',
                           'configuration': rejected})
            assert result.failed, result.document
            assert result.document['error']['code'] in {'invalid-config', 'invalid-input'}
        assert call({'action': 'status'}).document['result']['agents'] == []
    created = call({'action': 'create', 'runtime': 'codex', 'instruction': 'configuration', **selection})
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
        assert JsonlSessionStore(path).header['extra_fields']['graphtraj']['agentId'] == created.document['agent']
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

    call = agents_callback(root, Caller('controlled-native-host', 'agent-owner'), cwd)
    created = call({'action': 'create', 'runtime': 'codex', 'instruction': 'hold'}).document
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


def test_resume_settings_are_live_without_history_backfill(
    tmp_path: Path, peer: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resume-generated settings must not become an excluded historical prefix."""
    from agent_swarm import write_config
    from graphtraj.interfaces.agents import swarm_root
    from agent_swarm.sessions.archive import JsonlSessionStore, archive_path
    from agent_swarm.sessions.protocol import native_record
    from graphtraj.workspace import runner_project

    root = tmp_path / 'project'
    (root / '.graphtraj').mkdir(parents=True)
    (root / '.graphtraj/config.yml').write_text(default_configuration_content(root, root))
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'codex': {'runtime': 'codex', 'model': 'fixture-model'}},
    }))
    monkeypatch.setattr(runner_project, 'runtime_executable', lambda runtime: peer)
    monkeypatch.setenv('PEER_NATIVE_ROLLOUT', str(tmp_path / 'native'))
    monkeypatch.setenv('PEER_RESUME_SETTINGS', '1')
    write_config(swarm_root(root), save_normalized_sessions=True, backfill_history=False)
    call = agents_callback(root, Caller('controlled-native-host', 'owner'), root)
    created = call({'action': 'create', 'runtime': 'codex', 'instruction': 'first'}).document
    agent = created['agent']
    assert not call({'action': 'wait', 'agent': agent, 'timeout_seconds': 10}).failed
    assert not call({'action': 'resume', 'agent': agent, 'message': 'second'}).failed
    assert not call({'action': 'wait', 'agent': agent, 'timeout_seconds': 10}).failed
    store = JsonlSessionStore(archive_path(swarm_root(root), 'codex:' + created['session']))
    records = [native_record(event) for event in store.page()['events']]
    settings = [r for r in records if r.get('payload', {}).get('type') == 'thread_settings_applied']
    assert len(settings) == 1
    assert settings[0]['payload']['thread_settings']['model'] == 'fixture-model'
    assert not store.pending()


@pytest.mark.skipif(os.environ.get('CODEX_REAL_AUTO_REVIEW') != '1' or shutil.which('codex') is None,
                    reason='Explicit real Codex default auto_review probe only')
def test_real_codex_default_auto_review(tmp_path: Path) -> None:
    """Observe the default reviewer with the user's own Codex home; no credential is copied."""
    root = tmp_path / 'project'
    cwd = root / 'scratch'
    cwd.mkdir(parents=True)
    (root / '.graphtraj').mkdir()
    (root / '.graphtraj/config.yml').write_text(default_configuration_content(root, root))
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'codex': {'runtime': 'codex', 'model': os.environ['CODEX_REAL_MODEL']}},
        'role_tree': {'codex': {}},
    }))
    call = agents_callback(root, Caller('task354-auto-review-probe', 'agent-owner'), cwd)
    created = call({'action': 'create', 'runtime': 'codex',
                    'instruction': 'Reply exactly TASK354-READY. Do not use tools.'})
    assert not created.failed, created.document
    agent = created.document['agent']
    try:
        done = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 120})
        records = [yaml.safe_load(path.read_text()) for path in root.glob('.graphtraj/**/session.yml')]
        [permissions] = [record['permissions'] for record in records
                         if isinstance(record, dict) and 'permissions' in record]
        print(json.dumps({'project': str(root), 'agent': agent, 'session': created.document['session'],
                          'permissions': permissions, 'state': done.document['result']['state'],
                          'last_result': done.document['result'].get('last_result')}))
        assert permissions['requested'] == 'auto_review' and permissions['source'] == 'default', permissions
        assert permissions['observed'] == 'auto_review', permissions
        assert permissions['observed_source'] == 'thread/start', permissions
        assert permissions['matches_request'] is True, permissions
    finally:
        if call({'action': 'status', 'agent': agent}).document['result']['state'] == 'active':
            call({'action': 'interrupt', 'agent': agent})


def test_independent_codex_host_accepts_archiving(tmp_path: Path) -> None:
    """384: save_normalized_sessions: true no longer refuses the CLI host at start."""
    import subprocess
    import sys

    (tmp_path / 'config.yml').write_text('save_normalized_sessions: true\n')
    settings = tmp_path / 'settings.json'
    settings.write_text('{}')
    import agent_swarm

    source = str(Path(agent_swarm.__file__).parents[1])
    finished = subprocess.run([sys.executable, '-m', 'agent_swarm.codex.host', '--settings', str(settings),
                               '--directory', str(tmp_path), 'hi'], capture_output=True, text=True, timeout=60,
                              env={**os.environ, 'PYTHONPATH': source})
    # The empty settings still fail, but for their own reason, not archiving.
    assert 'archive-unavailable' not in finished.stdout + finished.stderr
    assert 'save_normalized_sessions' not in finished.stdout + finished.stderr
