"""S2 reproduction: the actual CLI binding ends before a detached budget stop."""
import os
import sys
import time
from pathlib import Path
import yaml
import pytest
from conftest import (FakeCodex, InstalledCommands, fake_codex, temporary_git_repository, isolated_runner_environment,
                      app_server_peer, run_process, wait_for_file)
from test_task_budget_control import commands, BODY, sample_stop
from runner_fixtures import configure_harness
from test_ticket_graph import _register, _change_status, _ticket
from graphtraj.execution import execution_budget as budgets
from graphtraj.execution.runner_process import process_is_alive


@pytest.mark.xfail(strict=True, reason="S2: external caller binding has no transport after CLI exit")
def test_bound_top_level_transport_after_cli_return(
    commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require late delivery through the actual binding, after launch has returned."""
    root, _, _, env = configure_harness(commands, temporary_git_repository, fake_codex, tmp_path)
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
import os, sys, time
from pathlib import Path
if sys.argv[1:3] == ['exec', '--help']:
    print('--sandbox')
    raise SystemExit(0)
sys.stdin.read()
Path('running.txt').touch()
while not Path(os.environ['PROBE_RELEASE']).exists():
    time.sleep(.02)
'''
    fake_codex.executable.write_text(app_server_peer('#!' + sys.executable + '\n' + scenario,
                                                    "os.environ['GRAPHTRAJ_PARENT_ALIAS']"))
    env.update(CODEX_THREAD_ID='existing-external-caller', PROBE_RELEASE=str(release))
    batch = root / 'batch.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'role': 'researcher', 'ticket_id': '153'}]}))
    launched = run_process([str(commands.runner), '--swarm-input', str(batch)],
                           cwd=root, env=env, timeout=30)
    assert launched.returncode == 0, launched.stdout + launched.stderr
    document = yaml.safe_load(launched.stdout)
    task = document['tasks'][0]
    assert task['launch_status'] == 'launched'
    directory = root / '.graphtraj/runner/sessions' / task['alias']
    evidence = root / '.graphtraj/state/tickets/153-research'
    try:
        wait_for_file(Path(task['worktree_path']) / 'running.txt')
        mapping = yaml.safe_load((directory / 'mapping.yml').read_text())
        monitor = budgets.execution_budget_monitor(evidence, '153', 'research')
        sample_stop(monitor, monkeypatch)
        wait_for_file(directory / 'execution.yml', timeout=10)
        terminal = yaml.safe_load((directory / 'execution.yml').read_text())
        assert terminal['outcome'] == 'interrupted' and terminal['budget_stopped']
        deadline = time.monotonic() + 15
        while process_is_alive(mapping['worker_pid']) and time.monotonic() < deadline:
            time.sleep(.02)
        assert not process_is_alive(mapping['worker_pid']), 'Worker still draining notices'
        usage = yaml.safe_load((evidence / 'execution-budget.yml').read_text())
        facts = {'launch_returned': True, 'physical_stop': terminal['outcome'],
                 'worker_exited': True, 'caller_stop_deliveries': document.get('stop_deliveries', []),
                 'notices': [{'key': n['key'], 'delivered': n['delivered'],
                              'channel_written': n.get('channel_written', False)}
                             for n in usage['leader_notices']]}
        print(yaml.safe_dump(facts))
        # This fails on the rejected candidate and the S1-only correction.
        assert all(n.get('channel_written', False) for n in usage['leader_notices']), facts
    finally:
        release.touch()
