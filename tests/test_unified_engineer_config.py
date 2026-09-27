"""One unified Engineer configuration serves every coding Team seat."""

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
from graphtraj.execution.runner_models import RunnerError


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


def test_a_configured_tier_role_keeps_its_own_identity_and_edge(
    tmp_path: Path,
) -> None:
    """A configured tier name dispatches its own preset and role-tree edge."""
    path = tmp_path / ".graphtraj" / "roles.yml"
    path.parent.mkdir()
    document = _selected_coding_roles()
    document["roles"]["custom_team"] = {
        "engineer-expert": {"runtime": "codex", "model": "expert-model"},
    }
    document["role_tree"] = {"engineer-expert": {}}
    path.write_text(yaml.safe_dump(document))
    roles = load_project_roles(tmp_path)

    # A bare name exactly one configured group declares selects that role.
    assert roles.preset("engineer-expert").model == "expert-model"
    assert roles.dispatch_preset(None, "engineer-expert").model == "expert-model"
    # The unified Engineer seat keeps its own settings.
    assert roles.preset("coding_team.engineer").model == "gpt-5.6-sol"

    task = parse_batch({"tasks": [{
        "ticket_id": "73", "ticket_name": "shared-graph",
        "role": "engineer-expert",
    }]}).tasks[0]

    assert task.role == "engineer-expert"
    assert task.role_reference == "engineer-expert"
    assert roles.preset(task.role_reference).model == "expert-model"


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


def test_inline_engineer_role_resolves_without_a_tier() -> None:
    """A one-Batch Engineer role stays traceable without naming a tier."""
    name, preset = parse_inline_role(
        {"engineer": {"runtime": "codex", "model": "gpt-5.6-terra"}}
    )

    assert name == "engineer"
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
        task.policy_role, selected
    )

    assert retained.read_bytes() == original
    assert task.role == "engineer"
    assert role.name == "engineer"
    # The installed Engineer template is the source of its required Skills.
    assert role.required_skills == ("implement", "ponytail")


@pytest.mark.parametrize(
    "role", ("engineer", "engineer-junior", "engineer-senior", "engineer-expert")
)
def test_retained_engineer_session_labels_its_actual_budget_work(role: str) -> None:
    """A retained Session labels observations without implying a programming phase."""
    assert execution_budget_stage(role) == role
