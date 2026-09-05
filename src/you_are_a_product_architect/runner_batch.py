"""Validation and durable storage for Agent Runner batches."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Mapping

import yaml

from .runner_models import LOGICAL_ROLES, Batch, RunnerError, Task


RUN_ID = re.compile(
    r"^[0-9]{8}-[a-z0-9]+(?:-[a-z0-9]+)*(?:-[1-9][0-9]*)?$"
)
TICKET_ID = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
TICKET_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that treats repeated mapping keys as malformed."""

    def construct_mapping(self, node: yaml.Node, deep: bool = False) -> object:
        self.flatten_mapping(node)
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as error:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found unhashable key",
                    key_node.start_mark,
                ) from error
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found duplicate key",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def valid_run_id(value: object) -> bool:
    """Return whether a value is one accepted Delivery Run identity."""

    if not isinstance(value, str) or len(value) > 64 or not RUN_ID.fullmatch(value):
        return False
    semantic_name = value[9:]
    name_and_suffix = semantic_name.rsplit("-", 1)
    if (
        len(name_and_suffix) == 2
        and re.fullmatch(r"[1-9][0-9]*", name_and_suffix[1])
    ):
        semantic_name = name_and_suffix[0]
    return len(semantic_name) <= 48


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
    if not isinstance(document, dict) or set(document) not in ({"tasks"}, {"run_id", "tasks"}):
        raise RunnerError(
            "BATCH_SCHEMA_INVALID",
            "Batch input must contain tasks and no top-level Runtime settings.",
        )
    run_id = document.get("run_id")
    if run_id is not None and not valid_run_id(run_id):
        raise RunnerError(
            "RUN_ID_INVALID",
            (
                "run_id must use YYYYMMDD-short-name form with a semantic "
                "short name of at most 48 ASCII characters and at most 64 "
                "characters overall."
            ),
        )
    tasks = document["tasks"]
    if not isinstance(tasks, list) or not tasks or (run_id is not None and len(tasks) > 4):
        raise RunnerError(
            "TASK_COUNT_UNSUPPORTED",
            "A batch must contain at least one task.",
        )
    validated_tasks = tuple(
        _read_task(task_document, cwd, run_free=run_id is None)
        for task_document in tasks
    )
    ticket_ids = [task.ticket_id for task in validated_tasks]
    identities = [(task.ticket_id, task.role) for task in validated_tasks]
    if len(identities) != len(set(identities)) or (
        run_id is not None and len(ticket_ids) != len(set(ticket_ids))
    ):
        raise RunnerError(
            "TICKET_ID_DUPLICATE",
            "ticket_id values must be unique within a batch.",
        )
    return Batch(
        run_id=run_id,
        tasks=validated_tasks,
        source_bytes=source_bytes,
    )


def validate_batch_roles(
    batch: Batch,
    role_bindings: Mapping[str, object],
) -> None:
    """Require every logical task role to have a selected-Runtime binding."""

    if any(task.role not in role_bindings for task in batch.tasks):
        raise RunnerError(
            "ROLE_NOT_CONFIGURED",
            "The selected logical Engineer role is not configured.",
        )


