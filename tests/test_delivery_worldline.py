from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from conftest import PROJECT_ROOT


def _trace(
    run_root: Path, ticket_stem: str, alias: str, turn: int
) -> str:
    relative = Path(
        "tickets",
        ticket_stem,
        "traces",
        alias,
        "turn-{0}".format(turn),
        "events.jsonl",
    )
    trace = run_root / relative
    trace.parent.mkdir(parents=True, exist_ok=True)
    trace.write_text('{"type":"turn.completed"}\n', encoding="utf-8")
    return relative.as_posix()


def test_atomic_worldline_projects_interleaved_explicit_events_deterministically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_ROOT / "src"))
    from you_are_a_product_architect.delivery_worldline import (
        append_worldline_event,
        project_worldline,
    )

    run_id = "20260829-atomic-worldline"
    run_root = tmp_path / run_id
    engineer_trace = _trace(run_root, "2-61-worldline", "e1", 1)
    spec_trace = _trace(run_root, "2-61-worldline", "r2", 1)
    standards_trace = _trace(run_root, "2-61-worldline", "r1", 1)

    supplied_events = (
        {
            "kind": "agent-turn-terminal",
            "ticket_id": "61",
            "role": "engineer-senior",
            "alias": "e1",
            "turn": 1,
            "outcome": "completed",
            "trace_ref": engineer_trace,
        },
        {
            "kind": "user-input",
            "ticket_id": "61",
            "input": "Keep the two review axes independent.",
            "caused_by_worldline_seqs": [1],
        },
        {
            "kind": "agent-turn-terminal",
            "ticket_id": "61",
            "role": "spec-reviewer",
            "alias": "r2",
            "turn": 1,
            "review_round": 1,
            "outcome": "completed",
            "trace_ref": spec_trace,
            "caused_by_worldline_seqs": [1],
        },
        {
            "kind": "agent-turn-terminal",
            "ticket_id": "61",
            "role": "standards-reviewer",
            "alias": "r1",
            "turn": 1,
            "review_round": 1,
            "outcome": "completed",
            "trace_ref": standards_trace,
            "caused_by_worldline_seqs": [1],
        },
        {
            "kind": "main-decision",
            "ticket_id": "61",
            "review_round": 1,
            "candidate_commit": "a" * 40,
            "accepted_findings": ["spec finding"],
            "rejected_findings": ["unsupported recovery request"],
            "verdict": "FAIL",
            "caused_by_worldline_seqs": [2, 3, 4],
        },
        {
            "kind": "task-state-change",
            "ticket_id": "61",
            "from_state": "reviewing",
            "to_state": "reworking",
            "caused_by_worldline_seqs": [5],
        },
        {
            "kind": "dag-change",
            "ticket_id": "61",
            "changes": [{"ticket_id": "62", "blocked_by": ["61"]}],
            "caused_by_worldline_seqs": [5],
        },
    )

    recorded = [
        append_worldline_event(run_root, run_id, event)
        for event in supplied_events
    ]

    journal = [
        json.loads(line)
        for line in (run_root / "worldline.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert journal == recorded
    assert [event["worldline_seq"] for event in journal] == list(range(1, 8))
    assert [event["kind"] for event in journal] == [
        event["kind"] for event in supplied_events
    ]
    assert all(event["run_id"] == run_id for event in journal)
    assert all("T" in event["captured_at"] for event in journal)
    assert journal[2]["trace_ref"] == spec_trace
    assert journal[3]["trace_ref"] == standards_trace
    assert journal[4]["caused_by_worldline_seqs"] == [2, 3, 4]
    assert "id" not in {key for event in journal for key in event}

    ledger = run_root / "ledger.yml"
    original_projection = ledger.read_bytes()
    assert yaml.safe_load(original_projection) == {
        "run_id": run_id,
        "trajectory": journal,
    }
    ledger.write_text("stale: true\n", encoding="utf-8")
    project_worldline(run_root)
    assert ledger.read_bytes() == original_projection


def test_product_command_records_explicit_state_agent_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_ROOT / "src"))
    from you_are_a_product_architect.cli import main

    run_id = "20260829-state-agent-event"
    run_root = tmp_path / run_id
    run_root.mkdir()
    event_file = tmp_path / "event.yml"
    event_file.write_text(
        yaml.safe_dump(
            {
                "kind": "user-input",
                "ticket_id": "61",
                "input": "Use the confirmed candidate.",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        main,
        [
            "worldline",
            "append",
            "--run-root",
            str(run_root),
            "--run-id",
            run_id,
            "--event-file",
            str(event_file),
        ],
    )

    assert result.exit_code == 0, result.output
    output = yaml.safe_load(result.output)
    assert output["kind"] == "user-input"
    assert output["worldline_seq"] == 1
    assert (run_root / "ledger.yml").is_file()
