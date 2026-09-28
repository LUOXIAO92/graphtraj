"""Current configured roles stay distinct from historical Engineer aliases."""

from pathlib import Path

import pytest
import yaml

from graphtraj.configuration.project_roles import (
    ProjectRolesError,
    default_roles_content,
    default_project_roles,
    load_project_roles,
    parse_inline_role,
)
from graphtraj.configuration.role_definitions import resolve_child_role
from graphtraj.execution.execution_budget import execution_budget_stage
from graphtraj.execution.runner_batch import parse_batch, read_batch


def test_default_role_selection_names_no_role() -> None:
    """Setup selects no role, including no coding Team arrangement."""
    assert yaml.safe_load(default_roles_content()) == {"roles": {}}
    assert default_project_roles().presets == {}


def _selected_coding_roles() -> dict:
    """Return the coding selection a project declares for the Engineer seat."""
    return {"roles": {"coding_team": {
        "team_leader": {
            "runtime": "codex",
            "model": "gpt-5.6-sol",
            "allow_runtime_swarm": True,
        },
        "engineer": {"runtime": "codex", "model": "gpt-5.6-sol"},
        "standards_reviewer": {"runtime": "codex", "model": "gpt-5.6-sol"},
        "spec_reviewer": {"runtime": "codex", "model": "gpt-5.6-sol"},
        "merge_resolver": {"runtime": "codex", "model": "gpt-5.6-sol"},
        "delivery_state": {"runtime": "codex", "model": "gpt-5.6-luna"},
    }}}


def test_configured_engineer_preset_serves_the_engineer_seat(tmp_path: Path) -> None:
    """Operator Runtime, model and connection settings reach the Engineer seat."""
    path = tmp_path / ".graphtraj" / "roles.yml"
    path.parent.mkdir()
    document = _selected_coding_roles()
    document["roles"]["coding_team"]["engineer"] = {
        "runtime": "codex",
        "model": "operator-selected-model",
        "reasoning_effort": "high",
        "base_url": "https://example.com",
        "api_key_env": "DEEPSEEK_API_KEY",
    }
    path.write_text(yaml.safe_dump(document))

    preset = load_project_roles(tmp_path).presets["coding_team.engineer"]

    assert preset.model == "operator-selected-model"
    assert preset.reasoning_effort == "high"
    assert preset.base_url == "https://example.com"
    assert preset.api_key_env == "DEEPSEEK_API_KEY"


def test_engineer_batch_reference_keeps_the_supplied_reference() -> None:
    """A new Batch keeps the role reference its caller named."""
    task = parse_batch({"tasks": [{
        "ticket_id": "73", "ticket_name": "shared-graph",
        "role": "coding-team.engineer-junior", "skills": ["implement"],
    }]}).tasks[0]

    assert task.role == "engineer-junior"
    assert task.policy_role == "engineer-junior"
    assert task.role_reference == "coding-team.engineer-junior"
    assert task.requested_skills == ("implement",)


@pytest.mark.parametrize("tier", ["junior", "senior", "expert"])
def test_a_configured_tier_role_keeps_its_own_identity_and_edge(
    tmp_path: Path, tier: str,
) -> None:
    """A configured tier name dispatches its own preset and role-tree edge."""
    reference = "engineer-" + tier
    path = tmp_path / ".graphtraj" / "roles.yml"
    path.parent.mkdir()
    document = _selected_coding_roles()
    document["roles"]["custom_team"] = {
        reference: {"runtime": "codex", "model": "expert-model",
                    "base_url": "https://role.example", "api_key_env": "ROLE_API_KEY",
                    "reasoning_effort": "high"},
    }
    document["role_tree"] = {reference: {}}
    path.write_text(yaml.safe_dump(document))
    roles = load_project_roles(tmp_path)

    # A bare name exactly one configured group declares selects that role.
    assert roles.preset(reference).model == "expert-model"
    assert roles.dispatch_preset(None, reference).model == "expert-model"
    # The unified Engineer seat keeps its own settings.
    assert roles.preset("coding_team.engineer").model == "gpt-5.6-sol"

    task = parse_batch({"tasks": [{
        "ticket_id": "73", "ticket_name": "shared-graph",
        "role": reference,
    }]}).tasks[0]

    assert task.role == reference
    assert task.role_reference == reference
    selected = roles.preset(task.role_reference)
    assert selected.model == "expert-model"
    assert selected.base_url == "https://role.example"
    assert selected.api_key_env == "ROLE_API_KEY"
    assert selected.reasoning_effort == "high"
    retained = tmp_path / "current-batch.yml"
    retained.write_bytes(parse_batch({"tasks": [{
        "ticket_id": "73", "ticket_name": "shared-graph", "role": reference,
    }]}).source_bytes)
    assert read_batch(retained, tmp_path).tasks[0] == task



