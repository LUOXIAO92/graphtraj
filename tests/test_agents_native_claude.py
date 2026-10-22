"""The agents function drives Claude's native owner with no Task, Team or Git.

The controlled official-CLI peer (claude_cli_fixture.py) stands in for the
Runtime; it proves the native lifecycle wiring, not a real host registration.
"""

import json
import os
from pathlib import Path

import pytest
import yaml

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.execution.runner_status import runtime_caller
from graphtraj.interfaces import gateway
from test_claude_runtime import claude_environment  # noqa: F401 - pytest fixture


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A GraphTraj project with one Claude role and no registered Task."""
    root = tmp_path / 'project'
    (root / '.graphtraj').mkdir(parents=True)
    (root / '.graphtraj/config.yml').write_text(default_configuration_content(root, root))
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'claude': {'runtime': 'claude', 'model': 'claude-opus-5-5'}},
        'role_tree': {'claude': {}},
    }))
    return root


def agents(project: Path, cwd: Path, identity: str | None, **request):
    """Call the registered gateway feature as the verified ``identity``."""
    envelope = {'action': 'execute', 'feature': 'agents', 'arguments': request}
    if identity is None:
        result = gateway.handle_request(envelope, cwd=cwd)
    else:
        with runtime_caller(project / '.graphtraj/runner', identity):
            result = gateway.handle_request(envelope, cwd=cwd)
    return result.document, result.failed


def test_native_claude_lifecycle_without_a_task(
    project: Path, tmp_path: Path, claude_environment: None,
) -> None:
    """create → send → wait → interrupt → resume (same Session) → retire."""
    cwd = project / 'scratch'
    cwd.mkdir()
    main = 'main-a'

    created, failed = agents(project, cwd, main, action='create', runtime='claude',
                             instruction='wait-first', name='consultant')
    assert not failed, created
    agent, session = created['agent'], created['session']
    assert created['result']['state'] == 'active' and created['result']['parent'] == main
    assert session

    sent, failed = agents(project, cwd, main, action='send', agent=agent, message='go')
    assert not failed and sent['execution'] == created['execution'], sent
    waited, _ = agents(project, cwd, main, action='wait', agent=agent, timeout_seconds=20)
    assert waited['result']['state'] == 'standby', waited
    assert waited['result']['last_result']['outcome'] == 'completed'
    assert 'go' in waited['result']['last_result']['last_message']

    # An idle send continues the same native Session; interrupt returns to standby.
    again, failed = agents(project, cwd, main, action='send', agent=agent, message='wait-second')
    assert not failed and again['session'] == session and again['execution'] != created['execution']
    stopped, failed = agents(project, cwd, main, action='interrupt', agent=agent)
    assert not failed and stopped['result']['interrupt'] == 'requested', stopped
    stopped, _ = agents(project, cwd, main, action='wait', agent=agent, timeout_seconds=20)
    assert stopped['result']['state'] == 'standby'
    assert stopped['result']['last_result']['outcome'] == 'interrupted'

    resumed, failed = agents(project, cwd, main, action='resume', agent=agent, message='recall')
    assert not failed and resumed['session'] == session, resumed
    resumed, _ = agents(project, cwd, main, action='wait', agent=agent, timeout_seconds=20)
    assert resumed['result']['last_result']['last_message'] == 'wait-first|go|wait-second|recall'

    # Another verified root sees nothing; an unverified call is refused.
    other, _ = agents(project, cwd, 'main-b', action='status')
    assert other['result']['agents'] == []
    hidden, failed = agents(project, cwd, 'main-b', action='send', agent=agent, message='x')
    assert failed and hidden['error']['code'] == 'not-found'
    anonymous, failed = agents(project, cwd, None, action='status')
    assert failed and anonymous['error']['code'] == 'authority-unavailable'

    tree, _ = agents(project, cwd, main, action='status')
    assert [(node['agent'], node['state']) for node in tree['result']['agents']] == [(agent, 'standby')]
    retired, failed = agents(project, cwd, main, action='retire', agent=agent)
    assert not failed and retired['result']['retired']
    tree, _ = agents(project, cwd, main, action='status')
    assert tree['result']['agents'] == []

    record = json.loads((project / '.graphtraj/swarm/control/agents' / f'{agent}.json').read_text())
    assert record['sessions'] == [session] and len(record['executions']) == 3
    assert record['settings']['cwd'] == str(cwd) and record['retired_at']
    assert (project / '.graphtraj/swarm/config.yml').read_text() == 'save_normalized_sessions: true\n'
    assert not (project / '.graphtraj/state/tasks').exists()


@pytest.mark.parametrize('behavior', ['allow', 'deny'])
def test_native_permission_request_ends_wait_and_takes_one_reply(
    project: Path, claude_environment: None, behavior: str,
) -> None:
    """A native approval is retained, ends wait, and is answered once."""
    cwd = project / 'scratch'
    cwd.mkdir()
    created, failed = agents(project, cwd, 'main-a', action='create', runtime='claude',
                             instruction='permission')
    assert not failed, created
    agent = created['agent']

    waited, _ = agents(project, cwd, 'main-a', action='wait', agent=agent, timeout_seconds=20)
    assert waited['result']['state'] == 'active' and waited['result']['pending_requests'] == 1
    listed, _ = agents(project, cwd, 'main-a', action='requests', agent=agent)
    [request] = listed['result']['requests']

    replied, failed = agents(project, cwd, 'main-a', action='reply', agent=agent,
                             request=request, response={'behavior': behavior})
    assert not failed and replied['result']['reply_status'] == 'submitted', replied
    repeated, _ = agents(project, cwd, 'main-a', action='reply', agent=agent,
                         request=request, response={'behavior': 'deny'})
    assert repeated['result']['duplicate']

    done, _ = agents(project, cwd, 'main-a', action='wait', agent=agent, timeout_seconds=20)
    assert done['result']['state'] == 'standby'
    expected = ({'behavior': 'allow', 'updatedInput': {'command': 'echo approved'}} if behavior == 'allow'
                else {'behavior': 'deny', 'message': 'Permission denied by parent.'})
    assert json.loads(done['result']['last_result']['last_message']) == expected


def test_project_root_cwd_preserves_private_state_denials(
    project: Path, tmp_path: Path, claude_environment: None,
) -> None:
    """A Task-free root launch works without granting its private subtree."""
    created, failed = agents(project, project, 'main-a', action='create',
                             runtime='claude', instruction='root consultation')
    assert not failed, created
    done, failed = agents(project, project, 'main-a', action='wait',
                         agent=created['agent'], timeout_seconds=20)
    assert not failed and done['result']['state'] == 'standby', done
    settings = json.loads((tmp_path / 'native-permissions.json').read_text())['settings']
    filesystem = settings['sandbox']['filesystem']
    assert str(project) not in filesystem['allowRead']
    assert str(project / '.graphtraj') in filesystem['denyRead']
    assert str(project / '.graphtraj') in filesystem['denyWrite']
    assert all(not Path(path).is_relative_to(project / '.graphtraj') for path in filesystem['allowWrite'])
    assert not settings['sandbox']['allowUnsandboxedCommands']

    (project / '.graphtraj/state').mkdir()
    denied, failed = agents(project, project / '.graphtraj/state', 'main-a',
                           action='create', runtime='claude', instruction='invalid cwd')
    assert failed and denied['error']['code'] == 'RUNTIME_ACCESS_DENIED', denied


def test_independent_claude_calls_registered_sdk_function_without_runner_alias(
    project: Path, claude_environment: None,
) -> None:
    """The owned SDK callback binds the child's core identity without a Task alias."""
    created, failed = agents(project, project, 'main-a', action='create', runtime='claude',
                             instruction='sdk-agents-status')
    assert not failed, created
    done, failed = agents(project, project, 'main-a', action='wait',
                         agent=created['agent'], timeout_seconds=20)
    assert not failed and done['result']['state'] == 'standby', done
    result = json.loads(done['result']['last_result']['last_message'])
    assert not result['isError'], result
    assert result['structuredContent']['result']['agents'] == []
    assert not (project / '.graphtraj/state/sessions').exists()
    assert not list((project / '.graphtraj/swarm/native').glob('*/trace.jsonl'))


