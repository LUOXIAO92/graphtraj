"""Strict Delivery State requests for Ticket and Team semantic state."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Mapping

import yaml

from graphtraj.graph.delivery_worldline import append_project_worldline_event, read_worldline
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.graph.ticket_graph import _TRANSITIONS, _load_states


_MEMBER_KEYS = {
    "team_leader",
    "engineer",
    "standards_reviewer",
    "spec_reviewer",
}
_ENGINEERS = {"engineer-junior", "engineer-senior", "engineer-expert"}
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
        "candidate": _COMMON | {"candidate"},
        "correction": _COMMON | {"responsible_role", "session_ref"},
        "final": _COMMON | {"candidate", "decision"},
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
        previous = _read_team(ticket_directory / "teams" / str(ordinal) / "team.yml")
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
        team_update = _read_team(team_file)
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
            if request["session_ref"] != team_update["members"]["team_leader"]["session_ref"]:
                raise ValueError("Retirement must retain the current Leader Session")
            expected_trace = (team_directory / "traces" / request["session_ref"] / "events.jsonl").relative_to(harness_root).as_posix()
            if request["trace_ref"] != expected_trace or expected_trace not in request["evidence_refs"]:
                raise ValueError("Retirement must retain the Leader Trace")
            team_update.update(status="retired", final_session_ref=request["session_ref"], final_trace_ref=expected_trace)
            kind = "team-retired"
        elif phase == "replace-member":
            member = request["member"]
            if member not in _MEMBER_KEYS - {"team_leader"}:
                raise ValueError("Replacing the Leader requires Team retirement")
            configured = team_update["members"][member]
            if configured["role"] != request["role"] or not request["session_ref"] or configured["session_ref"] == request["session_ref"]:
                raise ValueError("Replacement must identify a fresh Session for the seat")
            configured["session_ref"] = request["session_ref"]
            kind = "team-member-replaced"
        elif phase == "member":
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
        elif phase == "correction":
            if ticket["status"] != "reviewing":
                raise ValueError("Process correction requires an open Team Round")
            responsible = next(
                (member for seat, member in team_update["members"].items()
                 if seat != "team_leader" and member["role"] == request["responsible_role"]),
                None,
            )
            if responsible is None or not request["session_ref"] or responsible["session_ref"] != request["session_ref"]:
                raise ValueError("Process correction must resume the responsible Team Session")
            if request["responsible_role"] in _ENGINEERS:
                ticket_update["current_candidate"] = None
            kind = "team-process-correction"
        elif phase == "candidate":
            candidate = _validate_candidate(request["candidate"])
            if ticket["status"] not in {"implementing", "reviewing"} or ticket["current_candidate"] is not None:
                raise ValueError("Ticket cannot enter fixed-candidate Review")
            if team_update["members"]["engineer"]["session_ref"] is None:
                raise ValueError("Candidate Review requires the Engineer Session")
            ticket_update.update(
                status="reviewing",
                current_candidate=candidate,
            )
            kind = "candidate-ready-for-review"
        elif phase == "rework":
            previous = next(
                (event for event in reversed(read_worldline(state_directory, harness_root))
                 if event.get("ticket_id") == ticket_id),
                {},
            )
            if (
                ticket["status"] != "reworking"
                or previous.get("kind") != "team-round-implementation-rejected"
                or previous.get("ticket_id") != ticket_id
                or previous.get("team_round") != round_ordinal
                or request["caused_by_event_ids"] != [previous["event_id"]]
            ):
                raise ValueError("Rework requires the confirmed implementation rejection")
            ticket_update.update(status=_transition(ticket, "implementing"), current_candidate=None)
            team_update["current_round"] += 1
            open_round = True
            kind = "team-round-rework-started"
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
            elif request["decision"] == "implementation-rejected":
                _validate_implementation_rejection(
                    team_directory / "rounds" / str(round_ordinal), candidate
                )
                ticket_update["status"] = _transition(ticket, "reworking")
                close_round = True
                kind = "team-round-implementation-rejected"
            else:
                raise ValueError("Leader decision must be accepted or rejected")

    event = {
        "kind": kind,
        "caused_by_event_ids": list(request["caused_by_event_ids"]),
        "evidence_refs": list(request["evidence_refs"]),
        "ticket_id": ticket_id,
        "team_ordinal": ordinal,
        "team_round": round_ordinal + 1 if open_round else round_ordinal,
    }
    if phase == "candidate" or phase == "final":
        event["candidate"] = request["candidate"]
    if phase == "final":
        event["decision"] = request["decision"]
    if phase == "correction":
        event.update(
            responsible_role=request["responsible_role"],
            session_ref=request["session_ref"],
            action="resume-session-for-correction",
        )

    def mutation(recorded: dict[str, Any]):
        nonlocal team_update
        previous_modes: dict[Path, int] = {}
        try:
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
                (team_directory / "rounds" / str(round_ordinal + 1)).mkdir()
            if close_round:
                round_directory = team_directory / "rounds" / str(round_ordinal)
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


def confirmed_rework(path: Path) -> bool:
    lines = path.read_text(encoding="utf-8").splitlines()
    return (
        [line for line in lines if line.startswith("Decision:")] == ["Decision: REJECT"]
        and [line for line in lines if line.startswith("Diagnosis:")] == ["Diagnosis: implementation"]
        and [line for line in lines if line.startswith("Reviews:")] == ["Reviews: compliant"]
        and [line for line in lines if line.startswith("Action:")] == ["Action: rework"]
        and any(line.startswith("Rationale:") and line.removeprefix("Rationale:").strip() for line in lines)
    )


def _validate_implementation_rejection(directory: Path, candidate: str) -> None:
    """Check attributable report fields; the Leader owns their semantic diagnosis."""
    if not confirmed_rework(directory / "leader.md"):
        raise ValueError("Rework requires the Team Leader's confirmed diagnosis")
    comparisons = []
    findings = []
    for axis in ("Standards", "Spec"):
        path = directory / (axis.lower() + ".md")
        report = path.read_text(encoding="utf-8")
        lines = report.splitlines()

        def report_error(message: str) -> ValueError:
            return ValueError("Review report {0} (Axis: {1}) {2}".format(path, axis, message))

        for prefix, expected in (("Candidate commit:", candidate), ("Axis:", axis)):
            if [line.removeprefix(prefix).strip() for line in lines if line.startswith(prefix)] != [expected]:
                raise report_error("is missing an attributable {0} field".format(prefix))
        comparison = [line.removeprefix("Comparison:").strip() for line in lines if line.startswith("Comparison:")]
        if len(comparison) != 1:
            raise report_error("has a missing or ambiguous Comparison field")
        try:
            comparisons.append(_validate_candidate(comparison[0]))
        except ValueError as error:
            raise report_error("has an invalid Comparison field") from error
        finding_fields = [
            (index, line.removeprefix("Finding:").strip())
            for index, line in enumerate(lines)
            if line.startswith("Finding:")
        ]
        if not finding_fields:
            raise report_error("must report findings or explicitly report none")
        if any(value == "none" for _, value in finding_fields):
            if len(finding_fields) != 1:
                raise report_error("mixes Finding: none with another Finding")
            continue
        for position, (index, value) in enumerate(finding_fields):
            if not value:
                raise report_error("has an empty Finding field")
            following = (
                finding_fields[position + 1][0]
                if position + 1 < len(finding_fields) else len(lines)
            )
            block = lines[index + 1:following]
            for prefix in ("Rule:", "Input:", "Trace:", "Failure:", "Evidence:"):
                values = [line.removeprefix(prefix).strip() for line in block if line.startswith(prefix)]
                if len(values) != 1 or not values[0]:
                    raise report_error("Finding lacks accepted evidence requirements")
            findings.append(value)
    if comparisons[0] != comparisons[1]:
        raise ValueError("Rework requires matching Comparison fields in Standards and Spec reports")
    if not findings:
        raise ValueError("Rework requires an implementation finding in the Standards or Spec report")


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
