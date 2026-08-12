from __future__ import annotations

import os
from pathlib import Path

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


def install_skill(skill_root: Path, name: str) -> None:
    skill_directory = skill_root / name
    skill_directory.mkdir(parents=True)
    (skill_directory / "SKILL.md").write_text(
        "---\nname: {0}\ndescription: Test Skill.\n---\n\n# Test Skill\n".format(name),
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
    project_skills = (
        harness_root
        / ".agent-worktrees"
        / "integration"
        / ".agents"
        / "skills"
    )
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
