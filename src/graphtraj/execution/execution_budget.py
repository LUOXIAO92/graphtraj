"""Task execution budget parsing and live accounting."""

from __future__ import annotations

import json
import math
import os
import random
import time
from contextlib import contextmanager
from datetime import datetime
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

import yaml

from graphtraj import file_lock
from graphtraj.configuration.project_roles import configured_role_name
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.execution.runner_models import RunnerError


ADDITIONAL_ALLOWANCE_CAP_MINUTES = 20
ESTIMATED_TIME_MULTIPLIER = 0.2
ALLOWANCE_UNIFORM_LOWER_BOUND = -0.5
ALLOWANCE_UNIFORM_UPPER_BOUND = 0.5
STOPPING_LAMBDA_PER_MINUTE = 0.25
STOPPING_INTERVAL_MINUTES = 2

_BUDGET_FIELDS = frozenset(
    {
        "estimated_minutes",
        "planned_sessions",
        "correction_rounds",
        "estimation_note",
        "on_exceed",
    }
)
# Already accepted Tasks retain their estimation-only tier fields.
_LEGACY_BUDGET_FIELDS = frozenset({"engineer_tier", "tier_reason"})


class ExecutionBudgetError(ValueError):
    """The task execution budget is invalid."""


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
    """Read the optional task budget at the very beginning of a Task body."""

    front_matter = split_execution_budget_front_matter(body)
    if front_matter is None:
        return None
    _, document, _ = front_matter
    try:
        value = yaml.safe_load(document)
    except yaml.YAMLError as error:
        raise ExecutionBudgetError("execution budget front matter is not YAML") from error
    if (isinstance(value, dict) and set(value) == {"task"}
            and isinstance(value["task"], dict) and value["task"].get("schema_version") == 2):
        return read_execution_budget(front_matter[2])
    if not isinstance(value, dict) or "execution_budget" not in value:
        return None
    _validate_budget(value)
    return ExecutionBudget(value)


def execution_budget_monitor(
    task_directory: Path, task_id: str, task_name: str
) -> "ExecutionBudgetMonitor | None":
    """Return a monitor only for a registered Task with a budget."""

    if not (task_directory / "task.yml").is_file():
        return None
    try:
        budget = _current_budget(task_directory)
    except ExecutionBudgetError as error:
        raise RunnerError(
            "TASK_FILE_INVALID", "The selected Task execution budget is invalid."
        ) from error
    if budget is None:
        return None
    return ExecutionBudgetMonitor(task_directory, task_id, task_name)


def execution_budget_monitor_from_environment(
    mapping: Mapping[str, object],
) -> "ExecutionBudgetMonitor | None":
    """Resolve one resumed Session's monitor from its retained Team context."""

    evidence = os.environ.get("GRAPHTRAJ_EVIDENCE")
    task_id = mapping.get("task_id")
    task_name = os.environ.get("GRAPHTRAJ_TASK_NAME")
    if (
        not isinstance(evidence, str)
        or not evidence
        or not isinstance(task_id, str)
        or not task_id
        or not isinstance(task_name, str)
        or not task_name
    ):
        return None
    return execution_budget_monitor(Path(evidence), task_id, task_name)


_NOTICE_OUTPUT: ContextVar[int | None] = ContextVar("budget_notice_output", default=None)


@contextmanager
def budget_notice_output(descriptor: int) -> Iterator[None]:
    """Route live budget JSONL to a caller-owned descriptor for this operation.

    The caller keeps the descriptor open for the operation's lifetime. Without
    a selected or inherited channel, accounting and parent notices are still
    retained, but no terminal output is produced. CLI callers select stderr.
    """
    os.fstat(descriptor)
    token = _NOTICE_OUTPUT.set(descriptor)
    try:
        yield
    finally:
        _NOTICE_OUTPUT.reset(token)


def caller_notice_fd() -> tuple[int | None, bool]:
    """Return the selected or inherited notice channel and its close ownership."""

    try:
        selected = _NOTICE_OUTPUT.get()
        if selected is not None:
            return os.dup(selected), True
        descriptor = int(os.environ.get("GRAPHTRAJ_BUDGET_NOTICE_FD", ""))
        if descriptor < 3:
            raise ValueError("budget notice descriptor is not inherited")
        os.fstat(descriptor)
        return descriptor, False
    except (OSError, ValueError):
        return None, False


