from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from conftest import InstalledCommands, run_process
from test_existing_repository_setup import run_setup


@pytest.mark.parametrize("separate_source", (False, True))
def test_setup_prepares_both_layouts_without_bundled_skills(
    mutable_installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    separate_source: bool,
    tmp_path: Path,
) -> None:
    """Setup and doctor also work when the distribution has no Skill resources."""
    installed_commands = mutable_installed_commands
    package = run_process(
        [str(installed_python(installed_commands)), "-c",
         "import graphtraj; print(graphtraj.__path__[0])"],
        cwd=tmp_path,
    )
    package.check_returncode()
    shutil.rmtree(Path(package.stdout.strip()) / "resources" / "skills")
    root = temporary_git_repository.parent if separate_source else temporary_git_repository
    result = run_setup(installed_commands, root)
    assert result.returncode == 0, result.stderr
    assert not (root / ".agents").exists()

    doctor = run_process([str(installed_commands.product), "doctor"], cwd=root)
    assert doctor.returncode == 0, doctor.stdout + doctor.stderr
    assert doctor.stdout.splitlines() == ["roles: OK"]


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

from graphtraj.configuration.supported_skills import SupportedSkills

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
