from __future__ import annotations

import json
from pathlib import Path

import yaml

from conftest import FakeCodex, InstalledCommands, run_process
from test_agent_runner_status import (
    configured_runner,
    installed_worktree_commands,
    launch_turn,
    status,
    wait_for_file,
    wait_for_process_exit,
)


def send(
    installed_commands: InstalledCommands,
    integration: Path,
    environment: dict[str, str],
    alias: str,
    instruction: str,
):
    return run_process(
        [
            str(installed_commands.runner),
            "send",
            alias,
            "--instruction",
            instruction,
        ],
        cwd=integration,
        env=environment,
        timeout=5,
    )


def interrupt(
    installed_commands: InstalledCommands,
    integration: Path,
    environment: dict[str, str],
    alias: str,
):
    return run_process(
        [str(installed_commands.runner), "interrupt", alias],
        cwd=integration,
        env=environment,
        timeout=10,
    )


def test_installed_send_resumes_an_idle_runtime_session_under_the_same_alias(
    installed_worktree_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    (
        harness_root,
        integration,
        runner_directory,
        _,
        environment,
    ) = configured_runner(
        installed_worktree_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    session = "thread-10"
    alias, _ = launch_turn(
        installed_worktree_commands,
        harness_root,
        integration,
        {
            **environment,
            "FAKE_CODEX_EVENTS": json.dumps(
                [{"type": "thread.started", "thread_id": session}]
            ),
        },
        ticket_id="10",
        ticket_name="resume-engineer",
        role="engineer-expert",
        run_id="20260814-resume-engineer",
    )
    session_directory = runner_directory / "sessions" / alias
    turn_file = session_directory / "turn.yml"
    wait_for_file(turn_file)
    original_mapping = yaml.safe_load(
        (session_directory / "mapping.yml").read_text(encoding="utf-8")
    )
    original_runtime_record = json.loads(
        fake_codex.log_file.read_text(encoding="utf-8")
    )
    wait_for_process_exit(original_mapping["worker_pid"])
    resume_release = tmp_path / "allow-resumed-turn-to-finish"
    instruction = "Re-run the focused process test, then update the evidence."

    resumed = send(
        installed_worktree_commands,
        integration,
        {
            **environment,
            "FAKE_CODEX_EVENTS": json.dumps(
                [{"type": "thread.started", "thread_id": session}]
            ),
            "FAKE_CODEX_RELEASE_FILE": str(resume_release),
        },
        alias,
        instruction,
    )

    assert resumed.returncode == 0, resumed.stderr
    assert resumed.stderr == ""
    assert yaml.safe_load(resumed.stdout) == {
        "alias": alias,
        "send_status": "sent",
    }
    resumed_mapping = yaml.safe_load(
        (session_directory / "mapping.yml").read_text(encoding="utf-8")
    )
    assert resumed_mapping["alias"] == alias
    assert resumed_mapping["session"] == session
    assert resumed_mapping["worker_pid"] != original_mapping["worker_pid"]
    assert not turn_file.exists()
    running = status(
        installed_worktree_commands,
        integration,
        environment,
        alias,
    )
    assert running.returncode == 0, running.stderr
    assert yaml.safe_load(running.stdout) == {
        "aliases": [{"alias": alias, "activity": "running"}]
    }
    runtime_record = json.loads(fake_codex.log_file.read_text(encoding="utf-8"))
    assert runtime_record == {
        "argv": [
            *original_runtime_record["argv"][:-1],
            "resume",
            session,
            instruction,
        ],
        "cwd": resumed_mapping["worktree_path"],
    }

    resume_release.touch()
    wait_for_file(turn_file)
    wait_for_process_exit(resumed_mapping["worker_pid"])


def test_installed_send_rejects_running_codex_without_deferring_instruction(
    installed_worktree_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    (
        harness_root,
        integration,
        runner_directory,
        _,
        environment,
    ) = configured_runner(
        installed_worktree_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    release_file = tmp_path / "allow-running-turn-to-finish"
    session = "thread-10"
    alias, _ = launch_turn(
        installed_worktree_commands,
        harness_root,
        integration,
        {
            **environment,
            "FAKE_CODEX_EVENTS": json.dumps(
                [{"type": "thread.started", "thread_id": session}]
            ),
            "FAKE_CODEX_RELEASE_FILE": str(release_file),
        },
        ticket_id="10",
        ticket_name="reject-live-input",
        role="engineer-expert",
        run_id="20260814-reject-live-input",
    )
    session_directory = runner_directory / "sessions" / alias
    mapping_file = session_directory / "mapping.yml"
    original_mapping = mapping_file.read_bytes()
    rejected_instruction = "Apply this rejected instruction later."

    rejected = send(
        installed_worktree_commands,
        integration,
        environment,
        alias,
        rejected_instruction,
    )

    guidance = (
        "This Runtime cannot accept input during a running turn. To intervene "
        "immediately, explicitly interrupt the alias and then send the instruction."
    )
    assert rejected.returncode == 1
    assert yaml.safe_load(rejected.stdout) == {
        "alias": alias,
        "error": {"code": "live-input-unsupported", "message": guidance},
    }
    assert rejected.stderr == guidance + "\n"
    assert mapping_file.read_bytes() == original_mapping
    assert not (session_directory / "resume.yml").exists()
    assert rejected_instruction not in "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in session_directory.iterdir()
        if path.is_file()
    )
    still_running = status(
        installed_worktree_commands,
        integration,
        environment,
        alias,
    )
    assert still_running.returncode == 0, still_running.stderr
    assert yaml.safe_load(still_running.stdout) == {
        "aliases": [{"alias": alias, "activity": "running"}]
    }

    stopped = interrupt(
        installed_worktree_commands,
        integration,
        environment,
        alias,
    )
    assert stopped.returncode == 0, stopped.stderr
    assert yaml.safe_load(stopped.stdout) == {
        "alias": alias,
        "interrupt_status": "interrupted",
    }
    interrupted_mapping = yaml.safe_load(
        mapping_file.read_text(encoding="utf-8")
    )
    accepted_instruction = "Use only this explicitly accepted follow-up."
    resume_release = tmp_path / "allow-explicit-resume-to-finish"

    accepted = send(
        installed_worktree_commands,
        integration,
        {
            **environment,
            "FAKE_CODEX_EVENTS": json.dumps(
                [{"type": "thread.started", "thread_id": session}]
            ),
            "FAKE_CODEX_RELEASE_FILE": str(resume_release),
        },
        alias,
        accepted_instruction,
    )

    assert accepted.returncode == 0, accepted.stderr
    assert yaml.safe_load(accepted.stdout) == {
        "alias": alias,
        "send_status": "sent",
    }
    resumed_mapping = yaml.safe_load(
        mapping_file.read_text(encoding="utf-8")
    )
    assert resumed_mapping["session"] == session
    assert resumed_mapping["worker_pid"] != interrupted_mapping["worker_pid"]
    runtime_record = fake_codex.log_file.read_text(encoding="utf-8")
    assert accepted_instruction in runtime_record
    assert rejected_instruction not in runtime_record
    assert not release_file.exists()

    resume_release.touch()
    wait_for_file(session_directory / "turn.yml")
    wait_for_process_exit(resumed_mapping["worker_pid"])


def test_installed_interrupt_stops_only_the_addressed_runtime_process_group(
    installed_worktree_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    (
        harness_root,
        integration,
        runner_directory,
        _,
        environment,
    ) = configured_runner(
        installed_worktree_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    first_release = tmp_path / "allow-first-runtime-to-finish"
    second_release = tmp_path / "allow-second-runtime-to-finish"
    first_alias, _ = launch_turn(
        installed_worktree_commands,
        harness_root,
        integration,
        {
            **environment,
            "FAKE_CODEX_EVENTS": json.dumps(
                [{"type": "thread.started", "thread_id": "thread-10"}]
            ),
            "FAKE_CODEX_RELEASE_FILE": str(first_release),
        },
        ticket_id="10",
        ticket_name="interrupt-exact-group",
        role="engineer-expert",
        run_id="20260814-interrupt-exact-group",
    )
    second_alias, _ = launch_turn(
        installed_worktree_commands,
        harness_root,
        integration,
        {
            **environment,
            "FAKE_CODEX_EVENTS": json.dumps(
                [{"type": "thread.started", "thread_id": "thread-11"}]
            ),
            "FAKE_CODEX_RELEASE_FILE": str(second_release),
        },
        ticket_id="11",
        ticket_name="keep-other-group",
        role="engineer-senior",
        run_id="20260814-interrupt-exact-group",
    )
    first_directory = runner_directory / "sessions" / first_alias
    second_directory = runner_directory / "sessions" / second_alias
    first_mapping_file = first_directory / "mapping.yml"
    first_mapping_bytes = first_mapping_file.read_bytes()
    first_mapping = yaml.safe_load(first_mapping_bytes)
    second_mapping = yaml.safe_load(
        (second_directory / "mapping.yml").read_text(encoding="utf-8")
    )

    try:
        stopped = interrupt(
            installed_worktree_commands,
            integration,
            environment,
            first_alias,
        )

        assert stopped.returncode == 0, stopped.stderr
        assert stopped.stderr == ""
        assert yaml.safe_load(stopped.stdout) == {
            "alias": first_alias,
            "interrupt_status": "interrupted",
        }
        wait_for_file(first_directory / "turn.yml")
        wait_for_process_exit(first_mapping["worker_pid"])
        wait_for_process_exit(first_mapping["runtime_pid"])
        assert first_mapping_file.read_bytes() == first_mapping_bytes
        assert Path(first_mapping["worktree_path"]).is_dir()
        observed = status(
            installed_worktree_commands,
            integration,
            environment,
            first_alias,
            second_alias,
        )
        assert observed.returncode == 0, observed.stderr
        assert yaml.safe_load(observed.stdout) == {
            "aliases": [
                {
                    "alias": first_alias,
                    "activity": "idle",
                    "last_outcome": "interrupted",
                },
                {"alias": second_alias, "activity": "running"},
            ]
        }
        assert not first_release.exists()
        assert not second_release.exists()
    finally:
        first_release.touch()
        second_release.touch()
        wait_for_file(second_directory / "turn.yml")
        wait_for_process_exit(second_mapping["worker_pid"])


def test_launch_and_idle_send_share_ticket_worktree_exclusivity(
    installed_worktree_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    (
        harness_root,
        integration,
        runner_directory,
        _,
        environment,
    ) = configured_runner(
        installed_worktree_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    run_id = "20260814-worktree-exclusivity"
    first_alias, _ = launch_turn(
        installed_worktree_commands,
        harness_root,
        integration,
        environment,
        ticket_id="10",
        ticket_name="exclusive-writer",
        role="engineer-expert",
        run_id=run_id,
    )
    first_directory = runner_directory / "sessions" / first_alias
    wait_for_file(first_directory / "turn.yml")
    first_mapping_file = first_directory / "mapping.yml"
    first_mapping = yaml.safe_load(first_mapping_file.read_text(encoding="utf-8"))
    wait_for_process_exit(first_mapping["worker_pid"])
    second_release = tmp_path / "allow-second-alias-to-finish"
    second_alias, _ = launch_turn(
        installed_worktree_commands,
        harness_root,
        integration,
        {
            **environment,
            "FAKE_CODEX_EVENTS": json.dumps(
                [{"type": "thread.started", "thread_id": "thread-10-second"}]
            ),
            "FAKE_CODEX_RELEASE_FILE": str(second_release),
        },
        ticket_id="10",
        ticket_name="exclusive-writer",
        role="engineer-expert",
        run_id=run_id,
    )
    second_directory = runner_directory / "sessions" / second_alias

    rejected_send = send(
        installed_worktree_commands,
        integration,
        environment,
        first_alias,
        "Do not start beside the second alias.",
    )

    busy_error = {
        "code": "worktree-busy",
        "message": (
            "The Ticket Worktree already has an active Engineer turn under "
            "alias {0}.".format(second_alias)
        ),
    }
    assert rejected_send.returncode == 1
    assert yaml.safe_load(rejected_send.stdout) == {
        "alias": first_alias,
        "error": busy_error,
    }
    assert first_mapping_file.read_bytes() == yaml.safe_dump(
        first_mapping, sort_keys=False
    ).encode()

    second_release.touch()
    wait_for_file(second_directory / "turn.yml")
    second_mapping = yaml.safe_load(
        (second_directory / "mapping.yml").read_text(encoding="utf-8")
    )
    wait_for_process_exit(second_mapping["worker_pid"])
    resume_release = tmp_path / "allow-first-alias-resume-to-finish"
    resumed = send(
        installed_worktree_commands,
        integration,
        {
            **environment,
            "FAKE_CODEX_EVENTS": json.dumps(
                [{"type": "thread.started", "thread_id": "fake-thread"}]
            ),
            "FAKE_CODEX_RELEASE_FILE": str(resume_release),
        },
        first_alias,
        "Resume the first alias exclusively.",
    )
    assert resumed.returncode == 0, resumed.stderr

    rejected_launch = run_process(
        [
            str(installed_worktree_commands.runner),
            "--batch-input",
            str(harness_root / "batch-10.yml"),
        ],
        cwd=integration,
        env=environment,
        timeout=5,
    )

    assert rejected_launch.returncode == 1
    assert yaml.safe_load(rejected_launch.stdout) == {
        "error": {
            "code": "worktree-busy",
            "message": (
                "The Ticket Worktree already has an active Engineer turn under "
                "alias {0}.".format(first_alias)
            ),
        }
    }
    resume_release.touch()
    resumed_mapping = yaml.safe_load(
        first_mapping_file.read_text(encoding="utf-8")
    )
    wait_for_file(first_directory / "turn.yml")
    wait_for_process_exit(resumed_mapping["worker_pid"])


def test_session_operations_return_structured_recovery_errors_without_reidentity(
    installed_worktree_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    (
        harness_root,
        integration,
        runner_directory,
        _,
        environment,
    ) = configured_runner(
        installed_worktree_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    unknown_alias = "2-99-unknown@e1"

    missing_send = send(
        installed_worktree_commands,
        integration,
        environment,
        unknown_alias,
        "Continue.",
    )
    missing_interrupt = interrupt(
        installed_worktree_commands,
        integration,
        environment,
        unknown_alias,
    )

    missing_error = {
        "code": "alias-not-found",
        "message": "The requested Engineer alias was not found.",
    }
    assert missing_send.returncode == 1
    assert yaml.safe_load(missing_send.stdout) == {
        "alias": unknown_alias,
        "error": missing_error,
    }
    assert missing_interrupt.returncode == 1
    assert yaml.safe_load(missing_interrupt.stdout) == {
        "alias": unknown_alias,
        "error": missing_error,
    }

    corrupt_alias, _ = launch_turn(
        installed_worktree_commands,
        harness_root,
        integration,
        environment,
        ticket_id="10",
        ticket_name="corrupt-session",
        role="engineer-expert",
        run_id="20260814-recovery-errors",
    )
    corrupt_directory = runner_directory / "sessions" / corrupt_alias
    wait_for_file(corrupt_directory / "turn.yml")
    corrupt_mapping = corrupt_directory / "mapping.yml"
    corrupt_document = yaml.safe_load(corrupt_mapping.read_text(encoding="utf-8"))
    corrupt_worker = corrupt_document["worker_pid"]
    wait_for_process_exit(corrupt_worker)
    corrupt_document["session"] = "replacement-thread"
    corrupt_mapping.write_text(
        yaml.safe_dump(corrupt_document, sort_keys=False), encoding="utf-8"
    )
    runtime_before_corrupt_send = fake_codex.log_file.read_bytes()

    corrupt = send(
        installed_worktree_commands,
        integration,
        environment,
        corrupt_alias,
        "Continue.",
    )

    assert corrupt.returncode == 1
    assert yaml.safe_load(corrupt.stdout) == {
        "alias": corrupt_alias,
        "error": {
            "code": "operation-failed",
            "message": "The requested Engineer alias mapping is invalid.",
        },
    }
    assert fake_codex.log_file.read_bytes() == runtime_before_corrupt_send

    lost_alias, _ = launch_turn(
        installed_worktree_commands,
        harness_root,
        integration,
        {
            **environment,
            "FAKE_CODEX_EVENTS": json.dumps(
                [{"type": "thread.started", "thread_id": "thread-11"}]
            ),
        },
        ticket_id="11",
        ticket_name="lost-session",
        role="engineer-senior",
        run_id="20260814-recovery-errors",
    )
    lost_directory = runner_directory / "sessions" / lost_alias
    lost_turn = lost_directory / "turn.yml"
    wait_for_file(lost_turn)
    lost_mapping_file = lost_directory / "mapping.yml"
    lost_mapping_bytes = lost_mapping_file.read_bytes()
    lost_mapping = yaml.safe_load(lost_mapping_bytes)
    wait_for_process_exit(lost_mapping["worker_pid"])
    aliases_before = sorted(
        path.name for path in (runner_directory / "sessions").iterdir()
    )

    lost = send(
        installed_worktree_commands,
        integration,
        {
            **environment,
            "FAKE_CODEX_EVENTS": json.dumps(
                [{"type": "thread.started", "thread_id": "replacement-thread"}]
            ),
        },
        lost_alias,
        "Do not reconstruct me under another identity.",
    )

    not_resumable = {
        "code": "session-not-resumable",
        "message": "The mapped Runtime session is unavailable or cannot be resumed.",
    }
    assert lost.returncode == 1
    assert yaml.safe_load(lost.stdout) == {
        "alias": lost_alias,
        "error": not_resumable,
    }
    assert lost_mapping_file.read_bytes() == lost_mapping_bytes
    assert yaml.safe_load(lost_turn.read_text(encoding="utf-8")) == {
        "outcome": "completed",
        "runtime_exit_code": 0,
    }
    assert sorted(
        path.name for path in (runner_directory / "sessions").iterdir()
    ) == aliases_before
    assert list((runner_directory / "active-worktrees").iterdir()) == []

    non_resumable_alias, _ = launch_turn(
        installed_worktree_commands,
        harness_root,
        integration,
        environment,
        ticket_id="12",
        ticket_name="non-resumable-state",
        role="engineer-junior",
        run_id="20260814-recovery-errors",
    )
    non_resumable_directory = runner_directory / "sessions" / non_resumable_alias
    wait_for_file(non_resumable_directory / "turn.yml")
    non_resumable_mapping = yaml.safe_load(
        (non_resumable_directory / "mapping.yml").read_text(encoding="utf-8")
    )
    wait_for_process_exit(non_resumable_mapping["worker_pid"])
    (non_resumable_directory / "launch.yml").unlink()

    non_resumable = send(
        installed_worktree_commands,
        integration,
        environment,
        non_resumable_alias,
        "Continue.",
    )

    assert non_resumable.returncode == 1
    assert yaml.safe_load(non_resumable.stdout) == {
        "alias": non_resumable_alias,
        "error": not_resumable,
    }
    assert list((runner_directory / "active-worktrees").iterdir()) == []
