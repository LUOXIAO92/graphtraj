"""A GraphTraj DSH member finds its tools without the install's bin on the host PATH."""
import os
from pathlib import Path
import sys

import pytest

from graphtraj.configuration.project_roles import RolePreset
from graphtraj.configuration.role_definitions import ResolvedChildRole
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError, select_runtime_adapter


def executable(path: Path) -> Path:
    """Create an executable file, with its parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/bin/sh\n')
    path.chmod(0o755)
    return path


def install_dsh(host_bin: Path, package: Path) -> None:
    """Install DSH as a package with a link in ``host_bin``, as Homebrew lays it out."""
    entry = executable(package / 'lib/bin.js')
    (package / 'package.json').write_text('{"version": "0.2.2-alpha.2"}')
    host_bin.mkdir(parents=True, exist_ok=True)
    (host_bin / 'dsh').symlink_to(entry)


def preflight(tmp_path: Path) -> dict:
    """Run the member preflight and return its launch request."""
    role = ResolvedChildRole('author', 'Task responsibility', RolePreset(
        runtime='dsh', model='deepseek-official/deepseek-flash', base_url=None,
        api_key_env='DSH_TEST_KEY', worktree_access='read',
    ))
    return select_runtime_adapter('dsh').preflight_runtime_context(
        harness_root=tmp_path, git_common_directory=tmp_path / '.git', role=role,
        worktree=tmp_path / 'work', evidence=tmp_path / 'state', requested_skills=(),
    ).finalize().launch_document()['adapter_request']


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A venv whose Python links elsewhere, as ours does, and a PATH without the venv's bin."""
    interpreter = executable(tmp_path / 'conda/bin/python')
    python = tmp_path / 'venv/bin/python'
    python.parent.mkdir(parents=True)
    python.symlink_to(interpreter)
    monkeypatch.setattr(sys, 'executable', str(python))
    monkeypatch.setenv('PATH', str(tmp_path / 'host-bin'))
    monkeypatch.setenv('DSH_TEST_KEY', 'set')
    (tmp_path / 'host-bin').mkdir()
    return tmp_path


def test_a_member_starts_when_the_host_path_lacks_the_install_bin(host: Path) -> None:
    """The tool beside the running Python is used; the link is not followed into Conda."""
    install_dsh(host / 'host-bin', host / 'dsh')
    tool = executable(host / 'venv/bin/graphtraj-session')
    executable(host / 'conda/bin/graphtraj-session')
    request = preflight(host)
    assert request['tool'] == str(tool)
    assert request['executable'] == str(host / 'host-bin/dsh')


def test_the_tool_beside_python_wins_over_one_on_the_path(host: Path) -> None:
    """Another install on the PATH must not serve this install's member."""
    install_dsh(host / 'host-bin', host / 'dsh')
    tool = executable(host / 'venv/bin/graphtraj-session')
    executable(host / 'host-bin/graphtraj-session')
    assert preflight(host)['tool'] == str(tool)


def test_a_layout_without_a_sibling_script_uses_the_path(host: Path) -> None:
    """``pip install --user`` puts scripts away from the interpreter."""
    install_dsh(host / 'host-bin', host / 'dsh')
    tool = executable(host / 'host-bin/graphtraj-session')
    assert preflight(host)['tool'] == str(tool)


def test_a_sibling_that_cannot_run_is_not_the_tool(host: Path) -> None:
    """A file that is not executable falls through to the PATH."""
    install_dsh(host / 'host-bin', host / 'dsh')
    sibling = executable(host / 'venv/bin/graphtraj-session')
    sibling.chmod(0o644)
    assert not os.access(sibling, os.X_OK)
    tool = executable(host / 'host-bin/graphtraj-session')
    assert preflight(host)['tool'] == str(tool)


@pytest.mark.parametrize(('dsh', 'session', 'named', 'absent'), [
    (False, True, ['dsh'], ['graphtraj-session']),
    (True, False, ['graphtraj-session'], ['dsh']),
    (False, False, ['dsh', 'graphtraj-session'], []),
], ids=['dsh-missing', 'session-tool-missing', 'both-missing'])
def test_the_refusal_names_what_is_missing(
    host: Path, dsh: bool, session: bool, named: list[str], absent: list[str],
) -> None:
    """The code is unchanged; the message says which tool to install, and no other."""
    if dsh:
        install_dsh(host / 'host-bin', host / 'dsh')
    if session:
        executable(host / 'venv/bin/graphtraj-session')
    with pytest.raises(RuntimeAdapterError) as refused:
        preflight(host)
    assert refused.value.code == 'RUNTIME_UNAVAILABLE'
    words = refused.value.message.replace(',', ' ').replace('.', ' ').replace(':', ' ').split()
    assert [name for name in ('dsh', 'graphtraj-session') if name in words] == named
    assert not [name for name in absent if name in words]
