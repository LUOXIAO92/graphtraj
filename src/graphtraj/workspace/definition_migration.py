"""Rename each Task's unversioned ``task.md`` to its versioned definition name.

Every Task definition version is stored as ``definitions/<event_id>.md``,
named by the Worldline event that recorded it. State written before that
naming keeps the initial text in ``task.md``. This migration moves that file
to the name of the event that created the Task (``task-registered``, or the
``task-graph-revised`` event that added it), updates ``current_definition``
where it still names ``task.md``, and appends one ``task-definitions-renamed``
event mapping each old path to its new path. Earlier events keep their
original references; that mapping resolves them.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.graph.delivery_worldline import append_project_worldline_event, read_worldline
from graphtraj.graph.task_graph import (
    _EVENT_DEFINITION,
    _load_state,
    _lock,
    _unlock,
    _write_yaml,
    definition_name,
)


RETIRED_NAME = "task.md"


def migrate_task_definitions(cwd: Path, *, preview: bool = False) -> dict[str, Any]:
    """Migrate one project's Task definitions; the public command entry.

    Parameters
    ----------
    cwd : Path
        Harness Project Root whose configured state is migrated.
    preview : bool
        Return the planned renames without writing anything.

    Returns
    -------
    dict
        ``renamed`` lists each planned or applied rename. An applied run also
        returns its ``event_id`` and ``backup`` directory. A project that has
        nothing left to rename returns an empty list and writes nothing.

    Raises
    ------
    ValueError
        When any Task has a layout this migration does not support. Nothing is
        changed in that case.
    """
    configuration = load_project_configuration(cwd)
    harness       = configuration.harness_root
    stamp         = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup        = harness / ".graphtraj" / "backups" / ("task-definitions-" + stamp)
    return rename_initial_definitions(
        configuration.state, harness, preview=preview, backup=backup
    )


def rename_initial_definitions(
    state: Path,
    harness: Path,
    *,
    preview: bool = False,
    backup: Path | None = None,
) -> dict[str, Any]:
    """Plan, back up and apply the renames for one state directory.

    ``backup`` receives copies of every file the migration changes and of the
    Worldline before the event is appended. ``None`` is for a caller, such as
    the Ticket conversion, that already holds a complete backup.
    """
    tasks = state / "tasks"
    if not tasks.is_dir():
        raise ValueError("No Task state exists at {0}".format(tasks))
    lock = _lock(tasks, exclusive=True)
    try:
        plan, unchanged = _plan(state, harness)
        links           = _links_to_renamed(state, plan)
        report = {
            "tasks":     len(plan) + unchanged,
            "unchanged": unchanged,
            "renamed":   [_public(item) for item in plan],
            "links":     [str(link.relative_to(harness)) for link, _ in links],
            "preview":   preview,
        }
        if preview or not plan:
            if not plan:
                report["message"] = "Every Task definition already has a versioned name."
            return report

        if backup is not None:
            _backup(backup, state, harness, plan, links)
            report["backup"] = backup.relative_to(harness).as_posix()

        def mutation(recorded: dict[str, Any]):
            done: list[tuple[str, Path, Any]] = []
            try:
                _apply(plan, links, done)
                # Each renamed Task must load through the normal Task reader.
                for item in plan:
                    _load_state(item["directory"] / "task.yml")
            except BaseException:
                _undo(done)
                raise
            recorded["evidence_refs"] = [item["new_ref"] for item in plan]
            return lambda: _undo(done)

        event = append_project_worldline_event(
            state,
            harness,
            {
                "event": "task-definitions-renamed",
                "caused_by_event_ids": [],
                "evidence_refs": [],
                "renamed_definitions": {item["old_ref"]: item["new_ref"] for item in plan},
            },
            mutation,
        )
        report["event_id"] = event["event_id"]
        return report
    finally:
        _unlock(lock)


def _plan(state: Path, harness: Path) -> tuple[list[dict[str, Any]], int]:
    """Return the renames for every Task still holding ``task.md``.

    Every Task directory is checked before anything is written, so an
    unsupported layout stops the whole migration with the Task named.
    """
    # A Task is created by its task-registered event, or by a revision whose
    # definition_refs gives it an initial file instead of a definitions/ one.
    # Paths in older events may use earlier state layouts (tickets/ticket.md,
    # .graphtraj/state), so creators are matched by Task ID, not by path.
    creators: dict[str, list[str]] = {}
    for event in read_worldline(state):
        if event["event"] == "task-registered" and isinstance(event.get("task_id"), str):
            creators.setdefault(event["task_id"], []).append(event["event_id"])
        refs = event.get("definition_refs")
        if event["event"] == "task-graph-revised" and isinstance(refs, dict):
            for task_id, ref in refs.items():
                if isinstance(ref, str) and ref.rsplit("/", 1)[-1] in {"task.md", "ticket.md"}:
                    creators.setdefault(task_id, []).append(event["event_id"])

    plan: list[dict[str, Any]] = []
    unchanged = 0
    for directory in sorted((state / "tasks").iterdir()):
        if directory.name.startswith("."):
            continue
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("Unsupported entry in Task state: {0}".format(directory.name))
        record   = _record(directory)
        task_id  = record["task_id"]
        versions = _versions(directory)
        current  = record["current_definition"]
        old      = directory / RETIRED_NAME

        if not os.path.lexists(old):
            if current not in versions:
                raise ValueError(
                    "Task {0}: current_definition {1!r} is not one of its definitions".format(task_id, current)
                )
            unchanged += 1
            continue
        if old.is_symlink() or not old.is_file():
            raise ValueError("Task {0}: task.md is not a regular file".format(task_id))
        if current != RETIRED_NAME and current not in versions:
            raise ValueError(
                "Task {0}: current_definition {1!r} is not one of its definitions".format(task_id, current)
            )

        old_ref  = old.relative_to(harness).as_posix()
        creation = creators.get(task_id, [])
        if len(creation) != 1:
            raise ValueError(
                "Task {0}: expected one Worldline event creating it, found {1}".format(task_id, len(creation))
            )
        new = definition_name(creation[0])
        # The initial text must stay the oldest version by name.
        if any(version <= new for version in versions):
            raise ValueError(
                "Task {0}: {1} would not sort before its existing definitions".format(task_id, new)
            )
        plan.append({
            "task_id":   task_id,
            "directory": directory,
            "new":       new,
            "old_ref":   old_ref,
            "new_ref":   (directory / new).relative_to(harness).as_posix(),
            "current":   current == RETIRED_NAME,
        })
    return plan, unchanged


def _record(directory: Path) -> dict[str, Any]:
    """Read the execution record that the rename may update."""
    path = directory / "task.yml"
    if path.is_symlink() or not path.is_file():
        raise ValueError("Task directory {0} has no task.yml".format(directory.name))
    record = yaml.safe_load(path.read_text(encoding="utf-8"))
    if (
        not isinstance(record, dict)
        or not isinstance(record.get("task_id"), str)
        or not directory.name.startswith(record["task_id"] + "-")
        or not isinstance(record.get("current_definition"), str)
    ):
        raise ValueError("Task directory {0} has an unsupported task.yml".format(directory.name))
    return record


def _versions(directory: Path) -> list[str]:
    """Return a Task's existing ``definitions/<event_id>.md`` names in order."""
    definitions = directory / "definitions"
    if not os.path.lexists(definitions):
        return []
    if definitions.is_symlink() or not definitions.is_dir():
        raise ValueError("Task directory {0}: definitions is not a directory".format(directory.name))
    names = []
    for path in sorted(definitions.iterdir()):
        if path.is_symlink() or not path.is_file() or _EVENT_DEFINITION.fullmatch(path.name) is None:
            raise ValueError(
                "Task directory {0}: unsupported definition entry {1}".format(directory.name, path.name)
            )
        names.append("definitions/" + path.name)
    return names


