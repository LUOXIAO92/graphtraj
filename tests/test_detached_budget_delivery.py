"""The original CLI/MCP call retains budget notices through native execution."""

import fcntl
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, app_server_peer, wait_for_file
from graphtraj.execution import execution_budget as budgets
from graphtraj.execution.runner_process import process_is_alive
from runner_fixtures import configure_harness
from test_task_budget_control import BODY, commands, sample_stop
from test_ticket_graph import _change_status, _register, _ticket


@pytest.mark.parametrize('surface,stop,inherited,stop_instruction', [
    (surface, stop, inherited, None)
    for surface in ('cli', 'mcp')
    for stop in (True, False)
    for inherited in (False, True)
] + [
    (surface, True, False, instruction)
    for surface in ('cli', 'mcp')
    for instruction in ('Use my external research method.\nPreserve the evidence.', '')
])
def test_bound_top_level_transport_lasts_until_execution_ends(
    commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
    stop: bool,
    inherited: bool,
    stop_instruction: str | None,
) -> None:
    """Return late stop evidence, or normal completion, before task acceptance."""
    root, worktrees, _, env = configure_harness(
        commands, temporary_git_repository, fake_codex, tmp_path,
    )
    # Setup no longer supplies Skills; remove the fixture's user methods too.
    for skills in (root / '.agents/skills', tmp_path / 'operator-home/.agents/skills'):
        if skills.exists():
            shutil.rmtree(skills)
    if stop_instruction is not None:
        config_path = root / '.graphtraj/config.yml'
        config = yaml.safe_load(config_path.read_text())
        config['agent_runner']['stop_instruction'] = stop_instruction
        config_path.write_text(yaml.safe_dump(config))
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'researcher': {'runtime': 'codex', 'model': 'selected'}},
        'role_tree': {'researcher': {}},
    }))
    ticket = _ticket('153', 'research')
    ticket['body'] = BODY + ticket['body']
    _register(commands, root, ticket)
    _change_status(commands, root, '153', 'ready')
    release = tmp_path / 'release'
    scenario = '''
import json, os, sys, time
from pathlib import Path
if sys.argv[1:3] == ['exec', '--help']:
    print('--sandbox')
    raise SystemExit(0)
sys.stdin.read()
Path('result.md').write_text('Retained research')
Path('running.txt').write_text(os.environ['GRAPHTRAJ_PARENT_ALIAS'])
while not Path(os.environ['PROBE_RELEASE']).exists():
    time.sleep(.02)
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'done'}}))
'''
    fake_codex.executable.write_text(app_server_peer(
        '#!' + sys.executable + '\n' + scenario, "os.environ['GRAPHTRAJ_PARENT_ALIAS']",
    ))
    env.update(CODEX_THREAD_ID='existing-external-caller', PROBE_RELEASE=str(release))
    tasks = {'tasks': [{'role': 'researcher', 'ticket_id': '153'}]}
    if surface == 'cli':
        batch = root / 'batch.yml'
        batch.write_text(yaml.safe_dump(tasks))
        command = [str(commands.runner), '--swarm-input', str(batch)]
        request = None
    else:
        # MCP binds the request's caller, never the server's environment thread.
        env.pop('CODEX_THREAD_ID')
        command = [str(commands.runner.with_name('graphtraj-mcp'))]
        request = json.dumps({
            'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
            'params': {'name': 'graphtraj',
                       'arguments': {'action': 'execute', 'feature': 'swarm',
                                     'arguments': tasks},
                       '_meta': {'threadId': 'existing-external-caller'}},
        }) + '\n'

    read_fd, write_fd = os.pipe() if inherited else (None, None)
    if inherited:
        env['GRAPHTRAJ_BUDGET_NOTICE_FD'] = str(write_fd)

    worktree = worktrees / '153-research'
    evidence = root / '.graphtraj/state/tickets/153-research'
    with ThreadPoolExecutor(max_workers=1) as executor:
        launched = executor.submit(
            subprocess.run, command, cwd=root, env=env, input=request,
            text=True, capture_output=True, timeout=45,
            pass_fds=(write_fd,) if inherited else (),
        )
        try:
            wait_for_file(worktree / 'running.txt', timeout=15)
            alias = (worktree / 'running.txt').read_text()
            directory = root / '.graphtraj/runner/sessions' / alias
            mapping = yaml.safe_load((directory / 'mapping.yml').read_text())
            assert not launched.done(), 'Original caller returned during native execution'
            before = yaml.safe_load((evidence / 'execution-budget.yml').read_text())
            if stop:
                monitor = budgets.execution_budget_monitor(evidence, '153', 'research')
                with (evidence / '.execution-budget-notices.lock').open('a+') as lock:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                    sample_stop(monitor, monkeypatch)
                    wait_for_file(directory / 'execution.yml', timeout=10)
                    terminal = yaml.safe_load((directory / 'execution.yml').read_text())
                    assert terminal['outcome'] == 'interrupted' and terminal['budget_stopped']
                    # Stop is physical even while notification delivery is blocked.
                    assert not process_is_alive(mapping['runtime_pid'])
                    assert not launched.done()
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            else:
                release.touch()
            result = launched.result(timeout=20)
            assert result.returncode == (int(stop) if surface == 'cli' else 0), result.stdout + result.stderr
            if surface == 'cli':
                document = yaml.safe_load(result.stdout)
            else:
                response = json.loads(result.stdout)['result']
                assert response['isError'] is stop, response
                document = response['structuredContent']
            if stop:
                assert document['tasks'][0]['launch_status'] == 'stopped'
                assert document['tasks'][0]['error']['code'] == 'EXECUTION_BUDGET_STOPPED'
            else:
                assert document['tasks'][0]['alias'] == alias
            assert not process_is_alive(mapping['worker_pid'])
            assert (worktree / 'result.md').read_text() == 'Retained research'
            assert (evidence / 'teams/1/traces' / alias / 'events.jsonl').read_text()
            state = yaml.safe_load((evidence / 'ticket.yml').read_text())
            assert state['current_candidate'] is None and state['status'] != 'integrated'
            usage = yaml.safe_load((evidence / 'execution-budget.yml').read_text())
            for field in ('started_at', 'allowance_minutes', 'sessions'):
                assert usage[field] == before[field]
            if stop:
                assert len(usage['parent_notices']) == 3
                assert all(n.get('channel_written') for n in usage['parent_notices'])
                assert all(not n['delivered'] for n in usage['parent_notices'])
                if inherited:
                    notices = [json.loads(line) for line in os.read(read_fd, 10000).splitlines()]
                    assert len(notices) == 3
                    assert notices[-1]['threshold']['kind'] == 'stochastic_stop'
                    assert notices[-1]['ticket'] == {'ticket_id': '153', 'ticket_name': 'research'}
                    assert 'stop_deliveries' not in document
                else:
                    deliveries = document['stop_deliveries']
                    assert len(deliveries) == 1
                    assert deliveries[0]['ticket'] == {'ticket_id': '153', 'ticket_name': 'research'}
                    assert deliveries[0]['triggered_at'] and deliveries[0]['delivered_at']
                    if stop_instruction == '':
                        assert 'instruction' not in deliveries[0]
                    elif stop_instruction is not None:
                        assert deliveries[0]['instruction'] == stop_instruction
                    else:
                        assert deliveries[0]['instruction']
            else:
                assert 'stop_deliveries' not in document
                assert yaml.safe_load((directory / 'execution.yml').read_text())['outcome'] == 'completed'
        finally:
            release.touch()
            if inherited:
                os.close(write_fd)
                os.close(read_fd)
