"""Shared durable Runtime transport documents and validation."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict


RUNTIME_DIAGNOSTIC_FILES = frozenset(
    {
        "events.jsonl",
        "launch-error.yml",
        "launch.yml",
        "mapping.yml",
        "native-session.yml",
        "resume-error.yml",
        "resume.yml",
        "stderr.log",
        "execution.yml",
        "worker-stderr.log",
    }
)


def runtime_turn_outcome(runtime_exit_code: int) -> Dict[str, Any]:
    """Build the durable terminal document for one Runtime turn."""

    return {
        "outcome": "completed" if runtime_exit_code == 0 else "runtime-error",
        "runtime_exit_code": runtime_exit_code,
    }


def record_runtime_identity(events_file: Path, runtime: str) -> None:
    """Identify the Runtime before writing a new retained Trace."""

    if events_file.exists() and events_file.stat().st_size:
        return
    with events_file.open("a", encoding="utf-8") as events:
        events.write(
            json.dumps(
                {"type": "runtime", "runtime": runtime},
                separators=(",", ":"),
            )
            + "\n"
        )
        events.flush()
        os.fsync(events.fileno())


def valid_runtime_turn_outcome(document: Any) -> bool:
    """Return whether a document is one internally consistent terminal turn."""

    if not isinstance(document, dict):
        return False
    if document.get("outcome") == "interrupted":
        if "runtime_exit_code" not in document:
            return True
        interrupted_exit_code = document["runtime_exit_code"]
        return isinstance(interrupted_exit_code, int) and not isinstance(
            interrupted_exit_code, bool
        )
    runtime_exit_code = document.get("runtime_exit_code")
    if not isinstance(runtime_exit_code, int) or isinstance(runtime_exit_code, bool):
        return False
    return (
        document.get("outcome") == "completed" and runtime_exit_code == 0
    ) or (
        document.get("outcome") == "runtime-error" and runtime_exit_code != 0
    )


def runtime_launch_failure(
    code: str,
    message: str,
    diagnostic: str,
    *,
    terminal_confirmed: bool,
) -> Dict[str, Any]:
    """Build one durable worker failure document."""

    failure: Dict[str, Any] = {
        "code": code,
        "message": message,
        "terminal_confirmed": terminal_confirmed,
    }
    if diagnostic:
        failure["diagnostic"] = diagnostic
    return failure


def valid_terminal_launch_failure(document: Any) -> bool:
    """Return whether a failure independently proves Runtime termination."""

    return (
        isinstance(document, dict)
        and isinstance(document.get("code"), str)
        and isinstance(document.get("message"), str)
        and document.get("terminal_confirmed") is True
    )
