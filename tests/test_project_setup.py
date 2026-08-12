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
