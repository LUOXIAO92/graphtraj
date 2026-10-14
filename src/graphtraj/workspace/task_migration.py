"""One-time offline conversion of retained Ticket state to the Task format.

This module is the only place that reads the retired Ticket names. It renames
explicit structural keys, event names, status codes and state paths; it never
rewrites free text such as Task bodies, instructions or native Runtime records.
The previous ``state`` and ``runner`` directories are copied to a backup first
and restored if any step fails.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.execution.execution_budget import split_execution_budget_front_matter


KEYS = {
    "ticket":              "task",
    "tickets":             "tasks",
    "ticket_id":           "task_id",
    "ticket_ids":          "task_ids",
    "ticket_name":         "task_name",
    "ticket_file":         "task_file",
    "ticket_commit":       "task_commit",
    "ticket_status":       "task_status",
    "ticket_directory":    "task_directory",
    "caller_ticket_id":    "caller_task_id",
    "affected_ticket_ids": "affected_task_ids",
    "reopened_ticket_ids": "reopened_task_ids",
    "reopen_ticket_ids":   "reopen_task_ids",
    "unlocked_ticket_ids": "unlocked_task_ids",
    "latest_ticket_event": "latest_task_event",
    "launch_matches_ticket": "launch_matches_task",
}
# Exact GraphTraj event names and codes; free text never equals one of these.
VALUES = {
    **{"ticket-" + name: "task-" + name for name in (
        "registered", "graph-revised", "state-changed", "completed", "integrated",
        "integration-started", "integration-failed", "integration-escalated",
        "integration-conflict-started", "integration-conflict-dispatched",
        "integration-conflict-resolved", "dependency-unlocked", "already-live",
    )},
    "invalid-ticket": "invalid-task",
    **{"TICKET_" + name: "TASK_" + name for name in (
        "FILE_INVALID", "NOT_READY", "ALREADY_ACTIVE", "ID_INVALID",
        "ID_DUPLICATE", "NAME_INVALID",
    )},
}
# GraphTraj-owned line records; other JSONL files hold native Runtime text.
JSONL_NAMES = {"events.jsonl", "parent-notices.jsonl"}


class Counts(dict):
    """Count each kind of converted fact for the migration report."""

    def add(self, kind: str) -> None:
        """Increment one converted-fact counter."""
        self[kind] = self.get(kind, 0) + 1


def migrate_project(cwd: Path) -> dict[str, Any]:
    """Convert one project's retained Ticket state and return a summary.

    Parameters
    ----------
    cwd : Path
        Any directory inside the Harness Project whose ``.graphtraj`` is converted.

    Returns
    -------
    dict
        Backup location and the number of converted keys, values, paths,
        files and Worktree links.

    Raises
    ------
    ValueError
        When the project has no Ticket state or was already converted. Any
        failure after the backup restores the previous directories and links.
    """
    configuration = load_project_configuration(cwd)
    harness       = configuration.harness_root
    state         = configuration.state
    runner        = harness / ".graphtraj" / "runner"
    if not (state / "tickets").is_dir():
        raise ValueError("No Ticket state exists to convert")
    if (state / "tasks").exists():
        raise ValueError("Task state already exists; refusing to convert twice")

    # Copy first so that a failed conversion returns to the unchanged data.
    stamp  = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = harness / ".graphtraj" / "backups" / ("ticket-state-" + stamp)
    backup.mkdir(parents=True)
    shutil.copytree(state, backup / "state", symlinks=True)
    if runner.is_dir():
        shutil.copytree(runner, backup / "runner", symlinks=True)
    links = _worktree_links(configuration.agent_worktrees)
    (backup / "worktree-links.yml").write_text(
        yaml.safe_dump({str(link): os.readlink(link) for link in links}), encoding="utf-8")

    counts = Counts()
    try:
        for root in (state, runner):
            if root.is_dir():
                _convert_records(root, counts)
        _convert_definitions(state / "tickets", counts)
        _move_layout(state, counts)
        for link in links:
            target = _path(os.readlink(link), counts)
            if target != os.readlink(link):
                link.unlink()
                link.symlink_to(target, target_is_directory=True)
                counts.add("worktree_links")
    except BaseException:
        _restore(backup, state, runner, links)
        raise
    return {"backup": backup.relative_to(harness).as_posix(), "converted": dict(counts)}


def _convert_records(root: Path, counts: Counts) -> None:
    """Rewrite GraphTraj YAML and JSONL records under one retained root."""
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file() or "sessions" in path.relative_to(root).parts:
            continue
        if path.suffix in {".yml", ".yaml"}:
            original = yaml.safe_load(path.read_text(encoding="utf-8"))
            converted = _value(original, counts)
            if converted != original:
                _write(path, yaml.safe_dump(converted, sort_keys=False))
                counts.add("files")
        elif path.suffix == ".jsonl" and (path.name in JSONL_NAMES or path.parent.name == "worldline"):
            lines   = path.read_text(encoding="utf-8").splitlines()
            # Only each record's top level is GraphTraj structure; payloads stay unchanged.
            records = [_top_level(json.loads(line), counts) if line.strip() else line for line in lines]
            text    = "".join((json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else item)
                              + "\n" for item in records)
            if text != path.read_text(encoding="utf-8"):
                _write(path, text)
                counts.add("files")


def _top_level(record: Any, counts: Counts) -> Any:
    """Convert one line record's own keys and their structural values."""
    if not isinstance(record, dict):
        return record
    return {_key(key, counts): _value(value, counts) for key, value in record.items()}


