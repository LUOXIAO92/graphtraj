from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from conftest import FakeCodex, InstalledCommands, run_process


CORE_SKILL_NAMES = (
    "setup-matt-pocock-skills",
    "grill-with-docs",
    "grilling",
    "domain-modeling",
    "to-spec",
    "to-tickets",
    "task-delivery",
    "implement",
    "ponytail",
    "tdd",
    "code-review",
    "resolving-merge-conflicts",
)

REVIEWER_GUIDANCE_START = (
    "<!-- you-are-a-product-architect:reviewer-guidance:start -->"
)
REVIEWER_GUIDANCE_END = (
    "<!-- you-are-a-product-architect:reviewer-guidance:end -->"
)


def canonical_reviewer_guidance() -> str:
    project_document = Path(__file__).resolve().parents[1] / "AGENTS.md"
    content = project_document.read_text(encoding="utf-8")
    start = content.index(REVIEWER_GUIDANCE_START)
    end = content.index(REVIEWER_GUIDANCE_END, start) + len(REVIEWER_GUIDANCE_END)
    return content[start:end]


def install_skills(skill_root: Path, names: Iterable[str]) -> None:
    for name in names:
        skill_directory = skill_root / name
        skill_directory.mkdir(parents=True)
        (skill_directory / "SKILL.md").write_text(
            "---\nname: {0}\ndescription: Test Skill.\n---\n".format(name),
            encoding="utf-8",
        )


def install_user_skills(user_home: Path) -> None:
    install_skills(user_home / ".agents" / "skills", CORE_SKILL_NAMES)


def tree_contents(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def worktree_contents(root: Path) -> dict[str, bytes]:
    return {
        relative_path: path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
        for relative_path in (str(path.relative_to(root)),)
        if not relative_path.startswith(".git/") and relative_path != ".git"
    }


def supported_skill_contents(name: str) -> dict[str, bytes]:
    package_root = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "you_are_a_product_architect"
        / "resources"
    )
    if name == "task-delivery":
        return tree_contents(package_root / "skills" / name)
    return tree_contents(package_root / "codex" / "skills" / name)


def setup_environment(user_home: Path, fake_codex: FakeCodex) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(user_home),
            "PATH": os.pathsep.join(
                (str(fake_codex.executable.parent), environment.get("PATH", ""))
            ),
            "FAKE_CODEX_LOG": str(fake_codex.log_file),
        }
    )
    return environment


def run_setup(
    installed_commands: InstalledCommands,
    *,
    harness_root: Path,
    user_home: Path,
    fake_codex: FakeCodex,
    answers: str,
    commit_project_document: bool = False,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(installed_commands.product), "setup"],
        cwd=harness_root,
        env=setup_environment(user_home, fake_codex),
        input=answers,
        check=False,
        text=True,
        capture_output=True,
    )
    integration = harness_root / ".agent-worktrees" / "integration"
    if (
        commit_project_document
        and result.returncode == 0
        and git_output(integration, "status", "--porcelain", "--", "AGENTS.md")
    ):
        run_process(["git", "add", "AGENTS.md"], cwd=integration).check_returncode()
        run_process(
            ["git", "commit", "-m", "Install Reviewer guidance"],
            cwd=integration,
        ).check_returncode()
    return result


def run_ready_setup(
    installed_commands: InstalledCommands,
    *,
    harness_root: Path,
    user_home: Path,
    fake_codex: FakeCodex,
    answers: str,
) -> subprocess.CompletedProcess[str]:
    return run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers=answers,
        commit_project_document=True,
    )


def git_output(repository: Path, *arguments: str) -> str:
    result = run_process(["git", *arguments], cwd=repository)
    result.check_returncode()
    return result.stdout.strip()


def commit_dev_files_without_leaving_dev_checked_out(
    primary: Path,
    seed_worktree: Path,
    files: dict[str, str],
) -> None:
    run_process(["git", "branch", "dev"], cwd=primary).check_returncode()
    run_process(
        ["git", "worktree", "add", str(seed_worktree), "dev"], cwd=primary
    ).check_returncode()
    for relative_path, content in files.items():
        target = seed_worktree / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    run_process(["git", "add", "."], cwd=seed_worktree).check_returncode()
    run_process(
        ["git", "commit", "-m", "Seed conflicting dev resources"],
        cwd=seed_worktree,
    ).check_returncode()
    run_process(
        ["git", "worktree", "remove", str(seed_worktree)], cwd=primary
    ).check_returncode()


