from __future__ import annotations

import json
from pathlib import Path

import yaml

from conftest import FakeCodex, InstalledCommands, run_process, wait_for_file
from runner_fixtures import configure_harness


def _register_ready_ticket(
    installed_commands: InstalledCommands,
    harness_root: Path,
    *,
    body: str = "Deliver the accepted Session transport behavior.",
) -> None:
    ticket = harness_root / "ticket.yml"
    ticket.write_text(
        yaml.safe_dump(
            {
                "ticket_id": "76",
                "ticket_name": "session-alias-control",
                "source": "https://github.com/example/project/issues/76",
                "title": "Session alias control",
                "body": body,
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

    session_root = harness_root / ".graphtraj" / "runner" / "sessions"
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
    team_file = ticket_directory / "teams" / "1" / "team.yml"
    team = yaml.safe_load(team_file.read_text(encoding="utf-8"))
    team["current_round"] = 2
    team_file.write_text(yaml.safe_dump(team), encoding="utf-8")
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

    policy_log = tmp_path / "resumed-policy.jsonl"
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
                [{"type": "thread.started", "thread_id": session}, {"type": "turn.started"}]
            ),
            "FAKE_CODEX_RELEASE_FILE": str(release),
            "FAKE_CODEX_POLICY_LOG": str(policy_log),
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

    wait_for_file(policy_log)
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
    policy = json.loads(policy_log.read_text().splitlines()[0])
    assert policy["round"] == "2"
    assert policy["settings"]["agents"]["enabled"] is True
    filesystem = policy["settings"]["permissions"][
        policy["settings"]["default_permissions"]
    ]["filesystem"]
    report_writes = {
        path
        for path, access in filesystem.items()
        if access == "write"
        and (
            path.startswith(str(ticket_directory / "teams"))
            or path.startswith(str(worktree_root / "76-session-alias-control" / ".state" / "teams"))
        )
    }
    report = ticket_directory / "teams" / "1" / "rounds" / "2" / "leader.md"
    assert report_writes == {str(report)}
    assert "hooks" not in policy["settings"]
    assert (worktree_root / "76-session-alias-control").is_dir()
    assert "run_id" not in resumed_mapping
    assert "turn" not in resumed_mapping
    assert not list((ticket_directory / "teams" / "1" / "traces" / alias).glob("turn-*"))


def test_installed_status_reports_native_requests_and_commit_diff(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root, _, integration, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    baseline = run_process(["git", "rev-parse", "HEAD"], cwd=integration).stdout.strip()
    (integration / "README.md").write_text("# Changed target project\n", encoding="utf-8")
    (integration / "added.txt").write_text("added\n", encoding="utf-8")
    (integration / "binary.bin").write_bytes(b"\0")
    run_process(["git", "add", "."], cwd=integration).check_returncode()
    run_process(
        ["git", "commit", "-m", "Known diagnostic change"], cwd=integration,
    ).check_returncode()
    candidate = run_process(["git", "rev-parse", "HEAD"], cwd=integration).stdout.strip()

    alias = "diagnostics@e1"
    session_directory = harness_root / ".graphtraj" / "runner" / "sessions" / alias
    session_directory.mkdir(parents=True)
    trace = session_directory / "events.jsonl"
    trace.write_text(
        "{\"type\":\"runtime\",\"runtime\":\"codex\"}\n"
        "{\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"assistant\"}}\n"
        "{\"type\":\"response_item\",\"payload\":{\"type\":\"custom_tool_call\",\"call_id\":\"call-exec\",\"name\":\"functions.exec\",\"input\":\"{\\\"cmd\\\":\\\"first && second\\\"}\"}}\n"
        "{\"type\":\"response_item\",\"payload\":{\"type\":\"custom_tool_call\",\"call_id\":\"call-exec\",\"name\":\"functions.exec\",\"input\":\"{\\\"cmd\\\":\\\"first && second\\\"}\"}}\n"
        "{\"type\":\"response_item\",\"payload\":{\"type\":\"custom_tool_call_output\",\"call_id\":\"call-exec\"}}\n"
        "{\"type\":\"response_item\",\"payload\":{\"type\":\"function_call\",\"call_id\":\"call-mcp\",\"name\":\"mcp__server__lookup\",\"arguments\":\"{}\"}}\n"
        "{\"type\":\"response_item\",\"payload\":{\"type\":\"custom_tool_call\",\"call_id\":\"call-edit\",\"name\":\"apply_patch\",\"input\":\"*** Begin Patch\"}}\n"
        "{\"type\":\"response_item\",\"payload\":{\"type\":\"custom_tool_call\",\"call_id\":\"call-failed\",\"name\":\"functions.exec\",\"input\":\"{\\\"cmd\\\":\\\"false\\\"}\"}}\n"
        "{\"type\":\"response_item\",\"payload\":{\"type\":\"custom_tool_call_output\",\"call_id\":\"call-failed\",\"output\":\"failed\"}}\n"
        "{\"type\":\"response_item\",\"payload\":{\"type\":\"local_shell_call\",\"id\":\"legacy-shell\",\"status\":\"completed\",\"action\":{\"type\":\"exec\",\"command\":[\"pwd\"]}}}\n"
        "{\"type\":\"response_item\",\"payload\":{\"type\":\"tool_search_call\",\"call_id\":\"call-tool-search\",\"execution\":\"completed\",\"arguments\":\"status\"}}\n"
        "{\"type\":\"response_item\",\"payload\":{\"type\":\"web_search_call\",\"id\":\"web-search\",\"status\":\"completed\",\"action\":{\"type\":\"search\",\"query\":\"Codex protocol\"}}}\n"
        "{\"type\":\"response_item\",\"payload\":{\"type\":\"image_generation_call\",\"id\":\"image-generation\",\"status\":\"completed\",\"result\":\"generated\"}}\n"
        "{\"type\":\"event_msg\",\"payload\":{\"type\":\"item_started\",\"item\":{\"type\":\"CommandExecution\",\"command\":\"first && second\"}}}\n"
        "{\"type\":\"event_msg\",\"payload\":{\"type\":\"item_completed\",\"item\":{\"type\":\"CommandExecution\",\"command\":\"first && second\",\"exit_code\":1}}}\n"
        "{\"type\":\"event_msg\",\"payload\":{\"type\":\"item_completed\",\"item\":{\"type\":\"FileChange\",\"path\":\"added.txt\"}}}\n",
        encoding="utf-8",
    )
    (session_directory / "execution.yml").write_text("outcome: completed\n", encoding="utf-8")
    (session_directory / "mapping.yml").write_text(
        yaml.safe_dump(
            {
                "alias": alias,
                "runtime": "codex",
                "session": "native-session",
                "ticket_id": "96",
                "team_generation": 1,
                "role": "engineer-senior",
                "parent": None,
                "retained_batch_file": "batch.yml",
                "worktree_path": str(integration),
                "trace_file": str(trace),
                "worker_pid": 1,
                "runtime_pid": 1,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = run_process(
        [
            str(installed_commands.runner), "status", "--operation-total",
            "--baseline", baseline, "--candidate", candidate, alias,
        ],
        cwd=harness_root,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(result.stdout) == {
        "aliases": [
            {
                "alias": alias,
                "activity": "idle",
                "last_outcome": "completed",
                "operation_total": 8,
                "diff": {
                    "baseline": baseline,
                    "candidate": candidate,
                    "files": [
                        {"path": "README.md", "additions": 1, "deletions": 1},
                        {"path": "added.txt", "additions": 1, "deletions": 0},
                        {"path": "binary.bin", "additions": None, "deletions": None},
                    ],
                },
            }
        ]
    }