def test_an_unconfigured_tier_reference_fails_by_name(tmp_path: Path) -> None:
    """No preset serves a tier spelling that current configuration omits."""
    path = tmp_path / ".graphtraj" / "roles.yml"
    path.parent.mkdir()
    document = _selected_coding_roles()
    document["role_tree"] = {"team-leader": {"engineer-expert": {}}}
    path.write_text(yaml.safe_dump(document))
    roles = load_project_roles(tmp_path)

    # The tree permits this edge, but no configuration preset declares it.
    with pytest.raises(ProjectRolesError) as error:
        roles.dispatch_preset("team-leader", "engineer-expert")

    assert "engineer-expert" in str(error.value)
    assert roles.preset("coding_team.engineer").model == "gpt-5.6-sol"


def test_a_tier_named_group_role_keeps_its_own_reference(tmp_path: Path) -> None:
    """A tier is one configured role instead of silently serving the Engineer seat."""
    path = tmp_path / ".graphtraj" / "roles.yml"
    path.parent.mkdir()
    document = _selected_coding_roles()
    engineer = document["roles"]["coding_team"].pop("engineer")
    document["roles"]["coding_team"]["engineer-senior"] = engineer
    path.write_text(yaml.safe_dump(document))

    roles = load_project_roles(tmp_path)

    assert "coding_team.engineer-senior" in roles.presets
    with pytest.raises(ProjectRolesError) as error:
        roles.preset("coding_team.engineer")

    assert any(
        "coding_team.engineer" in diagnostic for diagnostic in error.value.diagnostics
    )


@pytest.mark.parametrize("reference", [
    "engineer", "engineer-junior", "engineer-senior", "engineer-expert",
])
def test_inline_engineer_role_keeps_its_name(reference: str) -> None:
    """Inline Runtime settings do not rewrite the caller's role identity."""
    name, preset = parse_inline_role(
        {reference: {"runtime": "codex", "model": "gpt-5.6-terra"}}
    )

    assert name == reference
    assert preset.model == "gpt-5.6-terra"


def test_non_engineer_task_retains_selected_repository_skills() -> None:
    """A non-Engineer task retains its selected repository Skills."""
    batch = parse_batch({"tasks": [{
        "ticket_id": "73", "ticket_name": "shared-graph",
        "role": "team-leader", "skills": ["implement"],
    }]})

    assert batch.tasks[0].role == "team-leader"
    assert batch.tasks[0].requested_skills == ("implement",)


def test_retained_tiered_batch_still_resolves_for_recovery(tmp_path: Path) -> None:
    """A retained Batch keeps its bytes while its Engineer seat stays resolvable."""
    retained = tmp_path / "retained-batch.yml"
    retained.write_text(
        "tasks:\n"
        '  - ticket_id: "73"\n'
        "    ticket_name: shared-graph\n"
        "    role: coding-team.engineer-senior\n"
        "    skills: [implement]\n",
        encoding="utf-8",
    )
    original = retained.read_bytes()

    task = read_batch(retained, tmp_path).tasks[0]
    _, selected = parse_inline_role(
        {"engineer": {"runtime": "codex", "model": "gpt-5.6-sol"}}
    )
    role = resolve_child_role(
        task.policy_role, selected, tmp_path
    )

    assert retained.read_bytes() == original
    assert task.role == "engineer-senior"
    assert role.name == "engineer-senior"
    # A retained identity does not implicitly select a professional resource.
    assert role.instructions == resolve_child_role("engineer", selected, tmp_path).instructions


@pytest.mark.parametrize(
    "role", ("engineer", "engineer-junior", "engineer-senior", "engineer-expert")
)
def test_retained_engineer_session_labels_its_actual_budget_work(role: str) -> None:
    """A retained Session labels observations without implying a programming phase."""
    assert execution_budget_stage(role) == role


@pytest.mark.parametrize('reference, roles, succeeds', [
    ('writing.author', ['writing.author', 'research.scribe'], True),
    (None, ['writing.author'], True),
    (None, ['writing.author', 'research.scribe'], False),
    ('missing.author', ['writing.author'], False),
])
def test_retained_session_binding_requires_unique_actual_facts(
    tmp_path: Path, reference: str | None, roles: list[str], succeeds: bool,
) -> None:
    """An old identity is preserved without guessing from role names or models."""
    from graphtraj.execution.runner_batch import read_session_task
    from graphtraj.execution.runner_models import RunnerError

    retained = tmp_path / 'batch.yml'
    retained.write_text(yaml.safe_dump({'tasks': [
        {'ticket_id': '169', 'ticket_name': 'binding', 'role': role} for role in roles
    ]}))
    original = retained.read_bytes()
    mapping = {'ticket_id': '169', 'role': 'editor', 'retained_batch_file': str(retained)}
    if reference is not None:
        mapping['role_reference'] = reference
    if succeeds:
        task = read_session_task(mapping, tmp_path)
        assert task.role == task.policy_role == 'editor'
        assert task.role_reference == (reference or roles[0])
    else:
        with pytest.raises(RunnerError, match='uniquely identify'):
            read_session_task(mapping, tmp_path)
    assert retained.read_bytes() == original