def test_setup_creates_missing_project_document_with_reviewer_guidance(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    integration = harness_root / ".agent-worktrees" / "integration"
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)

    result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(temporary_git_repository.name),
    )

    assert result.returncode == 0, result.stderr
    assert (integration / "AGENTS.md").read_text(encoding="utf-8") == (
        "# AGENTS.md\n\n{0}\n".format(canonical_reviewer_guidance())
    )
    assert "CREATE: Reviewer guidance Project Document" in result.stdout


def test_setup_preserves_existing_project_document_content(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    integration = harness_root / ".agent-worktrees" / "integration"
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    user_content = "# Team instructions\n\nKeep this exactly.\n"
    commit_dev_files_without_leaving_dev_checked_out(
        temporary_git_repository,
        tmp_path / "seed-dev",
        {"AGENTS.md": user_content},
    )

    result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\n".format(temporary_git_repository.name),
    )

    assert result.returncode == 0, result.stderr
    assert (integration / "AGENTS.md").read_text(encoding="utf-8") == (
        user_content + "\n" + canonical_reviewer_guidance() + "\n"
    )
    assert "REPLACE: Reviewer guidance Project Document" in result.stdout


def test_setup_updates_one_managed_reviewer_section_at_the_end(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    integration = harness_root / ".agent-worktrees" / "integration"
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    stale = (
        REVIEWER_GUIDANCE_START
        + "\n\n## Reviewer guidance\n\nStale copy.\n\n"
        + REVIEWER_GUIDANCE_END
    )
    existing = "# User heading\n" + stale + "\nUser tail\n" + stale + "\n"
    commit_dev_files_without_leaving_dev_checked_out(
        temporary_git_repository,
        tmp_path / "seed-dev",
        {"AGENTS.md": existing},
    )

    result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\n".format(temporary_git_repository.name),
    )

    assert result.returncode == 0, result.stderr
    installed = (integration / "AGENTS.md").read_text(encoding="utf-8")
    assert installed.count(REVIEWER_GUIDANCE_START) == 1
    assert installed.count(REVIEWER_GUIDANCE_END) == 1
    assert installed.endswith(canonical_reviewer_guidance() + "\n")
    assert "# User heading\n" in installed
    assert "\nUser tail\n" in installed
    assert "Stale copy." not in installed


def test_setup_rerun_does_not_rewrite_managed_reviewer_guidance(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    integration = harness_root / ".agent-worktrees" / "integration"
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    first = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(temporary_git_repository.name),
    )
    assert first.returncode == 0, first.stderr
    agents = integration / "AGENTS.md"
    before = agents.read_bytes()

    second = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\n".format(temporary_git_repository.name),
    )

    assert second.returncode == 0, second.stderr
    assert "ALREADY CONFIGURED: Reviewer guidance Project Document" in second.stdout
    assert agents.read_bytes() == before


def test_setup_reports_all_preflight_conflicts_without_mutation(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    primary = temporary_git_repository
    integration = harness_root / ".agent-worktrees" / "integration"
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    user_before = tree_contents(user_home)

    commit_dev_files_without_leaving_dev_checked_out(
        primary,
        tmp_path / "seed-dev",
        {".codex/config.toml": "operator-owned = true\n"},
    )
    runner_config = harness_root / ".codex" / "agent-runner" / "config.yml"
    runner_config.parent.mkdir(parents=True)
    (harness_root / ".codex" / "config.toml").write_text(
        "operator-owned = true\n", encoding="utf-8"
    )
    runner_config.write_text("operator-owned: true\n", encoding="utf-8")

    primary_files = worktree_contents(primary)
    worktrees_before = git_output(primary, "worktree", "list", "--porcelain")
    runner_before = runner_config.read_bytes()

    result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\n".format(primary.name),
    )

    assert result.returncode == 1
    assert "Setup preflight found conflicts" in result.stderr
    assert ".codex/config.toml" in result.stderr
    assert str(runner_config) in result.stderr
    assert not integration.exists()
    assert not (harness_root / ".agent-worktrees").exists()
    assert not (harness_root / "state").exists()
    assert git_output(primary, "worktree", "list", "--porcelain") == worktrees_before
    assert worktree_contents(primary) == primary_files
    assert runner_config.read_bytes() == runner_before
    assert tree_contents(user_home) == user_before
    assert not fake_codex.log_file.exists()


