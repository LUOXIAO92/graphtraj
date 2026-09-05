from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import yaml

from conftest import run_process
from test_agent_runner_batch import configure_harness


def ready_batch(commands, root, ids, name):
    (root / "readiness.md").write_text("No unmet dependencies.\n")
    tasks = []
    for ticket_id in ids:
        task = {"ticket_id": ticket_id, "ticket_name": "parallel", "role": "team-leader"}
        source = root / "ticket-input.yml"
        source.write_text(yaml.safe_dump({
            "ticket_id": ticket_id, "ticket_name": "parallel",
            "source": "https://github.com/example/project/issues/" + ticket_id,
            "title": "Parallel delivery", "body": "Deliver this Ticket.", "dependencies": [],
        }))
        run_process([str(commands.product), "ticket", "register", "--ticket-file", str(source)], cwd=root).check_returncode()
        source.write_text(yaml.safe_dump({
            "ticket_id": ticket_id, "status": "ready", "active_team_ordinal": None,
            "worktree": None, "branch": None, "current_candidate": None,
            "caused_by_event_ids": [], "evidence_refs": ["readiness.md"],
        }))
        run_process([str(commands.product), "ticket", "update", "--state-file", str(source)], cwd=root).check_returncode()
        tasks.append(task)
    batch = root / (name + ".yml")
    batch.write_text(yaml.safe_dump({"tasks": tasks}))
    return batch


def observe_runtime(fake, root, environment):
    # Observe actual Runtime lifetimes, independently of Runner's own records.
    probe = '''
import atexit, fcntl
probe_root = Path(os.environ['CAPACITY_PROBE'])
def observe(kind):
    with (probe_root / 'observations.jsonl').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.write(json.dumps({'kind': kind, 'pid': os.getpid(), 'ticket': os.environ['GRAPHTRAJ_TICKET_ID'], 'role': os.environ['GRAPHTRAJ_ROLE'], 'argv': sys.argv[1:]}) + '\\n')
        stream.flush()
observe('start')
atexit.register(observe, 'exit')
while not (probe_root / 'release').exists() and not (probe_root / ('release-' + os.environ['GRAPHTRAJ_TICKET_ID'])).exists():
    time.sleep(0.01)
if os.environ.get('FAIL_TICKET') == os.environ['GRAPHTRAJ_TICKET_ID']:
    sys.stderr.write('controlled startup failure\\n')
    raise SystemExit(23)
'''
    script = fake.executable.read_text()
    script = script.replace("configured_events =", probe + "\nconfigured_events =", 1)
    fake.executable.write_text(script)
    environment.update(CAPACITY_PROBE=str(root), FAKE_CODEX_LIFECYCLE_ACTION="complete-team-round")


def starts(root, count):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        path = root / "observations.jsonl"
        events = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        if sum(event["kind"] == "start" for event in events) >= count:
            return events
        time.sleep(0.02)
    raise AssertionError("Expected concurrently executing Runtime processes did not start")


