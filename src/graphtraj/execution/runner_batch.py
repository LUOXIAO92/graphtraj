"""Validation and durable storage for Agent Runner batches."""

from __future__ import annotations

import os
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

from graphtraj.configuration.project_roles import (
    ROLE_REFERENCE,
    ProjectRolesError,
    _UniqueKeyLoader,
    logical_role,
    parse_inline_role,
    retained_role_reference,
)
from graphtraj.configuration.role_definitions import has_packaged_role
from graphtraj.execution.runner_models import Batch, RunnerError, Task


TICKET_ID = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
TICKET_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def valid_ticket_id(value: object) -> bool:
    """Return whether a value is one accepted stable ticket identity."""

    return isinstance(value, str) and TICKET_ID.fullmatch(value) is not None


def valid_ticket_name(value: object) -> bool:
    """Return whether a value is one accepted ticket artifact name."""

    return (
        isinstance(value, str)
        and len(value) <= 64
        and TICKET_NAME.fullmatch(value) is not None
    )


def read_batch(
    batch_file: Path,
    cwd: Path,
) -> Batch:
    """Read and strictly validate one complete YAML batch input."""

    document, source_bytes = _read_document(batch_file, cwd)
    return replace(parse_batch(document), source_bytes=source_bytes)


def read_swarm(
    swarm_file: Path,
    cwd: Path,
    caller_ticket_id: str | None,
    registered_tickets: Mapping[str, str],
) -> Batch:
    """Read one swarm launch input and project each task's current Ticket.

    The file is validated exactly like a structured swarm document; only the
    Ticket identity a caller must not repeat per task is filled in from the
    calling Session and the registered Ticket state.
    """
    document, source_bytes = _read_document(swarm_file, cwd)
    resolved = _resolved_swarm(document, caller_ticket_id, registered_tickets)
    batch = parse_batch(resolved)
    # An input that already names every task's identity keeps its own bytes as
    # the retained record; when the caller left identity out, the resolved
    # document is recorded instead, so a later read still finds it.
    if document["tasks"] != resolved["tasks"]:
        return batch
    return replace(batch, source_bytes=source_bytes)


def _read_document(
    source_file: Path,
    cwd: Path,
) -> tuple[Any, bytes]:
    """Read one YAML launch input document and retain its exact bytes."""

    source = source_file if source_file.is_absolute() else cwd / source_file
    try:
        source = source.resolve(strict=True)
        if not source.is_file():
            raise OSError("launch input is not a regular file")
        source_bytes = source.read_bytes()
        source_text = source_bytes.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise RunnerError(
            "BATCH_FILE_INVALID",
            "Launch input must resolve to a readable UTF-8 regular file.",
        ) from error
    try:
        document = yaml.load(source_text, Loader=_UniqueKeyLoader)
    except yaml.YAMLError as error:
        raise RunnerError(
            "BATCH_YAML_INVALID", "Launch input is not valid YAML."
        ) from error
    return document, source_bytes


def parse_swarm(
    document: object,
    caller_ticket_id: str | None,
    registered_tickets: Mapping[str, str],
) -> Batch:
    """Validate one swarm launch input and project each task's current Ticket.

    Each task names the role alias to activate and the launch instruction it
    receives. Ticket identity is not repeated per task: a caller working inside
    a Ticket Session keeps that Ticket, and a name left out is read from the
    registered Ticket state Main selected through the DAG. A task may still
    name the Ticket its caller selected, which the existing Ticket and
    authority checks keep judging.

    The returned Batch is the resolved, self-contained record: every later read
    of the retained file (continue, worker start, Session lookup) still finds
    complete task identity. Returns Batch, or raises RunnerError before any
    dispatch or retention.
    """
    return parse_batch(_resolved_swarm(document, caller_ticket_id, registered_tickets))


def _resolved_swarm(
    document: object,
    caller_ticket_id: str | None,
    registered_tickets: Mapping[str, str],
) -> dict[str, Any]:
    """Return the swarm document whose tasks all carry complete identity."""
    tasks = _launch_input_tasks(document)
    return {
        "tasks": [
            _resolve_swarm_task(task, caller_ticket_id, registered_tickets)
            for task in tasks
        ]
    }


def _launch_input_tasks(document: object) -> list[Any]:
    """Return the task documents of one launch input, or refuse the input."""
    if not isinstance(document, dict) or set(document) != {"tasks"}:
        raise RunnerError(
            "BATCH_SCHEMA_INVALID",
            "Launch input must contain tasks and no top-level Runtime settings.",
        )
    tasks = document["tasks"]
    if not isinstance(tasks, list) or not tasks:
        raise RunnerError(
            "TASK_COUNT_UNSUPPORTED",
            "A launch must contain at least one task.",
        )
    return tasks


def _resolve_swarm_task(
    task: object,
    caller_ticket_id: str | None,
    registered_tickets: Mapping[str, str],
) -> dict[str, Any]:
    """Return one swarm task with the Ticket identity its caller left out.

    A supplied Ticket id wins over the calling Session's own Ticket, so Main's
    DAG selection and a Leader's own Ticket both work; a missing name is that
    registered Ticket's name.
    """
    allowed = {"ticket_id", "ticket_name", "role", "instruction", "skills"}
    if not isinstance(task, dict) or "role" not in task or not set(task) <= allowed:
        raise RunnerError(
            "TASK_SCHEMA_INVALID",
            "A swarm task must contain a role and only supported instruction, "
            "Repository Skill selection or Ticket selection.",
        )
    ticket_id = task.get("ticket_id", caller_ticket_id)
    if ticket_id is None:
        raise RunnerError(
            "TASK_SCHEMA_INVALID",
            "A swarm task outside a Ticket Session must select the Ticket Main dispatched.",
        )
    ticket_name = task.get("ticket_name")
    if ticket_name is not None:
        return {**task, "ticket_id": ticket_id}
    ticket_name = registered_tickets.get(ticket_id)
    if ticket_name is None:
        raise RunnerError(
            "invalid-ticket", "The selected swarm Ticket is not registered."
        )
    return {**task, "ticket_id": ticket_id, "ticket_name": ticket_name}


