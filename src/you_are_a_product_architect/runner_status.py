"""Alias-local observation for completed and active Engineer turns."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

import yaml

from .runner_io import active_turn_key, read_active_turn_owner
from .runner_models import RunnerError, StatusResponse
from .runner_process import process_is_alive
from .runner_project import discover_runner_directory


ALIAS = re.compile(r"^[A-Za-z0-9._%-]+@[ldjser][1-9][0-9]*$")
TERMINAL_OUTCOMES = frozenset({"completed", "interrupted", "runtime-error"})
LEGACY_MAPPING_FIELDS = frozenset(
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
SESSION_MAPPING_FIELDS = frozenset(
    {
        "alias",
        "runtime",
        "session",
        "ticket_id",
        "team_generation",
        "role",
        "parent",
        "retained_batch_file",
        "worktree_path",
        "trace_file",
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
    mapping, session_directory = read_alias_mapping(runner_directory, alias)
    if is_session_mapping(mapping):
        return _status_session(mapping, session_directory, alias)
    turn_file = session_directory / "turn.yml"
    if os.path.lexists(str(turn_file)):
        outcome = read_terminal_outcome(turn_file)
        return {
            "alias": alias,
            "activity": "idle",
            "last_outcome": outcome,
        }

    require_active_turn(runner_directory, alias, mapping)
    return {"alias": alias, "activity": "running"}


def _status_session(
    mapping: Dict[str, Any], session_directory: Path, alias: str
) -> Dict[str, str]:
    execution_file = session_directory / "execution.yml"
    if os.path.lexists(str(execution_file)):
        return {
            "alias": alias,
            "activity": "idle",
            "last_outcome": read_terminal_outcome(execution_file),
        }
    if process_is_alive(mapping["worker_pid"]):
        return {"alias": alias, "activity": "running"}
    raise _invalid_activity()


def read_alias_mapping(
    runner_directory: Path, alias: str
) -> Tuple[Dict[str, Any], Path]:
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


def is_session_mapping(mapping: Mapping[str, Any]) -> bool:
    return "run_id" not in mapping and SESSION_MAPPING_FIELDS.issubset(mapping)


def _valid_mapping(mapping: object, alias: str) -> bool:
    if not isinstance(mapping, dict):
        return False
    if is_session_mapping(mapping):
        return _valid_session_mapping(mapping, alias)
    return _valid_legacy_mapping(mapping, alias)


def _valid_legacy_mapping(mapping: Dict[str, Any], alias: str) -> bool:
    if not LEGACY_MAPPING_FIELDS.issubset(mapping):
        return False
    if mapping["alias"] != alias:
        return False
    string_fields = LEGACY_MAPPING_FIELDS - {"worker_pid", "runtime_pid"}
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


def _valid_session_mapping(mapping: Dict[str, Any], alias: str) -> bool:
    if mapping["alias"] != alias:
        return False
    string_fields = SESSION_MAPPING_FIELDS - {
        "team_generation", "parent", "worker_pid", "runtime_pid"
    }
    if any(
        not isinstance(mapping[field], str) or not mapping[field]
        for field in string_fields
    ):
        return False
    if mapping["parent"] is not None and not isinstance(mapping["parent"], str):
        return False
    return (
        isinstance(mapping["team_generation"], int)
        and not isinstance(mapping["team_generation"], bool)
        and mapping["team_generation"] > 0
        and all(
            isinstance(mapping[field], int)
            and not isinstance(mapping[field], bool)
            and mapping[field] > 0
            for field in ("worker_pid", "runtime_pid")
        )
    )


def read_terminal_outcome(turn_file: Path) -> str:
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


def require_active_turn(
    runner_directory: Path,
    alias: str,
    mapping: Dict[str, Any],
) -> None:
    try:
        key = active_turn_key(mapping["ticket_id"])
    except UnicodeEncodeError as error:
        raise _invalid_mapping() from error
    try:
        activity = read_active_turn_owner(runner_directory, key)
    except OSError as error:
        raise _invalid_activity() from error
    reviewers = activity.get("reviewers") if isinstance(activity, dict) else None
    if isinstance(reviewers, list):
        activity = next(
            (
                owner
                for owner in reviewers
                if isinstance(owner, dict) and owner.get("alias") == alias
            ),
            {},
        )
    if (
        not isinstance(activity, dict)
        or activity.get("activity") != "running"
        or any(
            activity.get(field) != mapping[field]
            for field in (
                "alias",
                "run_id",
                "ticket_id",
                "worktree_path",
                "session",
                "worker_pid",
                "runtime_pid",
            )
        )
    ):
        raise _invalid_activity()
    if not process_is_alive(mapping["worker_pid"]):
        raise _invalid_activity()


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
