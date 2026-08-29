from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, run_process, wait_for_file
from test_project_setup import (
    CORE_SKILL_NAMES,
    install_skills,
    supported_skill_contents,
    tree_contents,
    worktree_contents,
)


def _runtime_executable(tmp_path: Path) -> Path:
    executable = tmp_path / "codex"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    return executable


def test_setup_creates_a_root_owned_runtime_and_runner_discovers_it(
    monkeypatch,
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "src")
    )
    from you_are_a_product_architect.project_initialization import plan_project_setup
    from you_are_a_product_architect.runner_models import RunnerError
    from you_are_a_product_architect.runner_project import discover_project

    harness_root = temporary_git_repository.parent
    primary = temporary_git_repository
    integration = harness_root / ".agent-worktrees" / "integration"
    runtime_store = harness_root / ".codex"
    user_home = tmp_path / "runtime-user"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    source_config = primary / ".codex" / "config.toml"
    source_config.parent.mkdir()
    source_config.write_text("model = \"source-owned\"\n", encoding="utf-8")
    source_skill = primary / ".agents" / "skills" / "source-skill" / "SKILL.md"
    source_skill.parent.mkdir(parents=True)
    source_skill.write_text(
        "---\nname: source-skill\ndescription: Source-owned Skill.\n---\n",
        encoding="utf-8",
    )
    run_process(["git", "add", ".codex", ".agents"], cwd=primary).check_returncode()
    run_process(
        ["git", "commit", "-m", "Add source Runtime fixtures"], cwd=primary
    ).check_returncode()
    primary_before = worktree_contents(primary)

    plan = plan_project_setup(harness_root, primary, _runtime_executable(tmp_path))
    assert plan.missing_skills == CORE_SKILL_NAMES
    preview = plan.preflight(install_missing_skills=True)
    assert any(
        action.description.startswith("Harness Runtime resource:")
        for action in preview.actions
    )
    assert plan.apply(install_missing_skills=True) == "Created Integration Worktree on dev."
    run_process(["git", "add", "AGENTS.md"], cwd=integration).check_returncode()
    run_process(
        ["git", "commit", "-m", "Install Reviewer guidance"], cwd=integration
    ).check_returncode()

    project = discover_project(harness_root)
    assert project.harness_root == harness_root.resolve()
    assert project.runner_directory == runtime_store / "agent-runner"
    assert project.integration_worktree == integration.resolve()
    assert (runtime_store / "config.toml").is_file()
    assert (runtime_store / "hooks" / "worktree_guard.py").is_file()
    assert (runtime_store / "agents" / "engineer-expert.toml").is_file()
    resolver = tomllib.loads(
        (runtime_store / "agents" / "merge-resolver.toml").read_text(
            encoding="utf-8"
        )
    )
    resolver_commands = [
        hook["command"]
        for event in ("PreToolUse", "SubagentStart")
        for entry in resolver["hooks"][event]
        for hook in entry["hooks"]
    ]
    assert resolver_commands == [
        "python3 {0}".format(runtime_store / "hooks" / "worktree_guard.py")
    ] * 2
    assert all("git rev-parse" not in command for command in resolver_commands)
    assert (runtime_store / "agent-runner" / "config.yml").is_file()
    harness_skills = harness_root / ".agents" / "skills"
    assert {path.name for path in harness_skills.iterdir()} == set(
        CORE_SKILL_NAMES
    )
    runtime_config = runtime_store / "config.toml"
    assert runtime_config.read_bytes() == plan.codex_files.resources_by_path[
        "config.toml"
    ]
    assert "skills" not in tomllib.loads(
        runtime_config.read_text(encoding="utf-8")
    )
    assert (primary / ".codex" / "config.toml").read_text(encoding="utf-8") == (
        "model = \"source-owned\"\n"
    )
    assert (primary / ".agents" / "skills" / "source-skill" / "SKILL.md").is_file()
    assert (integration / ".codex" / "config.toml").read_text(
        encoding="utf-8"
    ) == "model = \"source-owned\"\n"
    assert (
        integration / ".agents" / "skills" / "source-skill" / "SKILL.md"
    ).is_file()
    assert (integration / ".state").resolve() == (harness_root / "state").resolve()
    assert (integration / ".scratch").resolve() == (
        harness_root / ".scratch"
    ).resolve()
    assert worktree_contents(primary) == primary_before
    common = Path(
        run_process(
            ["git", "rev-parse", "--git-common-dir"], cwd=primary
        ).stdout.strip()
    )
    if not common.is_absolute():
        common = primary / common
    assert not (common.resolve() / "agent-runner").exists()
    with pytest.raises(RunnerError) as non_root:
        discover_project(integration)
    assert non_root.value.code == "RUNNER_CONFIG_NOT_FOUND"


