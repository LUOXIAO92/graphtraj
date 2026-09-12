from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

from conftest import InstalledCommands, run_process, wait_for_file
from test_existing_repository_setup import run_setup
from runner_fixtures import configure_harness
from test_ticket_graph import _change_status, _register, _ticket


@pytest.fixture
def accepted_ticket(installed_commands, temporary_git_repository, fake_codex, tmp_path):
    root, worktrees, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path
    )
    _register(installed_commands, root, _ticket("83", "integration"))
    for identifier, dependencies in (("84", ["83"]), ("85", ["83"]), ("86", ["83", "84"])):
        _register(installed_commands, root, _ticket(identifier, "dependent", dependencies=dependencies))
    _change_status(installed_commands, root, "83", "ready")
    batch = root / "batch.yml"
    batch.write_text(yaml.safe_dump({"tasks": [{"ticket_id": "83", "ticket_name": "integration", "role": "coding-team.team-leader"}]}))
    environment.update(
        FAKE_CODEX_LIFECYCLE_ACTION="complete-team-round",
        GRAPHTRAJ_AGENT_RUNNER=str(installed_commands.runner),
    )
    launched = run_process([str(installed_commands.runner), "--batch-input", str(batch)], cwd=root, env=environment)
    assert launched.returncode == 0, launched.stderr
    state = root / ".graphtraj/state"
    record = yaml.safe_load((state / "tickets/83-integration/ticket.yml").read_text())
    assert record["status"] == "awaiting-integration"
    candidate = record["current_candidate"]
    assert run_process(["git", "merge-base", "--is-ancestor", candidate, "HEAD"], cwd=worktrees / "dev").returncode == 1
    return root, worktrees, state, candidate


def test_main_integrates_an_accepted_candidate_and_unlocks_only_satisfied_dependencies(
    installed_commands, accepted_ticket, fake_codex
):
    root, worktrees, state, candidate = accepted_ticket
    previous_runtime = fake_codex.log_file.read_bytes()
    # Later branch work must not silently replace the Team's fixed candidate.
    worktree = worktrees / "83-integration"
    (worktree / "LATER.txt").write_text("not part of the accepted candidate\n")
    run_process(["git", "add", "LATER.txt"], cwd=worktree).check_returncode()
    run_process(["git", "commit", "-m", "Later branch work"], cwd=worktree).check_returncode()
    validator = root / "validate.py"
    validator.write_text(
        "import pathlib, subprocess, yaml\n"
        f"state = yaml.safe_load(pathlib.Path({str(state / 'tickets/83-integration/ticket.yml')!r}).read_text())\n"
        "assert state['status'] == 'integrating'\n"
        f"assert state['current_candidate'] == {candidate!r}\n"
        "assert subprocess.check_output(['git', 'branch', '--show-current'], text=True).strip() == 'dev'\n"
        "assert pathlib.Path('TEAM_ROUND_DELIVERED.txt').read_text() == 'complete team round\\n'\n"
        "print('integration checks passed')\n"
    )
    result = run_process(
        [str(installed_commands.product), "ticket", "integrate", "--ticket-id", "83", "--", sys.executable, str(validator)], cwd=root
    )
    assert result.returncode == 0, result.stderr
    output = yaml.safe_load(result.stdout)
    assert output["candidate"] == candidate
    assert output["status"] == "integrated"
    assert fake_codex.log_file.read_bytes() == previous_runtime
    assert not any("@m" in path.name for path in state.rglob("*"))
    assert run_process(["git", "merge-base", "--is-ancestor", candidate, "HEAD"], cwd=worktrees / "dev").returncode == 0
    assert not (worktrees / "dev/LATER.txt").exists()
    graph = yaml.safe_load(run_process([str(installed_commands.product), "ticket", "graph"], cwd=root).stdout)
    assert [item["ticket_id"] for item in graph["tickets"] if item["ready"]] == ["84", "85"]
    assert [item["status"] for item in graph["tickets"]] == ["integrated", "ready", "ready", "pending"]
    events = [json.loads(line) for shard in (state / "worldline").glob("*.jsonl") for line in shard.read_text().splitlines()]
    accepted = next(event for event in events if event["kind"] == "team-round-accepted")
    started = next(event for event in events if event["kind"] == "ticket-integration-started")
    integrated = next(event for event in events if event["kind"] == "ticket-integrated")
    assert started["caused_by_event_ids"] == [accepted["event_id"]]
    assert integrated["caused_by_event_ids"] == [started["event_id"]]
    assert "integration checks passed" in (root / integrated["evidence_refs"][0]).read_text()
    unlocked = [event for event in events if event["kind"] == "ticket-dependency-unlocked"]
    assert {event["ticket_id"] for event in unlocked} == {"84", "85"}
    assert all(event["caused_by_event_ids"] == [integrated["event_id"]] for event in unlocked)
    assert not any(path.name in {"task-map.yml", "dag.md", "ledger.yml"} for path in state.rglob("*"))