def test_driver_honors_archive_binding_and_native_transcript_on_resume(
    project: Path, claude_environment: None,
) -> None:
    """The core Run.archive policy reaches real process transport and JSONL."""
    from agent_swarm import AgentControl, Caller, bind, write_config
    from graphtraj.execution.agent_driver import AdapterDriver
    from graphtraj.sessions.archive import JsonlSessionStore, SessionArchive, archive_path

    root = project / '.graphtraj/swarm'
    write_config(root, save_normalized_sessions=True, backfill_history=True)
    archive = SessionArchive(root, save_normalized_sessions=True, backfill_history=True)
    control = AgentControl(root, {'claude': AdapterDriver(project, project)})
    call = bind(control, Caller('test-host', 'main'), archive=archive)
    created = call({'action': 'create', 'runtime': 'claude', 'instruction': 'remember'}).document
    assert 'error' not in created, created
    done = call({'action': 'wait', 'agent': created['agent'], 'timeout_seconds': 20})
    assert not done.failed, done.document
    path = archive_path(root, 'claude:' + created['session'])
    first = JsonlSessionStore(path).messages()
    assert [m['role'] for m in first] == ['user', 'assistant']
    resumed = call({'action': 'send', 'agent': created['agent'], 'message': 'recall'})
    assert resumed.document['session'] == created['session']
    call({'action': 'wait', 'agent': created['agent'], 'timeout_seconds': 20})
    assert len(JsonlSessionStore(path).messages()) == 4
    before = path.read_bytes()
    write_config(root, save_normalized_sessions=False)
    call({'action': 'send', 'agent': created['agent'], 'message': 'no archive'})
    call({'action': 'wait', 'agent': created['agent'], 'timeout_seconds': 20})
    assert path.read_bytes() == before
    assert not (project / '.graphtraj/state/sessions').exists()


