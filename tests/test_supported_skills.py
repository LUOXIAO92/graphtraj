"""The distribution ships no bundled Skill, role or Codex agent resources.

Core imports and Runtime role resolution must work from the shipped code
alone, without any packaged Skill bodies or role templates.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from conftest import InstalledCommands, run_process


def test_built_distribution_supplies_no_bundled_runtime_resources(
    built_wheel: Path,
) -> None:
    """The artifact an operator installs carries no packaged runtime resources."""

    with zipfile.ZipFile(built_wheel) as archive:
        names = archive.namelist()

    assert not [name for name in names if name.startswith("graphtraj/resources/")]


def test_installed_core_imports_and_role_resolution_work_without_resources(
    installed_commands: InstalledCommands,
    tmp_path: Path,
) -> None:
    """Shipped code imports and resolves a role with no packaged resources."""

    probe = """
import json
from pathlib import Path

import graphtraj
from graphtraj.configuration.project_roles import RolePreset
from graphtraj.configuration.role_definitions import resolve_child_role
from graphtraj.interfaces import tools
from graphtraj.interfaces.cli import agent_runner, graphtraj as cli

role = resolve_child_role(
    "engineer",
    RolePreset(
        "codex", "operator-model", None, None,
        reasoning_effort="high", worktree_access="write",
    ),
    None,
)
print(json.dumps({
    "role": role.name,
    "instructions": bool(role.instructions),
    "resources": (Path(graphtraj.__file__).parent / "resources").exists(),
}))
"""

    result = run_process(
        [str(installed_commands.product.parent / "python"), "-c", probe],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "role": "engineer",
        "instructions": True,
        "resources": False,
    }
