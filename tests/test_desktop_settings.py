"""Human desktop settings through the public restricted native pipe."""

import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
import yaml

from graphtraj.execution.runner_status import runtime_caller
from graphtraj.interfaces.desktop_settings import serve
from test_role_organization import project, roles_path, snapshot


def call(root: Path, request: dict, decision: str = "decline") -> list[dict]:
    """Exchange one settings request and a controlled host review reply."""
    output = io.StringIO()
    serve(io.StringIO(json.dumps(request) + "\n" + json.dumps({"decision": decision}) + "\n"), output, root)
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
    replies = call(project, request, "accept")
    assert replies[0]["review"]["before"]["analyst"]["model"] == "analyst-model"
    assert replies[-1]["result"]["applied"] is True
    assert "hidden-existing-value" not in json.dumps(replies)
    assert "never-render-this-secret" not in json.dumps(replies)
    after = snapshot(project)
    assert {name for name in before if before[name] != after[name]} == {".graphtraj/roles.yml"}
    saved = yaml.safe_load(roles_path(project).read_text())
    assert saved["roles"]["coding_team"] == document["roles"]["coding_team"]
    assert saved["roles"]["analyst"]["codex"] == document["roles"]["analyst"]["codex"]
    assert saved["role_tree"] == document["role_tree"]


@pytest.mark.parametrize("decision", ["decline", "invalid-reply"])
def test_denial_or_review_failure_keeps_original(project: Path, decision: str) -> None:
    """Native review refusal and malformed replies never save the draft."""
    before = snapshot(project)
    replies = call(project, draft(project, model="rejected-model"), decision)
    assert "review" in replies[0]
    assert replies[-1]["failed"] is True
    assert snapshot(project) == before


def test_revision_conflict_before_and_during_review(project: Path) -> None:
    """External changes are detected at both draft and approval boundaries."""
    stale = draft(project, model="stale-draft")
    assert call(project, draft(project, model="external-native-change"), "accept")[-1]["result"]["applied"]
    before = snapshot(project)
    replies = call(project, stale, "accept")
    assert len(replies) == 1 and replies[0]["failed"]
    assert "changed while editing" in replies[0]["error"]
    assert snapshot(project) == before

    class ExternalChange(io.StringIO):
        """Apply a second native save when the first host receives its review."""

        def write(self, text: str) -> int:
            """Change through the public entry before returning approval."""
            if "review" in json.loads(text):
                call(project, draft(project, model="changed-during-review"), "accept")
            return super().write(text)

    output = ExternalChange()
    serve(io.StringIO(json.dumps(draft(project, model="must-not-win")) + '\n{"decision":"accept"}\n'), output, project)
    assert "changed during approval" in output.getvalue()
    assert read(project)["roles"]["analyst"]["model"] == "changed-during-review"