def test_sdk_retransmission_creates_one_child_with_real_parent_binding(
    project: Path, claude_environment: None,
) -> None:
    """Duplicate SDK transport requests reuse the receipt rather than launch twice."""
    created, failed = agents(project, project, 'main-a', action='create', runtime='claude',
                             instruction='sdk-agents-create-twice')
    assert not failed, created
    done, failed = agents(project, project, 'main-a', action='wait', agent=created['agent'], timeout_seconds=20)
    assert not failed, done
    first, second = json.loads(done['result']['last_result']['last_message'])
    assert not first['isError'] and not second['isError']
    assert first['structuredContent']['agent'] == second['structuredContent']['agent']
    child = first['structuredContent']['agent']
    child_status, failed = agents(project, project, 'main-a', action='wait', agent=child, timeout_seconds=20)
    assert not failed and child_status['result']['parent'] == created['agent']


def test_native_display_hook_does_not_send_an_extra_model_prompt(
    project: Path, tmp_path: Path, claude_environment: None,
) -> None:
    """The registered hook returns human-only frames while native memory stays unchanged."""
    created, failed = agents(project, project, 'main-a', action='create', runtime='claude',
                             instruction='sdk-agents-display')
    assert not failed, created
    done, failed = agents(project, project, 'main-a', action='wait', agent=created['agent'], timeout_seconds=20)
    assert not failed, done
    reply = json.loads(done['result']['last_result']['last_message'])
    assert reply['structuredContent']['result']['last_result']['last_message'] == 'child'
    history = tmp_path / (created['session'] + '.json')
    assert json.loads(history.read_text()) == ['sdk-agents-display']
    displays = [json.loads(line) for line in history.with_suffix('.display.jsonl').read_text().splitlines()]
    assert len(displays) == 2
    assert all(set(display) == {'systemMessage'} for display in displays)
    assert all('child' in display['systemMessage'] for display in displays)