def test_main_integration_refuses_dirty_dev(
    installed_commands, accepted_ticket,
):
    root, worktrees, state, candidate = accepted_ticket
    dev = worktrees / "dev"
    before = run_process(["git", "rev-parse", "HEAD"], cwd=dev).stdout
    (dev / "other-ticket-in-progress.txt").write_text(
        "temporary work from another Ticket\n", encoding="utf-8"
    )

    result = run_process(
        [
            str(installed_commands.product),
            "ticket",
            "integrate",
            "--ticket-id",
            "83",
            "--",
            sys.executable,
            "-c",
            "pass",
        ],
        cwd=root,
    )

    assert result.returncode == 1
    assert "must be clean" in yaml.safe_load(result.stdout)["error"]
    assert run_process(["git", "rev-parse", "HEAD"], cwd=dev).stdout == before
    record = yaml.safe_load((state / "tickets/83-integration/ticket.yml").read_text())
    assert record["status"] == "awaiting-integration"
    assert record["current_candidate"] == candidate


@pytest.mark.parametrize("flat_roles", (False, True))
def test_grouped_presets_apply_operator_settings_and_preserve_existing_history(
    installed_commands, accepted_ticket, fake_codex, flat_roles,
):
    root, _, state, _ = accepted_ticket
    roles_file = root / ".graphtraj/roles.yml"
    document = yaml.safe_load(roles_file.read_text())
    presets = document["roles"]["coding-team"]
    for name, preset in presets.items():
        preset.update(
            model="operator-" + name,
            base_url="https://runtime.example.invalid/" + name,
            reasoning_effort="high",
        )
    if flat_roles:
        document["roles"] = {**presets, "delivery-state": document["roles"]["delivery-state"]}
    roles_file.write_text(yaml.safe_dump(document))
    roles_before = roles_file.read_bytes()
    retained = {
        path: path.read_bytes()
        for directory in (state / "batches", state / "worldline", state / "tickets/83-integration/teams")
        for path in directory.rglob("*") if path.is_file()
    }
    setup = run_setup(installed_commands, root, answers="")
    assert setup.returncode == 0, setup.stderr
    assert roles_file.read_bytes() == roles_before
    assert {path: path.read_bytes() for path in retained} == retained

    _register(installed_commands, root, _ticket("89", "grouped-settings"))
    _change_status(installed_commands, root, "89", "ready")
    batch = root / "grouped-settings.yml"
    batch.write_text(yaml.safe_dump({"tasks": [{
        "ticket_id": "89", "ticket_name": "grouped-settings", "role": "coding-team.team-leader",
    }]}))
    fake_codex.log_file.write_text("")
    environment = dict(
        os.environ, HOME=str(root / "operator-home"),
        PATH=str(fake_codex.executable.parent) + os.pathsep + os.environ["PATH"],
        FAKE_CODEX_LOG=str(fake_codex.log_file), FAKE_CODEX_CAPTURE_ROLE="1",
        FAKE_CODEX_APPEND_LOG="1", FAKE_CODEX_CAPTURE_CONNECTION="1",
        FAKE_CODEX_LIFECYCLE_ACTION="complete-team-round",
        GRAPHTRAJ_AGENT_RUNNER=str(installed_commands.runner),
    )
    launched = run_process([str(installed_commands.runner), "--batch-input", str(batch)], cwd=root, env=environment)
    assert launched.returncode == 0, launched.stderr
    records = [json.loads(line) for line in fake_codex.log_file.read_text().splitlines()]
    assert {record["role"] for record in records} == {
        "team-leader", "engineer-junior", "standards-reviewer", "spec-reviewer", "delivery-state",
    }
    for record in records:
        if record["role"] == "delivery-state":
            continue
        selected = presets[record["role"]]
        assert record["argv"][record["argv"].index("--model") + 1] == selected["model"]
        assert record["connection"]["base_url"] == selected["base_url"]
        settings = {
            key: value
            for index, argument in enumerate(record["argv"][:-1])
            if argument == "-c"
            for key, value in tomllib.loads(record["argv"][index + 1]).items()
        }
        assert settings["model_reasoning_effort"] == selected["reasoning_effort"]
    leader_records = [record for record in records if record["role"] == "team-leader"]
    assert "resume" not in leader_records[0]["argv"]
    assert all("resume" in record["argv"] for record in leader_records[1:])
    assert roles_file.read_bytes() == roles_before
    for path, content in retained.items():
        if path.parent == state / "worldline":
            assert path.read_bytes().startswith(content)
        else:
            assert path.read_bytes() == content


