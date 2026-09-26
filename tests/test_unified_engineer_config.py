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


@pytest.mark.parametrize(
    "role",
    (
        "coding-team.engineer",
        "coding-team.engineer-junior",
        "coding-team.engineer-senior",
        "coding-team.engineer-expert",
    ),
)
def test_engineer_batch_reference_resolves_to_the_unified_role(role: str) -> None:
    """Retained Engineer spellings select the same configured Engineer preset."""
    task = parse_batch({"tasks": [{
        "ticket_id": "73", "ticket_name": "shared-graph", "role": role,
        "skills": ["implement"],
    }]}).tasks[0]

    assert task.role == "engineer"
    assert task.policy_role == "engineer"
    assert task.requested_skills == ("implement",)


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


def test_only_the_engineer_task_selects_repository_skills() -> None:
    """Repository Skill selection stays a unified-Engineer input."""
    with pytest.raises(RunnerError) as error:
        parse_batch({"tasks": [{
            "ticket_id": "73", "ticket_name": "shared-graph",
            "role": "team-leader", "skills": ["implement"],
        }]})

    assert error.value.code == "SKILL_SELECTION_INVALID"


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
def test_retained_engineer_session_keeps_its_budget_stage(role: str) -> None:
    """A retained Engineer Session identity keeps Engineer time accounting."""
    assert execution_budget_stage(role) == "implementation"