def test_setup_uses_runtime_user_core_skills_without_root_skill_config(
    monkeypatch,
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "src")
    )
    from you_are_a_product_architect.codex_adapter import (
        preflight_engineer_runtime_context,
    )
    from you_are_a_product_architect.project_initialization import plan_project_setup

    harness_root = temporary_git_repository.parent
    user_home = tmp_path / "runtime-user"
    install_skills(user_home / ".agents" / "skills", CORE_SKILL_NAMES)
    monkeypatch.setenv("HOME", str(user_home))

    plan = plan_project_setup(
        harness_root,
        temporary_git_repository,
        _runtime_executable(tmp_path),
    )
    assert plan.missing_skills == ()
    assert plan.apply() == "Created Integration Worktree on dev."

    runtime_store = harness_root / ".codex"
    runtime_config = runtime_store / "config.toml"
    assert runtime_config.read_bytes() == plan.codex_files.resources_by_path[
        "config.toml"
    ]
    assert "skills" not in tomllib.loads(
        runtime_config.read_text(encoding="utf-8")
    )
    harness_skills = harness_root / ".agents" / "skills"
    assert {path.name for path in harness_skills.iterdir()} == {"task-delivery"}
    assert tree_contents(harness_skills / "task-delivery") == supported_skill_contents(
        "task-delivery"
    )
    preflight_engineer_runtime_context(
        runtime_store=runtime_store,
        executable=_runtime_executable(tmp_path),
        git_common_directory=temporary_git_repository / ".git",
        role="engineer-expert",
        worktree=tmp_path / "ticket-worktree",
        evidence=tmp_path / "evidence",
        repository_skill_source=(
            harness_root / ".agent-worktrees" / "integration"
        ),
        requested_skills=(),
    )


