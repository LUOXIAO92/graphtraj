"""Stop, at the end of a pytest session, every process this test run started (454).

Tests start detached helpers: idle budget timers, Workers, fake Runtimes and
hosts that run in their own session or process group, so neither the shard's
process group nor ancestry finds them afterwards. The session therefore marks
its environment with ``TEST_RUN_ENV`` and, at its end, stops every same-user
process that carries exactly that value, except pytest and its ancestors.
Children inherit the value unless a spawner builds its environment from
scratch. Names and command patterns are never matched (the scanner of
``graftling.member_processes``).

``scripts/run_test_shards.py`` gives each shard ``<run id>-<n>``; a plain
``pytest`` draws its own value. A value already set is kept, so one shard's
cleanup never touches another shard's processes.

The reclaim runs only on macOS and Linux (622): the scanner reads other
processes' environments through ``/proc`` and libproc, which Windows lacks, and
the Windows CI runner is discarded after its job. Marking the run and ending
budget timers stay on every platform.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

# graftling.member_processes is imported where it is used, not at load: conftest
# loads this module before pytest_sessionstart, whose check names an interpreter
# that lacks graftling or GraphTraj's installed metadata with its fix (504).

# The name avoids KEY, SECRET and TOKEN, which credential filters drop, and the
# GRAPHTRAJ_ prefix, which the isolated_runner_environment fixture removes per test.
TEST_RUN_ENV = "PYTEST_GRAPHTRAJ_RUN"


def mark_test_run() -> str:
    """Return this run's value, drawing a fresh one when none is set."""
    value = os.environ.get(TEST_RUN_ENV)
    if not value:
        value = os.environ[TEST_RUN_ENV] = uuid.uuid4().hex
    return value


def reclaim_test_run(value: str | None = None) -> dict:
    """Stop the processes carrying this run's value; report what was found."""
    from graftling.member_processes import ancestor_pids, stop_marked_processes

    value = value or os.environ.get(TEST_RUN_ENV, "")
    return stop_marked_processes(value, exclude=ancestor_pids(), variable=TEST_RUN_ENV)


def end_budget_timers(directory: Path) -> int:
    """End the idle budget timers whose Sessions live under ``directory`` (490).

    Removing a Session's ``budget-timer.yml`` is the timer's own exit: the
    timer that no longer finds its record exits at its next sleep slice
    without acting. No process is signalled. Returns how many records went.
    """
    from graphtraj.execution.budget_idle_timer import TIMER_FILE_NAME

    records = list(directory.rglob(TIMER_FILE_NAME))
    for record in records:
        record.unlink(missing_ok=True)
    return len(records)


@pytest.fixture(autouse=True)
def end_test_budget_timers(request: pytest.FixtureRequest):
    """Timers a test's Runner Sessions started end with that test (490).

    pytest keeps recent temporary directories, so without this a timer of a
    passed test would wait for its last elapsed threshold.
    """
    yield
    directory = (request.node.funcargs or {}).get("tmp_path")
    if isinstance(directory, Path) and directory.is_dir():
        end_budget_timers(directory)


def await_ended_timers(value: str) -> None:
    """Give timers whose records the teardowns removed one sleep slice to exit (490).

    Only waits; whatever still runs afterwards is left to the reclaim, whose
    report then names it.
    """
    from graftling.member_processes import ancestor_pids, find_marked_processes
    from graphtraj.execution.budget_idle_timer import SLICE_SECONDS

    deadline = time.monotonic() + SLICE_SECONDS + 1
    while time.monotonic() < deadline:
        try:
            found = find_marked_processes(value, exclude=ancestor_pids(), variable=TEST_RUN_ENV)
        except (OSError, subprocess.SubprocessError):
            return  # The reclaim below reports the same error.
        if not any("graphtraj.execution.budget_idle_timer" in command for command in found.values()):
            return
        time.sleep(0.2)


def reclaim_supported() -> bool:
    """Whether graftling's scanner can read other processes' environments here (622)."""
    return sys.platform == "darwin" or sys.platform.startswith("linux")


def pytest_configure(config: pytest.Config) -> None:
    mark_test_run()


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session) -> None:
    if importlib.util.find_spec("graftling") is None:
        return  # pytest_sessionstart stopped this run, naming the missing graftling; no test started anything.
    if not reclaim_supported():
        return  # No scanner on this platform (622); the runner's processes go with it.
    value = os.environ.get(TEST_RUN_ENV, "")
    if value:
        await_ended_timers(value)
    report = reclaim_test_run(value)
    if report["found"] or report.get("error"):
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        lines = [f"leftover test processes of {TEST_RUN_ENV}={value}: found={len(report['found'])} "
                 f"stopped={len(report['stopped'])} remaining={len(report['remaining'])}"
                 + (f" error={report['error']}" if report.get("error") else "")]
        lines += [f"  {item['pid']} {item['command']}" for item in report["found"]]
        for line in lines:
            if reporter is not None:
                reporter.write_line(line)
            else:
                print(line)
