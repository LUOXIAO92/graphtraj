from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import yaml

from conftest import FakeCodex, InstalledCommands, run_process, wait_for_file
from runner_fixtures import configure_harness, engineer_probe
from test_session_alias_control import _register_ready_ticket
from test_team_correction import RUNTIME as CORRECTION_RUNTIME
from test_team_recovery import RUNTIME as RECOVERY_RUNTIME


def _budget_body(
    *,
    total: float,
    correction_rounds: int = 1,
    delivery_state_sessions: int = 1,
    revision_reason: str | None = None,
) -> str:
    revision = "" if revision_reason is None else "  revision_reason: " + revision_reason + "\n"
    return """---
difficulty: high
difficulty_reason: Runtime work crosses the Team boundary
execution_budget:
  engineer_tier: senior
  tier_reason: Runtime behavior needs cross-module validation
  estimated_minutes:
    implementation: 35
    validation: 15
    review: 10
    total: {total}
  planned_sessions:
    team_leader: 1
    engineer: 1
    standards_reviewer: 1
    spec_reviewer: 1
    delivery_state: {delivery_state_sessions}
  correction_rounds: {correction_rounds}
  estimation_note: The controlled Runtime holds the Engineer Session open
  on_exceed: Notify the caller and preserve the running Session
{revision}---

Deliver the accepted Runtime behavior.
""".format(
        total=total,
        correction_rounds=correction_rounds,
        delivery_state_sessions=delivery_state_sessions,
        revision=revision,
    )


def _notices(path: Path) -> list[dict[str, object]]:
    return _stderr_notices(path.read_text(encoding="utf-8"))


def _stderr_notices(output: str) -> list[dict[str, object]]:
    notices = []
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "execution-budget-exceeded":
            notices.append(event)
    return notices


def test_installed_runner_notifies_its_nested_caller_before_the_worker_finishes(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path
    )
    release = tmp_path / "release-engineer"
    environment = {**environment, "FAKE_CODEX_RELEASE_FILE": str(release)}

    with engineer_probe(
        installed_commands,
        harness,
        fake_codex,
        environment,
        body=_budget_body(total=0.01),
    ) as (alias, _, probe_environment):
        output = harness / "probe-output.log"
        deadline = time.monotonic() + 5
        notices = _notices(output)
        while not notices and time.monotonic() < deadline:
            time.sleep(0.02)
            notices = _notices(output)

        notice = next(
            item for item in notices
            if item["threshold"] == {"kind": "elapsed_minutes", "limit": 0.01}
        )
        assert notice["ticket"] == {
            "ticket_id": "82",
            "ticket_name": "adapter-probe",
        }
        assert notice["actual"]["elapsed_minutes"] >= 0.01

        status = run_process(
            [str(installed_commands.runner), "status", alias],
            cwd=harness,
            env=probe_environment,
        )
        assert status.returncode == 0, status.stderr
        assert yaml.safe_load(status.stdout)["aliases"][0]["activity"] == "running"
        release.touch()


