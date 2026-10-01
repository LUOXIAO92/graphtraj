"""Execute a concrete operation through Codex's native approval channel."""

from __future__ import annotations

import os
import shlex
import stat
import subprocess
from pathlib import Path
from typing import Sequence

import yaml

from graphtraj.execution.runner_models import RunnerError


def execute_native_operation(
    command: Sequence[str],
    operation: str,
    justification: str,
    result_field: str,
) -> dict:
    """Let the selected native reviewer authorize and execute the exact command.

    An unavailable inherited channel and a denied request fail without fallback.
    Without an inherited channel, return the concrete request for the caller's
    native tool; returning it neither grants approval nor changes project state.
    """
    status_field = operation + "_status"
    if "CODEX_ESCALATE_SOCKET" not in os.environ:
        # The caller's native tool owns approval and executes the operation
        # itself. Returning this request grants no authority and changes no seat.
        return {
            status_field: "requires-native-approval",
            "instruction": (
                "Invoke the actual caller's native exec_command with the exact arguments "
                "below. Its selected reviewer may reuse existing authority. A denial or "
                "failure must not be retried through another execution route."
            ),
            "native_execution": {
                "tool": "exec_command",
                "arguments": {
                    "cmd": shlex.join(command),
                    "workdir": os.getcwd(),
                    "login": False,
                    "sandbox_permissions": "require_escalated",
                    "justification": justification,
                },
            },
        }

    try:
        descriptor = int(os.environ["CODEX_ESCALATE_SOCKET"])
        wrapper = os.environ["EXEC_WRAPPER"]
        if descriptor < 0 or not stat.S_ISSOCK(os.fstat(descriptor).st_mode):
            raise ValueError("native escalation descriptor is not an open socket")
        if not Path(wrapper).is_file() or not os.access(wrapper, os.X_OK):
            raise ValueError("native execution wrapper is not executable")
    except (KeyError, ValueError, OSError) as error:
        raise RunnerError(
            "native-approval-unavailable",
            "Codex approval exists but its native execution channel is unavailable. "
            f"The inherited execution channel is invalid; no {operation} was executed.",
        ) from error

    try:
        result = subprocess.run(
            [wrapper, command[0], *command],
            pass_fds=(descriptor,), capture_output=True, text=True,
        )
    except OSError as error:
        raise RunnerError("native-approval-unavailable", str(error)) from error
    if result.returncode != 0:
        # Do not retry, reinterpret a denial as absent capability, or run the
        # operation locally. Native stderr retains refusal/cancellation details.
        raise RunnerError(
            f"native-{operation}-failed",
            result.stderr.strip() or f"The native Runtime did not complete the {operation}.",
        )
    try:
        document = yaml.safe_load(result.stdout)
    except yaml.YAMLError as error:
        raise RunnerError("operation-failed", f"Invalid native {operation} output.") from error
    if not isinstance(document, dict) or result_field not in document:
        raise RunnerError("operation-failed", f"The native {operation} returned no result.")
    return document
