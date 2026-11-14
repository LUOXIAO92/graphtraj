"""A reopened, cleaned Task's original Team recovers through public operations (Task 476).

Production 44729d5b: after integration and cleanup removed the Task Worktree,
``task revise --reopen`` left approved_recovery failing with "The requested
Agent alias mapping is invalid." until a dispatch (even a refused one) rebuilt
the Worktree. Each public operation must now work directly.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, run_process, wait_for_file
from graphtraj.execution import approved_recovery as recovery
from graphtraj.graph.delivery_worldline import read_worldline
from test_approved_recovery import _recovery_target, invoke
from test_task_integration import accepted_task  # noqa: F401  (fixture)


def _git(cwd: Path, *arguments: str) -> str:
    return subprocess.check_output(['git', *arguments], cwd=cwd, text=True).strip()


@pytest.fixture
def reopened(accepted_task: tuple, installed_commands: InstalledCommands, fake_codex: FakeCodex,
             tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple:
    """Integrate, clean up and reopen Task 83 through the installed public commands."""
    from graphtraj.graph.task_protocol import TASK_PROPERTIES
    from graphtraj.interfaces import tools

    root, worktrees, state, candidate = accepted_task
    environment = {**os.environ, 'HOME': str(tmp_path / 'operator-home'),
                   'PATH': str(fake_codex.executable.parent) + os.pathsep + os.environ['PATH'],
                   'FAKE_CODEX_LOG': str(fake_codex.log_file)}
    integrated = run_process(
        [str(installed_commands.product), 'task', 'integrate', '--task-id', '83', '--',
         sys.executable, '-c', 'pass'], cwd=root, env=environment)
    assert integrated.returncode == 0, integrated.stderr
    task = state / 'tasks/83-integration'
    worktree = root / yaml.safe_load((task / 'task.yml').read_text())['worktree']
    cleaned = run_process([str(installed_commands.runner), 'cleanup', '--task-id', '83'],
                          cwd=root, env=environment, timeout=15)
    assert cleaned.returncode == 0, cleaned.stdout + cleaned.stderr
    assert not worktree.exists()
    details = tools.read_current_graph({'details': ['83']}, cwd=root).document['details']['83']
    definition = {key: details[key] for key in TASK_PROPERTIES} | {
        'current_definition': details['current_definition']}
    (root / 'reopen-evidence.md').write_text('The integrated candidate needs another round.\n')
    revision = root / 'reopen.yml'
    revision.write_text(yaml.safe_dump({
        'product_preserving': True, 'tasks': [definition], 'reopen_task_ids': ['83'],
        'caused_by_event_ids': [read_worldline(state, root)[-1]['event_id']],
        'evidence_refs': ['reopen-evidence.md'],
    }))
    revised = run_process([str(installed_commands.product), 'task', 'revise',
                           '--revision-file', str(revision)], cwd=root, env=environment)
    assert revised.returncode == 0, revised.stdout + revised.stderr
    assert yaml.safe_load((task / 'task.yml').read_text())['status'] == 'reworking'
    _, _, mapping, arguments = _recovery_target(root, state, monkeypatch)
    arguments['caused_by_event_ids'] = [yaml.safe_load(revised.stdout)['event_id']]
    history = {'worldline': read_worldline(state, root), 'dev': worktrees / 'dev',
               'branch_exists': subprocess.run(
                   ['git', 'rev-parse', '--verify', '--quiet', yaml.safe_load((task / 'task.yml').read_text())['branch']],
                   cwd=worktrees / 'dev', capture_output=True).returncode == 0,
               'mapping': (root / '.graphtraj/runner/sessions' / mapping['alias'] / 'mapping.yml').read_bytes()}
    return root, task, worktree, mapping, arguments, environment, candidate, history


def _assert_restored(root: Path, worktree: Path, candidate: str, history: dict) -> None:
    """The canonical Worktree is back at current dev, which contains the integrated candidate."""
    repository = history['dev']
    dev = _git(repository, 'rev-parse', 'HEAD')
    assert worktree.is_dir() and not worktree.is_symlink()
    assert _git(worktree, 'rev-parse', 'HEAD') == dev
    branch = yaml.safe_load((root / '.graphtraj/state/tasks/83-integration/task.yml').read_text())['branch']
    assert _git(worktree, 'symbolic-ref', 'HEAD') == 'refs/heads/' + branch
    assert subprocess.run(['git', 'merge-base', '--is-ancestor', candidate, dev], cwd=repository).returncode == 0
    assert (worktree / '.state').resolve() == (root / '.graphtraj/state/tasks/83-integration').resolve()
    assert not _git(worktree, 'status', '--porcelain', '--untracked-files=all')
    # Cleanup deleted the integrated branch; dev retains its history.
    assert history['branch_exists'] is False


def _assert_history_kept(root: Path, task: Path, history: dict) -> None:
    after = read_worldline(task.parent.parent, root)
    assert after[:len(history['worldline'])] == history['worldline']
    assert not any(event['event'] in {'swarm-refused', 'dispatch-refused'} for event in after)


def test_budget_only_recovery_after_reopening_a_cleaned_task(reopened: tuple) -> None:
    """resume=false with restore_active grants time without any prior dispatch."""
    root, task, worktree, mapping, arguments, _, candidate, history = reopened
    from graphtraj.runtimes.runtime_adapter import recovery_review

    with recovery_review(lambda proposal: {'decision': 'accept'}):
        result = invoke(root, {**arguments, 'resume': False})
    assert result['recovery_status'] == 'applied', result
    assert yaml.safe_load((task / 'execution-budget.yml').read_text())['approved_minutes'] == 7
    _assert_restored(root, worktree, candidate, history)
    _assert_history_kept(root, task, history)


def test_resumed_recovery_after_reopening_a_cleaned_task(
    reopened: tuple, fake_codex: FakeCodex, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resume=true continues the original Leader Session in the restored Worktree."""
    root, task, worktree, mapping, arguments, environment, candidate, history = reopened
    for key in ('HOME', 'PATH', 'FAKE_CODEX_LOG'):
        monkeypatch.setenv(key, environment[key])
    received = tmp_path / 'recovery-received.json'
    script = fake_codex.executable.read_text().replace(
        "lifecycle_action = os.environ.get('FAKE_CODEX_LIFECYCLE_ACTION')",
        f"Path({str(received)!r}).write_text(json.dumps({{'argv': sys.argv, 'cwd': os.getcwd()}}))\n"
        "lifecycle_action = None",
    )
    fake_codex.executable.write_text(script)
    from graphtraj.runtimes.runtime_adapter import recovery_review

    with recovery_review(lambda proposal: {'decision': 'accept'}):
        result = invoke(root, arguments)
    assert result['recovery_status'] == 'resumed', result
    wait_for_file(received)
    observation = json.loads(received.read_text())
    assert observation['argv'][-2:] == [mapping['session'], '-']
    _assert_restored(root, worktree, candidate, history)
    _assert_history_kept(root, task, history)
    assert yaml.safe_load((root / '.graphtraj/runner/sessions' / mapping['alias'] / 'mapping.yml').read_text()
                          )['session'] == mapping['session']


