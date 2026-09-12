"""Coding-ticket execution budget parsing and live accounting."""

from __future__ import annotations

import fcntl
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

from .runner_io import write_yaml_durably
from .runner_models import RunnerError


ADDITIONAL_ALLOWANCE_CAP_MINUTES = 20
ESTIMATED_TIME_MULTIPLIER = 0.2
ALLOWANCE_UNIFORM_LOWER_BOUND = -0.5
ALLOWANCE_UNIFORM_UPPER_BOUND = 0.5
STOPPING_LAMBDA_PER_MINUTE = 0.25
STOPPING_INTERVAL_MINUTES = 2

_MINUTE_FIELDS = frozenset({"implementation", "validation", "review", "total"})
_SESSION_FIELDS = frozenset(
    {
        "team_leader",
        "engineer",
        "standards_reviewer",
        "spec_reviewer",
        "delivery_state",
    }
)
_BUDGET_FIELDS = frozenset(
    {
        "engineer_tier",
        "tier_reason",
        "estimated_minutes",
        "planned_sessions",
        "correction_rounds",
        "estimation_note",
        "on_exceed",
    }
)
_ROLE_SESSIONS = {
    "team-leader": "team_leader",
    "delivery-state": "delivery_state",
    "standards-reviewer": "standards_reviewer",
    "spec-reviewer": "spec_reviewer",
    "engineer-junior": "engineer",
    "engineer-senior": "engineer",
    "engineer-expert": "engineer",
}


class ExecutionBudgetError(ValueError):
    """The coding-ticket execution budget is invalid."""


@dataclass(frozen=True)
class ExecutionBudget:
    """One validated execution budget."""

    definition: dict[str, Any]

    @property
    def revision_reason(self) -> str | None:
        return self.definition["execution_budget"].get("revision_reason")


def split_execution_budget_front_matter(
    body: str,
) -> tuple[str, str, str] | None:
    """Return preserved front matter, its YAML, and the remaining body."""

    lines = body.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return None
    offset = len(lines[0])
    for line in lines[1:]:
        if line.rstrip("\r\n") == "---":
            end = offset + len(line)
            return body[:end], body[len(lines[0]):offset], body[end:]
        offset += len(line)
    raise ExecutionBudgetError("execution budget front matter is not closed")


def read_execution_budget(body: str) -> ExecutionBudget | None:
    """Read the optional coding budget at the very beginning of a Ticket body."""

    front_matter = split_execution_budget_front_matter(body)
    if front_matter is None:
        return None
    _, document, _ = front_matter
    try:
        value = yaml.safe_load(document)
    except yaml.YAMLError as error:
        raise ExecutionBudgetError("execution budget front matter is not YAML") from error
    if not isinstance(value, dict) or "execution_budget" not in value:
        return None
    _validate_budget(value)
    return ExecutionBudget(value)


def execution_budget_monitor(
    ticket_directory: Path, ticket_id: str, ticket_name: str
) -> "ExecutionBudgetMonitor | None":
    """Return a monitor only for a registered coding Ticket with a budget."""

    if not (ticket_directory / "ticket.yml").is_file():
        return None
    try:
        budget = _current_budget(ticket_directory)
    except ExecutionBudgetError as error:
        raise RunnerError(
            "TICKET_FILE_INVALID", "The selected Ticket execution budget is invalid."
        ) from error
    if budget is None:
        return None
    return ExecutionBudgetMonitor(ticket_directory, ticket_id, ticket_name)


def execution_budget_monitor_from_environment(
    mapping: Mapping[str, object],
) -> "ExecutionBudgetMonitor | None":
    """Resolve one resumed Session's monitor from its retained Team context."""

    evidence = os.environ.get("GRAPHTRAJ_EVIDENCE")
    ticket_id = mapping.get("ticket_id")
    ticket_name = os.environ.get("GRAPHTRAJ_TICKET_NAME")
    if (
        not isinstance(evidence, str)
        or not evidence
        or not isinstance(ticket_id, str)
        or not ticket_id
        or not isinstance(ticket_name, str)
        or not ticket_name
    ):
        return None
    return execution_budget_monitor(Path(evidence), ticket_id, ticket_name)


def caller_notice_fd() -> tuple[int | None, bool]:
    """Return a caller stderr descriptor suitable for a detached Session."""

    try:
        descriptor = int(os.environ.get("GRAPHTRAJ_BUDGET_NOTICE_FD", ""))
        if descriptor < 3:
            raise ValueError("budget notice descriptor is not inherited")
        os.fstat(descriptor)
        return descriptor, False
    except (OSError, ValueError):
        try:
            return os.dup(sys.stderr.fileno()), True
        except OSError:
            return None, False