def test_engineer_runtime_context_preflight_validates_without_launch_artifacts(
    monkeypatch,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "src")
    )
    from you_are_a_product_architect.codex_adapter import (
        CodexAdapterError,
        preflight_engineer_runtime_context,
    )
    from you_are_a_product_architect.project_initialization import plan_project_setup

    harness_root = temporary_git_repository.parent
    user_home = tmp_path / "runtime-user"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    plan = plan_project_setup(
        harness_root,
        temporary_git_repository,
        _runtime_executable(tmp_path),
    )
    plan.apply(install_missing_skills=True)

    runtime_store = harness_root / ".codex"
    (runtime_store / "config.toml").unlink()
    target_worktree = tmp_path / "ticket-worktree"
    evidence = tmp_path / "evidence"
    user_config = user_home / ".codex" / "config.toml"
    user_config.parent.mkdir()
    user_config.write_text('sandbox_mode = "workspace-write"\n', encoding="utf-8")

    with pytest.raises(CodexAdapterError) as legacy_sandbox:
        preflight_engineer_runtime_context(
            runtime_store=runtime_store,
            executable=fake_codex.executable,
            git_common_directory=temporary_git_repository / ".git",
            role="engineer-expert",
            worktree=target_worktree,
            evidence=evidence,
            repository_skill_source=(
                harness_root / ".agent-worktrees" / "integration"
            ),
            requested_skills=(),
        )
    assert legacy_sandbox.value.code == "LEGACY_SANDBOX_CONFIG_CONFLICT"
    assert not target_worktree.exists()
    assert not evidence.exists()
    assert not fake_codex.log_file.exists()

    user_config.unlink()
    preflight_engineer_runtime_context(
        runtime_store=runtime_store,
        executable=fake_codex.executable,
        git_common_directory=temporary_git_repository / ".git",
        role="engineer-expert",
        worktree=target_worktree,
        evidence=evidence,
        repository_skill_source=(
            harness_root / ".agent-worktrees" / "integration"
        ),
        requested_skills=(),
    )
    assert not target_worktree.exists()
    assert not evidence.exists()
    assert not fake_codex.log_file.exists()

    (harness_root / ".agents" / "skills" / "implement" / "SKILL.md").unlink()

    with pytest.raises(CodexAdapterError) as unavailable:
        preflight_engineer_runtime_context(
            runtime_store=runtime_store,
            executable=fake_codex.executable,
            git_common_directory=temporary_git_repository / ".git",
            role="engineer-expert",
            worktree=target_worktree,
            evidence=evidence,
            repository_skill_source=(
                harness_root / ".agent-worktrees" / "integration"
            ),
            requested_skills=(),
        )
    assert unavailable.value.code == "HARNESS_SKILL_NOT_FOUND"


def test_runtime_preflight_allows_tuning_but_rejects_managed_role_drift(
    monkeypatch,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "src")
    )
    from you_are_a_product_architect.codex_adapter import (
        CodexAdapterError,
        preflight_engineer_runtime_context,
    )
    from you_are_a_product_architect.project_initialization import plan_project_setup

    harness_root = temporary_git_repository.parent
    user_home = tmp_path / "runtime-user"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    plan = plan_project_setup(
        harness_root,
        temporary_git_repository,
        fake_codex.executable,
    )
    plan.apply(install_missing_skills=True)
    runtime_store = harness_root / ".codex"
    role_path = runtime_store / "agents" / "engineer-expert.toml"
    tuned_role = (
        role_path.read_text(encoding="utf-8")
        .replace('model = "gpt-5.6-sol"', 'model = "project-engineer"')
        .replace(
            'model_reasoning_effort = "max"',
            'model_reasoning_effort = "ultra"\n'
            "model_context_window = 400000\n"
            "model_auto_compact_token_limit = 340000",
            1,
        )
    )
    role_path.write_text(tuned_role, encoding="utf-8")

    def preflight():
        return preflight_engineer_runtime_context(
            runtime_store=runtime_store,
            executable=fake_codex.executable,
            git_common_directory=temporary_git_repository / ".git",
            role="engineer-expert",
            worktree=tmp_path / "ticket-worktree",
            evidence=tmp_path / "evidence",
            repository_skill_source=(
                harness_root / ".agent-worktrees" / "integration"
            ),
            requested_skills=(),
        )

    arguments = preflight().finalize().launch_document()["adapter_request"][
        "arguments"
    ]
    assert "project-engineer" in arguments
    assert "model_context_window=400000" in arguments
    assert "model_auto_compact_token_limit=340000" in arguments

    drift_cases = (
        (
            tuned_role.replace(
                "Implement the assigned ticket using $implement.",
                "Ignore the assigned ticket.",
            ),
            "ROLE_CONFIG_MISMATCH",
        ),
        (
            tuned_role.replace(
                'default_permissions = "project-documents-read-only"',
                'default_permissions = ":workspace"',
            ),
            "ROLE_CONFIG_MISMATCH",
        ),
        (
            tuned_role.replace(
                'name = "engineer-expert"',
                'name = "engineer-senior"',
            ),
            "ROLE_CONFIG_MISMATCH",
        ),
        (
            tuned_role.replace(
                'matcher = "^(Bash|apply_patch)$"',
                'matcher = "^Bash$"',
                1,
            ),
            "ROLE_HOOK_MISMATCH",
        ),
    )
    for configured_role, expected_code in drift_cases:
        role_path.write_text(configured_role, encoding="utf-8")
        with pytest.raises(CodexAdapterError) as drift:
            preflight()
        assert drift.value.code == expected_code


