"""Runtime-neutral background owner for one Session execution."""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Mapping

import yaml

from .codex_adapter import create_codex_resume_turn, create_codex_turn
from .execution_budget import (
    ExecutionBudgetMonitor,
    execution_budget_monitor_from_environment,
    execution_budget_stage,
)
from .runner_io import write_yaml_durably
from .runner_transport import runtime_launch_failure
from .runtime_adapter import (
    ResumeRuntimeAdapter,
    RuntimeAdapter,
    RuntimeAdapterError,
    RuntimeTurn,
)


ADAPTERS: Mapping[str, RuntimeAdapter] = {"codex": create_codex_turn}
RESUME_ADAPTERS: Mapping[str, ResumeRuntimeAdapter] = {
    "codex": create_codex_resume_turn
}


def run(job_file: Path) -> int:
    """Own one current Session execution without creating a Turn record."""

    session_directory = job_file.parent
    turn_handle: RuntimeTurn | None = None
    mapping_recorded = False
    terminal: dict[str, object] | None = None
    interrupted = False
    operation = "launch"
    previous_sigterm = None
    budget_monitor: ExecutionBudgetMonitor | None = None
    monitor_stop: threading.Event | None = None
    monitor_thread: threading.Thread | None = None
    deliver_parentless_leader_notices = False
    leader_notice_keys: list[str] = []

    def request_termination(signum: int, frame: object) -> None:
        nonlocal interrupted
        if turn_handle is not None and turn_handle.terminate():
            interrupted = True

    try:
        try:
            job = yaml.safe_load(job_file.read_text(encoding="utf-8"))
            if not isinstance(job, dict):
                raise ValueError("session job is not a mapping")
            operation = job.get("operation", "launch")
            if operation not in {"launch", "resume"}:
                raise ValueError("session operation is invalid")
            runtime = job["runtime"]
            request = job["adapter_request"]
            base_mapping = job["mapping"]
            if not isinstance(base_mapping, dict):
                raise ValueError("session mapping is not a mapping")
            monitor_execution_budget = job.get("monitor_execution_budget", False)
            if not isinstance(monitor_execution_budget, bool):
                raise ValueError("budget monitor request is invalid")
            deliver_parentless_leader_notices = job.get(
                "deliver_parentless_leader_notices", False
            )
            if not isinstance(deliver_parentless_leader_notices, bool):
                raise ValueError("Leader budget notice request is invalid")
            leader_notice_keys = job.get("leader_notice_keys", [])
            if (
                not isinstance(leader_notice_keys, list)
                or len(leader_notice_keys) != len(set(leader_notice_keys))
                or any(
                    not isinstance(key, str) or not key
                    for key in leader_notice_keys
                )
            ):
                raise ValueError("Leader budget notice keys are invalid")
            if monitor_execution_budget:
                budget_monitor = execution_budget_monitor_from_environment(
                    base_mapping
                )
                if budget_monitor is not None:
                    role = base_mapping.get("role")
                    if not isinstance(role, str) or not role:
                        raise ValueError("session role is invalid")
                    monitor_stop = threading.Event()
            prompt = sys.stdin.read()
            expected_session = job.get("expected_session")
            if operation == "resume" and (
                not isinstance(expected_session, str) or not expected_session
            ):
                raise ValueError("resumed Session has no expected Runtime session")
            causes = job.get("caused_by_event_ids", [])
            if (
                not isinstance(causes, list)
                or any(not isinstance(cause, str) or not cause for cause in causes)
                or len(causes) != len(set(causes))
            ):
                raise ValueError("follow-up causes are invalid")
            adapter = ADAPTERS[runtime]

            def record_session(session: str, runtime_pid: int) -> None:
                nonlocal mapping_recorded, monitor_thread
                if operation == "resume" and session != expected_session:
                    raise RuntimeAdapterError(
                        "RUNTIME_SESSION_NOT_RESUMABLE",
                        "The mapped Runtime session could not be resumed.",
                    )
                previous_outcome = _previous_outcome(
                    session_directory / "execution.yml"
                )
                mapping = {
                    **{
                        key: value
                        for key, value in base_mapping.items()
                        if key != "last_outcome"
                    },
                    "session": session,
                    "worker_pid": os.getpid(),
                    "runtime_pid": runtime_pid,
                }
                if previous_outcome is not None:
                    mapping["last_outcome"] = previous_outcome
                if causes:
                    _append_follow_up(session_directory / "events.jsonl", causes)
                (session_directory / "execution.yml").unlink(missing_ok=True)
                write_yaml_durably(session_directory / "mapping.yml", mapping)
                mapping_recorded = True
                if budget_monitor is not None and leader_notice_keys:
                    budget_monitor.mark_leader_notices_delivered(
                        leader_notice_keys
                    )
                if (
                    budget_monitor is not None
                    and monitor_stop is not None
                    and monitor_thread is None
                ):
                    monitor_thread = threading.Thread(
                        target=_monitor_execution_budget,
                        args=(
                            budget_monitor,
                            mapping,
                            monitor_stop,
                            deliver_parentless_leader_notices,
                        ),
                        daemon=True,
                    )
                    monitor_thread.start()

            if operation == "resume":
                turn_handle = RESUME_ADAPTERS[runtime](
                    request,
                    prompt,
                    expected_session,
                    session_directory,
                    record_session,
                )
            else:
                turn_handle = adapter(
                    request,
                    prompt,
                    session_directory,
                    record_session,
                )
            previous_sigterm = signal.signal(signal.SIGTERM, request_termination)
            try:
                result = turn_handle.run()
            finally:
                if monitor_stop is not None:
                    monitor_stop.set()
                if monitor_thread is not None:
                    monitor_thread.join()
            terminal = _terminal_turn(result, interrupted)
        except RuntimeAdapterError as error:
            if mapping_recorded:
                terminal = {"outcome": "interrupted" if interrupted else "runtime-error"}
            else:
                _write_worker_error(
                    session_directory,
                    operation,
                    error.code,
                    error.message,
                    terminal_confirmed=error.terminal_confirmed,
                )
        except (KeyError, OSError, TypeError, ValueError, yaml.YAMLError) as error:
            if mapping_recorded:
                terminal = {"outcome": "runtime-error"}
            else:
                _write_worker_error(
                    session_directory,
                    operation,
                    "RUNTIME_WORKER_FAILED",
                    "The internal Runtime worker could not own the Session.",
                    str(error),
                    terminal_confirmed=turn_handle is None or turn_handle.terminate(),
                )
        if terminal is not None:
            write_yaml_durably(session_directory / "execution.yml", terminal)
            if (
                budget_monitor is not None
                and deliver_parentless_leader_notices
                and base_mapping.get("role") == "team-leader"
                and base_mapping.get("parent") is None
            ):
                notices = budget_monitor.pending_leader_notices()
                if notices:
                    from .runner_control import _send_session

                    mapping = yaml.safe_load(
                        (session_directory / "mapping.yml").read_text(
                            encoding="utf-8"
                        )
                    )
                    stopped = budget_monitor.is_stopped()
                    _send_session(
                        mapping["alias"],
                        (
                            "Execution has stopped. Freeze the current scene and "
                            "report the current result and remaining work. Do not "
                            "dispatch or decide acceptance."
                            if stopped
                            else "\n".join(
                                notice["message"] for notice in notices
                            )
                            + "\nReceive these system notices, then continue the "
                            "interrupted instruction below.\n"
                            + prompt
                        ),
                        session_directory,
                        mapping,
                        (),
                        Path(os.environ["GRAPHTRAJ_HARNESS_ROOT"]),
                        leader_notice_keys=(
                            ()
                            if stopped
                            else tuple(notice["key"] for notice in notices)
                        ),
                        capacity_fd=int(os.environ["GRAPHTRAJ_CAPACITY_FD"]),
                    )
            return 0
    finally:
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)
    return 1


