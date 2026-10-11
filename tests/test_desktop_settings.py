"""Human desktop settings through the public restricted native pipe."""

import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from contextlib import contextmanager
from threading import Barrier

import pytest
import yaml

from graphtraj.execution.runner_status import runtime_caller
from graphtraj.interfaces.desktop_settings import serve
from test_role_organization import project, roles_path, snapshot


def call(root: Path, request: dict) -> list[dict]:
    """Exchange exactly one human desktop request without an approval reply."""
    output = io.StringIO()
    serve(io.StringIO(json.dumps(request) + "\n"), output, root)
    return [json.loads(line) for line in output.getvalue().splitlines()]


def read(root: Path) -> dict:
    """Read the exact safe editable view from the native desktop entry."""
    reply = call(root, {"action": "read"})[-1]
    assert reply["failed"] is False, reply
    return reply["result"]


def draft(root: Path, **fields: object) -> dict:
    """Create a draft against the currently observed revision."""
    return {"action": "save", "revision": read(root)["revision"], "edits": {"analyst": fields}}


def test_save_preserves_unedited_fields_secrets_and_other_files(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A native save changes only requested fields and exposes no stored key."""
    document = yaml.safe_load(roles_path(project).read_text())
    document["roles"]["analyst"]["codex"] = {
        "future_extension": {"api_key": "hidden-existing-value"},
        "approval": {"model": "review-model", "base_url": "https://example.invalid/v1", "api_key_env": "REVIEW_KEY"},
    }
    roles_path(project).write_text(yaml.safe_dump(document))
    monkeypatch.setenv("ENGINEER_KEY", "never-render-this-secret")
    before = snapshot(project)
    request = draft(project, model="edited-model", base_url="https://example.invalid/v1", api_key_env="NEW_KEY", reasoning_effort="medium")
    replies = call(project, request)
    assert len(replies) == 1
    assert replies[-1]["result"]["applied"] is True
    assert "hidden-existing-value" not in json.dumps(replies)
    assert "never-render-this-secret" not in json.dumps(replies)
    after = snapshot(project)
    assert {name for name in before if before[name] != after[name]} == {".graphtraj/roles.yml"}
    saved = yaml.safe_load(roles_path(project).read_text())
    assert saved["roles"]["coding_team"] == document["roles"]["coding_team"]
    assert saved["roles"]["analyst"]["codex"] == document["roles"]["analyst"]["codex"]
    assert saved["role_tree"] == document["role_tree"]


def test_write_failure_keeps_original(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An atomic writer failure reports the cause without replacing configuration."""
    from graphtraj.execution import role_organization

    def fail(path: Path, document: dict) -> None:
        """Represent an unavailable destination before atomic replacement."""
        raise OSError("Controlled destination is read-only")

    monkeypatch.setattr(role_organization, "write_yaml_durably", fail)
    before = snapshot(project)
    result = call(project, draft(project, model="unsaved"))[-1]
    assert result["failed"] and "read-only" in result["error"]
    assert result["error_kind"] == "write"
    assert snapshot(project) == before


def test_revision_conflict_before_save(project: Path) -> None:
    """An external save cannot be overwritten by an editor's old revision."""
    stale = draft(project, model="stale-edit")
    assert call(project, draft(project, model="external-native-change"))[-1]["result"]["applied"]
    before = snapshot(project)
    replies = call(project, stale)
    assert len(replies) == 1 and replies[0]["failed"]
    assert "changed while editing" in replies[0]["error"]
    assert replies[0]["error_kind"] == "conflict"
    assert snapshot(project) == before


@pytest.mark.parametrize("fields", [
    {"runtime": "pi", "model": "provider/"},
    {"runtime": "pi", "model": "/model"},
    {"api_key_env": "sk-plaintext-secret"},
    {"approval_api_key_env": "sk-plaintext-secret"},
    {"approval_base_url": "https://user:secret@example.invalid/v1"},
    {"base_url": "https://user:secret@example.invalid/v1"},
    {"model": ""}, {"runtime": "unknown"}, {"reasoning_effort": "impossible"},
    {"instructions": "missing-instructions.txt"}, {"api_key": "not-supported"},
])
def test_invalid_drafts_fail_before_review(project: Path, fields: dict) -> None:
    """Invalid settings and unsupported prompt layers fail without side effects."""
    before = snapshot(project)
    replies = call(project, draft(project, **fields))
    assert len(replies) == 1 and replies[0]["failed"]
    assert "sk-plaintext-secret" not in json.dumps(replies)
    assert "user:secret" not in json.dumps(replies)
    assert snapshot(project) == before


def test_native_prompt_clear_rename_and_nested_edges(project: Path) -> None:
    """Renaming arbitrary grouped roles preserves nested trees and role fields."""
    path = roles_path(project)
    document = yaml.safe_load(path.read_text())
    document["roles"]["coding_team"]["engineer"]["developer_prompt"] = "old layer"
    document["role_tree"] = {"owner": {"coding_team.team_leader": {"coding_team.engineer": {"analyst": {}}}}}
    path.write_text(yaml.safe_dump(document))
    request = {"action": "save", "revision": read(project)["revision"],
               "edits": {"coding_team.engineer": {"developer_prompt": None}},
               "renames": {"coding_team.engineer": "research.builder"},
               "remove_edges": [{"parent": "coding_team.engineer", "child": "analyst"}]}
    reply = call(project, request)[-1]
    assert reply["failed"] is False, reply
    saved = yaml.safe_load(path.read_text())
    assert saved["roles"]["research"]["builder"] == {"runtime": "codex", "model": "engineer-model", "api_key_env": "ENGINEER_KEY"}
    assert saved["role_tree"] == {"owner": {"coding_team.team_leader": {"research.builder": {}}}}


@pytest.mark.parametrize("identity", ["actual-agent", None])
def test_agent_caller_and_fabricated_approval_are_rejected(project: Path, identity: str | None) -> None:
    """Even a bound Main cannot use human desktop saves or forge request authority."""
    request = draft(project, model="forbidden")
    before = snapshot(project)
    with runtime_caller(project / ".graphtraj" / "runner", identity):
        assert call(project, {"action": "read"})[-1]["failed"]
        assert call(project, request)[-1]["failed"]
    for key, value in (("decision", "accept"), ("human", True), ("approved", True)):
        assert call(project, {**request, key: value})[-1]["failed"]
    assert snapshot(project) == before


def test_concurrent_saves_do_not_overwrite_one_another(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two direct saves of one revision can commit only one candidate."""
    from graphtraj import file_lock

    barrier = Barrier(2, timeout=5)
    revision = read(project)["revision"]
    original_lock = file_lock.replacement_lock

    @contextmanager
    def simultaneous(path: Path):
        """Prepare both public saves before entering the real replacement lock."""
        barrier.wait()
        with original_lock(path):
            yield

    monkeypatch.setattr(file_lock, "replacement_lock", simultaneous)

    def save(model: str) -> dict:
        """Use one owned native pipe per independent editor."""
        return call(project, {"action": "save", "revision": revision,
                              "edits": {"analyst": {"model": model}}})[-1]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save, ("first-model", "second-model")))
    assert sorted(result["failed"] for result in results) == [False, True]
    successful = next(result["result"] for result in results if not result["failed"])
    assert read(project)["roles"] == successful["roles"]


def test_team_creation_reparent_deletion_and_empty_recovery(project: Path) -> None:
    """Whole tree edits preserve custom presets and allow a recoverable empty tree."""
    original = yaml.safe_load(roles_path(project).read_text())
    state = read(project)
    tree = {**state['role_tree'], 'research.lead': {'research.worker': {'research.leaf': {}}}}
    request = {'action': 'save', 'revision': state['revision'], 'role_tree': tree,
               'edits': {f'research.{name}': {'runtime': 'codex', 'model': f'{name}-model'}
                         for name in ('lead', 'worker', 'leaf')}}
    preview = call(project, {**request, 'action': 'preview'})[-1]
    assert not preview['failed'] and not preview['result']['applied']
    assert yaml.safe_load(roles_path(project).read_text()) == original
    saved = call(project, request)[-1]['result']
    assert saved['role_tree'] == tree
    assert yaml.safe_load(roles_path(project).read_text())['roles']['coding_team'] == original['roles']['coding_team']

    # Delete only the middle node and explicitly reconnect its leaf.
    tree['research.lead'] = {'research.leaf': {}}
    saved = call(project, {'action': 'save', 'revision': saved['revision'],
                          'remove_presets': ['research.worker'], 'role_tree': tree})[-1]['result']
    assert 'research.worker' not in saved['roles']
    assert ['research.lead', 'research.leaf'] in saved['edges']
    renamed = call(project, {'action': 'save', 'revision': saved['revision'],
                            'renames': {'research.lead': 'renamed.lead', 'research.leaf': 'renamed.leaf'}})[-1]['result']
    assert renamed['role_tree']['renamed.lead'] == {'renamed.leaf': {}}

    # Delete all configured roles and trees, then create a new unambiguous root.
    empty = call(project, {'action': 'save', 'revision': renamed['revision'],
                          'remove_presets': list(renamed['roles']), 'role_tree': {}})[-1]['result']
    assert empty['roles'] == empty['role_tree'] == {}
    recovered = call(project, {'action': 'save', 'revision': empty['revision'],
                              'edits': {'new.root': {'runtime': 'codex', 'model': 'root-model'}},
                              'role_tree': {'new.root': {}}})[-1]['result']
    assert recovered['role_tree'] == {'new.root': {}}


@pytest.mark.parametrize('change', [
    {'remove_presets': ['coding_team.engineer']},
    {'role_tree': {'missing': {}}},
    {'role_tree': {'analyst': {'analyst': {}}}},
    {'edits': {'new.role': {'model': 'missing-runtime'}}},
])
def test_invalid_tree_changes_are_atomic(project: Path, change: dict) -> None:
    """No dangling references, cycles or incomplete new roles reach review or disk."""
    before = snapshot(project)
    replies = call(project, {'action': 'save', 'revision': read(project)['revision'], **change})
    assert len(replies) == 1 and replies[0]['failed']
    assert snapshot(project) == before


def test_global_connection_role_reference_and_project_isolation(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A reviewed global connection resolves from two isolated project role catalogs."""
    from graphtraj.configuration.project_roles import load_project_roles
    from test_role_organization import CONFIG

    home = project / 'user-home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('USERPROFILE', str(home))
    assert Path.home() == home
    connection = {'version': 1, 'runtimes': {'shared': {'runtime': 'codex', 'home': str(home / 'native'),
        'providers': {'custom': {'base_url': 'https://provider.invalid/v1', 'api_key_env': 'CUSTOM_KEY',
            'models': {'model': {'id': 'custom-model', 'alias': 'My model', 'source': 'manual', 'supported_efforts': ['low']}}}}}}}
    initial = call(project, {'scope': 'user', 'action': 'read'})[-1]['result']
    saved = call(project, {'scope': 'user', 'action': 'save', 'expected_revision': initial['revision'],
                          'catalog': connection})[-1]['result']
    assert saved['catalog'] == connection
    second = project / 'other'
    (second / '.graphtraj').mkdir(parents=True)
    (second / '.graphtraj/config.yml').write_text(CONFIG)
    (second / '.graphtraj/roles.yml').write_text('roles: {}\n')
    untouched = snapshot(second)
    request = {'action': 'save', 'revision': read(project)['revision'], 'edits': {
        'coding_team.engineer': {'connection': 'shared/custom/model', 'runtime': None,
                                'model': None, 'api_key_env': None, 'reasoning_effort': 'low',
                                'approval_model': 'review-model', 'approval_base_url': 'https://review.invalid/v1',
                                'approval_api_key_env': 'REVIEW_KEY'}},
    }
    reply = call(project, request)[-1]
    assert not reply['failed'], reply
    assert snapshot(second) == untouched
    resolved = load_project_roles(project).dispatch_preset('coding_team.team_leader', 'coding_team.engineer')
    assert (resolved.runtime, resolved.model, resolved.runtime_home, resolved.reasoning_effort) == (
        'codex', 'custom-model', str(home / 'native'), 'low')
    assert resolved.api_key_env == 'CUSTOM_KEY'
    assert call(second, {'scope': 'user', 'action': 'read'})[-1]['result']['catalog'] == connection
    assert read(project)['roles']['coding_team.engineer']['connection'] == 'shared/custom/model'


def test_standalone_global_settings_save_directly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The global page works before adding a project without creating project state."""
    monkeypatch.setenv('HOME', str(tmp_path))
    # Windows resolves Path.home() from USERPROFILE rather than HOME.
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    assert Path.home() == tmp_path
    state = call(tmp_path, {'scope': 'user', 'action': 'read'})[-1]['result']
    catalog = {'version': 1, 'runtimes': {'local': {'runtime': 'codex', 'providers': {}}}}
    request = {'scope': 'user', 'action': 'save', 'expected_revision': state['revision'], 'catalog': catalog}
    assert call(tmp_path, request)[-1]['result']['applied']
    assert {path.name for path in (tmp_path / '.graphtraj').iterdir()} == {'connections.lock', 'connections.yml'}


def test_staged_team_rename_and_new_child_round_trip(project: Path) -> None:
    """The renderer's rename/add payload persists one group and preserves untouched settings."""
    path = roles_path(project)
    (project / 'instructions.txt').write_text('Retained role instructions.', encoding='utf-8')
    original = {'runtime': 'codex', 'model': 'original', 'reports': ['report.md'],
                'instructions': 'instructions.txt', 'codex': {'retained_custom_field': 'preserved'}}
    path.write_text(yaml.safe_dump({'roles': {'a': {'root': original}}, 'role_tree': {'a.root': {}}}))
    request = {
        'action': 'save', 'revision': read(project)['revision'],
        'edits': {'a.worker': {'runtime': 'codex', 'model': 'worker-model'}},
        'renames': {'a.root': 'b.root', 'a.worker': 'b.worker'},
        'add_edges': [], 'remove_edges': [], 'remove_presets': [],
        'role_tree': {'a.root': {'a.worker': {}}},
    }
    reply = call(project, request)[-1]
    assert not reply['failed'], reply
    reloaded = read(project)
    assert reloaded['role_tree'] == {'b.root': {'b.worker': {}}}
    assert set(reloaded['roles']) == {'b.root', 'b.worker'}
    assert reloaded['roles']['b.worker']['model'] == 'worker-model'
    assert yaml.safe_load(path.read_text())['roles'] == {
        'b': {'root': original, 'worker': {'runtime': 'codex', 'model': 'worker-model'}},
    }


def test_new_team_uses_global_references_and_preserves_legacy_roles(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """New root/child references survive Save and reopen without migrating old roles."""
    from graphtraj.configuration.project_roles import load_project_roles

    home = project / 'isolated-user'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('USERPROFILE', str(home))
    monkeypatch.setenv('CUSTOM_KEY', 'controlled-secret-must-not-be-copied')
    # Custom Codex providers retain the existing explicit approval-route rule.
    config_path = project / '.graphtraj/config.yml'
    config = yaml.safe_load(config_path.read_text())
    config['codex'] = {'approval': {'model': 'review-model',
                                  'base_url': 'https://review.invalid/v1',
                                  'api_key_env': 'REVIEW_KEY'}}
    config_path.write_text(yaml.safe_dump(config))
    initial = call(project, {'scope': 'user', 'action': 'read'})[-1]['result']
    catalog = {'version': 1, 'runtimes': {'shared': {'runtime': 'codex', 'providers': {
        'custom': {'base_url': 'https://provider.invalid/v1', 'api_key_env': 'CUSTOM_KEY',
                   'models': {'model': {'id': 'chosen-model', 'source': 'manual',
                                        'supported_efforts': ['low']}}},
    }}}}
    saved_catalog = call(project, {'scope': 'user', 'action': 'save',
                                  'expected_revision': initial['revision'], 'catalog': catalog})[-1]
    assert not saved_catalog['failed'], saved_catalog
    original = yaml.safe_load(roles_path(project).read_text())
    state = read(project)
    request = {
        'action': 'save', 'revision': state['revision'],
        'edits': {'research.root': {'connection': 'shared/custom/model'},
                  'research.worker': {'connection': 'shared/custom/model', 'reasoning_effort': 'low'},
                  'research.independent': {'connection': 'shared/custom/model'}},
        'renames': {}, 'add_edges': [], 'remove_edges': [], 'remove_presets': [],
        'role_tree': {**state['role_tree'], 'research.root': {'research.worker': {}},
                      'research.independent': {}},
    }
    replies = call(project, request)
    assert not replies[-1]['failed'], replies
    reopened = read(project)
    assert reopened['role_tree'] == request['role_tree']
    document = yaml.safe_load(roles_path(project).read_text())
    assert {key: value for key, value in document['roles'].items() if key != 'research'} == original['roles']
    assert document['roles']['research'] == {
        'root': {'connection': 'shared/custom/model'},
        'worker': {'connection': 'shared/custom/model', 'reasoning_effort': 'low'},
        'independent': {'connection': 'shared/custom/model'},
    }
    resolved = load_project_roles(project).dispatch_preset('research.root', 'research.worker')
    assert (resolved.runtime, resolved.model, resolved.api_key_env, resolved.reasoning_effort) == (
        'codex', 'chosen-model', 'CUSTOM_KEY', 'low',
    )
    assert 'controlled-secret-must-not-be-copied' not in json.dumps(replies)
    assert 'controlled-secret-must-not-be-copied' not in roles_path(project).read_text()
    after = snapshot(project)
    conflict = call(project, request)[-1]
    assert conflict['failed'] and 'changed while editing' in conflict['error']
    assert snapshot(project) == after


def test_effort_without_model_metadata_saves_and_reopens(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Runtime-sourced effort options and custom connections share the direct writer."""
    home = project / 'effort-user'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('USERPROFILE', str(home))
    config_path = project / '.graphtraj/config.yml'
    config = yaml.safe_load(config_path.read_text())
    config['codex'] = {'approval': {'model': 'review', 'base_url': 'https://review.invalid/v1',
                                  'api_key_env': 'REVIEW_KEY'}}
    config_path.write_text(yaml.safe_dump(config))
    state = call(project, {'scope': 'user', 'action': 'read'})[-1]['result']
    options = state['capabilities']['reasoning_efforts']['codex']
    assert 'high' in options and 'max' in options
    catalog = {'version': 1, 'runtimes': {'codex': {'runtime': 'codex', 'providers': {
        'deepseek': {'base_url': 'https://provider.invalid/v1', 'api_key_env': 'CUSTOM_KEY',
                     'models': {'flash': {'id': 'deepseek-flash', 'source': 'manual'}}},
    }}}}
    assert call(project, {'scope': 'user', 'action': 'save', 'catalog': catalog,
                          'expected_revision': state['revision']})[-1]['result']['applied']
    for effort in ('high', 'max'):
        request = draft(project, connection='codex/deepseek/flash', runtime=None,
                        model=None, reasoning_effort=effort)
        replies = call(project, request)
        assert len(replies) == 1 and not replies[0]['failed'], replies
        reopened = read(project)['roles']['analyst']
        assert reopened['connection'] == 'codex/deepseek/flash'
        assert reopened['reasoning_effort'] == effort
    before = snapshot(project)
    assert call(project, draft(project, reasoning_effort='invented-effort'))[-1]['failed']
    assert snapshot(project) == before


def test_unrelated_custom_role_save_does_not_require_launch_approval(project: Path) -> None:
    """Editing a prompt preserves missing launch configuration rather than inventing a reviewer."""
    path = roles_path(project)
    document = yaml.safe_load(path.read_text())
    document['roles']['analyst']['base_url'] = 'https://work.invalid/v1'
    path.write_text(yaml.safe_dump(document))
    result = call(project, draft(project, system_prompt='Updated role instructions.'))[-1]
    assert not result['failed'], result
    saved = yaml.safe_load(path.read_text())['roles']['analyst']
    assert saved == {**document['roles']['analyst'], 'system_prompt': 'Updated role instructions.'}


def test_approval_connection_save_reopen_and_native_resolution(
    project: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """An existing global connection supplies the unchanged native review transport."""
    from graphtraj.configuration.project_roles import load_project_roles
    from graphtraj.configuration.role_definitions import resolve_child_role
    from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError
    from test_codex_app_server import context

    home = project / 'user'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('USERPROFILE', str(home))
    initial = call(project, {'scope': 'user', 'action': 'read'})[-1]['result']
    catalog = {'version': 1, 'runtimes': {'shared': {'runtime': 'pi', 'providers': {
        'review': {'base_url': 'https://review.invalid/v1', 'api_key_env': 'REVIEW_KEY',
                   'api': 'openai-completions', 'models': {
                       'selected': {'id': 'review-model', 'source': 'manual'},
                   }},
    }}}}
    assert not call(project, {'scope': 'user', 'action': 'save', 'catalog': catalog,
                             'expected_revision': initial['revision']})[-1]['failed']
    assert not call(project, draft(project, approval_connection='shared/review/selected',
                                   base_url='https://work.invalid/v1'))[-1]['failed']
    assert read(project)['roles']['analyst']['approval_connection'] == 'shared/review/selected'
    saved = yaml.safe_load(roles_path(project).read_text())['roles']['analyst']
    assert saved['codex']['approval'] == {'connection': 'shared/review/selected'}
    role = resolve_child_role('analyst', load_project_roles(project).preset('analyst'), project)
    # The public Adapter preparation seam does not invoke inference or read keys.
    executable = tmp_path / 'codex-help'
    executable.write_text('#!/bin/sh\necho --sandbox\n')
    executable.chmod(0o755)
    request = context(tmp_path / 'prepared', executable, role).launch_document()['adapter_request']
    assert request['approval'] == {'model': 'review-model', 'base_url': 'https://review.invalid/v1',
                                   'api_key_env': 'REVIEW_KEY'}
    before = snapshot(project)
    failure = call(project, draft(project, approval_connection='shared/review/missing'))[-1]
    assert failure['failed'] and failure['error_kind'] == 'validation'
    assert snapshot(project) == before
    assert not call(project, draft(project, approval_connection=None))[-1]['failed']
    role = resolve_child_role('analyst', load_project_roles(project).preset('analyst'), project)
    with pytest.raises(RuntimeAdapterError, match='codex.approval.model'):
        context(tmp_path / 'missing-review', executable, role)


@pytest.mark.parametrize(('runtime', 'model'), [('pi', 'provider/model'), ('dsh', 'deepseek-flash')])
def test_single_channel_prompt_save_and_resolution(project: Path, runtime: str, model: str) -> None:
    """Save/reopen preserves authored layers while resolution uses the real single channel."""
    from graphtraj.configuration.project_roles import load_project_roles
    from graphtraj.configuration.role_definitions import resolve_child_role

    result = call(project, draft(project, runtime=runtime, model=model,
                                 system_prompt='System text', developer_prompt='Developer text'))[-1]
    assert not result['failed'], result
    reopened = read(project)['roles']['analyst']
    assert reopened['system_prompt'] == 'System text'
    assert reopened['developer_prompt'] == 'Developer text'
    role = resolve_child_role('analyst', load_project_roles(project).preset('analyst'), project)
    assert 'System text' in role.instructions and 'Developer text' in role.instructions
    assert role.system_instructions == ''


def test_manual_efforts_survive_native_refresh_and_role_save(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discovery is read-only; manually declared capabilities survive and govern role effort."""
    from graphtraj.configuration.project_roles import load_project_roles
    from graphtraj.runtimes import model_discovery

    home = project / 'manual-user'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('USERPROFILE', str(home))
    initial = call(project, {'scope': 'user', 'action': 'read'})[-1]['result']
    catalog = {'version': 1, 'runtimes': {'local': {'runtime': 'codex', 'providers': {
        'openai': {'models': {'model': {'id': 'my-model', 'source': 'manual',
                                      'supported_efforts': ['low', 'high']}}},
    }}}}
    assert not call(project, {'scope': 'user', 'action': 'save', 'catalog': catalog,
                             'expected_revision': initial['revision']})[-1]['failed']
    monkeypatch.setattr(model_discovery, 'discover_models', lambda runtime: {
        'status': 'available', 'account_access': 'unknown',
        'models': [{'provider': 'openai', 'id': 'my-model', 'supported_efforts': ['medium']}],
    })
    discovered = call(project, {'scope': 'user', 'action': 'discover', 'runtime': 'local'})[-1]
    assert not discovered['failed']
    reopened = call(project, {'scope': 'user', 'action': 'read'})[-1]['result']
    assert reopened['catalog'] == catalog
    assert not call(project, draft(project, connection='local/openai/model',
                                   runtime=None, model=None, reasoning_effort='high'))[-1]['failed']
    assert read(project)['roles']['analyst']['reasoning_effort'] == 'high'
    assert load_project_roles(project).preset('analyst').reasoning_effort == 'high'
    assert call(project, draft(project, reasoning_effort='medium'))[-1]['failed']
