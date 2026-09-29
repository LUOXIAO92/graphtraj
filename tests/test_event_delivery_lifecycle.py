"""Installed event producers deliver to their real parent's native conversation.

Only model work is replaced with a deterministic peer. Actions run from the
parent's process through public Runner operations; logs distinguish input ACK
from consumption, result assessment and child progress.
"""

from __future__ import annotations

import fcntl
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, app_server_peer, run_process, wait_for_file
from runner_fixtures import configure_harness
from test_parent_permission_notice import _await_records, _last_worldline_event, _mapping_for_role
from test_session_alias_control import _register_ready_ticket
from test_task_budget_control import BODY


SCENARIO = r'''
import json, os, subprocess, sys, time
from pathlib import Path
import yaml


def record(value):
    """Record a model-side action separately from the native protocol."""
    with Path(os.environ['LIFECYCLE_LOG']).open('a') as stream:
        stream.write(json.dumps(value) + '\n')


def call(*args):
    """Act through the Runner as the real parent/child process."""
    result = subprocess.run([os.environ['GRAPHTRAJ_AGENT_RUNNER'], *args],
                            capture_output=True, text=True,
                            cwd=os.environ['GRAPHTRAJ_HARNESS_ROOT'])
    assert result.returncode == 0, (args, result.stdout, result.stderr)
    return yaml.safe_load(result.stdout)


def consume(text):
    """Read the received event and perform the parent's report update."""
    notice = json.loads(text)
    assert set(notice) == {'source', 'alias', 'event', 'message'}
    assert notice['source'] == 'graphtraj'
    details = ({} if notice['event'] == 'execution-budget-exceeded' else
               json.loads(notice['message'].split('\n')[-1]))
    result = call('submit-report', '--name', 'leader.md', '--text', text)
    record({'acted': notice, 'details': details, 'report': result})
    return notice


if sys.argv[1:3] == ['exec', '--help']:
    print('--sandbox')
    raise SystemExit(0)
prompt = sys.stdin.read()
role = os.environ['GRAPHTRAJ_ROLE']
if role == 'team-leader':
    if prompt.startswith('{'):
        notice = consume(prompt)
        # The deterministic model must consume steering received while its
        # first report call runs, just as it consumes its initial prompt.
        waiting = 'terminal' if notice['event'] in {'result-submitted', 'execution-budget-exceeded'} else (
            'aggregate' if notice['event'] == 'completed' and not Path(os.environ['LIFECYCLE_RELEASE']).exists() else None)
        seen = set()
        deadline = time.monotonic() + 20
        while waiting and time.monotonic() < deadline:
            path = Path(os.environ['LIFECYCLE_INPUT'])
            for line in path.read_text().splitlines() if path.exists() else []:
                request = json.loads(line)
                if request['params'].get('expectedTurnId') != os.environ['LIFECYCLE_TURN']:
                    continue
                text = request['params']['input'][0]['text']
                if text in seen:
                    continue
                seen.add(text)
                if text.startswith('{'):
                    item = consume(text)
                    if waiting == 'terminal' and item['event'] in {'completed', 'runtime-error', 'interrupted'}:
                        waiting = None
                elif text.startswith('Direct child execution results:'):
                    record({'aggregate': text})
                    if waiting == 'aggregate':
                        waiting = None
            time.sleep(.02)
        assert not waiting, waiting
    elif prompt == 'race':
        Path(os.environ['LIFECYCLE_PARENT_READY']).touch()
        seen = set()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            path = Path(os.environ['LIFECYCLE_INPUT'])
            for line in path.read_text().splitlines() if path.exists() else []:
                request = json.loads(line)
                if request['params'].get('expectedTurnId') != os.environ['LIFECYCLE_TURN']:
                    continue
                text = request['params']['input'][0]['text']
                if text in seen:
                    continue
                seen.add(text)
                if text.startswith('{'):
                    notice = consume(text)
                    receipt = call('send', notice['alias'], '--instruction', 'later',
                                   '--caused-by-event-id', os.environ['LIFECYCLE_CAUSE'])
                    record({'send_ack': receipt})
                    Path(os.environ['LIFECYCLE_RACE_ACK']).touch()
                elif text.startswith('Direct child execution results:'):
                    record({'aggregate': text})
                    raise SystemExit(0)
            time.sleep(.02)
        raise SystemExit('original Driver never aggregated')
    elif prompt == 'followup':
        child = Path(os.environ['LIFECYCLE_CHILD']).read_text()
        receipt = call('send', child, '--instruction', 'later',
                       '--caused-by-event-id', os.environ['LIFECYCLE_CAUSE'])
        record({'send_ack': receipt})
        if os.environ['LIFECYCLE_IDLE'] == '0':
            seen = set()
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                path = Path(os.environ['LIFECYCLE_INPUT'])
                for line in path.read_text().splitlines() if path.exists() else []:
                    request = json.loads(line)
                    if request['params'].get('expectedTurnId') != os.environ['LIFECYCLE_TURN']:
                        continue
                    text = request['params']['input'][0]['text']
                    if text not in seen and text.startswith('{'):
                        seen.add(text)
                        notice = consume(text)
                        if notice['event'] in {'completed', 'runtime-error', 'interrupted'}:
                            raise SystemExit(0)
                time.sleep(.02)
            raise SystemExit('parent never consumed terminal')
    elif 'Direct child execution results:' in prompt:
        record({'aggregate': prompt})
    else:
        call('--swarm-input', os.environ['LIFECYCLE_BATCH'])
elif prompt == 'later':
    release = Path(os.environ['LIFECYCLE_RELEASE'])
    while not release.exists():
        time.sleep(.02)
    if os.environ.get('LIFECYCLE_SUBMIT') == '1':
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
        result = call('submit-result', '--commit', commit, '--result-ref', 'README.md',
                      '--completion', 'Controlled result ready')
        record({'submitted': result})
    raise SystemExit(int(os.environ['LIFECYCLE_FAILURE']))
elif os.environ.get('LIFECYCLE_RACE') == '1':
    while not Path(os.environ['LIFECYCLE_INITIAL_RELEASE']).exists():
        time.sleep(.02)
'''


