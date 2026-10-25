"""Task registration and current Task Graph views."""

from __future__ import annotations

from graphtraj.configuration.project_configuration import runner_directory as project_runner_directory

import os
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from graphtraj import file_lock
from graphtraj.graph import task_protocol as protocol
from graphtraj.graph.task_protocol import validate_definition as _validate_issue
from graphtraj.graph.delivery_worldline import append_project_worldline_event
from graphtraj.execution.execution_budget import read_execution_budget


_TASK_ID = protocol.TASK_ID
_TASK_NAME = protocol.TASK_NAME
_EVENT_DEFINITION = re.compile(
    r"\d{8}T\d{6}\.\d{6}[+-]\d{4}(?:-[1-9]\d*)?\.md\Z"
)
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_STATUSES = frozenset(protocol.STATUSES)
_STATE_CHANGE_FIELDS = frozenset(protocol.STATE_CHANGE_SCHEMA["properties"])
_TRANSITIONS = {
    # Pending and ready both mean not started; dependencies decide readiness.
    "pending": {"ready", "implementing", "blocked", "escalated"},
    "ready": {"pending", "implementing", "blocked", "escalated"},
    "implementing": {"reviewing", "blocked", "escalated"},
    "reviewing": {"reworking", "awaiting-integration", "blocked", "escalated"},
    "reworking": {"implementing", "reviewing", "blocked", "escalated"},
    "awaiting-integration": {"reworking", "integrating", "blocked", "escalated"},
    "integrating": {"integrated", "resolving-integration", "blocked", "escalated"},
    "resolving-integration": {"integrating", "blocked", "escalated"},
    "integrated": set(),
    "blocked": {"pending", "ready", "escalated"},
    "escalated": {"pending", "ready", "blocked"},
}


def _validate_revision(revision: Any) -> None:
    """Validate the shared schema and definition semantics before any write."""
    from graphtraj.interfaces.gateway import _validate

    _validate(revision, protocol.REVISION_SCHEMA, "revision")
    _validate_string_list(revision, "caused_by_event_ids", allow_empty=True)
    _validate_string_list(revision, "evidence_refs", allow_empty=False)
    if "reopen_task_ids" in revision:
        _validate_string_list(revision, "reopen_task_ids", allow_empty=True)
    identifiers = []
    for definition in revision["tasks"]:
        _validate_issue({key: definition[key] for key in protocol.TASK_PROPERTIES})
        identifiers.append(definition["task_id"])
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Task revision repeats a Task")


def _validate_string_list(
    document: dict[str, Any], field: str, *, allow_empty: bool
) -> None:
    value = document[field]
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise ValueError("Task revision has invalid {0}".format(field))


def _validate_state_change(change: Any) -> None:
    if not isinstance(change, dict) or set(change) != _STATE_CHANGE_FIELDS:
        raise ValueError("Task state change is invalid")
    _validate_string_list(change, "caused_by_event_ids", allow_empty=True)
    _validate_string_list(change, "evidence_refs", allow_empty=False)
    if (
        not isinstance(change["task_id"], str)
        or _TASK_ID.fullmatch(change["task_id"]) is None
        or change["status"] not in _STATUSES
        or (change["active_team_ordinal"] is not None and (
            isinstance(change["active_team_ordinal"], bool)
            or not isinstance(change["active_team_ordinal"], int)
            or change["active_team_ordinal"] < 1
        ))
        or any(
            value is not None and (not isinstance(value, str) or not value)
            for value in (change["worktree"], change["branch"])
        )
        or (
            change["current_candidate"] is not None
            and (
                not isinstance(change["current_candidate"], str)
                or _COMMIT.fullmatch(change["current_candidate"]) is None
            )
        )
    ):
        raise ValueError("Task state change is invalid")