@pytest.mark.parametrize("fields", [
    {"runtime": "pi", "model": "provider/"},
    {"runtime": "pi", "model": "/model"},
    {"runtime": "pi", "model": "provider/model", "developer_prompt": "unsupported"},
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
    replies = call(project, draft(project, **fields), "accept")
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
    reply = call(project, request, "accept")[-1]
    assert reply["failed"] is False, reply
    saved = yaml.safe_load(path.read_text())
    assert saved["roles"]["research"]["builder"] == {"runtime": "codex", "model": "engineer-model", "api_key_env": "ENGINEER_KEY"}
    assert saved["role_tree"] == {"owner": {"coding_team.team_leader": {"research.builder": {}}}}


def test_agent_caller_and_fabricated_approval_are_rejected(project: Path) -> None:
    """A desktop flag or request field cannot elevate an actual Agent caller."""
    request = draft(project, model="forbidden")
    before = snapshot(project)
    with runtime_caller(project / ".graphtraj" / "runner", "actual-agent"):
        assert call(project, {"action": "read"})[-1]["failed"]
        assert call(project, request, "accept")[-1]["failed"]
    request["decision"] = "accept"
    assert call(project, request, "accept")[-1]["failed"]
    assert snapshot(project) == before


def test_concurrent_approved_saves_do_not_overwrite_one_another(project: Path) -> None:
    """Two reviews of the same revision can commit only one candidate."""
    barrier = Barrier(2, timeout=5)
    revision = read(project)["revision"]

    class SimultaneousReview(io.StringIO):
        """Hold both host reviews until each candidate has been prepared."""

        def write(self, text: str) -> int:
            """Release both native operations from their review boundary."""
            if "review" in json.loads(text):
                barrier.wait()
            return super().write(text)

    def save(model: str) -> dict:
        """Use one owned native pipe for each independently approved draft."""
        request = {"action": "save", "revision": revision, "edits": {"analyst": {"model": model}}}
        output = SimultaneousReview()
        serve(io.StringIO(json.dumps(request) + '\n{"decision":"accept"}\n'), output, project)
        return json.loads(output.getvalue().splitlines()[-1])

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
    denied = call(project, request)[-1]
    assert denied['failed']
    assert yaml.safe_load(roles_path(project).read_text()) == original
    saved = call(project, request, 'accept')[-1]['result']
    assert saved['role_tree'] == tree
    assert yaml.safe_load(roles_path(project).read_text())['roles']['coding_team'] == original['roles']['coding_team']

    # Delete only the middle node and explicitly reconnect its leaf.
    tree['research.lead'] = {'research.leaf': {}}
    saved = call(project, {'action': 'save', 'revision': saved['revision'],
                          'remove_presets': ['research.worker'], 'role_tree': tree}, 'accept')[-1]['result']
    assert 'research.worker' not in saved['roles']
    assert ['research.lead', 'research.leaf'] in saved['edges']
    renamed = call(project, {'action': 'save', 'revision': saved['revision'],
                            'renames': {'research.lead': 'renamed.lead', 'research.leaf': 'renamed.leaf'}}, 'accept')[-1]['result']
    assert renamed['role_tree']['renamed.lead'] == {'renamed.leaf': {}}

    # Delete all configured roles and trees, then create a new unambiguous root.
    empty = call(project, {'action': 'save', 'revision': renamed['revision'],
                          'remove_presets': list(renamed['roles']), 'role_tree': {}}, 'accept')[-1]['result']
    assert empty['roles'] == empty['role_tree'] == {}
    recovered = call(project, {'action': 'save', 'revision': empty['revision'],
                              'edits': {'new.root': {'runtime': 'codex', 'model': 'root-model'}},
                              'role_tree': {'new.root': {}}}, 'accept')[-1]['result']
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
    replies = call(project, {'action': 'save', 'revision': read(project)['revision'], **change}, 'accept')
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
                          'catalog': connection}, 'accept')[-1]['result']
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
    reply = call(project, request, 'accept')[-1]
    assert not reply['failed'], reply
    assert snapshot(second) == untouched
    resolved = load_project_roles(project).dispatch_preset('coding_team.team_leader', 'coding_team.engineer')
    assert (resolved.runtime, resolved.model, resolved.runtime_home, resolved.reasoning_effort) == (
        'codex', 'custom-model', str(home / 'native'), 'low')
    assert resolved.api_key_env == 'CUSTOM_KEY'
    assert call(second, {'scope': 'user', 'action': 'read'})[-1]['result']['catalog'] == connection
    assert read(project)['roles']['coding_team.engineer']['connection'] == 'shared/custom/model'


def test_standalone_global_settings_use_native_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The global page works before adding a project without creating project state."""
    monkeypatch.setenv('HOME', str(tmp_path))
    # Windows resolves Path.home() from USERPROFILE rather than HOME.
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    assert Path.home() == tmp_path
    state = call(tmp_path, {'scope': 'user', 'action': 'read'})[-1]['result']
    catalog = {'version': 1, 'runtimes': {'local': {'runtime': 'codex', 'providers': {}}}}
    request = {'scope': 'user', 'action': 'save', 'expected_revision': state['revision'], 'catalog': catalog}
    assert call(tmp_path, request)[-1]['failed']
    assert not (tmp_path / '.graphtraj/connections.yml').exists()
    assert call(tmp_path, request, 'accept')[-1]['result']['applied']
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
    reply = call(project, request, 'accept')[-1]
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
    """New root/child references survive review and reopen without migrating old roles."""
    from graphtraj.configuration.project_roles import load_project_roles

    home = project / 'isolated-user'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('USERPROFILE', str(home))
    monkeypatch.setenv('CUSTOM_KEY', 'controlled-secret-must-not-be-copied')
    initial = call(project, {'scope': 'user', 'action': 'read'})[-1]['result']
    catalog = {'version': 1, 'runtimes': {'shared': {'runtime': 'codex', 'providers': {
        'custom': {'base_url': 'https://provider.invalid/v1', 'api_key_env': 'CUSTOM_KEY',
                   'models': {'model': {'id': 'chosen-model', 'source': 'manual',
                                        'supported_efforts': ['low']}}},
    }}}}
    saved_catalog = call(project, {'scope': 'user', 'action': 'save',
                                  'expected_revision': initial['revision'], 'catalog': catalog}, 'accept')[-1]
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
    before = snapshot(project)
    denied = call(project, request)[-1]
    assert denied['failed'] and 'did not approve' in denied['error']
    assert snapshot(project) == before
    replies = call(project, request, 'accept')
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
    conflict = call(project, request, 'accept')[-1]
    assert conflict['failed'] and 'changed while editing' in conflict['error']
    assert snapshot(project) == after
