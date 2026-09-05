"""Runtime-neutral background owner for one Engineer turn."""

from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path
from typing import Mapping

import yaml

from .codex_adapter import create_codex_resume_turn, create_codex_turn
from .delivery_worldline import append_worldline_event
from .runner_io import (
    ActiveTurnReservation,
    release_active_turn,
    write_active_turn_owner,
    write_yaml_durably,
)
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


def run(launch_file: Path) -> int:
    """Run either the current Session transport or retained legacy work."""

    try:
        launch = yaml.safe_load(launch_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        launch = None
    mapping = launch.get("mapping") if isinstance(launch, dict) else None
    if isinstance(mapping, dict) and "run_id" not in mapping:
        return _run_session(launch_file)
    return _run_legacy(launch_file)


def _run_legacy(launch_file: Path) -> int:
    session_directory = launch_file.parent
    runner_directory = session_directory.parent.parent
    active_turn: ActiveTurnReservation | None = None
    turn_handle: RuntimeTurn | None = None
    mapping_recorded = False
    terminal_turn: dict[str, object] | None = None
    terminal_persisted = False
    runtime_terminal = False
    interruption_confirmed = False
    operation = "launch"
    previous_sigterm = None
    turn_start_seq: int | None = None
    run_root: Path | None = None
    trace_ref: str | None = None

    def request_termination(signum: int, frame: object) -> None:
        nonlocal interruption_confirmed
        if turn_handle is not None and turn_handle.terminate():
            interruption_confirmed = True

    try:
        try:
            launch = yaml.safe_load(launch_file.read_text(encoding="utf-8"))
            if not isinstance(launch, dict):
                raise ValueError("launch document is not a mapping")
            active_turn = ActiveTurnReservation(
                key=launch["active_turn_key"],
                device=launch["active_turn_device"],
                inode=launch["active_turn_inode"],
                role=launch.get("active_turn_role"),
            )
            runtime = launch["runtime"]
            operation = launch.get("operation", "launch")
            if operation not in {"launch", "resume"}:
                raise ValueError("worker operation is invalid")
            adapter = ADAPTERS[runtime]
            request = launch["adapter_request"]
            base_mapping = launch["mapping"]
            if not isinstance(base_mapping, dict):
                raise ValueError("mapping is not a mapping")
            prompt = sys.stdin.read()
            run_root, trace_ref = _prepare_trace(session_directory, base_mapping)

            def record_session(session: str, runtime_pid: int) -> None:
                nonlocal mapping_recorded, turn_start_seq
                mapping = dict(base_mapping)
                mapping.update(
                    {
                        "session": session,
                        "worker_pid": os.getpid(),
                        "runtime_pid": runtime_pid,
                    }
                )
                assert run_root is not None
                started = append_worldline_event(
                    run_root,
                    str(base_mapping["run_id"]),
                    _worldline_turn_event("agent-turn-start", base_mapping),
                )
                turn_start_seq = started["worldline_seq"]
                if operation == "resume":
                    (session_directory / "turn.yml").unlink()
                assert active_turn is not None
                write_active_turn_owner(
                    runner_directory,
                    active_turn,
                    {"activity": "running", **mapping},
                )
                write_yaml_durably(session_directory / "mapping.yml", mapping)
                mapping_recorded = True

            if operation == "resume":
                expected_session = launch["expected_session"]
                resume_adapter = RESUME_ADAPTERS[runtime]
                turn_handle = resume_adapter(
                    request,
                    prompt,
                    expected_session,
                    session_directory,
                    record_session,
                )
            else:
                turn_handle = adapter(
                    request, prompt, session_directory, record_session
                )
            previous_sigterm = signal.signal(signal.SIGTERM, request_termination)
            turn = turn_handle.run()
            runtime_terminal = True
            terminal_turn = _terminal_turn(turn, interruption_confirmed)
        except RuntimeAdapterError as error:
            runtime_terminal = error.terminal_confirmed
            if not runtime_terminal and turn_handle is not None:
                turn_handle.terminate_until_terminal()
                runtime_terminal = True
            if mapping_recorded and runtime_terminal:
                terminal_turn = {
                    "outcome": (
                        "interrupted" if interruption_confirmed else "runtime-error"
                    )
                }
            else:
                _write_worker_error(
                    session_directory,
                    operation,
                    error.code,
                    error.message,
                    terminal_confirmed=runtime_terminal,
                )
        except (KeyError, OSError, TypeError, ValueError, yaml.YAMLError) as error:
            if turn_handle is not None:
                turn_handle.terminate_until_terminal()
                runtime_terminal = True
            if mapping_recorded and runtime_terminal:
                terminal_turn = {"outcome": "runtime-error"}
            else:
                _write_worker_error(
                    session_directory,
                    operation,
                    "RUNTIME_WORKER_FAILED",
                    "The internal Runtime worker could not own the Engineer turn.",
                    str(error),
                    terminal_confirmed=runtime_terminal,
                )
        if terminal_turn is not None:
            try:
                write_yaml_durably(session_directory / "turn.yml", terminal_turn)
                assert run_root is not None
                assert trace_ref is not None
                assert turn_start_seq is not None
                append_worldline_event(
                    run_root,
                    str(base_mapping["run_id"]),
                    {
                        **_worldline_turn_event(
                            "agent-turn-terminal", base_mapping
                        ),
                        **terminal_turn,
                        "trace_ref": trace_ref,
                        "caused_by_worldline_seqs": [turn_start_seq],
                    },
                )
                terminal_persisted = True
            except (OSError, yaml.YAMLError) as error:
                _write_worker_error(
                    session_directory,
                    operation,
                    "RUNTIME_WORKER_FAILED",
                    "The internal Runtime worker could not persist its terminal outcome.",
                    str(error),
                    terminal_confirmed=runtime_terminal,
                )
    finally:
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)
        if active_turn is not None and (terminal_persisted or runtime_terminal):
            release_active_turn(runner_directory, active_turn)
    return 0 if terminal_persisted else 1