def execution_budget_stage(role: str) -> str:
    """Label elapsed-time observations with the actual execution role."""

    return role


def _session_key(role: str) -> str:
    """Use the actual role reference for Session accounting."""
    return configured_role_name(role).replace("-", "_")


class ExecutionBudgetMonitor:
    """Persist actual use and emit each budget threshold crossing once."""

    def __init__(self, task_directory: Path, task_id: str, task_name: str) -> None:
        self.task_directory = task_directory
        self.task_id = task_id
        self.task_name = task_name

    def record_session(self, role: str, stage: str) -> None:
        """Count one created Session against the shared Task budget."""
        self._observe(role, stage, session=True)

    def record_correction(self, role: str) -> None:
        self._observe(role, "correction", correction=True)

    def check(self, role: str, stage: str) -> bool:
        """Observe elapsed time and return whether Runner selected stopping."""
        return self._observe(role, stage)

    def is_stopped(self) -> bool:
        lock_path = self.task_directory / ".execution-budget.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            file_lock.flock(lock.fileno(), file_lock.LOCK_EX)
            try:
                budget = _current_budget(self.task_directory)
                if budget is None:
                    return False
                state, changed = _read_usage(self.task_directory, budget)
                if changed:
                    write_yaml_durably(
                        self.task_directory / "execution-budget.yml", state
                    )
                return state["stopped"]
            finally:
                file_lock.flock(lock.fileno(), file_lock.LOCK_UN)

    def continue_after_stop(self) -> None:
        """Clear one sampled stop while retaining the Task's accounting."""

        lock_path = self.task_directory / ".execution-budget.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            file_lock.flock(lock.fileno(), file_lock.LOCK_EX)
            try:
                budget = _current_budget(self.task_directory)
                if budget is None:
                    raise RunnerError(
                        "invalid-input",
                        "Explicit continuation requires a Task execution budget.",
                    )
                state, _ = _read_usage(self.task_directory, budget)
                if not state["stopped"]:
                    raise RunnerError(
                        "invalid-input",
                        "Explicit continuation requires a sampled stopped Task.",
                    )
                state["budget"] = budget.definition
                state["stopped"] = False
                write_yaml_durably(
                    self.task_directory / "execution-budget.yml", state
                )
            finally:
                file_lock.flock(lock.fileno(), file_lock.LOCK_UN)

    def deliver_parent_notices(self, session_directory: Path) -> None:
        """Deliver once to the task's recorded parent, outside the budget lock.

        The notifying Session uses its own direct parent, including while that
        parent's Driver waits for children. A caller-channel write records
        transport only and never claims that an Agent received the notice.
        """
        from graphtraj.execution.runner_control import notify_direct_parent
        from graphtraj.execution.runner_status import read_alias_mapping

        runner = session_directory.parent.parent
        if (session_directory / "mapping.yml").is_file():
            mapping, directory = read_alias_mapping(runner, session_directory.name)
        else:
            # Runner wrote this launch after binding the trusted creator. It is
            # also available when admission stops before a native Session exists.
            mapping = yaml.safe_load((session_directory / "launch.yml").read_text())["mapping"]
            directory = session_directory

        def deliver(pending: list[dict[str, Any]]) -> list[str]:
            """Return only notice keys acknowledged by the actual parent."""
            received = []
            for notice in pending:
                if isinstance(mapping.get("parent"), str) or mapping.get("parent_connection") is not None:
                    receipt = notify_direct_parent(
                        directory, notice["message"],
                        {"type": "execution-budget-exceeded", "key": notice["key"]},
                        before_creation=True,
                    )
                    if receipt["delivery"] == "received":
                        received.append(notice["key"])
                elif not notice.get("channel_written", False):
                    event = notice.get("event", {"message": notice["message"]})
                    if _emit_notice(json.dumps(event, sort_keys=True) + "\n"):
                        self._mark_channel_written(notice["key"])
            return received

        self.deliver_notices(deliver)

    def _mark_channel_written(self, key: str) -> None:
        """Retain a caller-channel write without asserting native receipt."""
        with (self.task_directory / ".execution-budget.lock").open("a+") as lock:
            file_lock.flock(lock.fileno(), file_lock.LOCK_EX)
            try:
                budget = _current_budget(self.task_directory)
                if budget is None:
                    return
                state, _ = _read_usage(self.task_directory, budget)
                for notice in state["parent_notices"]:
                    if notice["key"] == key:
                        notice["channel_written"] = True
                write_yaml_durably(self.task_directory / "execution-budget.yml", state)
            finally:
                file_lock.flock(lock.fileno(), file_lock.LOCK_UN)

    def deliver_notices(
        self, deliver: Callable[[list[dict[str, Any]]], list[str]]
    ) -> None:
        """Serialize delivery without holding the budget lock across the callback."""
        # Session recovery reads the budget while holding its launch lock.
        # Delivery may need that Session lock, so use a separate persistent lock.
        lock_path = self.task_directory / ".execution-budget-notices.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            file_lock.flock(lock.fileno(), file_lock.LOCK_EX)
            try:
                pending = self.pending_parent_notices()
                if not pending:
                    return
                received = deliver(pending)
                if received:
                    self.mark_parent_notices_delivered(received)
            finally:
                file_lock.flock(lock.fileno(), file_lock.LOCK_UN)

    def pending_parent_notices(self) -> list[dict[str, Any]]:
        """Return retained notices without confirmed parent receipt."""
        lock_path = self.task_directory / ".execution-budget.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            file_lock.flock(lock.fileno(), file_lock.LOCK_EX)
            try:
                budget = _current_budget(self.task_directory)
                if budget is None:
                    return []
                state, _ = _read_usage(self.task_directory, budget)
                return [
                    dict(notice)
                    for notice in state["parent_notices"]
                    if not notice["delivered"]
                ]
            finally:
                file_lock.flock(lock.fileno(), file_lock.LOCK_UN)

    def mark_parent_notices_delivered(self, keys: list[str]) -> None:
        """Record only keys acknowledged by the bound parent transport."""
        lock_path = self.task_directory / ".execution-budget.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            file_lock.flock(lock.fileno(), file_lock.LOCK_EX)
            try:
                budget = _current_budget(self.task_directory)
                if budget is None:
                    return
                state, _ = _read_usage(self.task_directory, budget)
                for notice in state["parent_notices"]:
                    if notice["key"] in keys:
                        notice["delivered"] = True
                write_yaml_durably(
                    self.task_directory / "execution-budget.yml", state
                )
            finally:
                file_lock.flock(lock.fileno(), file_lock.LOCK_UN)

    def _observe(
        self,
        role: str,
        stage: str,
        *,
        session: bool = False,
        correction: bool = False,
    ) -> bool:
        notices = []
        lock_path = self.task_directory / ".execution-budget.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            file_lock.flock(lock.fileno(), file_lock.LOCK_EX)
            try:
                try:
                    budget = _current_budget(self.task_directory)
                except ExecutionBudgetError as error:
                    raise RunnerError(
                        "TASK_FILE_INVALID",
                        "The selected Task execution budget is invalid.",
                    ) from error
                if budget is None:
                    return False
                state, created = _read_usage(self.task_directory, budget)
                changed = created or state["budget"] != budget.definition
                if changed:
                    state["budget"] = budget.definition
                session_key = _session_key(role)
                if session:
                    state["sessions"].setdefault(session_key, 0)
                    state["sessions"][session_key] += 1
                    changed = True
                if correction:
                    state["corrections"] += 1
                    changed = True
                stochastic_before = (
                    state["stopping_checks"], state["stopped"]
                )
                notices = _new_notices(
                    state, budget, self.task_id, self.task_name, role, stage
                )
                changed = changed or stochastic_before != (
                    state["stopping_checks"], state["stopped"]
                )
                if notices:
                    state["notifications"].extend(
                        notice["notification_key"] for notice in notices
                    )
                    state["parent_notices"].extend(
                        {
                            "key": notice["notification_key"],
                            "message": notice["message"],
                            "delivered": False,
                            "event": {key: value for key, value in notice.items()
                                      if key != "notification_key"},
                        }
                        for notice in notices
                    )
                    changed = True
                if changed:
                    write_yaml_durably(
                        self.task_directory / "execution-budget.yml", state
                    )
            finally:
                file_lock.flock(lock.fileno(), file_lock.LOCK_UN)
        return state["stopped"]


