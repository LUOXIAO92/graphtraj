"""Project-scoped append-only Worldline commands."""

from __future__ import annotations

import fcntl
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import click
import yaml

from .delivery_run_worldline import (
    append_worldline_event,
    project_worldline,
)
from .project_configuration import (
    ProjectConfigurationError,
    load_project_configuration,
)


_SHARD_SIZE = 200
_ASSIGNED_FIELDS = frozenset({"event_id", "captured_at", "run_id", "worldline_seq"})
_EVENT_FIELDS = frozenset({"kind", "caused_by_event_ids", "evidence_refs"})
_KIND = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}[+-]\d{2}:\d{2}\Z"
)
_EVENT_ID = re.compile(
    r"(?P<stamp>\d{8}T\d{6}\.\d{6}[+-]\d{4})(?:-(?P<suffix>[1-9]\d*))?\Z"
)
_NON_FACT_KINDS = frozenset(
    {
        "synchronization",
        "state-synchronization",
        "unchanged-poll",
        "unchanged-polling",
        "heartbeat",
        "no-op-retry",
        "projection-regeneration",
        "repeated-read",
    }
)


@click.group()
def worldline() -> None:
    """Append, read, and render the configured project's Worldline."""


@worldline.command("append")
@click.option(
    "--run-root",
    type=click.Path(path_type=Path, file_okay=False),
)
@click.option("--run-id")
@click.option(
    "--event-file",
    required=True,
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
def append_command(
    run_root: Path | None,
    run_id: str | None,
    event_file: Path,
) -> None:
    """Append one explicit durable fact from a YAML file."""

    try:
        event = yaml.safe_load(event_file.read_text(encoding="utf-8"))
        if not isinstance(event, dict):
            raise ValueError("event file must contain one mapping")
        if (run_root is None) != (run_id is None):
            raise ValueError("--run-root and --run-id must be supplied together")
        recorded = (
            append_worldline_event(run_root, run_id, event)
            if run_root is not None and run_id is not None
            else append_project_worldline_event(_configured_state(), event)
        )
    except (
        OSError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(recorded, sort_keys=False), nl=False)


@worldline.command("project")
@click.option(
    "--run-root",
    required=True,
    type=click.Path(path_type=Path, exists=True, file_okay=False),
)
def project_command(run_root: Path) -> None:
    """Regenerate a legacy Run-local ledger.yml."""

    try:
        ledger = project_worldline(run_root)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(str(ledger))


@worldline.command("read")
def read_command() -> None:
    """Read the complete Worldline as chronological JSONL."""

    try:
        events = read_worldline(_configured_state())
    except (
        OSError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    for event in events:
        click.echo(json.dumps(event, ensure_ascii=False, separators=(",", ":")))


@worldline.command("render")
def render_command() -> None:
    """Render a ledger-shaped YAML view without persisting it."""

    try:
        events = read_worldline(_configured_state())
    except (
        OSError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump({"trajectory": events}, sort_keys=False), nl=False)


def _configured_state() -> Path:
    return load_project_configuration(Path.cwd()).state


def append_project_worldline_event(
    state_directory: Path,
    event: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and atomically append one project Worldline event."""

    _validate_supplied_event(event)
    worldline_directory = state_directory / "worldline"
    worldline_directory.mkdir(parents=True, exist_ok=True)
    lock_descriptor = os.open(
        str(worldline_directory / ".lock"), os.O_RDWR | os.O_CREAT, 0o600
    )
    try:
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        shards, existing = _read_shards(state_directory)
        _validate_references(state_directory, event, existing)
        captured = datetime.now().astimezone()
        if existing and captured < _parse_timestamp(existing[-1]["captured_at"]):
            raise ValueError("system time precedes the chronologically last event")
        captured_at = captured.isoformat(timespec="microseconds")
        event_id = _next_event_id(captured, {item["event_id"] for item in existing})
        recorded = {
            "event_id": event_id,
            "captured_at": captured_at,
            **event,
        }
        line = json.dumps(recorded, ensure_ascii=False, separators=(",", ":")) + "\n"
        if shards and len(shards[-1][1]) < _SHARD_SIZE:
            target = shards[-1][0]
        else:
            target = worldline_directory / "{0}.jsonl".format(event_id)
        with target.open("a", encoding="utf-8") as stream:
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
        return recorded
    finally:
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)


def read_worldline(state_directory: Path) -> list[dict[str, Any]]:
    """Return validated events in absolute chronological shard order."""

    worldline_directory = state_directory / "worldline"
    if not worldline_directory.exists():
        return []
    lock_descriptor = os.open(
        str(worldline_directory / ".lock"), os.O_RDWR | os.O_CREAT, 0o600
    )
    try:
        fcntl.flock(lock_descriptor, fcntl.LOCK_SH)
        return _read_shards(state_directory)[1]
    finally:
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)


def _read_shards(
    state_directory: Path,
) -> tuple[list[tuple[Path, list[dict[str, Any]]]], list[dict[str, Any]]]:
    directory = state_directory / "worldline"
    paths = list(directory.glob("*.jsonl")) if directory.is_dir() else []
    paths.sort(key=_shard_order)
    shards: list[tuple[Path, list[dict[str, Any]]]] = []
    events: list[dict[str, Any]] = []
    known_ids: set[str] = set()
    collision_counts: dict[str, int] = {}
    previous_time: datetime | None = None
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines or len(lines) > _SHARD_SIZE:
            raise ValueError("worldline contains an invalid shard")
        shard_events: list[dict[str, Any]] = []
        for line in lines:
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError("worldline contains an invalid event")
            captured = _validate_recorded_event(
                state_directory, item, known_ids, collision_counts
            )
            if previous_time is not None and captured < previous_time:
                raise ValueError("worldline events are not chronological")
            previous_time = captured
            known_ids.add(item["event_id"])
            shard_events.append(item)
            events.append(item)
        if path.stem != shard_events[0]["event_id"]:
            raise ValueError("worldline shard name does not match its first event")
        shards.append((path, shard_events))
    return shards, events


def _validate_supplied_event(event: Mapping[str, Any]) -> None:
    if not isinstance(event, Mapping):
        raise ValueError("worldline event must be a mapping")
    if _ASSIGNED_FIELDS.intersection(event):
        raise ValueError("worldline event contains assigned fields")
    kind = event.get("kind")
    if not isinstance(kind, str) or _KIND.fullmatch(kind) is None:
        raise ValueError("worldline event requires a plain kind")
    if kind in _NON_FACT_KINDS:
        raise ValueError("operation does not introduce a new durable fact")
    _validate_string_list(event, "caused_by_event_ids")
    _validate_string_list(event, "evidence_refs")
    try:
        json.dumps(event, ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise ValueError("worldline event must be JSON serializable") from error


def _validate_string_list(event: Mapping[str, Any], field: str) -> list[str]:
    value = event.get(field)
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise ValueError("worldline event has an invalid {0}".format(field))
    return value


def _validate_references(
    state_directory: Path,
    event: Mapping[str, Any],
    existing: list[dict[str, Any]],
) -> None:
    known_ids = {item["event_id"] for item in existing}
    if any(item not in known_ids for item in event["caused_by_event_ids"]):
        raise ValueError("causal predecessor does not exist")
    _validate_evidence(state_directory, event["evidence_refs"])


def _validate_evidence(state_directory: Path, references: list[str]) -> None:
    root = state_directory.resolve()
    for reference in references:
        relative = Path(reference)
        if relative.is_absolute():
            raise ValueError("retained evidence reference must be state-relative")
        evidence = state_directory / relative
        try:
            evidence.resolve().relative_to(root)
        except (OSError, ValueError) as error:
            raise ValueError("retained evidence reference escapes project state") from error
        if evidence.is_symlink() or not evidence.is_file():
            raise ValueError("retained evidence does not exist")


def _validate_recorded_event(
    state_directory: Path,
    event: Mapping[str, Any],
    known_ids: set[str],
    collision_counts: dict[str, int],
) -> datetime:
    if set(_EVENT_FIELDS | {"event_id", "captured_at"}) - set(event):
        raise ValueError("worldline contains an invalid event")
    event_id = event.get("event_id")
    captured_at = event.get("captured_at")
    if not isinstance(event_id, str) or not isinstance(captured_at, str):
        raise ValueError("worldline contains an invalid event")
    captured = _parse_timestamp(captured_at)
    base = captured.strftime("%Y%m%dT%H%M%S.%f%z")
    expected_count = collision_counts.get(base, 0)
    expected_id = base if expected_count == 0 else "{0}-{1}".format(base, expected_count)
    if event_id != expected_id or event_id in known_ids:
        raise ValueError("worldline contains an invalid event ID")
    collision_counts[base] = expected_count + 1
    supplied = {key: value for key, value in event.items() if key not in {"event_id", "captured_at"}}
    _validate_supplied_event(supplied)
    _validate_references(state_directory, event, [{"event_id": item} for item in known_ids])
    return captured


def _parse_timestamp(value: str) -> datetime:
    if _TIMESTAMP.fullmatch(value) is None:
        raise ValueError("worldline contains a malformed timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("worldline contains a malformed timestamp") from error
    if parsed.utcoffset() is None:
        raise ValueError("worldline contains a malformed timestamp")
    return parsed


def _shard_order(path: Path) -> tuple[datetime, int]:
    match = _EVENT_ID.fullmatch(path.stem)
    if match is None:
        raise ValueError("worldline contains an invalid shard name")
    stamp = match.group("stamp")
    timestamp = "{0}-{1}-{2}T{3}:{4}:{5}{6}:{7}".format(
        stamp[0:4],
        stamp[4:6],
        stamp[6:8],
        stamp[9:11],
        stamp[11:13],
        stamp[13:22],
        stamp[22:25],
        stamp[25:27],
    )
    return _parse_timestamp(timestamp), int(match.group("suffix") or 0)


def _next_event_id(captured: datetime, existing_ids: set[str]) -> str:
    base = captured.strftime("%Y%m%dT%H%M%S.%f%z")
    if base not in existing_ids:
        return base
    suffix = 1
    while "{0}-{1}".format(base, suffix) in existing_ids:
        suffix += 1
    return "{0}-{1}".format(base, suffix)
