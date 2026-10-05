"""Optional Node desktop adapter against an independently installed Python CLI."""

import os
import shutil

import pytest

from conftest import InstalledCommands, PROJECT_ROOT, run_process


@pytest.mark.skipif(shutil.which("node") is None, reason="Optional desktop requires Node")
def test_desktop_adapter_uses_installed_public_queries(installed_commands: InstalledCommands) -> None:
    """Real native queries cover project identity, preferences, errors and reconnect."""
    environment = dict(os.environ)
    environment["GRAPHTRAJ_TOOL"] = str(installed_commands.product.with_name("graphtraj-tool"))
    result = run_process(
        ["node", "--preserve-symlinks", "--preserve-symlinks-main", "--test",
         "desktop/tests/projects.test.cjs"],
        cwd=PROJECT_ROOT, env=environment, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