def test_resumed_claude_children_keep_the_native_cwd(
    project: Path, claude_environment: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller's later working directory cannot relocate the resumed native parent."""
    first, later = project / 'first', project / 'later'
    first.mkdir()
    later.mkdir()
    monkeypatch.setenv('CLAUDE_FIXTURE_REPORT_CWD', '1')
    created, failed = agents(project, first, 'main-a', action='create', runtime='claude', instruction='first')
    assert not failed, created
    agents(project, first, 'main-a', action='wait', agent=created['agent'], timeout_seconds=20)
    resumed, failed = agents(project, later, 'main-a', action='send', agent=created['agent'],
                             message='sdk-agents-create-twice')
    assert not failed and resumed['session'] == created['session'], resumed
    done, failed = agents(project, later, 'main-a', action='wait', agent=created['agent'], timeout_seconds=20)
    assert not failed, done
    replies = json.loads(done['result']['last_result']['last_message'])
    child = replies[0]['structuredContent']['agent']
    done, failed = agents(project, later, 'main-a', action='wait', agent=child, timeout_seconds=20)
    assert not failed and done['result']['last_result']['last_message'] == str(first), done


@pytest.mark.skipif(not os.environ.get('CLAUDE_REAL_TEST_BINARY'), reason='Explicit real SDK registration probe only')
def test_real_claude_sdk_registration(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify real native registration separately from successful model inference."""
    from agent_swarm import AgentControl, Caller, bind, write_config
    from graphtraj.execution.agent_driver import AdapterDriver
    from graphtraj.sessions.archive import JsonlSessionStore, SessionArchive, archive_path

    binary = Path(os.environ['CLAUDE_REAL_TEST_BINARY'])
    monkeypatch.setenv('PATH', str(binary.parent) + os.pathsep + os.environ['PATH'])
    root = project / '.graphtraj/swarm'
    write_config(root, save_normalized_sessions=True, backfill_history=True)
    archive = SessionArchive(root, save_normalized_sessions=True, backfill_history=True)
    call = bind(AgentControl(root, {'claude': AdapterDriver(project, project)}),
                Caller('native-registration-probe', None, 'task332-probe'), archive=archive)
    created = call({'action': 'create', 'runtime': 'claude',
                    'instruction': 'Reply with only TASK332. Do not use any tools.'})
    assert not created.failed, created.document
    done = call({'action': 'wait', 'agent': created.document['agent'], 'timeout_seconds': 30})
    assert not done.failed and done.document['result']['state'] == 'standby', done.document
    session = JsonlSessionStore(archive_path(root, 'claude:' + created.document['session']))
    records = [item['event']['graphtraj']['native']['record']
               for item in [*session.pending(), *session.observations()]]
    native = next(r for r in records if r.get('type') == 'system' and r.get('subtype') == 'init')
    assert 'mcp__agents__agents' in native['tools']
    outcome = done.document['result']['last_result']
    print(json.dumps({'session': created.document['session'], 'registered_tool': 'mcp__agents__agents',
                      'permissionMode': native.get('permissionMode'), 'outcome': outcome['outcome'],
                      'error_code': (outcome.get('error') or {}).get('code')}))
    # A provider error is retained as such. This probe accepts only registration,
    # never treats missing login or a model failure as successful inference.
    assert outcome['outcome'] == 'completed' or (outcome.get('error') or {}).get('code') == 'RUNTIME_PROVIDER_FAILED'


@pytest.mark.skipif(not os.environ.get('CLAUDE_REAL_AUTO_TEST'), reason='Explicit real auto and deny probe only')
def test_real_claude_auto_and_native_denial(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Require actual auto, registered function use and a native denied Read in one turn."""
    from agent_swarm import AgentControl, Caller, bind, write_config
    from graphtraj.execution.agent_driver import AdapterDriver
    from graphtraj.sessions.archive import JsonlSessionStore, SessionArchive, archive_path

    binary = Path(os.environ['CLAUDE_REAL_TEST_BINARY'])
    monkeypatch.setenv('PATH', str(binary.parent) + os.pathsep + os.environ['PATH'])
    monkeypatch.delenv('CLAUDE_CODE_SUBPROCESS_ENV_SCRUB', raising=False)
    roles = project / '.graphtraj/roles.yml'
    document = yaml.safe_load(roles.read_text())
    document['roles']['claude']['model'] = 'claude-opus-5-5'
    document['roles']['claude']['reasoning_effort'] = 'high'
    # CLAUDE_REAL_AUTO_DEFAULT leaves the role unset to observe the default selection.
    if not os.environ.get('CLAUDE_REAL_AUTO_DEFAULT'):
        document['roles']['claude']['claude'] = {'permission_mode': 'auto'}
    roles.write_text(yaml.safe_dump(document))
    # Members may read .graphtraj/state since b3a6071; the control directory stays denied.
    denied = project / '.graphtraj/cli/task332-denied.txt'
    denied.parent.mkdir(parents=True, exist_ok=True)
    denied.write_text('TASK332-SYNTHETIC-NO-SECRET')
    assert denied.is_file() and denied.read_text() == 'TASK332-SYNTHETIC-NO-SECRET'
    root = project / '.graphtraj/swarm'
    write_config(root, save_normalized_sessions=True, backfill_history=True)
    archive = SessionArchive(root, save_normalized_sessions=True, backfill_history=True)
    call = bind(AgentControl(root, {'claude': AdapterDriver(project, project)}),
                Caller('native-auto-probe', None, 'task332-auto-probe'), archive=archive)
    created = call({'action': 'create', 'runtime': 'claude', 'instruction':
        'Call mcp__agents__agents with action status once. Then attempt exactly one Read tool call '
        f'on {denied}. The file is a synthetic permission-test fixture. '
        'If denied, do not retry or use another tool to access it. Reply with TASK332-DONE.'})
    assert not created.failed, created.document
    agent = created.document['agent']
    try:
        done = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 60})
        outcome = done.document['result'].get('last_result') or {}
        session = JsonlSessionStore(archive_path(root, 'claude:' + created.document['session']))
        records = [item['event']['graphtraj']['native']['record']
                   for item in [*session.pending(), *session.observations()]]
        native = next((r for r in records if r.get('type') == 'system' and r.get('subtype') == 'init'), {})
        print(json.dumps({'project': str(project), 'agent': agent, 'session': created.document['session'],
                          'requested': 'auto', 'observed': native.get('permissionMode'),
                          'requested_model': 'claude-opus-5-5', 'requested_effort': 'high',
                          'observed_model': native.get('model'),
                          'state': done.document['result']['state'], 'outcome': outcome.get('outcome'),
                          'error': outcome.get('error')}))
        assert not done.failed and done.document['result']['state'] == 'standby', done.document
        assert native.get('permissionMode') == 'auto', native
        assert native.get('model') == 'claude-opus-5-5', native
        assert outcome['outcome'] == 'completed', outcome
        transcript = Path(session.header['graphtraj']['native']['locator'])
        entries = [json.loads(line) for line in transcript.read_text().splitlines()]
        blocks = [block for entry in entries for block in entry.get('message', {}).get('content', [])
                  if isinstance(block, dict)]
        calls = [b for b in blocks if b.get('type') == 'tool_use']
        assert any(b.get('name') == 'mcp__agents__agents' for b in calls), calls
        read = next(b for b in calls if b.get('name') == 'Read' and b.get('input', {}).get('file_path') == str(denied))
        assert any(b.get('type') == 'tool_result' and b.get('tool_use_id') == read['id']
                   and b.get('is_error') is True for b in blocks), blocks
        assert_native_read_denial(records, read)
        assert denied.is_file() and denied.read_text() == 'TASK332-SYNTHETIC-NO-SECRET'
    finally:
        current = call({'action': 'status', 'agent': agent})
        if current.document['result']['state'] == 'active':
            call({'action': 'interrupt', 'agent': agent})
            stopped = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 30})
            assert stopped.document['result']['state'] == 'standby', stopped.document


