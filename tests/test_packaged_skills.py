from __future__ import annotations

from pathlib import Path

import pytest

from conftest import InstalledCommands, run_process
from test_existing_repository_setup import run_setup


@pytest.mark.parametrize("separate_source", (False, True))
def test_setup_prepares_both_layouts_without_bundled_skills(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    separate_source: bool,
) -> None:
    """Setup and doctor work when the distribution ships no Skill bodies."""
    root = temporary_git_repository.parent if separate_source else temporary_git_repository
    result = run_setup(installed_commands, root)
    assert result.returncode == 0, result.stderr
    assert not (root / ".agents" / "skills").exists()

    doctor = run_process([str(installed_commands.product), "doctor"], cwd=root)
    assert doctor.returncode == 0, doctor.stdout + doctor.stderr
    assert doctor.stdout.splitlines() == ["roles: OK"]
