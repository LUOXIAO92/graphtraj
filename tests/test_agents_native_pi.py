"""Independent agents operations through the controlled Pi RPC process."""
from pathlib import Path
import json

import pytest

from agent_swarm import AgentControl, Caller, bind, write_config
from graphtraj.runtimes.pi.driver import PiDriver
from graphtraj.sessions.archive import JsonlSessionStore, archive_path
from test_pi_runtime import context, pi_environment


def test_connection_reference_selects_pi_runtime(
    tmp_path: Path, pi_environment: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolve a configured connection before choosing the Pi role preset."""
    from dataclasses import replace
    from types import SimpleNamespace
    from graphtraj.configuration.project_roles import RolePreset
    from graphtraj.execution.agent_driver import AdapterDriver

    cwd = tmp_path / 'work'
    cwd.mkdir()
    reference = RolePreset(runtime='', model='', base_url=None, api_key_env=None,
                           connection='pi/fixture/deepseek-flash', pi=pi_environment)
    resolved = replace(reference, runtime='pi', model='deepseek/deepseek-flash',
                       connection_revision='fixture-revision')
    monkeypatch.setattr('graphtraj.configuration.project_roles.load_project_roles',
                        lambda root: SimpleNamespace(presets={
                            'pi': reference, 'other': replace(reference, connection='claude/unrelated/model'),
                        }))

    def resolve_selected(preset: RolePreset) -> RolePreset:
        """An unrelated Runtime's connection must not be read for Pi selection."""
        assert preset is reference
        return resolved

    monkeypatch.setattr('graphtraj.configuration.project_roles.resolve_preset', resolve_selected)
    prepared = AdapterDriver(tmp_path, cwd).prepare('pi', Caller('test-host', 'parent'))
    assert prepared['role'] == 'pi'
    assert prepared['adapter_request']['provider'] == 'deepseek'
    assert prepared['adapter_request']['model'] == 'deepseek-flash'
    assert prepared['adapter_request']['worktree_path'] == str(cwd)


@pytest.mark.parametrize('chunk', [1, 512])
def test_independent_pi_memory_stop_and_archive(
    tmp_path: Path,
    pi_environment: dict,
    monkeypatch: pytest.MonkeyPatch,
    chunk: int,
) -> None:
    """No Task, Git or mapping file is required to control and resume Pi."""
    cwd = tmp_path / 'worktrees/research'
    cwd.mkdir(parents=True)
    _, prepared = context(tmp_path, pi_environment)
    root = tmp_path / 'swarm'
    policy_file = tmp_path / 'policy.json'
    monkeypatch.setenv('PI_FIXTURE_POLICY', str(policy_file))
    monkeypatch.setenv('PI_FIXTURE_CHUNK', str(chunk))
    driver = PiDriver(prepared.launch_document()['adapter_request'])
    control = AgentControl(root, {'pi': driver})
    caller = Caller('test-host', 'parent', session='parent-session')
    call = bind(control, caller)
    created = call({'action': 'create', 'runtime': 'pi', 'instruction': 'memory-sentinel'})
    assert not created.failed, created.document
    agent = created.document['agent']
    session = created.document['session']
    ended = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 10})
    assert ended.document['result']['state'] == 'standby', ended.document
    assert not (root / 'sessions').exists()
    assert not (tmp_path / '.graphtraj').exists()
    assert not (root / 'native' / agent / 'mapping.yml').exists()
    policy = json.loads(policy_file.read_text())['filesystem']
    assert str(root) in policy['denyRead']
    assert str(root) in policy['denyWrite']
    assert str(root / 'native' / agent / 'trace.pi') in policy['allowWrite']
    resumed = call({'action': 'send', 'agent': agent, 'message': 'wait for stop'})
    assert not resumed.failed, resumed.document
    stopped = call({'action': 'interrupt', 'agent': agent})
    assert not stopped.failed, stopped.document
    ended = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 10})
    assert ended.document['result']['state'] == 'standby'
    assert ended.document['session'] == session
    assert 'memory-sentinel' in ended.document['result']['last_result']['last_message']

    write_config(root, save_normalized_sessions=True, backfill_history=True)
    call = bind(control, caller)
    resumed = call({'action': 'resume', 'agent': agent, 'message': 'stream-ok'})
    assert not resumed.failed, resumed.document
    ended = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 10})
    assert ended.document['result']['last_result']['outcome'] == 'completed', ended.document
    assert ended.document['session'] == session
    store = JsonlSessionStore(archive_path(root, 'pi:' + session))
    assert not store.pending()
    assert len(store.observations()) == 2
    records = [event['data']['record'] for event in store.page()['events'] if event['type'] == 'graphtraj/native']
    assert records[0]['message']['content'] == 'memory-sentinel'
    assert records[-1]['message']['role'] == 'toolResult'