def test_failed_validation_retains_evidence_without_unlocking_and_main_can_retry(
    installed_commands, accepted_ticket
):
    root, worktrees, state, candidate = accepted_ticket
    command = [str(installed_commands.product), "ticket", "integrate", "--ticket-id", "83", "--"]
    failed = run_process(command + [sys.executable, "-c", "print('validation failed'); raise SystemExit(1)"], cwd=root)
    assert failed.returncode == 1
    output = yaml.safe_load(failed.stdout)
    assert output["status"] == "integrating"
    evidence = root / output["evidence"]
    retained = evidence.read_bytes()
    assert b"validation failed" in retained
    assert run_process(["git", "merge-base", "--is-ancestor", candidate, "HEAD"], cwd=worktrees / "dev").returncode == 0
    graph = yaml.safe_load(run_process([str(installed_commands.product), "ticket", "graph"], cwd=root).stdout)
    assert not any(item["ready"] for item in graph["tickets"])
    # Generic semantic updates must not turn failed validation into integration.
    record = yaml.safe_load((state / "tickets/83-integration/ticket.yml").read_text())
    change = {key: record[key] for key in ("ticket_id", "active_team_ordinal", "worktree", "branch", "current_candidate")}
    change.update(status="integrated", caused_by_event_ids=[output["event_id"]], evidence_refs=[output["evidence"]])
    request = root / "bypass.yml"
    request.write_text(yaml.safe_dump(change))
    bypass = run_process([str(installed_commands.product), "ticket", "update", "--state-file", str(request)], cwd=root)
    assert bypass.returncode == 1
    assert yaml.safe_load((state / "tickets/83-integration/ticket.yml").read_text())["status"] == "integrating"
    retried = run_process(command + [sys.executable, "-c", "print('validation passed')"], cwd=root)
    assert retried.returncode == 0, retried.stderr
    assert yaml.safe_load(retried.stdout)["status"] == "integrated"
    assert evidence.read_bytes() == retained


def test_integration_rejects_a_team_caller_and_an_unaccepted_ticket(installed_commands, accepted_ticket):
    root, worktrees, state, candidate = accepted_ticket
    before = run_process(["git", "rev-parse", "HEAD"], cwd=worktrees / "dev").stdout
    for ticket_id, environment in (("83", {**os.environ, "GRAPHTRAJ_ROLE": "team-leader"}), ("84", os.environ)):
        result = run_process([str(installed_commands.product), "ticket", "integrate", "--ticket-id", ticket_id, "--", sys.executable, "-c", "pass"], cwd=root, env=environment)
        assert result.returncode == 1
        assert "error" in yaml.safe_load(result.stdout)
    assert run_process(["git", "rev-parse", "HEAD"], cwd=worktrees / "dev").stdout == before


def test_failed_merge_retains_conflict_evidence_and_does_not_run_validation(installed_commands, accepted_ticket):
    root, worktrees, state, candidate = accepted_ticket
    dev = worktrees / "dev"
    (dev / "TEAM_ROUND_DELIVERED.txt").write_text("conflicting integration work\n")
    for arguments in (("add", "TEAM_ROUND_DELIVERED.txt"), ("commit", "-m", "Independent dev change")):
        run_process(["git", *arguments], cwd=dev).check_returncode()
    result = run_process([str(installed_commands.product), "ticket", "integrate", "--ticket-id", "83", "--", sys.executable, "-c", "print('VALIDATOR RAN')"], cwd=root)
    assert result.returncode == 1
    output = yaml.safe_load(result.stdout)
    evidence = (root / output["evidence"]).read_text()
    assert "CONFLICT" in evidence
    assert "VALIDATOR RAN" not in evidence
    assert output["status"] == "integrating"
    graph = yaml.safe_load(run_process([str(installed_commands.product), "ticket", "graph"], cwd=root).stdout)
    assert not any(item["ready"] for item in graph["tickets"])