def _links_to_renamed(state: Path, plan: list[dict[str, Any]]) -> list[tuple[Path, Path]]:
    """Return each link in state that reads a renamed ``task.md`` and its new target."""
    targets = {item["directory"] / RETIRED_NAME: item["directory"] / item["new"] for item in plan}
    links = []
    for root, directories, files in os.walk(state):
        for name in directories + files:
            path = Path(root) / name
            if path.is_symlink():
                target = Path(os.path.abspath(path.parent / os.readlink(path)))
                if target in targets:
                    links.append((path, targets[target]))
    return links


def _backup(
    backup: Path,
    state: Path,
    harness: Path,
    plan: list[dict[str, Any]],
    links: list[tuple[Path, Path]],
) -> None:
    """Copy every file the migration changes, and the Worldline, aside first."""
    backup.mkdir(parents=True)
    copies = [item["directory"] / name for item in plan for name in (RETIRED_NAME, "task.yml")]
    copies += [link for link, _ in links]
    for path in copies:
        target = backup / path.relative_to(harness)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target, follow_symlinks=False)
    shutil.copytree(state / "worldline", backup / (state / "worldline").relative_to(harness))
    (backup / "migration.yml").write_text(
        yaml.safe_dump({"renamed": [_public(item) for item in plan]}, sort_keys=False),
        encoding="utf-8",
    )


def _apply(
    plan: list[dict[str, Any]],
    links: list[tuple[Path, Path]],
    done: list[tuple[str, Path, Any]],
) -> None:
    """Rename files, update records and retarget links, logging each step."""
    for item in plan:
        directory = item["directory"]
        target    = directory / item["new"]
        target.parent.mkdir(exist_ok=True)
        # A rename keeps the read-only mode and the bytes unchanged.
        os.rename(directory / RETIRED_NAME, target)
        done.append(("file", directory / RETIRED_NAME, target))
        if item["current"]:
            path     = directory / "task.yml"
            original = path.read_bytes()
            record   = yaml.safe_load(original)
            record["current_definition"] = item["new"]
            _write_yaml(path, record)
            done.append(("record", path, original))
    for link, target in links:
        original = os.readlink(link)
        link.unlink()
        link.symlink_to(os.path.relpath(target, link.parent))
        done.append(("link", link, original))


def _undo(done: list[tuple[str, Path, Any]]) -> None:
    """Reverse applied steps, newest first."""
    for kind, path, value in reversed(done):
        if kind == "file":
            os.rename(value, path)
        elif kind == "record":
            path.write_bytes(value)
        else:
            path.unlink()
            path.symlink_to(value)


def _public(item: dict[str, Any]) -> dict[str, Any]:
    """Return the reportable part of one planned rename."""
    return {
        "task_id":                    item["task_id"],
        "from":                       item["old_ref"],
        "to":                         item["new_ref"],
        "current_definition_updated": item["current"],
    }