def _append_follow_up(events_file: Path, causes: list[str]) -> None:
    with events_file.open("a", encoding="utf-8") as events:
        events.write(
            json.dumps(
                {"type": "runner-follow-up", "caused_by_event_ids": causes},
                separators=(",", ":"),
            )
            + "\n"
        )
        events.flush()
        os.fsync(events.fileno())


def _monitor_execution_budget(
    monitor: ExecutionBudgetMonitor,
    mapping: dict[str, object],
    stop: threading.Event,
    deliver_parentless_leader_notices: bool,
) -> None:
    role = mapping["role"]
    assert isinstance(role, str)

    def deliver(messages: list[str]) -> None:
        parent = mapping.get("parent")
        harness_root = os.environ.get("GRAPHTRAJ_HARNESS_ROOT")
        if not isinstance(parent, str) or not isinstance(harness_root, str):
            return
        from .runner_control import _send_session

        trace_file = mapping.get("trace_file")
        if not isinstance(trace_file, str):
            return
        parent_directory = Path(trace_file).parent.parent / parent
        parent_mapping = yaml.safe_load(
            (parent_directory / "mapping.yml").read_text(encoding="utf-8")
        )
        while not (parent_directory / "execution.yml").is_file():
            time.sleep(0.05)
        _send_session(
            parent,
            "\n".join(messages)
            + "\nReceive these system notices. Do not dispatch work or make a Team decision.",
            parent_directory,
            parent_mapping,
            (),
            Path(harness_root),
            budget_notice=True,
        )

    while not stop.is_set():
        stopped = monitor.check(role, execution_budget_stage(role))
        if isinstance(mapping.get("parent"), str):
            monitor.deliver_leader_notices(deliver)
        elif (
            deliver_parentless_leader_notices
            and role == "team-leader"
            and monitor.pending_leader_notices()
        ):
            os.kill(os.getpid(), signal.SIGTERM)
            return
        if stopped and (role.startswith("engineer-") or role == "team-leader"):
            os.kill(os.getpid(), signal.SIGTERM)
            return
        stop.wait(0.05)


