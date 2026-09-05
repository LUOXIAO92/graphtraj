"""Strict Delivery State requests for Ticket and Team semantic state."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Mapping

import click
import yaml

from .delivery_worldline import append_project_worldline_event
from .project_configuration import load_project_configuration
from .runner_io import write_yaml_durably
from .ticket_graph import _TRANSITIONS, _load_states


_MEMBER_KEYS = {
    "team_leader",
    "engineer",
    "standards_reviewer",
    "spec_reviewer",
}
_ENGINEERS = {"engineer-junior", "engineer-senior", "engineer-expert"}
_COMMON = {"phase", "ticket_id", "caused_by_event_ids", "evidence_refs"}


@click.group("delivery-state")
def delivery_state() -> None:
    """Apply strict requests produced by the Delivery State Agent."""


@delivery_state.command("apply")
@click.option(
    "--request-file",
    required=True,
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
def apply_command(request_file: Path) -> None:
    """Validate and atomically apply one semantic state request."""

    try:
        request = yaml.safe_load(request_file.read_text(encoding="utf-8"))
        configuration = load_project_configuration(Path.cwd())
        recorded = apply_delivery_state_request(
            configuration.state, configuration.harness_root, request
        )
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(recorded, sort_keys=False), nl=False)


def apply_delivery_state_request(
    state_directory: Path,
    harness_root: Path,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one Agent request and commit state with its causal event."""

    if not isinstance(request, dict):
        raise ValueError("Delivery State request must be a mapping")
    phase = request.get("phase")
    allowed = {
        "start": _COMMON | {"worktree", "branch", "members"},
        "member": _COMMON | {"member", "role", "session_ref"},
        "candidate": _COMMON | {"candidate"},
        "final": _COMMON | {"candidate", "decision"},
    }
    if (
        not isinstance(phase, str)
        or phase not in allowed
        or set(request) != allowed[phase]
    ):
        raise ValueError("Delivery State request has an invalid schema")
    _validate_string_list(request, "caused_by_event_ids", empty=False)
    _validate_string_list(request, "evidence_refs", empty=False)

    tickets = state_directory / "tickets"
    current = _load_states(tickets)
    ticket_id = request["ticket_id"]
    if not isinstance(ticket_id, str) or ticket_id not in current:
        raise ValueError("Delivery State request names an unknown Ticket")
    ticket_directory, ticket = current[ticket_id]
    team_directory = ticket_directory / "teams" / "1"
    team_file = team_directory / "team.yml"
    original_ticket = (ticket_directory / "ticket.yml").read_bytes()
    original_team = team_file.read_bytes() if team_file.is_file() else None
    team_directory_existed = team_directory.exists()
    ticket_update = dict(ticket)
    team_update: dict[str, Any] | None = None
    close_round = False

    if phase == "start":
        if (
            ticket["status"] != "ready"
            or ticket["active_team_ordinal"] is not None
            or ticket["current_candidate"] is not None
            or team_file.exists()
        ):
            raise ValueError("Ticket cannot start Team generation 1")
        members = _validate_members(request["members"])
        if (
            members["team_leader"]["session_ref"] is None
            or any(
                members[name]["session_ref"] is not None
                for name in ("engineer", "standards_reviewer", "spec_reviewer")
            )
        ):
            raise ValueError("Team start must identify only the Team Leader Session")
        worktree = _validate_worktree(harness_root, request["worktree"])
        if request["branch"] != "agent/{0}-{1}".format(
            ticket_id, ticket["ticket_name"]
        ):
            raise ValueError("Delivery State request has an invalid branch")
        ticket_update.update(
            status=_transition(ticket, "implementing"),
            active_team_ordinal=1,
            worktree=worktree,
            branch=request["branch"],
        )
        kind = "team-started"
    else:
        if not team_file.is_file():
            raise ValueError("Team generation 1 does not exist")
        team_update = _read_team(team_file)
        if phase == "member":
            member = request["member"]
            if not isinstance(member, str) or member not in _MEMBER_KEYS:
                raise ValueError("Delivery State request names an invalid Team member")
            configured = team_update["members"][member]
            if (
                configured["role"] != request["role"]
                or configured["session_ref"] is not None
                or not isinstance(request["session_ref"], str)
                or not request["session_ref"]
            ):
                raise ValueError("Delivery State member request conflicts with the Team")
            if (
                (member == "engineer" and ticket["status"] != "implementing")
                or (
                    member in {"standards_reviewer", "spec_reviewer"}
                    and ticket["status"] != "reviewing"
                )
                or member == "team_leader"
            ):
                raise ValueError("Team member request is outside its delivery phase")
            configured["session_ref"] = request["session_ref"]
            kind = "team-member-started"
        elif phase == "candidate":
            candidate = _validate_candidate(request["candidate"])
            if ticket["status"] != "implementing" or ticket["current_candidate"] is not None:
                raise ValueError("Ticket cannot enter fixed-candidate Review")
            if team_update["members"]["engineer"]["session_ref"] is None:
                raise ValueError("Candidate Review requires the Engineer Session")
            ticket_update.update(
                status=_transition(ticket, "reviewing"),
                current_candidate=candidate,
            )
            kind = "candidate-ready-for-review"
        else:
            candidate = _validate_candidate(request["candidate"])
            if ticket["status"] != "reviewing" or ticket["current_candidate"] != candidate:
                raise ValueError("Leader decision does not match the fixed candidate")
            if any(
                member["session_ref"] is None
                for member in team_update["members"].values()
            ):
                raise ValueError("Leader decision requires every Team member Session")
            if request["decision"] == "accepted":
                ticket_update["status"] = _transition(ticket, "awaiting-integration")
                close_round = True
                kind = "team-round-accepted"
            elif request["decision"] == "rejected":
                kind = "team-round-rejected"
            else:
                raise ValueError("Leader decision must be accepted or rejected")

    event = {
        "kind": kind,
        "caused_by_event_ids": list(request["caused_by_event_ids"]),
        "evidence_refs": list(request["evidence_refs"]),
        "ticket_id": ticket_id,
        "team_ordinal": 1,
        "team_round": 1,
    }
    if phase == "candidate" or phase == "final":
        event["candidate"] = request["candidate"]
    if phase == "final":
        event["decision"] = request["decision"]

    def mutation(recorded: dict[str, Any]):
        nonlocal team_update
        previous_modes: dict[Path, int] = {}
        try:
            if phase == "start":
                team_directory.mkdir(parents=True, exist_ok=True)
                team_update = {
                    "team_ordinal": 1,
                    "status": "active",
                    "members": members,
                    "current_round": 1,
                    "started_at": recorded["captured_at"],
                }
                _validate_team(team_update)
                write_yaml_durably(team_file, team_update)
            elif team_update is not None:
                _validate_team(team_update)
                write_yaml_durably(team_file, team_update)
            write_yaml_durably(ticket_directory / "ticket.yml", ticket_update)
            _load_states(tickets)
            if close_round:
                round_directory = team_directory / "rounds" / "1"
                for path in (*round_directory.iterdir(), round_directory):
                    previous_modes[path] = path.stat().st_mode & 0o777
                    path.chmod(0o444 if path != round_directory else 0o555)
        except Exception:
            _restore(ticket_directory / "ticket.yml", original_ticket)
            _restore_team(
                team_directory, team_file, original_team, team_directory_existed
            )
            _restore_modes(previous_modes)
            raise

        def rollback() -> None:
            _restore(ticket_directory / "ticket.yml", original_ticket)
            _restore_team(
                team_directory, team_file, original_team, team_directory_existed
            )
            _restore_modes(previous_modes)

        return rollback

    return append_project_worldline_event(
        state_directory, harness_root, event, mutation
    )


