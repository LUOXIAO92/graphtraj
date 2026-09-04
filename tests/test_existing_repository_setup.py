from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from conftest import InstalledCommands, run_process


def run_setup(
    installed_commands: InstalledCommands,
    repository: Path,
    answers: str = "y\n",
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(installed_commands.product), "setup"],
        cwd=repository,
        input=answers,
        check=False,
        text=True,
        capture_output=True,
    )


def git_output(repository: Path, *arguments: str) -> str:
    result = run_process(["git", *arguments], cwd=repository)
    result.check_returncode()
    return result.stdout.strip()


def test_setup_initializes_the_current_git_repository(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    repository = temporary_git_repository
    agents = repository / "AGENTS.md"
    context = repository / "CONTEXT.md"
    docs = repository / "docs"
    agents.write_text("# Existing guidance\n", encoding="utf-8")
    context.write_text("# Existing context\n", encoding="utf-8")
    docs.mkdir()
    (docs / "decision.md").write_text("# Existing decision\n", encoding="utf-8")
    documents_before = {
        agents: agents.read_bytes(),
        context: context.read_bytes(),
        docs / "decision.md": (docs / "decision.md").read_bytes(),
    }

    result = run_setup(installed_commands, repository)

    assert result.returncode == 0, result.stderr
    assert "Primary Worktree directory" not in result.stdout
    config_path = repository / ".graphtraj" / "config.yml"
    assert yaml.safe_load(config_path.read_text(encoding="utf-8")) == {
        "version": 1,
        "paths": {
            "project_root": ".",
            "docs": "docs",
            "agent_worktrees": ".graphtraj/.agent-worktrees",
            "state": ".graphtraj/state",
        },
        "agent_runner": {"dispatch_depth": 2, "max_concurrency": 18},
    }
    integration = repository / ".graphtraj" / ".agent-worktrees" / "dev"
    assert integration.is_dir()
    assert git_output(integration, "branch", "--show-current") == "dev"
    assert git_output(integration, "rev-parse", "HEAD") == git_output(
        repository, "rev-parse", "dev"
    )
    assert {path: path.read_bytes() for path in documents_before} == documents_before
    assert not (repository / ".codex" / "agent-runner" / "config.yml").exists()


def test_setup_preserves_a_valid_operator_configuration(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    repository = temporary_git_repository
    config_path = repository / ".graphtraj" / "config.yml"
    config_path.parent.mkdir()
    configuration = {
        "version": 1,
        "paths": {
            "project_root": ".",
            "docs": "docs",
            "agent_worktrees": ".graphtraj/operator-worktrees",
            "state": ".graphtraj/operator-state",
        },
        "agent_runner": {"dispatch_depth": 1, "max_concurrency": 3},
    }
    config_path.write_text(yaml.safe_dump(configuration, sort_keys=False), encoding="utf-8")
    configuration_before = config_path.read_bytes()

    first = run_setup(installed_commands, repository)
    second = run_setup(installed_commands, repository, answers="")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert config_path.read_bytes() == configuration_before
    integration = repository / ".graphtraj" / "operator-worktrees" / "dev"
    assert integration.is_dir()
    assert git_output(integration, "branch", "--show-current") == "dev"
    assert (repository / ".graphtraj" / "operator-state").is_dir()


def test_setup_preflight_failure_leaves_the_project_unchanged(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    repository = temporary_git_repository
    config_path = repository / ".graphtraj" / "config.yml"
    config_path.parent.mkdir()
    config_path.write_text("version: unsupported\n", encoding="utf-8")
    documents_before = {
        config_path: config_path.read_bytes(),
        repository / "README.md": (repository / "README.md").read_bytes(),
    }
    worktrees_before = git_output(repository, "worktree", "list", "--porcelain")

    result = run_setup(installed_commands, repository, answers="")

    assert result.returncode == 1
    assert "GraphTraj Config is invalid." in result.stderr
    assert {path: path.read_bytes() for path in documents_before} == documents_before
    assert not (repository / ".graphtraj" / ".agent-worktrees").exists()
    assert not (repository / ".graphtraj" / "state").exists()
    assert git_output(repository, "worktree", "list", "--porcelain") == worktrees_before


def test_runner_status_discovers_the_graphtraj_configuration(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    repository = temporary_git_repository
    setup = run_setup(installed_commands, repository)

    status = run_process(
        [str(installed_commands.runner), "status", "missing@j1"],
        cwd=repository,
    )

    assert setup.returncode == 0, setup.stderr
    assert status.returncode == 1
    assert "code: alias-not-found" in status.stdout
    assert "Harness Runner Config" not in status.stderr