def _previous_outcome(execution_file: Path) -> str | None:
    if not os.path.lexists(str(execution_file)):
        return None
    if execution_file.is_symlink() or not execution_file.is_file():
        raise ValueError("Session terminal outcome is invalid")
    outcome = yaml.safe_load(execution_file.read_text(encoding="utf-8"))
    if not isinstance(outcome, dict) or outcome.get("outcome") not in {
        "completed",
        "interrupted",
        "runtime-error",
    }:
        raise ValueError("Session terminal outcome is invalid")
    return outcome["outcome"]


def _terminal_turn(turn: object, interrupted: bool) -> dict[str, object]:
    if not isinstance(turn, dict):
        raise ValueError("Runtime turn result is not a mapping")
    outcome = turn.get("outcome")
    if outcome not in {"completed", "runtime-error"}:
        raise ValueError("Runtime turn result has an invalid outcome")
    terminal = {"outcome": "interrupted" if interrupted else outcome}
    exit_code = turn.get("runtime_exit_code")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        terminal["runtime_exit_code"] = exit_code
    return terminal


def _write_worker_error(
    session_directory: Path,
    operation: str,
    code: str,
    message: str,
    diagnostic: str = "",
    *,
    terminal_confirmed: bool,
) -> None:
    failure = runtime_launch_failure(
        code,
        message,
        diagnostic,
        terminal_confirmed=terminal_confirmed,
    )
    name = "resume-error.yml" if operation == "resume" else "launch-error.yml"
    write_yaml_durably(session_directory / name, failure)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(2)
    raise SystemExit(run(Path(sys.argv[1])))


if __name__ == "__main__":
    main()