def assert_native_read_denial(records: list[dict], read: dict) -> None:
    """Require the official result's authoritative permission booking for this Read."""
    denials = [denial for record in records if record.get('type') == 'result'
               for denial in record.get('permission_denials', [])]
    assert any(denial.get('tool_name') == 'Read'
               and denial.get('tool_use_id') == read['id']
               and denial.get('tool_input') == read['input'] for denial in denials), (
        'No authoritative native permission_denials entry matches the Read call; '
        'a generic tool_result error is insufficient.', denials,
    )


def test_real_probe_requires_correlated_native_permission_denial() -> None:
    """File/tool errors and another call's denial cannot pass the real evidence gate."""
    read = {'id': 'read-one', 'input': {'file_path': '/synthetic/exists'}}
    denied = {'tool_name': 'Read', 'tool_use_id': 'read-one', 'tool_input': read['input']}
    assert_native_read_denial([{'type': 'result', 'permission_denials': [denied]}], read)
    insufficient = [
        [{'type': 'user', 'message': {'content': [{'type': 'tool_result', 'is_error': True,
                                                 'tool_use_id': 'read-one', 'content': 'File not found'}]}}],
        [{'type': 'result', 'permission_denials': [{**denied, 'tool_use_id': 'another'}]}],
        [{'type': 'result', 'permission_denials': [{**denied, 'tool_input': {'file_path': '/other'}}]}],
        [{'type': 'result', 'permission_denials': [{**denied, 'tool_name': 'Bash'}]}],
    ]
    for records in insufficient:
        with pytest.raises(AssertionError, match='authoritative native'):
            assert_native_read_denial(records, read)


@pytest.mark.parametrize(('saving', 'configuration'), [(False, None), (True, None),
                                                       (True, 'astra_coding_team.engineer')])