def parse_batch(document: object) -> Batch:
    """Validate a structured Batch document and retain its YAML representation.

    Uses the same schema and RunnerError codes as read_batch and parse_swarm.
    File input keeps its original bytes; Python mappings retain an equivalent
    YAML document. Neither path provisions resources or launches a Runtime.
    """
    tasks = _launch_input_tasks(document)
    validated_tasks = tuple(
        _read_task(task_document)
        for task_document in tasks
    )
    identities = [(task.ticket_id, task.role) for task in validated_tasks]
    if len(identities) != len(set(identities)):
        raise RunnerError(
            "TICKET_ID_DUPLICATE",
            "A Batch cannot repeat the same Ticket, Team generation, and role.",
        )
    return Batch(
        tasks=validated_tasks,
        source_bytes=yaml.safe_dump(document, sort_keys=False).encode("utf-8"),
    )


def _read_task(
    task_document: object,
) -> Task:
    """Validate and resolve one task without changing the supplied choices."""

    required = {"ticket_id", "ticket_name", "role"}
    allowed = required | {"instruction", "skills"}
    if (
        not isinstance(task_document, dict)
        or not required.issubset(task_document)
        or not set(task_document).issubset(allowed)
    ):
        raise RunnerError(
            "TASK_SCHEMA_INVALID",
            "A task must contain ticket identity, role, and only supported instruction or Repository Skill selection.",
        )
    ticket_id = task_document["ticket_id"]
    if not valid_ticket_id(ticket_id):
        raise RunnerError(
            "TICKET_ID_INVALID",
            "ticket_id must be 1-32 ASCII letters, digits, dots, underscores, or hyphens.",
        )
    ticket_name = task_document["ticket_name"]
    if not valid_ticket_name(ticket_name):
        raise RunnerError(
            "TICKET_NAME_INVALID",
            "ticket_name must be 1-64 ASCII lowercase kebab-case characters.",
        )
    role_value = task_document["role"]
    inline_preset = None
    role_reference = None
    if isinstance(role_value, str):
        role_reference = retained_role_reference(role_value)
        if ROLE_REFERENCE.fullmatch(role_reference) is None:
            raise RunnerError(
                "ROLE_NOT_CONFIGURED",
                "The selected role reference is not a configured preset reference.",
            )
        role = logical_role(role_reference)
        policy_role = role
    elif isinstance(role_value, dict):
        try:
            role, inline_preset = parse_inline_role(role_value)
        except ProjectRolesError as error:
            raise RunnerError(
                "ROLE_NOT_CONFIGURED",
                "The selected inline role is invalid: {0}".format(
                    " ".join(error.diagnostics)
                ),
            ) from error
        role_reference = next(iter(role_value))
        policy_role = role if has_packaged_role(role) else "temporary-role"
    else:
        raise RunnerError(
            "ROLE_NOT_CONFIGURED",
            "The selected role reference is not a configured preset reference.",
        )
    requested_skills = task_document.get("skills", [])
    if (
        not isinstance(requested_skills, list)
        or any(not isinstance(name, str) or not name.strip() for name in requested_skills)
        or len(requested_skills) != len(set(requested_skills))
        or ("skills" in task_document and policy_role != "engineer")
    ):
        raise RunnerError(
            "SKILL_SELECTION_INVALID",
            "Engineer skills must be unique non-empty Repository Skill names.",
        )
    instruction = task_document.get("instruction")
    if instruction is not None and (
        not isinstance(instruction, str) or not instruction.strip()
    ):
        raise RunnerError(
            "INSTRUCTION_INVALID",
            "instruction must be non-empty plain text when supplied.",
        )
    return Task(
        ticket_id=ticket_id,
        ticket_name=ticket_name,
        role=role,
        ticket_file=None,
        ticket_content="",
        instruction=instruction,
        requested_skills=tuple(requested_skills),
        inline_preset=inline_preset,
        policy_role=policy_role,
        role_reference=role_reference,
    )


def retain_batch(state: Path, batch: Batch) -> Path:
    """Retain the exact validated input without overwriting prior batches."""

    batch_directory = state / "batches"
    _safe_directory(batch_directory, state)
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S.%f%z")
    for suffix in range(10000):
        name = "{0}{1}.yml".format(stamp, "" if suffix == 0 else "-{0}".format(suffix))
        target = batch_directory / name
        try:
            descriptor = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(batch.source_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            target.chmod(0o444)
            _sync_directory(batch_directory)
            return target.resolve()
        except OSError as error:
            target.unlink(missing_ok=True)
            raise RunnerError(
                "BATCH_RETENTION_FAILED",
                "The validated batch input could not be retained.",
            ) from error
    raise RunnerError("BATCH_RETENTION_FAILED", "The validated batch input could not be retained.")


def _safe_directory(path: Path, boundary: Path) -> None:
    try:
        boundary.mkdir(parents=True, exist_ok=True)
        boundary = boundary.resolve(strict=True)
        path.mkdir(parents=True, exist_ok=True)
        resolved = path.resolve()
        if path.is_symlink() or boundary not in (resolved, *resolved.parents):
            raise OSError("directory escapes its state boundary")
    except OSError as error:
        raise RunnerError(
            "STATE_DIRECTORY_INVALID",
            "The persistent Harness State Directory is invalid or unwritable.",
        ) from error


def _sync_directory(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
