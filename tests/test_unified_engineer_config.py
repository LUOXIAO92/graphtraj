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


def test_default_presets_expose_one_engineer_role() -> None:
    """Setup writes one Engineer preset beside the Team Leader and Reviewers."""
    document = yaml.safe_load(default_roles_content())

    assert set(document["roles"]["coding-team"]) == {
        "team-leader",
        "engineer",
        "standards-reviewer",
        "spec-reviewer",
        "merge-resolver",
    }
    assert document["roles"]["delivery-state"]["runtime"] == "codex"


def test_configured_engineer_preset_serves_the_engineer_seat(tmp_path: Path) -> None:
    """Operator Runtime, model and connection settings reach the Engineer seat."""
    path = tmp_path / ".graphtraj" / "roles.yml"
    path.parent.mkdir()
    path.write_text(default_roles_content())
    document = yaml.safe_load(path.read_text())
    document["roles"]["coding-team"]["engineer"] = {
        "runtime": "codex",
        "model": "operator-selected-model",
        "reasoning_effort": "high",
        "base_url": "https://example.com",
        "api_key_env": "DEEPSEEK_API_KEY",
    }
    path.write_text(yaml.safe_dump(document))

    preset = load_project_roles(tmp_path).presets["engineer"]

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


def test_engineer_tier_names_are_no_longer_presets(tmp_path: Path) -> None:
    """A tiered preset is rejected instead of silently configuring one Engineer."""
    path = tmp_path / ".graphtraj" / "roles.yml"
    path.parent.mkdir()
    path.write_text(
        default_roles_content().replace("  engineer:", "  engineer-senior:")
    )

    with pytest.raises(ProjectRolesError) as error:
        load_project_roles(tmp_path)

    assert any(
        "engineer-senior" in diagnostic for diagnostic in error.value.diagnostics
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
    role = resolve_child_role(
        task.policy_role, default_project_roles().presets["engineer"]
    )

    assert retained.read_bytes() == original
    assert task.role == "engineer"
    assert role.name == "engineer"
    assert role.required_skills == ("implement", "ponytail", "tdd")
    assert "junior" not in role.instructions


@pytest.mark.parametrize(
    "role", ("engineer", "engineer-junior", "engineer-senior", "engineer-expert")
)
def test_retained_engineer_session_keeps_its_budget_stage(role: str) -> None:
    """A retained Engineer Session identity keeps Engineer time accounting."""
    assert execution_budget_stage(role) == "implementation"