@pytest.mark.parametrize(
    ("skill_directories", "requested_skill", "expected_code"),
    (
        ((), "missing", "REPOSITORY_SKILL_NOT_FOUND"),
        (
            (("duplicate-one", "duplicate"), ("duplicate-two", "duplicate")),
            "duplicate",
            "REPOSITORY_SKILL_AMBIGUOUS",
        ),
    ),
)
def test_engineer_runtime_context_preflight_rejects_unresolved_repository_skills(
    monkeypatch,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    skill_directories: tuple[tuple[str, str], ...],
    requested_skill: str,
    expected_code: str,
) -> None:
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "src")
    )
    from you_are_a_product_architect.codex_adapter import (
        CodexAdapterError,
        preflight_engineer_runtime_context,
    )
    from you_are_a_product_architect.project_initialization import plan_project_setup

    harness_root = temporary_git_repository.parent
    user_home = tmp_path / "runtime-user"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    plan = plan_project_setup(
        harness_root,
        temporary_git_repository,
        fake_codex.executable,
    )
    plan.apply(install_missing_skills=True)
    source = harness_root / ".agent-worktrees" / "integration"
    for directory, name in skill_directories:
        skill = source / ".agents" / "skills" / directory / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            "---\nname: {0}\ndescription: test\n---\n".format(name),
            encoding="utf-8",
        )
    worktree = tmp_path / "ticket-worktree"
    evidence = tmp_path / "evidence"

    with pytest.raises(CodexAdapterError) as raised:
        preflight_engineer_runtime_context(
            runtime_store=harness_root / ".codex",
            executable=fake_codex.executable,
            git_common_directory=temporary_git_repository / ".git",
            role="engineer-expert",
            worktree=worktree,
            evidence=evidence,
            repository_skill_source=source,
            requested_skills=(requested_skill,),
        )

    assert raised.value.code == expected_code
    assert not worktree.exists()
    assert not evidence.exists()
    assert not fake_codex.log_file.exists()