def test_installed_runner_delivers_sampled_stop_to_leader_before_engineer_stops(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path
    )
    clock = tmp_path / "budget-clock"
    clock.write_text(str(time.time()), encoding="utf-8")
    draws = tmp_path / "budget-draws"
    draws.write_text("0", encoding="utf-8")
    allowance_draws = tmp_path / "allowance-draws"
    allowance_draws.write_text("0", encoding="utf-8")
    controls = tmp_path / "budget-controls"
    controls.mkdir()
    (controls / "sitecustomize.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "try:\n"
        "    import graphtraj.execution_budget as budget\n"
        "except ModuleNotFoundError:\n"
        "    pass\n"
        "else:\n"
        "    budget.time.time = lambda: float(Path(os.environ['BUDGET_CLOCK']).read_text())\n"
        "    def allowance(lower, upper):\n"
        "        path = Path(os.environ['ALLOWANCE_DRAWS'])\n"
        "        path.write_text(str(int(path.read_text()) + 1))\n"
        "        return lower\n"
        "    budget.random.uniform = allowance\n"
        "    def draw():\n"
        "        path = Path(os.environ['BUDGET_DRAWS'])\n"
        "        index = int(path.read_text())\n"
        "        path.write_text(str(index + 1))\n"
        "        return (0.1, 0.9)[index]\n"
        "    budget.random.random = draw\n",
        encoding="utf-8",
    )
    release = tmp_path / "release-stopped-reports"
    environment = {
        **environment,
        "BUDGET_CLOCK": str(clock),
        "BUDGET_DRAWS": str(draws),
        "ALLOWANCE_DRAWS": str(allowance_draws),
        "FAKE_CODEX_CAPTURE_STDIN": "1",
        "FAKE_CODEX_RELEASE_FILE": str(release),
        "PYTHONPATH": str(controls),
    }

    with engineer_probe(
        installed_commands,
        harness,
        fake_codex,
        environment,
        body=_budget_body(total=0.01),
    ) as (alias, _, probe_environment):
        started = float(clock.read_text(encoding="utf-8"))
        usage_file = (
            harness
            / ".graphtraj/state/tickets/82-adapter-probe/execution-budget.yml"
        )
        clock.write_text(str(started + 0.61), encoding="utf-8")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            usage = yaml.safe_load(usage_file.read_text(encoding="utf-8"))
            if len(usage["leader_notices"]) == 1 and usage["leader_notices"][0]["delivered"]:
                break
            time.sleep(0.02)
        assert draws.read_text(encoding="utf-8") == "0"
        clock.write_text(str(started + 0.67), encoding="utf-8")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            usage = yaml.safe_load(usage_file.read_text(encoding="utf-8"))
            if len(usage["leader_notices"]) == 2 and all(
                notice["delivered"] for notice in usage["leader_notices"]
            ):
                break
            time.sleep(0.02)
        assert draws.read_text(encoding="utf-8") == "0"
        clock.write_text(str(started + 120.67), encoding="utf-8")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            usage = yaml.safe_load(usage_file.read_text(encoding="utf-8"))
            if usage["stopping_checks"] == 1:
                break
            time.sleep(0.02)
        assert usage["stopped"] is False
        assert draws.read_text(encoding="utf-8") == "1"
        clock.write_text(str(started + 240.67), encoding="utf-8")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            usage = yaml.safe_load(usage_file.read_text(encoding="utf-8"))
            if usage["stopped"] and all(
                notice["delivered"] for notice in usage["leader_notices"]
            ):
                break
            time.sleep(0.02)
        release.touch()
        assert usage["stopped"] is True
        assert usage["allowance_minutes"] == 0.001
        assert allowance_draws.read_text(encoding="utf-8") == "1"
        assert usage["stopping_checks"] == 2
        assert draws.read_text(encoding="utf-8") == "2"
        assert [notice["key"] for notice in usage["leader_notices"]] == [
            "elapsed_minutes:0.01",
            "additional_allowance:0.001",
            "stochastic_stop:4",
        ]
        leader_inputs = [
            json.loads(line)["stdin"]
            for line in fake_codex.log_file.read_text(encoding="utf-8").splitlines()
            if json.loads(line).get("role") == "team-leader"
            and "stdin" in json.loads(line)
        ]
        assert any("planned budget of 00:00:00" in prompt for prompt in leader_inputs)
        assert any(
            "additional allowance of 00:00:00" in prompt for prompt in leader_inputs
        )
        assert any(
            "Execution has taken too long and must stop" in prompt
            for prompt in leader_inputs
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status = run_process(
                [str(installed_commands.runner), "status", alias],
                cwd=harness,
                env=probe_environment,
            )
            if yaml.safe_load(status.stdout)["aliases"][0]["activity"] == "idle":
                break
            time.sleep(0.02)
        assert yaml.safe_load(status.stdout)["aliases"][0]["activity"] == "idle"
        execution_file = harness / ".graphtraj/runner/sessions" / alias / "execution.yml"
        assert yaml.safe_load(execution_file.read_text(encoding="utf-8"))[
            "outcome"
        ] == "interrupted"

    assert yaml.safe_load(execution_file.read_text(encoding="utf-8"))[
        "outcome"
    ] == "completed"
    round_directory = (
        harness
        / ".graphtraj/state/tickets/82-adapter-probe/teams/1/rounds/1"
    )
    assert (round_directory / "engineer.md").is_file()
    assert (round_directory / "validation.md").is_file()
    assert (round_directory / "leader.md").is_file()
    cause = [
        json.loads(line)["event_id"]
        for path in (harness / ".graphtraj/state/worldline").glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ][-1]
    reported = run_process(
        [
            str(installed_commands.runner),
            "send",
            alias,
            "--instruction",
            "Create another implementation file, then report.",
            "--caused-by-event-id",
            cause,
        ],
        cwd=harness,
        env=probe_environment,
    )
    assert reported.returncode == 0, reported.stderr
    wait_for_file(execution_file)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if yaml.safe_load(execution_file.read_text(encoding="utf-8"))[
            "outcome"
        ] == "completed":
            break
        time.sleep(0.02)
    engineer_inputs = [
        json.loads(line)["stdin"]
        for line in fake_codex.log_file.read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("role", "").startswith("engineer-")
        and "stdin" in json.loads(line)
    ]
    assert "Execution was stopped by Runner" in engineer_inputs[-1]
    restarted = run_process(
        [str(installed_commands.runner), "--batch-input", str(harness / "probe-batch.yml")],
        cwd=harness,
        env=probe_environment,
    )
    assert yaml.safe_load(restarted.stdout)["tasks"][0]["launch_status"] == "stopped"
    assert allowance_draws.read_text(encoding="utf-8") == "1"


def test_installed_runner_collects_reviews_already_running_at_sampled_stop(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path
    )
    _register_ready_ticket(
        installed_commands, harness, body=_budget_body(total=0.01)
    )
    clock = tmp_path / "review-budget-clock"
    clock.write_text(str(time.time()), encoding="utf-8")
    controls = tmp_path / "review-budget-controls"
    controls.mkdir()
    (controls / "sitecustomize.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "try:\n"
        "    import graphtraj.execution_budget as budget\n"
        "except ModuleNotFoundError:\n"
        "    pass\n"
        "else:\n"
        "    budget.time.time = lambda: float(Path(os.environ['BUDGET_CLOCK']).read_text())\n"
        "    budget.random.uniform = lambda lower, upper: lower\n"
        "    budget.random.random = lambda: 0.99\n",
        encoding="utf-8",
    )
    release = tmp_path / "release-running-reviews"
    batch = harness / "review-stop-batch.yml"
    batch.write_text(
        "tasks:\n"
        "  - ticket_id: \"76\"\n"
        "    ticket_name: session-alias-control\n"
        "    role: coding-team.team-leader\n",
        encoding="utf-8",
    )
    run_environment = {
        **environment,
        "BUDGET_CLOCK": str(clock),
        "FAKE_CODEX_APPEND_LOG": "1",
        "FAKE_CODEX_CAPTURE_STDIN": "1",
        "FAKE_CODEX_LIFECYCLE_ACTION": "complete-team-round",
        "FAKE_CODEX_REVIEW_RELEASE_FILE": str(release),
        "GRAPHTRAJ_AGENT_RUNNER": str(installed_commands.runner),
        "PYTHONPATH": str(controls),
    }
    process = subprocess.Popen(
        [str(installed_commands.runner), "--batch-input", str(batch)],
        cwd=harness,
        env=run_environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 15
        reviewer_mappings = []
        while time.monotonic() < deadline:
            reviewer_mappings = [
                yaml.safe_load(path.read_text(encoding="utf-8"))
                for path in (harness / ".graphtraj/runner/sessions").glob(
                    "*/mapping.yml"
                )
                if yaml.safe_load(path.read_text(encoding="utf-8")).get("role")
                in {"standards-reviewer", "spec-reviewer"}
            ]
            if len(reviewer_mappings) == 2:
                break
            time.sleep(0.02)
        assert len(reviewer_mappings) == 2
        started = float(clock.read_text(encoding="utf-8"))
        clock.write_text(str(started + 121), encoding="utf-8")
        usage_file = (
            harness
            / ".graphtraj/state/tickets/76-session-alias-control/execution-budget.yml"
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            usage = yaml.safe_load(usage_file.read_text(encoding="utf-8"))
            if usage["stopped"] and all(
                notice["delivered"] for notice in usage["leader_notices"]
            ):
                break
            time.sleep(0.02)
        assert usage["stopped"] is True
        release.touch()
        stdout, stderr = process.communicate(timeout=20)
    finally:
        release.touch()
        if process.poll() is None:
            process.terminate()
            process.wait()

    assert process.returncode == 0, stdout + stderr
    assert yaml.safe_load(stdout)["tasks"][0]["launch_status"] == "stopped"
    round_directory = (
        harness
        / ".graphtraj/state/tickets/76-session-alias-control/teams/1/rounds/1"
    )
    assert (round_directory / "standards.md").is_file()
    assert (round_directory / "spec.md").is_file()
    assert len(reviewer_mappings) == 2
    cause = [
        json.loads(line)["event_id"]
        for path in (harness / ".graphtraj/state/worldline").glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ][-1]
    blocked = run_process(
        [
            str(installed_commands.runner),
            "send",
            reviewer_mappings[0]["alias"],
            "--instruction",
            "Start another Review.",
            "--caused-by-event-id",
            cause,
        ],
        cwd=harness,
        env=run_environment,
    )
    assert blocked.returncode == 1
    assert "selected stopping" in blocked.stderr


def test_installed_runner_stops_final_leader_before_acceptance(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path
    )
    _register_ready_ticket(
        installed_commands, harness, body=_budget_body(total=1)
    )
    clock = tmp_path / "final-leader-clock"
    clock.write_text(str(time.time()), encoding="utf-8")
    controls = tmp_path / "final-leader-controls"
    controls.mkdir()
    (controls / "sitecustomize.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "try:\n"
        "    import graphtraj.execution_budget as budget\n"
        "except ModuleNotFoundError:\n"
        "    pass\n"
        "else:\n"
        "    budget.time.time = lambda: float(Path(os.environ['BUDGET_CLOCK']).read_text())\n"
        "    budget.random.uniform = lambda lower, upper: lower\n"
        "    budget.random.random = lambda: 0.99\n",
        encoding="utf-8",
    )
    batch = harness / "final-leader-stop-batch.yml"
    batch.write_text(
        "tasks:\n"
        "  - ticket_id: \"76\"\n"
        "    ticket_name: session-alias-control\n"
        "    role: coding-team.team-leader\n",
        encoding="utf-8",
    )
    result = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch)],
        cwd=harness,
        env={
            **environment,
            "BUDGET_CLOCK": str(clock),
            "FAKE_CODEX_APPEND_LOG": "1",
            "FAKE_CODEX_CAPTURE_STDIN": "1",
            "FAKE_CODEX_CAPTURE_ROLE": "1",
            "FAKE_CODEX_FINAL_LEADER_CLOCK": str(clock),
            "FAKE_CODEX_LIFECYCLE_ACTION": "complete-team-round",
            "GRAPHTRAJ_AGENT_RUNNER": str(installed_commands.runner),
            "PYTHONPATH": str(controls),
        },
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert yaml.safe_load(result.stdout)["tasks"][0]["launch_status"] == "stopped"
    ticket = harness / ".graphtraj/state/tickets/76-session-alias-control"
    state = yaml.safe_load((ticket / "ticket.yml").read_text(encoding="utf-8"))
    assert state["status"] == "reviewing"
    assert state["current_candidate"] is not None
    usage = yaml.safe_load((ticket / "execution-budget.yml").read_text())
    assert usage["stopped"] is True
    assert all(notice["delivered"] for notice in usage["leader_notices"])
    leader_inputs = [
        json.loads(line)["stdin"]
        for line in fake_codex.log_file.read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("role") == "team-leader"
        and "stdin" in json.loads(line)
    ]
    assert "Execution has taken too long and must stop" in leader_inputs[-1]
    assert "read-only Worktree access" in leader_inputs[-1]
    leader_mappings = [
        yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in (harness / ".graphtraj/runner/sessions").glob("*/mapping.yml")
        if yaml.safe_load(path.read_text(encoding="utf-8"))["role"] == "team-leader"
    ]
    assert len(leader_mappings) == 1


def test_installed_runner_delivers_elapsed_notices_to_final_leader(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path
    )
    _register_ready_ticket(
        installed_commands, harness, body=_budget_body(total=2.5)
    )
    clock = tmp_path / "final-leader-notice-clock"
    clock.write_text(str(time.time()), encoding="utf-8")
    controls = tmp_path / "final-leader-notice-controls"
    controls.mkdir()
    (controls / "sitecustomize.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "try:\n"
        "    import graphtraj.execution_budget as budget\n"
        "except ModuleNotFoundError:\n"
        "    pass\n"
        "else:\n"
        "    budget.time.time = lambda: float(Path(os.environ['BUDGET_CLOCK']).read_text())\n"
        "    budget.random.uniform = lambda lower, upper: lower\n"
        "    budget.random.random = lambda: 0.99\n",
        encoding="utf-8",
    )
    batch = harness / "final-leader-notice-batch.yml"
    batch.write_text(
        "tasks:\n"
        "  - ticket_id: \"76\"\n"
        "    ticket_name: session-alias-control\n"
        "    role: coding-team.team-leader\n",
        encoding="utf-8",
    )
    result = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch)],
        cwd=harness,
        env={
            **environment,
            "BUDGET_CLOCK": str(clock),
            "FAKE_CODEX_APPEND_LOG": "1",
            "FAKE_CODEX_CAPTURE_STDIN": "1",
            "FAKE_CODEX_CAPTURE_ROLE": "1",
            "FAKE_CODEX_FINAL_LEADER_CLOCK": str(clock),
            "FAKE_CODEX_LIFECYCLE_ACTION": "complete-team-round",
            "GRAPHTRAJ_AGENT_RUNNER": str(installed_commands.runner),
            "PYTHONPATH": str(controls),
        },
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert yaml.safe_load(result.stdout)["tasks"][0]["launch_status"] == "accepted"
    ticket = harness / ".graphtraj/state/tickets/76-session-alias-control"
    state = yaml.safe_load((ticket / "ticket.yml").read_text(encoding="utf-8"))
    assert state["status"] == "awaiting-integration"
    usage = yaml.safe_load((ticket / "execution-budget.yml").read_text())
    assert usage["stopped"] is False
    assert len(usage["leader_notices"]) == 2
    assert all(notice["delivered"] for notice in usage["leader_notices"])
    leader_inputs = [
        json.loads(line)["stdin"]
        for line in fake_codex.log_file.read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("role") == "team-leader"
        and "stdin" in json.loads(line)
    ]
    assert "The planned budget of 00:02:30 has been reached" in leader_inputs[-1]
    assert "additional allowance of 00:00:15" in leader_inputs[-1]
    assert "read-only Worktree access" not in leader_inputs[-1]


