"""Deliver a timed Session's elapsed-budget notice while no execution runs (445).

Thresholds are otherwise observed only by a running execution's monitor, at
an execution start, or at native Session creation. When every member is idle
nobody samples the budget, so the notice waited for the next turn.

When a monitored execution ends with an elapsed threshold still ahead, the
Worker starts one detached timer process for that Session. It runs no
Runtime or model: it sleeps until the threshold and then exits without
acting if the Session runs an execution again (that execution's own monitor
observes it), if a newer timer replaced it, if the Session record was
removed, or if the Task is stopped or its directory removed. Otherwise it observes the thresholds
with ``check_elapsed`` (no stopping sample: stops stay with running
executions) and calls ``deliver_parent_notices`` with the Session as
observer, so the
existing keys deliver each notice once to the observer's direct parent:
Main through the root ``parent_connection`` for a Leader, the Leader for an
Engineer. A replacement, a resume, a stop or a cleanup never waits for it.

Its life is bounded (454): waiting ends at the last elapsed threshold or at
one of the exits above, and each delivery attempt is given at most
``DELIVERY_SECONDS``: a parent lock or connection that never answers ends the
timer, and the undelivered notice stays retained for the next execution start.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Callable

import yaml

from graphtraj.execution.execution_budget import (
    ExecutionBudgetMonitor,
    execution_budget_monitor_from_environment,
    execution_budget_stage,
)
from graphtraj.execution.runner_heartbeat import ownership_is_held, read_heartbeat
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_models import MEMBER_RUN_ENV

TIMER_FILE_NAME = "budget-timer.yml"
# Sleep in short slices so a replaced or cleaned Session's timer exits soon.
SLICE_SECONDS = 30.0
MARGIN_SECONDS = 1.0
# Upper bound of one delivery attempt (flock waits and parent send included).
DELIVERY_SECONDS = 300.0


class DeliveryTimeout(Exception):
    """One delivery attempt exceeded ``DELIVERY_SECONDS``."""


def _bounded(seconds: float | None, call: Callable[[], bool]) -> bool:
    """Run ``call``; raise DeliveryTimeout once ``seconds`` pass (main thread only)."""
    if seconds is None:
        return call()

    def expire(signum: int, frame: object) -> None:
        raise DeliveryTimeout()

    previous = signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return call()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def start_idle_budget_timer(session_directory: Path, monitor: ExecutionBudgetMonitor) -> str | None:
    """Start the detached timer for the next elapsed threshold; return its token."""
    if monitor.next_elapsed_threshold_at() is None:
        return None
    token = uuid.uuid4().hex
    path = session_directory / TIMER_FILE_NAME
    temporary = path.with_name(path.name + "." + token + ".tmp")
    temporary.write_text(yaml.safe_dump({"token": token, "pid": None}), encoding="utf-8")
    os.replace(temporary, path)
    subprocess.Popen(
        [sys.executable, "-I", "-m", "graphtraj.execution.budget_idle_timer", str(session_directory), token,
         str(os.getpid())],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, close_fds=True,
        env={key: value for key, value in os.environ.items() if key != MEMBER_RUN_ENV},
    )
    return token


def _current_token(session_directory: Path) -> str | None:
    try:
        record = yaml.safe_load((session_directory / TIMER_FILE_NAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return None
    return record.get("token") if isinstance(record, dict) else None


def _running(session_directory: Path, ended_worker: int | None) -> bool:
    """Whether a later execution owns the Session; the ending Worker does not count."""
    heartbeat = read_heartbeat(session_directory)
    return (heartbeat is not None and heartbeat["worker_pid"] != ended_worker
            and ownership_is_held(session_directory, heartbeat["worker_pid"]))


def _should_exit(session_directory: Path, token: str, monitor: ExecutionBudgetMonitor,
                 ended_worker: int | None) -> bool:
    return (not session_directory.is_dir() or not monitor.task_directory.is_dir()
            or _current_token(session_directory) != token
            or _running(session_directory, ended_worker) or monitor.is_stopped())


def run_idle_budget_timer(
    session_directory: Path,
    token: str,
    monitor: ExecutionBudgetMonitor,
    role: str,
    *,
    ended_worker: int | None = None,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    delivery_seconds: float | None = None,
) -> bool:
    """Wait for each pending elapsed threshold and deliver it; True if any was delivered.

    With ``delivery_seconds``, a delivery attempt that takes longer ends the
    timer (False for that attempt); the notice stays retained.
    """
    delivered = False
    while True:
        due = monitor.next_elapsed_threshold_at()
        if due is None:
            return delivered
        while True:
            if _should_exit(session_directory, token, monitor, ended_worker):
                return delivered
            remaining = due + MARGIN_SECONDS - clock()
            if remaining <= 0:
                break
            sleep(min(SLICE_SECONDS, remaining))
        monitor.check_elapsed(role, execution_budget_stage(role))
        try:
            if _bounded(delivery_seconds, lambda: monitor.deliver_parent_notices(session_directory)):
                return delivered  # Held for a stopped parent's continuation.
        except DeliveryTimeout:
            return delivered  # Retained for the next execution start.
        delivered = True
        if monitor.next_elapsed_threshold_at() == due:
            return delivered  # Not crossed after all (clock skew); never spin.


def main(argv: list[str]) -> int:
    session_directory, token, ended_worker = Path(argv[0]), argv[1], int(argv[2])
    try:
        from graphtraj.execution.runner_status import read_alias_mapping

        mapping, _ = read_alias_mapping(session_directory.parent.parent, session_directory.name)
        monitor = execution_budget_monitor_from_environment(mapping)
        role = mapping.get("role")
        if monitor is None or not isinstance(role, str) or not role:
            return 0
        run_idle_budget_timer(session_directory, token, monitor, role, ended_worker=ended_worker,
                              delivery_seconds=DELIVERY_SECONDS)
    except (RunnerError, OSError, ValueError, KeyError, yaml.YAMLError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
