"""Authorized public organization of child role presets and dispatch edges."""

import asyncio
from dataclasses import replace
import json
from pathlib import Path

import pytest
import yaml

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.configuration.project_roles import RolePreset, load_project_roles
from graphtraj.configuration.role_definitions import resolve_child_role
from graphtraj.execution import approved_recovery
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import runtime_caller
from graphtraj.interfaces import local_tool
from graphtraj.runtimes.codex.app_server import CodexAppServer, CodexServerRequest
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError
from graphtraj.runtimes.codex.managed_session import (
    native_operation_features,
    run_native_operation,
)
from test_codex_app_server import peer


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


CHILD_ATTEMPT = {"change": {"set_presets": {
    "child_only": {"runtime": "codex", "model": "child-model"},
}}}


def test_owning_host_thread_reaches_the_operation_and_a_child_does_not(
    tmp_path: Path, peer: Path,
) -> None:
    """Main's real host callback applies the change; a live child is still refused."""
    project = tmp_path
    (project / ".graphtraj").mkdir()
    (project / ".graphtraj" / "config.yml").write_text(
        default_configuration_content(project, project), encoding="utf-8",
    )
    (project / ".graphtraj" / "roles.yml").write_text(ROLES, encoding="utf-8")
    assert "role_organization" in native_operation_features()
    reviews: list[dict] = []

    def reviewer(proposal: dict) -> dict:
        """Approve whatever the owning host selected for review."""
        reviews.append(proposal)
        return {"decision": "accept"}

    async def exercise() -> tuple[dict, bool, dict, bool]:
        """Send both callers through the production native callback on one connection."""
        async with CodexAppServer(command=[str(peer)], cwd=project) as adapter:
            async def call(native_session: str, root_alias: str | None, arguments: dict) -> tuple[dict, bool]:
                """Issue one graphtraj tool call from the selected native thread."""
                response = await run_native_operation(
                    adapter, native_session, root_alias, project,
                    CodexServerRequest(1, 'item/tool/call', {
                        'threadId': native_session, 'tool': 'graphtraj', 'arguments': arguments,
                    }), recovery_reviewer=reviewer,
                )
                return json.loads(response['contentItems'][0]['text']), response['success']

            owner = await call('owner', None, {
                'action': 'execute', 'feature': 'role_organization', 'arguments': ADD,
            })
            child = await call('child@e1', 'child@e1', {
                'action': 'execute', 'feature': 'role_organization', 'arguments': CHILD_ATTEMPT,
            })
        return (*owner, *child)

    owner_document, owner_success, child_document, child_success = asyncio.run(exercise())
    assert owner_success, owner_document
    assert owner_document["applied"] is True
    assert len(reviews) == 1
    assert not child_success
    assert child_document["error"]["code"] == "authority-denied"
    assert len(reviews) == 1

    roles = load_project_roles(project)
    assert roles.preset("reviewer").model == "review-model"
    assert "child_only" not in roles.presets


SYSTEM_TEXT = (
    "Deliver only the layer the selected Runtime exposes.\n"
    "Keep the dispatch instruction in its own channel."
)
DEVELOPER_TEXT = "Treat the accepted specification as the contract."


def test_approved_prompt_content_is_persisted_verbatim(project: Path) -> None:
    """One approved call authors exact system/developer text through the public entry."""
    reviews: list[dict] = []

    def reviewer(proposal: dict) -> dict:
        """Retain the exact reviewed document and approve it."""
        reviews.append(proposal)
        return {"decision": "accept"}

    result = execute(
        project,
        {"change": {"set_presets": {"coding_team.engineer": {
            "system_prompt": SYSTEM_TEXT,
            "developer_prompt": DEVELOPER_TEXT,
        }}}},
        reviewer,
    ).document
    assert result["applied"] is True

    roles = load_project_roles(project)
    engineer = roles.preset("coding_team.engineer")
    assert engineer.system_prompt == SYSTEM_TEXT
    assert engineer.developer_prompt == DEVELOPER_TEXT
    assert engineer.instructions is None
    assert engineer.model == "engineer-model"
    assert engineer.api_key_env == "ENGINEER_KEY"

    # The reviewer decided on this exact text, and the file on disk carries it.
    reviewed = reviews[0]["after"]["roles"]["coding_team"]["engineer"]
    assert reviewed["system_prompt"] == SYSTEM_TEXT
    assert reviewed["developer_prompt"] == DEVELOPER_TEXT
    document = yaml.safe_load(roles_path(project).read_text(encoding="utf-8"))
    assert document["roles"]["coding_team"]["engineer"]["system_prompt"] == SYSTEM_TEXT


def test_prompt_change_keeps_instructions_reference_and_unrelated_settings(
    project: Path,
) -> None:
    """Authoring one prompt layer leaves the file reference and every other setting intact."""
    document = yaml.safe_load(roles_path(project).read_text(encoding="utf-8"))
    document["roles"]["coding_team"]["engineer"]["instructions"] = "engineer.md"
    document["roles"]["analyst"]["system_prompt"] = "Existing system text."
    roles_path(project).write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    before = snapshot(project)

    assert execute(
        project,
        {"change": {"set_presets": {
            "coding_team.engineer": {"developer_prompt": DEVELOPER_TEXT},
        }}},
        accept,
    ).document["applied"] is True

    after = snapshot(project)
    assert {
        name for name in set(before) | set(after) if before.get(name) != after.get(name)
    } == {".graphtraj/roles.yml"}

    roles = load_project_roles(project)
    engineer = roles.preset("coding_team.engineer")
    assert engineer.instructions == "engineer.md"
    assert engineer.developer_prompt == DEVELOPER_TEXT
    assert engineer.system_prompt is None
    assert roles.preset("analyst").system_prompt == "Existing system text."
    assert roles.preset("analyst").model == "analyst-model"
    assert roles.preset("coding_team.team_leader").reports == ("leader.md",)


