"""Ticket registration and current Task Graph views."""

from __future__ import annotations

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
from graphtraj.execution.execution_budget import (
    read_execution_budget,
    split_execution_budget_front_matter,
)


_TICKET_ID = protocol.TICKET_ID
_TICKET_NAME = protocol.TICKET_NAME
_EVENT_DEFINITION = re.compile(
    r"\d{8}T\d{6}\.\d{6}[+-]\d{4}(?:-[1-9]\d*)?\.md\Z"
)
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_ISSUE_FIELDS = frozenset(protocol.BASE_PROPERTIES)
_STATE_FIELDS = protocol.EXECUTION_FIELDS | protocol.LEGACY_RELATIONS
_STATUSES = frozenset(protocol.STATUSES)
_STATE_CHANGE_FIELDS = frozenset(protocol.STATE_CHANGE_SCHEMA["properties"])
_TRANSITIONS = {
    "pending": {"ready", "blocked", "escalated"},
    "ready": {"implementing", "blocked", "escalated"},
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
    if "reopen_ticket_ids" in revision:
        _validate_string_list(revision, "reopen_ticket_ids", allow_empty=True)
    identifiers = []
    for definition in revision["tickets"]:
        if definition.get("schema_version") == 2:
            _validate_issue({key: definition[key] for key in protocol.TASK_PROPERTIES})
        else:
            _validate_issue({key: definition[key] for key in _ISSUE_FIELDS})
            if (definition["active"] and definition["replaced_by"]
                    or len(definition["replaced_by"]) != len(set(definition["replaced_by"]))):
                raise ValueError("Ticket revision contains invalid replacements")
        identifiers.append(definition["ticket_id"])
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Ticket revision repeats a Ticket")


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
        raise ValueError("Ticket revision has invalid {0}".format(field))


def _validate_state_change(change: Any) -> None:
    if not isinstance(change, dict) or set(change) != _STATE_CHANGE_FIELDS:
        raise ValueError("Ticket state change is invalid")
    _validate_string_list(change, "caused_by_event_ids", allow_empty=True)
    _validate_string_list(change, "evidence_refs", allow_empty=False)
    if (
        not isinstance(change["ticket_id"], str)
        or _TICKET_ID.fullmatch(change["ticket_id"]) is None
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
        raise ValueError("Ticket state change is invalid")


def register_ticket(state: Path, harness_root: Path, issue: dict[str, Any]) -> Path:
    """Validate an accepted definition and return its durable Ticket directory.

    Invalid definitions or graph changes raise ValueError before registration.
    The snapshot, current state and causal Worldline event are committed together.
    """
    _validate_issue(issue)
    tickets = state / "tickets"
    directory = tickets / "{0}-{1}".format(issue["ticket_id"], issue["ticket_name"])
    if directory.exists():
        raise ValueError("Ticket {0} is already registered".format(issue["ticket_id"]))
    if tickets.is_dir() and any(tickets.glob("{0}-*".format(issue["ticket_id"]))):
        raise ValueError("Ticket {0} is already registered".format(issue["ticket_id"]))
    state_record = {
        "ticket_id": issue["ticket_id"],
        "ticket_name": issue["ticket_name"],
        "current_definition": "ticket.md",
        "active": True,
        "replaced_by": [],
        "dependencies": issue["dependencies"],
        "status": "pending",
        "active_team_ordinal": None,
        "worktree": None,
        "branch": None,
        "current_candidate": None,
    }
    if issue.get("schema_version") == 2:
        state_record.update(issue, active=issue["disposition"] == "active")
    snapshot = _render_definition(
        {**issue, **({} if issue.get("schema_version") == 2 else {"active": True, "replaced_by": []})}
    )
    tickets.mkdir(parents=True, exist_ok=True)
    lock = _lock(tickets, exclusive=True)
    try:
        if directory.exists() or any(tickets.glob("{0}-*".format(issue["ticket_id"]))):
            raise ValueError(
                "Ticket {0} is already registered".format(issue["ticket_id"])
            )
        current = _load_states(tickets)
        proposed = {ticket_id: record for ticket_id, (_, record) in current.items()}
        proposed[issue["ticket_id"]] = state_record
        _validate_graph(proposed)
        _require_reopened_ancestors(proposed, {key: record for key, (_, record) in current.items()})
        snapshot_path = directory / "ticket.md"

        def mutation(_: dict[str, Any]):
            try:
                directory.mkdir()
                snapshot_path.write_text(snapshot, encoding="utf-8")
                snapshot_path.chmod(0o444)
                _write_yaml(directory / "ticket.yml", state_record)
            except Exception:
                _remove_ticket_directory(directory)
                raise
            return lambda: _remove_ticket_directory(directory)

        evidence = snapshot_path.relative_to(harness_root).as_posix()
        append_project_worldline_event(
            state,
            harness_root,
            {
                "event": "ticket-registered",
                "caused_by_event_ids": [],
                "evidence_refs": [evidence],
                "ticket_id": issue["ticket_id"],
                "dependencies": issue["dependencies"],
            },
            mutation,
        )
    finally:
        _unlock(lock)
    return directory


def revise_tickets(
    state: Path, harness_root: Path, revision: dict[str, Any]
) -> dict[str, Any]:
    """Validate and commit a product-preserving revision with its causal event."""

    _validate_revision(revision)
    tickets = state / "tickets"
    if not tickets.is_dir():
        raise ValueError("no Tickets are registered")
    lock = _lock(tickets, exclusive=True)
    try:
        current = _load_states(tickets)
        revised = {item["ticket_id"]: item for item in revision["tickets"]}
        proposed = {
            ticket_id: dict(record) for ticket_id, (_, record) in current.items()
        }
        meaningful = False
        for ticket_id, definition in revised.items():
            if ticket_id in current:
                directory, old = current[ticket_id]
                if old.get("schema_version") == 2 and definition.get("schema_version") != 2:
                    raise ValueError("Legacy revision is incompatible with a v2 Ticket; supply all v2 fields")
                if (
                    old["ticket_name"] != definition["ticket_name"]
                    or (definition.get("schema_version") != 2
                        and _snapshot_source(directory / "ticket.md") != definition["source"])
                ):
                    raise ValueError("a stable Ticket identity cannot change")
                if definition.get("schema_version") == 2 and definition["current_definition"] != old["current_definition"]:
                    raise ValueError("Ticket current_definition changed; inspect the current definition")
                previous_budget = read_execution_budget(
                    (directory / old["current_definition"]).read_text(
                        encoding="utf-8"
                    )
                )
                revised_budget = read_execution_budget(definition["body"])
                if previous_budget is not None and revised_budget is None:
                    raise ValueError("a Ticket execution budget cannot be removed")
                if (
                    (
                        previous_budget is None
                        or previous_budget.definition != revised_budget.definition
                    )
                    and revised_budget is not None
                    and revised_budget.revision_reason is None
                ):
                    raise ValueError("a revised execution budget requires its reason")
                meaningful = meaningful or (
                    (directory / old["current_definition"]).read_text(
                        encoding="utf-8"
                    )
                    != _render_definition(definition)
                )
                record = dict(old)
                record.update(
                    active=definition.get("disposition", "active" if definition.get("active") else "cancelled") == "active",
                    replaced_by=definition["replaced_by"],
                    dependencies=definition["dependencies"],
                )
            else:
                meaningful = True
                directory = tickets / "{0}-{1}".format(
                    ticket_id, definition["ticket_name"]
                )
                if directory.exists() or any(tickets.glob("{0}-*".format(ticket_id))):
                    raise ValueError("Ticket identity collides with existing state")
                record = {
                    "ticket_id": ticket_id,
                    "ticket_name": definition["ticket_name"],
                    "current_definition": "ticket.md",
                    "active": definition.get("disposition", "active" if definition.get("active") else "cancelled") == "active",
                    "replaced_by": definition["replaced_by"],
                    "dependencies": definition["dependencies"],
                    "status": "pending",
                    "active_team_ordinal": None,
                    "worktree": None,
                    "branch": None,
                    "current_candidate": None,
                }
            if definition.get("schema_version") == 2:
                if ticket_id not in current and definition["current_definition"] is not None:
                    raise ValueError("A new Ticket requires current_definition: null")
                record.update({key: definition[key] for key in protocol.TASK_PROPERTIES})
            proposed[ticket_id] = record
        reopened = revision.get("reopen_ticket_ids", [])
        for ticket_id in reopened:
            if ticket_id not in revised or ticket_id not in current:
                raise ValueError("Reopening requires an explicit revision of each existing Ticket")
            record = proposed[ticket_id]
            if record.get("schema_version") != 2 or record["status"] != "integrated":
                raise ValueError("Only an integrated v2 Ticket can be reopened by graph revision")
            if record["active_team_ordinal"] is not None:
                from graphtraj.execution.runner_status import caller_alias, require_task_authority
                from graphtraj.graph.delivery_worldline import read_worldline

                runner = harness_root / ".graphtraj/runner"
                if caller_alias(runner) is not None:
                    submissions = [event for event in read_worldline(state, harness_root)
                                   if event["event"] == "result-submitted"
                                   and event.get("ticket_id") == ticket_id
                                   and event.get("candidate") == record["current_candidate"]]
                    if not submissions:
                        raise ValueError("Reopening file delivery requires its actual accepting parent")
                    require_task_authority(state, runner, ticket_id, submissions[-1]["alias"], "accept")
            record["status"] = "reworking" if record["active_team_ordinal"] is not None else "pending"
            meaningful = True
        if not meaningful:
            raise ValueError("Ticket revision does not introduce a new durable fact")
        _validate_graph(proposed)
        before = {key: record for key, (_, record) in current.items()}
        corrections = revision.get("completed_input_corrections", {})
        _validate_completed_input_corrections(proposed, before, revised, corrections)
        _require_reopened_ancestors(proposed, before, set(corrections))
        if revision.get("dry_run", False):
            from graphtraj.graph.delivery_worldline import _validate_evidence, _validate_causes, read_worldline

            _validate_evidence(harness_root, revision["evidence_refs"])
            _validate_causes(revision, read_worldline(state, harness_root))
            return {"dry_run": True, "affected_ticket_ids": list(revised),
                    "reopened_ticket_ids": reopened,
                    "current_definitions": {key: current[key][1]["current_definition"] if key in current else None
                                            for key in revised}}

        event = {
            "event": "ticket-graph-revised",
            "caused_by_event_ids": revision["caused_by_event_ids"],
            "evidence_refs": revision["evidence_refs"],
            "affected_ticket_ids": list(revised),
            "product_preserving": True,
            "reopened_ticket_ids": reopened,
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
                for ticket_id, definition in revised.items():
                    if ticket_id in current:
                        directory, old = current[ticket_id]
                        definition_path = (
                            directory
                            / "definitions"
                            / "{0}.md".format(recorded["event_id"])
                        )
                        definition_path.parent.mkdir(exist_ok=True)
                        state_path = directory / "ticket.yml"
                        changed.append(
                            (state_path, state_path.read_bytes(), definition_path)
                        )
                        definition_path.write_text(
                            _render_definition(definition), encoding="utf-8"
                        )
                        definition_path.chmod(0o444)
                        proposed[ticket_id]["current_definition"] = (
                            definition_path.relative_to(directory).as_posix()
                        )
                    else:
                        directory = tickets / "{0}-{1}".format(
                            ticket_id, definition["ticket_name"]
                        )
                        directory.mkdir()
                        definition_path = directory / "ticket.md"
                        state_path = directory / "ticket.yml"
                        changed.append((state_path, None, definition_path))
                        definition_path.write_text(
                            _render_definition(definition), encoding="utf-8"
                        )
                        definition_path.chmod(0o444)
                    definition_refs[ticket_id] = definition_path.relative_to(
                        harness_root
                    ).as_posix()
                    _write_yaml(state_path, proposed[ticket_id])
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


def read_graph(state: Path) -> dict[str, Any]:
    """Project definitions and execution state without inferring old parentage."""
    tickets = state / "tickets"
    if not tickets.is_dir():
        return {"schema_version": 2, "tickets": []}
    lock = _lock(tickets, exclusive=False)
    try:
        states = _load_states(tickets)
        records = {key: record for key, (_, record) in states.items()}
        _validate_graph(records)
        delivery = _delivery_facts(state, records)
        rendered = []
        for ticket_id in sorted(records, key=int):
            record = dict(records[ticket_id])
            children = [key for key, other in records.items() if other.get("parent_id") == ticket_id]
            completed = sum(_result_complete(records, child) for child in children)
            record.update(
                parent_known=record.get("schema_version") == 2,
                children=children,
                progress={"total": len(children), "completed": completed},
                delivery=delivery[ticket_id],
                ready=record["active"] and record["status"] in {"pending", "ready"}
                and all(_result_complete(records, item) for item in record["dependencies"]),
            )
            rendered.append(record)
        return {"schema_version": 2, "tickets": rendered}
    finally:
        _unlock(lock)


def _delivery_facts(state: Path, records: dict[str, dict[str, Any]]) -> dict[str, list[dict]]:
    """Project actual integration and summary acceptance from retained events.

    Membership alone does not establish receipt. Summary completion records
    identify the exact checked results; reopened or withdrawn tasks cannot
    inherit a current completion claim from their old events.
    """
    from graphtraj.graph.delivery_worldline import read_worldline

    latest: dict[str, dict] = {}
    for event in read_worldline(state):
        if event["event"] in {"ticket-integrated", "ticket-integration-conflict-resolved", "ticket-completed"}:
            latest[event["ticket_id"]] = event
    result: dict[str, list[dict]] = {key: [] for key in records}
    for key, event in latest.items():
        record = records.get(key)
        if not record or not record["active"] or record["status"] != "integrated":
            continue
        if event.get("candidate") != record["current_candidate"]:
            continue
        fact = {field: event.get(field) for field in (
            "event_id", "event", "ticket_id", "candidate", "dev_commit", "reason", "evidence_refs",
        )}
        result[key].append({**fact, "accepted_definition": event.get("current_definition")})
        if event["event"] == "ticket-completed":
            for child, definition in event.get("checked_definitions", {}).items():
                child_record = records.get(child)
                if child_record and child_record["active"] and child_record["status"] == "integrated":
                    result[child].append({**fact, "accepted_definition": definition})
    return result


def update_ticket_state(
    state: Path, harness_root: Path, change: dict[str, Any]
) -> dict[str, Any]:
    """Validate an evidence-backed state transition and return its causal event.

    Integration states require integrate_ticket; invalid transitions raise
    ValueError without changing the Ticket or its Worldline.
    """
    _validate_state_change(change)
    tickets = state / "tickets"
    if not tickets.is_dir():
        raise ValueError("no Tickets are registered")
    lock = _lock(tickets, exclusive=True)
    try:
        current = _load_states(tickets)
        ticket_id = change["ticket_id"]
        if ticket_id not in current:
            raise ValueError("Ticket {0} is not registered".format(ticket_id))
        directory, record = current[ticket_id]
        if not record["active"]:
            raise ValueError("an inactive Ticket cannot change delivery state")
        old_status = record["status"]
        if change["status"] in {"integrating", "integrated"}:
            raise ValueError("Integration state requires Main's ticket integrate command")
        if old_status == "awaiting-integration" and change["status"] == "reworking":
            raise ValueError("Returning an accepted result requires its parent's result decision")
        if change["status"] not in _TRANSITIONS[old_status]:
            raise ValueError(
                "Ticket transition from {0} to {1} is invalid".format(
                    old_status, change["status"]
                )
            )
        if record.get("schema_version") == 2 and any(
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
            "event": "ticket-state-changed",
            "caused_by_event_ids": change["caused_by_event_ids"],
            "evidence_refs": change["evidence_refs"],
            "ticket_id": ticket_id,
            "from_status": old_status,
            "to_status": change["status"],
            "active_team_ordinal": change["active_team_ordinal"],
            "worktree": change["worktree"],
            "branch": change["branch"],
            "current_candidate": change["current_candidate"],
        }
        state_path = directory / "ticket.yml"

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


def complete_ticket(state: Path, harness_root: Path, request: dict[str, Any]) -> dict[str, Any]:
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
    if caller_alias(harness_root / ".graphtraj/runner") is not None:
        raise ValueError("Completion without a Team requires the owning top-level caller")
    tickets = state / "tickets"
    if not tickets.is_dir():
        raise ValueError("no Tickets are registered")
    lock = _lock(tickets, exclusive=True)
    try:
        current = _load_states(tickets)
        records = {key: record for key, (_, record) in current.items()}
        _validate_graph(records)
        ticket_id = request["ticket_id"]
        if ticket_id not in records:
            raise ValueError("Completion names an unknown Ticket")
        directory, record = current[ticket_id]
        if record.get("schema_version") != 2 or not record["active"]:
            raise ValueError("Completion requires an active v2 task")
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
        children = [key for key, child in records.items() if child.get("parent_id") == ticket_id]
        unfinished, cancelled, checked = _required_results(records, children)
        if unfinished:
            raise ValueError(f"Required child results are not complete: {sorted(unfinished)}")
        if set(request["cancelled_scope"]) != cancelled or any(
            not reason.strip() for reason in request["cancelled_scope"].values()
        ):
            raise ValueError("Completion must explicitly confirm every cancelled child's withdrawn scope")
        updated = {**record, "status": "integrated"}
        event = {
            "event": "ticket-completed", "ticket_id": ticket_id,
            "from_status": record["status"], "to_status": "integrated",
            "reason": request["reason"], "cancelled_scope": request["cancelled_scope"],
            "current_definition": record["current_definition"],
            "checked_definitions": {key: records[key]["current_definition"] for key in checked},
            "caused_by_event_ids": request["caused_by_event_ids"],
            "evidence_refs": request["evidence_refs"],
        }
        path = directory / "ticket.yml"
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
    """Render the selected immutable definition format."""
    if definition.get("schema_version") == 2:
        return protocol.render_definition(definition)
    replacements = ", ".join(definition["replaced_by"]) or "none"
    dependencies = ", ".join(definition["dependencies"]) or "none"
    metadata = (
        "# Ticket {0}: {1}\n\n"
        "Ticket name: {2}\n\n"
        "Source: {3}\n\n"
        "Active: {4}\n\n"
        "Replaced by: {5}\n\n"
        "Dependencies: {6}\n\n"
    ).format(
        definition["ticket_id"],
        definition["title"],
        definition["ticket_name"],
        definition["source"],
        str(definition["active"]).lower(),
        replacements,
        dependencies,
    )
    front_matter = split_execution_budget_front_matter(definition["body"])
    if front_matter is None:
        return metadata + definition["body"] + "\n"
    preserved, _, body = front_matter
    separator = "\n" if preserved.endswith(("\n", "\r")) else "\n\n"
    body = body.lstrip("\r\n")
    return preserved + separator + metadata + body + ("" if body.endswith("\n") else "\n")


def _load_states(tickets: Path) -> dict[str, tuple[Path, dict[str, Any]]]:
    """Merge each execution record with its single current immutable definition."""
    states: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in tickets.glob("*/ticket.yml"):
        record = yaml.safe_load(path.read_text(encoding="utf-8"))
        modern = isinstance(record, dict) and record.get("schema_version") == 2
        expected = protocol.EXECUTION_FIELDS | {"schema_version"} if modern else _STATE_FIELDS
        if not isinstance(record, dict) or set(record) != expected:
            raise ValueError("Ticket state is invalid")
        ticket_id = record["ticket_id"]
        definition = (
            Path(record["current_definition"])
            if isinstance(record["current_definition"], str)
            else None
        )
        valid_definition = (
            definition == Path("ticket.md")
            or (
                definition is not None
                and definition.parent == Path("definitions")
                and _EVENT_DEFINITION.fullmatch(definition.name) is not None
            )
        )
        definition_path = path.parent / definition if definition is not None else path
        if modern and valid_definition and definition_path.is_file() and not definition_path.is_symlink():
            definition_record = protocol.read_definition(definition_path.read_text(encoding="utf-8"))
            _validate_issue(definition_record)
            if any(definition_record[key] != record[key] for key in ("ticket_id", "ticket_name", "schema_version")):
                raise ValueError("Ticket definition identity differs from execution state")
            record.update(definition_record, active=definition_record["disposition"] == "active")
        if (
            not isinstance(ticket_id, str)
            or _TICKET_ID.fullmatch(ticket_id) is None
            or not isinstance(record["ticket_name"], str)
            or _TICKET_NAME.fullmatch(record["ticket_name"]) is None
            or path.parent.name != "{0}-{1}".format(ticket_id, record["ticket_name"])
            or ticket_id in states
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
            raise ValueError("Ticket state is invalid")
        if not modern:
            snapshot = definition_path.read_text(encoding="utf-8")
            front = split_execution_budget_front_matter(snapshot)
            text = front[2] if front is not None else snapshot
            heading = text.lstrip("\r\n").splitlines()[0]
            prefix = f"# Ticket {ticket_id}: "
            if not heading.startswith(prefix):
                raise ValueError("Ticket snapshot is invalid")
            parts = text.lstrip("\r\n").split("\n\n", 6)
            if len(parts) != 7:
                raise ValueError("Legacy Ticket definition is invalid")
            body = (front[0] if front is not None else "") + parts[6]
            # Unknown history is explicit; prose declarations never become facts.
            record.update(schema_version=1, parent_known=False,
                          disposition="active" if record["active"] else "superseded" if record["replaced_by"] else None,
                          retirement_reason=None, title=heading.removeprefix(prefix),
                          source=_snapshot_source(definition_path), body=body)
        states[ticket_id] = (path.parent, record)
    directories = {path for path in tickets.iterdir() if path.is_dir()}
    if directories != {directory for directory, _ in states.values()}:
        raise ValueError("Ticket state is invalid")
    return states


def _validate_graph(records: dict[str, dict[str, Any]]) -> None:
    """Reject dangling edges and cycles, including combined result waits."""
    parents = {key: [record["parent_id"]] if record.get("parent_id") is not None else []
               for key, record in records.items()}
    dependencies = {key: record["dependencies"] for key, record in records.items()}
    replacements = {key: record["replaced_by"] for key, record in records.items()}
    for edges in (parents, dependencies, replacements):
        for key, targets in edges.items():
            if len(targets) != len(set(targets)) or any(target not in records or target == key for target in targets):
                raise ValueError("Ticket graph contains a dangling or self relationship")
        _validate_dag(edges)
    waits = {key: list(dependencies[key]) + list(replacements[key]) for key in records}
    for child, parent_ids in parents.items():
        for parent in parent_ids:
            waits[parent].append(child)
    _validate_dag(waits)
    for record in records.values():
        if record["active"] and record["replaced_by"]:
            raise ValueError("An active Ticket cannot have replacements")
        if record.get("schema_version", 1) == 1 and record["active"] and any(
            not records[item]["active"] for item in record["dependencies"]
        ):
            raise ValueError("an active dependency cannot point to an inactive Ticket")


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
        raise ValueError("Ticket relationships and combined waits must form a DAG")


def _required_results(
    records: dict[str, dict[str, Any]], ticket_ids: list[str]
) -> tuple[set[str], set[str], set[str]]:
    """Resolve replacement chains into unfinished, cancelled and checked tasks."""
    pending = list(ticket_ids)
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


def _result_complete(records: dict[str, dict[str, Any]], ticket_id: str) -> bool:
    """Cancellation does not deliver a result, even at the end of a replacement."""
    unfinished, cancelled, _ = _required_results(records, [ticket_id])
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
            old.get("schema_version") != 2
            or old["status"] != "integrated" or record["status"] != "integrated"
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
        changed_scope = old.get("schema_version") == 2 and any(
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
    stored = protocol.execution_record(value) if path.name == "ticket.yml" else value
    temporary.write_text(yaml.safe_dump(stored, sort_keys=False), encoding="utf-8")
    os.replace(temporary, path)


def _restore(path: Path, contents: bytes) -> None:
    temporary = path.with_name(".{0}.rollback".format(path.name))
    temporary.write_bytes(contents)
    os.replace(temporary, path)


def _rollback_revision(changed: list[tuple[Path, bytes | None, Path]]) -> None:
    for state_path, contents, definition_path in reversed(changed):
        if contents is None:
            _remove_ticket_directory(state_path.parent)
            continue
        _restore(state_path, contents)
        if definition_path.exists():
            definition_path.chmod(0o644)
            definition_path.unlink()


def _snapshot_source(path: Path) -> str:
    """Read the external source from a known legacy Markdown definition."""
    snapshot = path.read_text(encoding="utf-8")
    front_matter = split_execution_budget_front_matter(snapshot)
    if front_matter is not None:
        _, _, snapshot = front_matter
    for line in snapshot.splitlines():
        if line.startswith("Source: "):
            return line.removeprefix("Source: ")
    raise ValueError("Ticket snapshot is invalid")


def _remove_ticket_directory(directory: Path) -> None:
    if directory.exists():
        snapshot = directory / "ticket.md"
        if snapshot.exists():
            snapshot.chmod(0o644)
        shutil.rmtree(directory)


def _lock(tickets: Path, *, exclusive: bool) -> int:
    descriptor = os.open(str(tickets / ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
    file_lock.flock(descriptor, file_lock.LOCK_EX if exclusive else file_lock.LOCK_SH)
    return descriptor


def _unlock(descriptor: int) -> None:
    file_lock.flock(descriptor, file_lock.LOCK_UN)
    os.close(descriptor)
