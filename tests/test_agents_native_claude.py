"""The agents function drives Claude's native owner with no Task, Team or Git.

The controlled official-CLI peer (claude_cli_fixture.py) stands in for the
Runtime; it proves the native lifecycle wiring, not a real host registration.
"""

import json
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


def test_native_permission_request_ends_wait_and_takes_one_reply(
    project: Path, claude_environment: None,
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
                             request=request, response={'behavior': 'allow'})
    assert not failed and replied['result']['reply_status'] == 'submitted', replied
    repeated, _ = agents(project, cwd, 'main-a', action='reply', agent=agent,
                         request=request, response={'behavior': 'deny'})
    assert repeated['result']['duplicate']

    done, _ = agents(project, cwd, 'main-a', action='wait', agent=agent, timeout_seconds=20)
    assert done['result']['state'] == 'standby'
    assert json.loads(done['result']['last_result']['last_message']) == {
        'behavior': 'allow', 'updatedInput': {'command': 'echo approved'}}


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
    assert not settings['sandbox']['allowUnsandboxedCommands']

    denied, failed = agents(project, project / '.graphtraj/state', 'main-a',
                           action='create', runtime='claude', instruction='invalid cwd')
    assert failed and denied['error']['code'] == 'RUNTIME_ACCESS_DENIED', denied
