"""GraphTraj's own agents data root stays out of a git project's change list (530).

DSH lists a turn's changed files by snapshotting the work tree through a
private index with ``git add --all``; untracked files count, ignored ones do
not. The first agents call in a fresh project writes ``.graphtraj/swarm``'s
``config.yml`` and ``live/config.lock``; neither may be listed, while the
user's own files still are. The rule lands only in ``.graphtraj/swarm``,
which GraphTraj chooses, never in a directory the user chose.
"""
import os
from pathlib import Path
import subprocess

from graphtraj.interfaces.agents import configured_archive, swarm_root


def git(repo: Path, *args: str, env: dict | None = None) -> str:
    return subprocess.run(['git', '-C', str(repo), *args], check=True, text=True,
                          capture_output=True, env=env).stdout


def test_first_use_lists_only_the_user_file(tmp_path: Path) -> None:
    project = tmp_path / 'project'
    project.mkdir()
    git(project, 'init', '-q')
    configured_archive(project)
    (project / 'user-edit.txt').write_text('mine\n')

    # As DSH does: a private index, add everything, list it.
    env = {**os.environ, 'GIT_INDEX_FILE': str(tmp_path / 'private-index')}
    git(project, 'add', '--all', env=env)
    assert git(project, 'ls-files', env=env).split() == ['user-edit.txt']
    root = swarm_root(project)
    assert (root / 'config.yml').is_file() and (root / 'live' / 'config.lock').is_file()
    assert (root / '.gitignore').read_text() == '*\n'
    assert not (project / '.gitignore').exists() and not (project / '.graphtraj' / '.gitignore').exists()


def test_an_existing_rule_and_choice_are_kept(tmp_path: Path) -> None:
    from graphtraj.interfaces.agents import default_archive
    root = tmp_path / 'swarm'
    root.mkdir()
    (root / '.gitignore').write_text('# mine\n')
    (root / 'config.yml').write_text('save_normalized_sessions: false\n')
    assert default_archive(root)['save_normalized_sessions'] is False
    assert (root / '.gitignore').read_text() == '# mine\n'


def test_a_failed_rule_write_does_not_block_first_use(tmp_path: Path) -> None:
    from graphtraj.interfaces.agents import default_archive
    root = tmp_path / 'swarm'
    (root / '.gitignore').mkdir(parents=True)  # a directory: open('x') raises
    assert default_archive(root)['save_normalized_sessions'] is True