def _current_budget(task_directory: Path) -> ExecutionBudget | None:
    try:
        state = yaml.safe_load((task_directory / "task.yml").read_text(encoding="utf-8"))
        definition = task_directory / state["current_definition"]
        body = definition.read_text(encoding="utf-8")
    except (KeyError, OSError, TypeError, yaml.YAMLError) as error:
        raise ExecutionBudgetError("Task budget snapshot is unreadable") from error
    return read_execution_budget(body)


def _emit_notice(output: str) -> bool:
    """Send an already retained notice over the selected execution channel."""
    descriptor, owned = caller_notice_fd()
    if descriptor is None:
        return False
    try:
        os.write(descriptor, output.encode())
        return True
    except OSError:
        return False
    finally:
        if owned:
            os.close(descriptor)


def _read_usage(
    task_directory: Path, budget: ExecutionBudget
) -> tuple[dict[str, Any], bool]:
    path = task_directory / "execution-budget.yml"
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
                "sessions": {role: 0 for role in definition["planned_sessions"]},
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
                "parent_notices": [],
            },
            True,
        )
    try:
        state = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise RunnerError(
            "TASK_FILE_INVALID", "The Task execution budget accounting is invalid."
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
            parent_notices=[],
        )
    if (
        isinstance(state, dict)
        and "leader_notices" in state
        and "parent_notices" not in state
    ):
        # Records retained before the queue was renamed after its actual
        # recipient stay readable; the current key is used from here on.
        state["parent_notices"] = state.pop("leader_notices")
    if (
        not isinstance(state, dict)
        or set(state) - {"approved_minutes", "approved_window_started_at"} != {
            "started_at", "budget", "sessions", "corrections", "notifications",
            "allowance_minutes", "stopping_checks", "stopped", "parent_notices",
        }
        or not _nonnegative_number(state.get("approved_minutes", 0))
        or not _nonnegative_number(state.get("approved_window_started_at", 0))
        or not _nonnegative_number(state["started_at"])
        or not isinstance(state["budget"], dict)
        or not isinstance(state["sessions"], dict)
        or any(not isinstance(name, str) for name in state["sessions"])
        or any(type(value) is not int or value < 0 for value in state["sessions"].values())
        or type(state["corrections"]) is not int
        or state["corrections"] < 0
        or not isinstance(state["notifications"], list)
        or any(not isinstance(value, str) for value in state["notifications"])
        or not _nonnegative_number(state["allowance_minutes"])
        or type(state["stopping_checks"]) is not int
        or state["stopping_checks"] < 0
        or type(state["stopped"]) is not bool
        or not isinstance(state["parent_notices"], list)
        or any(
            not isinstance(value, dict)
            or not {"key", "message", "delivered"} <= set(value) <= {
                "key", "message", "delivered", "event", "channel_written",
            }
            or ("event" in value and not isinstance(value["event"], dict))
            or ("channel_written" in value and type(value["channel_written"]) is not bool)
            or not _text(value["key"])
            or not _text(value["message"])
            or type(value["delivered"]) is not bool
            for value in state["parent_notices"]
        )
    ):
        raise RunnerError(
            "TASK_FILE_INVALID", "The Task execution budget accounting is invalid."
        )
    return state, legacy


