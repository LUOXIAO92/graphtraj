"""Authorized public organization of child role presets and dispatch edges."""

from pathlib import Path

import pytest
import yaml

from graphtraj.configuration.project_roles import load_project_roles
from graphtraj.execution import approved_recovery
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import runtime_caller
from graphtraj.interfaces import local_tool


ROLES = """\
roles:
  coding_team:
    team_leader:
      runtime: codex
      model: leader-model
      reports: [leader.md]
    engineer:
      runtime: codex
      model: engineer-model
      api_key_env: ENGINEER_KEY
  analyst:
    runtime: codex
    model: analyst-model

role_tree:
  coding_team.team_leader:
    coding_team.engineer: {}
"""

CONFIG = """\
version: 1
paths:
  project_root: .
  docs: docs
  agent_worktrees: .graphtraj/.agent-worktrees
  state: .graphtraj/state

agent_runner:
  dispatch_depth: 2
  max_concurrency: 2
"""

def accept(proposal: dict) -> dict:
    """Approve whatever the host selected for review."""
    return {"decision": "accept"}


ADD = {"change": {
    "set_presets": {"reviewer": {"runtime": "codex", "model": "review-model"}},
    "add_edges": [{"parent": "coding_team.team_leader", "child": "reviewer"}],
}}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """One Harness Project Root holding a valid role configuration."""
    (tmp_path / ".graphtraj").mkdir()
    (tmp_path / ".graphtraj" / "config.yml").write_text(CONFIG, encoding="utf-8")
    (tmp_path / ".graphtraj" / "roles.yml").write_text(ROLES, encoding="utf-8")
    return tmp_path


def roles_path(project: Path) -> Path:
    """Return the single role configuration this public path may change."""
    return project / ".graphtraj" / "roles.yml"


def snapshot(root: Path) -> dict[str, bytes]:
    """Return every file below one project so side effects stay visible."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def execute(project: Path, arguments: dict, reviewer=None):
    """Call the public gateway with only the host's own reviewer binding."""
    call = local_tool.bind(project, recovery_reviewer=reviewer)
    return call({"action": "execute", "feature": "role_organization", "arguments": arguments})


def refusal(project: Path, arguments: dict, reviewer=None) -> tuple[str | None, str]:
    """Return the code and message of one refused public call."""
    try:
        result = execute(project, arguments, reviewer)
    except RunnerError as error:
        return error.code, error.message
    assert result.failed, result.document
    return None, result.document["error"]


def test_preview_reports_current_roles_without_writing(project: Path) -> None:
    """Reading the current organization never changes roles.yml."""
    before = roles_path(project).read_bytes()
    document = execute(project, {}).document
    assert document["presets"] == [
        "analyst", "coding_team.engineer", "coding_team.team_leader",
    ]
    assert document["edges"] == [["coding_team.team_leader", "coding_team.engineer"]]
    assert document["role_tree"] == {"coding_team.team_leader": {"coding_team.engineer": {}}}
    assert "applied" not in document
    assert roles_path(project).read_bytes() == before


def test_approved_change_alters_real_dispatch_eligibility(project: Path) -> None:
    """One approved call adds, updates and removes presets and dispatch edges."""
    reviews: list[dict] = []

    def reviewer(proposal: dict) -> dict:
        """Retain the exact reviewed document and approve it."""
        reviews.append(proposal)
        return {"decision": "accept"}

    assert execute(project, ADD, reviewer).document["applied"] is True
    added = load_project_roles(project)
    assert added.preset("reviewer").model == "review-model"
    assert added.permits_dispatch("coding_team.team_leader", "reviewer")
    assert reviews[0]["after"]["role_tree"]["coding_team.team_leader"]["reviewer"] == {}

    updated = execute(
        project,
        {"change": {"set_presets": {"reviewer": {"model": "reviewed-again", "reasoning_effort": "high"}}}},
        reviewer,
    ).document
    assert updated["applied"] is True
    current = load_project_roles(project)
    assert current.preset("reviewer").model == "reviewed-again"
    assert current.preset("reviewer").runtime == "codex"

    removed = execute(
        project,
        {"change": {
            "remove_presets": ["reviewer"],
            "remove_edges": [{"parent": "coding_team.team_leader", "child": "reviewer"}],
        }},
        reviewer,
    ).document
    assert removed["applied"] is True
    retracted = load_project_roles(project)
    assert "reviewer" not in retracted.presets
    assert not retracted.permits_dispatch("coding_team.team_leader", "reviewer")


