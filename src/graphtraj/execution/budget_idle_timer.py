"""Deliver a timed Session's elapsed-budget notice while no execution runs (445).

Thresholds are otherwise observed only by a running execution's monitor, at
an execution start, or at native Session creation. When every member is idle
nobody samples the budget, so the notice waited for the next turn.

When a monitored execution ends with an elapsed threshold still ahead, the
Worker starts one detached timer process for that Session. It runs no
Runtime or model: it sleeps until the threshold and then exits without
acting if the Session runs an execution again (that execution's own monitor
observes it), if a newer timer replaced it, if the Session record was
removed, or if the Task is stopped. Otherwise it observes the thresholds
with ``check_elapsed`` (no stopping sample: stops stay with running
executions) and calls ``deliver_parent_notices`` with the Session as
observer, so the
existing keys deliver each notice once to the observer's direct parent:
Main through the root ``parent_connection`` for a Leader, the Leader for an
Engineer. A replacement, a resume, a stop or a cleanup never waits for it.
"""

from __future__ import annotations

import os
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
    return (not session_directory.is_dir() or _current_token(session_directory) != token
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
) -> bool:
    """Wait for each pending elapsed threshold and deliver it; True if any was delivered."""
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
        if monitor.deliver_parent_notices(session_directory):
            return delivered  # Held for a stopped parent's continuation.
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
        run_idle_budget_timer(session_directory, token, monitor, role, ended_worker=ended_worker)
    except (RunnerError, OSError, ValueError, KeyError, yaml.YAMLError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
