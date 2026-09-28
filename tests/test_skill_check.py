from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from conftest import InstalledCommands, run_process


def doctor_environment(user_home: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["HOME"] = str(user_home)
    return environment


def write_configuration(root: Path) -> None:
    """Write one valid Harness Project configuration."""
    config = root / ".graphtraj" / "config.yml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        """version: 1
paths:
  project_root: .
  docs: docs
  agent_worktrees: .graphtraj/.agent-worktrees
  state: .graphtraj/state
agent_runner:
  dispatch_depth: 2
  max_concurrency: 18
""",
        encoding="utf-8",
    )


def test_doctor_reports_valid_roles_without_bundled_skills(
    installed_commands: InstalledCommands,
    tmp_path: Path,
) -> None:
    """Doctor is valid without any bundled or operator Skill present."""
    harness_root = tmp_path / "harness-project"
    harness_root.mkdir()
    write_configuration(harness_root)
    (harness_root / ".graphtraj" / "roles.yml").write_text(
        "roles: {}\n", encoding="utf-8"
    )

    result = run_process(
        [str(installed_commands.product), "doctor"],
        cwd=harness_root,
        env=doctor_environment(tmp_path / "operator-home"),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert result.stdout.splitlines() == ["roles: OK"]


def test_doctor_reports_nothing_and_succeeds_before_setup(
    installed_commands: InstalledCommands,
    tmp_path: Path,
) -> None:
    """A directory without Harness Project files has no diagnostics to report."""
    harness_root = tmp_path / "plain-directory"
    harness_root.mkdir()

    result = run_process(
        [str(installed_commands.product), "doctor"],
        cwd=harness_root,
        env=doctor_environment(tmp_path / "operator-home"),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert result.stdout == ""


def test_doctor_reports_all_invalid_reusable_role_fields_without_mutating(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    repository = temporary_git_repository
    write_configuration(repository)
    roles_path = repository / ".graphtraj" / "roles.yml"
    roles_path.write_text(
        "roles:\n"
        "  team-leader:\n"
        "    runtime: ''\n"
        "    model: 3\n"
        "    reasoning_effort: true\n"
        "    allow_runtime_swarm: sometimes\n"
        "  engineer:\n"
        "    runtime: codex\n"
        "    model: gpt-5.6-luna\n"
        "    permissions: write\n"
        "  unknown-role:\n"
        "    runtime: codex\n"
        "    model: gpt-5.6-sol\n",
        encoding="utf-8",
    )
    before = roles_path.read_bytes()

    result = run_process(
        [str(installed_commands.product), "doctor"],
        cwd=repository,
        env=doctor_environment(tmp_path / "operator-home"),
    )

    assert result.returncode == 1
    assert result.stderr == ""
    assert "GraphTraj Roles is invalid." in result.stdout
    assert "team-leader.runtime" in result.stdout
    assert "team-leader.model" in result.stdout
    assert "team-leader.reasoning_effort" in result.stdout
    assert "team-leader.allow_runtime_swarm" in result.stdout
    assert "engineer.permissions" in result.stdout
    assert roles_path.read_bytes() == before
    assert not (repository / ".codex" / "agents").exists()


def test_doctor_reports_a_missing_roles_file(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    """A configured project without roles.yml reports invalid roles."""
    repository = temporary_git_repository
    write_configuration(repository)

    result = run_process(
        [str(installed_commands.product), "doctor"],
        cwd=repository,
        env=doctor_environment(tmp_path / "operator-home"),
    )

    assert result.returncode == 1
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "GraphTraj Roles is invalid.",
        "- roles.yml was not found at {0}.".format(
            repository / ".graphtraj" / "roles.yml"
        ),
    ]


def test_doctor_rejects_a_source_worktree_beneath_a_harness_root(
    installed_commands: InstalledCommands,
    tmp_path: Path,
) -> None:
    harness_root = tmp_path / "harness-project"
    source_worktree = harness_root / "source-repository"
    write_configuration(harness_root)
    source_worktree.mkdir()

    result = run_process(
        [str(installed_commands.product), "doctor"],
        cwd=source_worktree,
        env=doctor_environment(tmp_path / "operator-home"),
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "Harness Project Root" in result.stderr


def test_doctor_has_no_machine_output_mode(
    installed_commands: InstalledCommands,
    tmp_path: Path,
) -> None:
    harness_root = tmp_path / "harness-project"
    harness_root.mkdir()

    result = run_process(
        [str(installed_commands.product), "doctor", "--yaml"],
        cwd=harness_root,
        env=doctor_environment(tmp_path / "operator-home"),
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "--yaml" in result.stderr


@pytest.mark.parametrize("invalid", ("yaml", "limit", "absolute", "parent"))
def test_doctor_rejects_invalid_configuration_without_mutating(
    installed_commands: InstalledCommands,
    tmp_path: Path,
    invalid: str,
) -> None:
    """Configuration errors and escaped paths remain errors without Skills."""
    root = tmp_path / "harness"
    write_configuration(root)
    config = root / ".graphtraj" / "config.yml"
    (config.parent / "roles.yml").write_text("roles: {}\n", encoding="utf-8")
    document = yaml.safe_load(config.read_text())
    if invalid == "yaml":
        config.write_text("[broken", encoding="utf-8")
    else:
        if invalid == "limit":
            document["agent_runner"]["max_concurrency"] = 0
        else:
            document["paths"]["state"] = (
                str(tmp_path / "outside") if invalid == "absolute" else "../outside"
            )
        config.write_text(yaml.safe_dump(document), encoding="utf-8")
    before = config.read_bytes()

    result = run_process(
        [str(installed_commands.product), "doctor"],
        cwd=root,
        env=doctor_environment(tmp_path / "operator-home"),
    )

    assert result.returncode == 2
    assert "GraphTraj Config" in result.stderr
    assert config.read_bytes() == before
    assert not (tmp_path / "outside").exists()