def register_task(state: Path, harness_root: Path, issue: dict[str, Any]) -> Path:
    """Validate an accepted definition and return its durable Task directory.

    Invalid definitions or graph changes raise ValueError before registration.
    The snapshot, current state and causal Worldline event are committed together.
    """
    _validate_issue(issue)
    tasks = state / "tasks"
    directory = tasks / "{0}-{1}".format(issue["task_id"], issue["task_name"])
    if directory.exists():
        raise ValueError("Task {0} is already registered".format(issue["task_id"]))
    if tasks.is_dir() and any(tasks.glob("{0}-*".format(issue["task_id"]))):
        raise ValueError("Task {0} is already registered".format(issue["task_id"]))
    state_record = {
        **issue,
        "current_definition": "task.md",
        "active": issue["disposition"] == "active",
        "status": "pending",
        "active_team_ordinal": None,
        "worktree": None,
        "branch": None,
        "current_candidate": None,
    }
    snapshot = protocol.render_definition(issue)
    tasks.mkdir(parents=True, exist_ok=True)
    lock = _lock(tasks, exclusive=True)
    try:
        if directory.exists() or any(tasks.glob("{0}-*".format(issue["task_id"]))):
            raise ValueError(
                "Task {0} is already registered".format(issue["task_id"])
            )
        current = _load_states(tasks)
        proposed = {task_id: record for task_id, (_, record) in current.items()}
        proposed[issue["task_id"]] = state_record
        _validate_graph(proposed)
        _require_reopened_ancestors(proposed, {key: record for key, (_, record) in current.items()})
        snapshot_path = directory / "task.md"

        def mutation(_: dict[str, Any]):
            try:
                directory.mkdir()
                snapshot_path.write_text(snapshot, encoding="utf-8")
                snapshot_path.chmod(0o444)
                _write_yaml(directory / "task.yml", state_record)
            except Exception:
                _remove_task_directory(directory)
                raise
            return lambda: _remove_task_directory(directory)

        evidence = snapshot_path.relative_to(harness_root).as_posix()
        append_project_worldline_event(
            state,
            harness_root,
            {
                "event": "task-registered",
                "caused_by_event_ids": [],
                "evidence_refs": [evidence],
                "task_id": issue["task_id"],
                "dependencies": issue["dependencies"],
            },
            mutation,
        )
    finally:
        _unlock(lock)
    return directory


