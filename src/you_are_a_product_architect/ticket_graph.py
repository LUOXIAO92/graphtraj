"""Ticket registration and current Task Graph views."""

from __future__ import annotations

import fcntl
import os
import re
import shutil
from pathlib import Path
from typing import Any

import click
import yaml

from .delivery_worldline import append_project_worldline_event
from .project_configuration import ProjectConfigurationError, load_project_configuration


_TICKET_ID = re.compile(r"[1-9]\d*\Z")
_TICKET_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_ISSUE_SOURCE = re.compile(r"https://github\.com/[^/]+/[^/]+/issues/([1-9]\d*)\Z")
_EVENT_DEFINITION = re.compile(
    r"\d{8}T\d{6}\.\d{6}[+-]\d{4}(?:-[1-9]\d*)?\.md\Z"
)
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_ISSUE_FIELDS = frozenset(
    {"ticket_id", "ticket_name", "source", "title", "body", "dependencies"}
)
_REVISION_FIELDS = frozenset(
    {"product_preserving", "caused_by_event_ids", "evidence_refs", "tickets"}
)
_REVISED_TICKET_FIELDS = _ISSUE_FIELDS | {"active", "replaced_by"}
_STATE_FIELDS = frozenset(
    {
        "ticket_id",
        "ticket_name",
        "current_definition",
        "active",
        "replaced_by",
        "dependencies",
        "status",
        "active_team_ordinal",
        "worktree",
        "branch",
        "current_candidate",
    }
)
_STATUSES = frozenset(
    {
        "pending",
        "ready",
        "implementing",
        "reviewing",
        "reworking",
        "awaiting-integration",
        "integrating",
        "resolving-integration",
        "integrated",
        "blocked",
        "escalated",
    }
)
_STATE_CHANGE_FIELDS = frozenset(
    {
        "ticket_id",
        "status",
        "active_team_ordinal",
        "worktree",
        "branch",
        "current_candidate",
        "caused_by_event_ids",
        "evidence_refs",
    }
)
_TRANSITIONS = {
    "pending": {"ready", "blocked", "escalated"},
    "ready": {"implementing", "blocked", "escalated"},
    "implementing": {"reviewing", "blocked", "escalated"},
    "reviewing": {"reworking", "awaiting-integration", "blocked", "escalated"},
    "reworking": {"implementing", "reviewing", "blocked", "escalated"},
    "awaiting-integration": {"integrating", "blocked", "escalated"},
    "integrating": {"integrated", "resolving-integration", "blocked", "escalated"},
    "resolving-integration": {"integrating", "blocked", "escalated"},
    "integrated": set(),
    "blocked": {"pending", "ready", "escalated"},
    "escalated": {"pending", "ready", "blocked"},
}


@click.group()
def ticket() -> None:
    """Register Tickets and inspect their current Task Graph."""


