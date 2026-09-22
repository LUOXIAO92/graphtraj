"""Execute a replacement with the calling Runtime's existing native mechanism."""

from __future__ import annotations

import os
import shlex
import stat
import subprocess
import sys
from pathlib import Path
from typing import Sequence

import yaml

from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_process import process_ancestors, process_executable


def caller_runtime() -> str | None:
    """Identify an external caller from its process ancestry, not projected flags.

    Managed callers use their recorded Runtime instead. For external callers,
    recognize Codex's executable and pi's actual Node entrypoint. An unknown
    executable is not classified as lacking approval support.
    """
    for pid in process_ancestors(os.getpid())[1:]:
        executable = process_executable(pid)
        if executable is None:
            continue
        if executable.name.lower() in {"codex", "codex-cli"}:
            return "codex"
        if executable.name == "node":
            try:
                if sys.platform.startswith("linux"):
                    argv = Path(f"/proc/{pid}/cmdline").read_bytes().decode().split("\0")
                else:
                    argv = shlex.split(subprocess.check_output(
                        ["/bin/ps", "-p", str(pid), "-o", "args="], text=True,
                    ))
                if len(argv) > 1 and str(Path(argv[1]).resolve()).endswith(
                    "/@mariozechner/pi-coding-agent/dist/cli.js"
                ):
                    return "pi"
            except (OSError, ValueError, subprocess.CalledProcessError):
                continue
    return None


def execute_replacement(command: Sequence[str]) -> dict:
    """Request native execution of this exact remaining operation.

    The native wrapper owns approval, rejection, cancellation and execution.
    GraphTraj reads only the operation's normal result. Without an inherited
    wrapper, return the exact execution request to the actual caller's native
    tool. No prior decision or approval token is retained or accepted; a broken
    inherited channel remains an error.
    """
    if "CODEX_ESCALATE_SOCKET" not in os.environ:
        # The caller's native tool owns approval and executes the operation
        # itself. Returning this request grants no authority and changes no seat.
        return {
            "replacement_status": "requires-native-approval",
            "instruction": (
                "In the actual calling Runtime, invoke exec_command with the exact "
                "arguments below. Native approval executes the remaining replacement; "
                "its output is the final operation result. If denied or cancelled, "
                "stop without executing the command by another route."
            ),
            "native_execution": {
                "tool": "exec_command",
                "arguments": {
                    "cmd": shlex.join(command),
                    "workdir": os.getcwd(),
                    "login": False,
                    "sandbox_permissions": "require_escalated",
                    "justification": (
                        "Allow this non-direct replacement after GraphTraj checked "
                        "the recorded caller relationship? The target and all "
                        "descendants must still be stopped before replacement."
                    ),
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
            "The inherited execution channel is invalid; no replacement was executed.",
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
            "native-replacement-failed",
            result.stderr.strip() or "The native Runtime did not complete the replacement.",
        )
    try:
        document = yaml.safe_load(result.stdout)
    except yaml.YAMLError as error:
        raise RunnerError("operation-failed", "Invalid native replacement output.") from error
    if not isinstance(document, dict) or "replacement_alias" not in document:
        raise RunnerError("operation-failed", "The native replacement returned no result.")
    return document
