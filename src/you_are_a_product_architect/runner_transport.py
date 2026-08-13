"""Shared durable Runtime transport documents and validation."""

from __future__ import annotations

from typing import Any, Dict


RUNTIME_DIAGNOSTIC_FILES = frozenset(
    {
        "events.jsonl",
        "launch-error.yml",
        "launch.yml",
        "mapping.yml",
        "stderr.log",
        "turn.yml",
        "worker-stderr.log",
    }
)


def runtime_turn_outcome(runtime_exit_code: int) -> Dict[str, Any]:
    """Build the durable terminal document for one Runtime turn."""

    return {
        "outcome": "completed" if runtime_exit_code == 0 else "runtime-error",
        "runtime_exit_code": runtime_exit_code,
    }


def valid_runtime_turn_outcome(document: Any) -> bool:
    """Return whether a document is one internally consistent terminal turn."""

    if not isinstance(document, dict):
        return False
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