def test_shared_connection_and_archive_binding_for_claude(
    project: Path,
    tmp_path: Path,
    claude_environment: None,
    monkeypatch: pytest.MonkeyPatch,
    saving: bool,
    configuration: str | None,
) -> None:
    """Compose the extracted shared seam with Claude's native owner and policy changes."""
    from agent_swarm import Caller, read_config, write_config
    from graphtraj.configuration import runtime_connections
    from graphtraj.interfaces.agents import agents_callback, swarm_root
    from graphtraj.interfaces.local_tool import bind
    from graphtraj.sessions.archive import JsonlSessionStore, archive_path

    monkeypatch.setattr(runtime_connections, 'connections_file', lambda: tmp_path / 'connections.yml')
    settings = bind(project, recovery_reviewer=lambda proposal: {'decision': 'accept'})
    current = settings({'action': 'execute', 'feature': 'runtime_connections', 'arguments': {'action': 'read'}})
    catalog = {'version': 1, 'runtimes': {'configured': {'runtime': 'claude',
        'providers': {'anthropic': {'models': {'chosen': {'id': 'claude-opus-5-5',
            'source': 'manual', 'supported_efforts': ['high']}}}}}}}
    saved = settings({'action': 'execute', 'feature': 'runtime_connections', 'arguments': {
        'action': 'save', 'expected_revision': current.document['revision'], 'catalog': catalog}})
    assert not saved.failed, saved.document
    role = {'connection': 'configured/anthropic/chosen', 'reasoning_effort': 'high',
            'claude': {'permission_mode': 'auto'}}
    roles = project / '.graphtraj/roles.yml'
    roles.write_text(yaml.safe_dump({'roles': {'worker': role}}))
    if configuration is not None:
        roles.write_text(yaml.safe_dump({'roles': {
            'astra_coding_team': {'engineer': role},
            'other_team': {'engineer': {'runtime': 'claude', 'model': 'wrong-model'}},
            'claude': {'runtime': 'claude', 'model': 'wrong-default'},
            'codex': {'runtime': 'codex', 'model': 'wrong-runtime'},
            'unavailable': {'connection': 'missing/provider/model'},
        }}))
    root = swarm_root(project)
    write_config(root, save_normalized_sessions=saving, backfill_history=True)
    call = agents_callback(project, Caller('controlled-native-host', 'parent'), project)
    if configuration is not None:
        for rejected in ('absent.engineer', 'engineer', 'codex', '', {'role': configuration}):
            result = call({'action': 'create', 'runtime': 'claude', 'instruction': 'must not launch',
                           'configuration': rejected})
            assert result.failed and result.document['error']['code'] in {'invalid-config', 'invalid-input'}
    selection = {} if configuration is None else {'configuration': configuration}
    created = call({'action': 'create', 'runtime': 'claude', 'instruction': 'first', **selection})
    assert not created.failed, created.document
    agent = created.document['agent']
    done = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 20})
    assert not done.failed and done.document['result']['last_result']['outcome'] == 'completed', done.document
    launch = json.loads((tmp_path / 'native-permissions.json').read_text())
    assert launch['model'] == 'claude-opus-5-5' and launch['effort'] == 'high'
    assert launch['mode'] == 'auto' and launch['scrub'] == '0'
    path = archive_path(root, 'claude:' + created.document['session'])
    assert path.exists() is saving
    if saving:
        assert len(JsonlSessionStore(path).messages()) == 2
    before = path.read_bytes() if saving else None
    assert read_config(root)['save_normalized_sessions'] is saving
    removed = settings({'action': 'execute', 'feature': 'runtime_connections', 'arguments': {
        'action': 'save', 'expected_revision': saved.document['revision'], 'catalog': {'version': 1, 'runtimes': {}}}})
    assert not removed.failed, removed.document
    write_config(root, save_normalized_sessions=False)
    resumed = call({'action': 'send', 'agent': agent, 'message': 'second'})
    assert not resumed.failed and resumed.document['session'] == created.document['session'], resumed.document
    done = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 20})
    assert done.document['result']['last_result']['outcome'] == 'completed', done.document
    assert (path.read_bytes() if saving else None) == before
    assert path.exists() is saving
    restored = settings({'action': 'execute', 'feature': 'runtime_connections', 'arguments': {
        'action': 'save', 'expected_revision': removed.document['revision'], 'catalog': catalog}})
    assert not restored.failed, restored.document
    roles.write_text(yaml.safe_dump({'roles': {'first': role, 'second': role}}))
    ambiguous = call({'action': 'create', 'runtime': 'claude', 'instruction': 'must not launch'})
    assert ambiguous.failed and ambiguous.document['error']['code'] == 'invalid-config'
    assert all(name in ambiguous.document['error']['message'] for name in ('first', 'second'))
