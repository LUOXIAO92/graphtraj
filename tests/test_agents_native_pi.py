"""Independent agents operations through the controlled Pi RPC process."""
from pathlib import Path
import json

import pytest

from agent_swarm import AgentControl, Caller, bind, write_config
from graphtraj.runtimes.pi.driver import PiDriver
from graphtraj.sessions.archive import JsonlSessionStore, archive_path
from test_pi_runtime import context, pi_environment


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
