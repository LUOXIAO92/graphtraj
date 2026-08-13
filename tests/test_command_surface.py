from __future__ import annotations

import json
import os
from pathlib import Path

from conftest import FakeCodex, InstalledCommands, run_process


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
    assert "not implemented" in runner_help.stdout.lower()


def test_installed_runner_future_operations_fail_until_implemented(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    operations = {
        "send": [
            str(installed_commands.runner),
            "send",
            "ticket-42@j1",
            "--instruction",
            "continue",
        ],
        "interrupt": [str(installed_commands.runner), "interrupt", "ticket-42@j1"],
        "cleanup": [
            str(installed_commands.runner),
            "cleanup",
            "--run-id",
            "test-run",
            "--ticket-id",
            "42",
        ],
    }

    for operation, command in operations.items():
        result = run_process(command, cwd=temporary_git_repository)

        assert result.returncode != 0, operation
        assert result.stdout == "", operation
        assert "not implemented" in result.stderr.lower(), operation


def test_fake_codex_records_jsonl_events_and_exact_argv(
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    expected_events = [
        {"type": "thread.started", "thread_id": "thread-42"},
        {"type": "turn.started"},
        {
            "type": "turn.completed",
            "usage": {
                "cached_input_tokens": 0,
                "input_tokens": 7,
                "output_tokens": 3,
            },
        },
    ]
    environment = os.environ.copy()
    environment.update(
        {
            "FAKE_CODEX_LOG": str(fake_codex.log_file),
            "FAKE_CODEX_EVENTS": json.dumps(expected_events),
            "FAKE_CODEX_EXIT_CODE": "23",
        }
    )

    result = run_process(
        [
            str(fake_codex.executable),
            "exec",
            "resume",
            "thread-42",
            "continue with this exact instruction",
        ],
        cwd=tmp_path,
        env=environment,
    )

    assert result.returncode == 23
    assert [json.loads(line) for line in result.stdout.splitlines()] == expected_events
    assert json.loads(fake_codex.log_file.read_text(encoding="utf-8")) == {
        "argv": [
            "exec",
            "resume",
            "thread-42",
            "continue with this exact instruction",
        ],
        "cwd": str(tmp_path),
    }