def test_installed_runner_uses_a_revised_budget_while_its_worker_is_running(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path
    )
    release = tmp_path / "release-revised-engineer"
    environment = {**environment, "FAKE_CODEX_RELEASE_FILE": str(release)}
    revised = _budget_body(
        total=0.01,
        revision_reason="Caller approved the observed Runtime wait before dispatch continued",
    )

    with engineer_probe(
        installed_commands,
        harness,
        fake_codex,
        environment,
        body=_budget_body(total=5),
    ) as (_, _, _):
        evidence = harness / "budget-revision.md"
        evidence.write_text("Caller approved the revised elapsed budget.\n", encoding="utf-8")
        revision = harness / "budget-revision.yml"
        revision_document = {
            "product_preserving": True,
            "caused_by_event_ids": [],
            "evidence_refs": ["budget-revision.md"],
            "tickets": [
                {
                    "ticket_id": "82",
                    "ticket_name": "adapter-probe",
                    "source": "https://github.com/example/project/issues/82",
                    "title": "Adapter Probe",
                    "body": _budget_body(total=0.01),
                    "dependencies": [],
                    "active": True,
                    "replaced_by": [],
                }
            ],
        }
        revision.write_text(
            yaml.safe_dump(revision_document, sort_keys=False),
            encoding="utf-8",
        )
        unapproved = run_process(
            [
                str(installed_commands.product),
                "ticket",
                "revise",
                "--revision-file",
                str(revision),
            ],
            cwd=harness,
        )
        assert unapproved.returncode == 1
        assert "requires its reason" in unapproved.stderr
        revision_document["tickets"][0]["body"] = revised
        revision.write_text(
            yaml.safe_dump(revision_document, sort_keys=False),
            encoding="utf-8",
        )
        revised_result = run_process(
            [
                str(installed_commands.product),
                "ticket",
                "revise",
                "--revision-file",
                str(revision),
            ],
            cwd=harness,
        )
        assert revised_result.returncode == 0, revised_result.stderr

        output = harness / "probe-output.log"
        deadline = time.monotonic() + 5
        notices = _notices(output)
        while not notices and time.monotonic() < deadline:
            time.sleep(0.02)
            notices = _notices(output)

        assert len(notices) == 1
        assert notices[0]["threshold"] == {"kind": "elapsed_minutes", "limit": 0.01}
        ticket = harness / ".graphtraj/state/tickets/82-adapter-probe"
        state = yaml.safe_load((ticket / "ticket.yml").read_text(encoding="utf-8"))
        assert state["current_definition"].startswith("definitions/")
        assert (ticket / "ticket.md").read_text(encoding="utf-8").startswith(
            _budget_body(total=5).split("\n\n", 1)[0]
        )
        current = ticket / state["current_definition"]
        assert current.read_text(encoding="utf-8").startswith(revised.split("\n\n", 1)[0])
        usage = yaml.safe_load((ticket / "execution-budget.yml").read_text(encoding="utf-8"))
        assert usage["budget"]["execution_budget"]["revision_reason"] == (
            "Caller approved the observed Runtime wait before dispatch continued"
        )
        release.touch()


