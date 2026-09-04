from __future__ import annotations

import json
from pathlib import Path

import yaml

from conftest import FakeCodex, InstalledCommands, run_process
from test_agent_runner_status import (
    configured_runner,
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
    caused_by_worldline_seq: int = 1,
):
    return run_process(
        [
            str(installed_commands.runner),
            "send",
            alias,
            "--instruction",
            instruction,
            "--caused-by-worldline-seq",
            str(caused_by_worldline_seq),
        ],
        cwd=integration.parent.parent.parent,
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
        cwd=integration.parent.parent.parent,
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
    (harness_root / ".codex" / "agents" / "engineer-expert.toml").write_text(
        'name = "changed-after-launch"\n', encoding="utf-8"
    )
    source_config = (
        Path(original_mapping["worktree_path"]) / ".codex" / "config.toml"
    )
    source_config.parent.mkdir()
    source_config.write_text('model = "source-changed"\n', encoding="utf-8")
    resume_release = tmp_path / "allow-resumed-turn-to-finish"
    instruction = "--dangerously-bypass-approvals-and-sandbox"
    run_root = (
        harness_root / ".graphtraj" / "state" / "20260814-resume-engineer"
    )
    decision_file = harness_root / "resume-decision.yml"
    decision_file.write_text(
        yaml.safe_dump(
            {
                "kind": "main-decision",
                "ticket_id": "10",
                "accepted_findings": [],
                "rejected_findings": [],
                "verdict": "FAIL",
                "caused_by_worldline_seqs": [2],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    decision = run_process(
        [
            str(installed_worktree_commands.product),
            "worldline",
            "append",
            "--run-root",
            str(run_root),
            "--run-id",
            "20260814-resume-engineer",
            "--event-file",
            str(decision_file),
        ],
        cwd=harness_root,
        env=environment,
    )
    assert decision.returncode == 0, decision.stderr
    decision_seq = yaml.safe_load(decision.stdout)["worldline_seq"]

    resumed = send(
        installed_worktree_commands,
        integration,
        {
            **environment,
            "FAKE_CODEX_EVENTS": json.dumps(
                [{"type": "thread.started", "thread_id": session}]
            ),
            "FAKE_CODEX_CAPTURE_STDIN": "1",
            "FAKE_CODEX_RELEASE_FILE": str(resume_release),
        },
        alias,
        instruction,
        decision_seq,
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
            "-",
        ],
        "cwd": resumed_mapping["worktree_path"],
        "stdin": instruction,
    }

    resume_release.touch()
    wait_for_file(turn_file)
    wait_for_process_exit(resumed_mapping["worker_pid"])
    worldline = [
        json.loads(line)
        for line in (run_root / "worldline.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    turn_two_start = next(
        event
        for event in worldline
        if event["kind"] == "agent-turn-start" and event["turn"] == 2
    )
    assert turn_two_start["caused_by_worldline_seqs"] == [decision_seq]


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
            "FAKE_CODEX_CAPTURE_STDIN": "1",
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
    runtime_record = json.loads(fake_codex.log_file.read_text(encoding="utf-8"))
    assert runtime_record["stdin"] == accepted_instruction
    assert rejected_instruction not in runtime_record["stdin"]

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
    group_child_pid_file = tmp_path / "addressed-group-child.pid"
    group_child_release = tmp_path / "allow-addressed-group-child-to-finish"
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
            "FAKE_CODEX_GROUP_CHILD_PID": str(group_child_pid_file),
            "FAKE_CODEX_GROUP_CHILD_RELEASE": str(group_child_release),
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
    wait_for_file(group_child_pid_file)
    group_child_pid = int(group_child_pid_file.read_text(encoding="utf-8"))

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
        wait_for_process_exit(group_child_pid, timeout=7)
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
    finally:
        group_child_release.touch()
        first_release.touch()
        second_release.touch()
        wait_for_file(second_directory / "turn.yml")
        wait_for_process_exit(second_mapping["worker_pid"])


def test_installed_interrupt_is_alias_local_for_shared_reviewer_reservation(
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
    standards_release = tmp_path / "allow-standards-to-finish"
    spec_release = tmp_path / "allow-spec-to-finish"
    common = {
        "ticket_id": "60",
        "ticket_name": "parallel-review",
        "run_id": "20260829-parallel-review",
    }
    standards_alias, _ = launch_turn(
        installed_worktree_commands,
        harness_root,
        integration,
        {
            **environment,
            "FAKE_CODEX_EVENTS": json.dumps(
                [{"type": "thread.started", "thread_id": "standards-thread"}]
            ),
            "FAKE_CODEX_RELEASE_FILE": str(standards_release),
        },
        role="standards-reviewer",
        **common,
    )
    spec_alias, _ = launch_turn(
        installed_worktree_commands,
        harness_root,
        integration,
        {
            **environment,
            "FAKE_CODEX_EVENTS": json.dumps(
                [{"type": "thread.started", "thread_id": "spec-thread"}]
            ),
            "FAKE_CODEX_RELEASE_FILE": str(spec_release),
        },
        role="spec-reviewer",
        **common,
    )
    try:
        stopped = interrupt(
            installed_worktree_commands,
            integration,
            environment,
            standards_alias,
        )

        assert stopped.returncode == 0, stopped.stderr
        interruption = yaml.safe_load(stopped.stdout)
        assert interruption["alias"] == standards_alias
        assert interruption["interrupt_status"] == "interrupted"
        sibling = status(
            installed_worktree_commands,
            integration,
            environment,
            spec_alias,
        )
        assert sibling.returncode == 0, sibling.stderr
        sibling_status = yaml.safe_load(sibling.stdout)["aliases"]
        assert sibling_status[0]["alias"] == spec_alias
        assert sibling_status[0]["activity"] == "running"
    finally:
        standards_release.touch()
        spec_release.touch()
        wait_for_file(runner_directory / "sessions" / spec_alias / "turn.yml")


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
        cwd=harness_root,
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

    assert missing_send.returncode == 1
    missing_send_error = yaml.safe_load(missing_send.stdout)
    assert missing_send_error["alias"] == unknown_alias
    assert missing_send_error["error"]["code"] == "alias-not-found"
    assert missing_interrupt.returncode == 1
    missing_interrupt_error = yaml.safe_load(missing_interrupt.stdout)
    assert missing_interrupt_error["alias"] == unknown_alias
    assert missing_interrupt_error["error"]["code"] == "alias-not-found"

    alias, _ = launch_turn(
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
    wait_for_file(runner_directory / "sessions" / alias / "turn.yml")

    lost = send(
        installed_worktree_commands,
        integration,
        {
            **environment,
            "FAKE_CODEX_EVENTS": json.dumps(
                [{"type": "thread.started", "thread_id": "replacement-thread"}]
            ),
        },
        alias,
        "Do not reconstruct me under another identity.",
    )

    assert lost.returncode == 1
    lost_error = yaml.safe_load(lost.stdout)
    assert lost_error["alias"] == alias
    assert lost_error["error"]["code"] == "session-not-resumable"
    observed = status(installed_worktree_commands, integration, environment, alias)
    assert observed.returncode == 0, observed.stderr
    alias_status = yaml.safe_load(observed.stdout)["aliases"]
    assert alias_status[0]["alias"] == alias
    assert alias_status[0]["activity"] == "idle"


def test_idle_send_reuses_the_persisted_request_after_runtime_store_changes(
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
    alias, _ = launch_turn(
        installed_worktree_commands,
        harness_root,
        integration,
        environment,
        ticket_id="20",
        ticket_name="revalidate-codex-safety",
        role="engineer-expert",
        run_id="20260814-revalidate-codex-safety",
    )
    session_directory = runner_directory / "sessions" / alias
    wait_for_file(session_directory / "turn.yml")
    mapping = yaml.safe_load(
        (session_directory / "mapping.yml").read_text(encoding="utf-8")
    )
    wait_for_process_exit(mapping["worker_pid"])
    initial_request = json.loads(fake_codex.log_file.read_text(encoding="utf-8"))
    runtime_store = harness_root / ".codex"

    for relative_path in (
        Path("hooks/worktree_guard.py"),
        Path("config.toml"),
    ):
        protected_file = runtime_store / relative_path
        original = protected_file.read_bytes()
        protected_file.write_bytes(original + b"\n# changed after launch\n")
        try:
            resumed = send(
                installed_worktree_commands,
                integration,
                environment,
                alias,
                "Reuse the persisted launch request.",
            )
        finally:
            protected_file.write_bytes(original)

        assert resumed.returncode == 0, resumed.stderr
        assert yaml.safe_load(resumed.stdout) == {
            "alias": alias,
            "send_status": "sent",
        }
        wait_for_file(session_directory / "turn.yml")
        resumed_request = json.loads(fake_codex.log_file.read_text(encoding="utf-8"))
        assert resumed_request == {
            "argv": [
                *initial_request["argv"][:-1],
                "resume",
                mapping["session"],
                "-",
            ],
            "cwd": mapping["worktree_path"],
        }


def test_idle_send_rejects_detached_or_rebranched_mapped_worktree(
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
    alias, _ = launch_turn(
        installed_worktree_commands,
        harness_root,
        integration,
        environment,
        ticket_id="21",
        ticket_name="validate-recovery-worktree",
        role="engineer-senior",
        run_id="20260814-validate-recovery-worktree",
    )
    session_directory = runner_directory / "sessions" / alias
    wait_for_file(session_directory / "turn.yml")
    mapping = yaml.safe_load(
        (session_directory / "mapping.yml").read_text(encoding="utf-8")
    )
    wait_for_process_exit(mapping["worker_pid"])
    worktree = Path(mapping["worktree_path"])
    runtime_before = fake_codex.log_file.read_bytes()
    invalid_mapping = {
        "code": "operation-failed",
        "message": "The requested Engineer alias mapping is invalid.",
    }

    run_process(["git", "switch", "--detach"], cwd=worktree).check_returncode()
    detached = send(
        installed_worktree_commands,
        integration,
        environment,
        alias,
        "Do not resume a detached Worktree.",
    )
    assert detached.returncode == 1
    assert yaml.safe_load(detached.stdout) == {
        "alias": alias,
        "error": invalid_mapping,
    }

    run_process(
        ["git", "switch", "-c", "unexpected-recovery-branch"], cwd=worktree
    ).check_returncode()
    rebranched = send(
        installed_worktree_commands,
        integration,
        environment,
        alias,
        "Do not resume a rebranched Worktree.",
    )
    assert rebranched.returncode == 1
    assert yaml.safe_load(rebranched.stdout) == {
        "alias": alias,
        "error": invalid_mapping,
    }
    assert fake_codex.log_file.read_bytes() == runtime_before