def launch(commands, root, batch, environment):
    return subprocess.Popen(
        [str(commands.runner), "--batch-input", str(batch)], cwd=root, env=environment,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def test_more_than_four_teams_execute_concurrently(
    installed_commands, temporary_git_repository, fake_codex, tmp_path,
):
    root, _, _, environment = configure_harness(installed_commands, temporary_git_repository, fake_codex, tmp_path)
    environment["GRAPHTRAJ_AGENT_RUNNER"] = str(installed_commands.runner)
    batch = ready_batch(installed_commands, root, [str(n) for n in range(101, 106)], "five")
    observe_runtime(fake_codex, root, environment)
    worker = launch(installed_commands, root, batch, environment)
    try:
        events = starts(root, 5)
        assert len({event["ticket"] for event in events}) == 5
        assert all(event["role"] == "team-leader" for event in events)
    finally:
        (root / "release").touch()
        stdout, stderr = worker.communicate(timeout=60)
    assert worker.returncode == 0, stderr + stdout
    assert [task["launch_status"] for task in yaml.safe_load(stdout)["tasks"]] == ["accepted"] * 5


def test_separate_runners_share_capacity_and_reject_whole_batches(
    installed_commands, temporary_git_repository, fake_codex, tmp_path,
):
    root, worktrees, _, environment = configure_harness(installed_commands, temporary_git_repository, fake_codex, tmp_path)
    environment["GRAPHTRAJ_AGENT_RUNNER"] = str(installed_commands.runner)
    config_file = root / ".graphtraj" / "config.yml"
    config = yaml.safe_load(config_file.read_text())
    config["agent_runner"]["max_concurrency"] = 3
    config_file.write_text(yaml.safe_dump(config))
    first = ready_batch(installed_commands, root, ["201", "202"], "first")
    denied = ready_batch(installed_commands, root, ["203", "204"], "denied")
    last = ready_batch(installed_commands, root, ["205"], "last")
    observe_runtime(fake_codex, root, environment)
    workers = [launch(installed_commands, root, first, environment)]
    try:
        starts(root, 2)
        rejected = run_process(
            [str(installed_commands.runner), "--batch-input", str(denied)],
            cwd=root, env=environment, timeout=5,
        )
        assert rejected.returncode == 1
        assert yaml.safe_load(rejected.stdout)["error"]["code"] == "insufficient-capacity"
        assert not (worktrees / "203-parallel").exists()
        assert not (worktrees / "204-parallel").exists()
        workers.append(launch(installed_commands, root, last, environment))
        events = starts(root, 3)
        assert {event["ticket"] for event in events} == {"201", "202", "205"}
    finally:
        (root / "release").touch()
        for worker in workers:
            worker.communicate(timeout=60)

    # All workers exited; their existing unlocked lock files must not consume capacity.
    retry = run_process(
        [str(installed_commands.runner), "--batch-input", str(denied)],
        cwd=root, env=environment, timeout=60,
    )
    output = yaml.safe_load(retry.stdout)
    assert "error" not in output, retry.stdout
    # The controlled Leader may decline to replace a rejected child Batch.
    assert all(task.get("error", {}).get("code") in {None, "insufficient-capacity"} for task in output["tasks"])
    active = set()
    maximum = 0
    for event in [json.loads(line) for line in (root / "observations.jsonl").read_text().splitlines()]:
        if event["kind"] == "start":
            active.add(event["pid"])
        else:
            active.remove(event["pid"])
        maximum = max(maximum, len(active))
    assert maximum == 3
    assert not active
    assert {"203", "204"}.issubset({
        event["ticket"] for event in starts(root, 3) if event["role"] == "team-leader"
    })


def test_reviewer_batch_starts_neither_role_when_only_one_position_is_free(
    installed_commands, temporary_git_repository, fake_codex, tmp_path,
):
    root, _, _, environment = configure_harness(installed_commands, temporary_git_repository, fake_codex, tmp_path)
    environment["GRAPHTRAJ_AGENT_RUNNER"] = str(installed_commands.runner)
    config_file = root / ".graphtraj" / "config.yml"
    config = yaml.safe_load(config_file.read_text())
    config["agent_runner"]["max_concurrency"] = 2
    config_file.write_text(yaml.safe_dump(config))
    occupied = ready_batch(installed_commands, root, ["301"], "occupied")
    subject = ready_batch(installed_commands, root, ["302"], "subject")
    observe_runtime(fake_codex, root, environment)
    holder = launch(installed_commands, root, occupied, environment)
    try:
        starts(root, 1)
        (root / "release-302").touch()
        result = run_process(
            [str(installed_commands.runner), "--batch-input", str(subject)],
            cwd=root, env=environment, timeout=30,
        )
        assert result.returncode == 1, result.stdout
        task = yaml.safe_load(result.stdout)["tasks"][0]
        assert task["error"]["code"] == "insufficient-capacity"
        events = [json.loads(line) for line in (root / "observations.jsonl").read_text().splitlines()]
        assert not any(event["role"].endswith("reviewer") for event in events)
    finally:
        (root / "release").touch()
        holder.communicate(timeout=60)


def test_startup_failure_does_not_erase_a_peer_that_started(
    installed_commands, temporary_git_repository, fake_codex, tmp_path,
):
    root, _, _, environment = configure_harness(installed_commands, temporary_git_repository, fake_codex, tmp_path)
    environment.update(GRAPHTRAJ_AGENT_RUNNER=str(installed_commands.runner), FAIL_TICKET="401")
    batch = ready_batch(installed_commands, root, ["401", "402"], "startup")
    observe_runtime(fake_codex, root, environment)
    worker = launch(installed_commands, root, batch, environment)
    try:
        starts(root, 2)
    finally:
        (root / "release").touch()
        stdout, stderr = worker.communicate(timeout=60)
    assert worker.returncode == 1, stdout
    failed, completed = yaml.safe_load(stdout)["tasks"]
    assert failed["ticket_id"] == "401"
    assert failed["launch_status"] == "failed"
    assert failed["error"]["code"] == "launch-failed"
    assert completed["ticket_id"] == "402"
    assert completed["launch_status"] == "accepted"
    assert completed["alias"]


def test_duplicate_team_role_is_rejected_before_runtime_start(
    installed_commands, temporary_git_repository, fake_codex, tmp_path,
):
    root, _, _, environment = configure_harness(installed_commands, temporary_git_repository, fake_codex, tmp_path)
    batch = ready_batch(installed_commands, root, ["501"], "duplicate")
    task = yaml.safe_load(batch.read_text())["tasks"][0]
    batch.write_text(yaml.safe_dump({"tasks": [task, task]}))
    result = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch)],
        cwd=root, env=environment,
    )
    assert result.returncode == 1
    assert yaml.safe_load(result.stdout)["error"]["code"] == "invalid-input"
    assert not fake_codex.log_file.exists()


