"""Retirement and replacement retries through installed public operations."""

import json
from pathlib import Path
import subprocess

import yaml
import pytest

from conftest import FakeCodex, InstalledCommands, wait_for_file
from test_task_recovery import command, events, installed_commands, prepare


def test_retire_refuses_running_descendant_then_preserves_history(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """A terminal parent is insufficient; retirement neither interrupts nor deletes."""
    root, env, task = prepare(installed_commands, temporary_git_repository, fake_codex,
                              tmp_path, 'researcher', child=True)
    alias = task['alias']
    runner = root / '.graphtraj/runner/sessions'
    child = json.loads((Path(task['worktree_path']) / 'child.json').read_text())['alias']
    try:
        wait_for_file(runner / alias / 'execution.yml')
        original = yaml.safe_load((runner / alias / 'mapping.yml').read_text())
        refused = command(installed_commands, root, env, 'retire', alias)
        assert refused.returncode == 1 and 'replacement-not-stopped' in refused.stdout
        assert (runner / alias / 'mapping.yml').is_file()
        assert not (runner / alias / 'stop.yml').exists()
        assert not (runner / child / 'execution.yml').exists()
        stopped = command(installed_commands, root, env, 'interrupt', alias)
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
        evidence = {name: (runner / alias / name).read_bytes()
                    for name in ('launch.yml', 'execution.yml', 'events.jsonl')}
        retired = subprocess.run(
            [str(installed_commands.runner.with_name('graphtraj-tool'))], cwd=root, env=env,
            input=json.dumps({'action': 'execute', 'feature': 'retire', 'arguments': {'alias': alias}}) + '\n',
            text=True, capture_output=True, timeout=30,
        )
        assert retired.returncode == 0, retired.stdout + retired.stderr
        assert 'retired' in retired.stdout
        assert not (runner / alias).exists()
        assert yaml.safe_load((Path(original['trace_file']).parent / 'runner/session.yml').read_text())['retirement']['mapping'] == original
        assert all((Path(original['trace_file']).parent / 'runner' / name).read_bytes() == content for name, content in evidence.items())
        assert Path(task['worktree_path']).is_dir()
        assert yaml.safe_load((runner / child / 'mapping.yml').read_text())['parent'] == alias
        team = yaml.safe_load((root / '.graphtraj/state/tickets/154-recovery/teams/1/team.yml').read_text())
        assert alias not in {member['session_ref'] for member in team['members'].values()}
        assert command(installed_commands, root, env, 'reports', alias).returncode == 0
        assert command(installed_commands, root, env, 'status', alias).returncode == 0
        stale = command(installed_commands, root, env, 'send', alias, '--instruction', 'Work',
                        '--caused-by-event-id', events(root)[-1]['event_id'])
        assert stale.returncode == 1 and 'session-retired' in stale.stdout
        assert command(installed_commands, root, env, 'retire', alias).returncode == 0
    finally:
        Path(env['RECOVERY_RELEASE']).touch()
        command(installed_commands, root, env, 'interrupt', alias)


def test_replace_retries_after_retirement_without_reviving_or_duplicating(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """A repeatable Runtime preflight failure leaves a retired seat for public retry."""
    root, env, task = prepare(installed_commands, temporary_git_repository, fake_codex,
                              tmp_path, 'researcher')
    alias = task['alias']
    runner = root / '.graphtraj/runner/sessions'
    successor = None
    try:
        assert command(installed_commands, root, env, 'interrupt', alias).returncode == 0
        cause = events(root)[-1]['event_id']
        roles_file = root / '.graphtraj/roles.yml'
        roles = yaml.safe_load(roles_file.read_text())
        roles['roles']['researcher']['instructions'] = 'missing-role-instructions.txt'
        roles_file.write_text(yaml.safe_dump(roles))
        failed = command(installed_commands, root, env, 'replace', alias, '--caused-by-event-id', cause)
        assert failed.returncode == 1, failed.stdout + failed.stderr
        result = yaml.safe_load(failed.stdout)
        assert result['completed_actions'] == ['retired']
        assert result['replace_status'] == 'failed' and result['error']
        assert not (runner / alias).exists()
        assert len(list(runner.iterdir())) == 0
        (root / 'missing-role-instructions.txt').write_text('Continue the accepted task.\n')
        Path(env['RECOVERY_RELEASE']).touch()
        replaced = command(installed_commands, root, env, 'replace', alias, '--caused-by-event-id', cause)
        assert replaced.returncode == 0, replaced.stdout + replaced.stderr
        successor = yaml.safe_load(replaced.stdout)['replacement_alias']
        wait_for_file(runner / successor / 'execution.yml')
        repeated = command(installed_commands, root, env, 'replace', alias, '--caused-by-event-id', cause)
        assert repeated.returncode == 0, repeated.stdout + repeated.stderr
        assert yaml.safe_load(repeated.stdout)['replacement_alias'] == successor
        assert len(list(runner.iterdir())) == 1
        assert not (runner / alias).exists()
    finally:
        Path(env['RECOVERY_RELEASE']).touch()
        command(installed_commands, root, env, 'interrupt', successor or alias)


def test_retire_unknown_termination_does_not_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreachable terminated Worker is uncertainty, not implicit stop authority."""
    from types import SimpleNamespace

    from graphtraj.execution import runner_control, runner_retirement, runner_status
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.interfaces.cli.projection import invoke_tool
    from test_direct_control_authority import _record_direct_session

    runner = tmp_path / 'runner'
    alias = '240-retirement-handover0-researcher@unknown'
    _record_direct_session(runner, alias, 'researcher', None)
    monkeypatch.setattr(runner_retirement, 'discover_project',
                        lambda *args, **kwargs: SimpleNamespace(runner_directory=runner))
    monkeypatch.setattr(runner_status, 'caller_alias', lambda directory: None)

    def unreachable(*args, **kwargs) -> dict:
        """Represent an owner that no longer answers native status."""
        raise RunnerError('operation-failed', 'Owner unavailable')

    monkeypatch.setattr(runner_status, 'session_operation', unreachable)
    monkeypatch.setattr(runner_status, '_unresponsive_status', lambda *args: {'activity': 'abnormal'})
    monkeypatch.setattr(runner_control, 'respond_to_abnormal_session',
                        lambda *args: pytest.fail('Retirement must not trigger interruption'))
    with pytest.raises(RunnerError, match='must be stopped'):
        invoke_tool('retire', {'alias': alias}, cwd=tmp_path)
    assert (runner / 'sessions' / alias / 'mapping.yml').is_file()
    assert not (runner / 'sessions' / alias / 'stop.yml').exists()