def test_setup_refuses_a_dev_checkout_owned_by_another_worktree(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    primary = temporary_git_repository
    foreign_dev = tmp_path / "operator-dev-worktree"
    run_process(["git", "branch", "dev"], cwd=primary).check_returncode()
    run_process(
        ["git", "worktree", "add", str(foreign_dev), "dev"], cwd=primary
    ).check_returncode()
    (foreign_dev / "operator-note.txt").write_text(
        "uncommitted operator work\n",
        encoding="utf-8",
    )

    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    worktrees_before = git_output(primary, "worktree", "list", "--porcelain")

    result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\n".format(primary.name),
    )

    assert result.returncode == 1
    assert "Setup preflight found conflicts" in result.stderr
    assert "dev is already checked out at a different Worktree" in result.stderr
    assert str(foreign_dev) in result.stderr
    assert not (harness_root / ".agent-worktrees").exists()
    assert not (harness_root / "state").exists()
    assert git_output(primary, "worktree", "list", "--porcelain") == worktrees_before
    assert (foreign_dev / "operator-note.txt").read_text(encoding="utf-8") == (
        "uncommitted operator work\n"
    )
    assert not fake_codex.log_file.exists()


def test_setup_reports_a_prunable_dev_registration_without_mutation(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    primary = temporary_git_repository
    worktree_root = harness_root / ".agent-worktrees"
    integration = worktree_root / "integration"
    runtime_store = harness_root / ".codex"
    state = harness_root / "state"
    run_process(["git", "branch", "dev"], cwd=primary).check_returncode()
    run_process(
        ["git", "worktree", "add", str(integration), "dev"], cwd=primary
    ).check_returncode()
    shutil.rmtree(integration)

    user_home = tmp_path / "operator-home"
    install_skills(
        user_home / ".agents" / "skills",
        tuple(name for name in CORE_SKILL_NAMES if name != "task-delivery"),
    )
    worktrees_before = git_output(primary, "worktree", "list", "--porcelain")

    result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(primary.name),
    )

    assert result.returncode == 1
    assert "stale or prunable Git Worktree registration" in result.stderr
    assert git_output(primary, "worktree", "list", "--porcelain") == worktrees_before
    assert not integration.exists()
    assert not runtime_store.exists()
    assert not state.exists()
    assert not fake_codex.log_file.exists()


def test_setup_rejects_runtime_and_skill_symlink_redirection_before_mutation(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    primary = temporary_git_repository
    integration = harness_root / ".agent-worktrees" / "integration"
    run_process(["git", "branch", "dev"], cwd=primary).check_returncode()
    run_process(
        ["git", "worktree", "add", str(integration), "dev"], cwd=primary
    ).check_returncode()

    neighbor = harness_root / "neighbor-project"
    runtime_redirect = neighbor / "runtime"
    skill_redirect = neighbor / "skill"
    runtime_redirect.mkdir(parents=True)
    skill_redirect.mkdir()
    (neighbor / "marker.txt").write_text("leave me alone\n", encoding="utf-8")
    (integration / ".codex").symlink_to(runtime_redirect, target_is_directory=True)
    skill_root = integration / ".agents" / "skills"
    skill_root.mkdir(parents=True)
    (skill_root / "domain-modeling").symlink_to(
        skill_redirect,
        target_is_directory=True,
    )
    runtime_store = harness_root / ".codex"
    runtime_store.mkdir()
    (runtime_store / "config.toml").symlink_to(runtime_redirect / "config.toml")
    root_skill_directory = harness_root / ".agents" / "skills"
    root_skill_directory.mkdir(parents=True)
    (root_skill_directory / "domain-modeling").symlink_to(
        skill_redirect,
        target_is_directory=True,
    )

    user_home = tmp_path / "operator-home"
    install_skills(
        user_home / ".agents" / "skills",
        tuple(name for name in CORE_SKILL_NAMES if name != "domain-modeling"),
    )
    result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(primary.name),
    )

    assert result.returncode == 1
    assert "Setup preflight found conflicts" in result.stderr
    assert ".codex" in result.stderr
    assert "skills/domain-modeling" in result.stderr
    assert not (harness_root / "state").exists()
    assert not (runtime_store / "agent-runner" / "config.yml").exists()
    assert (integration / ".codex").is_symlink()
    assert (skill_root / "domain-modeling").is_symlink()
    assert (runtime_store / "config.toml").is_symlink()
    assert (root_skill_directory / "domain-modeling").is_symlink()
    assert not fake_codex.log_file.exists()