def revise_tasks(
    state: Path, harness_root: Path, revision: dict[str, Any]
) -> dict[str, Any]:
    """Validate and commit a product-preserving revision with its causal event."""

    _validate_revision(revision)
    tasks = state / "tasks"
    if not tasks.is_dir():
        raise ValueError("no Tasks are registered")
    lock = _lock(tasks, exclusive=True)
    try:
        current = _load_states(tasks)
        revised = {item["task_id"]: item for item in revision["tasks"]}
        proposed = {
            task_id: dict(record) for task_id, (_, record) in current.items()
        }
        meaningful = False
        for task_id, definition in revised.items():
            if task_id in current:
                directory, old = current[task_id]
                if old["task_name"] != definition["task_name"]:
                    raise ValueError("a stable Task identity cannot change")
                if definition["current_definition"] != old["current_definition"]:
                    raise ValueError("Task current_definition changed; inspect the current definition")
                previous_budget = read_execution_budget(
                    (directory / old["current_definition"]).read_text(
                        encoding="utf-8"
                    )
                )
                revised_budget = read_execution_budget(definition["body"])
                if previous_budget is not None and revised_budget is None:
                    raise ValueError("a Task execution budget cannot be removed")
                if (
                    (
                        previous_budget is None
                        or previous_budget.definition != revised_budget.definition
                    )
                    and revised_budget is not None
                    and revised_budget.revision_reason is None
                ):
                    raise ValueError(
                        "a revised execution budget requires its reason: set "
                        "execution_budget.revision_reason in the revised body front matter"
                    )
                meaningful = meaningful or (
                    (directory / old["current_definition"]).read_text(
                        encoding="utf-8"
                    )
                    != _render_definition(definition)
                )
                record = dict(old)
                record.update(
                    active=definition["disposition"] == "active",
                    replaced_by=definition["replaced_by"],
                    dependencies=definition["dependencies"],
                )
            else:
                meaningful = True
                directory = tasks / "{0}-{1}".format(
                    task_id, definition["task_name"]
                )
                if directory.exists() or any(tasks.glob("{0}-*".format(task_id))):
                    raise ValueError("Task identity collides with existing state")
                record = {
                    "task_id": task_id,
                    "task_name": definition["task_name"],
                    "current_definition": "task.md",
                    "active": definition["disposition"] == "active",
                    "replaced_by": definition["replaced_by"],
                    "dependencies": definition["dependencies"],
                    "status": "pending",
                    "active_team_ordinal": None,
                    "worktree": None,
                    "branch": None,
                    "current_candidate": None,
                }
            if task_id not in current and definition["current_definition"] is not None:
                raise ValueError("A new Task requires current_definition: null")
            record.update({key: definition[key] for key in protocol.TASK_PROPERTIES})
            proposed[task_id] = record
        reopened = revision.get("reopen_task_ids", [])
        for task_id in reopened:
            if task_id not in revised or task_id not in current:
                raise ValueError("Reopening requires an explicit revision of each existing Task")
            record = proposed[task_id]
            if record["status"] != "integrated":
                raise ValueError("Only an integrated Task can be reopened by graph revision")
            if record["active_team_ordinal"] is not None:
                from graphtraj.execution.runner_status import caller_alias, require_task_authority
                from graphtraj.graph.delivery_worldline import read_worldline

                runner = project_runner_directory(harness_root)
                if caller_alias(runner) is not None:
                    submissions = [event for event in read_worldline(state, harness_root)
                                   if event["event"] == "result-submitted"
                                   and event.get("task_id") == task_id
                                   and event.get("candidate") == record["current_candidate"]]
                    if not submissions:
                        raise ValueError("Reopening file delivery requires its actual accepting parent")
                    require_task_authority(state, runner, task_id, submissions[-1]["alias"], "accept")
            record["status"] = "reworking" if record["active_team_ordinal"] is not None else "pending"
            meaningful = True
        if not meaningful:
            raise ValueError("Task revision does not introduce a new durable fact")
        _validate_graph(proposed)
        before = {key: record for key, (_, record) in current.items()}
        corrections = revision.get("completed_input_corrections", {})
        _validate_completed_input_corrections(proposed, before, revised, corrections)
        _require_reopened_ancestors(proposed, before, set(corrections))
        if revision.get("dry_run", False):
            from graphtraj.graph.delivery_worldline import _validate_evidence, _validate_causes, read_worldline

            _validate_evidence(harness_root, revision["evidence_refs"])
            _validate_causes(revision, read_worldline(state, harness_root))
            return {"dry_run": True, "affected_task_ids": list(revised),
                    "reopened_task_ids": reopened,
                    "current_definitions": {key: current[key][1]["current_definition"] if key in current else None
                                            for key in revised}}

        event = {
            "event": "task-graph-revised",
            "caused_by_event_ids": revision["caused_by_event_ids"],
            "evidence_refs": revision["evidence_refs"],
            "affected_task_ids": list(revised),
            "product_preserving": True,
            "reopened_task_ids": reopened,
            "completed_input_corrections": corrections,
            "reopened_results": {
                key: {"team_ordinal": current[key][1]["active_team_ordinal"],
                      "candidate": current[key][1]["current_candidate"]}
                for key in reopened
            },
        }

        def mutation(recorded: dict[str, Any]):
            changed: list[tuple[Path, bytes | None, Path]] = []
            definition_refs: dict[str, str] = {}
            try:
                for task_id, definition in revised.items():
                    if task_id in current:
                        directory, old = current[task_id]
                        definition_path = (
                            directory
                            / "definitions"
                            / "{0}.md".format(recorded["event_id"])
                        )
                        definition_path.parent.mkdir(exist_ok=True)
                        state_path = directory / "task.yml"
                        changed.append(
                            (state_path, state_path.read_bytes(), definition_path)
                        )
                        definition_path.write_text(
                            _render_definition(definition), encoding="utf-8"
                        )
                        definition_path.chmod(0o444)
                        proposed[task_id]["current_definition"] = (
                            definition_path.relative_to(directory).as_posix()
                        )
                    else:
                        directory = tasks / "{0}-{1}".format(
                            task_id, definition["task_name"]
                        )
                        directory.mkdir()
                        definition_path = directory / "task.md"
                        state_path = directory / "task.yml"
                        changed.append((state_path, None, definition_path))
                        definition_path.write_text(
                            _render_definition(definition), encoding="utf-8"
                        )
                        definition_path.chmod(0o444)
                    definition_refs[task_id] = definition_path.relative_to(
                        harness_root
                    ).as_posix()
                    _write_yaml(state_path, proposed[task_id])
                recorded["definition_refs"] = definition_refs
                recorded["evidence_refs"] = list(
                    dict.fromkeys(
                        (*recorded["evidence_refs"], *definition_refs.values())
                    )
                )
            except Exception:
                _rollback_revision(changed)
                raise
            return lambda: _rollback_revision(changed)

        return append_project_worldline_event(
            state, harness_root, event, mutation
        )
    finally:
        _unlock(lock)