def test_engineer_runtime_context_finalizes_worktree_facts_once(
    monkeypatch,
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "src")
    )
    from you_are_a_product_architect.codex_adapter import (
        preflight_engineer_runtime_context,
    )
    from you_are_a_product_architect.project_initialization import plan_project_setup

    harness_root = temporary_git_repository.parent
    user_home = tmp_path / "runtime-user"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    plan = plan_project_setup(
        harness_root,
        temporary_git_repository,
        _runtime_executable(tmp_path),
    )
    plan.apply(install_missing_skills=True)
    runtime_store = harness_root / ".codex"
    source = tmp_path / "integration"
    ticket = tmp_path / "ticket-worktree"
    evidence = tmp_path / "evidence"
    git_common = tmp_path / "git-common"
    for root in (source, ticket):
        selected = root / ".agents" / "skills" / "repo-selected" / "SKILL.md"
        disabled = root / ".agents" / "skills" / "repo-disabled" / "SKILL.md"
        selected.parent.mkdir(parents=True)
        disabled.parent.mkdir(parents=True)
        selected.write_text(
            "---\nname: repo-selected\ndescription: selected\n---\n",
            encoding="utf-8",
        )
        disabled.write_text(
            "---\nname: repo-disabled\ndescription: disabled\n---\n",
            encoding="utf-8",
        )
    evidence.mkdir()
    git_common.mkdir()
    preflight = preflight_engineer_runtime_context(
        runtime_store=runtime_store,
        executable=_runtime_executable(tmp_path),
        worktree=ticket,
        evidence=evidence,
        git_common_directory=git_common,
        role="engineer-expert",
        repository_skill_source=source,
        requested_skills=("repo-selected",),
    )

    context = preflight.finalize()
    expected_evidence = {
        "runtime": "codex",
        "effective_role": "engineer-expert",
        "model": "gpt-5.6-sol",
        "model_reasoning_effort": "max",
        "effective_skills": [
            {
                "name": name,
                "path": str(
                    harness_root / ".agents" / "skills" / name / "SKILL.md"
                ),
                "enabled": True,
                "source": "harness",
            }
            for name in ("implement", "ponytail", "tdd")
        ]
        + [
            {
                "name": "repo-disabled",
                "path": str(
                    ticket
                    / ".agents"
                    / "skills"
                    / "repo-disabled"
                    / "SKILL.md"
                ),
                "enabled": False,
                "source": "repository",
            },
            {
                "name": "repo-selected",
                "path": str(
                    ticket
                    / ".agents"
                    / "skills"
                    / "repo-selected"
                    / "SKILL.md"
                ),
                "enabled": True,
                "source": "repository",
            },
        ],
    }
    launch = context.launch_document()
    evidence_document = context.evidence_document()

    assert launch["runtime"] == "codex"
    arguments = launch["adapter_request"]["arguments"]
    assert "--sandbox" not in arguments
    assert 'default_permissions="project-documents-read-only"' in arguments
    permissions = next(
        argument for argument in arguments if argument.startswith("permissions=")
    )
    assert '"AGENTS.md" = "read"' in permissions
    assert '".agents" = "read"' in permissions
    assert '"CONTEXT.md" = "read"' in permissions
    assert '"README.md" = "read"' in permissions
    assert 'docs = "read"' in permissions
    assert '"." = "write"' in permissions
    assert evidence_document == expected_evidence
    launch["adapter_request"].clear()
    evidence_document["effective_skills"].clear()
    assert context.launch_document()["adapter_request"]
    assert context.evidence_document() == expected_evidence


