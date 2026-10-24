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


def migrate_project(cwd: Path, *, preview: bool = False) -> dict[str, Any]:
    """Convert one project's retained Ticket state and return a summary.

    Parameters
    ----------
    cwd : Path
        Harness Project Root whose ``.graphtraj`` is converted.
    preview : bool
        Return the associated sources and missing facts without writing state.

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
    from graphtraj.workspace.migration_snapshot import MANIFEST, capture_sources, source_map

    snapshot_file = harness / MANIFEST
    snapshot = yaml.safe_load(snapshot_file.read_text(encoding="utf-8")) if snapshot_file.is_file() else None
    project = Path(snapshot["project"]) if snapshot else harness
    runner = harness / ".graphtraj" / ("migration-runner" if snapshot else "runner")
    available = source_map(harness, snapshot) if snapshot else None
    if not (state / "tickets").is_dir():
        raise ValueError("No Ticket state exists to convert")
    if (state / "tasks").exists():
        raise ValueError("Task state already exists; refusing to convert twice")
    missing = _missing_parent_facts(state / "tickets")
    from graphtraj.workspace.session_migration import session_sources, archive_sources

    sources = snapshot["sources"] if snapshot else session_sources(state, runner, project)
    inventory = {
        "project": str(project), "harness": str(harness), "state": str(state),
        "snapshot": snapshot is not None,
        "tasks": sorted(p.name for p in (state / "tickets").iterdir() if p.is_dir() and not p.name.startswith(".")),
        "foreign_entries": foreign_entries(state / "tickets"),
        "missing_task_facts": missing, "sessions": sources,
        "notices": ["Unassociated Runtime histories are not searched or imported.",
                    "Preview does not read native transcript contents; apply validates native identity."],
    }
    if snapshot:
        inventory["captured_sources"] = snapshot["files"]
        inventory["missing_links"] = snapshot.get("missing_links", [])
    if preview:
        return inventory
    conflicts = [item for item in sources if item.get("identity_conflicts")]
    if conflicts:
        raise ValueError("Conflicting Session associations; inspect migrate-tickets --preview metadata before applying.")
    if missing:
        raise ValueError("Legacy definitions lack required Task facts; revise them to complete "
                         "v2 definitions first: " + "; ".join(
                             f"{task_id}: {', '.join(fields)}" for task_id, fields in missing.items()))

    # Copy first so that a failed conversion returns to the unchanged data.
    stamp  = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = harness / ".graphtraj" / "backups" / ("ticket-state-" + stamp)
    backup.mkdir(parents=True)
    shutil.copytree(state, backup / "state", symlinks=True)
    if runner.is_dir():
        shutil.copytree(runner, backup / "runner", symlinks=True)
    captured = capture_sources(backup / "native-sources", sources, project, available)
    for item in captured["files"]:
        if item.get("stored"):
            item["stored"] = "native-sources/" + item["stored"]
    captured.update(project=str(project), snapshot=snapshot is not None)
    (backup / "native-sources.yml").write_text(yaml.safe_dump(captured, sort_keys=False), encoding="utf-8")
    links = _worktree_links(configuration.agent_worktrees)
    (backup / "worktree-links.yml").write_text(
        yaml.safe_dump({str(link): os.readlink(link) for link in links}), encoding="utf-8")

    counts = Counts()
    try:
        archived = archive_sources(state, project, sources, source_paths=source_map(backup, captured))
        native_sources = {item["resolved_source"] for item in sources if "resolved_source" in item}
        if snapshot:
            # A source may also have a retained in-tree copy. Preserve that raw
            # record too; original absolute provenance is not its copied location.
            for item in sources:
                for name in ("source", "resolved_source"):
                    if not item.get(name):
                        continue
                    original = Path(item[name])
                    for old, copied in ((snapshot["state_source"], state), (snapshot["runner_source"], runner)):
                        if original.is_relative_to(old):
                            native_sources.add(str(copied / original.relative_to(old)))
        for root in (state, runner):
            if root.is_dir():
                _convert_records(root, counts, native_sources)
        _convert_definitions(state / "tickets", counts)
        _move_layout(state, counts)
        _convert_state_links(state, runner, counts)
        for link in links:
            target = _path(os.readlink(link), counts)
            if target != os.readlink(link):
                link.unlink()
                link.symlink_to(target, target_is_directory=True)
                counts.add("worktree_links")
        # A pre-cutover cache must never hide converted definitions or delivery facts.
        (state / "task-index.json").unlink(missing_ok=True)
        from graphtraj.graph.task_graph import read_graph

        graph = read_graph(state, view="full")
        inventory.update(sessions=archived, converted=dict(counts), graph=graph)
        (backup / "migration.yml").write_text(yaml.safe_dump(inventory, sort_keys=False), encoding="utf-8")
    except BaseException:
        _restore(backup, state, runner, links)
        raise
    return {"backup": backup.relative_to(harness).as_posix(), "converted": dict(counts),
            "sessions": archived, "tasks": len(graph["tasks"]), "graph": graph}


def restore_project(cwd: Path, backup: Path) -> dict[str, str]:
    """Restore the complete pre-cutover state and Runner set while writes are stopped.

    Only backups produced inside this project's backup directory are accepted.
    The installed program is selected separately by the operator; backup state
    is never used as a business read fallback.
    """
    configuration = load_project_configuration(cwd)
    harness = configuration.harness_root
    if not backup.is_absolute():
        backup = harness / backup
    backup = backup.resolve()
    if backup.parent != (harness / ".graphtraj/backups").resolve():
        raise ValueError("Choose a migration backup from this project's .graphtraj/backups directory.")
    if not (backup / "state").is_dir() or not (backup / "worktree-links.yml").is_file():
        raise ValueError("Incomplete migration backup; nothing restored.")
    links = yaml.safe_load((backup / "worktree-links.yml").read_text(encoding="utf-8")) or {}
    from graphtraj.workspace.migration_snapshot import MANIFEST, restore_sources

    snapshot = (harness / MANIFEST).is_file()
    runner = harness / ".graphtraj" / ("migration-runner" if snapshot else "runner")
    _restore(backup, configuration.state, runner, [Path(link) for link in links])
    restore_sources(backup, configuration.state, runner, allow_original=not snapshot)
    return {"restored": str(backup), "next": "Use the previous installed version before resuming writes."}


def foreign_entries(tasks: Path) -> list[str]:
    """Name hidden entries beside Task directories; they are kept, never Tasks.

    ``.lock`` is the Task Graph's own lock file, not a foreign entry.
    """
    if not tasks.is_dir():
        return []
    return sorted(p.name for p in tasks.iterdir() if p.name.startswith(".") and p.name != ".lock")


def _missing_parent_facts(tickets: Path) -> dict[str, list[str]]:
    """Return each legacy Ticket that lacks the facts a Task definition requires.

    A v1 record never stated its parent, disposition or retirement reason;
    these facts cannot be inferred, so conversion stops before any change.
    """
    missing = {}
    for path in sorted(tickets.glob("*/ticket.yml")):
        record = yaml.safe_load(path.read_text(encoding="utf-8"))
        required = ["schema_version", "parent_id", "disposition", "retirement_reason"]
        if record.get("schema_version") != 2:
            missing[str(record.get("ticket_id"))] = required
            continue
        current = record.get("current_definition", "ticket.md")
        definition = path.parent / current
        if not definition.is_file():
            missing[str(record.get("ticket_id"))] = ["current_definition"]
            continue
        split = split_execution_budget_front_matter(definition.read_text(encoding="utf-8"))
        metadata = yaml.safe_load(split[1]) if split else None
        facts = metadata.get("task", {}) if isinstance(metadata, dict) else {}
        absent = [field for field in required if field not in facts]
        if absent:
            missing[str(record.get("ticket_id"))] = absent
    return dict(sorted(missing.items(), key=lambda item: int(item[0])))


def _convert_records(root: Path, counts: Counts, native_sources: set[str]) -> None:
    """Rewrite GraphTraj YAML and JSONL records under one retained root."""
    for path in sorted(root.rglob("*")):
        parts = path.relative_to(root).parts
        if (path.is_symlink() or not path.is_file() or parts[0] == "runs"
                or (root.name not in {"runner", "migration-runner"} and (parts[0] == "sessions" or "rounds" in parts or "integration" in parts))
                or "traces" in parts
                or str(path.resolve()) in native_sources):
            continue
        if path.suffix in {".yml", ".yaml"}:
            try:
                original = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                raise ValueError("Invalid GraphTraj YAML record: " + path.relative_to(root).as_posix()) from None
            if path.name in {"session.yml", "native-session.yml"} and isinstance(original, dict):
                # These records belong to the Runtime except for the explicit
                # retained ownership and source-location fields added by Runner.
                converted = dict(original)
                for field in ("retirement", "rollout_path", "activity"):
                    if field in converted:
                        converted[field] = _value(converted[field], counts, field=field)
            else:
                converted = _value(original, counts)
            if converted != original:
                _write(path, yaml.safe_dump(converted, sort_keys=False))
                counts.add("files")
        elif (path.suffix == ".jsonl"
              and (path.name in JSONL_NAMES or path.parent.name == "worldline")
              and not ("traces" in path.relative_to(root).parts and path.parent.name != "runner")):
            lines   = path.read_text(encoding="utf-8").splitlines()
            # Named structural fields are converted; user and native payloads stay unchanged.
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
    return {_key(key, counts): _value(value, counts, field=key) for key, value in record.items()}


# Only named structural values are translated. Native/user payloads may contain
# identical strings and keys; their spelling does not make them Harness metadata.
OPAQUE_FIELDS = {"body", "title", "instruction", "instructions", "prompt", "system_prompt",
                 "developer_prompt", "text", "content", "payload", "data", "record",
                 "message", "arguments", "reason", "conclusion", "native_init",
                 "adapter_request", "context_evidence", "connection", "permissions", "configuration"}
PATH_FIELDS = {"current_definition", "previous_definition", "checked_definitions", "definition", "report_file", "report_files", "report_paths",
               "result_refs", "evidence_refs", "trace_file", "rollout_path", "ticket_file", "task_file",
               "ticket_directory", "task_directory", "state_directory"}
CODE_FIELDS = {"event", "status", "launch_status", "code"}


def _value(value: Any, counts: Counts, *, field: str | None = None) -> Any:
    """Convert named structural fields, preserving user and Runtime payloads."""
    if field in OPAQUE_FIELDS:
        return value
    if isinstance(value, dict):
        return {_key(key, counts): _value(item, counts, field=field if field in PATH_FIELDS else key)
                for key, item in value.items()}
    if isinstance(value, list):
        return [_value(item, counts, field=field) for item in value]
    if isinstance(value, str):
        if field in CODE_FIELDS and value in VALUES:
            counts.add("values")
            return VALUES[value]
        if field in PATH_FIELDS:
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
    """Rename identity keys in v2 definition metadata, leaving each body unchanged."""
    for path in sorted(tickets.glob("*/ticket.md")) + sorted(tickets.glob("*/definitions/*.md")):
        text  = path.read_text(encoding="utf-8")
        split = split_execution_budget_front_matter(text)
        metadata = yaml.safe_load(split[1]) if split is not None else None
        if not isinstance(metadata, dict) or not isinstance(metadata.get("task"), dict):
            # A historical v1 snapshot is immutable evidence; only current_definition is read.
            continue
        # The front matter is generated metadata; the body follows it unchanged.
        metadata["task"] = {KEYS.get(key, key): item for key, item in metadata["task"].items()}
        converted = "---\n" + yaml.safe_dump(metadata, sort_keys=False) + "---\n" + split[2]
        if converted != text:
            _write(path, converted)
            counts.add("definitions")


def _move_layout(state: Path, counts: Counts) -> None:
    """Rename the Ticket directory and each Task's state and first definition."""
    for directory in sorted((state / "tickets").iterdir()):
        for old, new in (("ticket.yml", "task.yml"), ("ticket.md", "task.md")):
            if (directory / old).exists():
                os.replace(directory / old, directory / new)
                counts.add("files_renamed")
    os.replace(state / "tickets", state / "tasks")


def _convert_state_links(state: Path, runner: Path, counts: Counts) -> None:
    """Retarget only links into the renamed Task layout, never native external paths."""
    for root in (state, runner):
        for link in root.rglob('*'):
            if not link.is_symlink():
                continue
            original = os.readlink(link)
            target = Path(os.path.abspath(link.parent / original))
            if not target.is_relative_to(state):
                continue
            parts = list(target.relative_to(state).parts)
            if not parts or parts[0] not in {'tickets', 'tasks'}:
                continue
            parts[0] = 'tasks'
            if len(parts) == 3 and parts[-1] in {'ticket.md', 'ticket.yml'}:
                parts[-1] = parts[-1].replace('ticket', 'task')
            updated = state.joinpath(*parts)
            if updated != target:
                link.unlink()
                link.symlink_to(os.path.relpath(updated, link.parent))
                counts.add('state_links')


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