def read_graph(
    state: Path,
    view: str = "current",
    task_id: str | None = None,
    details: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """Project the light Task Graph from its current index.

    Parameters
    ----------
    state : Path
        Project state directory.
    view : {"current", "full"}
        ``full`` returns every Task. ``current`` expands unfinished work in the
        scope plus its necessary inputs; every other Task is folded into its
        nearest visible ancestor, and top-level Tasks stay as coarse nodes.
    task_id : str or None
        Scope of the ``current`` view: this Task and its descendants. None
        uses the whole project.
    details : list of str
        Tasks whose full definitions and execution facts are read from disk.

    Returns
    -------
    dict
        ``tasks`` with readiness, progress, delivery and ``outcome``; the
        ``current`` view adds ``edges`` between visible endpoints and each
        visible Task's ``folded`` outcome counts.
    """
    from graphtraj.graph.task_index import read_index, task_directory

    if view not in {"current", "full"}:
        raise ValueError("Task graph view must be current or full")
    index   = read_index(state)
    records = index["tasks"]
    for key in [*([task_id] if task_id is not None else []), *details]:
        if key not in records:
            raise ValueError("Task {0} is not registered".format(key))

    delivery = _delivery_facts(index["deliveries"], records)
    children: dict[str, list[str]] = {key: [] for key in records}
    for key in sorted(records, key=int):
        if records[key]["parent_id"] is not None:
            children[records[key]["parent_id"]].append(key)
    visible = set(records) if view == "full" else _visible(records, children, task_id)

    rendered = []
    for key in sorted(visible, key=int):
        record = {field: value for field, value in records[key].items() if field != "stamp"}
        record.update(
            children=children[key],
            progress={
                "total":     len(children[key]),
                "completed": sum(_result_complete(records, child) for child in children[key]),
            },
            delivery=delivery[key],
            # Dispatch follows this derived flag, not the stored pending/ready.
            ready=record["active"] and record["status"] in {"pending", "ready"}
            and all(_result_complete(records, item) for item in record["dependencies"]),
            outcome=_outcome(record),
        )
        rendered.append(record)
    graph = {"schema_version": 2, "revision": index["revision"], "view": view, "tasks": rendered}

    if view == "current":
        _fold(graph, records, delivery, visible)
        graph["scope"] = task_id
    if details:
        graph["details"] = {
            key: _load_state(task_directory(state, index, key) / "task.yml")[1]
            for key in details
        }
    return graph


def _outcome(record: dict[str, Any]) -> str:
    """Name a Task's result without presenting retired or halted work as done."""
    if record["disposition"] != "active":
        return record["disposition"]
    return "completed" if record["status"] == "integrated" else record["status"]


def _visible(
    records: dict[str, dict[str, Any]],
    children: dict[str, list[str]],
    scope: str | None,
) -> set[str]:
    """Select the Tasks the current view expands.

    Unfinished work means an active Task that is not integrated, so blocked or
    escalated Tasks stay open while an adopted completed Task does not.
    """
    def unfinished(key: str) -> bool:
        return records[key]["active"] and records[key]["status"] != "integrated"

    region = [scope] if scope is not None else list(records)
    if scope is not None:
        for key in region:
            region.extend(children[key])
    shown = {key for key in region if unfinished(key)} | ({scope} if scope else set())

    # Necessary inputs: every dependency stays visible; unfinished inputs and
    # replacement chains are followed to the work they still wait for.
    pending = list(shown)
    while pending:
        key = pending.pop()
        for other in (*records[key]["dependencies"], *records[key]["replaced_by"]):
            if other not in shown:
                shown.add(other)
                if unfinished(other) or records[other]["replaced_by"]:
                    pending.append(other)

    # Summaries give context to what is shown; top-level Tasks remain coarse nodes.
    for key in list(shown):
        parent = records[key]["parent_id"]
        while parent is not None and parent not in shown:
            shown.add(parent)
            parent = records[parent]["parent_id"]
    return shown | {key for key, record in records.items() if record["parent_id"] is None}


def _fold(
    graph: dict[str, Any],
    records: dict[str, dict[str, Any]],
    delivery: dict[str, list[dict]],
    visible: set[str],
) -> None:
    """Project hidden Tasks and relationships onto visible ancestors.

    Each relationship keeps its direction and kind between the nearest
    visible ancestors of its real endpoints; relationships inside one folded
    summary disappear. Native relationships are not changed.
    """
    def shown(key: str) -> str:
        while key not in visible:
            key = records[key]["parent_id"]
        return key

    relations = []
    for key, record in records.items():
        relations += [(item, key, "dependency") for item in record["dependencies"]]
        relations += [(key, item, "replacement") for item in record["replaced_by"]]
        relations += [
            (key, fact["task_id"], "acceptance") for fact in delivery[key]
            if fact["event"] == "task-completed" and fact["task_id"] != key
        ]
    edges = {
        (shown(source), shown(target), kind) for source, target, kind in relations
        if shown(source) != shown(target)
    }
    graph["edges"] = [
        {"source": source, "target": target, "kind": kind}
        for source, target, kind in sorted(edges, key=lambda edge: (int(edge[0]), int(edge[1]), edge[2]))
    ]

    folded: dict[str, dict[str, int]] = {}
    for key in records.keys() - visible:
        counts = folded.setdefault(shown(key), {})
        outcome = _outcome(records[key])
        counts[outcome] = counts.get(outcome, 0) + 1
    for task in graph["tasks"]:
        task["folded"] = folded.get(task["task_id"], {})


def _delivery_facts(
    latest: dict[str, dict], records: dict[str, dict[str, Any]]
) -> dict[str, list[dict]]:
    """Project actual integration and summary acceptance from indexed events.

    Membership alone does not establish receipt. Summary completion records
    identify the exact checked results; reopened or withdrawn tasks cannot
    inherit a current completion claim from their old events.
    """
    result: dict[str, list[dict]] = {key: [] for key in records}
    for key, event in latest.items():
        record = records.get(key)
        if not record or not record["active"] or record["status"] != "integrated":
            continue
        if event.get("candidate") != record["current_candidate"]:
            continue
        fact = {field: event.get(field) for field in (
            "event_id", "event", "task_id", "candidate", "dev_commit", "reason", "evidence_refs",
        )}
        result[key].append({**fact, "accepted_definition": event.get("current_definition")})
        if event["event"] == "task-completed":
            for child, definition in (event.get("checked_definitions") or {}).items():
                child_record = records.get(child)
                if child_record and child_record["active"] and child_record["status"] == "integrated":
                    result[child].append({**fact, "accepted_definition": definition})
    return result


def update_task_state(
    state: Path, harness_root: Path, change: dict[str, Any]
) -> dict[str, Any]:
    """Validate an evidence-backed state transition and return its causal event.

    Integration states require integrate_task; invalid transitions raise
    ValueError without changing the Task or its Worldline.
    """
    _validate_state_change(change)
    tasks = state / "tasks"
    if not tasks.is_dir():
        raise ValueError("no Tasks are registered")
    lock = _lock(tasks, exclusive=True)
    try:
        current = _load_states(tasks)
        task_id = change["task_id"]
        if task_id not in current:
            raise ValueError("Task {0} is not registered".format(task_id))
        directory, record = current[task_id]
        if not record["active"]:
            raise ValueError("an inactive Task cannot change delivery state")
        old_status = record["status"]
        if change["status"] in {"integrating", "integrated"}:
            raise ValueError("Integration state requires Main's task integrate command")
        if old_status == "awaiting-integration" and change["status"] == "reworking":
            raise ValueError("Returning an accepted result requires its parent's result decision")
        if change["status"] not in _TRANSITIONS[old_status]:
            raise ValueError(
                "Task transition from {0} to {1} is invalid".format(
                    old_status, change["status"]
                )
            )
        if any(
            record[field] is not None and change[field] is None
            for field in ("active_team_ordinal", "worktree", "branch", "current_candidate")
        ):
            raise ValueError("Execution associations cannot be cleared by a generic state update")
        updated = dict(record)
        for field in (
            "status",
            "active_team_ordinal",
            "worktree",
            "branch",
            "current_candidate",
        ):
            updated[field] = change[field]
        event = {
            "event": "task-state-changed",
            "caused_by_event_ids": change["caused_by_event_ids"],
            "evidence_refs": change["evidence_refs"],
            "task_id": task_id,
            "from_status": old_status,
            "to_status": change["status"],
            "active_team_ordinal": change["active_team_ordinal"],
            "worktree": change["worktree"],
            "branch": change["branch"],
            "current_candidate": change["current_candidate"],
        }
        state_path = directory / "task.yml"

        def mutation(_: dict[str, Any]):
            previous = state_path.read_bytes()
            try:
                _write_yaml(state_path, updated)
            except Exception:
                _restore(state_path, previous)
                raise
            return lambda: _restore(state_path, previous)

        return append_project_worldline_event(
            state, harness_root, event, mutation
        )
    finally:
        _unlock(lock)


def complete_task(state: Path, harness_root: Path, request: dict[str, Any]) -> dict[str, Any]:
    """Accept a task without file delivery, preserving its own completion evidence.

    The existing top-level caller authority applies when there is no Team or
    submitted result to delegate acceptance. Actual file results must use the
    submission, acceptance and integration workflow.
    """
    from graphtraj.interfaces.gateway import _validate
    from graphtraj.execution.runner_status import caller_alias

    _validate(request, protocol.COMPLETE_SCHEMA, "completion")
    _validate_string_list(request, "evidence_refs", allow_empty=False)
    _validate_string_list(request, "caused_by_event_ids", allow_empty=True)
    if not request["reason"].strip():
        raise ValueError("Completion requires the task's own acceptance reason")
    if caller_alias(project_runner_directory(harness_root)) is not None:
        raise ValueError("Completion without a Team requires the owning top-level caller")
    tasks = state / "tasks"
    if not tasks.is_dir():
        raise ValueError("no Tasks are registered")
    lock = _lock(tasks, exclusive=True)
    try:
        current = _load_states(tasks)
        records = {key: record for key, (_, record) in current.items()}
        _validate_graph(records)
        task_id = request["task_id"]
        if task_id not in records:
            raise ValueError("Completion names an unknown Task")
        directory, record = current[task_id]
        if not record["active"]:
            raise ValueError("Completion requires an active task")
        if record["current_definition"] != request["current_definition"]:
            raise ValueError("Completion current_definition is stale")
        if record["status"] not in {"pending", "ready", "blocked", "escalated"}:
            raise ValueError("Task is already completed or has delivery in progress")
        if any(record[field] is not None for field in (
            "active_team_ordinal", "worktree", "branch", "current_candidate",
        )) or (directory / "teams").exists():
            raise ValueError("File delivery requires result submission, acceptance and integration")
        if any(not _result_complete(records, dependency) for dependency in record["dependencies"]):
            raise ValueError("Completion requires all dependency results")
        children = [key for key, child in records.items() if child.get("parent_id") == task_id]
        unfinished, cancelled, checked = _required_results(records, children)
        if unfinished:
            raise ValueError(f"Required child results are not complete: {sorted(unfinished)}")
        if set(request["cancelled_scope"]) != cancelled or any(
            not reason.strip() for reason in request["cancelled_scope"].values()
        ):
            raise ValueError("Completion must explicitly confirm every cancelled child's withdrawn scope")
        updated = {**record, "status": "integrated"}
        event = {
            "event": "task-completed", "task_id": task_id,
            "from_status": record["status"], "to_status": "integrated",
            "reason": request["reason"], "cancelled_scope": request["cancelled_scope"],
            "current_definition": record["current_definition"],
            "checked_definitions": {key: records[key]["current_definition"] for key in checked},
            "caused_by_event_ids": request["caused_by_event_ids"],
            "evidence_refs": request["evidence_refs"],
        }
        path = directory / "task.yml"
        previous = path.read_bytes()

        def mutation(_: dict[str, Any]):
            """Commit completion with the existing Worldline rollback contract."""
            try:
                _write_yaml(path, updated)
            except Exception:
                _restore(path, previous)
                raise
            return lambda: _restore(path, previous)

        return append_project_worldline_event(state, harness_root, event, mutation)
    finally:
        _unlock(lock)


def _render_definition(definition: dict[str, Any]) -> str:
    """Render the immutable Task definition."""
    return protocol.render_definition(definition)


def _load_states(tasks: Path) -> dict[str, tuple[Path, dict[str, Any]]]:
    """Merge each execution record with its single current immutable definition."""
    states: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in tasks.glob("*/task.yml"):
        task_id, record = _load_state(path)
        if task_id in states:
            raise ValueError("Task state is invalid")
        states[task_id] = (path.parent, record)
    # Hidden entries (for example a Runtime's ``.claude`` write marker) are
    # foreign to the Task layout, never a Task or a corruption of one.
    directories = {path for path in tasks.iterdir() if path.is_dir() and not path.name.startswith(".")}
    if directories != {directory for directory, _ in states.values()}:
        raise ValueError("Task state is invalid")
    return states


def _load_state(path: Path) -> tuple[str, dict[str, Any]]:
    """Merge one execution record with its single current immutable definition."""
    record = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict) or set(record) != protocol.EXECUTION_FIELDS:
        raise ValueError("Task state is invalid")
    task_id = record["task_id"]
    definition = (
        Path(record["current_definition"])
        if isinstance(record["current_definition"], str)
        else None
    )
    valid_definition = (
        definition == Path("task.md")
        or (
            definition is not None
            and definition.parent == Path("definitions")
            and _EVENT_DEFINITION.fullmatch(definition.name) is not None
        )
    )
    definition_path = path.parent / definition if definition is not None else path
    if valid_definition and definition_path.is_file() and not definition_path.is_symlink():
        definition_record = protocol.read_definition(definition_path.read_text(encoding="utf-8"))
        _validate_issue(definition_record)
        if any(definition_record[key] != record[key] for key in ("task_id", "task_name", "schema_version")):
            raise ValueError("Task definition identity differs from execution state")
        record.update(definition_record, active=definition_record["disposition"] == "active")
    if (
        not isinstance(task_id, str)
        or _TASK_ID.fullmatch(task_id) is None
        or not isinstance(record["task_name"], str)
        or _TASK_NAME.fullmatch(record["task_name"]) is None
        or path.parent.name != "{0}-{1}".format(task_id, record["task_name"])
        or not valid_definition
        or definition_path.is_symlink()
        or not definition_path.is_file()
        or not isinstance(record["active"], bool)
        or not isinstance(record["replaced_by"], list)
        or not isinstance(record["dependencies"], list)
        or any(not isinstance(item, str) for item in record["replaced_by"])
        or any(not isinstance(item, str) for item in record["dependencies"])
        or not isinstance(record["status"], str)
        or record["status"] not in _STATUSES
        or (record["active_team_ordinal"] is not None and (
            isinstance(record["active_team_ordinal"], bool)
            or not isinstance(record["active_team_ordinal"], int)
            or record["active_team_ordinal"] < 1
        ))
        or any(
            value is not None and (not isinstance(value, str) or not value)
            for value in (record["worktree"], record["branch"])
        )
        or (
            record["current_candidate"] is not None
            and (
                not isinstance(record["current_candidate"], str)
                or _COMMIT.fullmatch(record["current_candidate"]) is None
            )
        )
    ):
        raise ValueError("Task state is invalid")
    return task_id, record


