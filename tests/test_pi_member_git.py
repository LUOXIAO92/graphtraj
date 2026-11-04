"""What a Pi child can do with Git: grants and environment against a real repository."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from graftling.pi.execution import PiExecution


# Read before any test replaces HOME: this file is never to be granted.
REAL_GITCONFIG = Path.home() / '.gitconfig'
IDENTITY_VARIABLES = ('GIT_AUTHOR_NAME', 'GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_NAME', 'GIT_COMMITTER_EMAIL')


def git(cwd: Path, *arguments: str, env: dict | None = None) -> str:
    """Run real Git in ``cwd`` and return its stripped standard output."""
    completed = subprocess.run(['git', *arguments], cwd=cwd, env=env, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


@pytest.fixture
def layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Build a primary checkout with two linked Worktrees and an empty host Home.

    Every Git setting the host could inherit is removed, so each test states the
    identity it means to have.
    """
    root = tmp_path.resolve()
    for key in tuple(os.environ):
        if key.startswith('GIT_'):
            monkeypatch.delenv(key)
    monkeypatch.delenv('XDG_CONFIG_HOME', raising=False)
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')

    home = root / 'host-home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))

    primary, member, sibling = root / 'primary', root / 'worktrees/member', root / 'worktrees/sibling'
    primary.mkdir()
    git(primary, 'init', '-q', '-b', 'main')
    (primary / 'README.md').write_text('primary\n')
    git(primary, 'add', 'README.md')
    git(primary, '-c', 'user.name=Setup', '-c', 'user.email=setup@example.test', 'commit', '-q', '-m', 'Base')
    git(primary, 'worktree', 'add', '-q', '-b', 'member', str(member))
    git(primary, 'worktree', 'add', '-q', '-b', 'sibling', str(sibling))
    return {'root': root, 'home': home, 'primary': primary, 'member': member, 'sibling': sibling,
            'common': Path(git(member, 'rev-parse', '--path-format=absolute', '--git-common-dir'))}


def set_host_identity(layout: dict, name: str | None = 'Host Person', email: str | None = 'host@example.test') -> None:
    """Write the given identity to the host's global config, as ``git config --global`` does."""
    lines = ['[user]']
    if name:
        lines.append(f'\tname = {name}')
    if email:
        lines.append(f'\temail = {email}')
    (layout['home'] / '.gitconfig').write_text('\n'.join(lines) + '\n')


def launch(layout: dict, access: str) -> tuple[list, dict, dict]:
    """Prepare one child's launch in the ``member`` Worktree and return argv, policy and environment."""
    directory = layout['root'] / 'data/native/member'
    directory.mkdir(parents=True, exist_ok=True)
    agent_dir = layout['root'] / 'agent'
    agent_dir.mkdir(exist_ok=True)
    request = {'executable': '/bin/pi', 'provider': 'p', 'model': 'm', 'worktree_path': str(layout['member']),
               'agent_dir': str(agent_dir), 'instructions': '', 'sandbox_python': sys.executable,
               'sandbox_path': os.environ['PATH'], 'worktree_access': access, 'provider_domain': 'p.example',
               'git_common_directory': str(layout['common'])}
    turn = PiExecution(request, '', directory, None, None, directory / 'trace.jsonl', None)
    argv, env = turn.prepare_launch(None)
    return argv, json.loads((directory / 'pi-policy.json').read_text()), env


def covered(paths: list[str], target: Path) -> bool:
    """Whether any granted path is ``target`` or a directory containing it."""
    return any(target.resolve().is_relative_to(Path(path).resolve()) for path in paths)


def test_write_member_reads_and_writes_the_git_data_a_commit_needs(layout: dict) -> None:
    """Its admin directory, objects and refs are readable and writable; config and hooks stay protected."""
    _, policy, _ = launch(layout, 'write')
    filesystem = policy['filesystem']

    admin = Path(git(layout['member'], 'rev-parse', '--absolute-git-dir'))
    assert admin.is_relative_to(layout['common'])
    for target in (admin, layout['common'], layout['common'] / 'objects', layout['common'] / 'refs'):
        assert covered(filesystem['allowRead'], target), target
        assert covered(filesystem['allowWrite'], target), target

    assert covered(filesystem['denyWrite'], layout['common'] / 'config')
    assert covered(filesystem['denyWrite'], layout['common'] / 'hooks')


