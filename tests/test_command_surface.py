from __future__ import annotations

import os
from pathlib import Path

from conftest import InstalledCommands, run_process


def test_installed_commands_advertise_the_bootstrap_interfaces(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    environment = os.environ.copy()

    product_help = run_process(
        [str(installed_commands.product), "--help"],
        cwd=temporary_git_repository,
        env=environment,
    )
    runner_help = run_process(
        [str(installed_commands.runner), "--help"],
        cwd=temporary_git_repository,
        env=environment,
    )

    assert product_help.returncode == 0, product_help.stderr
    assert "setup" in product_help.stdout
    assert "doctor" in product_help.stdout
    assert runner_help.returncode == 0, runner_help.stderr
    for command in ("launch", "status", "send", "interrupt", "cleanup"):
        assert command in runner_help.stdout