def test_setup_recovers_a_byte_identical_partial_task_delivery_projection(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    primary = temporary_git_repository
    integration = harness_root / ".agent-worktrees" / "integration"
    run_process(["git", "branch", "dev"], cwd=primary).check_returncode()
    run_process(
        ["git", "worktree", "add", str(integration), "dev"], cwd=primary
    ).check_returncode()

    partial_skill = harness_root / ".agents" / "skills" / "task-delivery"
    partial_skill.mkdir(parents=True)
    supported = supported_skill_contents("task-delivery")
    partial_file = partial_skill / "SKILL.md"
    partial_file.write_bytes(supported["SKILL.md"])
    partial_mtime = partial_file.stat().st_mtime_ns

    user_home = tmp_path / "operator-home"
    install_skills(
        user_home / ".agents" / "skills",
        tuple(name for name in CORE_SKILL_NAMES if name != "task-delivery"),
    )

    result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(primary.name),
    )

    assert result.returncode == 0, result.stderr
    assert "ALREADY CONFIGURED: Harness Skill task-delivery" in result.stdout
    assert "CREATE: Harness Skill task-delivery" in result.stdout
    assert tree_contents(partial_skill) == supported
    assert partial_file.stat().st_mtime_ns == partial_mtime
    assert not fake_codex.log_file.exists()


def test_setup_repairs_a_complete_stale_task_delivery_projection(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    primary = temporary_git_repository
    task_delivery = harness_root / ".agents" / "skills" / "task-delivery"
    supported = supported_skill_contents("task-delivery")
    for relative_path in supported:
        target = task_delivery / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("stale\n", encoding="utf-8")
    (task_delivery / "SKILL.md").write_text(
        "---\nname: task-delivery\ndescription: Stale Skill.\n---\n",
        encoding="utf-8",
    )
    operator_note = task_delivery / "operator-note.md"
    operator_note.write_text("leave me alone\n", encoding="utf-8")
    unrelated_skill = harness_root / ".agents" / "skills" / "operator-skill"
    unrelated_skill.mkdir()
    unrelated_file = unrelated_skill / "SKILL.md"
    unrelated_file.write_text("operator-owned\n", encoding="utf-8")

    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)

    first = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(primary.name),
    )

    assert first.returncode == 0, first.stderr
    assert "REPLACE: Harness Skill task-delivery:" in first.stdout
    assert {
        relative_path: (task_delivery / relative_path).read_bytes()
        for relative_path in supported
    } == supported
    assert operator_note.read_text(encoding="utf-8") == "leave me alone\n"
    assert unrelated_file.read_text(encoding="utf-8") == "operator-owned\n"

    second = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\n".format(primary.name),
    )

    assert second.returncode == 0, second.stderr
    assert {
        relative_path: (task_delivery / relative_path).read_bytes()
        for relative_path in supported
    } == supported
    assert operator_note.read_text(encoding="utf-8") == "leave me alone\n"
    assert unrelated_file.read_text(encoding="utf-8") == "operator-owned\n"