def test_one_position_completes_one_round_with_sequential_reviewers(
    installed_commands, temporary_git_repository, fake_codex, tmp_path,
):
    root, _, _, environment = configure_harness(installed_commands, temporary_git_repository, fake_codex, tmp_path)
    environment.update(GRAPHTRAJ_AGENT_RUNNER=str(installed_commands.runner), FAKE_CODEX_SERIAL_TEAM="1")
    config_file = root / ".graphtraj" / "config.yml"
    config = yaml.safe_load(config_file.read_text())
    config["agent_runner"]["max_concurrency"] = 1
    config_file.write_text(yaml.safe_dump(config))
    batch = ready_batch(installed_commands, root, ["78"], "serial")
    observe_runtime(fake_codex, root, environment)
    (root / "release").touch()
    result = run_process([str(installed_commands.runner), "--batch-input", str(batch)], cwd=root, env=environment, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert yaml.safe_load(result.stdout)["tasks"][0]["launch_status"] == "accepted"
    active = set()
    roles = []
    events = starts(root, 1)
    for event in events:
        if event["kind"] == "start":
            active.add(event["pid"])
            roles.append(event["role"])
        else:
            active.remove(event["pid"])
        assert len(active) <= 1
    assert not active
    assert [role for role in roles if role != "delivery-state"] == [
        "team-leader", "engineer-junior", "team-leader", "team-leader",
        "standards-reviewer", "team-leader", "spec-reviewer", "team-leader",
    ]
    leaders = [event for event in events if event["kind"] == "start" and event["role"] == "team-leader"]
    assert "resume" not in leaders[0]["argv"]
    assert all("resume" in event["argv"] and "fake-thread" in event["argv"] for event in leaders[1:])
    ticket = root / ".graphtraj" / "state" / "tickets" / "78-parallel"
    team = yaml.safe_load((ticket / "teams" / "1" / "team.yml").read_text())
    assert team["current_round"] == 1
    assert yaml.safe_load((ticket / "ticket.yml").read_text())["status"] == "awaiting-integration"
    reports = ticket / "teams" / "1" / "rounds" / "1"
    assert {path.name for path in reports.iterdir()} == {"engineer.md", "validation.md", "standards.md", "spec.md", "leader.md"}
    assert all(member["session_ref"] for member in team["members"].values())
    assert len(list((root / ".graphtraj" / "state" / "batches").glob("*.yml"))) == 5
