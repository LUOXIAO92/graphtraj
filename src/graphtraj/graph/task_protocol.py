"""Shared Task definition schemas and versioned storage projections."""

from __future__ import annotations

import re
from typing import Any

import yaml

from graphtraj.execution.execution_budget import (
    ExecutionBudgetError, read_execution_budget, split_execution_budget_front_matter,
)

TICKET_ID = re.compile(r"[1-9]\d*\Z")
TICKET_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
ISSUE_SOURCE = re.compile(r"https://github\.com/[^/]+/[^/]+/issues/([1-9]\d*)\Z")
STATUSES = [
    "pending", "ready", "implementing", "reviewing", "reworking",
    "awaiting-integration", "integrating", "resolving-integration", "integrated",
    "blocked", "escalated",
]

BASE_PROPERTIES = {
    "ticket_id": {"type": "string"},
    "ticket_name": {"type": "string"},
    "source": {"type": "string"},
    "title": {"type": "string"},
    "body": {"type": "string"},
    "dependencies": {"type": "array", "items": {"type": "string"}},
}
TASK_PROPERTIES = {
    **BASE_PROPERTIES,
    "schema_version": {"const": 2},
    "parent_id": {"type": ["string", "null"]},
    "disposition": {"enum": ["active", "superseded", "cancelled"]},
    "replaced_by": {"type": "array", "items": {"type": "string"}},
    "retirement_reason": {"type": ["string", "null"]},
}
EXECUTION_FIELDS = {
    "ticket_id", "ticket_name", "current_definition", "status",
    "active_team_ordinal", "worktree", "branch", "current_candidate",
}
LEGACY_RELATIONS = {"active", "replaced_by", "dependencies"}


def object_schema(properties: dict, required: set | None = None) -> dict:
    """Describe a closed object with the supplied required properties."""
    return {"type": "object", "properties": properties,
            "required": sorted(properties if required is None else required),
            "additionalProperties": False}


def definition_schema(*, revision: bool = False) -> dict:
    """Expose explicit legacy and v2 alternatives through every transport."""
    legacy = dict(BASE_PROPERTIES)
    if revision:
        legacy.update(active={"type": "boolean"}, replaced_by=TASK_PROPERTIES["replaced_by"])
    modern = dict(TASK_PROPERTIES)
    if revision:
        modern["current_definition"] = {"type": ["string", "null"]}
    return {"type": "object", "properties": {**legacy, **modern},
            "anyOf": [object_schema(legacy), object_schema(modern)],
            "additionalProperties": False}


REGISTER_SCHEMA = definition_schema()
REVISION_SCHEMA = object_schema({
    "product_preserving": {"const": True},
    "caused_by_event_ids": {"type": "array", "items": {"type": "string"}},
    "evidence_refs": {"type": "array", "minItems": 1, "items": {"type": "string"}},
    "tickets": {"type": "array", "minItems": 1, "items": definition_schema(revision=True)},
    "dry_run": {"type": "boolean", "default": False},
    "reopen_ticket_ids": {"type": "array", "items": {"type": "string"}},
}, {"product_preserving", "caused_by_event_ids", "evidence_refs", "tickets"})
COMPLETE_SCHEMA = object_schema({
    "ticket_id": {"type": "string"},
    "current_definition": {"type": "string"},
    "reason": {"type": "string"},
    "cancelled_scope": {"type": "object", "additionalProperties": {"type": "string"}},
    "caused_by_event_ids": {"type": "array", "items": {"type": "string"}},
    "evidence_refs": {"type": "array", "minItems": 1, "items": {"type": "string"}},
})


def execution_record(record: dict[str, Any]) -> dict[str, Any]:
    """Persist execution facts only for v2; retain legacy storage unchanged."""
    fields = EXECUTION_FIELDS | ({"schema_version"} if record.get("schema_version") == 2
                                 else LEGACY_RELATIONS)
    return {key: value for key, value in record.items() if key in fields}


def render_definition(definition: dict[str, Any]) -> str:
    """Store structured metadata and the exact authored body in one definition.

    Execution readers unwrap the Task metadata before reading the budget.
    The Task body remains the unchanged text following the metadata delimiter.
    """
    body = definition["body"]
    metadata = {"task": {key: definition[key] for key in TASK_PROPERTIES if key != "body"}}
    return "---\n" + yaml.safe_dump(metadata, sort_keys=False) + "---\n" + body