def test_setup_rerun_reports_an_already_configured_plan_without_rewriting(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    primary = temporary_git_repository
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)

    first = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(primary.name),
    )
    assert first.returncode == 0, first.stderr

    runtime_store = harness_root / ".codex"
    runtime_config = runtime_store / "config.toml"
    runtime_config.write_text(
        runtime_config.read_text(encoding="utf-8")
        .replace('model = "gpt-5.6-sol"', 'model = "project-main"')
        .replace(
            'model_reasoning_effort = "xhigh"',
            'model_reasoning_effort = "high"\n'
            "model_context_window = 400000",
        )
        .replace(
            "model_auto_compact_token_limit = 204000",
            "model_auto_compact_token_limit = 340000",
        ),
        encoding="utf-8",
    )
    engineer_role = runtime_store / "agents" / "engineer-expert.toml"
    engineer_role.write_text(
        engineer_role.read_text(encoding="utf-8")
        .replace('model = "gpt-5.6-sol"', 'model = "project-engineer"')
        .replace(
            'model_reasoning_effort = "max"',
            'model_reasoning_effort = "ultra"\n'
            "model_context_window = 400000\n"
            "model_auto_compact_token_limit = 340000",
            1,
        ),
        encoding="utf-8",
    )
    before = {
        runtime_config: runtime_config.read_bytes(),
        engineer_role: engineer_role.read_bytes(),
    }

    second = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\n".format(primary.name),
    )

    assert second.returncode == 0, second.stderr
    assert {path: path.read_bytes() for path in before} == before


def test_setup_reports_partial_execution_and_rerun_recovers(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    primary = temporary_git_repository
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    real_git = shutil.which("git")
    assert real_git is not None
    failure_marker = tmp_path / "git-worktree-add-failed-once"
    git_wrapper = fake_codex.executable.parent / "git"
    git_wrapper.write_text(
        "#!{0}\n".format(sys.executable)
        + (
            "import os\n"
            "import sys\n"
            "from pathlib import Path\n"
            "\n"
            "real_git = {0!r}\n"
            "marker = Path({1!r})\n"
            "arguments = sys.argv[1:]\n"
            "if arguments[:2] == ['worktree', 'add'] and not marker.exists():\n"
            "    marker.write_text('failed once\\n', encoding='utf-8')\n"
            "    print('injected git worktree failure', file=sys.stderr)\n"
            "    raise SystemExit(73)\n"
            "os.execv(real_git, [real_git, *arguments])\n"
        ).format(real_git, str(failure_marker)),
        encoding="utf-8",
    )
    git_wrapper.chmod(0o755)

    failed = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(primary.name),
    )

    assert failed.returncode == 1
    assert "injected git worktree failure" in failed.stderr
    assert "Setup execution stopped" in failed.stderr
    assert (harness_root / ".agent-worktrees").is_dir()
    assert (harness_root / "state").is_dir()
    assert not (harness_root / ".agent-worktrees" / "integration").exists()
    assert run_process(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/dev"],
        cwd=primary,
    ).returncode == 0
    assert not (harness_root / ".codex" / "agent-runner" / "config.yml").exists()
    assert not fake_codex.log_file.exists()

    rerun = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\n".format(primary.name),
    )

    assert rerun.returncode == 0, rerun.stderr
    assert "Harness Project setup complete." in rerun.stdout
    assert (harness_root / ".agent-worktrees" / "integration").is_dir()
    assert git_output(
        harness_root / ".agent-worktrees" / "integration",
        "branch",
        "--show-current",
    ) == "dev"
    assert (harness_root / ".codex" / "agent-runner" / "config.yml").is_file()
    assert not fake_codex.log_file.exists()


def test_setup_confirms_the_exact_base_and_initializes_one_harness_project(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    primary = temporary_git_repository
    worktree_root = harness_root / ".agent-worktrees"
    integration = worktree_root / "integration"
    state = harness_root / "state"
    scratch_root = harness_root / ".scratch"
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    user_before = tree_contents(user_home)
    primary_head = git_output(primary, "rev-parse", "HEAD")
    primary_files = worktree_contents(primary)

    result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(primary.name),
    )

    assert result.returncode == 0, result.stderr
    assert integration.is_dir()
    assert state.is_dir()
    assert scratch_root.is_dir()
    assert git_output(integration, "branch", "--show-current") == "dev"
    assert git_output(integration, "rev-parse", "HEAD") == primary_head

    runtime_store = harness_root / ".codex"
    assert (runtime_store / "config.toml").is_file()
    assert (runtime_store / "agent-runner" / "config.yml").is_file()
    task_delivery = harness_root / ".agents" / "skills" / "task-delivery"
    assert tree_contents(task_delivery) == supported_skill_contents("task-delivery")

    state_link = integration / ".state"
    scratch_link = integration / ".scratch"
    assert state_link.is_symlink()
    assert state_link.resolve() == state.resolve()
    assert scratch_link.is_symlink()
    assert scratch_link.resolve() == scratch_root.resolve()
    for ignored_path in (".state", ".scratch"):
        ignored = run_process(
            ["git", "check-ignore", "--quiet", ignored_path], cwd=integration
        )
        assert ignored.returncode == 0

    assert worktree_contents(primary) == primary_files
    assert tree_contents(user_home) == user_before
    assert not fake_codex.log_file.exists()


