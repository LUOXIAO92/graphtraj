"""An inherited budget notice descriptor receives a root execution's sampled stop."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, app_server_peer, wait_for_file
from graphtraj.execution import execution_budget as budgets
from runner_fixtures import configure_harness
from test_task_budget_control import BODY, commands, sample_stop
from test_task_graph import _change_status, _register, _task


SCENARIO = '''
import json, os, sys, time
from pathlib import Path
if sys.argv[1:3] == ['exec', '--help']:
    print('--sandbox')
    raise SystemExit(0)
sys.stdin.read()
Path('running.txt').write_text(os.environ['GRAPHTRAJ_PARENT_ALIAS'])
while not Path(os.environ['PROBE_RELEASE']).exists():
    time.sleep(.02)
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'done'}}))
'''


def test_inherited_notice_descriptor_receives_the_sampled_stop(
    commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI caller's inherited channel receives the stop and the call reports it."""
    root, worktrees, _, env = configure_harness(
        commands, temporary_git_repository, fake_codex, tmp_path,
    )
    for skills in (root / '.agents/skills', tmp_path / 'operator-home/.agents/skills'):
        if skills.exists():
            shutil.rmtree(skills)
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'researcher': {'runtime': 'codex', 'model': 'selected'}},
        'role_tree': {'researcher': {}},
    }))
    task = _task('153', 'research')
    task['body'] = BODY + task['body']
    _register(commands, root, task)
    _change_status(commands, root, '153', 'ready')
    release = tmp_path / 'release'
    fake_codex.executable.write_text(app_server_peer(
        '#!' + sys.executable + '\n' + SCENARIO, "os.environ['GRAPHTRAJ_PARENT_ALIAS']",
    ))
    batch = root / 'batch.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'role': 'researcher', 'task_id': '153'}]}))
    read_fd, write_fd = os.pipe()
    env.update(PROBE_RELEASE=str(release), GRAPHTRAJ_BUDGET_NOTICE_FD=str(write_fd))
    worktree = worktrees / '153-research'
    evidence = root / '.graphtraj/state/tasks/153-research'
    launched = None
    try:
        # The CLI caller and its Worker both hold the inherited channel.
        launched = subprocess.Popen(
            [str(commands.runner), '--swarm-input', str(batch)], cwd=root, env=env,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=(write_fd,),
        )
        wait_for_file(worktree / 'running.txt', timeout=15)
        alias = (worktree / 'running.txt').read_text()
        directory = root / '.graphtraj/runner/sessions' / alias
        sample_stop(budgets.execution_budget_monitor(evidence, '153', 'research'), monkeypatch)
        wait_for_file(directory / 'execution.yml', timeout=15)
        terminal = yaml.safe_load((directory / 'execution.yml').read_text())
        assert terminal['outcome'] == 'interrupted' and terminal['budget_stopped']
        output, error = launched.communicate(timeout=30)
        assert launched.returncode == 1, output + error
        stopped = yaml.safe_load(output)['tasks'][0]
        assert stopped['launch_status'] == 'stopped', output
        assert stopped['error']['code'] == 'EXECUTION_BUDGET_STOPPED'

        os.set_blocking(read_fd, False)
        received, deadline = b'', time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                received += os.read(read_fd, 65536)
            except BlockingIOError:
                pass
            if b'stochastic_stop' in received:
                break
            time.sleep(0.05)
        notices = [json.loads(line) for line in received.splitlines()]
        assert notices and notices[-1]['threshold']['kind'] == 'stochastic_stop', notices
        assert notices[-1]['type'] == 'execution-budget-exceeded'
        assert notices[-1]['task'] == {'task_id': '153', 'task_name': 'research'}
        usage = yaml.safe_load((evidence / 'execution-budget.yml').read_text())
        assert usage['stopped'] is True
        assert all(notice.get('channel_written') for notice in usage['parent_notices'])
    finally:
        release.touch()
        if launched is not None and launched.poll() is None:
            launched.kill()
        os.close(write_fd)
        os.close(read_fd)