def test_declined_prompt_review_applies_nothing(project: Path) -> None:
    """A reviewer refusal keeps the authored prompt out of the configuration."""
    before = roles_path(project).read_bytes()
    code, message = refusal(
        project,
        {"change": {"set_presets": {
            "coding_team.engineer": {"developer_prompt": DEVELOPER_TEXT},
        }}},
        lambda proposal: {"decision": "decline", "rationale": "prompt not approved"},
    )
    assert code == "role-change-denied"
    assert "prompt not approved" in message
    assert roles_path(project).read_bytes() == before


def test_prompt_target_changed_after_review_is_refused(project: Path) -> None:
    """Prompt content changed after review is never overwritten by the approval."""
    def reviewer(proposal: dict) -> dict:
        """Change the target between review and application."""
        document = yaml.safe_load(roles_path(project).read_text(encoding="utf-8"))
        document["roles"]["coding_team"]["engineer"]["developer_prompt"] = "changed-after-review"
        roles_path(project).write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        return {"decision": "accept"}

    result = execute(
        project,
        {"change": {"set_presets": {
            "coding_team.engineer": {"developer_prompt": DEVELOPER_TEXT},
        }}},
        reviewer,
    ).document
    assert result["applied"] is False
    assert result["status"] == "stale"
    assert load_project_roles(project).preset(
        "coding_team.engineer"
    ).developer_prompt == "changed-after-review"


def test_child_caller_cannot_author_prompts(project: Path) -> None:
    """A live child Session is refused even with a host-bound accepting reviewer."""
    reviews: list[dict] = []
    before = snapshot(project)
    runner = project / ".graphtraj" / "runner"
    with runtime_caller(runner, "254-ticket@engineer"):
        code, message = refusal(
            project,
            {"change": {"set_presets": {
                "coding_team.engineer": {"system_prompt": SYSTEM_TEXT},
            }}},
            lambda proposal: reviews.append(proposal) or {"decision": "accept"},
        )
    assert code == "authority-denied"
    assert message
    assert reviews == []
    assert snapshot(project) == before


@pytest.mark.parametrize("value", ["", "   ", 7, ["text"]])
def test_malformed_prompt_content_is_refused_without_writing(
    project: Path, value: object,
) -> None:
    """A non-string, blank or NUL prompt value is refused before any reviewer or write."""
    reviews: list[dict] = []
    before = snapshot(project)
    code, message = refusal(
        project,
        {"change": {"set_presets": {"analyst": {"system_prompt": value}}}},
        lambda proposal: reviews.append(proposal) or {"decision": "accept"},
    )
    assert message
    assert code in {None, "invalid-input"}
    assert reviews == []
    assert snapshot(project) == before


def test_prompt_layer_the_runtime_does_not_expose_is_refused_before_dispatch(
    project: Path,
) -> None:
    """A declared layer is refused for the Runtimes that lack it, never folded elsewhere."""
    for runtime in ("pi", "dsh"):
        declared = RolePreset(runtime, "deepseek-flash", None, None,
                              developer_prompt=DEVELOPER_TEXT)
        with pytest.raises(RuntimeAdapterError) as refused:
            resolve_child_role("author", declared, project)
        assert refused.value.code == "ROLE_CONFIG_UNSUPPORTED"
        assert "developer_prompt" in refused.value.message
        assert runtime in refused.value.message


def test_supported_prompt_layers_resolve_into_the_role_text(project: Path) -> None:
    """Each Runtime's own layer resolves; the other layer is not silently carried."""
    analyst = load_project_roles(project).preset("analyst")
    assert analyst.runtime == "codex"

    # Codex keeps the two layers in separate native parameters.
    both = resolve_child_role(
        "analyst",
        replace(analyst, system_prompt=SYSTEM_TEXT, developer_prompt=DEVELOPER_TEXT),
        project,
    )
    assert both.system_instructions == SYSTEM_TEXT
    assert DEVELOPER_TEXT in both.instructions
    assert SYSTEM_TEXT not in both.instructions

    # Codex without a system-level prompt keeps its built-in base prompt.
    developer_only = resolve_child_role(
        "analyst", replace(analyst, developer_prompt=DEVELOPER_TEXT), project,
    )
    assert developer_only.system_instructions == ""
    assert DEVELOPER_TEXT in developer_only.instructions

    for runtime in ("pi", "dsh"):
        declared = RolePreset(runtime, "deepseek-flash", None, None,
                              system_prompt=SYSTEM_TEXT)
        resolved = resolve_child_role("author", declared, project)
        assert SYSTEM_TEXT in resolved.instructions
        assert resolved.system_instructions == ""
        assert DEVELOPER_TEXT not in resolved.instructions