def _value(value: Any, counts: Counts) -> Any:
    """Convert explicit keys, exact codes and state paths within one value."""
    if isinstance(value, dict):
        return {_key(key, counts): _value(item, counts) for key, item in value.items()}
    if isinstance(value, list):
        return [_value(item, counts) for item in value]
    if isinstance(value, str):
        if value in VALUES:
            counts.add("values")
            return VALUES[value]
        return _path(value, counts)
    return value


def _key(key: Any, counts: Counts) -> Any:
    """Rename one structural key from the explicit Ticket key list."""
    if key in KEYS:
        counts.add("keys")
        return KEYS[key]
    return key


def _path(value: str, counts: Counts) -> str:
    """Rename state path segments in a single path-like string.

    Text containing whitespace is free text and is never changed.
    """
    if any(character.isspace() for character in value) or "ticket" not in value:
        return value
    parts = value.split("/")
    renamed = list(parts)
    for index, part in enumerate(parts):
        if part == "tickets" and ((index == 0 and len(parts) > 1) or parts[index - 1:index] == ["state"]):
            renamed[index] = "tasks"
        elif part in {"ticket.yml", "ticket.md"} and index > 0:
            renamed[index] = part.replace("ticket", "task")
    if value == "ticket.md":
        renamed = ["task.md"]
    if renamed == parts:
        return value
    counts.add("paths")
    return "/".join(renamed)


def _convert_definitions(tickets: Path, counts: Counts) -> None:
    """Rename identity keys in definition metadata, leaving each body unchanged."""
    for path in sorted(tickets.glob("*/ticket.md")) + sorted(tickets.glob("*/definitions/*.md")):
        text  = path.read_text(encoding="utf-8")
        split = split_execution_budget_front_matter(text)
        metadata = yaml.safe_load(split[1]) if split is not None else None
        if isinstance(metadata, dict) and isinstance(metadata.get("task"), dict):
            # v2: the front matter is generated metadata; the body follows it unchanged.
            metadata["task"] = {KEYS.get(key, key): item for key, item in metadata["task"].items()}
            converted = "---\n" + yaml.safe_dump(metadata, sort_keys=False) + "---\n" + split[2]
        else:
            # v1: rename only the generated heading and name lines.
            converted = _legacy_headings(text)
        if converted != text:
            _write(path, converted)
            counts.add("definitions")


def _legacy_headings(text: str) -> str:
    """Rename the generated ``# Ticket N:`` and ``Ticket name:`` lines only."""
    split  = split_execution_budget_front_matter(text)
    prefix = split[0] if split is not None else ""
    body   = split[2] if split is not None else text
    lines  = body.splitlines(keepends=True)
    seen_heading = seen_name = False
    for index, line in enumerate(lines):
        if not seen_heading and line.startswith("# Ticket "):
            lines[index]  = "# Task " + line.removeprefix("# Ticket ")
            seen_heading = True
        elif seen_heading and not seen_name and line.startswith("Ticket name: "):
            lines[index] = "Task name: " + line.removeprefix("Ticket name: ")
            seen_name    = True
            break
    return prefix + "".join(lines)


def _move_layout(state: Path, counts: Counts) -> None:
    """Rename the Ticket directory and each Task's state and first definition."""
    for directory in sorted((state / "tickets").iterdir()):
        for old, new in (("ticket.yml", "task.yml"), ("ticket.md", "task.md")):
            if (directory / old).exists():
                os.replace(directory / old, directory / new)
                counts.add("files_renamed")
    os.replace(state / "tickets", state / "tasks")


def _worktree_links(worktrees: Path) -> list[Path]:
    """Return each Agent Worktree ``.state`` link into the retained state."""
    if not worktrees.is_dir():
        return []
    return sorted(link for link in worktrees.glob("*/.state") if link.is_symlink())


def _write(path: Path, text: str) -> None:
    """Replace one file atomically, keeping a read-only definition read-only."""
    mode = stat.S_IMODE(path.stat().st_mode)
    temporary = path.with_name("." + path.name + ".migrating")
    temporary.write_text(text, encoding="utf-8")
    temporary.chmod(mode)
    os.replace(temporary, path)


def _restore(backup: Path, state: Path, runner: Path, links: list[Path]) -> None:
    """Return the state, runner records and Worktree links to the backup."""
    for root, name in ((state, "state"), (runner, "runner")):
        if (backup / name).is_dir():
            if root.exists():
                for path in root.rglob("*"):
                    if path.is_file() and not path.is_symlink():
                        path.chmod(0o644)
                shutil.rmtree(root)
            shutil.copytree(backup / name, root, symlinks=True)
    recorded = yaml.safe_load((backup / "worktree-links.yml").read_text(encoding="utf-8")) or {}
    for link in links:
        if os.path.lexists(link):
            link.unlink()
        link.symlink_to(recorded[str(link)], target_is_directory=True)