def test_main_resolves_observed_textual_conflict_then_validates_dev(
    installed_commands, accepted_ticket, fake_codex
):
    root, worktrees, state, candidate = accepted_ticket
    roles_file = root / ".graphtraj/roles.yml"
    roles = yaml.safe_load(roles_file.read_text())
    roles["roles"]["coding-team"]["merge-resolver"]["model"] = "gpt-5.6-luna"
    roles_file.write_text(yaml.safe_dump(roles))
    dev = worktrees / "dev"
    (dev / "TEAM_ROUND_DELIVERED.txt").write_text("conflicting integration work\n")
    for arguments in (("add", "TEAM_ROUND_DELIVERED.txt"), ("commit", "-m", "Independent dev change")):
        run_process(["git", *arguments], cwd=dev).check_returncode()
    before = run_process(["git", "rev-parse", "HEAD"], cwd=dev).stdout.strip()
    command = [str(installed_commands.product), "ticket", "integrate", "--ticket-id", "83"]
    validator = [sys.executable, "-c", "from pathlib import Path; assert Path('TEAM_ROUND_DELIVERED.txt').read_text() == 'complete team round\\nconflicting integration work\\n'"]
    failed = run_process(command + ["--", *validator], cwd=root)
    assert failed.returncode == 1
    previous_runtime = fake_codex.log_file.read_bytes()
    environment = {
        **os.environ,
        "HOME": str(root / "operator-home"),
        "PATH": str(fake_codex.executable.parent) + os.pathsep + os.environ["PATH"],
        "FAKE_CODEX_LOG": str(fake_codex.log_file),
        "FAKE_CODEX_CAPTURE_STDIN": "1",
        "FAKE_CODEX_LIFECYCLE_ACTION": "resolve-integration",
    }
    interrupted = run_process(command + ["--resolve-conflict", "Preserve both accepted lines", "--", *validator], cwd=root, env={**environment, "FAKE_CODEX_EXIT_CODE": "1"})
    assert interrupted.returncode == 1
    assert yaml.safe_load(interrupted.stdout).get("status") == "integrating", interrupted.stdout + interrupted.stderr
    result = run_process(command + ["--resolve-conflict", "Preserve both accepted lines", "--", *validator], cwd=root, env=environment)
    output = yaml.safe_load(result.stdout)
    assert result.returncode == 0, result.stdout + result.stderr + (root / output["evidence"]).read_text()
    assert output["status"] == "integrated"
    request = json.loads(fake_codex.log_file.read_text())
    assert fake_codex.log_file.read_bytes() != previous_runtime
    assert request["cwd"] == str(dev)
    assert request["argv"][request["argv"].index("--model") + 1] == "gpt-5.6-luna"
    assert candidate in request["stdin"] and before in request["stdin"]
    assert "CONFLICT" in request["stdin"]
    settings = {}
    for index, argument in enumerate(request["argv"]):
        if argument == "-c":
            settings.update(tomllib.loads(request["argv"][index + 1]))
    assert settings["agents"]["enabled"] is False
    permissions = settings["permissions"][settings["default_permissions"]]["filesystem"]
    assert permissions[str(state / "tickets/83-integration")] == "read"
    assert permissions[":workspace_roots"]["docs"] == "read"
    assert "hooks" not in settings
    assert run_process(["git", "rev-parse", "HEAD^1"], cwd=dev).stdout.strip() == before
    assert run_process(["git", "rev-parse", "HEAD^2"], cwd=dev).stdout.strip() == candidate
    events = [json.loads(line) for shard in (state / "worldline").glob("*.jsonl") for line in shard.read_text().splitlines()]
    resolved = next(event for event in events if event["kind"] == "ticket-integration-conflict-resolved")
    assert resolved["session_ref"]
    trace = next(root / ref for ref in resolved["evidence_refs"] if ref.endswith("events.jsonl"))
    assert "Decision: RESOLVED" in trace.read_text()
    assert yaml.safe_load((state / "tickets/83-integration/ticket.yml").read_text())["status"] == "integrated"


