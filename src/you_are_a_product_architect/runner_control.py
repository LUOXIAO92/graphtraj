"""Alias-addressed follow-up operations for recoverable Engineer sessions."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Tuple

import yaml

from .codex_adapter import codex_connection_environment, read_codex_session_identity
from .delivery_worldline import read_worldline
from .project_configuration import ProjectConfigurationError, load_project_configuration
from .runner_io import (
    ActiveTurnBusyError,
    ActiveTurnReservation,
    active_turn_alias_released,
    active_turn_key,
    confirm_alias_mapping_durable,
    create_active_turn_reservation,
    release_active_turn,
    write_yaml_durably,
)
from .runner_models import RunnerError
from .runner_process import (
    OPERATION_TIMEOUT_SECONDS,
    process_is_alive,
    stop_worker,
)
from .runner_project import (
    configured_worktree_root,
    discover_runner_directory,
    registered_worktree_owns_branch,
)
from .runner_status import (
    is_session_mapping,
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
SESSION_IMMUTABLE_MAPPING_FIELDS = (
    "alias",
    "runtime",
    "ticket_id",
    "team_generation",
    "role",
    "parent",
    "retained_batch_file",
    "worktree_path",
    "trace_file",
)


def send_instruction(
    alias: str,
    instruction: str,
    cwd: Path,
    caused_by_event_ids: tuple[str, ...],
) -> Dict[str, str]:
    """Resume one idle mapped Runtime Session without changing its alias."""

    if not instruction.strip():
        raise RunnerError(
            "invalid-input", "instruction must be non-empty plain text."
        )
    if (
        not caused_by_event_ids
        or len(caused_by_event_ids) != len(set(caused_by_event_ids))
        or any(not event_id for event_id in caused_by_event_ids)
    ):
        raise RunnerError(
            "invalid-input", "causal Project Worldline event IDs must be unique."
        )
    runner_directory = discover_runner_directory(cwd)
    mapping, session_directory = read_alias_mapping(runner_directory, alias)
    if is_session_mapping(mapping):
        _require_project_events(cwd, caused_by_event_ids)
        return _send_session(
            alias,
            instruction,
            session_directory,
            mapping,
            caused_by_event_ids,
        )
    raise _not_resumable()


def _send_session(
    alias: str,
    instruction: str,
    session_directory: Path,
    mapping: Dict[str, Any],
    caused_by_event_ids: tuple[str, ...],
) -> Dict[str, str]:
    execution_file = session_directory / "execution.yml"
    if not os.path.lexists(str(execution_file)):
        if process_is_alive(mapping["worker_pid"]):
            raise RunnerError("live-input-unsupported", LIVE_INPUT_GUIDANCE)
        raise _not_resumable()
    read_terminal_outcome(execution_file)
    worktree = Path(mapping["worktree_path"])
    if not worktree.is_absolute() or worktree.is_symlink() or not worktree.is_dir():
        raise _invalid_mapping()
    request, connection = _read_session_resume_request(session_directory, mapping)
    _attest_runtime_session(session_directory, mapping)
    resume_file = session_directory / "resume.yml"
    error_file = session_directory / "resume-error.yml"
    error_file.unlink(missing_ok=True)
    try:
        write_yaml_durably(
            resume_file,
            {
                "operation": "resume",
                "runtime": mapping["runtime"],
                "adapter_request": request,
                "expected_session": mapping["session"],
                "caused_by_event_ids": list(caused_by_event_ids),
                "mapping": {
                    key: value
                    for key, value in mapping.items()
                    if key not in {"worker_pid", "runtime_pid"}
                },
            },
        )
        worker_environment = dict(os.environ)
        worker_environment.update(_resume_environment(mapping, connection))
        with (session_directory / "worker-stderr.log").open(
            "w", encoding="utf-8"
        ) as diagnostics:
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
                env=worker_environment,
            )
            assert worker.stdin is not None
            worker.stdin.write(instruction)
            worker.stdin.close()
        _await_session_resume(worker, session_directory, error_file, mapping["session"])
    except RunnerError:
        if "worker" in locals():
            stop_worker(worker.pid)
        raise
    except (OSError, BrokenPipeError, yaml.YAMLError) as error:
        if "worker" in locals():
            stop_worker(worker.pid)
        raise RunnerError(
            "operation-failed", "The mapped Runtime session could not be resumed."
        ) from error
    return {"alias": alias, "send_status": "sent"}


def send_legacy_instruction(
    alias: str,
    instruction: str,
    cwd: Path,
    caused_by_worldline_seqs: tuple[int, ...],
) -> Dict[str, str]:
    """Resume one retained legacy mapped Runtime session."""

    if not instruction.strip():
        raise RunnerError(
            "invalid-input", "instruction must be non-empty plain text."
        )
    if len(caused_by_worldline_seqs) != len(set(caused_by_worldline_seqs)):
        raise RunnerError(
            "invalid-input", "causal Worldline sequences must be unique."
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
    request, connection = _read_resume_request(session_directory, mapping)
    _attest_runtime_session(session_directory, mapping)
    worker_environment = dict(os.environ)
    worker_environment.update(_resume_environment(mapping, connection))
    try:
        reservation = create_active_turn_reservation(
            runner_directory,
            mapping["ticket_id"],
            {
                "run_id": mapping["run_id"],
                "ticket_id": mapping["ticket_id"],
                "worktree_path": str(worktree),
                "alias": alias,
                "role": mapping["role"],
                "launcher_pid": os.getpid(),
            },
        )
    except ActiveTurnBusyError as error:
        raise RunnerError(
            "WORKTREE_TURN_ACTIVE",
            error.message,
        ) from error
    except (OSError, ValueError, yaml.YAMLError) as error:
        raise RunnerError(
            "operation-failed",
            "The Ticket Worktree could not be reserved for an Engineer turn.",
        ) from error
    worker_started = False
    try:
        resume_file = session_directory / "resume.yml"
        turn = mapping.get("turn")
        if not isinstance(turn, int) or isinstance(turn, bool) or turn < 1:
            raise _invalid_mapping()
        write_yaml_durably(
            resume_file,
            {
                "operation": "resume",
                "runtime": mapping["runtime"],
                "adapter_request": request,
                "active_turn_key": key,
                "active_turn_device": reservation.device,
                "active_turn_inode": reservation.inode,
                "active_turn_role": reservation.role,
                "expected_session": mapping["session"],
                "mapping": {
                    **mapping,
                    "turn": turn + 1,
                    "caused_by_worldline_seqs": list(caused_by_worldline_seqs),
                },
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
                env=worker_environment,
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
            release_active_turn(runner_directory, reservation)
        raise
    except (OSError, BrokenPipeError, yaml.YAMLError) as error:
        if worker_started:
            stop_worker(worker.pid)
        else:
            release_active_turn(runner_directory, reservation)
        raise RunnerError(
            "operation-failed",
            "The mapped Engineer session could not be resumed.",
        ) from error
    return {"alias": alias, "send_status": "sent"}


def interrupt_session(alias: str, cwd: Path) -> Dict[str, str]:
    """Interrupt one exact running Runtime Session by alias."""

    runner_directory = discover_runner_directory(cwd)
    mapping, session_directory = read_alias_mapping(runner_directory, alias)
    if is_session_mapping(mapping):
        return _interrupt_session(alias, session_directory, mapping)
    return _interrupt_legacy_session(alias, cwd)


def _interrupt_session(
    alias: str, session_directory: Path, mapping: Dict[str, Any]
) -> Dict[str, str]:
    execution_file = session_directory / "execution.yml"
    if os.path.lexists(str(execution_file)):
        read_terminal_outcome(execution_file)
        raise RunnerError(
            "operation-failed",
            "The requested Session has no active Runtime execution to interrupt.",
        )
    if not process_is_alive(mapping["worker_pid"]):
        raise _not_resumable()
    try:
        os.kill(mapping["worker_pid"], signal.SIGTERM)
    except ProcessLookupError:
        raise _not_resumable() from None
    except OSError as error:
        raise RunnerError(
            "operation-failed",
            "The active Runtime execution could not be interrupted.",
        ) from error
    deadline = time.monotonic() + OPERATION_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if execution_file.is_file():
            outcome = read_terminal_outcome(execution_file)
            if outcome == "interrupted" and not process_is_alive(mapping["worker_pid"]):
                return {"alias": alias, "interrupt_status": "interrupted"}
            if outcome != "interrupted":
                break
        time.sleep(0.01)
    raise RunnerError(
        "operation-failed",
        "The active Runtime execution could not be confirmed interrupted.",
    )


def _interrupt_legacy_session(alias: str, cwd: Path) -> Dict[str, str]:
    """Stop only the active Runtime owned by one retained legacy alias."""

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

    deadline = time.monotonic() + OPERATION_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if turn_file.is_file():
            outcome = read_terminal_outcome(turn_file)
            if (
                outcome == "interrupted"
                and active_turn_alias_released(runner_directory, key, alias)
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


def _require_project_events(cwd: Path, event_ids: tuple[str, ...]) -> None:
    try:
        configuration = load_project_configuration(cwd)
        known_ids = {
            event["event_id"]
            for event in read_worldline(
                configuration.state, configuration.harness_root
            )
        }
    except (OSError, ValueError, ProjectConfigurationError) as error:
        raise RunnerError(
            "operation-failed", "The Project Worldline could not be read."
        ) from error
    if any(event_id not in known_ids for event_id in event_ids):
        raise RunnerError(
            "invalid-input",
            "causal Project Worldline event IDs must identify retained events.",
        )


def _read_session_resume_request(
    session_directory: Path, mapping: Dict[str, Any]
) -> Tuple[Dict[str, Any], Dict[str, str]]:
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
        or not isinstance(launch.get("connection"), dict)
        or not isinstance(launch.get("mapping"), dict)
        or any(
            launch["mapping"].get(field) != mapping[field]
            for field in SESSION_IMMUTABLE_MAPPING_FIELDS
        )
        or launch["adapter_request"].get("worktree_path")
        != mapping["worktree_path"]
    ):
        raise _invalid_mapping()
    connection = launch["connection"]
    if any(
        key not in {"base_url", "api_key_env"}
        or not isinstance(value, str)
        or not value
        for key, value in connection.items()
    ):
        raise _invalid_mapping()
    return launch["adapter_request"], connection


def _await_session_resume(
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
            and is_session_mapping(mapping)
            and mapping.get("worker_pid") == worker.pid
            and mapping.get("session") == expected_session
        ):
            try:
                confirm_alias_mapping_durable(mapping_file)
            except OSError as error:
                raise RunnerError(
                    "operation-failed",
                    "The resumed Session mapping could not be persisted.",
                ) from error
            return
        if worker.poll() is not None:
            raise _not_resumable()
        time.sleep(0.01)
    raise _not_resumable()


def _resume_environment(
    mapping: Dict[str, Any],
    connection: Dict[str, str],
) -> Dict[str, str]:
    """Resolve one resume environment from the immutable launch Context."""
    if mapping.get("runtime") == "codex":
        return dict(
            codex_connection_environment(
                connection.get("base_url"), connection.get("api_key_env")
            )
        )
    raise _not_resumable()


def _mapped_worktree(
    mapping: Dict[str, Any], runner_directory: Path
) -> Path:
    worktree = Path(mapping["worktree_path"])
    encoded_id = mapping["ticket_id"].replace(".", "%2E")
    ticket_stem = "{0}-{1}-{2}".format(
        len(mapping["ticket_id"]), encoded_id, mapping["ticket_name"]
    )
    expected_branch = "agent/{0}/{1}".format(mapping["run_id"], ticket_stem)
    try:
        worktree_root = configured_worktree_root(runner_directory)
        expected_worktree = (
            worktree_root / "runs" / mapping["run_id"] / ticket_stem
        ).resolve()
    except (OSError, RunnerError) as error:
        raise _invalid_mapping() from error
    if (
        not worktree.is_absolute()
        or worktree.is_symlink()
        or not worktree.is_dir()
        or worktree.resolve() != expected_worktree
        or mapping["branch"] != expected_branch
        or not mapping["alias"].startswith("{0}@".format(ticket_stem))
    ):
        raise _invalid_mapping()
    try:
        owns_branch = registered_worktree_owns_branch(worktree, mapping["branch"])
    except RunnerError as error:
        raise _invalid_mapping() from error
    if not owns_branch:
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
) -> Tuple[Dict[str, Any], Dict[str, str]]:
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
    connection = launch.get("connection")
    if (
        not isinstance(original_mapping, dict)
        or not isinstance(connection, dict)
        or any(key not in {"base_url", "api_key_env"} for key in connection)
        or any(
            not isinstance(value, str) or not value
            for value in connection.values()
        )
        or any(
            original_mapping.get(field) != mapping[field]
            for field in IMMUTABLE_MAPPING_FIELDS
        )
        or launch.get("active_turn_key") != _mapping_active_turn_key(mapping)
        or request.get("worktree_path") != mapping["worktree_path"]
    ):
        raise _invalid_mapping()
    return request, connection


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
        "PROJECT_CONFIG_MISMATCH",
        "ROLE_GUARD_MISMATCH",
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
