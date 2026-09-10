from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from conftest import PROJECT_ROOT, InstalledCommands, run_process


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
    evidence = project / "evidence" / "candidate.txt"
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
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}-(?:07|08):00",
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
    shard_contents = {
        path: path.read_bytes() for path in (state / "worldline").glob("*.jsonl")
    }
    evidence.unlink()
    read_after_removal = _worldline(installed_commands, project, "read")
    assert read_after_removal.returncode == 0, read_after_removal.stderr
    assert [json.loads(line) for line in read_after_removal.stdout.splitlines()] == [
        first,
        second,
    ]
    assert _worldline(installed_commands, project, "render").returncode == 0
    new_evidence = project / "evidence" / "new-candidate.txt"
    new_evidence.write_text("new candidate\n", encoding="utf-8")
    third_file = _event_file(
        project,
        "third.yml",
        {
            "kind": "candidate-recorded",
            "caused_by_event_ids": [second["event_id"]],
            "evidence_refs": ["evidence/new-candidate.txt"],
            "candidate_commit": "b" * 40,
        },
    )

    third_result = _worldline(
        installed_commands, project, "append", "--event-file", str(third_file)
    )

    assert third_result.returncode == 0, third_result.stderr
    assert all(
        path.read_bytes().startswith(contents)
        for path, contents in shard_contents.items()
    )


@pytest.mark.parametrize(
    "event",
    [
        {
            "kind": "candidate-recorded",
            "caused_by_event_ids": ["missing-event"],
            "evidence_refs": [],
        },
        {
            "kind": "candidate-recorded",
            "caused_by_event_ids": [],
            "evidence_refs": ["evidence/missing.txt"],
        },
        {
            "kind": "candidate-recorded",
            "caused_by_event_ids": [],
            "evidence_refs": [],
            "captured_at": "2026-09-05T12:00:00+09:00",
        },
        {"kind": "Not a plain kind", "caused_by_event_ids": [], "evidence_refs": []},
        [],
    ],
)
def test_invalid_event_is_rejected_without_append(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    event: object,
) -> None:
    project = temporary_git_repository
    state = _configure_project(project)
    event_file = _event_file(project, "event.yml", event)

    result = _worldline(
        installed_commands, project, "append", "--event-file", str(event_file)
    )

    assert result.returncode == 1
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
    assert shard.read_bytes() == before


def test_same_instant_offset_collisions_keep_causal_order_across_shards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_ROOT / "src"))
    monkeypatch.chdir(tmp_path)
    state = _configure_project(tmp_path)
    from graphtraj.cli import main
    from graphtraj import delivery_worldline

    instant = datetime(2026, 1, 1, tzinfo=timezone.utc)

    captured_times = iter(
        instant.astimezone(timezone(timedelta(hours=9 if number % 2 == 0 else -8)))
        for number in range(201)
    )
    monkeypatch.setattr(delivery_worldline, "_capture_time", lambda: next(captured_times))
    event_file = tmp_path / "event.yml"
    predecessor: str | None = None
    event_ids = []
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
        result = CliRunner().invoke(
            main, ["worldline", "append", "--event-file", str(event_file)]
        )
        assert result.exit_code == 0, result.output
        predecessor = yaml.safe_load(result.output)["event_id"]
        event_ids.append(predecessor)

    assert event_ids[0] == "20260101T090000.000000+0900"
    assert event_ids[1] == "20251231T160000.000000-0800-1"
    assert event_ids[200] == "20260101T090000.000000+0900-200"
    shards = tuple((state / "worldline").glob("*.jsonl"))
    assert {path.stem for path in shards} == {event_ids[0], event_ids[200]}
    assert sorted(
        len(path.read_text(encoding="utf-8").splitlines()) for path in shards
    ) == [1, 200]
    read_result = CliRunner().invoke(main, ["worldline", "read"])
    assert read_result.exit_code == 0, read_result.output
    events = [json.loads(line) for line in read_result.output.splitlines()]
    assert [event["number"] for event in events] == list(range(201))
    assert events[200]["caused_by_event_ids"] == [events[199]["event_id"]]