def execution_budget_stage(role: str) -> str:
    if role.startswith("engineer-"):
        return "implementation"
    if role in {"standards-reviewer", "spec-reviewer"}:
        return "review"
    if role == "delivery-state":
        return "delivery-state"
    return "team-lead"


class ExecutionBudgetMonitor:
    """Persist actual use and emit each budget threshold crossing once."""

    def __init__(self, ticket_directory: Path, ticket_id: str, ticket_name: str) -> None:
        self.ticket_directory = ticket_directory
        self.ticket_id = ticket_id
        self.ticket_name = ticket_name

    def record_session(self, role: str, stage: str) -> None:
        self._observe(role, stage, session=True)

    def record_correction(self, role: str) -> None:
        self._observe(role, "correction", correction=True)

    def check(self, role: str, stage: str) -> bool:
        return self._observe(role, stage)

    def is_stopped(self) -> bool:
        lock_path = self.ticket_directory / ".execution-budget.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                budget = _current_budget(self.ticket_directory)
                if budget is None:
                    return False
                state, changed = _read_usage(self.ticket_directory, budget)
                if changed:
                    write_yaml_durably(
                        self.ticket_directory / "execution-budget.yml", state
                    )
                return state["stopped"]
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def continue_after_stop(self) -> None:
        """Clear one sampled stop while retaining the Ticket's accounting."""

        lock_path = self.ticket_directory / ".execution-budget.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                budget = _current_budget(self.ticket_directory)
                if budget is None:
                    raise RunnerError(
                        "invalid-input",
                        "Explicit continuation requires a Ticket execution budget.",
                    )
                state, _ = _read_usage(self.ticket_directory, budget)
                if not state["stopped"]:
                    raise RunnerError(
                        "invalid-input",
                        "Explicit continuation requires a sampled stopped Ticket.",
                    )
                state["budget"] = budget.definition
                state["stopped"] = False
                write_yaml_durably(
                    self.ticket_directory / "execution-budget.yml", state
                )
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def deliver_leader_notices(
        self, deliver: Callable[[list[str]], None]
    ) -> None:
        lock_path = self.ticket_directory / ".execution-budget.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                budget = _current_budget(self.ticket_directory)
                if budget is None:
                    return
                state, _ = _read_usage(self.ticket_directory, budget)
                pending = [
                    notice for notice in state["leader_notices"]
                    if not notice["delivered"]
                ]
                if not pending:
                    return
                deliver([notice["message"] for notice in pending])
                for notice in pending:
                    notice["delivered"] = True
                write_yaml_durably(
                    self.ticket_directory / "execution-budget.yml", state
                )
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def pending_leader_notices(self) -> list[dict[str, str]]:
        lock_path = self.ticket_directory / ".execution-budget.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                budget = _current_budget(self.ticket_directory)
                if budget is None:
                    return []
                state, _ = _read_usage(self.ticket_directory, budget)
                return [
                    {"key": notice["key"], "message": notice["message"]}
                    for notice in state["leader_notices"]
                    if not notice["delivered"]
                ]
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def mark_leader_notices_delivered(self, keys: list[str]) -> None:
        lock_path = self.ticket_directory / ".execution-budget.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                budget = _current_budget(self.ticket_directory)
                if budget is None:
                    return
                state, _ = _read_usage(self.ticket_directory, budget)
                for notice in state["leader_notices"]:
                    if notice["key"] in keys:
                        notice["delivered"] = True
                write_yaml_durably(
                    self.ticket_directory / "execution-budget.yml", state
                )
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _observe(
        self,
        role: str,
        stage: str,
        *,
        session: bool = False,
        correction: bool = False,
    ) -> bool:
        notices = []
        lock_path = self.ticket_directory / ".execution-budget.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                try:
                    budget = _current_budget(self.ticket_directory)
                except ExecutionBudgetError as error:
                    raise RunnerError(
                        "TICKET_FILE_INVALID",
                        "The selected Ticket execution budget is invalid.",
                    ) from error
                if budget is None:
                    return False
                state, created = _read_usage(self.ticket_directory, budget)
                changed = created or state["budget"] != budget.definition
                if changed:
                    state["budget"] = budget.definition
                session_key = _ROLE_SESSIONS.get(role)
                if session and session_key is not None:
                    state["sessions"][session_key] += 1
                    changed = True
                if correction:
                    state["corrections"] += 1
                    changed = True
                stochastic_before = (
                    state["stopping_checks"], state["stopped"]
                )
                notices = _new_notices(
                    state, budget, self.ticket_id, self.ticket_name, role, stage
                )
                changed = changed or stochastic_before != (
                    state["stopping_checks"], state["stopped"]
                )
                if notices:
                    state["notifications"].extend(
                        notice["notification_key"] for notice in notices
                    )
                    state["leader_notices"].extend(
                        {
                            "key": notice["notification_key"],
                            "message": notice["message"],
                            "delivered": False,
                        }
                        for notice in notices
                        if "message" in notice
                    )
                    changed = True
                if changed:
                    write_yaml_durably(
                        self.ticket_directory / "execution-budget.yml", state
                    )
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        for notice in notices:
            notice.pop("notification_key")
            _emit_notice(json.dumps(notice, sort_keys=True) + "\n")
        return state["stopped"]


