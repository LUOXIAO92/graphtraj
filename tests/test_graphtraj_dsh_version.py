"""GraphTraj's DSH members follow the agents DSH version rule."""
from pathlib import Path
import shutil

import pytest

from graphtraj.configuration.project_roles import RolePreset
from graphtraj.configuration.role_definitions import ResolvedChildRole
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError, select_runtime_adapter


def preflight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, package: str | None) -> dict:
    """Run the member preflight against a DSH whose ``package.json`` holds ``package``."""
    root = tmp_path / 'dsh'
    (root / 'lib').mkdir(parents=True)
    if package is not None:
        (root / 'package.json').write_text(package)
    monkeypatch.setattr(shutil, 'which', lambda name: str(root / 'lib' / 'bin.js')
                        if name == 'dsh' else '/installed/graphtraj-session')
    monkeypatch.setenv('DSH_TEST_KEY', 'set')
    role = ResolvedChildRole('author', 'Task responsibility', RolePreset(
        runtime='dsh', model='deepseek-official/deepseek-flash', base_url=None,
        api_key_env='DSH_TEST_KEY', worktree_access='read',
    ))
    return select_runtime_adapter('dsh').preflight_runtime_context(
        harness_root=tmp_path, git_common_directory=tmp_path / '.git', role=role,
        worktree=tmp_path / 'work', evidence=tmp_path / 'state', requested_skills=(),
    ).finalize().launch_document()


@pytest.mark.parametrize('version', ['0.2.0-rc.2', '0.2.0-rc.10', '0.2.0', '0.2.1-alpha.5', '0.2.2-alpha.2', '1.0.0'])
def test_a_member_accepts_the_floor_and_later(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str) -> None:
    """Including the locally installed 0.2.2-alpha.2 that the exact pin refused."""
    request = preflight(tmp_path, monkeypatch, f'{{"version": "{version}"}}')['adapter_request']
    assert request['package'] == str(tmp_path / 'dsh/package.json')


@pytest.mark.parametrize(('package', 'installed'), [
    ('{"version": "0.2.0-rc.1"}', '0.2.0-rc.1'), ('{"version": "0.2.0-beta.4"}', '0.2.0-beta.4'),
    ('{"version": "0.1.9"}', '0.1.9'), ('{"version": "latest"}', 'latest'), ('{"version": 2}', '2'),
    ('{}', 'unknown'), ('not json', 'unknown'), (None, 'unknown'),
])
def test_an_earlier_or_unreadable_version_keeps_the_same_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, package: str | None, installed: str,
) -> None:
    """The code stays RUNTIME_UNSUPPORTED; the message is the agents rule's own."""
    with pytest.raises(RuntimeAdapterError) as refused:
        preflight(tmp_path, monkeypatch, package)
    assert (refused.value.code, refused.value.message) == (
        'RUNTIME_UNSUPPORTED', f'DSH 0.2.0-rc.2 or later is required (installed {installed}).')
