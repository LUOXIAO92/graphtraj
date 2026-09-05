from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from conftest import PROJECT_ROOT, InstalledCommands, run_process


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


def _configure_project(project: Path) -> Path:
    state = project / ".graphtraj" / "operator-state"
    config = project / ".graphtraj" / "config.yml"
    config.parent.mkdir()
    config.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "paths": {
                    "project_root": ".",
                    "docs": "docs",
                    "agent_worktrees": ".graphtraj/worktrees",
                    "state": ".graphtraj/operator-state",
                },
                "agent_runner": {"dispatch_depth": 1, "max_concurrency": 2},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    state.mkdir()
    return state


def _event_file(project: Path, name: str, event: object) -> Path:
    path = project / name
    path.write_text(yaml.safe_dump(event, sort_keys=False), encoding="utf-8")
    return path


def _worldline(
    commands: InstalledCommands,
    project: Path,
    *arguments: str,
    timezone: str = "Asia/Tokyo",
):
    environment = os.environ.copy()
    environment["TZ"] = timezone
    return run_process(
        [str(commands.product), "worldline", *arguments],
        cwd=project,
        env=environment,
    )


def test_installed_command_appends_reads_and_renders_project_worldline(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    state = _configure_project(project)
    evidence = state / "evidence" / "candidate.txt"
    evidence.parent.mkdir()
    evidence.write_text("candidate\n", encoding="utf-8")
    first_file = _event_file(
        project,
        "first.yml",
        {
            "kind": "user-decision",
            "caused_by_event_ids": [],
            "evidence_refs": [],
            "decision": "Use the candidate.",
        },
    )

    first_result = _worldline(
        installed_commands, project, "append", "--event-file", str(first_file)
    )

    assert first_result.returncode == 0, first_result.stderr
    first = yaml.safe_load(first_result.stdout)
    assert re.fullmatch(
        r"\d{8}T\d{6}\.\d{6}\+0900(?:-\d+)?", first["event_id"]
    )
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+09:00",
        first["captured_at"],
    )
    second_file = _event_file(
        project,
        "second.yml",
        {
            "kind": "candidate-recorded",
            "caused_by_event_ids": [first["event_id"]],
            "evidence_refs": ["evidence/candidate.txt"],
            "candidate_commit": "a" * 40,
        },
    )
    second_result = _worldline(
        installed_commands,
        project,
        "append",
        "--event-file",
        str(second_file),
        timezone="America/Los_Angeles",
    )

    assert second_result.returncode == 0, second_result.stderr
    second = yaml.safe_load(second_result.stdout)
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}-07:00",
        second["captured_at"],
    )
    read_result = _worldline(installed_commands, project, "read")
    assert read_result.returncode == 0, read_result.stderr
    assert [json.loads(line) for line in read_result.stdout.splitlines()] == [
        first,
        second,
    ]
    render_result = _worldline(installed_commands, project, "render")
    assert render_result.returncode == 0, render_result.stderr
    assert yaml.safe_load(render_result.stdout) == {"trajectory": [first, second]}
    assert not (state / "ledger.yml").exists()
    assert not (state / "dag.md").exists()


@pytest.mark.parametrize(
    "event,error",
    [
        (
            {
                "kind": "candidate-recorded",
                "caused_by_event_ids": ["missing-event"],
                "evidence_refs": [],
            },
            "causal predecessor",
        ),
        (
            {
                "kind": "candidate-recorded",
                "caused_by_event_ids": [],
                "evidence_refs": ["evidence/missing.txt"],
            },
            "retained evidence",
        ),
        (
            {
                "kind": "candidate-recorded",
                "caused_by_event_ids": [],
                "evidence_refs": [],
                "captured_at": "2026-09-05T12:00:00+09:00",
            },
            "assigned fields",
        ),
        (
            {"kind": "Not a plain kind", "caused_by_event_ids": [], "evidence_refs": []},
            "plain kind",
        ),
        ([], "mapping"),
    ],
)
def test_invalid_event_is_rejected_without_append(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    event: object,
    error: str,
) -> None:
    project = temporary_git_repository
    state = _configure_project(project)
    event_file = _event_file(project, "event.yml", event)

    result = _worldline(
        installed_commands, project, "append", "--event-file", str(event_file)
    )

    assert result.returncode == 1
    assert error in result.stderr
    assert not tuple((state / "worldline").glob("*.jsonl"))


