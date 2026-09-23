"""Editable repository modules must not replace the installed Runner in a Worker."""

import subprocess

from test_managed_sessions import ManagedProject, launch_document, managed_project, observe


def test_launch_and_resume_use_installed_control_code(managed_project: ManagedProject) -> None:
    """A same-named Worktree package cannot run as the privileged control module."""
    root, cause, call, _ = managed_project
    worktree = root / '.graphtraj/.agent-worktrees/dev'
    package = worktree / 'graphtraj'
    package.mkdir()
    (package / '__init__.py').write_text('raise RuntimeError("Worktree module was imported")\n')
    subprocess.run(['git', 'add', 'graphtraj'], cwd=worktree, check=True, capture_output=True)
    subprocess.run(['git', 'commit', '-m', 'Add module isolation fixture'],
                   cwd=worktree, check=True, capture_output=True)

    created = call('launch', launch_document())['tasks'][0]
    alias = created['alias']
    original = observe(call, alias, 'running')['session']
    call('send', [alias, 'complete first turn', [cause]])
    observe(call, alias, 'idle', 'completed')
    call('send', [alias, 'hold', [cause]])
    assert observe(call, alias, 'running')['session'] == original
