from __future__ import annotations

import json
from pathlib import Path

import yaml

from conftest import FakeCodex, InstalledCommands, run_process, wait_for_file
from test_agent_runner_batch import configure_harness


def _register_ready_ticket(
    installed_commands: InstalledCommands,
    harness_root: Path,
) -> None:
    ticket = harness_root / "ticket.yml"
    ticket.write_text(
        yaml.safe_dump(
            {
                "ticket_id": "76",
                "ticket_name": "session-alias-control",
                "source": "https://github.com/example/project/issues/76",
                "title": "Session alias control",
                "body": "Deliver the accepted Session transport behavior.",
                "dependencies": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    registered = run_process(
        [
            str(installed_commands.product),
            "ticket",
            "register",
            "--ticket-file",
            str(ticket),
        ],
        cwd=harness_root,
    )
    assert registered.returncode == 0, registered.stderr

    readiness = harness_root / "readiness.md"
    readiness.write_text("The Ticket is ready.\n", encoding="utf-8")
    state = harness_root / "state.yml"
    state.write_text(
        yaml.safe_dump(
            {
                "ticket_id": "76",
                "status": "ready",
                "active_team_ordinal": None,
                "worktree": None,
                "branch": None,
                "current_candidate": None,
                "caused_by_event_ids": [],
                "evidence_refs": ["readiness.md"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ready = run_process(
        [
            str(installed_commands.product),
            "ticket",
            "update",
            "--state-file",
            str(state),
        ],
        cwd=harness_root,
    )
    assert ready.returncode == 0, ready.stderr


def test_installed_alias_control_resumes_and_interrupts_one_team_session(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root, worktree_root, _, environment = configure_harness(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    send_help = run_process(
        [str(installed_commands.runner), "send", "--help"],
        cwd=harness_root,
        env=environment,
    )
    assert send_help.returncode == 0
    assert "--caused-by-event-id" in send_help.stdout
    assert "--caused-by-worldline-seq" not in send_help.stdout
    _register_ready_ticket(installed_commands, harness_root)
    batch = harness_root / "batch.yml"
    batch.write_text(
        "tasks:\n"
        "  - ticket_id: \"76\"\n"
        "    ticket_name: session-alias-control\n"
        "    role: team-leader\n",
        encoding="utf-8",
    )
    launched = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch)],
        cwd=harness_root,
        env={
            **environment,
            "FAKE_CODEX_LIFECYCLE_ACTION": "complete-team-round",
            "GRAPHTRAJ_AGENT_RUNNER": str(installed_commands.runner),
        },
        timeout=15,
    )
    assert launched.returncode == 0, launched.stderr

    session_root = harness_root / ".codex" / "agent-runner" / "sessions"
    mapping_file = next(
        path
        for path in session_root.glob("*/mapping.yml")
        if yaml.safe_load(path.read_text(encoding="utf-8"))["role"] == "team-leader"
    )
    mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
    alias = mapping["alias"]
    session = mapping["session"]
    ticket_directory = (
        harness_root / ".graphtraj" / "state" / "tickets" / "76-session-alias-control"
    )
    trace = ticket_directory / "teams" / "1" / "traces" / alias / "events.jsonl"
    trace_before = trace.read_text(encoding="utf-8")
    worldline = [
        json.loads(line)
        for shard in (harness_root / ".graphtraj" / "state" / "worldline").glob("*.jsonl")
        for line in shard.read_text(encoding="utf-8").splitlines()
    ]
    cause = worldline[-1]["event_id"]
    release = tmp_path / "allow-resumed-session-to-finish"
    config_file = harness_root / ".graphtraj" / "config.yml"
    config = yaml.safe_load(config_file.read_text())
    config["agent_runner"]["max_concurrency"] = 1
    config_file.write_text(yaml.safe_dump(config))
    peer_mapping_file = next(
        path for path in session_root.glob("*/mapping.yml")
        if yaml.safe_load(path.read_text())["role"].startswith("engineer-")
    )
    peer_alias = yaml.safe_load(peer_mapping_file.read_text())["alias"]

    resumed = run_process(
        [
            str(installed_commands.runner),
            "send",
            alias,
            "--instruction",
            "Inspect the accepted candidate again.",
            "--caused-by-event-id",
            cause,
        ],
        cwd=harness_root,
        env={
            **environment,
            "FAKE_CODEX_EVENTS": json.dumps(
                [{"type": "thread.started", "thread_id": session}]
            ),
            "FAKE_CODEX_RELEASE_FILE": str(release),
        },
        timeout=10,
    )

    assert resumed.returncode == 0, resumed.stderr
    assert yaml.safe_load(resumed.stdout) == {"alias": alias, "send_status": "sent"}
    running = run_process(
        [str(installed_commands.runner), "status", alias],
        cwd=harness_root,
        env=environment,
    )
    assert running.returncode == 0, running.stderr
    assert yaml.safe_load(running.stdout) == {
        "aliases": [
            {
                "alias": alias,
                "activity": "running",
                "last_outcome": "completed",
            }
        ]
    }

    unsupported = run_process(
        [
            str(installed_commands.runner),
            "send",
            alias,
            "--instruction",
            "Do not queue this follow-up.",
            "--caused-by-event-id",
            cause,
        ],
        cwd=harness_root,
        env=environment,
    )
    assert unsupported.returncode == 1
    assert yaml.safe_load(unsupported.stdout)["error"]["code"] == "live-input-unsupported"

    peer_before = peer_mapping_file.read_text()
    denied = run_process(
        [str(installed_commands.runner), "send", peer_alias,
         "--instruction", "Inspect the candidate.", "--caused-by-event-id", cause],
        cwd=harness_root, env=environment,
    )
    assert denied.returncode == 1
    assert yaml.safe_load(denied.stdout)["error"]["code"] == "insufficient-capacity"
    assert peer_mapping_file.read_text() == peer_before
    denied_batch = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch)],
        cwd=harness_root, env=environment,
    )
    assert denied_batch.returncode == 1
    assert yaml.safe_load(denied_batch.stdout)["error"]["code"] == "insufficient-capacity"

    interrupted = run_process(
        [str(installed_commands.runner), "interrupt", alias],
        cwd=harness_root,
        env=environment,
        timeout=10,
    )
    assert interrupted.returncode == 0, interrupted.stderr
    assert yaml.safe_load(interrupted.stdout) == {
        "alias": alias,
        "interrupt_status": "interrupted",
    }
    wait_for_file(mapping_file.parent / "execution.yml")
    retry = run_process(
        [str(installed_commands.runner), "send", peer_alias,
         "--instruction", "Inspect the candidate.", "--caused-by-event-id", cause],
        cwd=harness_root, env=environment,
    )
    assert retry.returncode == 0, retry.stdout + retry.stderr
    idle = run_process(
        [str(installed_commands.runner), "status", alias],
        cwd=harness_root,
        env=environment,
    )
    assert idle.returncode == 0, idle.stderr
    assert yaml.safe_load(idle.stdout) == {
        "aliases": [
            {
                "alias": alias,
                "activity": "idle",
                "last_outcome": "interrupted",
            }
        ]
    }
    assert trace.read_text(encoding="utf-8") != trace_before
    assert cause in trace.read_text(encoding="utf-8")
    resumed_mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
    assert resumed_mapping["alias"] == alias
    assert resumed_mapping["session"] == session
    assert (worktree_root / "76-session-alias-control").is_dir()
    assert "run_id" not in resumed_mapping
    assert "turn" not in resumed_mapping
    assert not list((ticket_directory / "teams" / "1" / "traces" / alias).glob("turn-*"))
