"""Alias-local observation for completed and active Engineer turns."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Sequence, Tuple

import yaml

from .runner_io import active_turn_directory, active_turn_key
from .runner_models import RunnerError, StatusResponse
from .runner_project import discover_runner_directory


ALIAS = re.compile(r"^[A-Za-z0-9._%-]+@[jse][1-9][0-9]*$")
TERMINAL_OUTCOMES = frozenset({"completed", "interrupted", "runtime-error"})
MAPPING_FIELDS = frozenset(
    {
        "alias",
        "runtime",
        "run_id",
        "ticket_id",
        "ticket_name",
        "role",
        "branch",
        "worktree_path",
        "ticket_file",
        "evidence_path",
        "session",
        "worker_pid",
        "runtime_pid",
    }
)


def status_aliases(aliases: Sequence[str], cwd: Path) -> StatusResponse:
    """Read exactly the supplied durable aliases; never discover a Run."""

    runner_directory = discover_runner_directory(cwd)
    results = []
    errors = []
    for alias in aliases:
        try:
            results.append(_status_alias(runner_directory, alias))
        except RunnerError as error:
            results.append({"alias": alias, "error": error.as_document()})
            errors.append(error)
    return StatusResponse(
        document={"aliases": results},
        succeeded=not errors,
        errors=tuple(errors),
    )


def _status_alias(runner_directory: Path, alias: str) -> Dict[str, str]:
    mapping, session_directory = _read_mapping(runner_directory, alias)
    turn_file = session_directory / "turn.yml"
    if os.path.lexists(str(turn_file)):
        outcome = _read_terminal_outcome(turn_file)
        return {
            "alias": alias,
            "activity": "idle",
            "last_outcome": outcome,
        }

    _require_active_turn(runner_directory, alias, mapping)
    return {"alias": alias, "activity": "running"}


def _read_mapping(runner_directory: Path, alias: str) -> Tuple[Dict[str, Any], Path]:
    if not ALIAS.fullmatch(alias):
        raise _alias_not_found()
    session_root = runner_directory / "sessions"
    session_directory = session_root / alias
    mapping_file = session_directory / "mapping.yml"
    if session_root.is_symlink():
        raise _invalid_mapping()
    if not session_root.is_dir() or not os.path.lexists(str(session_directory)):
        raise _alias_not_found()
    if session_directory.is_symlink() or not session_directory.is_dir():
        raise _invalid_mapping()
    if mapping_file.is_symlink() or not mapping_file.is_file():
        raise _invalid_mapping()
    try:
        mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise _invalid_mapping() from error
    if not _valid_mapping(mapping, alias):
        raise _invalid_mapping()
    return mapping, session_directory


def _valid_mapping(mapping: object, alias: str) -> bool:
    if not isinstance(mapping, dict) or not MAPPING_FIELDS.issubset(mapping):
        return False
    if mapping["alias"] != alias:
        return False
    string_fields = MAPPING_FIELDS - {"worker_pid", "runtime_pid"}
    if any(
        not isinstance(mapping[field], str) or not mapping[field]
        for field in string_fields
    ):
        return False
    return all(
        isinstance(mapping[field], int)
        and not isinstance(mapping[field], bool)
        and mapping[field] > 0
        for field in ("worker_pid", "runtime_pid")
    )


def _read_terminal_outcome(turn_file: Path) -> str:
    if turn_file.is_symlink() or not turn_file.is_file():
        raise _invalid_activity()
    try:
        turn = yaml.safe_load(turn_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise _invalid_activity() from error
    if (
        not isinstance(turn, dict)
        or not isinstance(turn.get("outcome"), str)
        or turn["outcome"] not in TERMINAL_OUTCOMES
    ):
        raise _invalid_activity()
    return turn["outcome"]


def _require_active_turn(
    runner_directory: Path,
    alias: str,
    mapping: Dict[str, Any],
) -> None:
    try:
        key = active_turn_key(mapping["ticket_id"])
    except UnicodeEncodeError as error:
        raise _invalid_mapping() from error
    reservation = active_turn_directory(runner_directory, key)
    owner = reservation / "reservation.yml"
    if (
        reservation.is_symlink()
        or not reservation.is_dir()
        or owner.is_symlink()
        or not owner.is_file()
    ):
        raise _invalid_activity()
    try:
        activity = yaml.safe_load(owner.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise _invalid_activity() from error
    if (
        not isinstance(activity, dict)
        or activity.get("activity") != "running"
        or activity.get("alias") != alias
        or activity.get("ticket_id") != mapping["ticket_id"]
    ):
        raise _invalid_activity()
    if not _process_is_alive(mapping["worker_pid"]):
        raise _invalid_activity()


def _process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _alias_not_found() -> RunnerError:
    return RunnerError("alias-not-found", "The requested Engineer alias was not found.")


def _invalid_mapping() -> RunnerError:
    return RunnerError(
        "operation-failed", "The requested Engineer alias mapping is invalid."
    )


def _invalid_activity() -> RunnerError:
    return RunnerError(
        "operation-failed",
        "The requested Engineer alias has no valid active turn or terminal outcome.",
    )
