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
"""

from __future__ import annotations

import os
import uuid

import pytest

from graftling.member_processes import ancestor_pids, stop_marked_processes

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
    value = value or os.environ.get(TEST_RUN_ENV, "")
    return stop_marked_processes(value, exclude=ancestor_pids(), variable=TEST_RUN_ENV)


def pytest_configure(config: pytest.Config) -> None:
    mark_test_run()


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session) -> None:
    value = os.environ.get(TEST_RUN_ENV, "")
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