def _new_notices(
    state: dict[str, Any],
    budget: ExecutionBudget,
    task_id: str,
    task_name: str,
    role: str,
    stage: str,
) -> list[dict[str, Any]]:
    definition = budget.definition["execution_budget"]
    observed_at = time.time()
    elapsed = max(0.0, (observed_at - state["started_at"]) / 60)
    counted = _counted_minutes(state, definition, observed_at)
    actual = {
        "elapsed_minutes": elapsed,
        "sessions": dict(state["sessions"]),
        "session_total": sum(state["sessions"].values()),
        "corrections": state["corrections"],
    }
    exceeded = []
    estimated = definition["estimated_minutes"]["total"] + state.get("approved_minutes", 0)
    allowance = state["allowance_minutes"]
    seen = set(state["notifications"])
    # An approved window resumes the count at the exhausted allowance, so its
    # planned end is the full increment later, not ``allowance`` minutes early.
    planned_end = estimated + (allowance if "approved_window_started_at" in state else 0)
    if counted >= planned_end:
        exceeded.append(
            (
                "elapsed_minutes",
                estimated,
                "System notice: Elapsed time: {0}. The planned budget of {1} has been reached.".format(
                    _duration(elapsed), _duration(estimated)
                ),
            )
        )
    if counted >= estimated + allowance:
        exceeded.append(
            (
                "additional_allowance",
                allowance,
                "System reminder: Elapsed time: {0}. The planned budget and additional allowance of {1} have been exceeded. Review progress and remaining work now.".format(
                    _duration(elapsed), _duration(allowance)
                ),
            )
        )
        due = int((counted - estimated - allowance) // STOPPING_INTERVAL_MINUTES)
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
        if state["sessions"].get(session_role, 0) > limit:
            exceeded.append(("planned_sessions." + session_role, limit, None))
    if state["corrections"] > definition["correction_rounds"]:
        exceeded.append(("correction_rounds", definition["correction_rounds"], None))
    notices = []
    for kind, limit, message in exceeded:
        key = kind + ":" + json.dumps(limit, sort_keys=True)
        if key not in seen:
            notice = {
                    "type": "execution-budget-exceeded",
                    "occurred_at": _event_instant(observed_at),
                    "task": {"task_id": task_id, "task_name": task_name},
                    "threshold": {"kind": kind, "limit": limit},
                    "actual": actual,
                    "stage": stage,
                    "responsible_role": role,
                    "notification_key": key,
                }
            notice["message"] = message or (
                f"System notice: Task {task_id} exceeded {kind} ({limit})."
            )
            notices.append(notice)
    return notices


def _counted_minutes(state: dict[str, Any], definition: dict[str, Any], now: float) -> float:
    """Return the minutes counted against the budget at ``now``.

    Wall time since ``started_at`` counts until an approved increment arrives
    after the budget and allowance ran out. From ``approved_window_started_at``
    the count resumes at that exhausted threshold, so waiting for approval is
    not execution time; the historical clock itself is unchanged::

        counted = total + allowance + (now - approved_window_started_at) / 60
    """
    window = state.get("approved_window_started_at")
    if window is None:
        return max(0.0, (now - state["started_at"]) / 60)
    return (definition["estimated_minutes"]["total"] + state["allowance_minutes"]
            + max(0.0, (now - window) / 60))


def start_approved_window(before: dict[str, Any], after: dict[str, Any], now: float) -> dict[str, Any]:
    """Return ``after`` with its approved increment counted as execution time from ``now``.

    ``before`` is the accounting the increment was approved against. When it
    had already exhausted its budget, allowance and earlier approvals, the
    window start is placed so the count resumes at that threshold now;
    otherwise the increment simply extends the running count.
    """
    previous = before.get("approved_minutes", 0)
    if after.get("approved_minutes", 0) <= previous or "allowance_minutes" not in before:
        return after
    definition = before["budget"]["execution_budget"]
    threshold = definition["estimated_minutes"]["total"] + before["allowance_minutes"] + previous
    if _counted_minutes(before, definition, now) <= threshold:
        return after
    return {**after, "approved_window_started_at": now - previous * 60}


def _event_instant(seconds: float) -> str:
    """Return one budget event's absolute instant with its explicit UTC offset.

    The offset is the machine's actual local offset at that instant, so a
    receiver can tell when the event happened without guessing a time or
    reading the elapsed duration as a clock time.
    """
    return datetime.fromtimestamp(seconds).astimezone().isoformat(timespec="seconds")


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
    allowed = _BUDGET_FIELDS | _LEGACY_BUDGET_FIELDS | {"revision_reason"}
    if not _BUDGET_FIELDS <= frozenset(budget) <= allowed:
        raise ExecutionBudgetError("execution budget front matter has invalid fields")
    if (
        not _text(budget["estimation_note"])
        or not _text(budget["on_exceed"])
        or not isinstance(budget["estimated_minutes"], dict)
        or "total" not in budget["estimated_minutes"]
        or any(not _text(name) for name in budget["estimated_minutes"])
        or any(not _positive_number(item) for item in budget["estimated_minutes"].values())
        or not isinstance(budget["planned_sessions"], dict)
        or any(not _text(name) for name in budget["planned_sessions"])
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
