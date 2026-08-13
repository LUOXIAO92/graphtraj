"""Alias-addressed follow-up operations for recoverable Engineer sessions."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict

import yaml

from .codex_adapter import read_codex_session_identity
from .runner_io import (
    ActiveTurnBusyError,
    ActiveTurnReservationError,
    active_turn_directory,
    active_turn_key,
    confirm_alias_mapping_durable,
    release_active_turn,
    reserve_active_turn,
    write_yaml_durably,
)
from .runner_models import RunnerError
from .runner_process import (
    OPERATION_TIMEOUT_SECONDS,
    process_is_alive,
    stop_worker,
)
from .runner_project import discover_runner_directory
from .runner_status import (
    read_alias_mapping,
    read_terminal_outcome,
    require_active_turn,
)
from .runtime_adapter import RuntimeAdapterError


LIVE_INPUT_GUIDANCE = (
    "This Runtime cannot accept input during a running turn. To intervene "
    "immediately, explicitly interrupt the alias and then send the instruction."
)
IMMUTABLE_MAPPING_FIELDS = (
    "alias",
    "runtime",
    "run_id",
    "ticket_id",
    "ticket_name",
    "role",
    "branch",
    "worktree_path",
    "ticket_file",
    "evidence_path",
)
SESSION_IDENTITY_READERS = {"codex": read_codex_session_identity}


def send_instruction(alias: str, instruction: str, cwd: Path) -> Dict[str, str]:
    """Resume one idle mapped Runtime session without changing its alias."""

    if not instruction.strip():
        raise RunnerError(
            "invalid-input", "instruction must be non-empty plain text."
        )
    runner_directory = discover_runner_directory(cwd)
    mapping, session_directory = read_alias_mapping(runner_directory, alias)
    turn_file = session_directory / "turn.yml"
    if not os.path.lexists(str(turn_file)):
        require_active_turn(runner_directory, alias, mapping)
        raise RunnerError("live-input-unsupported", LIVE_INPUT_GUIDANCE)
    read_terminal_outcome(turn_file)

    worktree = _mapped_worktree(mapping, runner_directory)
    key = _mapping_active_turn_key(mapping)
    request = _read_resume_request(session_directory, mapping)
    _attest_runtime_session(session_directory, mapping)
    try:
        reserve_active_turn(
            runner_directory,
            key,
            {
                "run_id": mapping["run_id"],
                "ticket_id": mapping["ticket_id"],
                "worktree_path": str(worktree),
                "alias": alias,
                "launcher_pid": os.getpid(),
            },
        )
    except ActiveTurnBusyError as error:
        raise RunnerError(
            "WORKTREE_TURN_ACTIVE",
            error.message,
        ) from error
    except ActiveTurnReservationError as error:
        raise RunnerError(
            "operation-failed",
            "The Ticket Worktree could not be reserved for an Engineer turn.",
        ) from error
    worker_started = False
    try:
        resume_file = session_directory / "resume.yml"
        write_yaml_durably(
            resume_file,
            {
                "operation": "resume",
                "runtime": mapping["runtime"],
                "adapter_request": request,
                "active_turn_key": key,
                "expected_session": mapping["session"],
                "mapping": mapping,
            },
        )
        error_file = session_directory / "resume-error.yml"
        error_file.unlink(missing_ok=True)
        worker_stderr = session_directory / "worker-stderr.log"
        with worker_stderr.open("w", encoding="utf-8") as diagnostics:
            worker = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "you_are_a_product_architect.runner_worker",
                    str(resume_file),
                ],
                cwd=worktree,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=diagnostics,
                text=True,
                start_new_session=True,
            )
            worker_started = True
            assert worker.stdin is not None
            worker.stdin.write(instruction)
            worker.stdin.close()
        _await_resumed_mapping(
            worker,
            session_directory,
            error_file,
            mapping["session"],
        )
    except RunnerError:
        if worker_started:
            stop_worker(worker.pid)
        else:
            release_active_turn(runner_directory, key)
        raise
    except (OSError, BrokenPipeError, yaml.YAMLError) as error:
        if worker_started:
            stop_worker(worker.pid)
        else:
            release_active_turn(runner_directory, key)
        raise RunnerError(
            "operation-failed",
            "The mapped Engineer session could not be resumed.",
        ) from error
    return {"alias": alias, "send_status": "sent"}


def interrupt_session(alias: str, cwd: Path) -> Dict[str, str]:
    """Stop only the active Runtime owned by one exact Engineer alias."""

    runner_directory = discover_runner_directory(cwd)
    mapping, session_directory = read_alias_mapping(runner_directory, alias)
    turn_file = session_directory / "turn.yml"
    if os.path.lexists(str(turn_file)):
        read_terminal_outcome(turn_file)
        raise RunnerError(
            "operation-failed",
            "The requested Engineer alias has no active turn to interrupt.",
        )
    require_active_turn(runner_directory, alias, mapping)
    key = _mapping_active_turn_key(mapping)
    try:
        os.kill(mapping["worker_pid"], signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError as error:
        raise RunnerError(
            "operation-failed",
            "The active Engineer turn could not be interrupted.",
        ) from error

    reservation = active_turn_directory(runner_directory, key)
    deadline = time.monotonic() + OPERATION_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if turn_file.is_file():
            outcome = read_terminal_outcome(turn_file)
            if (
                outcome == "interrupted"
                and not os.path.lexists(str(reservation))
                and not process_is_alive(mapping["worker_pid"])
            ):
                return {
                    "alias": alias,
                    "interrupt_status": "interrupted",
                }
            if outcome != "interrupted":
                break
        time.sleep(0.01)
    raise RunnerError(
        "operation-failed",
        "The active Engineer turn could not be confirmed interrupted.",
    )


def _mapped_worktree(
    mapping: Dict[str, Any], runner_directory: Path
) -> Path:
    worktree = Path(mapping["worktree_path"])
    if not worktree.is_absolute() or worktree.is_symlink() or not worktree.is_dir():
        raise _invalid_mapping()
    try:
        mapped_runner = discover_runner_directory(worktree)
    except RunnerError as error:
        raise _invalid_mapping() from error
    if mapped_runner != runner_directory:
        raise _invalid_mapping()
    return worktree


def _mapping_active_turn_key(mapping: Dict[str, Any]) -> str:
    try:
        return active_turn_key(mapping["ticket_id"])
    except UnicodeEncodeError as error:
        raise RunnerError(
            "operation-failed", "The requested Engineer alias mapping is invalid."
        ) from error


def _read_resume_request(
    session_directory: Path, mapping: Dict[str, Any]
) -> Dict[str, Any]:
    launch_file = session_directory / "launch.yml"
    if launch_file.is_symlink() or not launch_file.is_file():
        raise _not_resumable()
    try:
        launch = yaml.safe_load(launch_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise _not_resumable() from error
    if (
        not isinstance(launch, dict)
        or launch.get("runtime") != mapping["runtime"]
        or not isinstance(launch.get("adapter_request"), dict)
    ):
        raise _not_resumable()
    original_mapping = launch.get("mapping")
    request = launch["adapter_request"]
    if (
        not isinstance(original_mapping, dict)
        or any(
            original_mapping.get(field) != mapping[field]
            for field in IMMUTABLE_MAPPING_FIELDS
        )
        or launch.get("active_turn_key") != _mapping_active_turn_key(mapping)
        or request.get("worktree_path") != mapping["worktree_path"]
    ):
        raise _invalid_mapping()
    return request


def _attest_runtime_session(
    session_directory: Path, mapping: Dict[str, Any]
) -> None:
    reader = SESSION_IDENTITY_READERS.get(mapping["runtime"])
    if reader is None:
        raise _not_resumable()
    try:
        identity = reader(session_directory)
    except RuntimeAdapterError as error:
        raise _not_resumable() from error
    if identity != mapping["session"]:
        raise _invalid_mapping()


def _await_resumed_mapping(
    worker: subprocess.Popen[str],
    session_directory: Path,
    error_file: Path,
    expected_session: str,
) -> None:
    mapping_file = session_directory / "mapping.yml"
    deadline = time.monotonic() + OPERATION_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if error_file.is_file():
            raise _read_resume_error(error_file)
        try:
            mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            mapping = None
        if (
            isinstance(mapping, dict)
            and mapping.get("worker_pid") == worker.pid
            and mapping.get("session") == expected_session
        ):
            try:
                confirm_alias_mapping_durable(mapping_file)
            except OSError as error:
                raise RunnerError(
                    "operation-failed",
                    "The resumed Engineer session state could not be persisted.",
                ) from error
            return
        if worker.poll() is not None:
            raise _not_resumable()
        time.sleep(0.01)
    raise _not_resumable()


def _not_resumable() -> RunnerError:
    return RunnerError(
        "session-not-resumable",
        "The mapped Runtime session is unavailable or cannot be resumed.",
    )


def _read_resume_error(error_file: Path) -> RunnerError:
    try:
        failure = yaml.safe_load(error_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        failure = None
    if isinstance(failure, dict) and failure.get("code") in {
        "RUNTIME_REQUEST_INVALID",
        "RUNTIME_SESSION_MISSING",
        "RUNTIME_SESSION_NOT_RESUMABLE",
        "RUNTIME_START_FAILED",
    }:
        return _not_resumable()
    return RunnerError(
        "operation-failed",
        "The mapped Engineer session could not be resumed.",
    )


def _invalid_mapping() -> RunnerError:
    return RunnerError(
        "operation-failed", "The requested Engineer alias mapping is invalid."
    )
