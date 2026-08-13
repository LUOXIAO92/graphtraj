from __future__ import annotations

import json
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


def installed_python(installed_commands: InstalledCommands) -> Path:
    for line in installed_commands.product.read_text(encoding="utf-8").splitlines():
        prefix = "'''exec' '"
        if line.startswith(prefix):
            return Path(line.removeprefix(prefix).split("'", maxsplit=1)[0])
    raise AssertionError("Installed product wrapper did not declare its Python interpreter.")


def test_supported_skills_loads_from_one_child_traversable(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    expected_names = json.dumps(CORE_SKILL_NAMES)
    resource_probe = """
from you_are_a_product_architect import supported_skills
import json

class SingleChildTraversable:
    def joinpath(self, child):
        return self

    def is_dir(self):
        return True

supported_skills.resources.files = lambda _: SingleChildTraversable()
skill_resources = supported_skills.SupportedSkills.load()
print(json.dumps(tuple(skill_resources.resources_by_name)))
"""

    result = run_process(
        [str(installed_python(installed_commands)), "-c", resource_probe],
        cwd=temporary_git_repository,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == json.loads(expected_names)
