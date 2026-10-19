"""Shared Task definition schemas and versioned storage projections."""

from __future__ import annotations

import re
from typing import Any

import yaml

from graphtraj.execution.execution_budget import (
    ExecutionBudgetError, read_execution_budget, split_execution_budget_front_matter,
)

TASK_ID = re.compile(r"[1-9]\d*\Z")
TASK_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
STATUSES = [
    "pending", "ready", "implementing", "reviewing", "reworking",
    "awaiting-integration", "integrating", "resolving-integration", "integrated",
    "blocked", "escalated",
]

TASK_PROPERTIES = {
    "task_id": {"type": "string"},
    "task_name": {"type": "string"},
    "source": {"type": "string"},
    "title": {"type": "string"},
    "body": {"type": "string"},
    "dependencies": {"type": "array", "items": {"type": "string"}},
    "schema_version": {"const": 2},
    "parent_id": {"type": ["string", "null"]},
    "disposition": {"enum": ["active", "superseded", "cancelled"]},
    "replaced_by": {"type": "array", "items": {"type": "string"}},
    "retirement_reason": {"type": ["string", "null"]},
}
EXECUTION_FIELDS = {
    "task_id", "task_name", "current_definition", "status",
    "active_team_ordinal", "worktree", "branch", "current_candidate", "schema_version",
}


def object_schema(properties: dict, required: set | None = None) -> dict:
    """Describe a closed object with the supplied required properties."""
    return {"type": "object", "properties": properties,
            "required": sorted(properties if required is None else required),
            "additionalProperties": False}


def definition_schema(*, revision: bool = False) -> dict:
    """Describe one complete Task definition, optionally with its revision base."""
    properties = dict(TASK_PROPERTIES)
    if revision:
        properties["current_definition"] = {"type": ["string", "null"]}
        properties["body"] = {
            "type": "string",
            "description": "Complete Task body. A changed execution budget states its reason "
                           "in the body front matter as execution_budget.revision_reason.",
        }
    return object_schema(properties)


REGISTER_SCHEMA = definition_schema()
REVISION_SCHEMA = object_schema({
    "product_preserving": {"const": True},
    "caused_by_event_ids": {"type": "array", "items": {"type": "string"}},
    "evidence_refs": {"type": "array", "minItems": 1, "items": {"type": "string"}},
    "tasks": {"type": "array", "minItems": 1, "items": definition_schema(revision=True)},
    "dry_run": {"type": "boolean", "default": False},
    "reopen_task_ids": {"type": "array", "items": {"type": "string"}},
    "completed_input_corrections": {
        "type": "object", "additionalProperties": {"type": "string"},
        "description": "Completed task IDs mapped to the owner's evidence-backed reason for recording already-consumed completed inputs without changing the accepted scope.",
    },
}, {"product_preserving", "caused_by_event_ids", "evidence_refs", "tasks"})
COMPLETE_SCHEMA = object_schema({
    "task_id": {"type": "string"},
    "current_definition": {"type": "string"},
    "reason": {"type": "string"},
    "cancelled_scope": {"type": "object", "additionalProperties": {"type": "string"}},
    "caused_by_event_ids": {"type": "array", "items": {"type": "string"}},
    "evidence_refs": {"type": "array", "minItems": 1, "items": {"type": "string"}},
})


def execution_record(record: dict[str, Any]) -> dict[str, Any]:
    """Persist only execution facts; the immutable definition holds the rest."""
    return {key: value for key, value in record.items() if key in EXECUTION_FIELDS}


def render_definition(definition: dict[str, Any]) -> str:
    """Store structured metadata and the exact authored body in one definition.

    Execution readers unwrap the Task metadata before reading the budget.
    The Task body remains the unchanged text following the metadata delimiter.
    """
    body = definition["body"]
    metadata = {"task": {key: definition[key] for key in TASK_PROPERTIES if key != "body"}}
    return "---\n" + yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True) + "---\n" + body


def read_definition(snapshot: str) -> dict[str, Any]:
    """Read the v2 definition, preserving the body's exact bytes as text."""
    split = split_execution_budget_front_matter(snapshot)
    metadata = yaml.safe_load(split[1]) if split is not None else None
    if not isinstance(metadata, dict) or not isinstance(metadata.get("task"), dict):
        raise ValueError("Task definition is invalid")
    return {**metadata["task"], "body": split[2]}


TASK_SCHEMA = object_schema({
    **TASK_PROPERTIES,
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
    "delivery": {"type": "array", "items": object_schema({
        "event_id": {"type": "string"},
        "event": {"type": "string"},
        "task_id": {"type": "string"},
        "candidate": {"type": ["string", "null"]},
        "dev_commit": {"type": ["string", "null"]},
        "reason": {"type": ["string", "null"]},
        "accepted_definition": {"type": ["string", "null"]},
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
    })},
})


def validate_definition(issue: Any) -> None:
    """Validate one complete Task definition; the source is any nonempty text."""
    if not isinstance(issue, dict) or set(issue) != set(TASK_PROPERTIES):
        raise ValueError("accepted Task definition is invalid")
    task_id = issue["task_id"]
    task_name = issue["task_name"]
    source = issue["source"]
    title = issue["title"]
    body = issue["body"]
    dependencies = issue["dependencies"]
    if (
        not isinstance(task_id, str)
        or TASK_ID.fullmatch(task_id) is None
        or not isinstance(task_name, str)
        or TASK_NAME.fullmatch(task_name) is None
        or not isinstance(source, str)
        or not source.strip()
        or not isinstance(title, str)
        or not title.strip()
        or not isinstance(body, str)
        or not isinstance(dependencies, list)
        or any(
            not isinstance(item, str) or TASK_ID.fullmatch(item) is None
            for item in dependencies
        )
        or len(dependencies) != len(set(dependencies))
        or task_id in dependencies
    ):
        raise ValueError("accepted Task definition is invalid")
    parent = issue["parent_id"]
    disposition = issue["disposition"]
    reason = issue["retirement_reason"]
    replacements = issue["replaced_by"]
    if (type(issue["schema_version"]) is not int
            or (parent is not None and (not isinstance(parent, str) or TASK_ID.fullmatch(parent) is None))
            or disposition not in {"active", "superseded", "cancelled"}
            or not isinstance(replacements, list)
            or any(not isinstance(item, str) or TASK_ID.fullmatch(item) is None for item in replacements)
            or len(replacements) != len(set(replacements))
            or (disposition == "superseded") != bool(replacements)
            or (disposition == "active" and reason is not None)
            or (disposition != "active" and (not isinstance(reason, str) or not reason.strip()))):
        raise ValueError("Task parent, disposition or retirement facts are invalid")
    try:
        read_execution_budget(body)
    except ExecutionBudgetError as error:
        raise ValueError("accepted Task execution budget is invalid") from error


STATE_CHANGE_SCHEMA = object_schema({
    **{key: TASK_SCHEMA["properties"][key] for key in (
        "task_id", "status", "active_team_ordinal", "worktree", "branch", "current_candidate",
    )},
    "caused_by_event_ids": {"type": "array", "items": {"type": "string"}},
    "evidence_refs": {"type": "array", "minItems": 1, "items": {"type": "string"}},
})
