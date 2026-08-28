from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

import yaml

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
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(installed_commands.product), "setup"],
        cwd=harness_root,
        env=setup_environment(user_home, fake_codex),
        input=answers,
        check=False,
        text=True,
        capture_output=True,
    )


def git_output(repository: Path, *arguments: str) -> str:
    result = run_process(["git", *arguments], cwd=repository)
    result.check_returncode()
    return result.stdout.strip()


def common_git_directory(repository: Path) -> Path:
    common = Path(git_output(repository, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = repository / common
    return common.resolve()


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

    neighbor = harness_root / "neighbor-project"
    neighbor.mkdir()
    (neighbor / "marker.txt").write_text("leave me alone\n", encoding="utf-8")
    neighbor_before = tree_contents(neighbor)
    primary_head = git_output(primary, "rev-parse", "HEAD")
    dev_head = git_output(primary, "rev-parse", "dev")
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
    assert git_output(primary, "rev-parse", "HEAD") == primary_head
    assert git_output(primary, "rev-parse", "dev") == dev_head
    assert git_output(primary, "branch", "--show-current") == "main"
    assert git_output(primary, "status", "--porcelain") == ""
    assert worktree_contents(primary) == primary_files
    assert runner_config.read_bytes() == runner_before
    assert tree_contents(user_home) == user_before
    assert tree_contents(neighbor) == neighbor_before
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
    user_before = tree_contents(user_home)
    neighbor = harness_root / "neighbor-project"
    neighbor.mkdir()
    (neighbor / "marker.txt").write_text("leave me alone\n", encoding="utf-8")
    neighbor_before = tree_contents(neighbor)
    primary_before = worktree_contents(primary)
    foreign_before = tree_contents(foreign_dev)
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
    assert git_output(primary, "branch", "--show-current") == "main"
    assert git_output(primary, "status", "--porcelain") == ""
    assert worktree_contents(primary) == primary_before
    assert tree_contents(foreign_dev) == foreign_before
    assert tree_contents(user_home) == user_before
    assert tree_contents(neighbor) == neighbor_before
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
    user_before = tree_contents(user_home)
    harness_entries_before = tuple(
        sorted(path.name for path in harness_root.iterdir())
    )
    primary_head = git_output(primary, "rev-parse", "HEAD")
    dev_head = git_output(primary, "rev-parse", "dev")
    primary_status = git_output(primary, "status", "--porcelain")
    primary_files = worktree_contents(primary)
    worktrees_before = git_output(primary, "worktree", "list", "--porcelain")
    assert "worktree {0}".format(integration) in worktrees_before
    assert "branch refs/heads/dev" in worktrees_before
    assert "prunable" in worktrees_before

    result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(primary.name),
    )

    expected_error = (
        "The dev Integration Worktree is registered at {0}, but that directory "
        "is missing; this is a stale or prunable Git Worktree registration. "
        "Setup made no changes. Inspect `git worktree list --porcelain`, then "
        "manually restore the directory at {0} or remove the exact stale "
        "registration for {0} before rerunning setup."
    ).format(integration)
    assert result.returncode == 1
    assert "Missing required core Skills: task-delivery" in result.stdout
    assert "Install the missing Skills into this Harness Project?" in result.stdout
    assert expected_error in result.stderr
    assert git_output(primary, "worktree", "list", "--porcelain") == (
        worktrees_before
    )
    assert git_output(primary, "rev-parse", "HEAD") == primary_head
    assert git_output(primary, "rev-parse", "dev") == dev_head
    assert git_output(primary, "branch", "--show-current") == "main"
    assert git_output(primary, "status", "--porcelain") == primary_status == ""
    assert worktree_contents(primary) == primary_files
    assert tuple(sorted(path.name for path in harness_root.iterdir())) == (
        harness_entries_before
    )
    assert worktree_root.is_dir()
    assert tuple(worktree_root.iterdir()) == ()
    assert not integration.exists()
    assert not runtime_store.exists()
    assert not state.exists()
    assert tree_contents(user_home) == user_before
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
    neighbor_before = tree_contents(neighbor)
    primary_before = worktree_contents(primary)
    integration_before = tree_contents(integration)
    worktrees_before = git_output(primary, "worktree", "list", "--porcelain")

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
    assert git_output(primary, "worktree", "list", "--porcelain") == worktrees_before
    assert git_output(primary, "status", "--porcelain") == ""
    assert worktree_contents(primary) == primary_before
    assert tree_contents(integration) == integration_before
    assert tree_contents(neighbor) == neighbor_before
    assert (integration / ".codex").is_symlink()
    assert (integration / ".codex").resolve() == runtime_redirect.resolve()
    assert (skill_root / "domain-modeling").is_symlink()
    assert (skill_root / "domain-modeling").resolve() == skill_redirect.resolve()
    assert (runtime_store / "config.toml").is_symlink()
    assert (root_skill_directory / "domain-modeling").is_symlink()
    assert not fake_codex.log_file.exists()


def test_setup_recovers_a_byte_identical_partial_supported_skill_copy(
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

    partial_skill = harness_root / ".agents" / "skills" / "domain-modeling"
    partial_skill.mkdir(parents=True)
    supported = supported_skill_contents("domain-modeling")
    partial_file = partial_skill / "ADR-FORMAT.md"
    partial_file.write_bytes(supported["ADR-FORMAT.md"])
    partial_mtime = partial_file.stat().st_mtime_ns

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

    assert result.returncode == 0, result.stderr
    assert "ALREADY CONFIGURED: Harness Skill domain-modeling" in result.stdout
    assert "CREATE: Harness Skill domain-modeling" in result.stdout
    assert tree_contents(partial_skill) == supported
    assert partial_file.stat().st_mtime_ns == partial_mtime
    assert not fake_codex.log_file.exists()


def test_setup_rerun_reports_an_already_configured_plan_without_rewriting(
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
    runner_config = runtime_store / "agent-runner" / "config.yml"
    exclude_file = common_git_directory(primary) / "info" / "exclude"
    watched_files = tuple(
        path for path in runtime_store.rglob("*") if path.is_file()
    ) + (runner_config, exclude_file)
    before_bytes = {path: path.read_bytes() for path in watched_files}
    before_mtimes = {path: path.stat().st_mtime_ns for path in watched_files}
    scratch_before = (integration / ".scratch").lstat().st_mtime_ns
    worktrees_before = git_output(primary, "worktree", "list", "--porcelain")
    integration_status = git_output(integration, "status", "--porcelain")

    second = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\n".format(primary.name),
    )

    assert second.returncode == 0, second.stderr
    for planned_target in (
        "Worktree Directory",
        "Harness State Directory",
        "Integration Worktree on dev",
        "Harness Runtime resource",
        "Integration scratch link",
        "Harness Runner Config",
        "Ignore Integration .scratch",
    ):
        assert "ALREADY CONFIGURED: {0}".format(planned_target) in second.stdout
    assert {path: path.read_bytes() for path in watched_files} == before_bytes
    assert {path: path.stat().st_mtime_ns for path in watched_files} == before_mtimes
    assert (integration / ".scratch").lstat().st_mtime_ns == scratch_before
    assert git_output(primary, "worktree", "list", "--porcelain") == worktrees_before
    assert git_output(integration, "status", "--porcelain") == integration_status
    assert git_output(primary, "branch", "--show-current") == "main"
    assert git_output(primary, "status", "--porcelain") == ""
    assert not fake_codex.log_file.exists()


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
    user_before = tree_contents(user_home)
    primary_head = git_output(primary, "rev-parse", "HEAD")
    primary_before = worktree_contents(primary)
    worktrees_before = git_output(primary, "worktree", "list", "--porcelain")

    neighbor = harness_root / "neighbor-project"
    neighbor.mkdir()
    (neighbor / "marker.txt").write_text("leave me alone\n", encoding="utf-8")
    neighbor_before = tree_contents(neighbor)

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
    assert "Completed actions were not rolled back" in failed.stderr
    completed = failed.stderr.split("Completed actions:\n", maxsplit=1)[1].split(
        "\nIncomplete actions:\n",
        maxsplit=1,
    )[0]
    incomplete = failed.stderr.split("\nIncomplete actions:\n", maxsplit=1)[1]
    assert "Worktree Directory: {0}".format(
        harness_root / ".agent-worktrees"
    ) in completed
    assert "Harness State Directory: {0}".format(
        harness_root / "state"
    ) in completed
    assert "Create dev branch from {0}".format(primary_head) in completed
    assert "Integration Worktree on dev: {0}".format(
        harness_root / ".agent-worktrees" / "integration"
    ) in incomplete
    assert "Harness Runtime resource:" in incomplete
    assert "Integration scratch link:" in incomplete
    assert "Ignore Integration .scratch" in incomplete
    assert "Harness Runner Config:" in incomplete
    assert "Correct the cause and rerun setup" in failed.stderr
    assert (harness_root / ".agent-worktrees").is_dir()
    assert (harness_root / "state").is_dir()
    assert not (harness_root / ".agent-worktrees" / "integration").exists()
    assert git_output(primary, "worktree", "list", "--porcelain") == worktrees_before
    assert run_process(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/dev"],
        cwd=primary,
    ).returncode == 0
    assert git_output(primary, "rev-parse", "dev") == primary_head
    assert not (harness_root / ".codex" / "agent-runner" / "config.yml").exists()
    assert git_output(primary, "rev-parse", "HEAD") == primary_head
    assert git_output(primary, "branch", "--show-current") == "main"
    assert git_output(primary, "status", "--porcelain") == ""
    assert worktree_contents(primary) == primary_before
    assert tree_contents(user_home) == user_before
    assert tree_contents(neighbor) == neighbor_before
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
    assert git_output(primary, "branch", "--show-current") == "main"
    assert git_output(primary, "status", "--porcelain") == ""
    assert worktree_contents(primary) == primary_before
    assert tree_contents(user_home) == user_before
    assert tree_contents(neighbor) == neighbor_before
    assert not fake_codex.log_file.exists()


def test_setup_reports_each_completed_and_incomplete_skill_file(
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

    skill = harness_root / ".agents" / "skills" / "domain-modeling"
    blocked_directory = skill / "agents"
    blocked_directory.mkdir(parents=True)
    blocked_directory.chmod(0o555)

    user_home = tmp_path / "operator-home"
    install_skills(
        user_home / ".agents" / "skills",
        tuple(name for name in CORE_SKILL_NAMES if name != "domain-modeling"),
    )
    user_before = tree_contents(user_home)
    primary_before = worktree_contents(primary)

    failed = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(primary.name),
    )
    blocked_directory.chmod(0o755)

    assert failed.returncode == 1
    assert "Setup execution stopped" in failed.stderr
    completed = failed.stderr.split("Completed actions:\n", maxsplit=1)[1].split(
        "\nIncomplete actions:\n",
        maxsplit=1,
    )[0]
    incomplete = failed.stderr.split("\nIncomplete actions:\n", maxsplit=1)[1]
    for relative_path in ("ADR-FORMAT.md", "CONTEXT-FORMAT.md"):
        action = "Harness Skill domain-modeling: {0}".format(
            skill / relative_path
        )
        assert "- {0}".format(action) in completed
        assert "- {0}".format(action) not in incomplete
    for relative_path in ("agents/openai.yaml", "SKILL.md"):
        action = "Harness Skill domain-modeling: {0}".format(
            skill / relative_path
        )
        assert "- {0}".format(action) in incomplete
        assert "- {0}".format(action) not in completed
    assert "Harness Runtime resource:" in incomplete
    assert "Integration scratch link:" in incomplete
    assert "Ignore Integration .scratch" in incomplete
    assert "Harness Runner Config:" in incomplete
    assert git_output(primary, "branch", "--show-current") == "main"
    assert git_output(primary, "status", "--porcelain") == ""
    assert worktree_contents(primary) == primary_before
    assert tree_contents(user_home) == user_before
    assert not fake_codex.log_file.exists()

    rerun = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(primary.name),
    )

    assert rerun.returncode == 0, rerun.stderr
    assert tree_contents(skill) == supported_skill_contents("domain-modeling")
    assert git_output(primary, "branch", "--show-current") == "main"
    assert git_output(primary, "status", "--porcelain") == ""
    assert worktree_contents(primary) == primary_before
    assert tree_contents(user_home) == user_before
    assert not fake_codex.log_file.exists()


def test_setup_reports_inner_codex_actions_before_registration_failure(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    primary = temporary_git_repository
    integration = harness_root / ".agent-worktrees" / "integration"
    state = harness_root / "state"
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    user_before = tree_contents(user_home)
    primary_head = git_output(primary, "rev-parse", "HEAD")
    primary_before = worktree_contents(primary)

    neighbor = harness_root / "neighbor-project"
    neighbor.mkdir()
    (neighbor / "marker.txt").write_text("leave me alone\n", encoding="utf-8")
    neighbor_before = tree_contents(neighbor)

    exclude_file = common_git_directory(primary) / "info" / "exclude"
    exclude_before = exclude_file.read_bytes()
    exclude_file.chmod(0o444)

    failed = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(primary.name),
    )
    exclude_file.chmod(0o644)

    assert failed.returncode == 1
    assert "Setup execution stopped" in failed.stderr
    completed = failed.stderr.split("Completed actions:\n", maxsplit=1)[1].split(
        "\nIncomplete actions:\n",
        maxsplit=1,
    )[0]
    incomplete = failed.stderr.split("\nIncomplete actions:\n", maxsplit=1)[1]
    assert "Worktree Directory:" in completed
    assert "Harness State Directory:" in completed
    assert "dev branch from {0}".format(primary_head) in completed
    assert "Integration Worktree on dev:" in completed
    for relative_path in (
        "config.toml",
        "agents/delivery-state.toml",
        "agents/engineer-expert.toml",
        "agents/engineer-junior.toml",
        "agents/engineer-senior.toml",
        "agents/merge-resolver.toml",
        "agents/spec-reviewer.toml",
        "agents/standards-reviewer.toml",
        "hooks/worktree_guard.py",
    ):
        action = "Harness Runtime resource: {0}".format(
            harness_root / ".codex" / relative_path
        )
        assert "- {0}".format(action) in completed
        assert "- {0}".format(action) not in incomplete
    assert "Integration scratch link: {0} -> {1}".format(
        integration / ".scratch",
        state,
    ) in completed
    assert "Ignore Integration .scratch in {0}".format(exclude_file) in incomplete
    assert "Harness Runner Config:" in incomplete
    assert exclude_file.read_bytes() == exclude_before
    assert not (harness_root / ".codex" / "agent-runner" / "config.yml").exists()
    assert git_output(primary, "branch", "--show-current") == "main"
    assert git_output(primary, "status", "--porcelain") == ""
    assert worktree_contents(primary) == primary_before
    assert tree_contents(user_home) == user_before
    assert tree_contents(neighbor) == neighbor_before
    assert not fake_codex.log_file.exists()

    rerun = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\n".format(primary.name),
    )

    assert rerun.returncode == 0, rerun.stderr
    assert git_output(integration, "branch", "--show-current") == "dev"
    assert (integration / ".scratch").resolve() == state.resolve()
    assert (harness_root / ".codex" / "agent-runner" / "config.yml").is_file()
    assert git_output(primary, "branch", "--show-current") == "main"
    assert git_output(primary, "status", "--porcelain") == ""
    assert worktree_contents(primary) == primary_before
    assert tree_contents(user_home) == user_before
    assert tree_contents(neighbor) == neighbor_before
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
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    (user_home / ".codex").mkdir()
    (user_home / ".codex" / "config.toml").write_text(
        "operator_setting = true\n", encoding="utf-8"
    )
    (user_home / ".codex" / "credentials.json").write_text(
        '{"token": "unchanged"}\n', encoding="utf-8"
    )
    (user_home / ".codex" / "trust.txt").write_text(
        "operator-controlled\n", encoding="utf-8"
    )
    user_before = tree_contents(user_home)
    primary_head = git_output(primary, "rev-parse", "HEAD")
    primary_branch = git_output(primary, "branch", "--show-current")
    primary_status = git_output(primary, "status", "--porcelain")
    primary_files = worktree_contents(primary)

    neighbor = harness_root / "neighbor-project"
    neighbor.mkdir()
    (neighbor / "marker.txt").write_text("leave me alone\n", encoding="utf-8")
    neighbor_before = tree_contents(neighbor)

    result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(primary.name),
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "Proposed dev base: {0}".format(primary_head) in result.stdout
    assert "Create dev from {0}?".format(primary_head) in result.stdout
    assert integration.is_dir()
    assert state.is_dir()
    assert not (worktree_root / primary.name).exists()
    assert not (state / primary.name).exists()

    assert git_output(integration, "branch", "--show-current") == "dev"
    assert git_output(integration, "rev-parse", "HEAD") == primary_head
    assert git_output(integration, "log", "-1", "--format=%s") == (
        "Initial target project"
    )
    assert git_output(integration, "status", "--porcelain") == ""

    runtime_store = harness_root / ".codex"
    installed_resource_files = {
        str(path.relative_to(runtime_store)): path.read_bytes()
        for path in runtime_store.rglob("*")
        if path.is_file()
    }
    assert set(installed_resource_files) == {
        "config.toml",
        "agents/delivery-state.toml",
        "agents/engineer-expert.toml",
        "agents/engineer-junior.toml",
        "agents/engineer-senior.toml",
        "agents/merge-resolver.toml",
        "agents/spec-reviewer.toml",
        "agents/standards-reviewer.toml",
        "hooks/worktree_guard.py",
        "agent-runner/config.yml",
    }
    assert not (integration / ".codex").exists()
    assert not (integration / ".agents").exists()

    scratch = integration / ".scratch"
    assert scratch.is_symlink()
    assert scratch.resolve() == state.resolve()
    ignored = run_process(
        ["git", "check-ignore", "--quiet", ".scratch"], cwd=integration
    )
    assert ignored.returncode == 0

    common_directory = Path(git_output(primary, "rev-parse", "--git-common-dir"))
    if not common_directory.is_absolute():
        common_directory = primary / common_directory
    runner_config = runtime_store / "agent-runner" / "config.yml"
    assert yaml.safe_load(runner_config.read_text(encoding="utf-8")) == {
        "version": 1,
        "harness_root": str(harness_root.resolve()),
        "repository": str(primary.resolve()),
        "common_directory": str(common_directory.resolve()),
        "default_runtime": "codex",
        "worktree_root": str(worktree_root.resolve()),
        "integration_branch": "dev",
        "runtimes": {
            "codex": {
                "executable": str(fake_codex.executable.resolve()),
                "roles": {
                    "engineer-junior": "engineer-junior",
                    "engineer-senior": "engineer-senior",
                    "engineer-expert": "engineer-expert",
                    "standards-reviewer": "standards-reviewer",
                    "spec-reviewer": "spec-reviewer",
                },
            }
        },
        "repository_skill_allowlist": [],
    }

    assert git_output(primary, "rev-parse", "HEAD") == primary_head
    assert git_output(primary, "branch", "--show-current") == primary_branch == "main"
    assert git_output(primary, "status", "--porcelain") == primary_status == ""
    assert worktree_contents(primary) == primary_files
    assert tree_contents(user_home) == user_before
    assert tree_contents(neighbor) == neighbor_before
    assert not (neighbor / ".agent-worktrees").exists()
    assert not fake_codex.log_file.exists()
    assert "Harness Runtime Store installed at {0}.".format(runtime_store) in result.stdout
    assert "setup-matt-pocock-skills" in result.stdout


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
    run_process(["git", "branch", "dev"], cwd=primary).check_returncode()

    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    user_before = tree_contents(user_home)
    dev_head = git_output(primary, "rev-parse", "dev")
    worktree_listing = git_output(primary, "worktree", "list", "--porcelain")
    primary_status = git_output(primary, "status", "--porcelain")
    primary_files = worktree_contents(primary)

    result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\n".format(primary.name),
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "Registered Integration Worktree on existing dev." in result.stdout
    assert "Proposed dev base:" not in result.stdout
    assert "Create dev from" not in result.stdout
    assert state.is_dir()
    assert integration.is_dir()
    assert git_output(integration, "branch", "--show-current") == "dev"
    assert git_output(integration, "rev-parse", "HEAD") == dev_head
    registered_worktrees = git_output(primary, "worktree", "list", "--porcelain")
    assert registered_worktrees != worktree_listing
    assert "worktree {0}".format(integration) in registered_worktrees
    assert "branch refs/heads/dev" in registered_worktrees
    assert git_output(integration, "status", "--porcelain") == ""
    assert not (integration / ".codex").exists()
    assert not (integration / ".agents").exists()
    assert tree_contents(user_home) == user_before
    assert worktree_contents(primary) == primary_files
    assert git_output(primary, "status", "--porcelain") == primary_status == ""
    assert (integration / ".scratch").resolve() == state.resolve()
    assert not (worktree_root / primary.name).exists()
    assert not (state / primary.name).exists()
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
    primary_head = git_output(primary, "rev-parse", "HEAD")
    primary_files = worktree_contents(primary)
    common_directory = Path(git_output(primary, "rev-parse", "--git-common-dir"))
    if not common_directory.is_absolute():
        common_directory = primary / common_directory

    result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\nn\n".format(primary.name),
    )

    assert result.returncode == 1
    assert "Missing required core Skills:" in result.stdout
    assert "Install the missing Skills into this Harness Project?" in result.stdout
    assert "Setup stopped before any setup mutation." in result.stderr
    for name in CORE_SKILL_NAMES:
        assert name in "{0}{1}".format(result.stdout, result.stderr)

    assert not (harness_root / ".agent-worktrees").exists()
    assert not (harness_root / "state").exists()
    assert not (harness_root / ".codex").exists()
    assert not (
        common_directory.resolve() / "agent-runner" / "config.yml"
    ).exists()
    assert git_output(primary, "rev-parse", "HEAD") == primary_head
    assert git_output(primary, "branch", "--show-current") == "main"
    assert git_output(primary, "status", "--porcelain") == ""
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
    assert result.stderr == ""
    assert "Missing required core Skills: {0}".format(
        ", ".join(missing_names)
    ) in result.stdout
    assert "Core Skills: OK" in result.stdout
    assert existing_grilling.read_bytes() == grilling_before
    assert not (project_skills / "tdd").exists()
    assert {path.name for path in project_skills.iterdir()} == {"grilling"}
    runtime_skills = harness_root / ".agents" / "skills"
    assert not (harness_root / ".codex" / "skills").exists()
    for name in missing_names:
        assert tree_contents(runtime_skills / name) == supported_skill_contents(name)
    assert not (runtime_skills / "tdd").exists()
    assert not fake_codex.log_file.exists()
    assert tree_contents(user_home) == user_before

    installed_skill_files = tuple(
        path
        for name in missing_names
        for path in (runtime_skills / name).rglob("*")
        if path.is_file()
    )
    skill_mtimes = {
        path: path.stat().st_mtime_ns for path in installed_skill_files
    }
    skill_bytes = {path: path.read_bytes() for path in installed_skill_files}

    rerun = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\n".format(primary.name),
    )

    assert rerun.returncode == 0, rerun.stderr
    assert "Core Skills: OK" in rerun.stdout
    assert "Install the missing Skills" not in rerun.stdout
    assert {path: path.read_bytes() for path in installed_skill_files} == skill_bytes
    assert {
        path: path.stat().st_mtime_ns for path in installed_skill_files
    } == skill_mtimes
    assert existing_grilling.read_bytes() == grilling_before
    assert not (project_skills / "tdd").exists()
    assert tree_contents(user_home) == user_before
    assert not fake_codex.log_file.exists()


def test_setup_succeeds_when_rerun_after_user_scope_skill_installation(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    primary = temporary_git_repository
    integration = harness_root / ".agent-worktrees" / "integration"
    user_home = tmp_path / "operator-home"
    user_home.mkdir()

    stopped = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\nn\n".format(primary.name),
    )

    assert stopped.returncode == 1
    assert not (harness_root / ".agent-worktrees").exists()
    assert not (harness_root / "state").exists()
    assert not (harness_root / ".codex").exists()

    install_user_skills(user_home)

    rerun = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(primary.name),
    )

    assert rerun.returncode == 0, rerun.stderr
    assert rerun.stderr == ""
    assert "Core Skills: OK" in rerun.stdout
    assert integration.is_dir()
    assert git_output(integration, "branch", "--show-current") == "dev"
    assert not (integration / ".agents").exists()
    assert not fake_codex.log_file.exists()
