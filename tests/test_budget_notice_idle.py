"""An idle timed Session's elapsed threshold is delivered without a new execution (445)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from graphtraj.execution import budget_idle_timer as timers
from graphtraj.execution import runner_control, runner_status
from graphtraj.execution.execution_budget import ExecutionBudgetMonitor
from graphtraj.execution.runner_heartbeat import hold_ownership, write_heartbeat
from test_execution_budgets import _budget_body

ROOT_CONNECTION = {"runtime": "claude", "connection": "main"}


class Clock:
    """A test clock: sleeping advances time instantly."""

    def __init__(self, now: float) -> None:
        self.now = now
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def team(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A Task with a 1-minute budget, an idle Leader under Main and its idle Engineer."""
    task = tmp_path / "task"
    task.mkdir()
    (task / "task.md").write_text(_budget_body(total=1))
    (task / "task.yml").write_text(yaml.safe_dump({"current_definition": "task.md"}))
    runner = tmp_path / "runner"
    mappings = {
        "leader-1": {"alias": "leader-1", "task_id": "445", "role": "team_leader",
                     "parent": None, "parent_connection": ROOT_CONNECTION},
        "engineer-1": {"alias": "engineer-1", "task_id": "445", "role": "engineer",
                       "parent": "leader-1"},
    }
    for alias, mapping in mappings.items():
        directory = runner / "sessions" / alias
        directory.mkdir(parents=True)
        (directory / "mapping.yml").write_text(yaml.safe_dump(mapping))
    received: list[tuple[str, str, dict]] = []

    def notify(directory: Path, message: str, event: dict, **_: object) -> dict:
        received.append((directory.name, message, event))
        return {"delivery": "received"}

    def read(runner_directory: Path, alias: str):
        return mappings[alias], runner_directory / "sessions" / alias

    monkeypatch.setattr(runner_control, "notify_direct_parent", notify)
    monkeypatch.setattr(runner_status, "read_alias_mapping", read)

    def monitor(alias: str) -> ExecutionBudgetMonitor:
        observer = ExecutionBudgetMonitor(task, "445", "budget-notice-idle-timed-leader")
        observer.observer = alias
        return observer

    # The ended execution's start observed the budget once, as the Worker does.
    monitor("leader-1").check("team_leader", "team_leader")
    return task, runner, monitor, received


def _state(task: Path) -> dict:
    return yaml.safe_load((task / "execution-budget.yml").read_text())


def _run(runner: Path, alias: str, monitor, clock: Clock, token: str = "t1", **kwargs) -> bool:
    directory = runner / "sessions" / alias
    (directory / timers.TIMER_FILE_NAME).write_text(yaml.safe_dump({"token": token}))
    role = "team_leader" if alias.startswith("leader") else "engineer"
    return timers.run_idle_budget_timer(directory, token, monitor(alias), role,
                                        clock=clock, sleep=clock.sleep, **kwargs)


def test_idle_leader_planned_end_reaches_main_once_without_an_execution(team, monkeypatch) -> None:
    task, runner, monitor, received = team
    state = _state(task)
    assert state["notifications"] == []
    planned_end = state["started_at"] + 60
    assert monitor("leader-1").next_elapsed_threshold_at() == pytest.approx(planned_end)
    clock = Clock(state["started_at"] + 5)
    # check() reads the wall clock; the test clock stands in for it.
    monkeypatch.setattr(timers.time, "time", clock)
    delivered_at = []
    original = runner_control.notify_direct_parent

    def notify(*args, **kwargs):
        delivered_at.append(clock.now)
        return original(*args, **kwargs)

    monkeypatch.setattr(runner_control, "notify_direct_parent", notify)
    assert _run(runner, "leader-1", monitor, clock) is True
    assert all(step <= timers.SLICE_SECONDS for step in clock.slept)
    # Each notice goes once to the Leader's direct parent: Main via parent_connection.
    keys = [event["key"] for _, _, event in received]
    assert keys[0] == "elapsed_minutes:1" and keys[1].startswith("additional_allowance:")
    assert len(keys) == 2 and {alias for alias, _, _ in received} == {"leader-1"}
    assert planned_end <= delivered_at[0] <= planned_end + timers.MARGIN_SECONDS + 1
    assert "planned budget of 00:01:00 has been reached" in received[0][1]
    assert all(notice["observer"] == "leader-1" and notice["delivered"]
               for notice in _state(task)["parent_notices"])
    assert monitor("leader-1").next_elapsed_threshold_at() is None
    # A later execution start observes again and delivers nothing new.
    monitor("leader-1").check("team_leader", "team_leader")
    monitor("leader-1").deliver_parent_notices(runner / "sessions" / "leader-1")
    assert len(received) == 2
    # Even a late timer never samples a stop; running executions keep that.
    clock.now += 3600
    monitor("leader-1").check_elapsed("team_leader", "team_leader")
    assert _state(task)["stopping_checks"] == 0 and _state(task)["stopped"] is False


def test_idle_engineer_planned_end_reaches_its_leader(team, monkeypatch) -> None:
    task, runner, monitor, received = team
    clock = Clock(_state(task)["started_at"])
    monkeypatch.setattr(timers.time, "time", clock)
    assert _run(runner, "engineer-1", monitor, clock) is True
    # notify_direct_parent addresses the observer's own direct parent (the Leader).
    assert [event["key"] for _, _, event in received][0] == "elapsed_minutes:1"
    assert {alias for alias, _, _ in received} == {"engineer-1"}
    assert all(notice["observer"] == "engineer-1" and notice["delivered"]
               for notice in _state(task)["parent_notices"])
    # The Leader's timer finds nothing of its own to deliver.
    assert _run(runner, "leader-1", monitor, clock) is False
    assert len(received) == 2