def _current_budget(ticket_directory: Path) -> ExecutionBudget | None:
    try:
        state = yaml.safe_load((ticket_directory / "ticket.yml").read_text(encoding="utf-8"))
        definition = ticket_directory / state["current_definition"]
        body = definition.read_text(encoding="utf-8")
    except (KeyError, OSError, TypeError, yaml.YAMLError) as error:
        raise ExecutionBudgetError("Ticket budget snapshot is unreadable") from error
    return read_execution_budget(body)


def _emit_notice(output: str) -> None:
    try:
        descriptor = int(os.environ.get("GRAPHTRAJ_BUDGET_NOTICE_FD", ""))
        if descriptor < 3:
            raise ValueError("budget notice descriptor is not inherited")
        os.write(descriptor, output.encode())
        return
    except (OSError, ValueError):
        pass
    try:
        sys.stderr.write(output)
        sys.stderr.flush()
    except OSError:
        pass


def _read_usage(
    ticket_directory: Path, budget: ExecutionBudget
) -> tuple[dict[str, Any], bool]:
    path = ticket_directory / "execution-budget.yml"
    if not path.exists():
        definition = budget.definition["execution_budget"]
        base_allowance = min(
            ADDITIONAL_ALLOWANCE_CAP_MINUTES,
            ESTIMATED_TIME_MULTIPLIER * definition["estimated_minutes"]["total"],
        )
        return (
            {
                "started_at": time.time(),
                "budget": budget.definition,
                "sessions": {role: 0 for role in _SESSION_FIELDS},
                "corrections": 0,
                "notifications": [],
                "allowance_minutes": base_allowance
                * (
                    1
                    + random.uniform(
                        ALLOWANCE_UNIFORM_LOWER_BOUND,
                        ALLOWANCE_UNIFORM_UPPER_BOUND,
                    )
                ),
                "stopping_checks": 0,
                "stopped": False,
                "leader_notices": [],
            },
            True,
        )
    try:
        state = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise RunnerError(
            "TICKET_FILE_INVALID", "The Ticket execution budget accounting is invalid."
        ) from error
    legacy = set(state) == {
        "started_at", "budget", "sessions", "corrections", "notifications"
    }
    if legacy:
        definition = budget.definition["execution_budget"]
        base_allowance = min(
            ADDITIONAL_ALLOWANCE_CAP_MINUTES,
            ESTIMATED_TIME_MULTIPLIER * definition["estimated_minutes"]["total"],
        )
        state.update(
            allowance_minutes=base_allowance
            * (
                1
                + random.uniform(
                    ALLOWANCE_UNIFORM_LOWER_BOUND,
                    ALLOWANCE_UNIFORM_UPPER_BOUND,
                )
            ),
            stopping_checks=0,
            stopped=False,
            leader_notices=[],
        )
    if (
        not isinstance(state, dict)
        or set(state) != {
            "started_at", "budget", "sessions", "corrections", "notifications",
            "allowance_minutes", "stopping_checks", "stopped", "leader_notices",
        }
        or not _nonnegative_number(state["started_at"])
        or not isinstance(state["budget"], dict)
        or not isinstance(state["sessions"], dict)
        or set(state["sessions"]) != _SESSION_FIELDS
        or any(type(value) is not int or value < 0 for value in state["sessions"].values())
        or type(state["corrections"]) is not int
        or state["corrections"] < 0
        or not isinstance(state["notifications"], list)
        or any(not isinstance(value, str) for value in state["notifications"])
        or not _nonnegative_number(state["allowance_minutes"])
        or type(state["stopping_checks"]) is not int
        or state["stopping_checks"] < 0
        or type(state["stopped"]) is not bool
        or not isinstance(state["leader_notices"], list)
        or any(
            not isinstance(value, dict)
            or set(value) != {"key", "message", "delivered"}
            or not _text(value["key"])
            or not _text(value["message"])
            or type(value["delivered"]) is not bool
            for value in state["leader_notices"]
        )
    ):
        raise RunnerError(
            "TICKET_FILE_INVALID", "The Ticket execution budget accounting is invalid."
        )
    return state, legacy


