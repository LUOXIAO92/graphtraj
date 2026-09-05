"""Legacy Run-local Worldline retained until its downstream contraction."""

from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .runner_io import write_yaml_durably


_ASSIGNED_FIELDS = frozenset({"run_id", "worldline_seq", "captured_at"})


def append_worldline_event(
    run_root: Path,
    run_id: str,
    event: Mapping[str, Any],
) -> dict[str, Any]:
    """Append one legacy Run-local event and regenerate its projection."""

    _validate_supplied_event(event)
    run_root.mkdir(parents=True, exist_ok=True)
    journal = run_root / "worldline.jsonl"
    descriptor = os.open(str(journal), os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        with os.fdopen(descriptor, "r+", encoding="utf-8", closefd=False) as stream:
            existing = _read_events(stream.read(), run_id)
            sequence = len(existing) + 1
            _validate_causal_references(event, sequence)
            normalized = {
                "run_id": run_id,
                "worldline_seq": sequence,
                "captured_at": datetime.now().astimezone().isoformat(),
                **event,
            }
            _validate_trace_reference(run_root, normalized)
            stream.write(
                json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
            _write_projection(run_root, run_id, [*existing, normalized])
        return normalized
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def project_worldline(run_root: Path) -> Path:
    """Regenerate the legacy ledger.yml from its Run-local journal."""

    journal = run_root / "worldline.jsonl"
    descriptor = os.open(str(journal), os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_SH)
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as stream:
            events = _read_events(stream.read())
        if not events:
            raise ValueError("worldline is empty")
        return _write_projection(run_root, events[0]["run_id"], events)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _read_events(content: str, expected_run_id: str | None = None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for sequence, line in enumerate(content.splitlines(), start=1):
        event = json.loads(line)
        if (
            not isinstance(event, dict)
            or event.get("worldline_seq") != sequence
            or not isinstance(event.get("run_id"), str)
            or (expected_run_id is not None and event["run_id"] != expected_run_id)
        ):
            raise ValueError("worldline contains an invalid event")
        if expected_run_id is None:
            expected_run_id = event["run_id"]
        events.append(event)
    return events


def _write_projection(
    run_root: Path,
    run_id: str,
    events: list[dict[str, Any]],
) -> Path:
    ledger = run_root / "ledger.yml"
    write_yaml_durably(
        ledger,
        {"run_id": run_id, "trajectory": _group_trajectory(events)},
    )
    return ledger


def _group_trajectory(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    agent_turns: dict[tuple[str, int], dict[str, Any]] = {}
    review_rounds: dict[tuple[str, int], dict[str, Any]] = {}
    review_turns: dict[tuple[str, int, str, int], dict[str, Any]] = {}
    decisions: dict[int, dict[str, Any]] = {}
    for event in events:
        kind = event["kind"]
        if kind in {"task-state-change", "dag-change"}:
            decision = next(
                (
                    decisions[sequence]
                    for sequence in event["caused_by_worldline_seqs"]
                    if sequence in decisions
                ),
                None,
            )
            if decision is not None:
                key = "task_state_changes" if kind == "task-state-change" else "dag_changes"
                decision[key].append(event)
                continue
        if kind.startswith("agent-turn-"):
            if "review_round" in event:
                round_key = (event["ticket_id"], event["review_round"])
                review_round = review_rounds.get(round_key)
                if review_round is None:
                    review_round = {
                        "kind": "review-round",
                        "ticket_id": event["ticket_id"],
                        "review_round": event["review_round"],
                        "agent_turns": [],
                    }
                    review_rounds[round_key] = review_round
                    groups.append(review_round)
                turn_key = (*round_key, event["alias"], event["turn"])
                turn = review_turns.get(turn_key)
                if turn is None:
                    turn = _new_turn(event)
                    review_turns[turn_key] = turn
                    review_round["agent_turns"].append(turn)
                turn["events"].append(event)
            else:
                turn_key = (event["alias"], event["turn"])
                turn = agent_turns.get(turn_key)
                if turn is None:
                    turn = _new_turn(event)
                    agent_turns[turn_key] = turn
                    groups.append(turn)
                turn["events"].append(event)
            continue
        if kind == "user-input":
            groups.append({"kind": kind, "event": event})
            continue
        if kind == "main-decision":
            decision = {
                "kind": kind,
                "event": event,
                "task_state_changes": [],
                "dag_changes": [],
            }
            decisions[event["worldline_seq"]] = decision
            groups.append(decision)
            continue
        groups.append({"kind": kind, "event": event})
    for review_round in review_rounds.values():
        review_round["agent_turns"].sort(key=_turn_completion_sequence)
    return groups


def _new_turn(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": "agent-turn",
        "ticket_id": event["ticket_id"],
        "role": event["role"],
        "alias": event["alias"],
        "turn": event["turn"],
        "events": [],
    }


def _turn_completion_sequence(turn: Mapping[str, Any]) -> int:
    terminal = next(
        (
            event["worldline_seq"]
            for event in turn["events"]
            if event["kind"] == "agent-turn-terminal"
        ),
        None,
    )
    return terminal if terminal is not None else turn["events"][0]["worldline_seq"]


def _validate_supplied_event(event: Mapping[str, Any]) -> None:
    if not isinstance(event, Mapping) or not isinstance(event.get("kind"), str):
        raise ValueError("worldline event requires an explicit kind")
    if "id" in event or _ASSIGNED_FIELDS.intersection(event):
        raise ValueError("worldline event contains a reserved identifier")
    kind = event["kind"]
    if kind.startswith("agent-turn-"):
        _require(event, "ticket_id", "role", "alias", "turn")
        if (
            not isinstance(event["turn"], int)
            or isinstance(event["turn"], bool)
            or event["turn"] < 1
        ):
            raise ValueError("agent Turn requires a positive turn")
        if event.get("role") in {"standards-reviewer", "spec-reviewer"}:
            _require(event, "review_round")
    if kind == "agent-turn-terminal":
        _require(event, "trace_ref", "outcome")
    elif kind == "user-input":
        _require(event, "input")
    elif kind == "main-decision":
        _require(
            event,
            "ticket_id",
            "accepted_findings",
            "rejected_findings",
            "verdict",
            "caused_by_worldline_seqs",
        )
        if event["verdict"] not in {"PASS", "FAIL"}:
            raise ValueError("Main decision verdict must be PASS or FAIL")
    elif kind == "task-state-change":
        _require(event, "ticket_id", "from_state", "to_state", "caused_by_worldline_seqs")
    elif kind == "dag-change":
        _require(event, "changes", "caused_by_worldline_seqs")
    try:
        json.dumps(event, ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise ValueError("worldline event must be JSON serializable") from error


def _require(event: Mapping[str, Any], *fields: str) -> None:
    if any(field not in event for field in fields):
        raise ValueError("worldline event is missing required domain fields")


def _validate_causal_references(event: Mapping[str, Any], sequence: int) -> None:
    references = event.get("caused_by_worldline_seqs")
    if references is None:
        return
    if (
        not isinstance(references, list)
        or any(
            not isinstance(reference, int)
            or isinstance(reference, bool)
            or reference < 1
            or reference >= sequence
            for reference in references
        )
        or len(references) != len(set(references))
    ):
        raise ValueError("causal references must name prior Run-local events")


def _validate_trace_reference(run_root: Path, event: Mapping[str, Any]) -> None:
    trace_ref = event.get("trace_ref")
    if trace_ref is None:
        return
    if not isinstance(trace_ref, str):
        raise ValueError("trace_ref must be Run-relative")
    relative = Path(trace_ref)
    alias = str(event.get("alias", "")).lstrip("@")
    expected_tail = (
        "traces",
        alias,
        "turn-{0}".format(event.get("turn")),
        "events.jsonl",
    )
    if (
        relative.is_absolute()
        or len(relative.parts) < 6
        or relative.parts[0] != "tickets"
        or relative.parts[-4:] != expected_tail
    ):
        raise ValueError("trace_ref does not match its Turn identity")
    trace = run_root / relative
    if trace.is_symlink() or not trace.is_file():
        raise ValueError("trace_ref does not identify an immutable raw trace")
