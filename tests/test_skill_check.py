from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pytest

from conftest import InstalledCommands, run_process


CORE_SKILL_NAMES = (
    "setup-project",
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
    "task-breakdown",
    "research",
    "retro",
    "wayfinder",
    "prototype",
    "ponytail-review",
)


def install_skill(
    skill_root: Path,
    name: str,
    *,
    directory_name: Optional[str] = None,
    frontmatter: Optional[str] = None,
) -> None:
    skill_directory = skill_root / (directory_name or name)
    skill_directory.mkdir(parents=True)
    (skill_directory / "SKILL.md").write_text(
        frontmatter
        or "---\nname: {0}\ndescription: Test Skill.\n---\n\n# Test Skill\n".format(name),
        encoding="utf-8",
    )


def doctor_environment(user_home: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["HOME"] = str(user_home)
    return environment


def test_doctor_finds_core_skills_in_project_and_user_scopes(
    installed_commands: InstalledCommands,
    tmp_path: Path,
) -> None:
    harness_root = tmp_path / "harness-project"
    project_skills = harness_root / ".agents" / "skills"
    user_home = tmp_path / "operator-home"
    user_skills = user_home / ".agents" / "skills"
    harness_root.mkdir()

    for name in CORE_SKILL_NAMES[:6]:
        install_skill(project_skills, name)
    for name in CORE_SKILL_NAMES[6:]:
        install_skill(user_skills, name)

    result = run_process(
        [str(installed_commands.product), "doctor"],
        cwd=harness_root,
        env=doctor_environment(user_home),
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "{0}: OK".format(name) for name in CORE_SKILL_NAMES
    ]


def test_doctor_reports_all_invalid_reusable_role_fields_without_mutating(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    repository = temporary_git_repository
    for name in CORE_SKILL_NAMES:
        install_skill(repository / ".agents" / "skills", name)
    graphtraj = repository / ".graphtraj"
    graphtraj.mkdir()
    (graphtraj / "config.yml").write_text(
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
    roles_path = graphtraj / "roles.yml"
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
    assert "unknown-role" in result.stdout
    assert roles_path.read_bytes() == before
    assert not (repository / ".codex" / "agents").exists()


def test_doctor_reports_one_and_multiple_missing_core_skills(
    installed_commands: InstalledCommands,
    tmp_path: Path,
) -> None:
    for case_name, missing_names in (
        ("one-missing", {"task-delivery"}),
        ("multiple-missing", {"grilling", "task-delivery", "tdd"}),
    ):
        harness_root = tmp_path / case_name
        project_skills = harness_root / ".agents" / "skills"
        legacy_skills = harness_root / ".codex" / "skills"
        user_home = tmp_path / "{0}-home".format(case_name)
        harness_root.mkdir()

        for index, name in enumerate(CORE_SKILL_NAMES):
            if name not in missing_names:
                install_skill(
                    project_skills,
                    name,
                    directory_name="skill-{0}".format(index),
                )
        install_skill(project_skills, "unrelated-skill")
        for name in missing_names:
            install_skill(legacy_skills, name)

        result = run_process(
            [str(installed_commands.product), "doctor"],
            cwd=harness_root,
            env=doctor_environment(user_home),
        )

        assert result.returncode == 1
        assert result.stderr == ""
        assert result.stdout.splitlines() == [
            "{0}: {1}".format(
                name,
                "MISSING" if name in missing_names else "OK",
            )
            for name in CORE_SKILL_NAMES
        ]


def test_doctor_excludes_primary_worktree_and_neighboring_projects(
    installed_commands: InstalledCommands,
    tmp_path: Path,
) -> None:
    harness_root = tmp_path / "harness-project"
    primary_skills = harness_root / "source-repository" / ".agents" / "skills"
    neighboring_skills = harness_root / "neighbor" / ".agents" / "skills"
    user_home = tmp_path / "empty-operator-home"
    harness_root.mkdir()

    for name in CORE_SKILL_NAMES:
        install_skill(primary_skills, name)
        install_skill(neighboring_skills, name)

    result = run_process(
        [str(installed_commands.product), "doctor"],
        cwd=harness_root,
        env=doctor_environment(user_home),
    )

    assert result.returncode == 1
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "{0}: MISSING".format(name) for name in CORE_SKILL_NAMES
    ]


def test_doctor_rejects_a_source_worktree_beneath_a_harness_root(
    installed_commands: InstalledCommands,
    tmp_path: Path,
) -> None:
    harness_root = tmp_path / "harness-project"
    source_worktree = harness_root / "source-repository"
    source_skills = source_worktree / ".agents" / "skills"
    user_home = tmp_path / "operator-home"
    config = harness_root / ".graphtraj" / "config.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        """version: 1
paths:
  project_root: source-repository
  docs: docs
  agent_worktrees: .graphtraj/.agent-worktrees
  state: .graphtraj/state
agent_runner:
  dispatch_depth: 2
  max_concurrency: 18
""",
        encoding="utf-8",
    )
    source_worktree.mkdir()
    for name in CORE_SKILL_NAMES:
        install_skill(source_skills, name)

    result = run_process(
        [str(installed_commands.product), "doctor"],
        cwd=source_worktree,
        env=doctor_environment(user_home),
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "Harness Project Root" in result.stderr


def test_doctor_ignores_a_tracked_same_root_core_skill(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    repository = temporary_git_repository
    source_skill = repository / ".agents" / "skills" / "implement" / "SKILL.md"
    source_skill.parent.mkdir(parents=True)
    source_skill.write_text(
        "---\nname: implement\ndescription: Repository Skill.\n---\n",
        encoding="utf-8",
    )
    run_process(["git", "add", ".agents"], cwd=repository).check_returncode()
    run_process(
        ["git", "commit", "-m", "Add repository implement Skill"], cwd=repository
    ).check_returncode()
    config = repository / ".graphtraj" / "config.yml"
    config.parent.mkdir()
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
    user_home = tmp_path / "operator-home"
    for name in CORE_SKILL_NAMES:
        if name != "implement":
            install_skill(user_home / ".agents" / "skills", name)

    result = run_process(
        [str(installed_commands.product), "doctor"],
        cwd=repository,
        env=doctor_environment(user_home),
    )

    assert result.returncode == 1
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "{0}: {1}".format(
            name,
            "MISSING" if name == "implement" else "OK",
        )
        for name in CORE_SKILL_NAMES
    ] + [
        "GraphTraj Roles is invalid.",
        "- roles.yml was not found at {0}.".format(
            repository / ".graphtraj" / "roles.yml"
        ),
    ]


def test_doctor_ignores_a_tracked_same_root_core_skill_before_setup(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    repository = temporary_git_repository
    source_skill = repository / ".agents" / "skills" / "implement" / "SKILL.md"
    source_skill.parent.mkdir(parents=True)
    source_skill.write_text(
        "---\nname: implement\ndescription: Repository Skill.\n---\n",
        encoding="utf-8",
    )
    run_process(["git", "add", ".agents"], cwd=repository).check_returncode()
    run_process(
        ["git", "commit", "-m", "Add repository implement Skill"], cwd=repository
    ).check_returncode()
    user_home = tmp_path / "operator-home"
    for name in CORE_SKILL_NAMES:
        if name != "implement":
            install_skill(user_home / ".agents" / "skills", name)

    result = run_process(
        [str(installed_commands.product), "doctor"],
        cwd=repository,
        env=doctor_environment(user_home),
    )

    assert result.returncode == 1
    assert result.stderr == ""
    assert not (repository / ".graphtraj").exists()
    assert result.stdout.splitlines() == [
        "{0}: {1}".format(
            name,
            "MISSING" if name == "implement" else "OK",
        )
        for name in CORE_SKILL_NAMES
    ]


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


def test_doctor_uses_only_valid_top_level_yaml_names(
    installed_commands: InstalledCommands,
    tmp_path: Path,
) -> None:
    harness_root = tmp_path / "harness-project"
    project_skills = harness_root / ".agents" / "skills"
    user_home = tmp_path / "operator-home"
    harness_root.mkdir()

    for name in CORE_SKILL_NAMES:
        install_skill(project_skills, name)

    install_skill(
        project_skills,
        "tdd",
        directory_name="quoted-tdd",
        frontmatter=(
            "---\nname: \"tdd\" # supported inline comment\n"
            "description: Test Skill.\n---\n"
        ),
    )
    install_skill(
        project_skills,
        "task-delivery",
        directory_name="nested-only",
        frontmatter=(
            "---\nmetadata:\n  name: task-delivery\n"
            "description: Not a declared top-level name.\n---\n"
        ),
    )
    install_skill(
        project_skills,
        "grilling",
        directory_name="unterminated",
        frontmatter="---\nname: grilling\ndescription: Missing delimiter.\n",
    )

    # Remove the valid copies so only malformed declarations remain for these names.
    for name in ("task-delivery", "grilling", "tdd"):
        (project_skills / name / "SKILL.md").unlink()

    result = run_process(
        [str(installed_commands.product), "doctor"],
        cwd=harness_root,
        env=doctor_environment(user_home),
    )

    assert result.returncode == 1
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "{0}: {1}".format(
            name,
            "MISSING" if name in {"task-delivery", "grilling"} else "OK",
        )
        for name in CORE_SKILL_NAMES
    ]


@pytest.mark.parametrize("link_kind", ("directory", "skill-file"))
def test_doctor_finds_a_linked_harness_core_skill(
    installed_commands: InstalledCommands,
    tmp_path: Path,
    link_kind: str,
) -> None:
    harness_root = tmp_path / "harness-project"
    harness_skills = harness_root / ".agents" / "skills"
    user_home = tmp_path / "operator-home"
    target = tmp_path / "external-implement"
    harness_root.mkdir()
    install_skill(tmp_path, "implement", directory_name=target.name)
    for name in CORE_SKILL_NAMES:
        if name != "implement":
            install_skill(user_home / ".agents" / "skills", name)

    if link_kind == "directory":
        harness_skills.mkdir(parents=True)
        (harness_skills / "linked-implement").symlink_to(
            target, target_is_directory=True
        )
    else:
        linked_skill = harness_skills / "linked-implement" / "SKILL.md"
        linked_skill.parent.mkdir(parents=True)
        linked_skill.symlink_to(target / "SKILL.md")

    result = run_process(
        [str(installed_commands.product), "doctor"],
        cwd=harness_root,
        env=doctor_environment(user_home),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "{0}: OK".format(name) for name in CORE_SKILL_NAMES
    ]