def test_swarm_after_reopening_a_cleaned_task(reopened: tuple, installed_commands: InstalledCommands) -> None:
    """A new dispatch for the reopened Task starts directly in the restored Worktree."""
    root, task, worktree, mapping, arguments, environment, candidate, history = reopened
    batch = root / 'reopen-batch.yml'
    batch.write_text(yaml.safe_dump({'tasks': [
        {'task_id': '83', 'task_name': 'integration', 'role': 'coding-team.team-leader'}]}))
    launched = run_process([str(installed_commands.runner), '--swarm-input', str(batch)],
                           cwd=root, env={**environment, 'FAKE_CODEX_LIFECYCLE_ACTION': ''})
    assert launched.returncode == 0, launched.stdout + launched.stderr
    _assert_restored(root, worktree, candidate, history)
    _assert_history_kept(root, task, history)


def test_missing_worktree_error_names_cause_and_public_operations(
    reopened: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the Worktree cannot be restored the refusal says why and what to use."""
    root, task, worktree, mapping, arguments, _, _, history = reopened
    from graphtraj.runtimes.runtime_adapter import recovery_review

    worktree.parent.mkdir(parents=True, exist_ok=True)
    worktree.write_text('A foreign file occupies the Task Worktree path.\n')
    with recovery_review(lambda proposal: {'decision': 'accept'}):
        result = invoke(root, arguments)
    assert result['recovery_status'] == 'resume-failed', result
    text = json.dumps(result['error'])
    assert 'alias mapping is invalid' not in text, result
    assert str(worktree) in text and 'swarm' in text, result