def test_timer_exits_while_a_new_execution_runs_or_after_replacement(team, tmp_path) -> None:
    task, runner, monitor, received = team
    directory = runner / "sessions" / "leader-1"
    clock = Clock(_state(task)["started_at"])
    # A later Worker owns the Session again: its own monitor observes the budget.
    owner = hold_ownership(directory, os.getpid())
    write_heartbeat(directory, {"alias": "leader-1", "worker_pid": os.getpid()})
    try:
        assert _run(runner, "leader-1", monitor, clock) is False
        # The ending Worker's own ownership does not count as a running execution
        # until it passes; the replaced token makes the timer exit instead.
        (directory / timers.TIMER_FILE_NAME).write_text(yaml.safe_dump({"token": "newer"}))
        assert timers.run_idle_budget_timer(
            directory, "t1", monitor("leader-1"), "team_leader", ended_worker=os.getpid(),
            clock=clock, sleep=clock.sleep) is False
    finally:
        owner.close()
    assert received == [] and _state(task)["notifications"] == []


def test_timer_delivers_nothing_while_the_task_is_stopped(team) -> None:
    task, runner, monitor, received = team
    state = _state(task)
    state["stopped"] = True
    (task / "execution-budget.yml").write_text(yaml.safe_dump(state))
    clock = Clock(state["started_at"] + 3600)
    assert monitor("leader-1").next_elapsed_threshold_at() is None
    assert _run(runner, "leader-1", monitor, clock) is False
    assert received == [] and _state(task)["notifications"] == []


def test_timer_exits_after_cleanup_removes_the_session(team) -> None:
    import shutil

    task, runner, monitor, received = team
    directory = runner / "sessions" / "leader-1"
    clock = Clock(_state(task)["started_at"])
    shutil.rmtree(directory)
    assert timers.run_idle_budget_timer(directory, "t1", monitor("leader-1"), "team_leader",
                                        clock=clock, sleep=clock.sleep) is False
    assert received == []


def test_ended_execution_starts_one_detached_timer_and_a_newer_one_replaces_it(
        team, monkeypatch) -> None:
    task, runner, monitor, received = team
    directory = runner / "sessions" / "leader-1"
    started = []
    monkeypatch.setattr(timers.subprocess, "Popen", lambda argv, **kwargs: started.append((argv, kwargs)))
    first = timers.start_idle_budget_timer(directory, monitor("leader-1"))
    second = timers.start_idle_budget_timer(directory, monitor("leader-1"))
    assert first and second and first != second
    assert timers._current_token(directory) == second
    argv, kwargs = started[0]
    assert argv[1:5] == ["-I", "-m", "graphtraj.execution.budget_idle_timer", str(directory)]
    assert argv[5] == first and argv[6] == str(os.getpid())
    # Detached from the Worker: own session, no inherited streams.
    assert kwargs["start_new_session"] is True and kwargs["stdin"] is timers.subprocess.DEVNULL
    # Nothing ahead: no timer.
    state = _state(task)
    state["stopped"] = True
    (task / "execution-budget.yml").write_text(yaml.safe_dump(state))
    assert timers.start_idle_budget_timer(directory, monitor("leader-1")) is None
    assert len(started) == 2
    # The timer drops only the member marker; the test-run marker survives (454).
    assert timers.MEMBER_RUN_ENV not in kwargs["env"]
    assert kwargs["env"].get("PYTEST_GRAPHTRAJ_RUN") == os.environ.get("PYTEST_GRAPHTRAJ_RUN")


def test_timer_life_ends_at_the_last_threshold(team, monkeypatch) -> None:
    """Even with the Session directory kept, waiting never passes the last threshold (454)."""
    task, runner, monitor, received = team
    state = _state(task)
    clock = Clock(state["started_at"])
    monkeypatch.setattr(timers.time, "time", clock)
    assert _run(runner, "leader-1", monitor, clock) is True
    last = state["started_at"] + (1 + state["allowance_minutes"]) * 60
    assert clock.now <= last + timers.MARGIN_SECONDS + timers.SLICE_SECONDS
    assert monitor("leader-1").next_elapsed_threshold_at() is None


def test_timer_exits_after_the_task_directory_is_removed(team) -> None:
    import shutil

    task, runner, monitor, received = team
    clock = Clock(_state(task)["started_at"])
    observer = monitor("leader-1")
    shutil.rmtree(task)
    assert _run(runner, "leader-1", lambda alias: observer, clock) is False
    assert received == [] and clock.slept == []


def test_a_delivery_that_never_returns_ends_the_timer(team, monkeypatch) -> None:
    """A parent lock or connection that never answers bounds the timer; the notice stays (454)."""
    import time as real_time

    task, runner, monitor, received = team
    clock = Clock(_state(task)["started_at"] + 3600)
    monkeypatch.setattr(timers.time, "time", clock)
    monkeypatch.setattr(runner_control, "notify_direct_parent",
                        lambda *args, **kwargs: real_time.sleep(60))
    started = real_time.monotonic()
    assert _run(runner, "leader-1", monitor, clock, delivery_seconds=0.5) is False
    assert real_time.monotonic() - started < 10
    assert _state(task)["parent_notices"] and not any(
        notice["delivered"] for notice in _state(task)["parent_notices"])
    assert timers.DELIVERY_SECONDS > 0
