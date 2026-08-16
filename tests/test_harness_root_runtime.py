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

    project = discover_project(harness_root)
    assert project.harness_root == harness_root.resolve()
    assert project.runner_directory == runtime_store / "agent-runner"
    assert project.integration_worktree == integration.resolve()
    assert (runtime_store / "config.toml").is_file()
    assert (runtime_store / "hooks" / "worktree_guard.py").is_file()
    assert (runtime_store / "agents" / "engineer-expert.toml").is_file()
    assert (runtime_store / "agent-runner" / "config.yml").is_file()
    harness_skills = harness_root / ".agents" / "skills"
    assert {path.name for path in harness_skills.iterdir()} == set(
        CORE_SKILL_NAMES
    )
    runtime_config = tomllib.loads(
        (runtime_store / "config.toml").read_text(encoding="utf-8")
    )
    assert runtime_config["skills"]["config"] == [
        {
            "path": str(harness_skills / name / "SKILL.md"),
            "enabled": True,
        }
        for name in CORE_SKILL_NAMES
    ]
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
    assert (integration / ".scratch").resolve() == (harness_root / "state").resolve()
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


def test_setup_configures_main_skills_from_the_runtime_user_scope(
    monkeypatch,
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "src")
    )
    from you_are_a_product_architect.codex_adapter import resolve_codex_role
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
    runtime_config = tomllib.loads(
        (runtime_store / "config.toml").read_text(encoding="utf-8")
    )
    assert runtime_config["skills"]["config"] == [
        {
            "path": str(
                user_home / ".agents" / "skills" / name / "SKILL.md"
            ),
            "enabled": True,
        }
        for name in CORE_SKILL_NAMES
    ]
    assert not (harness_root / ".agents" / "skills").exists()
    assert resolve_codex_role(runtime_store, "engineer-expert").name == (
        "engineer-expert"
    )


