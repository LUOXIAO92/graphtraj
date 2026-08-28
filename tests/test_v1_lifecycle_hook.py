from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

from conftest import FakeCodex, InstalledCommands, run_process
from test_project_setup import (
    install_user_skills,
    run_ready_setup as run_setup,
    setup_environment,
)


def run_guard(hook: Path, event: dict[str, object], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(hook)],
        cwd=cwd,
        input=json.dumps(event),
        check=False,
        text=True,
        capture_output=True,
    )


def test_installed_worktree_guard_is_an_independent_ticket_process(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    integration = harness_root / ".agent-worktrees" / "integration"
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    environment = setup_environment(user_home, fake_codex)
    setup = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(temporary_git_repository.name),
    )
    assert setup.returncode == 0, setup.stderr

    ticket_file = harness_root / "ticket.md"
    ticket_file.write_text("# Hook process ticket\n", encoding="utf-8")
    batch_file = harness_root / "batch.yml"
    batch_file.write_text(
        yaml.safe_dump(
            {
                "run_id": "20260814-hook-process",
                "runtime": "codex",
                "tasks": [
                    {
                        "ticket_id": "15",
                        "ticket_name": "hook-process",
                        "role": "engineer-expert",
                        "ticket_file": str(ticket_file),
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    launch = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch_file)],
        cwd=harness_root,
        env=environment,
        timeout=10,
    )
    assert launch.returncode == 0, launch.stderr
    task = yaml.safe_load(launch.stdout)["tasks"][0]
    ticket_worktree = Path(task["worktree_path"])
    hook = harness_root / ".codex" / "hooks" / "worktree_guard.py"
    assert not (ticket_worktree / ".codex").exists()
    start = run_guard(
        hook,
        {"hook_event_name": "SubagentStart", "cwd": str(ticket_worktree)},
        ticket_worktree,
    )
    assert start.returncode == 0, start.stderr
    start_payload = json.loads(start.stdout)
    assert str(ticket_worktree) in start_payload["hookSpecificOutput"]["additionalContext"]

    allowed = run_guard(
        hook,
        {
            "hook_event_name": "PreToolUse",
            "cwd": str(ticket_worktree),
            "tool_name": "Bash",
            "tool_input": {
                "command": "mkdir -p .scratch/task-delivery/reviews && touch "
                ".scratch/task-delivery/result.md"
            },
        },
        ticket_worktree,
    )
    assert allowed.returncode == 0, allowed.stderr
    assert allowed.stdout == ""

    denied = run_guard(
        hook,
        {
            "hook_event_name": "PreToolUse",
            "cwd": str(ticket_worktree),
            "tool_name": "Bash",
            "tool_input": {
                "command": "git -C {0} status --short".format(
                    temporary_git_repository
                )
            },
        },
        ticket_worktree,
    )
    assert denied.returncode == 0, denied.stderr
    assert json.loads(denied.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