def _validate_graph(records: dict[str, dict[str, Any]]) -> None:
    """Reject dangling edges and cycles, including combined result waits."""
    parents = {key: [record["parent_id"]] if record.get("parent_id") is not None else []
               for key, record in records.items()}
    dependencies = {key: record["dependencies"] for key, record in records.items()}
    replacements = {key: record["replaced_by"] for key, record in records.items()}
    for edges in (parents, dependencies, replacements):
        for key, targets in edges.items():
            if len(targets) != len(set(targets)) or any(target not in records or target == key for target in targets):
                raise ValueError("Task graph contains a dangling or self relationship")
        _validate_dag(edges)
    waits = {key: list(dependencies[key]) + list(replacements[key]) for key in records}
    for child, parent_ids in parents.items():
        for parent in parent_ids:
            waits[parent].append(child)
    _validate_dag(waits)
    for record in records.values():
        if record["active"] and record["replaced_by"]:
            raise ValueError("An active Task cannot have replacements")


def _validate_dag(edges: dict[str, list[str]]) -> None:
    """Check a directed graph using indegrees, without recursion depth limits."""
    degrees = dict.fromkeys(edges, 0)
    for targets in edges.values():
        for target in targets:
            degrees[target] += 1
    ready = [key for key, degree in degrees.items() if not degree]
    count = 0
    while ready:
        key = ready.pop()
        count += 1
        for target in edges[key]:
            degrees[target] -= 1
            if not degrees[target]:
                ready.append(target)
    if count != len(edges):
        raise ValueError("Task relationships and combined waits must form a DAG")