def _new_notices(
    state: dict[str, Any],
    budget: ExecutionBudget,
    ticket_id: str,
    ticket_name: str,
    role: str,
    stage: str,
) -> list[dict[str, Any]]:
    definition = budget.definition["execution_budget"]
    elapsed = max(0.0, (time.time() - state["started_at"]) / 60)
    actual = {
        "elapsed_minutes": elapsed,
        "sessions": dict(state["sessions"]),
        "session_total": sum(state["sessions"].values()),
        "corrections": state["corrections"],
    }
    exceeded = []
    estimated = definition["estimated_minutes"]["total"]
    allowance = state["allowance_minutes"]
    seen = set(state["notifications"])
    if elapsed >= estimated:
        exceeded.append(
            (
                "elapsed_minutes",
                estimated,
                "System notice: Elapsed time: {0}. The planned budget of {1} has been reached.".format(
                    _duration(elapsed), _duration(estimated)
                ),
            )
        )
    if elapsed >= estimated + allowance:
        exceeded.append(
            (
                "additional_allowance",
                allowance,
                "System reminder: Elapsed time: {0}. The planned budget and additional allowance of {1} have been exceeded. Review progress and remaining work now.".format(
                    _duration(elapsed), _duration(allowance)
                ),
            )
        )
        due = int((elapsed - estimated - allowance) // STOPPING_INTERVAL_MINUTES)
        while not state["stopped"] and state["stopping_checks"] < due:
            state["stopping_checks"] += 1
            checked_at = state["stopping_checks"] * STOPPING_INTERVAL_MINUTES
            if random.random() >= math.exp(-STOPPING_LAMBDA_PER_MINUTE * checked_at):
                state["stopped"] = True
                exceeded.append(
                    (
                        "stochastic_stop",
                        checked_at,
                        "System notice: Elapsed time: {0}. Execution has taken too long and must stop.".format(
                            _duration(elapsed)
                        ),
                    )
                )
    for session_role, limit in definition["planned_sessions"].items():
        if state["sessions"][session_role] > limit:
            exceeded.append(("planned_sessions." + session_role, limit, None))
    if state["corrections"] > definition["correction_rounds"]:
        exceeded.append(("correction_rounds", definition["correction_rounds"], None))
    notices = []
    for kind, limit, message in exceeded:
        key = kind + ":" + json.dumps(limit, sort_keys=True)
        if key not in seen:
            notice = {
                    "type": "execution-budget-exceeded",
                    "ticket": {"ticket_id": ticket_id, "ticket_name": ticket_name},
                    "threshold": {"kind": kind, "limit": limit},
                    "actual": actual,
                    "stage": stage,
                    "responsible_role": role,
                    "notification_key": key,
                }
            if message is not None:
                notice["message"] = message
            notices.append(notice)
    return notices


def _duration(minutes: float) -> str:
    seconds = int(minutes * 60)
    hours, seconds = divmod(seconds, 3600)
    minutes_value, seconds = divmod(seconds, 60)
    return "{0:02d}:{1:02d}:{2:02d}".format(hours, minutes_value, seconds)


def _validate_budget(value: Any) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != {"difficulty", "difficulty_reason", "execution_budget"}
        or not _text(value["difficulty"])
        or not _text(value["difficulty_reason"])
        or not isinstance(value["execution_budget"], dict)
    ):
        raise ExecutionBudgetError("execution budget front matter has invalid fields")
    budget = value["execution_budget"]
    if frozenset(budget) not in {_BUDGET_FIELDS, _BUDGET_FIELDS | {"revision_reason"}}:
        raise ExecutionBudgetError("execution budget front matter has invalid fields")
    if (
        budget["engineer_tier"] not in {"junior", "senior", "expert"}
        or not _text(budget["tier_reason"])
        or not _text(budget["estimation_note"])
        or not _text(budget["on_exceed"])
        or not isinstance(budget["estimated_minutes"], dict)
        or set(budget["estimated_minutes"]) != _MINUTE_FIELDS
        or any(not _positive_number(item) for item in budget["estimated_minutes"].values())
        or not isinstance(budget["planned_sessions"], dict)
        or set(budget["planned_sessions"]) != _SESSION_FIELDS
        or any(not _positive_number(item) for item in budget["planned_sessions"].values())
        or not _nonnegative_number(budget["correction_rounds"])
        or (
            "revision_reason" in budget
            and not _text(budget["revision_reason"])
        )
    ):
        raise ExecutionBudgetError("execution budget front matter has invalid values")


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _positive_number(value: object) -> bool:
    return _nonnegative_number(value) and value > 0


def _nonnegative_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value >= 0
        and (not isinstance(value, float) or math.isfinite(value))
    )