@pytest.mark.parametrize("outcome", ["resolved", "escalated", "invalid-resolution", "unrelated-history"])
def test_semantic_conflict_returns_to_main_and_requires_passing_validation(
    installed_commands, accepted_ticket, fake_codex, outcome
):
    root, worktrees, state, candidate = accepted_ticket
    if outcome == "escalated":
        _register(installed_commands, root, _ticket("88", "independent"))
        _change_status(installed_commands, root, "88", "ready")
        batch = root / "independent.yml"
        batch.write_text(yaml.safe_dump({"tasks": [{"ticket_id": "88", "ticket_name": "independent", "role": "team-leader"}]}))
        launched = run_process([str(installed_commands.runner), "--batch-input", str(batch)], cwd=root, env={
            **os.environ, "HOME": str(root / "operator-home"),
            "PATH": str(fake_codex.executable.parent) + os.pathsep + os.environ["PATH"],
            "FAKE_CODEX_LOG": str(fake_codex.log_file),
            "FAKE_CODEX_LIFECYCLE_ACTION": "complete-team-round",
            "GRAPHTRAJ_AGENT_RUNNER": str(installed_commands.runner),
        })
        assert launched.returncode == 0, launched.stderr
    command = [str(installed_commands.product), "ticket", "integrate", "--ticket-id", "83"]
    validator = [sys.executable, "-c", "from pathlib import Path; assert Path('TEAM_ROUND_DELIVERED.txt').read_text() == 'complete team round\\nconflicting integration work\\n', 'semantic incompatibility: missing existing dev behavior'"]
    failed = run_process(command + ["--", *validator], cwd=root)
    assert failed.returncode == 1
    environment = {
        **os.environ, "HOME": str(root / "operator-home"),
        "PATH": str(fake_codex.executable.parent) + os.pathsep + os.environ["PATH"],
        "FAKE_CODEX_LOG": str(fake_codex.log_file),
        "FAKE_CODEX_CAPTURE_STDIN": "1",
        "FAKE_CODEX_LIFECYCLE_ACTION": "resolve-integration",
        "FAKE_CODEX_RESOLUTION": outcome,
    }
    previous_runtime = fake_codex.log_file.read_bytes()
    weaker = run_process(command + ["--resolve-conflict", "Preserve accepted behavior", "--", sys.executable, "-c", "pass"], cwd=root, env=environment)
    assert weaker.returncode == 1
    assert fake_codex.log_file.read_bytes() == previous_runtime
    result = run_process(command + ["--resolve-conflict", "Preserve accepted behavior", "--", *validator], cwd=root, env=environment)
    output = yaml.safe_load(result.stdout)
    assert output["status"] == {"resolved": "integrated", "escalated": "escalated", "invalid-resolution": "integrating", "unrelated-history": "escalated"}[outcome], (root / output["evidence"]).read_text()
    assert result.returncode == (0 if outcome == "resolved" else 1)
    events = [json.loads(line) for shard in (state / "worldline").glob("*.jsonl") for line in shard.read_text().splitlines()]
    final = next(event for event in events if event["event_id"] == output["event_id"])
    assert final["session_ref"]
    assert "semantic incompatibility" in json.loads(fake_codex.log_file.read_text())["stdin"]
    graph = yaml.safe_load(run_process([str(installed_commands.product), "ticket", "graph"], cwd=root).stdout)
    assert any(item["ready"] for item in graph["tickets"]) == (outcome == "resolved")
    if outcome == "unrelated-history":
        assert "changed dev history" in (root / output["evidence"]).read_text()
    if outcome == "escalated":
        assert run_process(["git", "rev-parse", "HEAD"], cwd=worktrees / "dev").stdout.strip() == candidate
        trace = next(root / ref for ref in final["evidence_refs"] if ref.endswith("events.jsonl"))
        assert "incompatible accepted requirements" in trace.read_text()
        other = run_process([str(installed_commands.product), "ticket", "integrate", "--ticket-id", "88", "--", sys.executable, "-c", "pass"], cwd=root)
        assert other.returncode == 1
        assert "unfinished integration" in yaml.safe_load(other.stdout)["error"]


def test_resolver_requires_mains_observed_conflict(installed_commands, accepted_ticket, fake_codex):
    root, worktrees, state, candidate = accepted_ticket
    previous_runtime = fake_codex.log_file.read_bytes()
    command = [str(installed_commands.product), "ticket", "integrate", "--ticket-id", "83", "--resolve-conflict", "No observed conflict", "--", sys.executable, "-c", "pass"]
    rejected = run_process(command, cwd=root)
    assert rejected.returncode == 1
    batch = root / "resolver.yml"
    batch.write_text(yaml.safe_dump({"tasks": [{"ticket_id": "83", "ticket_name": "integration", "role": "merge-resolver"}]}))
    rejected = run_process([str(installed_commands.runner), "--batch-input", str(batch)], cwd=root)
    assert rejected.returncode == 1
    assert "conflict" in yaml.safe_load(rejected.stdout)["error"]["message"]
    assert fake_codex.log_file.read_bytes() == previous_runtime