def _validate_members(value: Any) -> dict[str, dict[str, str | None]]:
    if not isinstance(value, dict) or set(value) != _MEMBER_KEYS:
        raise ValueError("Delivery State request has invalid Team members")
    expected = {
        "team_leader": {"team-leader"},
        "engineer": _ENGINEERS,
        "standards_reviewer": {"standards-reviewer"},
        "spec_reviewer": {"spec-reviewer"},
    }
    members: dict[str, dict[str, str | None]] = {}
    for name, member in value.items():
        if (
            not isinstance(member, dict)
            or set(member) != {"role", "session_ref"}
            or member.get("role") not in expected[name]
            or (
                member.get("session_ref") is not None
                and (not isinstance(member["session_ref"], str) or not member["session_ref"])
            )
        ):
            raise ValueError("Delivery State request has invalid Team members")
        members[name] = dict(member)
    return members


def _read_team(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    _validate_team(document)
    return document


def _validate_team(team: Any) -> None:
    if (
        not isinstance(team, dict)
        or set(team) != {"team_ordinal", "status", "members", "current_round", "started_at"}
        or team["team_ordinal"] != 1
        or team["status"] != "active"
        or team["current_round"] != 1
        or not isinstance(team["started_at"], str)
    ):
        raise ValueError("Team state is invalid")
    _validate_members(team["members"])


def _validate_worktree(harness_root: Path, value: Any) -> str:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("Ticket Worktree must be Harness-root relative")
    relative = Path(value)
    normalized = Path(os.path.normpath(value))
    if normalized.as_posix() != relative.as_posix():
        raise ValueError("Ticket Worktree must use a normalized relative path")
    resolved = (harness_root / relative).resolve()
    try:
        resolved.relative_to(harness_root.resolve())
    except ValueError as error:
        raise ValueError("Ticket Worktree escapes the Harness Project") from error
    return relative.as_posix()


def _validate_candidate(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("Delivery State request has an invalid candidate")
    return value


def _transition(ticket: Mapping[str, Any], status: str) -> str:
    if status not in _TRANSITIONS[ticket["status"]]:
        raise ValueError("Delivery State request has an invalid Ticket transition")
    return status


def _validate_string_list(request: Mapping[str, Any], field: str, *, empty: bool) -> None:
    value = request.get(field)
    if (
        not isinstance(value, list)
        or (not empty and not value)
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise ValueError("Delivery State request has invalid {0}".format(field))


def _restore(path: Path, content: bytes) -> None:
    temporary = path.with_name(".{0}.rollback".format(path.name))
    temporary.write_bytes(content)
    os.replace(temporary, path)


def _restore_team(
    directory: Path,
    path: Path,
    content: bytes | None,
    directory_existed: bool,
) -> None:
    if content is None:
        if not directory_existed and directory.exists():
            shutil.rmtree(directory)
        elif path.exists():
            path.unlink()
        if (
            not directory_existed
            and directory.parent.is_dir()
            and not any(directory.parent.iterdir())
        ):
            directory.parent.rmdir()
    else:
        _restore(path, content)


def _restore_modes(modes: Mapping[Path, int]) -> None:
    for path, mode in modes.items():
        if path.exists():
            path.chmod(mode)