def test_write_member_cannot_reach_other_working_files(layout: dict) -> None:
    """No grant covers a sibling Worktree, the primary checkout's files or their shared parents."""
    _, policy, _ = launch(layout, 'write')
    filesystem = policy['filesystem']

    for target in (layout['sibling'], layout['sibling'] / 'README.md', layout['primary'],
                   layout['primary'] / 'README.md', layout['member'].parent):
        assert not covered(filesystem['allowRead'], target), target
        assert not covered(filesystem['allowWrite'], target), target


def test_write_member_commits_with_the_host_identity(layout: dict) -> None:
    """The returned environment commits in the linked Worktree with no global config to read."""
    set_host_identity(layout)
    _, policy, env = launch(layout, 'write')

    # As in the sandbox, the child cannot use the Home the host resolved it from.
    empty = layout['root'] / 'empty-home'
    empty.mkdir()
    child = {**env, 'HOME': str(empty)}
    (layout['member'] / 'work.txt').write_text('done\n')
    git(layout['member'], 'add', 'work.txt', env=child)
    git(layout['member'], 'commit', '-q', '-m', 'Member work', env=child)

    assert git(layout['member'], 'log', '-1', '--format=%s|%an|%ae|%cn|%ce') == (
        'Member work|Host Person|host@example.test|Host Person|host@example.test')
    assert git(layout['primary'], 'rev-parse', 'member') == git(layout['member'], 'rev-parse', 'HEAD')

    # A global config Git tried to read would stop it, as the denied one did.
    unreadable = layout['root'] / 'malformed-home'
    unreadable.mkdir()
    (unreadable / '.gitconfig').write_text('[user\n')
    git(layout['member'], 'status', '--short', env={**env, 'HOME': str(unreadable)})

    for path in (REAL_GITCONFIG, layout['home'] / '.gitconfig'):
        assert not covered(policy['filesystem']['allowRead'], path), path
        assert not covered(policy['filesystem']['allowWrite'], path), path
        assert str(path) not in env.values()


@pytest.mark.parametrize('name,email,expected', [
    (None, None, {}),
    ('Host Person', None, {'GIT_AUTHOR_NAME': 'Host Person', 'GIT_COMMITTER_NAME': 'Host Person'}),
    (None, 'host@example.test', {'GIT_AUTHOR_EMAIL': 'host@example.test', 'GIT_COMMITTER_EMAIL': 'host@example.test'}),
])
def test_write_member_gets_only_the_identity_that_is_set(layout: dict, name: str, email: str, expected: dict) -> None:
    """An unset value adds no variable and launch still proceeds."""
    set_host_identity(layout, name, email)
    argv, _, env = launch(layout, 'write')

    assert argv
    assert env['GIT_CONFIG_GLOBAL'] == os.devnull
    assert {key: env[key] for key in IDENTITY_VARIABLES if key in env} == expected


def test_write_member_launches_when_host_git_is_missing(layout: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """A host that cannot run Git adds no identity and does not fail the launch."""
    set_host_identity(layout)
    no_git = layout['root'] / 'no-git'
    no_git.mkdir()
    monkeypatch.setenv('PATH', str(no_git))

    argv, _, env = launch(layout, 'write')

    assert argv
    assert env['GIT_CONFIG_GLOBAL'] == os.devnull
    assert not set(IDENTITY_VARIABLES) & set(env)


def test_read_member_gets_no_git_access_or_variables(layout: dict) -> None:
    """A read-only child has no Git directory grant and no Git variable added, identity or not."""
    set_host_identity(layout)
    _, policy, env = launch(layout, 'read')
    filesystem = policy['filesystem']

    admin = Path(git(layout['member'], 'rev-parse', '--absolute-git-dir'))
    for target in (admin, layout['common'], layout['common'] / 'objects', layout['sibling']):
        assert not covered(filesystem['allowRead'], target), target
        assert not covered(filesystem['allowWrite'], target), target
    assert not covered(filesystem['allowWrite'], layout['member'])

    assert 'GIT_CONFIG_GLOBAL' not in env
    assert not set(IDENTITY_VARIABLES) & set(env)