def test_installed_runner_counts_sessions_and_emits_one_correction_overrun(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path
    )
    _register_ready_ticket(
        installed_commands,
        harness,
        body=_budget_body(total=60, correction_rounds=0),
    )
    fake_codex.executable.write_text("#!" + sys.executable + "\n" + CORRECTION_RUNTIME)
    batch = harness / "budget-correction-batch.yml"
    batch.write_text(
        "tasks:\n"
        "  - ticket_id: \"76\"\n"
        "    ticket_name: session-alias-control\n"
        "    role: coding-team.team-leader\n",
        encoding="utf-8",
    )
    result = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch)],
        cwd=harness,
        env={
            **environment,
            "GRAPHTRAJ_AGENT_RUNNER": str(installed_commands.runner),
            "CORRECTION_LOG": str(tmp_path / "budget-corrections.jsonl"),
            "CORRECTION_TIMING": "after-review",
        },
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert yaml.safe_load(result.stdout)["tasks"][0]["launch_status"] == "accepted"
    usage = yaml.safe_load(
        (
            harness
            / ".graphtraj/state/tickets/76-session-alias-control/execution-budget.yml"
        ).read_text(encoding="utf-8")
    )
    assert usage["sessions"] == {
        "team_leader": 1,
        "engineer": 1,
        "standards_reviewer": 1,
        "spec_reviewer": 1,
        "delivery_state": 1,
    }
    assert usage["corrections"] == 2
    notices = _stderr_notices(result.stderr)
    assert len(notices) == 1
    assert notices[0]["threshold"] == {"kind": "correction_rounds", "limit": 0}
    assert notices[0]["stage"] == "correction"
    assert notices[0]["responsible_role"] == "engineer-junior"


