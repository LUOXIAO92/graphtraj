"""Task 439: a model-written inline role cannot choose a key source or destination."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphtraj.configuration.project_roles import ProjectRolesError, load_project_roles, parse_inline_role

REFUSED = [
    ({'base_url': 'https://attacker.invalid'}, 'base_url'),
    ({'pi': {'agent_dir': '/tmp/fake439-agent'}}, 'pi.agent_dir'),
    ({'pi': {'sandbox_python': '/tmp/fake439-python'}}, 'pi.sandbox_python'),
    ({'pi': {'sandbox_path': '/tmp/fake439-srt'}}, 'pi.sandbox_path'),
    ({'codex': {'approval': {'model': 'm', 'base_url': 'https://attacker.invalid'}}}, 'codex.approval.model'),
    ({'codex': {'approval': {'base_url': 'https://attacker.invalid'}}}, 'codex.approval.base_url'),
    ({'codex': {'approval': {'api_key_env': 'FAKE439_KEY'}}}, 'codex.approval.api_key_env'),
]


@pytest.mark.parametrize(('field', 'path'), REFUSED)
def test_a_new_inline_role_refuses_the_field(field: dict, path: str) -> None:
    role = {'coding_team.engineer': {'runtime': 'pi', 'model': 'm', **field}}
    with pytest.raises(ProjectRolesError) as caught:
        parse_inline_role(role)
    message = caught.value.diagnostics[0]
    assert path in message and 'connection: runtime/provider/model' in message
    assert 'roles.yml' in message


@pytest.mark.parametrize(('field', 'path'), REFUSED)
def test_a_retained_inline_role_keeps_loading(field: dict, path: str) -> None:
    role = {'coding_team.engineer': {'runtime': 'pi', 'model': 'm', **field}}
    assert parse_inline_role(role, retained=True)[1].model == 'm'


def test_inline_codex_approval_by_connection_is_allowed() -> None:
    _, preset = parse_inline_role({'a': {'runtime': 'codex', 'model': 'm',
                                         'codex': {'approval': {'connection': 'one/two/three'}}}})
    assert preset.codex == {'approval': {'connection': 'one/two/three'}}


@pytest.mark.parametrize(('field', 'path'), REFUSED)
def test_the_users_roles_file_keeps_the_field(tmp_path: Path, field: dict, path: str) -> None:
    import yaml

    folder = tmp_path / '.graphtraj'
    folder.mkdir()
    (folder / 'roles.yml').write_text(yaml.safe_dump(
        {'roles': {'engineer': {'runtime': 'pi', 'model': 'm', **field}}}), encoding='utf-8')
    roles = load_project_roles(tmp_path)
    assert 'engineer' in roles.presets
