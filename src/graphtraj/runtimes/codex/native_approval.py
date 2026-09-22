"""Read the approval a caller's own Codex session recorded for one command.

A Codex session writes every tool call it decides about into its own rollout
record under the Codex home. When a call asked for escalated permission and the
session then produced that call's result, the native Runtime explicitly approved
and ran exactly that command line in exactly that working directory. This module
turns those records into one yes-or-no question, without writing anything.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Iterator


# The Runtime projects its current session identifier into the environment of
# every process it starts. It is only a pointer to which record to read: the
# decision itself is the record, and the record has to name this exact command.
SESSION_VARIABLE = "CODEX_THREAD_ID"
HOME_VARIABLE = "CODEX_HOME"

# The marker a call carries when it asked the Runtime for escalated permission.
ESCALATED = 'sandbox_permissions:"require_escalated"'
ESCALATED_JSON = "require_escalated"


def codex_native_command_approval(command: str, cwd: str) -> bool:
    """Return whether this command line ran under a native escalation approval.

    Parameters
    ----------
    command
        The exact command line this entry is running, as one shell string.
    cwd
        The working directory this entry is running in.

    Returns
    -------
    ``True`` only when the caller's own Codex session recorded a tool call that
    asked for escalated permission and then produced a result, and that call
    named this command line and this working directory exactly. Anything else,
    including a denial, a cancel, a different command or no record at all, is
    ``False``.
    """
    thread = os.environ.get(SESSION_VARIABLE)
    if not thread:
        return False
    directory = os.environ.get(HOME_VARIABLE) or str(Path.home() / ".codex")
    rollout = _rollout_for(Path(directory) / "sessions", thread)
    if rollout is None:
        return False
    named: list[str] = []
    escalated: set[str] = set()
    answered: set[str] = set()
    for record in _records(rollout):
        call = _named_call(record, command, cwd)
        if call is not None:
            call_id, was_escalated = call
            named.append(call_id)
            if was_escalated:
                escalated.add(call_id)
            continue
        payload = record.get("payload") or {}
        if record.get("type") == "response_item" and payload.get("type") in {
            "custom_tool_call_output",
            "function_call_output",
        }:
            answer = payload.get("call_id")
            if isinstance(answer, str):
                answered.add(answer)
    # Only the last call naming this exact command and directory counts. A
    # later identical call that asked for no escalation, produced no result or
    # was denied must not fall back to an earlier approval of the same command.
    if not named:
        return False
    last = named[-1]
    return last in escalated and last in answered


def _rollout_for(sessions: Path, thread: str) -> Path | None:
    """Return the rollout record one thread wrote, newest first."""

    if not sessions.is_dir():
        return None
    matches = sorted(
        sessions.glob("**/rollout-*{0}.jsonl".format(thread)),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None


def _records(rollout: Path) -> Iterator[dict]:
    """Yield each JSON record of one rollout, ignoring unreadable lines."""

    try:
        lines: Iterable[str] = rollout.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            yield record


def _named_call(record: dict, command: str, cwd: str) -> tuple[str, bool] | None:
    """Return one call's identifier and escalation when it names this command.

    The call arguments are read from their own record, never from the command
    being checked, and both the command line and the working directory must
    equal the supplied values exactly. A record that merely mentions the
    command is not a match.
    """

    if record.get("type") != "response_item":
        return None
    payload = record.get("payload") or {}
    if payload.get("type") == "custom_tool_call" and payload.get("name") == "exec":
        call_id = payload.get("call_id")
        text = payload.get("input")
        if not isinstance(call_id, str) or not isinstance(text, str):
            return None
        if _quoted(text, "cmd") != command or _quoted(text, "workdir") != cwd:
            return None
        return call_id, ESCALATED in text
    if payload.get("type") == "function_call":
        call_id = payload.get("call_id")
        arguments = payload.get("arguments")
        if not isinstance(call_id, str) or not isinstance(arguments, str):
            return None
        try:
            values: Any = json.loads(arguments)
        except ValueError:
            return None
        if not isinstance(values, dict):
            return None
        if values.get("cmd") != command or values.get("workdir") != cwd:
            return None
        return call_id, values.get("sandbox_permissions") == ESCALATED_JSON
    return None


def _quoted(text: str, key: str) -> str | None:
    """Return one double-quoted value of a call written in call syntax."""

    marker = '{0}:"'.format(key)
    start = text.find(marker)
    if start < 0:
        return None
    start += len(marker)
    end = start
    while end < len(text):
        if text[end] == "\\":
            end += 2
            continue
        if text[end] == '"':
            return text[start:end]
        end += 1
    return None
