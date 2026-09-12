from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import InstalledCommands, run_process
from test_existing_repository_setup import run_setup
from test_project_setup import supported_skill_contents, tree_contents


@pytest.mark.parametrize("separate_source", (False, True))
def test_setup_installs_all_core_skills_and_their_readable_references(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    separate_source: bool,
) -> None:
    root = temporary_git_repository.parent if separate_source else temporary_git_repository
    result = run_setup(installed_commands, root)
    assert result.returncode == 0, result.stderr
    skills = root / ".agents" / "skills"
    assert {path.name for path in skills.iterdir()} == {
        "setup-project", "grill-with-docs", "grilling", "domain-modeling",
        "to-spec", "to-tickets", "task-delivery", "implement",
        "ponytail", "tdd", "code-review", "resolving-merge-conflicts",
        "task-breakdown", "research", "retro", "wayfinder", "prototype",
        "ponytail-review",
    }
    for skill in skills.iterdir():
        assert tree_contents(skill) == supported_skill_contents(skill.name)
    for name in (
        "setup-project", "task-delivery", "domain-modeling", "research", "retro", "wayfinder",
    ):
        assert (skills / name / "references" / "coding.md").read_text().strip()
    for reference in ("UI.md", "LOGIC.md"):
        assert (skills / "prototype" / reference).read_text().strip()

    doctor = run_process([str(installed_commands.product), "doctor"], cwd=root)
    assert doctor.returncode == 0, doctor.stdout + doctor.stderr
    assert len(doctor.stdout.splitlines()) == 19  # 18 Skills and reusable roles.


def installed_python(installed_commands: InstalledCommands) -> Path:
    candidate = installed_commands.product.parent / "python"
    if candidate.is_file():
        return candidate
    for line in installed_commands.product.read_text(encoding="utf-8").splitlines():
        prefix = "'''exec' '"
        if line.startswith(prefix):
            return Path(line.removeprefix(prefix).split("'", maxsplit=1)[0])
    raise AssertionError("Installed product wrapper did not declare its Python interpreter.")


def test_installed_distribution_installs_supported_skill_resources(
    installed_commands: InstalledCommands,
    tmp_path: Path,
) -> None:
    resource_probe = """
import json
import sys
from pathlib import Path

from graphtraj.supported_skills import SupportedSkills

runtime_store = Path(sys.argv[1]) / ".codex"
SupportedSkills.load().install_missing(runtime_store, ("task-delivery", "tdd", "setup-project", "ponytail-review"))
skill_root = runtime_store.parent / ".agents" / "skills"
print(json.dumps({
    name: (skill_root / name / "SKILL.md").read_text(encoding="utf-8")
    for name in ("task-delivery", "tdd", "setup-project", "ponytail-review")
}))

"""

    result = run_process(
        [
            str(installed_python(installed_commands)),
            "-c",
            resource_probe,
            str(tmp_path),
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    resources = json.loads(result.stdout)
    assert resources["task-delivery"].startswith("---\nname: task-delivery\n")
    assert resources["tdd"].startswith("---\nname: tdd\n")
    assert resources["setup-project"].startswith("---\nname: setup-project\n")
    assert resources["ponytail-review"].startswith("---\nname: ponytail-review\n")
