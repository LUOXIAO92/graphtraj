from __future__ import annotations

import json
import os
import sys
from typing import Dict

import pytest

from conftest import PROJECT_ROOT, find_uv, run_process


RESOURCE_PATHS = {
    "skill": "resources/skills/task-delivery/SKILL.md",
    "skill_metadata": "resources/skills/task-delivery/agents/openai.yaml",
    "delivery_state_role": "resources/codex/agents/delivery-state.toml",
}


def normalized(text: str) -> str:
    return " ".join(text.split()).lower()


@pytest.fixture(scope="module")
def installed_task_delivery_resources(
    tmp_path_factory: pytest.TempPathFactory,
) -> Dict[str, str]:
    """Read release resources from an installed distribution, not the source tree."""
    uv = find_uv()
    if uv is None:
        pytest.skip("uv is unavailable; set UV to its executable or add uv to PATH")

    temporary_directory = tmp_path_factory.mktemp("installed-task-delivery")
    install_directory = temporary_directory / "site-packages"
    environment = os.environ.copy()
    environment["UV_CACHE_DIR"] = str(temporary_directory / "uv-cache")
    install = run_process(
        [
            str(uv),
            "pip",
            "install",
            "--python",
            sys.executable,
            "--target",
            str(install_directory),
            "--no-deps",
            "--no-build-isolation",
            str(PROJECT_ROOT),
        ],
        cwd=temporary_directory,
        env=environment,
    )
    assert install.returncode == 0, install.stderr

    probe = """
import importlib.resources
import json
import sys

sys.path.insert(0, sys.argv[1])
package = importlib.resources.files("you_are_a_product_architect")
paths = json.loads(sys.argv[2])
print(json.dumps({
    name: package.joinpath(*path.split("/")).read_text(encoding="utf-8")
    for name, path in paths.items()
}))
"""
    result = run_process(
        [
            sys.executable,
            "-I",
            "-c",
            probe,
            str(install_directory),
            json.dumps(RESOURCE_PATHS),
        ],
        cwd=temporary_directory,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_installed_task_delivery_skill_has_complete_interface_metadata(
    installed_task_delivery_resources: Dict[str, str],
) -> None:
    skill = installed_task_delivery_resources["skill"]
    metadata = installed_task_delivery_resources["skill_metadata"]

    assert skill.startswith("---\nname: task-delivery\ndescription:")
    assert "TODO" not in skill
    assert 'display_name: "Task Delivery"' in metadata
    assert "Use $task-delivery" in metadata


def test_installed_task_delivery_keeps_semantic_orchestration_with_main(
    installed_task_delivery_resources: Dict[str, str],
) -> None:
    skill = installed_task_delivery_resources["skill"]
    guidance = normalized(skill)

    for required_guidance in (
        "accepted ticket dag",
        "grilling",
        "$to-spec",
        "$to-tickets",
        "complete accepted DAG",
        "plain-language",
        "readiness",
        "tier",
        "dispatch",
        "review",
        "retry",
        "escalation",
        "integration",
        "exceptions",
        "mechanical transport",
    ):
        assert required_guidance.lower() in guidance

    assert "Do not merge into `dev`" in skill
    assert "Do not normalize" in skill
    assert "automatically re-split" in skill
    for required_guidance in (
        "require the engineer to return either a candidate commit and validation evidence",
        "the engineer does not dispatch reviewers",
        "let main fix the candidate commit",
        "main adjudicates both reports",
    ):
        assert required_guidance in guidance


def test_installed_task_delivery_selects_one_runtime_for_each_batch(
    installed_task_delivery_resources: Dict[str, str],
) -> None:
    guidance = normalized(installed_task_delivery_resources["skill"])

    for required_guidance in (
        "explicit user direction",
        "harness project policy",
        "main's current runtime",
        "ask the user and record the answer",
        "one selected runtime once at batch level",
        "do not repeat runtime",
    ):
        assert required_guidance in guidance


def test_installed_task_delivery_runs_one_parallel_fixed_candidate_review_round(
    installed_task_delivery_resources: Dict[str, str],
) -> None:
    guidance = normalized(installed_task_delivery_resources["skill"])

    for required_guidance in (
        "concurrently",
        "separate runner tasks",
        "same fixed ticket worktree",
        "neither axis gating the other",
        "report_file",
        "exact non-overwriting report path",
        "reviewer instruction",
        "main waits for both reports",
        "source repository root `agents.md`",
        "adr 0026",
    ):
        assert required_guidance in guidance
    assert "serialized" not in guidance
    assert "supported reachable state after upstream validation" not in guidance
    assert "concrete observable failure" not in guidance


def test_installed_task_delivery_routes_state_projection_authority_to_adr_0003(
    installed_task_delivery_resources: Dict[str, str],
) -> None:
    guidance = normalized(installed_task_delivery_resources["skill"])

    assert "adr 0003" in guidance
    assert "0003-delivery-state-agent-maintains-run-state.md" in guidance
    assert "sole writer of that run's ledger and mermaid dag" not in guidance
    assert "synchronize after every engineer or reviewer return" not in guidance


def test_installed_task_delivery_assigns_only_mechanical_evidence_work_to_runner(
    installed_task_delivery_resources: Dict[str, str],
) -> None:
    skill = normalized(installed_task_delivery_resources["skill"])

    for required_guidance in (
        "provision or reuse the persistent ticket evidence directory",
        "scoped `.scratch/task-delivery` symlink",
        "write or update `metadata.yml`",
        "mechanically known launch facts",
    ):
        assert required_guidance.lower() in skill


def test_installed_resources_define_delivery_state_identity_and_runner_seam(
    installed_task_delivery_resources: Dict[str, str],
) -> None:
    skill = normalized(installed_task_delivery_resources["skill"])
    role = normalized(installed_task_delivery_resources["delivery_state_role"])

    for guidance in (skill, role):
        for required_contract in (
            "`run_id`",
            "ascii `yyyymmdd-short-name`",
            "semantic lowercase kebab-case short name",
            "optional positive numeric collision suffix such as `-2`",
            "resolve",
            "runner only validates",
        ):
            assert required_contract in guidance

    assert "only when main supplies them from runner results" in role
    assert "ledger references to runner-provisioned evidence" in role
    assert "do not create evidence directories or physical links" in role
    assert "supplied by main or runner" not in role
    assert (
        "create the working task map, ledger, mermaid dag, and ticket evidence links"
        not in role
    )


def test_installed_delivery_state_role_maintains_records_without_deciding(
    installed_task_delivery_resources: Dict[str, str],
) -> None:
    role = installed_task_delivery_resources["delivery_state_role"]
    guidance = normalized(role)

    assert 'name = "delivery-state"' in role
    assert 'model = "gpt-5.6-luna"' in role
    assert 'model_reasoning_effort = "high"' in role
    assert "developer_instructions" in role
    for required_guidance in (
        "one active Delivery Run",
        "sole writer",
        "ledger",
        "Mermaid",
        "read evidence directly",
        "only when Main asks",
        "recover",
        "persistent artifacts",
        "Do not adjudicate reviews",
        "Do not choose",
        "Do not dispatch",
        "Do not accept integration",
    ):
        assert required_guidance.lower() in guidance