@ticket.command("register")
@click.option(
    "--ticket-file",
    required=True,
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
def register_command(ticket_file: Path) -> None:
    """Register one accepted GitHub Issue from a YAML file."""

    try:
        issue = yaml.safe_load(ticket_file.read_text(encoding="utf-8"))
        _validate_issue(issue)
        configuration = load_project_configuration(Path.cwd())
        directory = _register(configuration.state, configuration.harness_root, issue)
    except (
        OSError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    click.echo(str(directory))


@ticket.command("revise")
@click.option(
    "--revision-file",
    required=True,
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
def revise_command(revision_file: Path) -> None:
    """Apply one validated product-preserving Task Graph revision."""

    try:
        revision = yaml.safe_load(revision_file.read_text(encoding="utf-8"))
        _validate_revision(revision)
        configuration = load_project_configuration(Path.cwd())
        recorded = _revise(
            configuration.state, configuration.harness_root, revision
        )
    except (
        OSError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(recorded, sort_keys=False), nl=False)


@ticket.command("graph")
def graph_command() -> None:
    """Generate the current Ticket DAG and readiness view as YAML."""

    try:
        configuration = load_project_configuration(Path.cwd())
        view = _graph(configuration.state)
    except (
        OSError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(view, sort_keys=False), nl=False)


@ticket.command("update")
@click.option(
    "--state-file",
    required=True,
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
def update_command(state_file: Path) -> None:
    """Apply one evidence-backed current Ticket state transition."""

    try:
        change = yaml.safe_load(state_file.read_text(encoding="utf-8"))
        _validate_state_change(change)
        configuration = load_project_configuration(Path.cwd())
        recorded = _update_state(
            configuration.state, configuration.harness_root, change
        )
    except (
        OSError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(recorded, sort_keys=False), nl=False)


def _validate_issue(issue: Any) -> None:
    if not isinstance(issue, dict) or set(issue) != _ISSUE_FIELDS:
        raise ValueError("accepted Ticket definition is invalid")
    ticket_id = issue["ticket_id"]
    ticket_name = issue["ticket_name"]
    source = issue["source"]
    title = issue["title"]
    body = issue["body"]
    dependencies = issue["dependencies"]
    source_match = _ISSUE_SOURCE.fullmatch(source) if isinstance(source, str) else None
    if (
        not isinstance(ticket_id, str)
        or _TICKET_ID.fullmatch(ticket_id) is None
        or not isinstance(ticket_name, str)
        or _TICKET_NAME.fullmatch(ticket_name) is None
        or source_match is None
        or source_match.group(1) != ticket_id
        or not isinstance(title, str)
        or not title.strip()
        or not isinstance(body, str)
        or not isinstance(dependencies, list)
        or any(
            not isinstance(item, str) or _TICKET_ID.fullmatch(item) is None
            for item in dependencies
        )
        or len(dependencies) != len(set(dependencies))
        or ticket_id in dependencies
    ):
        raise ValueError("accepted Ticket definition is invalid")


def _validate_revision(revision: Any) -> None:
    if (
        not isinstance(revision, dict)
        or set(revision) != _REVISION_FIELDS
        or revision["product_preserving"] is not True
        or not isinstance(revision["tickets"], list)
        or not revision["tickets"]
    ):
        raise ValueError(
            "Ticket revision is invalid or changes accepted product behavior"
        )
    _validate_string_list(revision, "caused_by_event_ids", allow_empty=True)
    _validate_string_list(revision, "evidence_refs", allow_empty=False)
    identifiers: list[str] = []
    for definition in revision["tickets"]:
        if (
            not isinstance(definition, dict)
            or set(definition) != _REVISED_TICKET_FIELDS
        ):
            raise ValueError("Ticket revision contains an invalid definition")
        _validate_issue({field: definition[field] for field in _ISSUE_FIELDS})
        if (
            not isinstance(definition["active"], bool)
            or not isinstance(definition["replaced_by"], list)
            or any(
                not isinstance(item, str) or _TICKET_ID.fullmatch(item) is None
                for item in definition["replaced_by"]
            )
            or len(definition["replaced_by"]) != len(set(definition["replaced_by"]))
            or definition["ticket_id"] in definition["replaced_by"]
            or (definition["active"] and definition["replaced_by"])
        ):
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


def _register(state: Path, harness_root: Path, issue: dict[str, Any]) -> Path:
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
    snapshot = _render_definition(
        {**issue, "active": True, "replaced_by": []}
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
                "kind": "ticket-registered",
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


def _revise(
    state: Path, harness_root: Path, revision: dict[str, Any]
) -> dict[str, Any]:
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
                if (
                    old["ticket_name"] != definition["ticket_name"]
                    or _snapshot_source(directory / "ticket.md") != definition["source"]
                ):
                    raise ValueError("a stable Ticket identity cannot change")
                meaningful = meaningful or (
                    (directory / old["current_definition"]).read_text(
                        encoding="utf-8"
                    )
                    != _render_definition(definition)
                )
                record = dict(old)
                record.update(
                    active=definition["active"],
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
                    "active": definition["active"],
                    "replaced_by": definition["replaced_by"],
                    "dependencies": definition["dependencies"],
                    "status": "pending",
                    "active_team_ordinal": None,
                    "worktree": None,
                    "branch": None,
                    "current_candidate": None,
                }
            proposed[ticket_id] = record
        if not meaningful:
            raise ValueError("Ticket revision does not introduce a new durable fact")
        _validate_graph(proposed)

        event = {
            "kind": "ticket-graph-revised",
            "caused_by_event_ids": revision["caused_by_event_ids"],
            "evidence_refs": revision["evidence_refs"],
            "affected_ticket_ids": list(revised),
            "product_preserving": True,
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


def _graph(state: Path) -> dict[str, Any]:
    tickets = state / "tickets"
    if not tickets.is_dir():
        return {"tickets": []}
    lock = _lock(tickets, exclusive=False)
    try:
        states = _load_states(tickets)
        records = {ticket_id: record for ticket_id, (_, record) in states.items()}
        _validate_graph(records)
        rendered = []
        for ticket_id in sorted(records, key=int):
            record = records[ticket_id]
            ready = (
                record["active"]
                and record["status"] in {"pending", "ready"}
                and all(
                    records[item]["status"] == "integrated"
                    for item in record["dependencies"]
                )
            )
            rendered.append(
                {
                    "ticket_id": ticket_id,
                    "ticket_name": record["ticket_name"],
                    "status": record["status"],
                    "active": record["active"],
                    "ready": ready,
                    "dependencies": record["dependencies"],
                    "replaced_by": record["replaced_by"],
                }
            )
        return {"tickets": rendered}
    finally:
        _unlock(lock)


def _update_state(
    state: Path, harness_root: Path, change: dict[str, Any]
) -> dict[str, Any]:
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
        if change["status"] not in _TRANSITIONS[old_status]:
            raise ValueError(
                "Ticket transition from {0} to {1} is invalid".format(
                    old_status, change["status"]
                )
            )
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
            "kind": "ticket-state-changed",
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


def _render_definition(definition: dict[str, Any]) -> str:
    replacements = ", ".join(definition["replaced_by"]) or "none"
    dependencies = ", ".join(definition["dependencies"]) or "none"
    return (
        "# Ticket {0}: {1}\n\n"
        "Ticket name: {2}\n\n"
        "Source: {3}\n\n"
        "Active: {4}\n\n"
        "Replaced by: {5}\n\n"
        "Dependencies: {6}\n\n"
        "{7}\n"
    ).format(
        definition["ticket_id"],
        definition["title"],
        definition["ticket_name"],
        definition["source"],
        str(definition["active"]).lower(),
        replacements,
        dependencies,
        definition["body"],
    )


def _load_states(tickets: Path) -> dict[str, tuple[Path, dict[str, Any]]]:
    states: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in tickets.glob("*/ticket.yml"):
        record = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or set(record) != _STATE_FIELDS:
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
        states[ticket_id] = (path.parent, record)
    directories = {path for path in tickets.iterdir() if path.is_dir()}
    if directories != {directory for directory, _ in states.values()}:
        raise ValueError("Ticket state is invalid")
    return states


def _validate_graph(records: dict[str, dict[str, Any]]) -> None:
    for ticket_id, record in records.items():
        dependencies = record["dependencies"]
        replacements = record["replaced_by"]
        if record["active"] and any(
            item in records and not records[item]["active"] for item in dependencies
        ):
            raise ValueError("an active dependency cannot point to an inactive Ticket")
        if (
            any(item not in records or item == ticket_id for item in dependencies)
            or len(dependencies) != len(set(dependencies))
            or any(item not in records or item == ticket_id for item in replacements)
            or len(replacements) != len(set(replacements))
            or (record["active"] and replacements)
            or any(not records[item]["active"] for item in replacements)
        ):
            raise ValueError(
                "Ticket graph contains an invalid dependency or replacement"
            )
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(ticket_id: str) -> None:
        if ticket_id in visiting:
            raise ValueError("Ticket dependencies must form a DAG")
        if ticket_id in visited or not records[ticket_id]["active"]:
            return
        visiting.add(ticket_id)
        for dependency in records[ticket_id]["dependencies"]:
            visit(dependency)
        visiting.remove(ticket_id)
        visited.add(ticket_id)

    for ticket_id in records:
        visit(ticket_id)


def _write_yaml(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(".{0}.tmp".format(path.name))
    temporary.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
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
    for line in path.read_text(encoding="utf-8").splitlines():
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
    fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
    return descriptor


def _unlock(descriptor: int) -> None:
    fcntl.flock(descriptor, fcntl.LOCK_UN)
    os.close(descriptor)