def lifecycle_peer(fake_codex: FakeCodex) -> None:
    """Keep production Adapter wire semantics and expose received steer to model work."""
    directory = fake_codex.executable.parent
    peer = Path(__file__).with_name('runner_codex_peer.py').read_text()
    peer = peer.replace(
        "    process = subprocess.Popen(argv,",
        "    os.environ['LIFECYCLE_TURN'] = turn\n    process = subprocess.Popen(argv,",
    ).replace(
        "    elif method == 'turn/steer':\n",
        "    elif method == 'turn/steer':\n"
        "        with open(os.environ['LIFECYCLE_INPUT'], 'a') as stream:\n"
        "            stream.write(json.dumps(request) + '\\n')\n",
    )
    script = app_server_peer('#!' + sys.executable + '\n' + SCENARIO,
                             "os.environ['GRAPHTRAJ_PARENT_ALIAS']")
    original_peer = str(Path(__file__).with_name('runner_codex_peer.py'))
    target = directory / 'lifecycle-peer.py'
    peer = peer.replace(
        "    if method == 'initialize':",
        "    if method in ('turn/start', 'turn/steer') and os.environ.get('LIFECYCLE_REFUSE') == '1':\n"
        "        text = params['input'][0]['text']\n"
        "        event = json.loads(text).get('event') if text.startswith('{') else None\n"
        "        marker = Path(os.environ['LIFECYCLE_LOG']).with_suffix('.' + str(event))\n"
        "        if event and not marker.exists():\n"
        "            marker.touch()\n"
        "            emit({'id': request['id'], 'error': {'code': -32000, 'message': 'temporary event refusal'}})\n"
        "            continue\n"
        "    if method == 'initialize':",
    )
    peer = peer.replace(
        "        assert params['threadId'] == session and params['expectedTurnId'] == turn",
        "        if os.environ.get('LIFECYCLE_RACE') == '1' and params['input'][0]['text'].startswith('{'):\n"
        "            import time\n"
        "            deadline = time.monotonic() + 4\n"
        "            while not Path(os.environ['LIFECYCLE_RACE_ACK']).exists() and time.monotonic() < deadline:\n"
        "                time.sleep(.01)\n"
        "        assert params['threadId'] == session and params['expectedTurnId'] == turn",
    )
    target.write_text(peer)
    fake_codex.executable.write_text(script.replace(original_peer, str(target)))
    fake_codex.executable.chmod(0o755)


