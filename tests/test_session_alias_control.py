from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import yaml

from conftest import app_server_peer, FakeCodex, InstalledCommands, run_process, wait_for_file
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
    harness_root, worktree_root, integration, environment = configure_harness(
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
        [str(installed_commands.runner), "--swarm-input", str(batch)],
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
    # The first Team names the Ticket, handover0, the configured role and the
    # entity for every Session it starts.
    assert alias == "76-session_alias_control-handover0-team_leader@team_leader"
    assert all(
        yaml.safe_load(path.read_text(encoding="utf-8"))["alias"].startswith(
            "76-session_alias_control-handover0-"
        )
        for path in session_root.glob("*/mapping.yml")
    )
    ticket_directory = (
        harness_root / ".graphtraj" / "state" / "tickets" / "76-session-alias-control"
    )
    team_file = ticket_directory / "teams" / "1" / "team.yml"
    team = yaml.safe_load(team_file.read_text(encoding="utf-8"))
    team["current_round"] = 2
    team_file.write_text(yaml.safe_dump(team), encoding="utf-8")
    trace = ticket_directory / "teams" / "1" / "traces" / alias / "events.jsonl"
    session_records = mapping_file.parent / "events.jsonl"
    records_before = session_records.read_text(encoding="utf-8")
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
        if yaml.safe_load(path.read_text())["role"] == "engineer"
    )
    peer_alias = yaml.safe_load(peer_mapping_file.read_text())["alias"]
    (integration / "other-ticket-in-progress.txt").write_text(
        "temporary work from another Ticket\n", encoding="utf-8"
    )

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
    resumed_document = yaml.safe_load(resumed.stdout)
    assert resumed_document["alias"] == alias
    assert resumed_document["session"] == session
    assert resumed_document["send_status"] == "sent"
    running = run_process(
        [str(installed_commands.runner), "status", alias],
        cwd=harness_root,
        env=environment,
    )
    assert running.returncode == 0, running.stderr
    running_status = yaml.safe_load(running.stdout)
    assert running_status["aliases"][0].pop("session") == session
    native_execution = running_status["aliases"][0].pop("execution_id")
    assert native_execution
    # The continuation reported the execution the resumed Worker recorded.
    assert resumed_document["execution_id"] == native_execution
    assert running_status == {
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
    assert unsupported.returncode == 0, unsupported.stdout + unsupported.stderr
    # A live execution receives the input: no second execution is started.
    assert yaml.safe_load(unsupported.stdout) == {
        "alias": alias,
        "session": session,
        "execution_id": native_execution,
        "send_status": "sent",
    }

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
        [str(installed_commands.runner), "--swarm-input", str(batch)],
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
    idle_status = yaml.safe_load(idle.stdout)
    assert idle_status["aliases"][0].pop("session") == session
    assert idle_status["aliases"][0].pop("execution_id") == native_execution
    assert idle_status == {
        "aliases": [
            {
                "alias": alias,
                "activity": "idle",
                "last_outcome": "interrupted",
            }
        ]
    }
    # The Runner records the follow-up cause in the Session's own records,
    # while the Trace entry keeps reading the Runtime-owned Session file.
    assert session_records.read_text(encoding="utf-8") != records_before
    assert cause in session_records.read_text(encoding="utf-8")
    assert trace.is_symlink()
    assert Path(os.readlink(trace)) == Path(
        yaml.safe_load((mapping_file.parent / "session.yml").read_text())["rollout_path"]
    )
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


def test_installed_runner_keeps_clean_dev_requirement_for_new_ticket_worktree(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root, worktree_root, integration, environment = configure_harness(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    _register_ready_ticket(installed_commands, harness_root)
    (integration / "other-ticket-in-progress.txt").write_text(
        "temporary work from another Ticket\n", encoding="utf-8"
    )
    batch = harness_root / "batch.yml"
    batch.write_text(
        "tasks:\n"
        "  - ticket_id: \"76\"\n"
        "    ticket_name: session-alias-control\n"
        "    role: team-leader\n",
        encoding="utf-8",
    )

    launched = run_process(
        [str(installed_commands.runner), "--swarm-input", str(batch)],
        cwd=harness_root,
        env=environment,
        timeout=15,
    )

    assert launched.returncode == 1
    response = yaml.safe_load(launched.stdout)
    error = response.get("error") or response["tasks"][0]["error"]
    assert error["code"] == "integration-not-ready"
    state = yaml.safe_load(
        (
            harness_root
            / ".graphtraj/state/tickets/76-session-alias-control/ticket.yml"
        ).read_text(encoding="utf-8")
    )
    assert state["status"] == "ready"
    assert state["worktree"] is None
    assert not (worktree_root / "76-session-alias-control").exists()


def test_installed_send_resumes_an_unregistered_leader_session(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root, _, integration, environment = configure_harness(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
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
        [str(installed_commands.runner), "--swarm-input", str(batch)],
        cwd=harness_root,
        env=environment,
        timeout=15,
    )

    assert launched.returncode == 1
    mapping_file = next(
        path
        for path in (harness_root / ".graphtraj" / "runner" / "sessions").glob(
            "*/mapping.yml"
        )
        if yaml.safe_load(path.read_text(encoding="utf-8"))["role"] == "team-leader"
    )
    mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
    ticket = harness_root / ".graphtraj" / "state" / "tickets" / "76-session-alias-control"
    assert not (ticket / "teams" / "1" / "team.yml").exists()
    launch_before = (mapping_file.parent / "launch.yml").read_bytes()
    execution = mapping_file.parent / "execution.yml"
    cause = [
        json.loads(line)["event_id"]
        for shard in (harness_root / ".graphtraj" / "state" / "worldline").glob(
            "*.jsonl"
        )
        for line in shard.read_text(encoding="utf-8").splitlines()
    ][-1]
    (integration / "other-ticket-in-progress.txt").write_text(
        "temporary work from another Ticket\n", encoding="utf-8"
    )

    resumed = run_process(
        [
            str(installed_commands.runner),
            "send",
            mapping["alias"],
            "--instruction",
            "Register the first Engineer child Batch.",
            "--caused-by-event-id",
            cause,
        ],
        cwd=harness_root,
        env={
            **environment,
            "FAKE_CODEX_LIFECYCLE_ACTION": "complete-team-round",
            "FAKE_CODEX_RELEASE_FILE": str(tmp_path / "resume-release"),
            "GRAPHTRAJ_AGENT_RUNNER": str(installed_commands.runner),
        },
        timeout=15,
    )

    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert not os.path.lexists(str(execution))
    (tmp_path / "resume-release").touch()
    wait_for_file(execution)
    assert yaml.safe_load(mapping_file.read_text(encoding="utf-8"))["session"] == mapping[
        "session"
    ]
    assert (mapping_file.parent / "launch.yml").read_bytes() == launch_before
    registration = yaml.safe_load(
        (mapping_file.parent / "child-registration.yml").read_text(encoding="utf-8")
    )
    assert registration["tasks"] == [
        {
            "ticket_id": "76",
            "role": "engineer",
            "alias": "76-session_alias_control-handover0-engineer@engineer",
            "launch_status": "registered",
        }
    ]
    assert not (ticket / "teams" / "1" / "team.yml").exists()


def test_installed_stopped_preteam_send_is_read_only(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root, _, _, environment = configure_harness(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    clock = tmp_path / "stopped-preteam-clock"
    clock.write_text(str(time.time()), encoding="utf-8")
    controls = tmp_path / "stopped-preteam-controls"
    controls.mkdir()
    (controls / "sitecustomize.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "try:\n"
        "    import graphtraj.execution.execution_budget as budget\n"
        "except ModuleNotFoundError:\n"
        "    pass\n"
        "else:\n"
        "    budget.time.time = lambda: float(Path(os.environ['BUDGET_CLOCK']).read_text())\n"
        "    budget.random.random = lambda: 0.99\n",
        encoding="utf-8",
    )
    run_environment = {
        **environment,
        "BUDGET_CLOCK": str(clock),
        "PYTHONPATH": str(controls),
    }
    _register_ready_ticket(
        installed_commands,
        harness_root,
        body="""---
difficulty: medium
difficulty_reason: The stopped Leader resumes before Team registration
execution_budget:
  engineer_tier: senior
  tier_reason: The Runner checks one stopped Leader continuation
  estimated_minutes:
    implementation: 1
    validation: 1
    review: 1
    total: 0.01
  planned_sessions:
    team_leader: 1
    engineer: 1
    standards_reviewer: 1
    spec_reviewer: 1
    delivery_state: 1
  correction_rounds: 1
  estimation_note: The controlled clock samples one stopped continuation
  on_exceed: Preserve the current Session
---

Deliver the accepted Session transport behavior.
""",
    )
    batch = harness_root / "batch.yml"
    batch.write_text(
        "tasks:\n"
        "  - ticket_id: \"76\"\n"
        "    ticket_name: session-alias-control\n"
        "    role: team-leader\n",
        encoding="utf-8",
    )
    launched = run_process(
        [str(installed_commands.runner), "--swarm-input", str(batch)],
        cwd=harness_root,
        env=run_environment,
        timeout=15,
    )

    assert launched.returncode == 1
    mapping_file = next(
        path
        for path in (harness_root / ".graphtraj" / "runner" / "sessions").glob(
            "*/mapping.yml"
        )
        if yaml.safe_load(path.read_text(encoding="utf-8"))["role"] == "team-leader"
    )
    mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
    ticket = harness_root / ".graphtraj" / "state" / "tickets" / "76-session-alias-control"
    assert not (ticket / "teams" / "1" / "team.yml").exists()
    usage_file = ticket / "execution-budget.yml"
    usage = yaml.safe_load(usage_file.read_text(encoding="utf-8"))
    clock.write_text(
        str(
            usage["started_at"]
            + (0.01 + usage["allowance_minutes"] + 2.1) * 60
        ),
        encoding="utf-8",
    )
    policy = tmp_path / "stopped-preteam-policy.json"
    fake_codex.executable.write_text(
        app_server_peer("#!" + sys.executable + "\n" + """
import json
import os
import sys
import tomllib
from pathlib import Path

settings = {}
for index, argument in enumerate(sys.argv[:-1]):
    if argument == "-c":
        settings.update(tomllib.loads(sys.argv[index + 1]))
filesystem = settings["permissions"][settings["default_permissions"]]["filesystem"]
Path(os.environ["STOPPED_POLICY_LOG"]).write_text(json.dumps({
    "worktree_access": filesystem[":workspace_roots"]["."],
    "team_round": os.environ.get("GRAPHTRAJ_TEAM_ROUND"),
}), encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": "fake-thread"}), flush=True)
print(json.dumps({"type": "turn.completed"}), flush=True)
"""),
        encoding="utf-8",
    )
    fake_codex.executable.chmod(0o755)
    cause = [
        json.loads(line)["event_id"]
        for shard in (harness_root / ".graphtraj" / "state" / "worldline").glob(
            "*.jsonl"
        )
        for line in shard.read_text(encoding="utf-8").splitlines()
    ][-1]

    stopped = run_process(
        [
            str(installed_commands.runner),
            "send",
            mapping["alias"],
            "--instruction",
            "Report the stopped result.",
            "--caused-by-event-id",
            cause,
        ],
        cwd=harness_root,
        env={**run_environment, "STOPPED_POLICY_LOG": str(policy)},
        timeout=15,
    )

    assert stopped.returncode == 0, stopped.stdout + stopped.stderr
    wait_for_file(policy)
    assert json.loads(policy.read_text(encoding="utf-8")) == {
        "worktree_access": "read",
        "team_round": None,
    }
    assert yaml.safe_load(usage_file.read_text(encoding="utf-8"))["stopped"] is True
    assert not (ticket / "teams" / "1" / "team.yml").exists()


def test_installed_leader_registration_does_not_grant_budget_write_paths(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root, _, _, environment = configure_harness(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    _register_ready_ticket(
        installed_commands,
        harness_root,
        body="""---
difficulty: medium
difficulty_reason: Nested registration checks the Ticket budget
execution_budget:
  engineer_tier: senior
  tier_reason: The Runner resumes one Team Leader
  estimated_minutes:
    implementation: 10
    validation: 10
    review: 10
    total: 30
  planned_sessions:
    team_leader: 3
    engineer: 1
    standards_reviewer: 1
    spec_reviewer: 1
    delivery_state: 1
  correction_rounds: 1
  estimation_note: The controlled Runtime completes one Team
  on_exceed: Preserve the current Session
---

Deliver the accepted Session transport behavior.
""",
    )
    batch = harness_root / "batch.yml"
    batch.write_text(
        "tasks:\n"
        "  - ticket_id: \"76\"\n"
        "    ticket_name: session-alias-control\n"
        "    role: team-leader\n",
        encoding="utf-8",
    )
    policy_log = tmp_path / "leader-policy.jsonl"

    result = run_process(
        [str(installed_commands.runner), "--swarm-input", str(batch)],
        cwd=harness_root,
        env={
            **environment,
            "FAKE_CODEX_LIFECYCLE_ACTION": "complete-team-round",
            "FAKE_CODEX_POLICY_LOG": str(policy_log),
            "GRAPHTRAJ_AGENT_RUNNER": str(installed_commands.runner),
        },
        timeout=45,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    ticket = harness_root / ".graphtraj" / "state" / "tickets" / "76-session-alias-control"
    assert (ticket / "execution-budget.yml").is_file()
    leaders = [
        json.loads(line)
        for line in policy_log.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["role"] == "team-leader"
    ]
    assert len(leaders) >= 2
    for leader in leaders:
        filesystem = leader["settings"]["permissions"][
            leader["settings"]["default_permissions"]
        ]["filesystem"]
        assert str(ticket / ".execution-budget.lock") not in filesystem
        assert str(ticket / "execution-budget.yml") not in filesystem
        assert filesystem.get(str(ticket)) != "write"


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
    # The Session keeps the Runner's own records; the Trace entry reads the
    # Runtime-owned native record, which may still be written when read.
    (session_directory / "events.jsonl").write_text(
        "{\"type\":\"runtime\",\"runtime\":\"codex\"}\n"
        "{\"type\": \"runner-execution-start\"}\n",
        encoding="utf-8",
    )
    trace = (
        harness_root
        / ".graphtraj"
        / "state"
        / "tickets"
        / "96-diagnostics"
        / "teams"
        / "1"
        / "traces"
        / alias
        / "events.jsonl"
    )
    trace.parent.mkdir(parents=True)
    trace.write_text(
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
        "{\"type\":\"event_msg\",\"payload\":{\"type\":\"item_completed\",\"item\":{\"type\":\"FileChange\",\"path\":\"added.txt\"}}}\n"
        "{\"type\":\"response_item\",\"payload\":{\"type\":\"custom_tool_call\",\"call_id\":\"call-unwrit",
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
                "role": "engineer",
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


def _retained_session(
    harness_root: Path,
    worktree: Path,
    alias: str,
    role: str,
) -> Path:
    """Write one recorded Session and its finished execution without a Runtime."""
    directory = harness_root / ".graphtraj" / "runner" / "sessions" / alias
    directory.mkdir(parents=True)
    (directory / "events.jsonl").write_text("", encoding="utf-8")
    (directory / "execution.yml").write_text("outcome: completed\n", encoding="utf-8")
    (directory / "mapping.yml").write_text(
        yaml.safe_dump(
            {
                "alias": alias,
                "runtime": "codex",
                "session": "native-session",
                "ticket_id": "76",
                "team_generation": 1,
                "role": role,
                "parent": None,
                "retained_batch_file": "batch.yml",
                "worktree_path": str(worktree),
                "trace_file": str(directory / "events.jsonl"),
                "worker_pid": 1,
                "runtime_pid": 1,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return directory


def test_installed_status_accepts_configured_entity_names_and_retains_history(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """An arbitrary entity name is locatable, an invalid one is refused, and history keeps its spelling."""
    harness_root, _, integration, environment = configure_harness(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    current_alias = "76-session_alias_control-handover0-engineer@小明"
    retained_alias = "76-session-alias-control@e1"
    current = _retained_session(harness_root, integration, current_alias, "engineer")
    retained = _retained_session(harness_root, integration, retained_alias, "engineer")
    current_record = (current / "mapping.yml").read_bytes()
    retained_record = (retained / "mapping.yml").read_bytes()

    located = run_process(
        [str(installed_commands.runner), "status", current_alias, retained_alias],
        cwd=harness_root,
        env=environment,
    )

    assert located.returncode == 0, located.stdout + located.stderr
    assert [
        entry["alias"] for entry in yaml.safe_load(located.stdout)["aliases"]
    ] == [current_alias, retained_alias]

    for refused_alias in (
        "76-session_alias_control-handover0-engineer@xiao-ming",
        "76-session_alias_control-handover0-engineer@xiao ming",
        "76-session_alias_control-handover0-engineer@../engineer",
        "76-session_alias_control-handover0-engineer@小..明",
        "76-session_alias_control-handover0-engineer@first@second",
    ):
        refused = run_process(
            [str(installed_commands.runner), "status", refused_alias],
            cwd=harness_root,
            env=environment,
        )
        assert refused.returncode == 1, refused_alias
        assert [
            entry["error"]["code"]
            for entry in yaml.safe_load(refused.stdout)["aliases"]
        ] == ["alias-not-found"], refused_alias

    assert (current / "mapping.yml").read_bytes() == current_record
    assert (retained / "mapping.yml").read_bytes() == retained_record
