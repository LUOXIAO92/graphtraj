from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, run_process, wait_for_file
from test_project_setup import install_user_skills, run_ready_setup as run_setup


def configure_harness(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> tuple[Path, Path, Path, dict[str, str]]:
    harness_root = temporary_git_repository.parent
    worktree_root = harness_root / ".graphtraj" / ".agent-worktrees"
    integration = worktree_root / "dev"
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    setup_result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="y\n",
    )
    assert setup_result.returncode == 0, setup_result.stderr
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(user_home),
            "PATH": os.pathsep.join(
                (str(fake_codex.executable.parent), os.environ.get("PATH", ""))
            ),
            "FAKE_CODEX_LOG": str(fake_codex.log_file),
        }
    )
    return harness_root, worktree_root, integration, environment


@contextlib.contextmanager
def engineer_probe(commands, harness, fake_codex, environment, *, body="Probe the Adapter.", executable=None):
    """Dispatch a real Team Leader with only the Engineer's Runtime substituted."""
    from test_ticket_graph import _change_status, _register, _ticket

    _register(commands, harness, {**_ticket("82", "adapter-probe"), "body": body})
    _change_status(commands, harness, "82", "ready")
    driver = fake_codex.executable.with_name("controlled-codex")
    shutil.copyfile(fake_codex.executable, driver)
    driver.chmod(0o755)
    # The installed Runner still resolves, configures, and launches every role.
    # Only the executable's model work is controlled at the Runtime boundary.
    fake_codex.executable.write_text(
        "#!" + sys.executable + "\nimport os, sys\n"
        + "engineer = os.environ.get('GRAPHTRAJ_ROLE', '').startswith('engineer-')\n"
        + "if not engineer:\n    os.environ.pop('FAKE_CODEX_RELEASE_FILE', None)\n"
        + "target = " + repr(str(executable or driver)) + " if engineer else " + repr(str(driver)) + "\n"
        + "os.execv(target, [target, *sys.argv[1:]])\n"
    )
    env = dict(environment, FAKE_CODEX_LIFECYCLE_ACTION="complete-team-round",
               FAKE_CODEX_APPEND_LOG="1", FAKE_CODEX_CAPTURE_ROLE="1",
               GRAPHTRAJ_AGENT_RUNNER=str(commands.runner))
    env["PATH"] = str(fake_codex.executable.parent) + os.pathsep + env.get("PATH", "")
    batch = harness / "probe-batch.yml"
    batch.write_text(yaml.safe_dump({"tasks": [{
        "ticket_id": "82", "ticket_name": "adapter-probe", "role": "team-leader",
    }]}))
    with (harness / "probe-output.log").open("w+") as output:
        process = subprocess.Popen(
            [str(commands.runner), "--batch-input", str(batch)], cwd=harness, env=env,
            text=True, stdout=output, stderr=subprocess.STDOUT,
        )
        alias = None
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                for path in (harness / ".graphtraj" / "runner").glob("sessions/*/mapping.yml"):
                    mapping = yaml.safe_load(path.read_text())
                    if mapping["role"].startswith("engineer-"):
                        alias = mapping["alias"]
                        break
                if alias:
                    break
                if process.poll() is not None:
                    output.seek(0)
                    raise AssertionError(output.read())
                time.sleep(0.02)
            assert alias, "The installed Team did not launch its Engineer"
            yield alias, Path(mapping["worktree_path"]), env
        finally:
            if alias:
                status = run_process([str(commands.runner), "status", alias], cwd=harness, env=env)
                if yaml.safe_load(status.stdout)["aliases"][0].get("activity") == "running":
                    interrupted = run_process([str(commands.runner), "interrupt", alias], cwd=harness, env=env)
                    if interrupted.returncode:
                        observed = run_process([str(commands.runner), "status", alias], cwd=harness, env=env)
                        assert yaml.safe_load(observed.stdout)["aliases"][0].get("activity") == "idle"
            process.wait(timeout=60)