def test_independent_pi_native_request_and_explicit_reply(tmp_path: Path, pi_environment: dict) -> None:
    """A native Pi dialog reaches the core without a Task parent notifier."""
    (tmp_path / 'worktrees/research').mkdir(parents=True)
    _, prepared = context(tmp_path, pi_environment)
    driver = PiDriver(prepared.launch_document()['adapter_request'])
    call = bind(AgentControl(tmp_path / 'swarm', {'pi': driver}), Caller('test-host', 'parent'))
    created = call({'action': 'create', 'runtime': 'pi', 'instruction': 'dialog'})
    assert not created.failed, created.document
    agent = created.document['agent']
    waiting = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 10})
    assert waiting.document['result']['pending_requests'] == 1
    requests = call({'action': 'requests', 'agent': agent})
    request = requests.document['result']['requests'][0]
    assert request['method'] == 'pi/confirm'
    replied = call({'action': 'reply', 'agent': agent, 'request': request,
                    'response': {'confirmed': False}})
    assert not replied.failed, replied.document
    assert replied.document['result']['reply_status'] == 'submitted'
    ended = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 10})
    assert ended.document['result']['state'] == 'standby'


def test_pi_child_calls_same_control_via_authenticated_mcp(
    tmp_path: Path, pi_environment: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A controlled Pi descendant's actual MCP subprocess creates its own child."""
    import json

    monkeypatch.setenv('DSH_SESSION_ID', 'native-dsh-parent')
    monkeypatch.setenv('DSH_AGENT_SOURCE', 'child')
    (tmp_path / 'worktrees/research').mkdir(parents=True)
    _, prepared = context(tmp_path, pi_environment)
    driver = PiDriver(prepared.launch_document()['adapter_request'])
    root = tmp_path / 'swarm'
    control = AgentControl(root, {'pi': driver})
    call = bind(control, Caller('test-host', 'parent'))
    created = call({'action': 'create', 'runtime': 'pi', 'instruction': 'agents-mcp'})
    assert not created.failed, created.document
    ended = call({'action': 'wait', 'agent': created.document['agent'], 'timeout_seconds': 20})
    result = ended.document['result']['last_result']
    assert result['outcome'] == 'completed', result
    received = json.loads(result['last_message'])
    assert received['exit'] == 0
    listed, described, called = received['replies']
    assert [tool['name'] for tool in listed['result']['tools']] == ['agents']
    assert set(described['result']['structuredContent']['input_schema']['properties']) == {'agent'}
    assert not called['result']['isError'], called
    grandchild = called['result']['structuredContent']['agent']
    final = call({'action': 'wait', 'agent': grandchild, 'timeout_seconds': 10})
    assert final.document['result']['parent'] == created.document['agent']
    assert final.document['result']['last_result']['last_message'] == 'grandchild-memory'
    assert not list(root.rglob('mapping.yml'))
    assert not list(root.rglob('control-*'))
    policy = json.loads((root / 'native' / created.document['agent'] / 'pi-policy.json').read_text())
    assert str(root.resolve()) in policy['filesystem']['denyRead']
    assert any('/mcp/control-' in path for path in policy['filesystem']['allowWrite'])


def test_pi_control_and_native_dialog_do_not_import_task_host(tmp_path: Path, pi_environment: dict) -> None:
    """Prepared independent Pi execution works when Task host modules are unavailable."""
    import json
    import os
    import subprocess
    import sys

    (tmp_path / 'worktrees/research').mkdir(parents=True)
    _, prepared = context(tmp_path, pi_environment)
    request = tmp_path / 'prepared.json'
    request.write_text(json.dumps(prepared.launch_document()['adapter_request']))
    script = '''
import sys, json, importlib.abc
from pathlib import Path
class NoTaskHost(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        forbidden = ('graphtraj.interfaces', 'graphtraj.configuration', 'graphtraj.workspace',
                     'graphtraj.execution.runner_control', 'graphtraj.execution.runner_status',
                     'graphtraj.runtimes.codex')
        if fullname.startswith(forbidden):
            raise ImportError('Task host is unavailable: ' + fullname)
sys.meta_path.insert(0, NoTaskHost())
from agent_swarm import AgentControl, Caller, bind, write_config
from graphtraj.runtimes.pi.driver import PiDriver
request = json.loads(Path(sys.argv[1]).read_text())
root = Path(sys.argv[2])
write_config(root, save_normalized_sessions=True, backfill_history=True)
call = bind(AgentControl(root, {'pi': PiDriver(request)}), Caller('independent-test', 'parent'))
created = call({'action':'create','runtime':'pi','instruction':'dialog'})
assert not created.failed, created.document
agent = created.document['agent']
waiting = call({'action':'wait','agent':agent,'timeout_seconds':10})
assert waiting.document['result']['pending_requests'] == 1, waiting.document
request = call({'action':'requests','agent':agent}).document['result']['requests'][0]
assert not call({'action':'reply','agent':agent,'request':request,'response':{'confirmed':False}}).failed
ended = call({'action':'wait','agent':agent,'timeout_seconds':10})
assert ended.document['result']['last_result']['outcome'] == 'completed', ended.document
assert not list(root.rglob('mapping.yml'))
print('independent Pi control/dialog/archive without Task-host modules')
'''
    result = subprocess.run([sys.executable, '-c', script, str(request), str(tmp_path / 'isolated-swarm')],
                            env=dict(os.environ), capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr + result.stdout
