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


def coding_roles() -> dict:
    """Return one configured coding Team arrangement for dispatch tests.

    Setup writes an empty role selection, so a project that selects coding
    work declares these presets itself.
    """
    document = {"roles": {
        "coding_team": {
            "team_leader": {
                "runtime": "codex",
                "model": "gpt-5.6-sol",
                "allow_runtime_swarm": True,
            },
            "engineer": {"runtime": "codex", "model": "gpt-5.6-sol"},
            "standards_reviewer": {"runtime": "codex", "model": "gpt-5.6-sol"},
            "spec_reviewer": {"runtime": "codex", "model": "gpt-5.6-sol"},
            "merge_resolver": {"runtime": "codex", "model": "gpt-5.6-sol"},
        },
        "delivery_state": {"runtime": "codex", "model": "gpt-5.6-luna"},
    }}
    for name, preset in document["roles"]["coding_team"].items():
        preset["instructions"] = name.replace("_", "-")
        if name in {"team_leader", "standards_reviewer", "spec_reviewer"}:
            preset["worktree_access"] = "read"
        if name == "engineer":
            preset["reports"] = ["engineer.md", "validation.md"]
        elif name == "team_leader":
            preset["reports"] = ["leader.md"]
    document["roles"]["delivery_state"]["instructions"] = "delivery-state"
    return document


def configure_coding_roles(harness_root: Path) -> None:
    """Declare the coding Team presets and their dispatch tree in roles.yml."""
    roles_file = harness_root / ".graphtraj/roles.yml"
    roles = coding_roles()
    # Test task dispatch explicitly authorizes its configured direct children.
    children = {name: {} for name in (
        "coding-team.engineer", "coding_team.engineer", "engineer",
        "coding-team.standards-reviewer", "coding-team.spec-reviewer",
    )}
    roles["role_tree"] = {
        **{name: children for name in ("coding-team.team-leader", "coding_team.team_leader", "team-leader")},
        "coding_team.merge_resolver": {}, "merge-resolver": {}, "delivery_state": {},
    }
    roles_file.write_text(yaml.safe_dump(roles))


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
    configure_coding_roles(harness_root)
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


def retained_state(path: Path) -> bytes | str:
    """Return what a later run must not change for one retained record.

    A retained Trace entry reads the Runtime-owned native Session file through a
    symbolic link, and its owner may keep appending to that file. The fake
    Runtime also reuses one native Session file per test, so a linked entry is
    compared by its link target and every other record by its own bytes.
    """
    return os.readlink(path) if path.is_symlink() else path.read_bytes()


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
        + "engineer = os.environ.get('GRAPHTRAJ_ROLE') == 'engineer'\n"
        + "if not engineer:\n    os.environ.pop('FAKE_CODEX_RELEASE_FILE', None)\n"
        + "target = " + repr(str(executable or driver)) + " if engineer else " + repr(str(driver)) + "\n"
        + "os.execv(target, [target, *sys.argv[1:]])\n"
    )
    env = dict(environment, FAKE_CODEX_LIFECYCLE_ACTION="complete-team-round",
               FAKE_CODEX_LOG=str(fake_codex.log_file),
               FAKE_CODEX_APPEND_LOG="1", FAKE_CODEX_CAPTURE_ROLE="1",
               FAKE_CODEX_CAPTURE_STDIN="1",
               GRAPHTRAJ_AGENT_RUNNER=str(commands.runner))
    env["PATH"] = str(fake_codex.executable.parent) + os.pathsep + env.get("PATH", "")
    batch = harness / "probe-batch.yml"
    batch.write_text(yaml.safe_dump({"tasks": [{
        "ticket_id": "82", "ticket_name": "adapter-probe", "role": "team-leader",
    }]}))
    with (harness / "probe-output.log").open("w+") as output:
        process = subprocess.Popen(
            [str(commands.runner), "--swarm-input", str(batch)], cwd=harness, env=env,
            text=True, stdout=output, stderr=subprocess.STDOUT,
        )
        alias = None
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                for path in (harness / ".graphtraj" / "runner").glob("sessions/*/mapping.yml"):
                    mapping = yaml.safe_load(path.read_text())
                    if mapping["role"] == "engineer":
                        alias = mapping["alias"]
                        break
                if alias:
                    break
                if process.poll() is not None:
                    output.seek(0)
                    raise AssertionError(output.read())
                time.sleep(0.02)
            assert alias, "The installed Team did not launch its Engineer"
            if executable is None:
                # Native turn/start acknowledges ownership before model work begins.
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if fake_codex.log_file.exists():
                        records = [json.loads(line) for line in fake_codex.log_file.read_text().splitlines()]
                        if any(record.get("role") == "engineer" for record in records):
                            break
                    time.sleep(0.01)
                else:
                    raise AssertionError("The controlled Engineer did not receive its input")
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


def wait_for_ticket_status(commands: InstalledCommands, root: Path, ticket_id: str, status: str) -> None:
    """Wait for this controlled asynchronous task's public delivery outcome."""
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        result = run_process([str(commands.product), 'ticket', 'graph'], cwd=root)
        result.check_returncode()
        tickets = yaml.safe_load(result.stdout)['tickets']
        current = next(ticket for ticket in tickets if ticket['ticket_id'] == ticket_id)
        if current['status'] == status:
            return
        time.sleep(.05)
    raise AssertionError(current)
