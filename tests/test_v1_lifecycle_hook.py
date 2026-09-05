from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

from conftest import FakeCodex, InstalledCommands, run_process, wait_for_file
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
    integration = harness_root / ".graphtraj" / ".agent-worktrees" / "dev"
    context = harness_root / "CONTEXT.md"
    documents = harness_root / "docs"
    context.write_text("# Harness context\n", encoding="utf-8")
    documents.mkdir()
    (documents / "guidance.md").write_text(
        "# Harness guidance\n", encoding="utf-8"
    )
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    environment = setup_environment(user_home, fake_codex)
    setup = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="y\n",
    )
    assert setup.returncode == 0, setup.stderr

    ticket_file = harness_root / "ticket.md"
    ticket_file.write_text("# Hook process ticket\n", encoding="utf-8")
    batch_file = harness_root / "batch.yml"
    batch_file.write_text(
        yaml.safe_dump(
            {
                "run_id": "20260814-hook-process",
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
    assert (ticket_worktree / "CONTEXT.md").resolve() == context.resolve()
    assert (ticket_worktree / "CONTEXT.md").read_text(encoding="utf-8") == (
        "# Harness context\n"
    )
    assert (ticket_worktree / "docs").resolve() == documents.resolve()
    assert (ticket_worktree / "docs" / "guidance.md").read_text(
        encoding="utf-8"
    ) == "# Harness guidance\n"
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
                "command": "mkdir -p .state/reviews && touch "
                ".state/result.md"
            },
        },
        ticket_worktree,
    )
    assert allowed.returncode == 0, allowed.stderr
    assert allowed.stdout == ""

    for command in ("cat CONTEXT.md", "cat docs/guidance.md"):
        readable = run_guard(
            hook,
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(ticket_worktree),
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            ticket_worktree,
        )
        assert readable.returncode == 0, readable.stderr
        assert readable.stdout == ""

    for command in ("touch CONTEXT.md", "touch docs/forbidden.md"):
        write = run_guard(
            hook,
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(ticket_worktree),
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            ticket_worktree,
        )
        assert write.returncode == 0, write.stderr
        assert (
            json.loads(write.stdout)["hookSpecificOutput"]["permissionDecision"]
            == "deny"
        )

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

    session = (
        harness_root / ".codex" / "agent-runner" / "sessions" / task["alias"]
    )
    wait_for_file(session / "turn.yml")
    cleanup = run_process(
        [
            str(installed_commands.runner),
            "cleanup",
            "--run-id",
            "20260814-hook-process",
            "--ticket-id",
            "15",
        ],
        cwd=harness_root,
        env=environment,
    )
    assert cleanup.returncode == 0, cleanup.stderr
    assert yaml.safe_load(cleanup.stdout)["cleanup_status"] == "cleaned"
    assert not ticket_worktree.exists()
    assert context.read_text(encoding="utf-8") == "# Harness context\n"
    assert (documents / "guidance.md").read_text(encoding="utf-8") == (
        "# Harness guidance\n"
    )