def _read_task(
    task_document: object,
    cwd: Path,
    *,
    run_free: bool = False,
) -> Task:
    """Validate and resolve one task without changing the supplied choices."""

    required = {"ticket_id", "ticket_name", "role"}
    if not run_free:
        required.add("ticket_file")
    allowed = required | {
        "instruction",
        "skills",
        "report_file",
        "review_round",
    }
    if (
        not isinstance(task_document, dict)
        or not required.issubset(task_document)
        or not set(task_document).issubset(allowed)
    ):
        raise RunnerError(
            "TASK_SCHEMA_INVALID",
            "A task must contain ticket identity, role, ticket_file, and only supported task access.",
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
    role = task_document["role"]
    if (
        not isinstance(role, str)
        or role not in LOGICAL_ROLES
    ):
        raise RunnerError(
            "ROLE_NOT_CONFIGURED",
            "The selected logical Engineer role is not configured.",
        )
    ticket_path = None
    ticket_content = ""
    if not run_free:
        ticket_value = task_document["ticket_file"]
        if not isinstance(ticket_value, str) or not ticket_value:
            raise RunnerError(
                "TICKET_FILE_INVALID",
                "ticket_file must resolve to a readable UTF-8 regular file.",
            )
        ticket_path = Path(ticket_value)
        if not ticket_path.is_absolute():
            ticket_path = cwd / ticket_path
        try:
            ticket_path = ticket_path.resolve(strict=True)
            if not ticket_path.is_file() or not os.access(ticket_path, os.R_OK):
                raise OSError("ticket is not a readable regular file")
            ticket_content = ticket_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise RunnerError(
                "TICKET_FILE_INVALID",
                "ticket_file must resolve to a readable UTF-8 regular file.",
            ) from error
    instruction = task_document.get("instruction")
    if instruction is not None and (
        not isinstance(instruction, str) or not instruction.strip()
    ):
        raise RunnerError(
            "INSTRUCTION_INVALID",
            "instruction must be non-empty plain text when supplied.",
        )
    requested_skills = task_document.get("skills", [])
    if (
        not isinstance(requested_skills, list)
        or any(
            not isinstance(name, str) or not name.strip()
            for name in requested_skills
        )
        or len(requested_skills) != len(set(requested_skills))
    ):
        raise RunnerError(
            "SKILL_SELECTION_INVALID",
            "skills must be a list of unique non-empty semantic Skill names.",
        )
    report_file = None if run_free else _read_report_file(task_document.get("report_file"), role)
    review_round = task_document.get("review_round")
    reviewer = role in {"standards-reviewer", "spec-reviewer"}
    if not run_free and reviewer != (
        isinstance(review_round, int)
        and not isinstance(review_round, bool)
        and review_round > 0
    ):
        raise RunnerError(
            "TASK_SCHEMA_INVALID",
            "Reviewer tasks require one positive review_round; Engineer tasks do not accept one.",
        )
    return Task(
        ticket_id=ticket_id,
        ticket_name=ticket_name,
        role=role,
        ticket_file=ticket_path,
        ticket_content=ticket_content,
        instruction=instruction,
        requested_skills=tuple(requested_skills),
        report_file=report_file,
        review_round=review_round,
    )


def _read_report_file(value: object, role: str) -> Path | None:
    reviewer = role in {"standards-reviewer", "spec-reviewer"}
    if value is None:
        if reviewer:
            raise RunnerError(
                "REPORT_FILE_INVALID",
                "A Reviewer task must supply one report_file beneath "
                ".state/reviews/.",
            )
        return None
    path = Path(value) if isinstance(value, str) else Path()
    if (
        not reviewer
        or not isinstance(value, str)
        or path.is_absolute()
        or len(path.parts) != 3
        or path.parts[:2] != (".state", "reviews")
        or path.name in {".", ".."}
        or path.suffix != ".md"
    ):
        raise RunnerError(
            "REPORT_FILE_INVALID",
            "report_file must name one Markdown file beneath "
            ".state/reviews/ for a Reviewer task.",
        )
    return path


def retain_batch(state: Path, batch: Batch) -> Path:
    """Retain the exact validated input without overwriting prior batches."""

    if batch.run_id is None:
        run_directory = state / "batches"
        _safe_directory(run_directory, state)
        stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S.%f%z")
        for suffix in range(10000):
            name = "{0}{1}.yml".format(stamp, "" if suffix == 0 else "-{0}".format(suffix))
            target = run_directory / name
            try:
                descriptor = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                continue
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(batch.source_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            _sync_directory(run_directory)
            return target.resolve()
        raise RunnerError("BATCH_RETENTION_FAILED", "The validated batch input could not be retained.")
    run_directory = state / batch.run_id
    _safe_directory(run_directory, state)
    for ordinal in range(1, 10000):
        name = "batch.yml" if ordinal == 1 else "batch-{0}.yml".format(ordinal)
        target = run_directory / name
        try:
            descriptor = os.open(
                str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
        except FileExistsError:
            try:
                if target.is_file() and target.read_bytes() == batch.source_bytes:
                    return target.resolve()
            except OSError:
                pass
            continue
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(batch.source_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            _sync_directory(run_directory)
            return target.resolve()
        except OSError as error:
            raise RunnerError(
                "BATCH_RETENTION_FAILED",
                "The validated batch input could not be retained.",
            ) from error
    raise RunnerError(
        "BATCH_RETENTION_FAILED",
        "The validated batch input could not be retained.",
    )


def evidence_path(state: Path, run_id: str, task: Task) -> Path:
    """Return one ticket's deterministic persistent evidence path."""

    return (state / run_id / "tickets" / task.stem).resolve()


def prepare_evidence(state: Path, run_id: str, task: Task) -> Path:
    """Create the one persistent evidence directory for a validated ticket."""

    evidence = evidence_path(state, run_id, task)
    _safe_directory(evidence, state)
    return evidence.resolve()


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