@pytest.mark.parametrize(
    "kind",
    [
        "synchronization",
        "unchanged-polling",
        "heartbeat",
        "no-op-retry",
        "projection-regeneration",
        "repeated-read",
    ],
)
def test_operation_without_a_new_fact_creates_no_event(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    kind: str,
) -> None:
    project = temporary_git_repository
    state = _configure_project(project)
    event_file = _event_file(
        project,
        "event.yml",
        {"kind": kind, "caused_by_event_ids": [], "evidence_refs": []},
    )

    result = _worldline(
        installed_commands, project, "append", "--event-file", str(event_file)
    )

    assert result.returncode == 1
    assert "durable fact" in result.stderr
    assert not tuple((state / "worldline").glob("*.jsonl"))


def test_installed_command_rolls_200_events_into_a_new_immutable_shard(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    state = _configure_project(project)
    event_file = project / "event.yml"
    predecessor: str | None = None

    for number in range(201):
        event_file.write_text(
            yaml.safe_dump(
                {
                    "kind": "fact-recorded",
                    "caused_by_event_ids": [predecessor] if predecessor else [],
                    "evidence_refs": [],
                    "number": number,
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        timezone = "Asia/Tokyo" if number < 200 else "America/Los_Angeles"
        result = _worldline(
            installed_commands,
            project,
            "append",
            "--event-file",
            str(event_file),
            timezone=timezone,
        )
        assert result.returncode == 0, result.stderr
        predecessor = yaml.safe_load(result.stdout)["event_id"]

    shards = tuple((state / "worldline").glob("*.jsonl"))
    assert len(shards) == 2
    shard_lengths = sorted(
        len(path.read_text(encoding="utf-8").splitlines()) for path in shards
    )
    assert shard_lengths == [1, 200]
    full_shard = next(
        path
        for path in shards
        if len(path.read_text(encoding="utf-8").splitlines()) == 200
    )
    full_contents = full_shard.read_bytes()
    read_result = _worldline(installed_commands, project, "read")
    assert read_result.returncode == 0, read_result.stderr
    assert len(read_result.stdout.splitlines()) == 201
    assert full_shard.read_bytes() == full_contents
    assert json.loads(read_result.stdout.splitlines()[-1])["number"] == 200
    assert sorted(shards)[0] != full_shard


def test_malformed_retained_history_prevents_an_append(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    state = _configure_project(project)
    event_file = _event_file(
        project,
        "event.yml",
        {
            "kind": "fact-recorded",
            "caused_by_event_ids": [],
            "evidence_refs": [],
            "fact": "first",
        },
    )
    first = _worldline(
        installed_commands, project, "append", "--event-file", str(event_file)
    )
    assert first.returncode == 0, first.stderr
    shard = next((state / "worldline").glob("*.jsonl"))
    malformed = json.loads(shard.read_text(encoding="utf-8"))
    malformed["captured_at"] = malformed["captured_at"].replace(".000000", "")
    if malformed["captured_at"] == yaml.safe_load(first.stdout)["captured_at"]:
        malformed["captured_at"] = "2026-09-05T12:00:00+09:00"
    shard.write_text(json.dumps(malformed) + "\n", encoding="utf-8")
    before = shard.read_bytes()

    result = _worldline(
        installed_commands, project, "append", "--event-file", str(event_file)
    )

    assert result.returncode == 1
    assert "malformed timestamp" in result.stderr
    assert shard.read_bytes() == before


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
    projection = yaml.safe_load(original_projection)
    assert projection["run_id"] == run_id
    assert [group["kind"] for group in projection["trajectory"]] == [
        "agent-turn",
        "user-input",
        "review-round",
        "main-decision",
    ]
    assert projection["trajectory"][0]["events"] == [journal[0]]
    assert projection["trajectory"][1]["event"] == journal[1]
    review_round = projection["trajectory"][2]
    assert review_round["review_round"] == 1
    assert [turn["alias"] for turn in review_round["agent_turns"]] == [
        "r2",
        "r1",
    ]
    assert [turn["events"] for turn in review_round["agent_turns"]] == [
        [journal[2]],
        [journal[3]],
    ]
    decision = projection["trajectory"][3]
    assert decision["event"] == journal[4]
    assert decision["task_state_changes"] == [journal[5]]
    assert decision["dag_changes"] == [journal[6]]
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
