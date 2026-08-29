from __future__ import annotations

import json
from pathlib import Path

from conftest import InstalledCommands, run_process


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

from you_are_a_product_architect.supported_skills import SupportedSkills

runtime_store = Path(sys.argv[1]) / ".codex"
SupportedSkills.load().install_missing(runtime_store, ("task-delivery", "tdd"))
skill_root = runtime_store.parent / ".agents" / "skills"
print(json.dumps({
    name: (skill_root / name / "SKILL.md").read_text(encoding="utf-8")
    for name in ("task-delivery", "tdd")
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
