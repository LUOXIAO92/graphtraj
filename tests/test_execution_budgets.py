from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import yaml

from conftest import FakeCodex, InstalledCommands, run_process
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

        assert len(notices) == 1
        notice = notices[0]
        assert notice["ticket"] == {
            "ticket_id": "82",
            "ticket_name": "adapter-probe",
        }
        assert notice["threshold"] == {"kind": "elapsed_minutes", "limit": 0.01}
        assert notice["stage"] == "implementation"
        assert notice["responsible_role"] == "engineer-junior"
        assert notice["actual"]["elapsed_minutes"] >= 0.01

        status = run_process(
            [str(installed_commands.runner), "status", alias],
            cwd=harness,
            env=probe_environment,
        )
        assert status.returncode == 0, status.stderr
        assert yaml.safe_load(status.stdout)["aliases"][0]["activity"] == "running"
        release.touch()


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