def test_setup_registers_an_existing_valid_dev_as_the_integration_worktree(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    primary = temporary_git_repository
    worktree_root = harness_root / ".agent-worktrees"
    integration = worktree_root / "integration"
    state = harness_root / "state"
    scratch_root = harness_root / ".scratch"
    run_process(["git", "branch", "dev"], cwd=primary).check_returncode()

    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    user_before = tree_contents(user_home)
    dev_head = git_output(primary, "rev-parse", "dev")
    primary_files = worktree_contents(primary)

    result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\n".format(primary.name),
    )

    assert result.returncode == 0, result.stderr
    assert state.is_dir()
    assert integration.is_dir()
    assert git_output(integration, "branch", "--show-current") == "dev"
    assert git_output(integration, "rev-parse", "HEAD") == dev_head
    assert tree_contents(user_home) == user_before
    assert worktree_contents(primary) == primary_files
    assert (integration / ".state").resolve() == state.resolve()
    assert (integration / ".scratch").resolve() == scratch_root.resolve()
    assert not fake_codex.log_file.exists()

    assert (harness_root / ".codex" / "agent-runner" / "config.yml").is_file()


def test_setup_stops_before_any_mutation_for_runtime_user_scope_skill_installation(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    primary = temporary_git_repository
    user_home = tmp_path / "operator-home"
    user_home.mkdir()
    (user_home / "operator-note.txt").write_text(
        "leave user scope alone\n", encoding="utf-8"
    )
    user_before = tree_contents(user_home)
    primary_files = worktree_contents(primary)

    result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\nn\n".format(primary.name),
    )

    assert result.returncode == 1
    assert "Missing required core Skills:" in result.stdout
    assert "Setup stopped before any setup mutation." in result.stderr

    assert not (harness_root / ".agent-worktrees").exists()
    assert not (harness_root / "state").exists()
    assert not (harness_root / ".codex").exists()
    assert worktree_contents(primary) == primary_files
    assert tree_contents(user_home) == user_before


def test_setup_installs_only_missing_supported_skills_in_harness_runtime_store(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    primary = temporary_git_repository
    integration = harness_root / ".agent-worktrees" / "integration"
    run_process(["git", "branch", "dev"], cwd=primary).check_returncode()
    run_process(
        ["git", "worktree", "add", str(integration), "dev"], cwd=primary
    ).check_returncode()

    project_skills = integration / ".agents" / "skills"
    install_skills(project_skills, ("grilling",))
    existing_grilling = project_skills / "grilling" / "SKILL.md"
    existing_grilling.write_text(
        "---\nname: grilling\ndescription: Existing project Skill.\n---\n",
        encoding="utf-8",
    )
    grilling_before = existing_grilling.read_bytes()

    user_home = tmp_path / "operator-home"
    install_skills(user_home / ".agents" / "skills", ("tdd",))
    user_before = tree_contents(user_home)
    missing_names = tuple(
        name for name in CORE_SKILL_NAMES if name != "tdd"
    )

    result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(primary.name),
    )

    assert result.returncode == 0, result.stderr
    assert existing_grilling.read_bytes() == grilling_before
    assert not (project_skills / "tdd").exists()
    runtime_skills = harness_root / ".agents" / "skills"
    for name in missing_names:
        assert (runtime_skills / name / "SKILL.md").is_file()
    assert not (runtime_skills / "tdd").exists()
    assert not fake_codex.log_file.exists()
    assert tree_contents(user_home) == user_before
