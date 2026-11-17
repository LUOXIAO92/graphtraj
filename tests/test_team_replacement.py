"""Actual multi-member replacement preserves stopped descendants and ownership."""

import json
import os
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, wait_for_file
from graphtraj.execution import execution_budget as budgets
from test_task_budget_control import sample_stop
from test_task_recovery import command, events, installed_commands, prepare


def test_replacing_parent_keeps_old_descendants_stopped_and_bound_to_old_session(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new parent cannot inherit control of the original parent's children."""
    root, env, task = prepare(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
        'researcher', child=True, preflight_failure=True,
    )
    alias = task['alias']
    child = json.loads((Path(task['worktree_path']) / 'child.json').read_text())['alias']
    runner = root / '.graphtraj/runner/sessions'
    cause = events(root)[-1]['event_id']
    try:
        wait_for_file(runner / alias / 'execution.yml')
        assert yaml.safe_load((runner / alias / 'execution.yml').read_text())['outcome'] == 'completed'
        refused = command(installed_commands, root, env, 'replace', alias, '--caused-by-event-id', cause)
        assert refused.returncode == 1 and 'replacement-not-stopped' in refused.stdout
        stopped = command(installed_commands, root, env, 'interrupt', alias)
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
        members = yaml.safe_load(stopped.stdout)['members']
        assert {member['alias'] for member in members} == {alias, child}
        original_child = yaml.safe_load((runner / child / 'mapping.yml').read_text())
        marker = (runner / alias / 'stop.yml').read_bytes()
        # A returned interrupt without a pending record has the terminal record readable (474).
        assert all('execution_record' not in member for member in members)
        assert yaml.safe_load((runner / child / 'execution.yml').read_text())['outcome'] == 'interrupted'
        # Historical preflight allocation has no launch, identity or owner.
        residue = runner / '154-recovery-handover0-researcher@unstarted'
        residue.mkdir()
        (residue / 'events.jsonl').touch()
        Path(env['RECOVERY_RELEASE']).touch()
        replaced = command(installed_commands, root, env, 'replace', alias, '--actor', 'user',
                           '--caused-by-event-id', cause)
        assert replaced.returncode == 0, replaced.stdout + replaced.stderr
        successor = yaml.safe_load(replaced.stdout)['replacement_alias']
        wait_for_file(runner / successor / 'execution.yml')
        assert successor != alias
        assert list(residue.iterdir()) == [residue / 'events.jsonl']
        assert (residue / 'events.jsonl').read_bytes() == b''
        assert yaml.safe_load((runner / child / 'mapping.yml').read_text()) == original_child
        assert original_child['parent'] == alias
        assert (root / '.graphtraj/state/tasks/154-recovery/teams/1/traces' / alias / 'runner/stop.yml').read_bytes() == marker
        reports = yaml.safe_load(command(installed_commands, root, env, 'reports', successor).stdout)
        assert reports['submissions']  # model-side ownership assertion completed
        team = yaml.safe_load((root / '.graphtraj/state/tasks/154-recovery/teams/1/team.yml').read_text())
        assert {member['session_ref'] for member in team['members'].values()} == {successor, child}

        task_directory = root / '.graphtraj/state/tasks/154-recovery'
        monitor = budgets.execution_budget_monitor(task_directory, '154', 'recovery')
        sample_stop(monitor, monkeypatch)
        accounting = yaml.safe_load((task_directory / 'execution-budget.yml').read_text())
        original_successor = yaml.safe_load((runner / successor / 'mapping.yml').read_text())
        continued = command(installed_commands, root, env, 'continue', '--task-id', '154',
                            '--caused-by-event-id', events(root)[-1]['event_id'])
        assert continued.returncode == 0, continued.stdout + continued.stderr
        assert [item['alias'] for item in yaml.safe_load(continued.stdout)['tasks']] == [successor]
        wait_for_file(runner / successor / 'execution.yml')
        assert yaml.safe_load((runner / successor / 'execution.yml').read_text())['outcome'] == 'completed'
        current_successor = yaml.safe_load((runner / successor / 'mapping.yml').read_text())
        assert current_successor['session'] == original_successor['session']
        assert current_successor['execution_id'] != original_successor['execution_id']
        assert yaml.safe_load((runner / child / 'mapping.yml').read_text()) == original_child
        assert (root / '.graphtraj/state/tasks/154-recovery/teams/1/traces' / alias / 'runner/stop.yml').read_bytes() == marker
        after = yaml.safe_load((task_directory / 'execution-budget.yml').read_text())
        assert not after['stopped']
        for field in ('started_at', 'allowance_minutes', 'sessions', 'stopping_checks'):
            assert after[field] == accounting[field]
    finally:
        Path(env['RECOVERY_RELEASE']).touch()
        command(installed_commands, root, env, 'interrupt', alias)


SLOW_TERMINAL = '''
import sys, time
if 'graphtraj.execution.runner_worker' in sys.orig_argv:
    from pathlib import Path
    import graphtraj.execution.runner_io as runner_io
    original = runner_io.write_yaml_durably
    def slow_write(path, document):
        if Path(path).name == 'execution.yml':
            time.sleep(3)
        return original(path, document)
    runner_io.write_yaml_durably = slow_write
'''


def test_interrupt_returns_after_slow_terminal_record(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Worker slow to record its end still has that record readable when interrupt returns."""
    controls = tmp_path / 'slow-terminal'
    controls.mkdir()
    (controls / 'sitecustomize.py').write_text(SLOW_TERMINAL)
    # The installed test environment loads a PYTHONPATH sitecustomize into -I
    # Workers only while BUDGET_CLOCK is set (conftest graphtraj_test_clock).
    monkeypatch.setenv('BUDGET_CLOCK', '1')
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join(filter(None, [str(controls), os.environ.get('PYTHONPATH')])))
    root, env, task = prepare(
        installed_commands, temporary_git_repository, fake_codex, tmp_path, 'researcher', child=True,
    )
    alias = task['alias']
    child = json.loads((Path(task['worktree_path']) / 'child.json').read_text())['alias']
    runner = root / '.graphtraj/runner/sessions'
    try:
        wait_for_file(runner / alias / 'execution.yml', timeout=30)
        assert not (runner / child / 'execution.yml').exists()
        stopped = command(installed_commands, root, env, 'interrupt', alias)
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
        member = next(item for item in yaml.safe_load(stopped.stdout)['members'] if item['alias'] == child)
        assert member == {'alias': child, 'interrupt_status': 'interrupted'}
        assert yaml.safe_load((runner / child / 'execution.yml').read_text())['outcome'] == 'interrupted'
    finally:
        Path(env['RECOVERY_RELEASE']).touch()
        command(installed_commands, root, env, 'interrupt', alias)


def test_replacement_drives_registered_child_without_send(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """The replacement's Worker executes its retained Batch after registration."""
    root, env, task = prepare(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
        'researcher', replacement_child=True,
    )
    alias = task['alias']
    successor = None
    runner = root / '.graphtraj/runner/sessions'
    try:
        stopped = command(installed_commands, root, env, 'interrupt', alias)
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
        cause = events(root)[-1]['event_id']
        Path(env['RECOVERY_RELEASE']).touch()
        replaced = command(installed_commands, root, env, 'replace', alias,
                           '--caused-by-event-id', cause)
        assert replaced.returncode == 0, replaced.stdout + replaced.stderr
        successor = yaml.safe_load(replaced.stdout)['replacement_alias']
        child_file = Path(task['worktree_path']) / 'child.json'
        wait_for_file(child_file)
        registered = json.loads(child_file.read_text())
        assert registered['launch_status'] == 'registered'
        child = registered['alias']
        wait_for_file(runner / child / 'mapping.yml')
        mapping = yaml.safe_load((runner / child / 'mapping.yml').read_text())
        assert mapping['parent'] == successor
        assert mapping['session']
        wait_for_file(runner / child / 'execution.yml')
        assert yaml.safe_load((runner / child / 'execution.yml').read_text())['outcome'] == 'completed'
    finally:
        Path(env['RECOVERY_RELEASE']).touch()
        command(installed_commands, root, env, 'interrupt', successor or alias)
