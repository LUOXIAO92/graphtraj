"""Root CLI/JSON-line launches retain a host beyond their calling process."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, app_server_peer, run_process, wait_for_file
from graphtraj.runtimes.codex.host_events import current_connection, send_event
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError
from runner_fixtures import configure_harness
from test_session_alias_control import _register_ready_ticket
from test_task_budget_control import BODY


PROXY = r'''
import json, os, sys
from pathlib import Path
if sys.argv[1:] == ['app-server', 'proxy']:
    root = Path(os.environ['HOST_TEST_ROOT'])
    for line in sys.stdin:
        request = json.loads(line)
        with (root / 'wire.jsonl').open('a') as stream:
            stream.write(json.dumps({'request':request, 'home':os.environ['CODEX_HOME']})+'\n')
        if request['method'] == 'initialized':
            continue
        result = {'id':request['id'], 'result': {}}
        if request['method'] == 'turn/start':
            params = request['params']
            event = json.loads(params['toolOutput']['output'])
            assert params['threadId'] == 'original-host'
            assert set(params) == {'threadId', 'input', 'toolOutput'}
            assert params['input'] == [] and params['toolOutput']['name'] == 'graphtraj'
            if event['message'] == 'refuse':
                result = {'id':request['id'], 'error': {'code':-32600, 'message': 'direct input refused'}}
            else:
                result['result'] = {'turn': {'id': 'existing-or-new-turn', 'status': 'inProgress', 'items': []}}
                (root / (event['event'] + '-received')).write_text(json.dumps(event))
        print(json.dumps(result), flush=True)
    raise SystemExit(0)
'''

CHILD = r'''
import os, sys, time
from pathlib import Path
if sys.argv[1:3] == ['exec', '--help']:
    print('--sandbox')
    raise SystemExit(0)
sys.stdin.read()
root = Path(os.environ['HOST_TEST_ROOT'])
(root / 'child-ready').touch()
while not (root / 'release').exists():
    time.sleep(.02)
'''


def test_capture_and_native_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Capture uses the launch context; native failure remains an Adapter error."""
    assert current_connection() is None
    monkeypatch.setenv('CODEX_THREAD_ID', 'original-host')
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'owning-home'))
    connection = current_connection()
    assert connection == {'runtime': 'codex', 'session': 'original-host',
                          'codex_home':str(tmp_path / 'owning-home')}
    peer = tmp_path / 'codex'
    peer.write_text('#!' + sys.executable + '\n' + PROXY)
    peer.chmod(0o755)
    monkeypatch.setenv('PATH', str(tmp_path) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('HOST_TEST_ROOT', str(tmp_path))
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'later-home'))
    monkeypatch.setenv('GRAPHTRAJ_ROLE', 'engineer')
    assert current_connection() is None
    for event in ('completed', 'execution-budget-exceeded', 'interrupted'):
        send_event(connection, {'source': 'graphtraj', 'alias': 'child', 'event':event, 'message': 'notice'})
        assert (tmp_path / (event + '-received')).is_file()
    with pytest.raises(RuntimeAdapterError, match='direct input refused'):
        send_event(connection, {'source': 'graphtraj', 'alias': 'child', 'event': 'completed', 'message': 'refuse'})
    wire = [json.loads(line) for line in (tmp_path / 'wire.jsonl').read_text().splitlines()]
    assert {item['home'] for item in wire} == {str(tmp_path / 'owning-home')}
    assert [item['request']['method'] for item in wire] == ['initialize', 'initialized', 'turn/start'] * 4


@pytest.mark.parametrize('entry', ['cli', 'json-line'])
def test_root_completion_after_entry_and_send_exit(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    entry: str,
) -> None:
    """CLI live delivery and JSON-line post-exit delivery retain the send destination."""
    root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'researcher': {'runtime': 'codex', 'model': 'selected'}},
        'role_tree': {'researcher': {}},
    }))
    _register_ready_ticket(installed_commands, root, body=BODY)
    fake_codex.executable.write_text(
        '#!' + sys.executable + '\n' + PROXY
        + app_server_peer(CHILD, "os.environ['GRAPHTRAJ_PARENT_ALIAS']"),
    )
    environment.pop('PYTHONPATH', None)
    environment.update({'CODEX_THREAD_ID': 'original-host',
                        'CODEX_HOME':str(tmp_path / 'owning-home'),
                        'HOST_TEST_ROOT':str(tmp_path)})
    batch = {'tasks': [{'ticket_id': '76', 'role': 'researcher', 'instruction': 'wait for release'}]}
    batch_file = tmp_path / 'batch.yml'
    batch_file.write_text(yaml.safe_dump(batch))
    if entry == 'cli':
        process = subprocess.Popen(
            [str(installed_commands.runner), '--swarm-input', str(batch_file)],
            cwd=root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            wait_for_file(tmp_path / 'child-ready', timeout=15)
            assert process.poll() is None
        finally:
            (tmp_path / 'release').touch()
        output, error = process.communicate(timeout=30)
        assert process.returncode == 0, output + error
        document = yaml.safe_load(output)
    else:
        launched = subprocess.run(
            [str(installed_commands.runner.with_name('graphtraj-tool'))],
            input=json.dumps({'action': 'execute', 'feature': 'swarm', 'arguments':batch})+'\n',
            cwd=root, env=environment, capture_output=True, text=True, timeout=30,
        )
        assert launched.returncode == 0, launched.stdout + launched.stderr
        document = json.loads(launched.stdout)['result']
    alias = document['tasks'][0]['alias']
    try:
        wait_for_file(tmp_path / 'child-ready')
        if entry == 'json-line':
            assert not (tmp_path / 'completed-received').exists()
            (tmp_path / 'release').touch()
        wait_for_file(tmp_path / 'completed-received', timeout=15)
        initial = json.loads((tmp_path / 'completed-received').read_text())
        assert initial['alias'] == alias and initial['source'] == 'graphtraj'
        (tmp_path / 'release').unlink()
        (tmp_path / 'completed-received').unlink()
        events = [json.loads(line) for shard in (root / '.graphtraj/state/worldline').glob('*.jsonl')
                  for line in shard.read_text().splitlines()]
        changed = dict(environment, CODEX_THREAD_ID='different-caller', CODEX_HOME=str(tmp_path / 'other-home'))
        sent = run_process([str(installed_commands.runner), 'send', alias, '--instruction', 'later',
                            '--caused-by-event-id', events[-1]['event_id']], cwd=root, env=changed, timeout=30)
        assert sent.returncode == 0, sent.stdout + sent.stderr
        assert yaml.safe_load(sent.stdout)['send_status'] == 'sent'
        assert not (tmp_path / 'completed-received').exists()
        (tmp_path / 'release').touch()
        wait_for_file(tmp_path / 'completed-received', timeout=15)
        wire = [json.loads(line) for line in (tmp_path / 'wire.jsonl').read_text().splitlines()]
        turns = [item for item in wire if item['request']['method'] == 'turn/start']
        assert len(turns) == 2
        assert {item['home'] for item in turns} == {str(tmp_path / 'owning-home')}
    finally:
        (tmp_path / 'release').touch()
        run_process([str(installed_commands.runner), 'interrupt', alias], cwd=root, env=environment, timeout=30)
