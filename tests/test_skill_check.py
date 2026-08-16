from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from conftest import InstalledCommands, run_process


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
    project_skills = harness_root / ".codex" / "skills"
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


def test_doctor_reports_one_and_multiple_missing_core_skills(
    installed_commands: InstalledCommands,
    tmp_path: Path,
) -> None:
    for case_name, missing_names in (
        ("one-missing", {"task-delivery"}),
        ("multiple-missing", {"grilling", "task-delivery", "tdd"}),
    ):
        harness_root = tmp_path / case_name
        project_skills = harness_root / ".codex" / "skills"
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
    source_skills = source_worktree / ".codex" / "skills"
    user_home = tmp_path / "operator-home"
    (
        harness_root / ".codex" / "agent-runner" / "config.yml"
    ).parent.mkdir(parents=True)
    (harness_root / ".codex" / "agent-runner" / "config.yml").write_text(
        "runtime: codex\n",
        encoding="utf-8",
    )
    source_worktree.mkdir()
    (
        source_worktree / ".codex" / "agent-runner" / "config.yml"
    ).parent.mkdir(parents=True)
    (
        source_worktree / ".codex" / "agent-runner" / "config.yml"
    ).write_text("runtime: source-owned\n", encoding="utf-8")
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
    assert "no such option" in result.stderr.lower()
    assert "--yaml" in result.stderr
    for name in CORE_SKILL_NAMES:
        assert "{0}:".format(name) not in result.stderr


def test_doctor_uses_only_valid_top_level_yaml_names(
    installed_commands: InstalledCommands,
    tmp_path: Path,
) -> None:
    harness_root = tmp_path / "harness-project"
    project_skills = harness_root / ".codex" / "skills"
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
