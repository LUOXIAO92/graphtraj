"""A Task branch head whose content dev already holds exactly counts as integrated."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from graphtraj.execution.runner_cleanup import _content_integrated


def git(repository: Path, *arguments: str) -> str:
    return subprocess.run(['git', *arguments], cwd=repository, check=True, text=True,
                          capture_output=True).stdout.strip()


def commit(repository: Path, name: str, text: str, message: str) -> str:
    (repository / name).write_text(text)
    git(repository, 'add', name)
    git(repository, 'commit', '-qm', message)
    return git(repository, 'rev-parse', 'HEAD')


def history(tmp_path: Path) -> SimpleNamespace:
    """dev merges the accepted candidate and another line; the Task branch merges them separately."""
    repository = tmp_path / 'repository'
    repository.mkdir()
    git(repository, 'init', '-q', '-b', 'dev')
    git(repository, 'config', 'user.email', 'test@example.com')
    git(repository, 'config', 'user.name', 'test')
    commit(repository, 'base.txt', 'base\n', 'base')
    git(repository, 'checkout', '-qb', 'other')
    other = commit(repository, 'other.txt', 'other\n', 'other line')
    git(repository, 'checkout', '-qb', 'task', 'dev')
    candidate = commit(repository, 'task.txt', 'task\n', 'candidate')
    git(repository, 'checkout', '-q', 'dev')
    git(repository, 'merge', '-q', '--no-ff', '-m', 'dev merges candidate', candidate)
    git(repository, 'merge', '-q', '--no-ff', '-m', 'dev merges other', other)
    git(repository, 'checkout', '-q', 'task')
    git(repository, 'merge', '-q', '--no-ff', '-m', 'task merges other', other)
    head = git(repository, 'rev-parse', 'HEAD')
    dev = git(repository, 'rev-parse', 'dev')
    assert subprocess.run(['git', 'merge-base', '--is-ancestor', head, dev], cwd=repository).returncode == 1
    return SimpleNamespace(repository=repository, candidate=candidate, head=head, dev=dev)


def target(case: SimpleNamespace, candidate: str | None = None, dev: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(candidate=candidate or case.candidate, project=SimpleNamespace(
        repository=case.repository, dev_commit=dev or case.dev))


def test_a_content_integrated_head_is_accepted_with_a_recreatable_record(tmp_path: Path) -> None:
    case = history(tmp_path)
    accepted = _content_integrated(target(case), case.head)
    assert accepted == {'branch_head': case.head, 'tree': git(case.repository, 'rev-parse', 'dev^{tree}')}


def test_an_extra_unintegrated_change_is_refused(tmp_path: Path) -> None:
    case = history(tmp_path)
    extra = commit(case.repository, 'extra.txt', 'extra\n', 'not in dev')
    assert _content_integrated(target(case), extra) is None


def test_a_conflicting_head_is_refused(tmp_path: Path) -> None:
    case = history(tmp_path)
    changed = commit(case.repository, 'task.txt', 'task branch\n', 'task edit')
    git(case.repository, 'checkout', '-q', 'dev')
    dev = commit(case.repository, 'task.txt', 'dev edit\n', 'dev edit')
    assert _content_integrated(target(case, dev=dev), changed) is None


def test_a_candidate_outside_dev_is_refused(tmp_path: Path) -> None:
    case = history(tmp_path)
    assert _content_integrated(target(case, candidate=case.head), case.head) is None
