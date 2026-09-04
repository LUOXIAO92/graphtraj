from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from conftest import InstalledCommands, run_process


def run_setup(
    installed_commands: InstalledCommands,
    repository: Path,
    answers: str = "y\ny\n",
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


def create_git_repository(path: Path) -> Path:
    path.mkdir()
    run_process(["git", "init", "--initial-branch=main"], cwd=path).check_returncode()
    run_process(["git", "config", "user.name", "GraphTraj Test"], cwd=path).check_returncode()
    run_process(
        ["git", "config", "user.email", "graphtraj@example.invalid"], cwd=path
    ).check_returncode()
    (path / "README.md").write_text("# Source\n", encoding="utf-8")
    run_process(["git", "add", "README.md"], cwd=path).check_returncode()
    run_process(["git", "commit", "-m", "Initial source"], cwd=path).check_returncode()
    return path


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


def test_setup_selects_the_only_git_child_and_preserves_root_documents(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    agents = harness_root / "AGENTS.md"
    context = harness_root / "CONTEXT.md"
    docs = harness_root / "docs"
    agents.write_text("# Harness guidance\n", encoding="utf-8")
    context.write_text("# Harness context\n", encoding="utf-8")
    docs.mkdir()
    decision = docs / "decision.md"
    decision.write_text("# Harness decision\n", encoding="utf-8")
    documents_before = {
        agents: agents.read_bytes(),
        context: context.read_bytes(),
        decision: decision.read_bytes(),
    }

    first = run_setup(installed_commands, harness_root)
    config_path = harness_root / ".graphtraj" / "config.yml"
    config_before = config_path.read_bytes()
    second = run_setup(installed_commands, harness_root, answers="")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    config = yaml.safe_load(config_before)
    assert config["paths"]["project_root"] == temporary_git_repository.name
    assert config["paths"]["docs"] == "docs"
    assert config_path.read_bytes() == config_before
    integration = harness_root / ".graphtraj" / ".agent-worktrees" / "dev"
    assert git_output(integration, "rev-parse", "--show-toplevel") == str(
        integration.resolve()
    )
    assert {path: path.read_bytes() for path in documents_before} == documents_before


def test_setup_prompts_to_select_one_of_multiple_git_children(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    selected = create_git_repository(harness_root / "selected-source")

    result = run_setup(installed_commands, harness_root, answers="selected-source\ny\ny\n")

    assert result.returncode == 0, result.stderr
    config = yaml.safe_load(
        (harness_root / ".graphtraj" / "config.yml").read_text(encoding="utf-8")
    )
    assert config["paths"]["project_root"] == selected.name
    integration = harness_root / ".graphtraj" / ".agent-worktrees" / "dev"
    assert git_output(integration, "rev-parse", "--show-toplevel") == str(
        integration.resolve()
    )


def test_setup_prompts_for_an_explicit_source_when_no_git_child_exists(
    installed_commands: InstalledCommands,
    tmp_path: Path,
) -> None:
    harness_root = tmp_path / "harness-project"
    harness_root.mkdir()
    source = create_git_repository(tmp_path / "external-source")

    result = run_setup(installed_commands, harness_root, answers="{0}\ny\ny\n".format(source))

    assert result.returncode == 0, result.stderr
    config = yaml.safe_load(
        (harness_root / ".graphtraj" / "config.yml").read_text(encoding="utf-8")
    )
    assert config["paths"]["project_root"] == str(source)
    integration = harness_root / ".graphtraj" / ".agent-worktrees" / "dev"
    assert git_output(integration, "rev-parse", "--show-toplevel") == str(
        integration.resolve()
    )


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


def test_setup_uses_the_configured_document_directory_for_child_worktrees(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    documents = harness_root / "project-documents"
    documents.mkdir()
    (documents / "decision.md").write_text("# Decision\n", encoding="utf-8")
    (harness_root / "CONTEXT.md").write_text("# Context\n", encoding="utf-8")
    config_path = harness_root / ".graphtraj" / "config.yml"
    config_path.parent.mkdir()
    config_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "paths": {
                    "project_root": temporary_git_repository.name,
                    "docs": "project-documents",
                    "agent_worktrees": ".graphtraj/.agent-worktrees",
                    "state": ".graphtraj/state",
                },
                "agent_runner": {"dispatch_depth": 2, "max_concurrency": 18},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = run_setup(installed_commands, harness_root, answers="y\ny\n")

    integration = harness_root / ".graphtraj" / ".agent-worktrees" / "dev"
    assert result.returncode == 0, result.stderr
    assert (integration / "docs").resolve() == documents.resolve()
    assert (integration / "docs" / "decision.md").read_text(encoding="utf-8") == (
        "# Decision\n"
    )


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