def test_installed_runner_notifies_once_when_a_replacement_exceeds_session_plan(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path
    )
    _register_ready_ticket(
        installed_commands,
        harness,
        body=_budget_body(total=60, delivery_state_sessions=2),
    )
    fake_codex.executable.write_text("#!" + sys.executable + "\n" + RECOVERY_RUNTIME)
    batch = harness / "budget-replacement-batch.yml"
    batch.write_text(
        "tasks:\n"
        "  - ticket_id: \"76\"\n"
        "    ticket_name: session-alias-control\n"
        "    role: coding-team.team-leader\n",
        encoding="utf-8",
    )
    launch_environment = {
        **environment,
        "GRAPHTRAJ_AGENT_RUNNER": str(installed_commands.runner),
        "RECOVERY_TARGET": "provider-replace",
    }
    failed = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch)],
        cwd=harness,
        env=launch_environment,
        timeout=30,
    )
    assert failed.returncode == 1
    ticket = harness / ".graphtraj/state/tickets/76-session-alias-control"
    mapping = next(
        yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in (harness / ".graphtraj/runner/sessions").glob("*/mapping.yml")
        if yaml.safe_load(path.read_text(encoding="utf-8"))["role"] == "engineer-junior"
    )
    cause = [
        json.loads(line)["event_id"]
        for path in (harness / ".graphtraj/state/worldline").glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ][-1]

    replaced = run_process(
        [
            str(installed_commands.runner),
            "replace",
            mapping["alias"],
            "--actor",
            "main",
            "--caused-by-event-id",
            cause,
        ],
        cwd=harness,
        env=launch_environment,
        timeout=30,
    )

    assert replaced.returncode == 0, replaced.stdout + replaced.stderr
    usage = yaml.safe_load((ticket / "execution-budget.yml").read_text(encoding="utf-8"))
    assert usage["sessions"]["engineer"] == 2
    notices = _stderr_notices(replaced.stderr)
    assert len(notices) == 1
    assert notices[0]["threshold"] == {"kind": "planned_sessions.engineer", "limit": 1}
    assert notices[0]["actual"]["sessions"]["engineer"] == 2
    assert notices[0]["stage"] == "implementation"
    assert notices[0]["responsible_role"] == "engineer-junior"