def _run_session(job_file: Path) -> int:
    """Own one current Session execution without creating a Turn record."""

    session_directory = job_file.parent
    turn_handle: RuntimeTurn | None = None
    mapping_recorded = False
    terminal: dict[str, object] | None = None
    interrupted = False
    operation = "launch"
    previous_sigterm = None

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
                nonlocal mapping_recorded
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
            result = turn_handle.run()
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


def _prepare_trace(
    session_directory: Path, mapping: dict[str, object]
) -> tuple[Path, str]:
    evidence = mapping.get("evidence_path")
    alias = mapping.get("alias")
    turn = mapping.get("turn")
    if (
        not isinstance(evidence, str)
        or not isinstance(alias, str)
        or not isinstance(turn, int)
        or isinstance(turn, bool)
        or turn < 1
    ):
        raise ValueError("trace address is invalid")
    trace_directory = (
        Path(evidence) / "traces" / alias / "turn-{0}".format(turn)
    )
    trace_directory.mkdir(parents=True)
    trace_file = trace_directory / "events.jsonl"
    trace_file.touch(exist_ok=False)
    live_events = session_directory / "events.jsonl"
    live_events.unlink(missing_ok=True)
    os.link(trace_file, live_events)
    run_root = Path(evidence).parent.parent
    return run_root, trace_file.relative_to(run_root).as_posix()


def _worldline_turn_event(
    kind: str, mapping: Mapping[str, object]
) -> dict[str, object]:
    event = {
        "kind": kind,
        "ticket_id": mapping["ticket_id"],
        "role": mapping["role"],
        "alias": mapping["alias"],
        "turn": mapping["turn"],
    }
    review_round = mapping.get("review_round")
    if review_round is not None:
        event["review_round"] = review_round
    if kind == "agent-turn-start" and "caused_by_worldline_seqs" in mapping:
        event["caused_by_worldline_seqs"] = mapping[
            "caused_by_worldline_seqs"
        ]
    return event


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