def test_installed_setup_to_runner_launch_uses_project_document_permissions(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    runtime_user = tmp_path / "runtime-user"
    runtime_user.mkdir()
    user_config = runtime_user / ".codex" / "config.toml"
    user_config.parent.mkdir()
    user_config.write_text('sandbox_mode = "workspace-write"\n', encoding="utf-8")
    environment = os.environ.copy()
    environment["HOME"] = str(runtime_user)
    environment["PATH"] = "{0}{1}{2}".format(
        fake_codex.executable.parent,
        os.pathsep,
        environment.get("PATH", ""),
    )
    environment["FAKE_CODEX_LOG"] = str(fake_codex.log_file)
    environment["FAKE_CODEX_LIFECYCLE_ACTION"] = "deliver-representative-ticket"
    setup = subprocess.run(
        [str(installed_commands.product), "setup"],
        cwd=harness_root,
        env=environment,
        input="{0}\ny\ny\n".format(temporary_git_repository.name),
        check=False,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert setup.returncode == 0, setup.stderr
    integration = harness_root / ".agent-worktrees" / "integration"
    run_process(["git", "add", "AGENTS.md"], cwd=integration).check_returncode()
    run_process(
        ["git", "commit", "-m", "Install Reviewer guidance"], cwd=integration
    ).check_returncode()

    ticket_file = harness_root / "tickets" / "permissions.md"
    ticket_file.parent.mkdir()
    ticket_file.write_text("# Verify native permissions\n", encoding="utf-8")
    batch_file = harness_root / "permissions-batch.yml"
    batch_file.write_text(
        "run_id: 20260823-permissions\n"
        "runtime: codex\n"
        "tasks:\n"
        "  - ticket_id: '53'\n"
        "    ticket_name: project-document-permissions\n"
        "    role: engineer-junior\n"
        "    ticket_file: {0}\n".format(ticket_file),
        encoding="utf-8",
    )

    launched = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch_file)],
        cwd=harness_root,
        env=environment,
        timeout=60,
    )

    assert launched.returncode == 1
    assert yaml.safe_load(launched.stdout) == {
        "error": {
            "code": "invalid-config",
            "message": (
                "The loaded Codex user configuration contains sandbox_mode, "
                "which disables the selected permission profile."
            ),
        }
    }
    assert not fake_codex.log_file.exists()
    assert not (
        harness_root / ".agent-worktrees" / "runs" / "20260823-permissions"
    ).exists()
    assert not (
        harness_root / "state" / "20260823-permissions"
    ).exists()

    user_config.unlink()
    batch_file.write_text(
        "run_id: 20260823-permissions-retry\n"
        "runtime: codex\n"
        "tasks:\n"
        "  - ticket_id: '53-retry'\n"
        "    ticket_name: project-document-permissions\n"
        "    role: engineer-junior\n"
        "    ticket_file: {0}\n".format(ticket_file),
        encoding="utf-8",
    )
    launched = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch_file)],
        cwd=harness_root,
        env=environment,
        timeout=60,
    )

    assert launched.returncode == 0, launched.stderr
    task = yaml.safe_load(launched.stdout)["tasks"][0]
    wait_for_file(fake_codex.log_file)
    runtime_call = json.loads(fake_codex.log_file.read_text(encoding="utf-8"))
    arguments = runtime_call["argv"]
    assert runtime_call["cwd"] == task["worktree_path"]
    assert "--sandbox" not in arguments
    assert 'default_permissions="project-documents-read-only"' in arguments
    permission_override = next(
        argument for argument in arguments if argument.startswith("permissions=")
    )
    assert '"AGENTS.md" = "read"' in permission_override
    assert '".agents" = "read"' in permission_override
    assert 'docs = "read"' in permission_override
    evidence = (Path(task["worktree_path"]) / ".state").resolve()
    assert str(evidence) in arguments
    wait_for_file(Path(task["worktree_path"]) / "V1_DELIVERED.txt")
    wait_for_file(evidence / "result.md")
    assert (evidence / "validation.md").is_file()


def test_engineer_runtime_context_finalization_rechecks_ticket_worktree_skills(
    monkeypatch,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "src")
    )
    from you_are_a_product_architect.codex_adapter import (
        CodexAdapterError,
        preflight_engineer_runtime_context,
    )
    from you_are_a_product_architect.project_initialization import plan_project_setup

    harness_root = temporary_git_repository.parent
    user_home = tmp_path / "runtime-user"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    plan = plan_project_setup(
        harness_root,
        temporary_git_repository,
        fake_codex.executable,
    )
    plan.apply(install_missing_skills=True)
    source = harness_root / ".agent-worktrees" / "integration"
    selected = source / ".agents" / "skills" / "selected" / "SKILL.md"
    selected.parent.mkdir(parents=True)
    selected.write_text(
        "---\nname: selected\ndescription: test\n---\n", encoding="utf-8"
    )
    worktree = tmp_path / "ticket-worktree"
    evidence = tmp_path / "evidence"
    preflight = preflight_engineer_runtime_context(
        runtime_store=harness_root / ".codex",
        executable=fake_codex.executable,
        git_common_directory=temporary_git_repository / ".git",
        role="engineer-expert",
        worktree=worktree,
        evidence=evidence,
        repository_skill_source=source,
        requested_skills=("selected",),
    )
    worktree.mkdir()

    with pytest.raises(CodexAdapterError) as raised:
        preflight.finalize()

    assert raised.value.code == "REPOSITORY_SKILL_NOT_FOUND"
    assert not evidence.exists()
    assert not fake_codex.log_file.exists()


