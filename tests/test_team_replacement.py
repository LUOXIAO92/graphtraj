"""Actual multi-member replacement preserves stopped descendants and ownership."""

import json
from pathlib import Path

import yaml

from conftest import FakeCodex, InstalledCommands, wait_for_file
from test_task_recovery import command, events, installed_commands, prepare


def test_replacing_parent_keeps_old_descendants_stopped_and_bound_to_old_session(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """A new parent cannot inherit control of the original parent's children."""
    root, env, task = prepare(
        installed_commands, temporary_git_repository, fake_codex, tmp_path, 'researcher', child=True,
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
        assert yaml.safe_load((runner / child / 'execution.yml').read_text())['outcome'] == 'interrupted'
        Path(env['RECOVERY_RELEASE']).touch()
        replaced = command(installed_commands, root, env, 'replace', alias, '--actor', 'user',
                           '--caused-by-event-id', cause)
        assert replaced.returncode == 0, replaced.stdout + replaced.stderr
        successor = yaml.safe_load(replaced.stdout)['replacement_alias']
        assert successor != alias
        assert yaml.safe_load((runner / child / 'mapping.yml').read_text()) == original_child
        assert original_child['parent'] == alias
        assert (runner / alias / 'stop.yml').read_bytes() == marker
        reports = yaml.safe_load(command(installed_commands, root, env, 'reports', successor).stdout)
        assert reports['submissions']  # model-side ownership assertion completed
        team = yaml.safe_load((root / '.graphtraj/state/tickets/154-recovery/teams/1/team.yml').read_text())
        assert {member['session_ref'] for member in team['members'].values()} == {successor, child}
    finally:
        Path(env['RECOVERY_RELEASE']).touch()
        command(installed_commands, root, env, 'interrupt', alias)
