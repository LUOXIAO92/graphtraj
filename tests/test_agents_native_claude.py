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