def _required_results(
    records: dict[str, dict[str, Any]], task_ids: list[str]
) -> tuple[set[str], set[str], set[str]]:
    """Resolve replacement chains into unfinished, cancelled and checked tasks."""
    pending = list(task_ids)
    checked, unfinished, cancelled = set(), set(), set()
    while pending:
        key = pending.pop()
        if key in checked:
            continue
        checked.add(key)
        record = records[key]
        if record["replaced_by"]:
            pending.extend(record["replaced_by"])
        elif record.get("disposition") == "cancelled":
            cancelled.add(key)
        elif not record["active"] or record["status"] != "integrated":
            unfinished.add(key)
    return unfinished, cancelled, checked


def _result_complete(records: dict[str, dict[str, Any]], task_id: str) -> bool:
    """Cancellation does not deliver a result, even at the end of a replacement."""
    unfinished, cancelled, _ = _required_results(records, [task_id])
    return not unfinished and not cancelled


def _validate_completed_input_corrections(
    records: dict[str, dict[str, Any]],
    before: dict[str, dict[str, Any]],
    revised: dict[str, dict[str, Any]],
    corrections: dict[str, str],
) -> None:
    """Check the narrow historical-input correction declared by the task owner.

    The existing revision authority, evidence and immutable definitions retain
    the semantic decision. Only additive, already-completed inputs qualify;
    this declaration cannot change lifecycle, ownership or execution budgets.
    """
    for key, reason in corrections.items():
        if key not in revised or key not in before or not reason.strip():
            raise ValueError("A completed input correction needs an existing revised task and its reason")
        old, record = before[key], records[key]
        added = set(record["dependencies"]) - set(old["dependencies"])
        if (
            old["status"] != "integrated" or record["status"] != "integrated"
            or not old["active"] or not record["active"]
            or not added or not set(old["dependencies"]) <= set(record["dependencies"])
            or any(old.get(field) != record.get(field)
                   for field in protocol.TASK_PROPERTIES if field not in {"body", "dependencies"})
            or read_execution_budget(old["body"]) != read_execution_budget(record["body"])
            or any(dependency not in before or not _result_complete(before, dependency)
                   or not _result_complete(records, dependency) for dependency in added)
        ):
            raise ValueError("Completed input correction may only add already-completed inputs to unchanged accepted scope")


