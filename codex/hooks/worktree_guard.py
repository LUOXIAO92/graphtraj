#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path


def output(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def deny(reason: str) -> None:
    output({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    })
    raise SystemExit(0)


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_path(
    raw: str,
    base: Path,
    *,
    force: bool = False,
) -> Path | None:
    value = raw.strip().strip("'\"")

    if not value:
        return None

    if value.startswith(
        ("http://", "https://", "ssh://", "git@")
    ):
        return None

    value = value.replace("${PWD}", str(base))
    value = value.replace("$PWD", str(base))

    # Dynamic directory calculation cannot be proven safe.
    if "$(" in value or "`" in value:
        return None

    value = os.path.expanduser(value)

    looks_like_path = (
        os.path.isabs(value)
        or value.startswith(".")
        or "/" in value
        or "\\" in value
    )

    if not force and not looks_like_path:
        return None

    path = Path(value)

    if not path.is_absolute():
        path = base / path

    return path.resolve(strict=False)


def shell_tokens(command: str) -> list[str]:
    try:
        lexer = shlex.shlex(
            command,
            posix=True,
            punctuation_chars=";&|()<>",
        )
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return []


event = json.load(sys.stdin)

event_name = event.get("hook_event_name")
cwd = Path(event.get("cwd") or os.getcwd()).resolve()


# Determine the worktree that owns this Codex session.
try:
    root = Path(
        git(cwd, "rev-parse", "--show-toplevel")
    ).resolve()

    worktree_output = git(
        root,
        "worktree",
        "list",
        "--porcelain",
    )

    all_worktrees = [
        Path(line[9:]).resolve()
        for line in worktree_output.splitlines()
        if line.startswith("worktree ")
    ]

except Exception as exc:
    # Fail closed for tool execution.
    if event_name == "PreToolUse":
        deny(
            "Cannot verify the current Git worktree: "
            f"{exc}"
        )

    output({
        "systemMessage":
            f"Cannot verify current Git worktree: {exc}"
    })
    raise SystemExit(0)


other_worktrees = [
    path
    for path in all_worktrees
    if path != root
]


# Give every spawned agent an explicit immutable boundary.
if event_name == "SubagentStart":
    output({
        "hookSpecificOutput": {
            "hookEventName": "SubagentStart",
            "additionalContext": (
                f"Worktree boundary: {root}. "
                "Stay inside this worktree. "
                "Do not access any other Git worktree."
            ),
        }
    })
    raise SystemExit(0)


if event_name != "PreToolUse":
    raise SystemExit(0)


tool_name = event.get("tool_name")
tool_input = event.get("tool_input") or {}
command = tool_input.get("command")

if not isinstance(command, str):
    deny("Cannot verify tool input.")


# ---------------------------------------------------------
# Explicit tool working-directory escape
# ---------------------------------------------------------

for key in ("cwd", "workdir"):
    value = tool_input.get(key)

    if not isinstance(value, str) or not value:
        continue

    target = resolve_path(
        value,
        cwd,
        force=True,
    )

    if target is None or not is_inside(target, root):
        deny(
            "Blocked working directory outside "
            f"current worktree: {value}"
        )


# ---------------------------------------------------------
# apply_patch
# ---------------------------------------------------------

if tool_name == "apply_patch":
    prefixes = (
        "*** Add File:",
        "*** Update File:",
        "*** Delete File:",
        "*** Move to:",
    )

    targets = [
        line.split(":", 1)[1].strip()
        for line in command.splitlines()
        if line.startswith(prefixes)
    ]

    # Fail closed if the edit shape cannot be understood.
    if not targets:
        deny("Cannot verify apply_patch targets.")

    for raw in targets:
        target = resolve_path(
            raw,
            cwd,
            force=True,
        )

        if target is None or not is_inside(target, root):
            deny(
                "Blocked patch outside current "
                f"worktree: {raw}"
            )


# ---------------------------------------------------------
# Bash / exec_command
# ---------------------------------------------------------

elif tool_name == "Bash":
    normalized_command = command.replace("\\", "/")

    # Catch explicit references to every other registered
    # Git worktree, including paths embedded in python -c,
    # shell scripts, redirects, cp/mv/rm arguments, etc.
    for other in other_worktrees:
        spellings = {str(other)}

        for base in (cwd, root):
            relative = os.path.relpath(other, base)

            if relative not in ("", "."):
                spellings.add(relative)

        for spelling in spellings:
            normalized = spelling.replace("\\", "/")

            if normalized in normalized_command:
                deny(
                    "Blocked reference to another "
                    f"worktree: {other}"
                )

    tokens = shell_tokens(command)

    # Explicit directory changes must remain inside root.
    for index, token in enumerate(tokens):
        if token not in ("cd", "pushd"):
            continue

        next_index = index + 1

        while (
            next_index < len(tokens)
            and tokens[next_index] in ("-L", "-P")
        ):
            next_index += 1

        if next_index >= len(tokens):
            deny(
                f"Blocked unverifiable {token}."
            )

        raw = tokens[next_index]

        if (
            raw == "-"
            or "$(" in raw
            or "`" in raw
        ):
            deny(
                f"Blocked dynamic {token} target."
            )

        target = resolve_path(
            raw,
            cwd,
            force=True,
        )

        if target is None or not is_inside(target, root):
            deny(
                f"Blocked {token} outside "
                f"current worktree: {raw}"
            )

    # Resolve direct path operands. This catches paths that
    # reach another worktree through symlinks or relative
    # traversal.
    for token in tokens:
        target = resolve_path(token, cwd)

        if target is None:
            continue

        for other in other_worktrees:
            if is_inside(target, other):
                deny(
                    "Blocked path into another "
                    f"worktree: {target}"
                )