def test_installed_send_notifies_its_caller_while_a_budgeted_resume_runs(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path
    )
    _register_ready_ticket(
        installed_commands,
        harness,
        body=_budget_body(total=60),
    )
    batch = harness / "budget-send-batch.yml"
    batch.write_text(
        "tasks:\n"
        "  - ticket_id: \"76\"\n"
        "    ticket_name: session-alias-control\n"
        "    role: coding-team.team-leader\n",
        encoding="utf-8",
    )
    launched = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch)],
        cwd=harness,
        env={
            **environment,
            "FAKE_CODEX_LIFECYCLE_ACTION": "complete-team-round",
            "GRAPHTRAJ_AGENT_RUNNER": str(installed_commands.runner),
        },
        timeout=30,
    )
    assert launched.returncode == 0, launched.stdout + launched.stderr
    ticket = harness / ".graphtraj/state/tickets/76-session-alias-control"
    team_file = ticket / "teams/1/team.yml"
    team = yaml.safe_load(team_file.read_text(encoding="utf-8"))
    team["current_round"] = 2
    team_file.write_text(yaml.safe_dump(team), encoding="utf-8")
    mapping_file = next(
        path
        for path in (harness / ".graphtraj/runner/sessions").glob("*/mapping.yml")
        if yaml.safe_load(path.read_text(encoding="utf-8"))["role"] == "team-leader"
    )
    mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
    cause = [
        json.loads(line)["event_id"]
        for path in (harness / ".graphtraj/state/worldline").glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ][-1]
    evidence = harness / "send-budget-revision.md"
    evidence.write_text("Caller approved the resumed elapsed budget.\n", encoding="utf-8")
    revision = harness / "send-budget-revision.yml"
    revised = _budget_body(
        total=0.01,
        revision_reason="Caller approved the retained Session retry budget",
    )
    revision.write_text(
        yaml.safe_dump(
            {
                "product_preserving": True,
                "caused_by_event_ids": [],
                "evidence_refs": ["send-budget-revision.md"],
                "tickets": [
                    {
                        "ticket_id": "76",
                        "ticket_name": "session-alias-control",
                        "source": "https://github.com/example/project/issues/76",
                        "title": "Session Alias Control",
                        "body": revised,
                        "dependencies": [],
                        "active": True,
                        "replaced_by": [],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    revised_result = run_process(
        [
            str(installed_commands.product),
            "ticket",
            "revise",
            "--revision-file",
            str(revision),
        ],
        cwd=harness,
    )
    assert revised_result.returncode == 0, revised_result.stderr

    release = tmp_path / "release-sent-leader"
    stdout = tmp_path / "send.stdout"
    stderr = tmp_path / "send.stderr"
    send_environment = {
        **environment,
        "FAKE_CODEX_EVENTS": json.dumps(
            [
                {"type": "thread.started", "thread_id": mapping["session"]},
                {"type": "turn.started"},
            ]
        ),
        "FAKE_CODEX_LIFECYCLE_ACTION": "complete-team-round",
        "FAKE_CODEX_APPEND_LOG": "1",
        "FAKE_CODEX_CAPTURE_STDIN": "1",
        "FAKE_CODEX_CAPTURE_ROLE": "1",
        "FAKE_CODEX_RELEASE_FILE": str(release),
        "GRAPHTRAJ_AGENT_RUNNER": str(installed_commands.runner),
    }
    with stdout.open("w+", encoding="utf-8") as out, stderr.open(
        "w+", encoding="utf-8"
    ) as err:
        sent = subprocess.Popen(
            [
                str(installed_commands.runner),
                "send",
                mapping["alias"],
                "--instruction",
                "Retry the retained Team Leader Session.",
                "--caused-by-event-id",
                cause,
            ],
            cwd=harness,
            env=send_environment,
            text=True,
            stdout=out,
            stderr=err,
        )
        try:
            assert sent.wait(timeout=10) == 0
            assert yaml.safe_load(stdout.read_text(encoding="utf-8")) == {
                "alias": mapping["alias"],
                "send_status": "sent",
            }
            deadline = time.monotonic() + 5
            notices = _notices(stderr)
            while not notices and time.monotonic() < deadline:
                time.sleep(0.02)
                notices = _notices(stderr)

            assert len(notices) == 1
            assert notices[0]["threshold"] == {
                "kind": "elapsed_minutes",
                "limit": 0.01,
            }
            deadline = time.monotonic() + 5
            while True:
                running = run_process(
                    [str(installed_commands.runner), "status", mapping["alias"]],
                    cwd=harness,
                    env=environment,
                )
                if (
                    yaml.safe_load(running.stdout)["aliases"][0]["activity"]
                    == "running"
                    or time.monotonic() >= deadline
                ):
                    break
                time.sleep(0.02)
            assert yaml.safe_load(running.stdout)["aliases"][0]["activity"] == "running"
            assert yaml.safe_load(mapping_file.read_text(encoding="utf-8"))["session"] == mapping["session"]
            assert (mapping_file.parent / "resume.yml").is_file()
        finally:
            release.touch()
    wait_for_file(mapping_file.parent / "execution.yml")
    trace = ticket / "teams/1/traces" / mapping["alias"] / "events.jsonl"
    assert cause in trace.read_text(encoding="utf-8")
    assert (mapping_file.parent / "worker-stderr.log").is_file()

    usage_file = ticket / "execution-budget.yml"
    usage = yaml.safe_load(usage_file.read_text(encoding="utf-8"))
    clock = tmp_path / "send-stop-clock"
    clock.write_text(
        str(
            usage["started_at"]
            + (0.01 + usage["allowance_minutes"] + 2.1) * 60
        ),
        encoding="utf-8",
    )
    controls = tmp_path / "send-stop-controls"
    controls.mkdir()
    (controls / "sitecustomize.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "try:\n"
        "    import graphtraj.execution_budget as budget\n"
        "except ModuleNotFoundError:\n"
        "    pass\n"
        "else:\n"
        "    budget.time.time = lambda: float(Path(os.environ['BUDGET_CLOCK']).read_text())\n"
        "    budget.random.random = lambda: 0.99\n",
        encoding="utf-8",
    )
    stopped_environment = {
        **environment,
        "BUDGET_CLOCK": str(clock),
        "FAKE_CODEX_APPEND_LOG": "1",
        "FAKE_CODEX_CAPTURE_STDIN": "1",
        "FAKE_CODEX_CAPTURE_ROLE": "1",
        "FAKE_CODEX_LIFECYCLE_ACTION": "complete-team-round",
        "GRAPHTRAJ_AGENT_RUNNER": str(installed_commands.runner),
        "PYTHONPATH": str(controls),
    }
    stopped_send = run_process(
        [
            str(installed_commands.runner),
            "send",
            mapping["alias"],
            "--instruction",
            "Continue the retained Leader work.",
            "--caused-by-event-id",
            cause,
        ],
        cwd=harness,
        env=stopped_environment,
    )
    assert stopped_send.returncode == 0, stopped_send.stderr
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        usage = yaml.safe_load(usage_file.read_text(encoding="utf-8"))
        execution_file = mapping_file.parent / "execution.yml"
        if (
            usage["stopped"]
            and all(notice["delivered"] for notice in usage["leader_notices"])
            and execution_file.is_file()
            and yaml.safe_load(execution_file.read_text(encoding="utf-8"))[
                "outcome"
            ]
            == "completed"
        ):
            break
        time.sleep(0.02)
    assert yaml.safe_load(execution_file.read_text(encoding="utf-8"))[
        "outcome"
    ] == "completed"
    leader_inputs = [
        json.loads(line)["stdin"]
        for line in fake_codex.log_file.read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("role") == "team-leader"
        and "stdin" in json.loads(line)
    ]
    assert "Execution was stopped by Runner" in leader_inputs[-1]
    assert "must stop" in leader_inputs[-1]
    usage = yaml.safe_load(usage_file.read_text(encoding="utf-8"))
    assert all(notice["delivered"] for notice in usage["leader_notices"])
    assert (ticket / "teams/1/rounds/2/leader.md").is_file()


def test_installed_send_delivers_elapsed_notices_to_the_resumed_leader(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path
    )
    _register_ready_ticket(
        installed_commands, harness, body=_budget_body(total=1)
    )
    clock = tmp_path / "detached-leader-clock"
    clock.write_text(str(time.time()), encoding="utf-8")
    started = float(clock.read_text(encoding="utf-8"))
    controls = tmp_path / "detached-leader-controls"
    controls.mkdir()
    (controls / "sitecustomize.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "try:\n"
        "    import graphtraj.execution_budget as budget\n"
        "except ModuleNotFoundError:\n"
        "    pass\n"
        "else:\n"
        "    budget.time.time = lambda: float(Path(os.environ['BUDGET_CLOCK']).read_text())\n"
        "    budget.random.uniform = lambda lower, upper: lower\n"
        "    budget.random.random = lambda: 0.99\n",
        encoding="utf-8",
    )
    batch = harness / "detached-leader-notices-batch.yml"
    batch.write_text(
        "tasks:\n"
        "  - ticket_id: \"76\"\n"
        "    ticket_name: session-alias-control\n"
        "    role: coding-team.team-leader\n",
        encoding="utf-8",
    )
    run_environment = {
        **environment,
        "BUDGET_CLOCK": str(clock),
        "FAKE_CODEX_APPEND_LOG": "1",
        "FAKE_CODEX_CAPTURE_STDIN": "1",
        "FAKE_CODEX_CAPTURE_ROLE": "1",
        "FAKE_CODEX_LIFECYCLE_ACTION": "complete-team-round",
        "GRAPHTRAJ_AGENT_RUNNER": str(installed_commands.runner),
        "PYTHONPATH": str(controls),
    }
    completed = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch)],
        cwd=harness,
        env=run_environment,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    alias = yaml.safe_load(completed.stdout)["tasks"][0]["alias"]
    config_file = harness / ".graphtraj/config.yml"
    config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    config["agent_runner"]["max_concurrency"] = 1
    config_file.write_text(yaml.safe_dump(config), encoding="utf-8")
    cause = [
        json.loads(line)["event_id"]
        for path in (harness / ".graphtraj/state/worldline").glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ][-1]
    release = tmp_path / "release-detached-leader-notices"
    run_environment.pop("FAKE_CODEX_LIFECYCLE_ACTION")
    run_environment["FAKE_CODEX_RELEASE_FILE"] = str(release)
    usage_file = (
        harness
        / ".graphtraj/state/tickets/76-session-alias-control/execution-budget.yml"
    )
    stdout = tmp_path / "detached-leader-notices.stdout"
    stderr = tmp_path / "detached-leader-notices.stderr"
    with stdout.open("w", encoding="utf-8") as out, stderr.open(
        "w", encoding="utf-8"
    ) as err:
        sent = subprocess.Popen(
            [
                str(installed_commands.runner),
                "send",
                alias,
                "--instruction",
                "Inspect the retained result.",
                "--caused-by-event-id",
                cause,
            ],
            cwd=harness,
            env=run_environment,
            text=True,
            stdout=out,
            stderr=err,
        )
        assert sent.wait(timeout=10) == 0
    clock.write_text(str(started + 67), encoding="utf-8")
    try:
        deadline = time.monotonic() + 10
        leader_inputs = []
        while time.monotonic() < deadline:
            usage = yaml.safe_load(usage_file.read_text(encoding="utf-8"))
            leader_inputs = [
                json.loads(line)["stdin"]
                for line in fake_codex.log_file.read_text(encoding="utf-8").splitlines()
                if json.loads(line).get("role") == "team-leader"
                and "stdin" in json.loads(line)
            ]
            if (
                len(usage["leader_notices"]) == 2
                and all(notice["delivered"] for notice in usage["leader_notices"])
                and leader_inputs
                and "additional allowance of 00:00:06" in leader_inputs[-1]
            ):
                break
            time.sleep(0.02)
        assert not release.exists()
        assert len(usage["leader_notices"]) == 2
        assert all(notice["delivered"] for notice in usage["leader_notices"])
        assert "The planned budget of 00:01:00 has been reached" in leader_inputs[-1]
        assert "additional allowance of 00:00:06" in leader_inputs[-1]
        assert "Inspect the retained result." in leader_inputs[-1]
        assert "read-only Worktree access" not in leader_inputs[-1]
    finally:
        release.touch()


def test_installed_runner_counts_implementation_rework_as_correction(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path
    )
    _register_ready_ticket(
        installed_commands,
        harness,
        body=_budget_body(total=60, correction_rounds=0),
    )
    fake_codex.executable.write_text("#!" + sys.executable + "\n" + RECOVERY_RUNTIME)
    batch = harness / "budget-rework-batch.yml"
    batch.write_text(
        "tasks:\n"
        "  - ticket_id: \"76\"\n"
        "    ticket_name: session-alias-control\n"
        "    role: coding-team.team-leader\n",
        encoding="utf-8",
    )
    runtime_environment = {
        **environment,
        "GRAPHTRAJ_AGENT_RUNNER": str(installed_commands.runner),
        "RECOVERY_TARGET": "provider-rework",
    }
    failed = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch)],
        cwd=harness,
        env=runtime_environment,
        timeout=45,
    )
    assert failed.returncode == 1
    ticket = harness / ".graphtraj/state/tickets/76-session-alias-control"
    mapping_file = next(
        path
        for path in (harness / ".graphtraj/runner/sessions").glob("*/mapping.yml")
        if yaml.safe_load(path.read_text(encoding="utf-8"))["role"] == "engineer-junior"
    )
    mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
    cause = [
        json.loads(line)["event_id"]
        for path in (harness / ".graphtraj/state/worldline").glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ][-1]
    retried = run_process(
        [
            str(installed_commands.runner),
            "send",
            mapping["alias"],
            "--instruction",
            "Retry the interrupted current Team step.",
            "--caused-by-event-id",
            cause,
        ],
        cwd=harness,
        env=runtime_environment,
        timeout=45,
    )
    assert retried.returncode == 0, retried.stdout + retried.stderr
    wait_for_file(mapping_file.parent / "execution.yml")

    continued = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch)],
        cwd=harness,
        env=runtime_environment,
        timeout=45,
    )

    assert continued.returncode == 0, continued.stdout + continued.stderr
    usage = yaml.safe_load((ticket / "execution-budget.yml").read_text(encoding="utf-8"))
    assert usage["corrections"] == 1
    events = [
        json.loads(line)
        for path in (harness / ".graphtraj/state/worldline").glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(event["kind"] == "team-round-rework-started" for event in events)
    assert not any(event["kind"] == "team-process-correction" for event in events)
    notices = _stderr_notices(continued.stderr)
    assert len(notices) == 1
    assert notices[0]["threshold"] == {"kind": "correction_rounds", "limit": 0}
    assert notices[0]["stage"] == "correction"
    assert notices[0]["responsible_role"] == "engineer-junior"