def _require_reopened_ancestors(
    records: dict[str, dict[str, Any]],
    before: dict[str, dict[str, Any]],
    completed_input_corrections: set[str] | frozenset[str] = frozenset(),
) -> None:
    """Require explicit reopening when necessary scope or its results change."""
    for child, record in records.items():
        old = before.get(child, {})
        changed_scope = bool(old) and any(
            old.get(field) != record.get(field)
            for field in ("body", "dependencies", "disposition", "replaced_by", "retirement_reason")
        )
        if (record["status"] == "integrated" and record["active"] and changed_scope
                and child not in completed_input_corrections):
            raise ValueError(f"Explicitly reopen completed task {child} when revising its required scope")
        # ponytail: scan replacement chains per revision; index reverse edges if project size warrants it.
        unfinished, cancelled, _ = _required_results(records, [child])
        if not unfinished:
            if not cancelled:
                continue
            previous_cancelled = _required_results(before, [child])[1] if old else set()
            unchanged_withdrawal = (
                cancelled == previous_cancelled and not changed_scope
                and old.get("parent_id") == record.get("parent_id")
                and all(all(records[key].get(field) == before[key].get(field)
                            for field in ("body", "retirement_reason")) for key in cancelled)
            )
            if unchanged_withdrawal:
                continue
        parent = record.get("parent_id")
        while parent is not None:
            if records[parent]["status"] == "integrated":
                raise ValueError(f"Explicitly reopen completed ancestor {parent} in the same revision")
            parent = records[parent].get("parent_id")