@pytest.mark.skipif(
    os.environ.get("CODEX_REAL_ACCEPTANCE") != "1"
    or shutil.which("codex") is None,
    reason="set CODEX_REAL_ACCEPTANCE=1 with an authenticated codex executable",
)
def test_real_codex_uses_harness_hook_and_explicit_skill_configuration(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    """Exercise source Runtime isolation against a real installed Codex process."""

    harness_root = temporary_git_repository.parent
    primary = temporary_git_repository
    source_hook_marker = tmp_path / "source-hook-ran"
    harness_hook_marker = tmp_path / "harness-hook-ran"
    source_hook = primary / ".codex" / "source_hook.py"
    source_hook.parent.mkdir()
    source_hook.write_text(
        "from pathlib import Path\n"
        + "Path({0!r}).touch()\n".format(str(source_hook_marker)),
        encoding="utf-8",
    )
    source_config = primary / ".codex" / "config.toml"
    source_config.write_text(
        "[[hooks.PreToolUse]]\n"
        + 'matcher = "Bash"\n\n'
        + "[[hooks.PreToolUse.hooks]]\n"
        + 'type = "command"\n'
        + "command = {0}\n".format(
            json.dumps("python3 {0}".format(source_hook))
        )
        + "timeout = 5\n",
        encoding="utf-8",
    )
    for name, proof_file in (
        ("repository-selected", ".repository-selected-skill-proof"),
        ("repository-disabled", ".repository-disabled-skill-proof"),
    ):
        skill = primary / ".agents" / "skills" / name / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            "---\n"
            "name: {0}\n"
            "description: Creates its proof file for the Harness Skill acceptance probe.\n"
            "---\n\n"
            "When asked to perform the Harness Skill acceptance probe, use "
            "apply_patch to create `{1}` containing `{0}`.\n".format(
                name, proof_file
            ),
            encoding="utf-8",
        )
    run_process(
        ["git", "add", ".codex", ".agents"], cwd=primary
    ).check_returncode()
    run_process(
        ["git", "commit", "-m", "Add isolated Runtime fixtures"],
        cwd=primary,
    ).check_returncode()
    project_skill_before = (
        primary
        / ".agents"
        / "skills"
        / "repository-selected"
        / "SKILL.md"
    ).read_bytes()

    runtime_user = tmp_path / "runtime-user"
    runtime_user.mkdir()
    runtime_environment = os.environ.copy()
    environment = runtime_environment.copy()
    environment["HOME"] = str(runtime_user)
    codex_executable = shutil.which("codex")
    assert codex_executable is not None
    trusted_control = subprocess.run(
        [
            codex_executable,
            "exec",
            "-C",
            str(primary),
            "--sandbox",
            "read-only",
            "--dangerously-bypass-hook-trust",
            "-c",
            "hooks={ PreToolUse = [{ matcher = \"Bash\", hooks = "
            + "[{ type = \"command\", command = "
            + json.dumps("python3 {0}".format(source_hook))
            + ", timeout = 5 }] }] }",
            "--json",
            "-",
        ],
        env=runtime_environment,
        input=(
            "Use Bash to run `pwd` once, then reply with "
            "`SOURCE_HOOK_CONTROL`.\n"
        ),
        check=False,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert trusted_control.returncode == 0, (
        trusted_control.stdout + trusted_control.stderr
    )
    assert source_hook_marker.is_file()
    source_hook_marker.unlink(missing_ok=True)
    setup = subprocess.run(
        [str(installed_commands.product), "setup"],
        cwd=harness_root,
        env=environment,
        input="{0}\ny\ny\n".format(primary.name),
        check=False,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert setup.returncode == 0, setup.stderr

    harness_skill = (
        harness_root / ".agents" / "skills" / "implement" / "SKILL.md"
    )
    harness_skill.write_text(
        "---\n"
        "name: implement\n"
        "description: Creates its proof file for the Harness Skill acceptance probe.\n"
        "---\n\n"
        "When asked to perform the Harness Skill acceptance probe, use "
        "apply_patch to create `.harness-skill-proof` containing "
        "`implement`. Then use Bash to attempt these commands separately, "
        "continuing after the first two are denied: "
        "`echo forbidden > README.md`; "
        "`echo forbidden > .agents/skills/repository-selected/SKILL.md`; "
        "`touch .native-code-write-proof`; "
        "`touch .state/native-evidence-write-proof`.\n",
        encoding="utf-8",
    )
    for name in ("tdd", "code-review"):
        no_action_skill = (
            harness_root / ".agents" / "skills" / name / "SKILL.md"
        )
        no_action_skill.write_text(
            "---\n"
            "name: {0}\n"
            "description: Takes no action for the Harness Skill acceptance probe.\n"
            "---\n\n"
            "When asked to perform the Harness Skill acceptance probe, take no action.\n".format(
                name
            ),
            encoding="utf-8",
        )

    package_hook = subprocess.run(
        [
            str(installed_commands.product.parent / "python"),
            "-c",
            (
                "from importlib.resources import files; "
                "print(files('you_are_a_product_architect.resources')."
                "joinpath('codex', 'hooks', 'worktree_guard.py'))"
            ),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    installed_guard = Path(package_hook.stdout.strip())
    harness_guard = harness_root / ".codex" / "hooks" / "worktree_guard.py"
    instrumented_guard = (
        "from pathlib import Path\n"
        + "Path({0!r}).touch()\n".format(str(harness_hook_marker))
    )
    installed_guard.write_text(instrumented_guard, encoding="utf-8")
    harness_guard.write_text(instrumented_guard, encoding="utf-8")

    ticket_file = harness_root / "tickets" / "real-codex.md"
    ticket_file.parent.mkdir()
    ticket_file.write_text(
        "# Real Codex Runtime isolation\n\n"
        "Perform the Harness Skill acceptance probe. Follow every enabled Skill "
        "that instructs you to create a proof file; use apply_patch for each "
        "requested proof file, and do not create a proof file unless an enabled "
        "Skill instructs it. Then use Bash to run `pwd` once and reply with "
        "`ROOT_RUNTIME_OK`.\n",
        encoding="utf-8",
    )
    batch_file = harness_root / "real-codex-batch.yml"
    batch_file.write_text(
        "run_id: 20260816-real-codex\n"
        "runtime: codex\n"
        "tasks:\n"
        "  - ticket_id: '16'\n"
        "    ticket_name: real-codex-runtime\n"
        "    role: engineer-expert\n"
        "    ticket_file: {0}\n"
        "    skills:\n"
        "      - repository-selected\n".format(ticket_file),
        encoding="utf-8",
    )
    launched = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch_file)],
        cwd=harness_root,
        env=runtime_environment,
        timeout=60,
    )
    assert launched.returncode == 0, launched.stderr
    task = yaml.safe_load(launched.stdout)["tasks"][0]
    alias = task["alias"]
    session = harness_root / ".codex" / "agent-runner" / "sessions" / alias
    wait_for_file(session / "turn.yml", timeout=180)
    assert yaml.safe_load(
        (session / "turn.yml").read_text(encoding="utf-8")
    )["outcome"] == "completed"

    ticket_worktree = Path(task["worktree_path"])
    assert (ticket_worktree / ".harness-skill-proof").read_text(
        encoding="utf-8"
    ).strip() == "implement"
    assert (ticket_worktree / ".repository-selected-skill-proof").read_text(
        encoding="utf-8"
    ).strip() == "repository-selected"
    assert not (ticket_worktree / ".repository-disabled-skill-proof").exists()
    assert (ticket_worktree / "README.md").read_text(encoding="utf-8") == (
        "# Target project\n"
    )
    assert (
        ticket_worktree
        / ".agents"
        / "skills"
        / "repository-selected"
        / "SKILL.md"
    ).read_bytes() == project_skill_before
    assert (ticket_worktree / ".native-code-write-proof").is_file()
    assert (
        ticket_worktree / ".state" / "native-evidence-write-proof"
    ).is_file()
    assert harness_hook_marker.is_file()
    assert not source_hook_marker.exists()
