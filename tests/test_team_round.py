from __future__ import annotations

import json
import os
from pathlib import Path

import yaml
import pytest

from conftest import FakeCodex, InstalledCommands, run_process, wait_for_file
from test_agent_runner_batch import configure_harness


@pytest.mark.parametrize(
    ("leader_decision", "expected_status", "round_closed"),
    (("accept", "awaiting-integration", True), ("reject", "reviewing", False)),
)
def test_installed_runner_obeys_the_explicit_leader_decision_for_a_run_free_team_round(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    leader_decision: str,
    expected_status: str,
    round_closed: bool,
) -> None:
    harness_root, worktree_root, _, environment = configure_harness(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    ticket_input = harness_root / "ticket.yml"
    ticket_input.write_text(
        yaml.safe_dump(
            {
                "ticket_id": "74",
                "ticket_name": "complete-team-round",
                "source": "https://github.com/example/project/issues/74",
                "title": "Complete Team Round",
                "body": "Deliver one complete Team Round.",
                "dependencies": [],
            },
            sort_keys=False,
        )
    )
    registered = run_process(
        [str(installed_commands.product), "ticket", "register", "--ticket-file", str(ticket_input)],
        cwd=harness_root,
    )
    assert registered.returncode == 0, registered.stderr
    ticket_directory = harness_root / ".graphtraj" / "state" / "tickets" / "74-complete-team-round"
    readiness = harness_root / "readiness.md"
    readiness.write_text("The registered Ticket has no unmet dependencies.\n")
    state_change = harness_root / "state-change.yml"
    state_change.write_text(
        yaml.safe_dump(
            {
                "ticket_id": "74",
                "status": "ready",
                "active_team_ordinal": None,
                "worktree": None,
                "branch": None,
                "current_candidate": None,
                "caused_by_event_ids": [],
                "evidence_refs": ["readiness.md"],
            },
            sort_keys=False,
        )
    )
    ready = run_process(
        [str(installed_commands.product), "ticket", "update", "--state-file", str(state_change)],
        cwd=harness_root,
    )
    assert ready.returncode == 0, ready.stderr

    batch = harness_root / "batch.yml"
    batch_bytes = (
        "tasks:\n"
        "  - ticket_id: \"74\"\n"
        "    ticket_name: complete-team-round\n"
        "    role: team-leader\n"
        "    instruction: Keep the accepted Ticket exact.\n"
    ).encode()
    batch.write_bytes(batch_bytes)
    environment.update(
        {
            "FAKE_CODEX_LIFECYCLE_ACTION": "complete-team-round",
            "GRAPHTRAJ_AGENT_RUNNER": str(installed_commands.runner),
            "FAKE_CODEX_LEADER_DECISION": leader_decision,
        }
    )

    launched = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch)],
        cwd=harness_root,
        env=environment,
        timeout=10,
    )

    assert launched.returncode == 0, launched.stderr
    output = yaml.safe_load(launched.stdout)
    assert "run_id" not in output
    retained = Path(output["retained_batch_file"])
    assert retained.parent == harness_root / ".graphtraj" / "state" / "batches"
    assert retained.read_bytes() == batch_bytes
    retained_batches = list(retained.parent.glob("*.yml"))
    assert len(retained_batches) == 3
    worktree = worktree_root / "74-complete-team-round"
    assert output["tasks"][0]["worktree_path"] == str(worktree.resolve())
    wait_for_file(ticket_directory / "teams" / "1" / "rounds" / "1" / "leader.md", 15)

    current = yaml.safe_load((ticket_directory / "ticket.yml").read_text())
    team = yaml.safe_load((ticket_directory / "teams" / "1" / "team.yml").read_text())
    assert current["status"] == expected_status
    assert current["active_team_ordinal"] == 1
    assert current["worktree"] == ".graphtraj/.agent-worktrees/74-complete-team-round"
    assert current["branch"] == "agent/74-complete-team-round"
    assert len(current["current_candidate"]) == 40
    assert set(team) == {
        "team_ordinal", "status", "members", "current_round", "started_at"
    }
    assert team["team_ordinal"] == 1
    assert team["status"] == "active"
    assert team["current_round"] == 1
    assert set(team["members"]) == {
        "team_leader",
        "engineer",
        "standards_reviewer",
        "spec_reviewer",
    }
    assert all(set(member) == {"role", "session_ref"} for member in team["members"].values())
    assert all(member["session_ref"] for member in team["members"].values())
    round_directory = ticket_directory / "teams" / "1" / "rounds" / "1"
    assert {path.name for path in round_directory.iterdir()} == {
        "engineer.md", "validation.md", "standards.md", "spec.md", "leader.md"
    }
    assert (round_directory.stat().st_mode & 0o222 == 0) is round_closed
    assert all((path.stat().st_mode & 0o222 == 0) is round_closed for path in round_directory.iterdir())
    traces = list((ticket_directory / "teams" / "1" / "traces").glob("*/events.jsonl"))
    assert len(traces) >= 5
    mappings = [
        yaml.safe_load(path.read_text())
        for path in (harness_root / ".codex" / "agent-runner" / "sessions").glob("*/mapping.yml")
    ]
    assert len(mappings) >= 5
    assert all("run_id" not in mapping and "turn" not in mapping for mapping in mappings)
    leader_alias = next(mapping["alias"] for mapping in mappings if mapping["role"] == "team-leader")
    delivery_state_mappings = [mapping for mapping in mappings if mapping["role"] == "delivery-state"]
    assert len(delivery_state_mappings) == 1
    assert delivery_state_mappings[0]["alias"] not in {
        member["session_ref"] for member in team["members"].values()
    }
    assert all(
        mapping["parent"] == leader_alias
        for mapping in mappings
        if mapping["role"] not in {"team-leader", "delivery-state"}
    )
    assert not list(ticket_directory.rglob("turn-*"))
    assert not (ticket_directory / "metadata.yml").exists()
    assert not (ticket_directory / "handoff.md").exists()
    assert not (harness_root / ".graphtraj" / "state" / "runs").exists()
    assert not any(path.name in {"ledger.yml", "dag.md", "history.jsonl"} for path in ticket_directory.rglob("*"))
    worldline = [
        json.loads(line)
        for shard in (harness_root / ".graphtraj" / "state" / "worldline").glob("*.jsonl")
        for line in shard.read_text().splitlines()
    ]
    assert worldline[-1]["kind"] == (
        "team-round-accepted" if round_closed else "team-round-rejected"
    )
    started = next(event for event in worldline if event["kind"] == "team-started")
    assert team["started_at"] == started["captured_at"]
    assert all(event["caused_by_event_ids"] for event in worldline[2:])
    assert all(path.stat().st_mode & 0o222 == 0 for path in retained_batches)