def _write_yaml(path: Path, value: dict[str, Any]) -> None:
    """Write execution facts without duplicating a v2 immutable definition."""
    temporary = path.with_name(".{0}.tmp".format(path.name))
    stored = protocol.execution_record(value) if path.name == "task.yml" else value
    temporary.write_text(yaml.safe_dump(stored, sort_keys=False, allow_unicode=True), encoding="utf-8")
    os.replace(temporary, path)


def _restore(path: Path, contents: bytes) -> None:
    temporary = path.with_name(".{0}.rollback".format(path.name))
    temporary.write_bytes(contents)
    os.replace(temporary, path)


def _rollback_revision(changed: list[tuple[Path, bytes | None, Path]]) -> None:
    for state_path, contents, definition_path in reversed(changed):
        if contents is None:
            _remove_task_directory(state_path.parent)
            continue
        _restore(state_path, contents)
        if definition_path.exists():
            definition_path.chmod(0o644)
            definition_path.unlink()


def _remove_task_directory(directory: Path) -> None:
    if directory.exists():
        snapshot = directory / "task.md"
        if snapshot.exists():
            snapshot.chmod(0o644)
        shutil.rmtree(directory)


def _lock(tasks: Path, *, exclusive: bool) -> int:
    descriptor = os.open(str(tasks / ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
    file_lock.flock(descriptor, file_lock.LOCK_EX if exclusive else file_lock.LOCK_SH)
    return descriptor


def _unlock(descriptor: int) -> None:
    file_lock.flock(descriptor, file_lock.LOCK_UN)
    os.close(descriptor)
