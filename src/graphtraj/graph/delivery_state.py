"""Strict Delivery State requests for Ticket and Team semantic state."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

import yaml

from graphtraj.configuration.project_roles import ROLE_REFERENCE
from graphtraj.graph.delivery_worldline import (
    _read_shards,
    _validate_evidence,
    append_project_worldline_event,
    read_worldline,
)
from graphtraj.execution.runner_io import write_yaml_durably, _sync_directory
from graphtraj.execution.runner_status import caller_alias, read_alias_mapping, require_task_authority
from graphtraj.workspace.runner_project import discover_runner_directory, run_git
from graphtraj.graph.ticket_graph import _TRANSITIONS, _load_states


_COMMON = {"phase", "ticket_id", "caused_by_event_ids", "evidence_refs"}


def apply_delivery_state_request(
    state_directory: Path,
    harness_root: Path,
    request: Mapping[str, Any],
    authoritative_facts: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one Agent request and commit state with its causal event."""

    if (
        not isinstance(request, dict)
        or not isinstance(authoritative_facts, dict)
        or request != authoritative_facts
    ):
        raise ValueError("Delivery State request differs from authoritative facts")
    phase = request.get("phase")
    allowed = {
        "start": _COMMON | {"worktree", "branch", "members"},
        "member": _COMMON | {"member", "role", "session_ref"},
        "final": _COMMON | {"candidate", "decision", "submission_id", "reason"},
        "rework": _COMMON,
        "retiring": _COMMON | {"actor"},
        "retired": _COMMON | {"session_ref", "trace_ref"},
        "replace-member": _COMMON | {"member", "role", "session_ref"},
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
    ordinal = ticket["active_team_ordinal"] or 1
    replacing = False
    if phase == "start" and ticket["active_team_ordinal"] is not None:
        previous = read_team(ticket_directory / "teams" / str(ordinal) / "team.yml")
        if previous["status"] != "retired":
            raise ValueError("The previous Team must be retired before replacement")
        ordinal += 1
        replacing = True
    team_directory = ticket_directory / "teams" / str(ordinal)
    team_file = team_directory / "team.yml"
    original_ticket = (ticket_directory / "ticket.yml").read_bytes()
    original_team = team_file.read_bytes() if team_file.is_file() else None
    team_directory_existed = team_directory.exists()
    ticket_update = dict(ticket)
    team_update: dict[str, Any] | None = None
    close_round = False
    open_round = False
    round_ordinal = 1

    if phase == "start":
        if (
            not replacing and (ticket["status"] != "ready"
            or ticket["active_team_ordinal"] is not None
            or ticket["current_candidate"] is not None)
            or team_file.exists()
        ):
            raise ValueError("Ticket cannot start Team generation 1")
        # Retained callers may still supply empty seats. Persist actual members only.
        members = {
            name: member for name, member in _validate_members(request["members"]).items()
            if member["session_ref"] is not None
        }
        if not members:
            raise ValueError("Team start must identify at least one actual Session")
        worktree = _validate_worktree(harness_root, request["worktree"])
        if request["branch"] != "agent/{0}-{1}".format(
            ticket_id, ticket["ticket_name"]
        ):
            raise ValueError("Delivery State request has an invalid branch")
        ticket_update.update(
            status="implementing" if replacing else _transition(ticket, "implementing"),
            active_team_ordinal=ordinal,
            current_candidate=None,
            worktree=worktree,
            branch=request["branch"],
        )
        if replacing and (worktree != ticket["worktree"] or request["branch"] != ticket["branch"]):
            raise ValueError("A replacement Team must reuse the Ticket Worktree and branch")
        kind = "team-replaced" if replacing else "team-started"
    else:
        if not team_file.is_file():
            raise ValueError("Team generation 1 does not exist")
        team_update = read_team(team_file)
        round_ordinal = team_update["current_round"]
        if team_update["status"] != "active" and phase != "retired":
            raise ValueError("The Team has stopped starting new work")
        if phase == "retiring":
            if request["actor"] not in {"main", "user"} or os.environ.get("GRAPHTRAJ_ROLE"):
                raise ValueError("Only Main or the user may retire a Team")
            team_update.update(status="retiring", retired_by=request["actor"])
            kind = "team-retiring"
        elif phase == "retired":
            if team_update["status"] != "retiring":
                raise ValueError("The Team is not retiring")
            if request["session_ref"] not in {
                member["session_ref"] for member in team_update["members"].values()
            }:
                raise ValueError("Retirement must retain a current member Session")
            expected_trace = (team_directory / "traces" / request["session_ref"] / "events.jsonl").relative_to(harness_root).as_posix()
            if request["trace_ref"] != expected_trace or expected_trace not in request["evidence_refs"]:
                raise ValueError("Retirement must retain the member Trace")
            team_update.update(status="retired", final_session_ref=request["session_ref"], final_trace_ref=expected_trace)
            kind = "team-retired"
        elif phase == "replace-member":
            member = request["member"]
            if not isinstance(member, str) or member not in team_update["members"]:
                raise ValueError("Replacement names an unknown Team member")
            configured = team_update["members"][member]
            if configured["role"] != request["role"] or not request["session_ref"] or configured["session_ref"] == request["session_ref"]:
                raise ValueError("Replacement must identify a fresh Session for the seat")
            configured["session_ref"] = request["session_ref"]
            kind = "team-member-replaced"
        elif phase == "member":
            member = request["member"]
            if not isinstance(member, str):
                raise ValueError("Delivery State request names an invalid Team member")
            registered = _validate_members({
                member: {"role": request["role"], "session_ref": request["session_ref"]},
            })
            configured = team_update["members"].get(member)
            if request["session_ref"] is None or (
                configured is not None
                and (configured["role"] != request["role"] or configured["session_ref"] is not None)
            ):
                raise ValueError("Delivery State member request conflicts with the Team")
            # A conflict starts actual work after the accepted Round closed.
            # Open its next Round once, preserving all original reports.
            round_directory = team_directory / "rounds" / str(round_ordinal)
            if ticket["status"] == "resolving-integration" and not round_directory.stat().st_mode & 0o200:
                team_update["current_round"] += 1
                open_round = True
            team_update["members"].update(registered)
            kind = "team-member-started"
        elif phase == "rework":
            previous = next(
                (event for event in reversed(read_worldline(state_directory, harness_root))
                 if event.get("ticket_id") == ticket_id),
                {},
            )
            if (
                ticket["status"] not in {"reworking", "resolving-integration"}
                or previous.get("kind") != "team-round-implementation-rejected"
                or previous.get("ticket_id") != ticket_id
                or previous.get("team_round") != round_ordinal
                or request["caused_by_event_ids"] != [previous["event_id"]]
            ):
                raise ValueError("Rework requires the confirmed result rejection")
            runner = discover_runner_directory(harness_root)
            author = caller_alias(runner)
            if author is None:
                raise ValueError("Result correction requires its own Session")
            require_task_authority(state_directory, runner, ticket_id, author, "submit")
            if ticket["status"] != "resolving-integration":
                ticket_update.update(status=_transition(ticket, "implementing"), current_candidate=None)
            team_update["current_round"] += 1
            open_round = True
            kind = "team-round-rework-started"
        else:
            submission, author = _validate_result_decision(
                state_directory, harness_root, request, ticket, team_update,
                read_worldline(state_directory, harness_root),
            )
            snapshots = _decision_evidence(harness_root, submission, author, request["evidence_refs"])
            integration = ticket["status"] == "resolving-integration"
            if not integration:
                ticket_update["current_candidate"] = submission["candidate"]
            # Submission and acceptance can happen without a separate Review step.
            if ticket["status"] == "implementing":
                ticket_update["status"] = _transition(ticket, "reviewing")
            close_round = True
            if request["decision"] == "accepted":
                if not integration:
                    ticket_update["status"] = _transition(ticket_update, "awaiting-integration")
                kind = "team-round-accepted"
            else:
                if not integration:
                    ticket_update["status"] = _transition(ticket_update, "reworking")
                # Retain the existing event kind for all rejected task results.
                kind = "team-round-implementation-rejected"

    event = {
        "kind": kind,
        "caused_by_event_ids": list(request["caused_by_event_ids"]),
        "evidence_refs": list(request["evidence_refs"]),
        "ticket_id": ticket_id,
        "team_ordinal": ordinal,
        "team_round": round_ordinal + 1 if open_round else round_ordinal,
    }
    if phase == "final":
        event["candidate"] = request["candidate"]
        event.update(
            decision=request["decision"], submission_id=request["submission_id"],
            reason=request["reason"], alias=author,
            session=read_alias_mapping(discover_runner_directory(harness_root), author)[0]["session"]
            if author is not None else None,
        )

    def mutation(recorded: dict[str, Any]):
        nonlocal team_update
        previous_modes: dict[Path, int] = {}
        retained: Path | None = None
        if phase in {"final", "rework"}:
            if ((ticket_directory / "ticket.yml").read_bytes() != original_ticket
                    or team_file.read_bytes() != original_team):
                raise ValueError("The task changed before acceptance; inspect it again")
        if phase == "final":
            _validate_result_decision(
                state_directory, harness_root, request, ticket, team_update,
                _read_shards(state_directory)[1],
            )
        try:
            if phase == "final":
                retained = team_directory / "traces" / submission["alias"] / recorded["event_id"]
                retained.mkdir(parents=True)
                recorded["evidence_refs"] = []
                for index, (name, content) in enumerate(snapshots):
                    path = retained / f"{index}-{name}"
                    with path.open("xb") as stream:
                        stream.write(content)
                        stream.flush()
                        os.fsync(stream.fileno())
                    recorded["evidence_refs"].append(path.relative_to(harness_root).as_posix())
                _sync_directory(retained)
                _sync_directory(retained.parent)
            if phase == "start":
                team_directory.mkdir(parents=True, exist_ok=True)
                team_update = {
                    "team_ordinal": ordinal,
                    "status": "active",
                    "members": members,
                    "current_round": 1,
                    "started_at": recorded["captured_at"],
                }
                _validate_team(team_update)
                write_yaml_durably(team_file, team_update)
            elif team_update is not None:
                if phase == "retiring":
                    team_update["retirement_event_id"] = recorded["event_id"]
                elif phase == "retired":
                    team_update["retired_at"] = recorded["captured_at"]
                _validate_team(team_update)
                write_yaml_durably(team_file, team_update)
            write_yaml_durably(ticket_directory / "ticket.yml", ticket_update)
            _load_states(tickets)
            if open_round:
                (team_directory / "rounds" / str(round_ordinal + 1)).mkdir(parents=True)
            if close_round:
                round_directory = team_directory / "rounds" / str(round_ordinal)
                for path in ((*round_directory.iterdir(), round_directory) if round_directory.exists() else ()):
                    previous_modes[path] = path.stat().st_mode & 0o777
                    path.chmod(0o444 if path != round_directory else 0o555)
        except Exception:
            if retained is not None and retained.exists():
                shutil.rmtree(retained)
            _restore(ticket_directory / "ticket.yml", original_ticket)
            _restore_team(
                team_directory, team_file, original_team, team_directory_existed
            )
            _restore_modes(previous_modes)
            raise

        def rollback() -> None:
            if retained is not None:
                shutil.rmtree(retained)
            if open_round:
                (team_directory / "rounds" / str(round_ordinal + 1)).rmdir()
            _restore(ticket_directory / "ticket.yml", original_ticket)
            _restore_team(
                team_directory, team_file, original_team, team_directory_existed
            )
            _restore_modes(previous_modes)

        return rollback

    return append_project_worldline_event(
        state_directory, harness_root, event, mutation
    )


def _decision_evidence(
    harness: Path,
    submission: Mapping[str, Any],
    author: str | None,
    references: list[str],
) -> list[tuple[str, bytes]]:
    """Read only submitted evidence, committed files, or the caller's own reports."""
    from graphtraj.execution.runner_results import task_report_paths

    _validate_evidence(harness, references)
    runner = discover_runner_directory(harness)
    mapping, _ = read_alias_mapping(runner, submission["alias"])
    worktree = Path(mapping["worktree_path"]).resolve()
    allowed = {(harness / ref).resolve() for ref in submission["evidence_refs"]}
    if author is not None:
        owner, _ = read_alias_mapping(runner, author)
        allowed.update(path.resolve() for path in task_report_paths(owner, harness))
    snapshots = []
    for reference in references:
        path = (harness / reference).resolve()
        if path in allowed or author is None:
            content = path.read_bytes()
        else:
            relative = path.relative_to(worktree).as_posix()
            # Read committed bytes, so the evidence is tied to the judged version.
            if run_git(worktree, 'cat-file', '-t', f'{submission["candidate"]}:{relative}') != 'blob':
                raise ValueError('Decision evidence must name committed files or assigned reports')
            content = subprocess.check_output(
                ['git', 'show', f'{submission["candidate"]}:{relative}'], cwd=worktree,
            )
        snapshots.append((path.name, content))
    return snapshots


def _validate_result_decision(
    state: Path,
    harness: Path,
    request: Mapping[str, Any],
    ticket: Mapping[str, Any],
    team: Mapping[str, Any],
    events: list[dict[str, Any]],
) -> tuple[dict[str, Any], str | None]:
    """Bind an authorized decision to the latest submitted version in this Round."""
    candidate = _validate_candidate(request["candidate"])
    if not isinstance(request["decision"], str) or request["decision"] not in {"accepted", "rejected"}:
        raise ValueError("Result decision must be accepted or rejected")
    if not isinstance(request["reason"], str) or not request["reason"].strip():
        raise ValueError("Result decision requires a reason")
    submissions = [event for event in events if event["kind"] == "result-submitted"
                   and event.get("ticket_id") == ticket["ticket_id"]
                   and event.get("team_ordinal") == ticket["active_team_ordinal"]
                   and event.get("round") == team["current_round"]]
    if not submissions or submissions[-1]["event_id"] != request["submission_id"]:
        raise ValueError("Decision must identify the latest submission in the current Round")
    submission = submissions[-1]
    runner = discover_runner_directory(harness)
    mapping = require_task_authority(state, runner, ticket["ticket_id"], submission["alias"], "accept")
    if (mapping["session"] != submission["session"]
            or ticket["status"] not in {"implementing", "reviewing", "resolving-integration"}
            or candidate != submission["candidate"]
            or request["submission_id"] not in request["caused_by_event_ids"]
            or any(event.get("submission_id") == request["submission_id"] for event in events)):
        raise ValueError("Decision does not match an undecided submitted version")
    worktree = Path(mapping["worktree_path"])
    if ticket["status"] == "resolving-integration":
        from graphtraj.configuration.project_configuration import load_project_configuration

        if worktree != load_project_configuration(harness).integration_worktree:
            raise ValueError("Integration decisions require an Integration Worktree result")
    if (run_git(worktree, "rev-parse", "HEAD") != candidate
            or run_git(worktree, "diff", "--name-only")
            or run_git(worktree, "diff", "--cached", "--name-only")):
        raise ValueError("The submitted version differs from the current Worktree")
    return submission, caller_alias(runner)


def _validate_members(value: Any) -> dict[str, dict[str, str | None]]:
    """Validate actual members; null Sessions remain readable in historical records."""
    if not isinstance(value, dict) or not value:
        raise ValueError("Delivery State request has invalid Team members")
    members: dict[str, dict[str, str | None]] = {}
    sessions: set[str] = set()
    for name, member in value.items():
        role = member.get("role") if isinstance(member, dict) else None
        if (
            not isinstance(name, str) or not name.strip()
            or not isinstance(member, dict)
            or set(member) != {"role", "session_ref"}
            or not isinstance(role, str) or ROLE_REFERENCE.fullmatch(role) is None
            or (member.get("session_ref") is not None and (
                not isinstance(member["session_ref"], str) or not member["session_ref"]
                or member["session_ref"] in sessions
            ))
        ):
            raise ValueError("Delivery State request has invalid Team members")
        if member["session_ref"] is not None:
            sessions.add(member["session_ref"])
        members[name] = dict(member)
    return members


def read_team(path: Path) -> dict[str, Any]:
    """Read a Team, including retained records with the former four seats."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    _validate_team(document)
    return document


def _validate_team(team: Any) -> None:
    required = {"team_ordinal", "status", "members", "current_round", "started_at"}
    if isinstance(team, dict) and team.get("status") in {"retiring", "retired"}:
        required |= {"retired_by", "retirement_event_id"}
        if team["status"] == "retired":
            required |= {"retired_at", "final_session_ref", "final_trace_ref"}
    if (
        not isinstance(team, dict)
        or set(team) != required
        or not isinstance(team.get("team_ordinal"), int)
        or isinstance(team["team_ordinal"], bool)
        or team["team_ordinal"] < 1
        or team.get("status") not in {"active", "retiring", "retired"}
        or type(team["current_round"]) is not int
        or team["current_round"] < 1
        or not isinstance(team["started_at"], str)
    ):
        raise ValueError("Team state is invalid")
    if team["status"] != "active" and (
        team["retired_by"] not in {"main", "user"}
        or any(not isinstance(team[name], str) or not team[name]
               for name in required - {"team_ordinal", "status", "members", "current_round", "started_at"})
    ):
        raise ValueError("Team retirement facts are invalid")
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
