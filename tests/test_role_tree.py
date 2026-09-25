"""Explicit role-tree permissions are independent of execution presets."""

from pathlib import Path

import pytest
import yaml

from graphtraj.configuration.project_roles import ProjectRolesError, load_project_roles


def test_role_tree_limits_roots_and_direct_edges(tmp_path: Path) -> None:
    """Inline settings complete a declared role without granting new edges."""
    directory = tmp_path / '.graphtraj'
    directory.mkdir()
    (directory / 'roles.yml').write_text(yaml.safe_dump({
        'roles': {'researcher': {'runtime': 'codex', 'model': 'configured-model'}},
        'role_tree': {'researcher': {'analyst': {}}, 'team_leader': {}},
    }))
    roles = load_project_roles(tmp_path)
    assert roles.permits_dispatch(None, 'researcher')
    assert roles.permits_dispatch('researcher', 'analyst')
    assert not roles.permits_dispatch(None, 'analyst')
    assert not roles.permits_dispatch('team_leader', 'analyst')
    assert roles.dispatch_preset(None, 'researcher').model == 'configured-model'
    assert roles.dispatch_preset('researcher', {'analyst': {
        'runtime': 'codex', 'model': 'inline-model',
    }}).model == 'inline-model'
    with pytest.raises(ProjectRolesError):
        roles.dispatch_preset('researcher', 'analyst')
    with pytest.raises(ProjectRolesError):
        roles.dispatch_preset('team_leader', {'analyst': {
            'runtime': 'codex', 'model': 'inline-model',
        }})


@pytest.mark.parametrize('tree', [
    {'a': {'a': {}}}, {'a': {'b': {}}, 'b': {'a': {}}},
    {'a': None}, {'../a': {}}, ['a'],
])
def test_invalid_role_tree_is_rejected(tmp_path: Path, tree: object) -> None:
    """Reject malformed nodes and cycles even when spread across roots."""
    directory = tmp_path / '.graphtraj'
    directory.mkdir()
    (directory / 'roles.yml').write_text(yaml.safe_dump({'roles': {}, 'role_tree': tree}))
    with pytest.raises(ProjectRolesError):
        load_project_roles(tmp_path)


def test_repeated_roles_merge_only_explicit_edges(tmp_path: Path) -> None:
    """Multiple parents may select a shared role; descendants are not direct edges."""
    directory = tmp_path / '.graphtraj'
    directory.mkdir()
    path = directory / 'roles.yml'
    path.write_text(yaml.safe_dump({'roles': {}, 'role_tree': {
        'a': {'shared': {'leaf': {}}}, 'b': {'shared': {'other': {}}},
    }}))
    roles = load_project_roles(tmp_path)
    assert roles.permits_dispatch('a', 'shared')
    assert roles.permits_dispatch('b', 'shared')
    assert roles.permits_dispatch('shared', 'leaf')
    assert roles.permits_dispatch('shared', 'other')
    assert not roles.permits_dispatch('a', 'leaf')
    path.write_text(yaml.safe_dump({'roles': {
        'team_leader': {'runtime': 'codex', 'model': 'preserved'},
    }}))
    roles = load_project_roles(tmp_path)
    assert roles.preset('team_leader').model == 'preserved'
    assert not roles.permits_dispatch(None, 'team_leader')
    assert not roles.permits_dispatch('team_leader', 'engineer')
