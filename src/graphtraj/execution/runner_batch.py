"""Validation and durable storage for Agent Runner batches."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Mapping

import yaml

from graphtraj.configuration.project_roles import (
    ROLE_NAMES,
    ROLE_REFERENCES,
    ProjectRolesError,
    RolePreset,
    _UniqueKeyLoader,
    parse_inline_role,
)
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

    source = batch_file if batch_file.is_absolute() else cwd / batch_file
    try:
        source = source.resolve(strict=True)
        if not source.is_file():
            raise OSError("batch input is not a regular file")
        source_bytes = source.read_bytes()
        source_text = source_bytes.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise RunnerError(
            "BATCH_FILE_INVALID",
            "Batch input must resolve to a readable UTF-8 regular file.",
        ) from error
    try:
        document = yaml.load(source_text, Loader=_UniqueKeyLoader)
    except yaml.YAMLError as error:
        raise RunnerError(
            "BATCH_YAML_INVALID", "Batch input is not valid YAML."
        ) from error
    if not isinstance(document, dict) or set(document) != {"tasks"}:
        raise RunnerError(
            "BATCH_SCHEMA_INVALID",
            "Batch input must contain tasks and no top-level Runtime settings.",
        )
    tasks = document["tasks"]
    if not isinstance(tasks, list) or not tasks:
        raise RunnerError(
            "TASK_COUNT_UNSUPPORTED",
            "A batch must contain at least one task.",
        )
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
        source_bytes=source_bytes,
    )


def resolved_role_preset(
    task: Task, role_bindings: Mapping[str, RolePreset]
) -> RolePreset:
    """Return one task's immutable inline or reusable Runtime settings."""

    if task.inline_preset is not None:
        return task.inline_preset
    return role_bindings[task.role]


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
    if isinstance(role_value, str):
        role = ROLE_REFERENCES.get(role_value, role_value)
        if role not in ROLE_NAMES:
            raise RunnerError(
                "ROLE_NOT_CONFIGURED",
                "The selected logical Engineer role is not configured.",
            )
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
        policy_role = role if role in ROLE_NAMES else "temporary-role"
    else:
        raise RunnerError(
            "ROLE_NOT_CONFIGURED",
            "The selected logical Engineer role is not configured.",
        )
    requested_skills = task_document.get("skills", [])
    if (
        not isinstance(requested_skills, list)
        or any(not isinstance(name, str) or not name.strip() for name in requested_skills)
        or len(requested_skills) != len(set(requested_skills))
        or ("skills" in task_document and policy_role not in {
            "engineer-junior", "engineer-senior", "engineer-expert",
        })
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