@pytest.mark.parametrize('idle,failure,submit,stop', [
    (True, False, True, False), (False, False, True, False),
    (True, True, False, False), (False, True, False, False),
    (True, False, False, True),
])
def test_send_returned_before_result_parent_consumes_and_acts(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    idle: bool,
    failure: bool,
    submit: bool,
    stop: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Send ACK precedes completion; both idle/running parents act without report polling."""
    root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    lifecycle_peer(fake_codex)
    _register_ready_ticket(installed_commands, root, body=BODY)
    batch = root / 'child.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{
        'ticket_id': '76', 'ticket_name': 'session-alias-control',
        'role': 'coding-team.engineer', 'instruction': 'initial',
    }]}))
    initial = root / 'initial.yml'
    initial.write_text(yaml.safe_dump({'tasks': [{
        'ticket_id': '76', 'ticket_name': 'session-alias-control', 'role': 'team-leader',
    }]}))
    log = tmp_path / 'actions.jsonl'
    child_file = tmp_path / 'child-alias'
    release = tmp_path / 'release'
    environment.pop('PYTHONPATH', None)
    environment.update({
        'GRAPHTRAJ_AGENT_RUNNER': str(installed_commands.runner),
        'CODEX_HOME': str(tmp_path / 'native-home'),
        'LIFECYCLE_LOG': str(log), 'LIFECYCLE_BATCH': str(batch),
        'LIFECYCLE_INPUT': str(tmp_path / 'inputs.jsonl'),
        'LIFECYCLE_CHILD': str(child_file), 'LIFECYCLE_RELEASE': str(release),
        'LIFECYCLE_CAUSE': _last_worldline_event(root),
        'LIFECYCLE_IDLE': str(int(idle)), 'LIFECYCLE_FAILURE': str(int(failure)),
        'LIFECYCLE_SUBMIT': str(int(submit)),
        'LIFECYCLE_REFUSE': str(int(stop or (submit and not idle))),
    })
    runner = root / '.graphtraj/runner'
    launched = run_process([str(installed_commands.runner), '--swarm-input', str(initial)],
                           cwd=root, env=environment, timeout=60)
    assert launched.returncode == 0, launched.stdout + launched.stderr
    parent = _mapping_for_role(runner, 'team-leader')
    child = _mapping_for_role(runner, 'engineer')
    assert child['parent'] == parent['alias']
    child_file.write_text(child['alias'])
    try:
        sent = run_process([
            str(installed_commands.runner), 'send', parent['alias'],
            '--instruction', 'followup', '--caused-by-event-id', _last_worldline_event(root),
        ], cwd=root, env=environment, timeout=30)
        assert sent.returncode == 0, sent.stdout + sent.stderr
        actions = _await_records(log, lambda rows: any('send_ack' in r for r in rows))
        receipt = next(r['send_ack'] for r in actions if 'send_ack' in r)
        assert receipt['send_status'] == 'sent'
        assert receipt['session'] == child['session']
        assert receipt['execution_id'] != child['execution_id']
        assert not (runner / 'sessions' / child['alias'] / 'execution.yml').exists()
        if idle:
            wait_for_file(runner / 'sessions' / parent['alias'] / 'execution.yml')
        if stop:
            from graphtraj.execution import execution_budget as budgets
            from test_task_budget_control import sample_stop

            evidence = root / '.graphtraj/state/tickets/76-session-alias-control'
            monitor = budgets.execution_budget_monitor(evidence, '76', 'session-alias-control')
            with (runner / 'sessions' / parent['alias'] / 'launch.yml').open('rb') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                before = sample_stop(monitor, monkeypatch)
                terminal_file = runner / 'sessions' / child['alias'] / 'execution.yml'
                wait_for_file(terminal_file)
                terminal = yaml.safe_load(terminal_file.read_text())
                assert terminal['outcome'] == 'interrupted' and terminal['budget_stopped']
            assert yaml.safe_load((evidence / 'execution-budget.yml').read_text())['started_at'] == before['started_at']
        release.touch()
        expected = 'interrupted' if stop else 'runtime-error' if failure else 'completed'
        actions = _await_records(log, lambda rows: any(
            r.get('acted', {}).get('event') == expected
            and r.get('details', {}).get('execution_id') == receipt['execution_id']
            for r in rows
        ))
        action = next(r for r in actions if r.get('details', {}).get('execution_id') == receipt['execution_id']
                      and r['acted']['event'] == expected)
        assert action['acted']['alias'] == child['alias']
        assert action['details']['session'] == child['session']
        assert action['report']['alias'] == parent['alias']
        if stop:
            actions = _await_records(log, lambda rows: any(
                r.get('acted', {}).get('event') == 'execution-budget-exceeded' for r in rows
            ))
            notices = runner / 'sessions' / child['alias'] / 'parent-notices.jsonl'
            retained = [json.loads(line) for line in notices.read_text().splitlines()]
            assert any('temporary event refusal' in r.get('error', {}).get('message', '') for r in retained)
            assert any(r['delivery'] == 'received' and r['identity'].get('type') == 'execution-budget-exceeded' for r in retained)
        if submit:
            submitted = next(r for r in actions if r.get('acted', {}).get('event') == 'result-submitted')
            assert submitted['details']['completion'] == 'Controlled result ready'
            assert submitted['details']['candidate']
        current = yaml.safe_load((runner / 'sessions' / parent['alias'] / 'mapping.yml').read_text())
        assert current['session'] == parent['session']
        assert len(list((runner / 'sessions').iterdir())) == 2
    finally:
        release.touch()
        run_process([str(installed_commands.runner), 'interrupt', parent['alias']],
                    cwd=root, env=environment, timeout=30)


def test_original_driver_keeps_its_result_when_parent_starts_successor(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """A parent reacts before notice ACK; original aggregation must retain its execution."""
    root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    lifecycle_peer(fake_codex)
    _register_ready_ticket(installed_commands, root, body=BODY)
    child_batch = root / 'child.yml'
    child_batch.write_text(yaml.safe_dump({'tasks': [{
        'ticket_id': '76', 'role': 'coding-team.engineer', 'instruction': 'initial',
    }]}))
    initial = root / 'initial.yml'
    initial.write_text(yaml.safe_dump({'tasks': [{'ticket_id': '76', 'role': 'team-leader'}]}))
    log = tmp_path / 'actions.jsonl'
    release = tmp_path / 'release'
    ready = tmp_path / 'ready'
    initial_release = tmp_path / 'initial-release'
    environment.pop('PYTHONPATH', None)
    environment.update({
        'GRAPHTRAJ_AGENT_RUNNER': str(installed_commands.runner),
        'CODEX_HOME': str(tmp_path / 'native-home'),
        'LIFECYCLE_LOG': str(log), 'LIFECYCLE_BATCH': str(child_batch),
        'LIFECYCLE_INPUT': str(tmp_path / 'inputs.jsonl'),
        'LIFECYCLE_RELEASE': str(release), 'LIFECYCLE_RACE': '1',
        'LIFECYCLE_CAUSE': _last_worldline_event(root),
        'LIFECYCLE_PARENT_READY': str(ready),
        'LIFECYCLE_RACE_ACK': str(tmp_path / 'race-ack'),
        'LIFECYCLE_INITIAL_RELEASE': str(initial_release),
        'LIFECYCLE_IDLE': '1', 'LIFECYCLE_FAILURE': '0',
    })
    runner = root / '.graphtraj/runner'
    with (tmp_path / 'launch.out').open('w') as output, (tmp_path / 'launch.err').open('w') as errors:
        process = subprocess.Popen(
            [str(installed_commands.runner), '--swarm-input', str(initial)],
            cwd=root, env=environment, stdout=output, stderr=errors,
        )
        try:
            parent = _mapping_for_role(runner, 'team-leader')
            child = _mapping_for_role(runner, 'engineer')
            sent = run_process([
                str(installed_commands.runner), 'send', parent['alias'],
                '--instruction', 'race', '--caused-by-event-id', _last_worldline_event(root),
            ], cwd=root, env=environment, timeout=20)
            assert sent.returncode == 0, sent.stdout + sent.stderr
            wait_for_file(ready)
            initial_release.touch()
            actions = _await_records(log, lambda rows: any('aggregate' in r for r in rows))
            acknowledgement = next(r['send_ack'] for r in actions if 'send_ack' in r)
            aggregate = next(yaml.safe_load(r['aggregate'].split('\n', 1)[1]) for r in actions if 'aggregate' in r)
            original = aggregate['tasks'][0]
            assert original['launch_status'] == 'completed', aggregate
            assert original['execution_id'] == child['execution_id']
            assert acknowledgement['execution_id'] != child['execution_id']
            assert acknowledgement['session'] == child['session']
        finally:
            initial_release.touch()
            release.touch()
            if 'parent' in locals():
                run_process([str(installed_commands.runner), 'interrupt', parent['alias']],
                            cwd=root, env=environment, timeout=30)
            process.wait(timeout=30)
