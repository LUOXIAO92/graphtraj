"""Public launch and cleanup around Git provisioning before Session registration."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, run_process, wait_for_file
from runner_fixtures import configure_harness
from test_task_recovery import installed_commands
from test_ticket_graph import _change_status, _register, _ticket


def _prepare(
    commands: InstalledCommands,
    repository: Path,
    runtime: FakeCodex,
    tmp_path: Path,
) -> tuple[Path, Path, Path, dict[str, str]]:
    """Set up and register an isolated ready Ticket through public commands."""
    root, worktrees, _, env = configure_harness(commands, repository, runtime, tmp_path)
    roles = root / '.graphtraj/roles.yml'
    document = yaml.safe_load(roles.read_text())
    document['role_tree'] = {'coding-team.engineer': {}}
    roles.write_text(yaml.safe_dump(document))
    _register(commands, root, _ticket('268', 'failed-start'))
    _change_status(commands, root, '268', 'ready')
    batch = root / 'swarm.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{
        'ticket_id': '268', 'role': 'coding-team.engineer',
    }]}))
    return root, worktrees / '268-failed-start', batch, env


def _launch(commands: InstalledCommands, root: Path, batch: Path, env: dict[str, str]):
    """Run the unchanged swarm input and expose its native response as evidence."""
    result = run_process([str(commands.runner), '--swarm-input', str(batch)],
                         cwd=root, env=env, timeout=30)
    print(result.stdout, result.stderr)
    return result


def _cleanup(commands: InstalledCommands, root: Path, env: dict[str, str]):
    """Request native cleanup without introducing an alias or changing state."""
    result = run_process([str(commands.runner), 'cleanup', '--ticket-id', '268'],
                         cwd=root, env=env, timeout=30)
    print(result.stdout, result.stderr)
    return result


def test_unrelated_absent_worktree_does_not_block_launch(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """Real prunable metadata stays untouched while the canonical launch succeeds."""
    root, worktree, batch, env = _prepare(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    absent = worktree.parent / '000-absent'
    foreign = worktree.parent / '001-foreign'
    for path in (absent, foreign):
        run_process(['git', 'worktree', 'add', '-b', path.name, str(path)],
                    cwd=temporary_git_repository).check_returncode()
    shutil.rmtree(absent)
    (foreign / 'unfinished.txt').write_text('Keep this foreign work.\n')
    before = run_process(['git', 'worktree', 'list', '--porcelain'],
                         cwd=temporary_git_repository).stdout
    assert 'prunable' in before
    launched = _launch(installed_commands, root, batch, env)
    assert launched.returncode == 0, launched.stdout + launched.stderr
    alias = yaml.safe_load(launched.stdout)['tasks'][0]['alias']
    wait_for_file(root / '.graphtraj/runner/sessions' / alias / 'execution.yml')
    after = run_process(['git', 'worktree', 'list', '--porcelain'],
                        cwd=temporary_git_repository).stdout
    assert str(absent) in after and 'prunable' in after
    assert (foreign / 'unfinished.txt').read_text() == 'Keep this foreign work.\n'


@pytest.mark.parametrize('recovery', ['retry', 'cleanup', 'dirty'])
def test_pre_registration_git_failure_retains_native_recovery(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    recovery: str,
) -> None:
    """A Git failure after add retains ownership, safe diagnostics and original Batch."""
    root, worktree, batch, env = _prepare(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    real_git = shutil.which('git')
    wrapper = fake_codex.executable.with_name('git')
    marker = tmp_path / 'git-failed-once'
    wrapper.write_text(
        '#!' + sys.executable + '\nimport os, sys\nfrom pathlib import Path\n'
        + f'marker = Path({str(marker)!r})\n'
        + f'if Path.cwd() == Path({str(worktree)!r}) and '
          "sys.argv[1:] == ['rev-parse', '--git-common-dir'] and not marker.exists():\n"
          "    marker.touch()\n"
          "    print('https://operator:secret-token@example.invalid authorization=secret-token', file=sys.stderr)\n"
          "    raise SystemExit(73)\n"
        + f'os.execv({real_git!r}, [{real_git!r}, *sys.argv[1:]])\n'
    )
    wrapper.chmod(0o755)
    failed = _launch(installed_commands, root, batch, env)
    assert failed.returncode == 1
    response = yaml.safe_load(failed.stdout)
    assert 'rev-parse' in response['tasks'][0]['error']['message']
    assert '73' in response['tasks'][0]['error']['message']
    assert 'secret-token' not in failed.stdout + failed.stderr
    retained = Path(response['retained_batch_file'])
    original = retained.read_bytes()
    input_before = batch.read_bytes()
    assert yaml.safe_load(original)['tasks'][0]['ticket_id'] == '268'
    sessions = root / '.graphtraj/runner/sessions'
    assert not sessions.exists() or not list(sessions.iterdir())
    ticket = root / '.graphtraj/state/tickets/268-failed-start/ticket.yml'
    before = ticket.read_bytes()
    state = yaml.safe_load(before)
    assert state['active_team_ordinal'] is None

    if recovery == 'dirty':
        (worktree / 'unfinished.txt').write_text('Keep my changes.\n')
        rejected = _cleanup(installed_commands, root, env)
        assert rejected.returncode == 1
        assert yaml.safe_load(rejected.stdout)['cleanup_status'] == 'refused'
        retried = _launch(installed_commands, root, batch, env)
        assert retried.returncode == 1
        assert yaml.safe_load(retried.stdout)['tasks'][0]['error']['code'] == 'worktree-conflict'
        assert (worktree / 'unfinished.txt').read_text() == 'Keep my changes.\n'
    else:
        env.update(FAKE_CODEX_LIFECYCLE_ACTION='complete-team-round',
                   GRAPHTRAJ_AGENT_RUNNER=str(installed_commands.runner))
        retried = _launch(installed_commands, root, batch, env)
        assert retried.returncode == 0, retried.stdout + retried.stderr
        alias = yaml.safe_load(retried.stdout)['tasks'][0]['alias']
        wait_for_file(sessions / alias / 'execution.yml')
        if recovery == 'cleanup':
            reported = run_process([str(installed_commands.runner), 'reports', alias],
                                   cwd=root, env=env)
            submission = yaml.safe_load(reported.stdout)['submissions'][-1]
            accepted = run_process([
                str(installed_commands.runner), 'decide-result',
                '--submission-id', submission['event_id'], '--commit', submission['candidate'],
                '--decision', 'accepted', '--reason', 'Fixture completed after native retry',
                '--evidence-ref', submission['evidence_refs'][0],
            ], cwd=root, env=env)
            assert accepted.returncode == 0, accepted.stdout + accepted.stderr
            integrated = run_process([
                str(installed_commands.product), 'ticket', 'integrate', '--ticket-id', '268',
                '--', sys.executable, '-c', 'pass',
            ], cwd=root, env=env, timeout=30)
            assert integrated.returncode == 0, integrated.stdout + integrated.stderr
            cleaned = _cleanup(installed_commands, root, env)
            assert cleaned.returncode == 0, cleaned.stdout + cleaned.stderr
            assert yaml.safe_load(cleaned.stdout)['cleanup_status'] == 'cleaned'
            assert not worktree.exists()
    assert retained.read_bytes() == original
    assert batch.read_bytes() == input_before


def test_foreign_canonical_worktree_is_not_retried_or_cleaned(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """A matching branch/path alone cannot establish failed-launch ownership."""
    root, worktree, batch, env = _prepare(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    run_process(['git', 'worktree', 'add', '-b', 'agent/268-failed-start', str(worktree)],
                cwd=temporary_git_repository).check_returncode()
    failed = _launch(installed_commands, root, batch, env)
    assert failed.returncode == 1
    assert yaml.safe_load(failed.stdout)['tasks'][0]['error']['code'] == 'worktree-conflict'
    refused = _cleanup(installed_commands, root, env)
    assert yaml.safe_load(refused.stdout)['error']['code'] == 'cleanup-ownership-mismatch'
    assert worktree.is_dir()
