"""Rebuildable light Task Graph index and its layered query views.

The index is a projection of Task state and accepted delivery events, never a
second editable fact. Every native Task change is committed by a Project
Worldline append, which also advances the index under the same lock. The
index records the last Worldline event it reflects; a read whose marker
differs from the current last event rebuilds it, so a stale, interrupted or
damaged index is never reported as current.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from graphtraj import file_lock


_INDEX          = "task-index.json"
_SCHEMA_VERSION = 1
_DELIVERY_EVENTS = frozenset(
    {"task-integrated", "task-integration-conflict-resolved", "task-completed"}
)
_DELIVERY_FIELDS = (
    "event_id", "event", "task_id", "candidate", "dev_commit", "reason",
    "evidence_refs", "current_definition", "checked_definitions",
)
_NODE_FIELDS = (
    "task_id", "task_name", "title", "parent_id", "status", "disposition",
    "active", "dependencies", "replaced_by", "current_definition",
    "current_candidate",
)


def read_index(state: Path) -> dict[str, Any]:
    """Return the current light index, rebuilding it when it is not current.

    Parameters
    ----------
    state : Path
        Project state directory containing ``tasks/`` and ``worldline/``.

    Returns
    -------
    dict
        ``revision`` counts reflected Worldline events; ``tasks`` maps IDs to
        light records; ``deliveries`` maps IDs to their latest delivery event.
    """
    worldline = state / "worldline"
    if not (state / "tasks").is_dir() or not worldline.is_dir():
        return {"revision": 0, "event_id": None, "tasks": {}, "deliveries": {}}

    # Task state is written only inside Worldline appends, so the shared
    # Worldline lock gives one consistent snapshot of both.
    descriptor = os.open(str(worldline / ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        file_lock.flock(descriptor, file_lock.LOCK_SH)
        index = _load(state)
        if index is None or index["event_id"] != _last_event_id(worldline):
            index = _rebuild(state)
            _store(state, index)
        return index
    finally:
        file_lock.flock(descriptor, file_lock.LOCK_UN)
        os.close(descriptor)


def apply_event(state: Path, previous_event_id: str | None, recorded: dict[str, Any]) -> None:
    """Advance a current index past one just-appended Worldline event.

    Called with the Worldline lock held after the event is durable. Only
    Task records whose ``task.yml`` changed are reloaded. An index that did
    not reflect ``previous_event_id`` is left behind for the next read to
    rebuild rather than patched from an unknown base.
    """
    index = _load(state)
    if index is None or index["event_id"] != previous_event_id:
        return
    from graphtraj.graph.task_graph import _load_state

    tasks   = state / "tasks"
    current = {}
    for directory in (tasks.iterdir() if tasks.is_dir() else ()):
        path = directory / "task.yml"
        if not path.is_file():
            continue
        stamp   = _stamp(path)
        task_id = directory.name.split("-", 1)[0]
        node    = index["tasks"].get(task_id)
        if node is None or node["stamp"] != stamp:
            task_id, record = _load_state(path)
            node = _node(record, stamp)
        current[task_id] = node

    if recorded["event"] in _DELIVERY_EVENTS:
        index["deliveries"][recorded["task_id"]] = _delivery(recorded)
    index.update(
        tasks=current, event_id=recorded["event_id"], revision=index["revision"] + 1
    )
    _store(state, index)


def task_directory(state: Path, index: dict[str, Any], task_id: str) -> Path:
    """Return the durable directory of one indexed Task."""
    node = index["tasks"][task_id]
    return state / "tasks" / "{0}-{1}".format(task_id, node["task_name"])


def _rebuild(state: Path) -> dict[str, Any]:
    """Build the index from every Task state and the whole Worldline."""
    from graphtraj.graph.delivery_worldline import _read_shards
    from graphtraj.graph.task_graph import _load_states, _validate_graph

    states  = _load_states(state / "tasks")
    _validate_graph({key: record for key, (_, record) in states.items()})
    events  = _read_shards(state)[1]
    latest  = {
        event["task_id"]: _delivery(event)
        for event in events if event["event"] in _DELIVERY_EVENTS
    }
    return {
        "schema_version": _SCHEMA_VERSION,
        "revision":       len(events),
        "event_id":       events[-1]["event_id"] if events else None,
        "tasks":          {
            key: _node(record, _stamp(directory / "task.yml"))
            for key, (directory, record) in states.items()
        },
        "deliveries":     latest,
    }


def _node(record: dict[str, Any], stamp: list[int]) -> dict[str, Any]:
    """Keep only graph facts; bodies, reports and Sessions stay on disk."""
    return {**{key: record.get(key) for key in _NODE_FIELDS}, "stamp": stamp}


def _delivery(event: dict[str, Any]) -> dict[str, Any]:
    """Keep the accepted delivery relation of one event."""
    return {key: event.get(key) for key in _DELIVERY_FIELDS}


def _stamp(path: Path) -> list[int]:
    """Identify one atomically replaced state file without reading it."""
    status = path.stat()
    return [status.st_ino, status.st_mtime_ns, status.st_size]


def _last_event_id(worldline: Path) -> str | None:
    """Read the newest event ID from the last shard only."""
    from graphtraj.graph.delivery_worldline import _shard_order

    shards = sorted(worldline.glob("*.jsonl"), key=_shard_order)
    if not shards:
        return None
    lines = shards[-1].read_text(encoding="utf-8").splitlines()
    return json.loads(lines[-1])["event_id"] if lines else None


def _load(state: Path) -> dict[str, Any] | None:
    """Return a structurally usable stored index, or None to force a rebuild."""
    try:
        index = json.loads((state / _INDEX).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
        not isinstance(index, dict)
        or index.get("schema_version") != _SCHEMA_VERSION
        or not isinstance(index.get("revision"), int)
        or not isinstance(index.get("tasks"), dict)
        or not isinstance(index.get("deliveries"), dict)
        or "event_id" not in index
    ):
        return None
    return index


def _store(state: Path, index: dict[str, Any]) -> None:
    """Atomically replace the stored index; concurrent rebuilds write equal data."""
    temporary = state / ".{0}.{1}-{2}.tmp".format(_INDEX, os.getpid(), threading.get_ident())
    temporary.write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, state / _INDEX)