def test_declined_review_applies_nothing(project: Path) -> None:
    """A reviewer refusal keeps the target byte-for-byte unchanged."""
    before = roles_path(project).read_bytes()
    code, message = refusal(
        project,
        {"change": {"set_presets": {"analyst": {"model": "denied-model"}}}},
        lambda proposal: {"decision": "decline", "rationale": "scope not approved"},
    )
    assert code == "role-change-denied"
    assert "scope not approved" in message
    assert roles_path(project).read_bytes() == before


def test_unavailable_review_applies_nothing(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller without a bound or configured reviewer writes nothing."""
    monkeypatch.setattr(approved_recovery, "caller_runtime", lambda: None)
    before = roles_path(project).read_bytes()
    code, message = refusal(
        project, {"change": {"set_presets": {"analyst": {"model": "unavailable-model"}}}},
    )
    assert code == "native-approval-unavailable"
    assert message
    assert roles_path(project).read_bytes() == before


@pytest.mark.parametrize("change", [
    pytest.param({"change": {"add_edges": [
        {"parent": "shared", "child": "loop"}, {"parent": "loop", "child": "shared"},
    ]}}, id="cycle"),
    pytest.param({"change": {"set_presets": {
        "engineer": {"runtime": "codex", "model": "clash-model"},
    }}}, id="duplicate"),
    pytest.param({"change": {"unsupported_field": {}}}, id="unknown-field"),
])
def test_invalid_role_graph_is_refused_without_writing(
    project: Path, change: dict,
) -> None:
    """An invalid result is refused before any reviewer or write."""
    reviews: list[dict] = []
    before = snapshot(project)
    code, message = refusal(project, change, lambda proposal: reviews.append(proposal) or {"decision": "accept"})
    assert message
    assert code in {None, "invalid-input"}
    assert reviews == []
    assert snapshot(project) == before


def test_target_changed_after_review_is_refused(project: Path) -> None:
    """Content that changed after review is never overwritten by the approval."""
    def reviewer(proposal: dict) -> dict:
        """Change the target between review and application."""
        document = yaml.safe_load(roles_path(project).read_text(encoding="utf-8"))
        document["roles"]["analyst"]["model"] = "changed-after-review"
        roles_path(project).write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        return {"decision": "accept"}

    result = execute(
        project,
        {"change": {"set_presets": {"analyst": {"model": "approved-model"}}}},
        reviewer,
    ).document
    assert result["applied"] is False
    assert result["status"] == "stale"
    assert load_project_roles(project).preset("analyst").model == "changed-after-review"


def test_local_change_preserves_unrelated_roles_and_settings(project: Path) -> None:
    """Changing one preset leaves every other role, edge and file untouched."""
    before = snapshot(project)
    assert execute(
        project,
        {"change": {"set_presets": {"analyst": {"model": "local-model"}}}},
        accept,
    ).document["applied"] is True
    after = snapshot(project)
    assert {
        name for name in set(before) | set(after) if before.get(name) != after.get(name)
    } == {".graphtraj/roles.yml"}

    roles = load_project_roles(project)
    assert roles.preset("analyst").model == "local-model"
    assert roles.preset("coding_team.engineer").api_key_env == "ENGINEER_KEY"
    assert roles.preset("coding_team.team_leader").reports == ("leader.md",)
    assert roles.permits_dispatch("coding_team.team_leader", "coding_team.engineer")
    assert roles.presets["coding_team.team_leader"].model == "leader-model"


def test_child_caller_cannot_organize_roles(project: Path) -> None:
    """A live child Session is refused even with a host-bound accepting reviewer."""
    reviews: list[dict] = []
    before = snapshot(project)
    runner = project / ".graphtraj" / "runner"
    with runtime_caller(runner, "253-ticket@engineer"):
        code, message = refusal(project, ADD, lambda proposal: reviews.append(proposal) or {"decision": "accept"})
    assert code == "authority-denied"
    assert message
    assert reviews == []
    assert snapshot(project) == before
