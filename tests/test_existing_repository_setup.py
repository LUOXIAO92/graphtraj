from __future__ import annotations

from conftest import runner_command, runner_operation
import subprocess
from pathlib import Path

import pytest
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
        "agent_runner": {"max_concurrency": 18},
    }
    integration = repository / ".graphtraj" / ".agent-worktrees" / "dev"
    assert integration.is_dir()
    assert git_output(integration, "branch", "--show-current") == "dev"
    assert git_output(integration, "rev-parse", "HEAD") == git_output(
        repository, "rev-parse", "dev"
    )
    assert (integration / "CONTEXT.md").is_symlink()
    assert (integration / "CONTEXT.md").resolve() == context.resolve()
    assert (integration / "docs").is_symlink()
    assert (integration / "docs").resolve() == docs.resolve()
    assert {path: path.read_bytes() for path in documents_before} == documents_before
    assert not (repository / ".graphtraj" / "runner" / "config.yml").exists()


def test_setup_writes_an_empty_role_selection(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    result = run_setup(installed_commands, temporary_git_repository)

    assert result.returncode == 0, result.stderr
    role_config = yaml.safe_load(
        (temporary_git_repository / ".graphtraj" / "roles.yml").read_text(
            encoding="utf-8"
        )
    )
    # Setup selects no role; the operator declares the roles this project uses.
    assert role_config == {"roles": {}}
    assert not (temporary_git_repository / ".codex" / "agents").exists()


def test_setup_preserves_the_operator_role_selection(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    roles_path = temporary_git_repository / ".graphtraj" / "roles.yml"
    roles_path.parent.mkdir()
    roles_path.write_text(
        "roles:\n"
        "  researcher:\n"
        "    runtime: codex\n"
        "    model: operator-selected-model\n"
        "role_tree:\n"
        "  researcher: {}\n",
        encoding="utf-8",
    )
    selected = roles_path.read_bytes()

    first = run_setup(installed_commands, temporary_git_repository)
    second = run_setup(installed_commands, temporary_git_repository, answers="")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert roles_path.read_bytes() == selected


def test_setup_leaves_legacy_runtime_role_files_unmanaged(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    first = run_setup(installed_commands, temporary_git_repository)
    legacy_role = (
        temporary_git_repository / ".codex" / "agents" / "engineer-expert.toml"
    )
    # Setup creates .codex only for Codex contexts (8081888, Task 220).
    legacy_role.parent.mkdir(parents=True)
    legacy_role.write_text("legacy role projection\n", encoding="utf-8")
    before = legacy_role.read_bytes()

    second = run_setup(installed_commands, temporary_git_repository, answers="")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert legacy_role.read_bytes() == before


def test_setup_rejects_invalid_roles_before_project_mutation(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    roles_path = temporary_git_repository / ".graphtraj" / "roles.yml"
    roles_path.parent.mkdir()
    roles_path.write_text(
        "roles:\n"
        "  engineer:\n"
        "    runtime: codex\n"
        "    model: ''\n"
        "    command: codex\n",
        encoding="utf-8",
    )
    before = roles_path.read_bytes()
    worktrees_before = git_output(
        temporary_git_repository, "worktree", "list", "--porcelain"
    )

    result = run_setup(installed_commands, temporary_git_repository, answers="")

    assert result.returncode == 1
    assert "GraphTraj Roles is invalid." in result.stderr
    assert "engineer.model" in result.stderr
    assert "engineer.command" in result.stderr
    assert roles_path.read_bytes() == before
    assert not (temporary_git_repository / ".codex").exists()
    assert not (temporary_git_repository / ".graphtraj" / "state").exists()
    assert git_output(
        temporary_git_repository, "worktree", "list", "--porcelain"
    ) == worktrees_before


def test_setup_rejects_a_non_file_role_target_before_project_mutation(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    roles_path = temporary_git_repository / ".graphtraj" / "roles.yml"
    roles_path.mkdir(parents=True)
    worktrees_before = git_output(
        temporary_git_repository, "worktree", "list", "--porcelain"
    )

    result = run_setup(installed_commands, temporary_git_repository, answers="")

    assert result.returncode == 1
    assert "roles.yml must be a regular readable file" in result.stderr
    assert roles_path.is_dir()
    assert not (temporary_git_repository / ".codex").exists()
    assert git_output(
        temporary_git_repository, "worktree", "list", "--porcelain"
    ) == worktrees_before


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
    worktrees_before = git_output(source, "worktree", "list", "--porcelain")

    result = run_setup(installed_commands, harness_root, answers="{0}\ny\ny\n".format(source))

    assert result.returncode == 1
    assert "direct Git child" in result.stderr
    assert not (harness_root / ".graphtraj").exists()
    assert not (harness_root / ".codex").exists()
    assert git_output(source, "worktree", "list", "--porcelain") == worktrees_before


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


@pytest.mark.parametrize("path_name", ("project_root", "docs", "agent_worktrees", "state"))
@pytest.mark.parametrize("escape_kind", ("absolute", "parent"))
def test_setup_rejects_configured_paths_outside_the_harness_root(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    tmp_path: Path,
    path_name: str,
    escape_kind: str,
) -> None:
    repository = temporary_git_repository
    outside = tmp_path / "outside-harness"
    value = str(outside) if escape_kind == "absolute" else "../outside-harness"
    config_path = repository / ".graphtraj" / "config.yml"
    config_path.parent.mkdir()
    paths = {
        "project_root": ".",
        "docs": "docs",
        "agent_worktrees": ".graphtraj/.agent-worktrees",
        "state": ".graphtraj/state",
    }
    paths[path_name] = value
    config_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "paths": paths,
                "agent_runner": {"dispatch_depth": 2, "max_concurrency": 18},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    config_before = config_path.read_bytes()
    worktrees_before = git_output(repository, "worktree", "list", "--porcelain")

    result = run_setup(installed_commands, repository, answers="")

    assert result.returncode == 1
    assert "GraphTraj Config is invalid." in result.stderr
    assert config_path.read_bytes() == config_before
    assert not outside.exists()
    assert not (repository / ".codex").exists()
    assert git_output(repository, "worktree", "list", "--porcelain") == worktrees_before


def test_setup_and_runner_reject_a_nested_configured_source_repository(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Codex query reports invalid config without a recovery Skill binding."""
    harness_root = temporary_git_repository.parent
    nested_source = harness_root / "nested" / "source"
    nested_source.parent.mkdir()
    create_git_repository(nested_source)
    config_path = harness_root / ".graphtraj" / "config.yml"
    config_path.parent.mkdir()
    configuration = {
        "version": 1,
        "paths": {
            "project_root": "nested/source",
            "docs": "docs",
            "agent_worktrees": ".graphtraj/.agent-worktrees",
            "state": ".graphtraj/state",
        },
        "agent_runner": {"dispatch_depth": 2, "max_concurrency": 18},
    }
    config_path.write_text(yaml.safe_dump(configuration, sort_keys=False), encoding="utf-8")
    config_before = config_path.read_bytes()
    worktrees_before = git_output(nested_source, "worktree", "list", "--porcelain")

    setup = run_setup(installed_commands, harness_root, answers="")
    monkeypatch.setenv("CODEX_THREAD_ID", "query-without-recovery-skill")
    assert not (harness_root / ".agents/skills/retro/SKILL.md").exists()
    status = run_process(
        runner_operation(installed_commands, "status", "missing@e1"),
        cwd=harness_root,
    )

    assert setup.returncode == 1
    assert "GraphTraj Config is invalid." in setup.stderr
    assert status.returncode == 1
    assert "code: invalid-config" in status.stdout
    assert "GraphTraj Config is invalid." in status.stdout
    assert config_path.read_bytes() == config_before
    assert not (harness_root / ".codex").exists()
    assert git_output(nested_source, "worktree", "list", "--porcelain") == worktrees_before


def test_same_root_setup_rejects_a_primary_worktree_not_on_main(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    repository = temporary_git_repository
    run_process(["git", "switch", "-c", "operator-change"], cwd=repository).check_returncode()
    worktrees_before = git_output(repository, "worktree", "list", "--porcelain")

    result = run_setup(installed_commands, repository, answers="")

    assert result.returncode == 1
    assert "checked out on main" in result.stderr
    assert not (repository / ".graphtraj").exists()
    assert not (repository / ".codex").exists()
    assert not (repository / ".agents").exists()
    assert git_output(repository, "worktree", "list", "--porcelain") == worktrees_before


@pytest.mark.parametrize("command", ["status", "requests", "reports"])
def test_runner_status_discovers_the_graphtraj_configuration(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    """Queries reach configured Runner results without execution recovery setup."""
    from graphtraj.runtimes.replacement import caller_runtime

    if command == "status" and caller_runtime() != "codex":
        pytest.skip("status verifies a CODEX_THREAD_ID caller by Codex process ancestry "
                    "(468b83f); this test process has no Codex ancestor")
    repository = temporary_git_repository
    setup = run_setup(installed_commands, repository)
    monkeypatch.setenv("CODEX_THREAD_ID", "query-without-recovery-skill")
    assert not (repository / ".agents").exists()
    assert not (repository / ".agents/skills/retro/SKILL.md").exists()

    # Task 344 removed the status/requests routes; their library operations remain.
    status = run_process(
        runner_command(installed_commands, command, "missing@e1"),
        cwd=repository,
    )

    assert setup.returncode == 0, setup.stderr
    assert status.returncode == 1
    assert "code: alias-not-found" in status.stdout
    assert "Harness Runner Config" not in status.stderr


def _private_index_changes(repository: Path, tmp_path: Path) -> set[str]:
    """Stage everything into a throwaway index, as DSH's change snapshot does."""

    environment = {
        **__import__("os").environ,
        "GIT_INDEX_FILE": str(tmp_path / "private-index"),
    }
    for arguments in (["read-tree", "HEAD"], ["add", "--all"]):
        subprocess.run(
            ["git", *arguments], cwd=repository, env=environment, check=True
        )
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "HEAD"],
        cwd=repository,
        env=environment,
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    return set(staged.split())


def test_same_root_setup_hides_graphtraj_runtime_files_but_not_user_files(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    repository = temporary_git_repository
    assert run_setup(installed_commands, repository).returncode == 0
    inbox = repository / ".graphtraj" / "runner" / "main-sessions" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "key.jsonl").write_text("{}\n", encoding="utf-8")
    (inbox / "key.lock").write_text("", encoding="utf-8")
    (repository / ".graphtraj" / "runner" / "main-sessions" / "continuity.jsonl").write_text("{}\n", encoding="utf-8")
    core = repository / ".graphtraj" / "core" / "runner"
    core.mkdir(parents=True)
    (core / "record.jsonl").write_text("{}\n", encoding="utf-8")
    (repository / "notes-539.txt").write_text("user note\n", encoding="utf-8")
    (repository / "session.jsonl").write_text("user data\n", encoding="utf-8")

    status = git_output(repository, "status", "--porcelain", "--untracked-files=all")
    changes = _private_index_changes(repository, tmp_path)

    for listing in (set(line[3:] for line in status.splitlines()), changes):
        assert "notes-539.txt" in listing
        assert "session.jsonl" in listing
        assert ".graphtraj/config.yml" in listing
        assert ".graphtraj/roles.yml" in listing
        assert not {
            path for path in listing
            if path.startswith(".graphtraj/") and path not in {".graphtraj/config.yml", ".graphtraj/roles.yml"}
        }


def test_setup_registers_the_graphtraj_ignore_for_an_existing_same_root_project(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    from graphtraj.workspace.project_initialization import plan_project_setup

    repository = temporary_git_repository
    assert run_setup(installed_commands, repository).returncode == 0
    ignore = repository / ".graphtraj" / ".gitignore"
    ignore.unlink()  # a project set up before the rule existed

    def disposition() -> str:
        actions = plan_project_setup(repository).preflight().actions
        (match,) = [
            action.disposition for action in actions
            if action.description == "Ignore GraphTraj runtime files in {0}".format(ignore)
        ]
        return match

    assert disposition() == "REGISTER"
    assert run_setup(installed_commands, repository).returncode == 0
    assert ignore.is_file()
    assert disposition() == "ALREADY CONFIGURED"


def test_child_source_setup_leaves_the_graphtraj_directory_without_an_ignore(
    installed_commands: InstalledCommands,
    tmp_path: Path,
) -> None:
    harness = tmp_path / "harness"
    harness.mkdir()
    create_git_repository(harness / "source")
    assert run_setup(installed_commands, harness).returncode == 0
    assert not (harness / ".graphtraj" / ".gitignore").exists()