def test_adapter_uses_root_role_hook_and_explicit_skill_paths(
    monkeypatch,
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "src")
    )
    from you_are_a_product_architect.codex_adapter import (
        CodexAdapterError,
        resolve_codex_role,
        resolve_effective_skills,
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
    ticket = tmp_path / "ticket-worktree"
    selected = ticket / ".agents" / "skills" / "repo-selected" / "SKILL.md"
    disabled = ticket / ".agents" / "skills" / "repo-disabled" / "SKILL.md"
    source_config = ticket / ".codex" / "config.toml"
    selected.parent.mkdir(parents=True)
    disabled.parent.mkdir(parents=True)
    source_config.parent.mkdir(parents=True)
    selected.write_text(
        "---\nname: repo-selected\ndescription: selected\n---\n",
        encoding="utf-8",
    )
    disabled.write_text(
        "---\nname: repo-disabled\ndescription: disabled\n---\n",
        encoding="utf-8",
    )
    source_config.write_text("model = \"source-poison\"\n", encoding="utf-8")
    evidence = tmp_path / "evidence"
    git_common = tmp_path / "git-common"
    evidence.mkdir()
    git_common.mkdir()

    role = resolve_codex_role(runtime_store, "engineer-expert")
    effective = resolve_effective_skills(
        runtime_store,
        ticket,
        "engineer-expert",
        ("repo-selected",),
    )
    request = role.launch_request(
        executable=_runtime_executable(tmp_path),
        worktree=ticket,
        evidence=evidence,
        git_common_directory=git_common,
        runtime_store=runtime_store,
        effective_skills=effective,
    )
    arguments = request["arguments"]
    overrides = {}
    for index, argument in enumerate(arguments):
        if argument == "-c":
            overrides.update(tomllib.loads(arguments[index + 1]))

    assert overrides["developer_instructions"].startswith(
        "Implement the assigned ticket using [$implement]({0}).\n"
        "Use [$tdd]({1}) for behavior changes and [$code-review]({2}) "
        "before handing off the candidate.\n".format(
            harness_root / ".agents" / "skills" / "implement" / "SKILL.md",
            harness_root / ".agents" / "skills" / "tdd" / "SKILL.md",
            harness_root / ".agents" / "skills" / "code-review" / "SKILL.md",
        )
    )
    assert overrides["projects"][str(ticket)]["trust_level"] == "untrusted"
    hooks = overrides["hooks"]
    for event in ("PreToolUse", "SubagentStart"):
        for entry in hooks[event]:
            for hook in entry["hooks"]:
                assert str(runtime_store / "hooks" / "worktree_guard.py") in hook[
                    "command"
                ]
                assert str(ticket / ".codex") not in hook["command"]
    by_path = {
        entry["path"]: entry["enabled"]
        for entry in overrides["skills"]["config"]
    }
    assert by_path[str(selected.resolve())] is True
    assert by_path[str(disabled.resolve())] is False
    assert all(
        by_path[
            str(harness_root / ".agents" / "skills" / name / "SKILL.md")
        ] is True
        for name in ("implement", "tdd", "code-review")
    )
    assert [skill.name for skill in effective if skill.source == "repository"] == [
        "repo-disabled",
        "repo-selected",
    ]
    with pytest.raises(CodexAdapterError, match="not found") as missing:
        resolve_effective_skills(
            runtime_store,
            ticket,
            "engineer-expert",
            ("missing",),
        )
    assert missing.value.code == "REPOSITORY_SKILL_NOT_FOUND"
    for directory in ("duplicate-one", "duplicate-two"):
        duplicate = ticket / ".agents" / "skills" / directory / "SKILL.md"
        duplicate.parent.mkdir(parents=True)
        duplicate.write_text(
            "---\nname: duplicate\ndescription: ambiguous\n---\n",
            encoding="utf-8",
        )
    with pytest.raises(CodexAdapterError, match="ambiguous") as ambiguous:
        resolve_effective_skills(
            runtime_store,
            ticket,
            "engineer-expert",
            ("duplicate",),
        )
    assert ambiguous.value.code == "REPOSITORY_SKILL_AMBIGUOUS"


def test_resume_reuses_the_persisted_request_after_runtime_changes(
    monkeypatch,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "src")
    )
    from you_are_a_product_architect.codex_adapter import (
        create_codex_resume_turn,
        resolve_codex_role,
        resolve_effective_skills,
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
    ticket = tmp_path / "ticket-worktree"
    evidence = tmp_path / "evidence"
    git_common = tmp_path / "git-common"
    ticket.mkdir()
    evidence.mkdir()
    git_common.mkdir()
    role = resolve_codex_role(runtime_store, "engineer-expert")
    request = role.launch_request(
        executable=fake_codex.executable,
        worktree=ticket,
        evidence=evidence,
        git_common_directory=git_common,
        runtime_store=runtime_store,
        effective_skills=resolve_effective_skills(
            runtime_store,
            ticket,
            "engineer-expert",
            (),
        ),
    )
    session_directory = tmp_path / "session"
    session_directory.mkdir()
    session = "persisted-session"
    (ticket / ".codex").mkdir()
    (ticket / ".codex" / "config.toml").write_text(
        "model = \"source-changed\"\n", encoding="utf-8"
    )
    (runtime_store / "agents" / "engineer-expert.toml").write_text(
        "name = \"changed-after-launch\"\n", encoding="utf-8"
    )
    monkeypatch.setenv("FAKE_CODEX_LOG", str(fake_codex.log_file))
    monkeypatch.setenv(
        "FAKE_CODEX_EVENTS",
        json.dumps([{"type": "thread.started", "thread_id": session}]),
    )
    resumed = []
    turn = create_codex_resume_turn(
        request,
        "Resume the persisted request.",
        session,
        session_directory,
        lambda identity, process_id: resumed.append(identity),
    )
    turn.run()
    runtime_record = json.loads(fake_codex.log_file.read_text(encoding="utf-8"))
    assert resumed == [session]
    assert runtime_record["argv"] == [
        *request["arguments"][1:-1],
        "resume",
        session,
        "-",
    ]


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

    runtime_user = tmp_path / "runtime-user"
    runtime_user.mkdir()
    environment = os.environ.copy()
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
        env=environment,
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
        "`implement`.\n",
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
        env=environment,
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

    request = yaml.safe_load(
        (session / "launch.yml").read_text(encoding="utf-8")
    )["adapter_request"]
    overrides = {}
    for index, argument in enumerate(request["arguments"]):
        if argument == "-c":
            overrides.update(tomllib.loads(request["arguments"][index + 1]))
    ticket_worktree = Path(task["worktree_path"])
    assert overrides["projects"][str(ticket_worktree)]["trust_level"] == "untrusted"
    selected = (
        ticket_worktree
        / ".agents"
        / "skills"
        / "repository-selected"
        / "SKILL.md"
    )
    disabled = (
        ticket_worktree
        / ".agents"
        / "skills"
        / "repository-disabled"
        / "SKILL.md"
    )
    configured_skills = {
        Path(entry["path"]): entry["enabled"]
        for entry in overrides["skills"]["config"]
    }
    assert configured_skills[harness_skill] is True
    assert configured_skills[selected] is True
    assert configured_skills[disabled] is False
    assert (ticket_worktree / ".harness-skill-proof").read_text(
        encoding="utf-8"
    ).strip() == "implement"
    assert (ticket_worktree / ".repository-selected-skill-proof").read_text(
        encoding="utf-8"
    ).strip() == "repository-selected"
    assert not (ticket_worktree / ".repository-disabled-skill-proof").exists()
    assert harness_hook_marker.is_file()
    assert not source_hook_marker.exists()