def read_definition(snapshot: str) -> dict[str, Any]:
    """Read the v2 definition, preserving the body's exact bytes as text."""
    split = split_execution_budget_front_matter(snapshot)
    metadata = yaml.safe_load(split[1]) if split is not None else None
    if not isinstance(metadata, dict) or not isinstance(metadata.get("task"), dict):
        raise ValueError("Ticket v2 definition is invalid")
    return {**metadata["task"], "body": split[2]}


TASK_SCHEMA = object_schema({
    **TASK_PROPERTIES,
    "schema_version": {"enum": [1, 2]},
    "disposition": {"enum": ["active", "superseded", "cancelled", None]},
    "parent_known": {"type": "boolean"},
    "current_definition": {"type": "string"},
    "status": {"type": "string", "enum": STATUSES},
    "active_team_ordinal": {"type": ["integer", "null"]},
    "worktree": {"type": ["string", "null"]},
    "branch": {"type": ["string", "null"]},
    "current_candidate": {"type": ["string", "null"]},
    "active": {"type": "boolean"},
    "ready": {"type": "boolean"},
    "children": {"type": "array", "items": {"type": "string"}},
    "progress": object_schema({"total": {"type": "integer"}, "completed": {"type": "integer"}}),
})
# A missing legacy parent is unknown; null is reserved for a confirmed v2 root.
TASK_SCHEMA["required"].remove("parent_id")
TASK_SCHEMA["anyOf"] = [
    {"properties": {"schema_version": {"const": 1}}},
    {"properties": {"schema_version": {"const": 2}}, "required": ["parent_id"]},
]


def validate_definition(issue: Any) -> None:
    """Validate either an explicit v2 definition or an unchanged legacy input."""
    modern = isinstance(issue, dict) and issue.get("schema_version") == 2
    expected = set(TASK_PROPERTIES) if modern else frozenset(BASE_PROPERTIES)
    if not isinstance(issue, dict) or set(issue) != expected:
        raise ValueError("accepted Ticket definition is invalid")
    ticket_id = issue["ticket_id"]
    ticket_name = issue["ticket_name"]
    source = issue["source"]
    title = issue["title"]
    body = issue["body"]
    dependencies = issue["dependencies"]
    source_match = ISSUE_SOURCE.fullmatch(source) if isinstance(source, str) else None
    if (
        not isinstance(ticket_id, str)
        or TICKET_ID.fullmatch(ticket_id) is None
        or not isinstance(ticket_name, str)
        or TICKET_NAME.fullmatch(ticket_name) is None
        or (not modern and (source_match is None or source_match.group(1) != ticket_id))
        or (modern and (not isinstance(source, str) or not source.strip()))
        or not isinstance(title, str)
        or not title.strip()
        or not isinstance(body, str)
        or not isinstance(dependencies, list)
        or any(
            not isinstance(item, str) or TICKET_ID.fullmatch(item) is None
            for item in dependencies
        )
        or len(dependencies) != len(set(dependencies))
        or ticket_id in dependencies
    ):
        raise ValueError("accepted Ticket definition is invalid")
    if modern:
        parent = issue["parent_id"]
        disposition = issue["disposition"]
        reason = issue["retirement_reason"]
        replacements = issue["replaced_by"]
        if (type(issue["schema_version"]) is not int
                or (parent is not None and (not isinstance(parent, str) or TICKET_ID.fullmatch(parent) is None))
                or disposition not in {"active", "superseded", "cancelled"}
                or not isinstance(replacements, list)
                or any(not isinstance(item, str) or TICKET_ID.fullmatch(item) is None for item in replacements)
                or len(replacements) != len(set(replacements))
                or (disposition == "superseded") != bool(replacements)
                or (disposition == "active" and reason is not None)
                or (disposition != "active" and (not isinstance(reason, str) or not reason.strip()))):
            raise ValueError("Ticket v2 parent, disposition or retirement facts are invalid")
    try:
        read_execution_budget(body)
    except ExecutionBudgetError as error:
        raise ValueError("accepted Ticket execution budget is invalid") from error


STATE_CHANGE_SCHEMA = object_schema({
    **{key: TASK_SCHEMA["properties"][key] for key in (
        "ticket_id", "status", "active_team_ordinal", "worktree", "branch", "current_candidate",
    )},
    "caused_by_event_ids": {"type": "array", "items": {"type": "string"}},
    "evidence_refs": {"type": "array", "minItems": 1, "items": {"type": "string"}},
})