def test_main_integration_is_serialized_until_validation_finishes(installed_commands, accepted_ticket):
    root, worktrees, state, candidate = accepted_ticket
    started = root / "validation-started"
    release = root / "validation-release"
    validator = root / "wait-validation.py"
    validator.write_text(
        "from pathlib import Path\nimport time\n"
        f"Path({str(started)!r}).touch()\n"
        f"while not Path({str(release)!r}).exists():\n    time.sleep(0.01)\n"
    )
    command = [str(installed_commands.product), "ticket", "integrate", "--ticket-id", "83", "--", sys.executable, str(validator)]
    first = subprocess.Popen(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        wait_for_file(started)
        second = run_process(command, cwd=root, timeout=5)
        assert second.returncode == 1
        assert "in progress" in yaml.safe_load(second.stdout)["error"]
        assert yaml.safe_load((state / "tickets/83-integration/ticket.yml").read_text())["status"] == "integrating"
    finally:
        release.touch()
        stdout, stderr = first.communicate(timeout=10)
    assert first.returncode == 0, stderr
    assert yaml.safe_load(stdout)["status"] == "integrated"


@pytest.mark.parametrize("entrypoint", ["python", "cli"])
@pytest.mark.parametrize("validation_exit", [0, 1])
def test_shared_integration_enforces_main_and_returns_retained_outcome(
    installed_commands: InstalledCommands,
    accepted_ticket: tuple[Path, Path, Path, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    entrypoint: str,
    validation_exit: int,
) -> None:
    """Python integration includes the CLI's authority and serialization guards."""
    from click.testing import CliRunner
    from graphtraj.configuration.project_configuration import load_project_configuration
    from graphtraj.graph.delivery_worldline import read_worldline
    from graphtraj.graph.ticket_graph import read_graph
    from graphtraj.interfaces.cli.graphtraj import main
    from graphtraj.teams.coding.ticket_integration import integrate_ticket

    root, worktrees, state, candidate = accepted_ticket
    configuration = load_project_configuration(root)
    command = (sys.executable, "-c", "assert open('TEAM_ROUND_DELIVERED.txt').read() == 'complete team round\\n'")
    command = (*command[:2], command[2] + f"; raise SystemExit({validation_exit})")
    monkeypatch.chdir(root)
    monkeypatch.setenv("GRAPHTRAJ_ROLE", "engineer-expert")
    before = read_worldline(state, root)
    with pytest.raises(ValueError) as error:
        integrate_ticket(configuration, "83", command)
    denied = CliRunner().invoke(main, ["ticket", "integrate", "--ticket-id", "83", "--", *command])
    assert denied.exit_code == 1
    assert yaml.safe_load(denied.stdout) == {"error": str(error.value)}
    assert read_worldline(state, root) == before
    monkeypatch.delenv("GRAPHTRAJ_ROLE")
    with pytest.raises(ValueError):
        integrate_ticket(configuration, "83", ())
    assert read_worldline(state, root) == before

    if entrypoint == "python":
        result = integrate_ticket(configuration, "83", command)
        assert capsys.readouterr() == ("", "")
    else:
        completed = CliRunner().invoke(main, ["ticket", "integrate", "--ticket-id", "83", "--", *command])
        assert completed.exit_code == validation_exit, completed.output
        result = yaml.safe_load(completed.stdout)
    assert result["status"] == ("integrated" if validation_exit == 0 else "integrating")
    assert result["candidate"] == candidate
    assert set(result["unlocked_ticket_ids"]) == ({"84", "85"} if validation_exit == 0 else set())
    event = next(item for item in read_worldline(state, root) if item["event_id"] == result["event_id"])
    assert event["kind"] == ("ticket-integrated" if validation_exit == 0 else "ticket-integration-failed")
    assert event["validation_command"] == list(command)
    assert result["evidence"] in event["evidence_refs"]
    assert (root / result["evidence"]).is_file()
    assert read_graph(state)["tickets"][0]["status"] == result["status"]
