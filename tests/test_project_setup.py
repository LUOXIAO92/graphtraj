from __future__ import annotations

import os
import subprocess
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
    runner_config = common_git_directory(primary) / "agent-runner" / "config.yml"
    runner_config.parent.mkdir(parents=True)
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
        answers="{0}\nproject-local\n".format(primary.name),
    )

    assert result.returncode == 1
    assert "Setup preflight found conflicts" in result.stderr
    assert ".codex" in result.stderr
    assert ".agents/skills/domain-modeling" in result.stderr
    assert not (harness_root / "state").exists()
    assert not (
        common_git_directory(primary) / "agent-runner" / "config.yml"
    ).exists()
    assert git_output(primary, "worktree", "list", "--porcelain") == worktrees_before
    assert git_output(primary, "status", "--porcelain") == ""
    assert worktree_contents(primary) == primary_before
    assert tree_contents(integration) == integration_before
    assert tree_contents(neighbor) == neighbor_before
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

    partial_skill = integration / ".agents" / "skills" / "domain-modeling"
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
        answers="{0}\nproject-local\n".format(primary.name),
    )

    assert result.returncode == 0, result.stderr
    assert "ALREADY CONFIGURED: Project-local Skill domain-modeling" in result.stdout
    assert "CREATE: Project-local Skill domain-modeling" in result.stdout
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

    runner_config = common_git_directory(primary) / "agent-runner" / "config.yml"
    exclude_file = common_git_directory(primary) / "info" / "exclude"
    watched_files = tuple(
        path for path in (integration / ".codex").rglob("*") if path.is_file()
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
        "Codex Runtime resource",
        "Integration scratch link",
        "Project Runner Config",
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
    assert set(git_output(integration, "status", "--porcelain").splitlines()) == {
        "?? .codex/"
    }

    installed_resource_files = {
        str(path.relative_to(integration)): path.read_bytes()
        for path in (integration / ".codex").rglob("*")
        if path.is_file()
    }
    assert set(installed_resource_files) == {
        ".codex/config.toml",
        ".codex/agents/delivery-state.toml",
        ".codex/agents/engineer-expert.toml",
        ".codex/agents/engineer-junior.toml",
        ".codex/agents/engineer-senior.toml",
        ".codex/agents/merge-resolver.toml",
        ".codex/hooks/worktree_guard.py",
    }
    assert not (integration / ".codex" / "skills").exists()

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
    runner_config = common_directory.resolve() / "agent-runner" / "config.yml"
    assert yaml.safe_load(runner_config.read_text(encoding="utf-8")) == {
        "version": 1,
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
                },
            }
        },
    }

    assert git_output(primary, "rev-parse", "HEAD") == primary_head
    assert git_output(primary, "branch", "--show-current") == primary_branch == "main"
    assert git_output(primary, "status", "--porcelain") == primary_status == ""
    assert worktree_contents(primary) == primary_files
    assert tree_contents(user_home) == user_before
    assert tree_contents(neighbor) == neighbor_before
    assert not (neighbor / ".agent-worktrees").exists()
    assert not fake_codex.log_file.exists()
    assert "Review and commit" in result.stdout
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
    assert set(git_output(integration, "status", "--porcelain").splitlines()) == {
        "?? .codex/",
    }
    assert not (integration / ".agents").exists()
    assert tree_contents(user_home) == user_before
    assert worktree_contents(primary) == primary_files
    assert git_output(primary, "status", "--porcelain") == primary_status == ""
    assert (integration / ".scratch").resolve() == state.resolve()
    assert not (worktree_root / primary.name).exists()
    assert not (state / primary.name).exists()
    assert not fake_codex.log_file.exists()

    common_directory = Path(git_output(primary, "rev-parse", "--git-common-dir"))
    if not common_directory.is_absolute():
        common_directory = primary / common_directory
    assert (common_directory.resolve() / "agent-runner" / "config.yml").is_file()


def test_setup_stops_before_any_mutation_for_independent_skill_installation(
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
        answers="{0}\nindependent\n".format(primary.name),
    )

    assert result.returncode == 1
    assert "Missing required core Skills:" in result.stdout
    assert "project-local" in result.stdout
    assert "independent" in result.stdout
    assert "Setup stopped before any setup mutation." in result.stderr
    for name in CORE_SKILL_NAMES:
        assert name in "{0}{1}".format(result.stdout, result.stderr)

    assert not (harness_root / ".agent-worktrees").exists()
    assert not (harness_root / "state").exists()
    assert not (
        common_directory.resolve() / "agent-runner" / "config.yml"
    ).exists()
    assert git_output(primary, "rev-parse", "HEAD") == primary_head
    assert git_output(primary, "branch", "--show-current") == "main"
    assert git_output(primary, "status", "--porcelain") == ""
    assert worktree_contents(primary) == primary_files
    assert tree_contents(user_home) == user_before


def test_setup_installs_only_missing_supported_skills_project_locally(
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
        name for name in CORE_SKILL_NAMES if name not in {"grilling", "tdd"}
    )

    result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\nproject-local\n".format(primary.name),
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "Missing required core Skills: {0}".format(
        ", ".join(missing_names)
    ) in result.stdout
    assert "Core Skills: OK" in result.stdout
    assert existing_grilling.read_bytes() == grilling_before
    assert not (project_skills / "tdd").exists()
    assert {
        path.name for path in project_skills.iterdir()
    } == set(CORE_SKILL_NAMES) - {"tdd"}
    for name in missing_names:
        assert tree_contents(project_skills / name) == supported_skill_contents(name)
    assert not fake_codex.log_file.exists()
    assert tree_contents(user_home) == user_before


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
        answers="{0}\nindependent\n".format(primary.name),
    )

    assert stopped.returncode == 1
    assert not (harness_root / ".agent-worktrees").exists()
    assert not (harness_root / "state").exists()

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
