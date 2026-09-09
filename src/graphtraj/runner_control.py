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

from .codex_adapter import (
    codex_connection_environment,
    read_codex_session_identity,
    refresh_codex_report_paths,
)
from .delivery_worldline import read_worldline
from .project_configuration import ProjectConfigurationError, load_project_configuration
from .runner_io import confirm_alias_mapping_durable, write_yaml_durably
from .runner_capacity import capacity_positions
from .runner_models import RunnerError
from .runner_process import (
    OPERATION_TIMEOUT_SECONDS,
    process_is_alive,
    stop_worker,
)
from .runner_project import discover_project, discover_runner_directory
from .runner_status import (
    is_session_mapping,
    read_alias_mapping,
    read_terminal_outcome,
)
from .runtime_adapter import RuntimeAdapterError


LIVE_INPUT_GUIDANCE = (
    "This Runtime cannot accept input during a running Runtime execution. To intervene "
    "immediately, explicitly interrupt the alias and then send the instruction."
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
        from .team_replacement import require_active_session

        require_active_session(discover_project(cwd), alias)
        return _send_session(
            alias,
            instruction,
            session_directory,
            mapping,
            caused_by_event_ids,
            cwd,
        )
    raise _not_resumable()


def _send_session(
    alias: str,
    instruction: str,
    session_directory: Path,
    mapping: Dict[str, Any],
    caused_by_event_ids: tuple[str, ...],
    cwd: Path,
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
    team_environment = _team_runtime_environment(mapping, cwd)
    request = _refresh_current_team_report_request(
        request, mapping, worktree, team_environment
    )
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
        worker_environment.update(team_environment)
        if mapping["role"] == "team-leader":
            worker_environment.update(
                GRAPHTRAJ_PARENT_ALIAS=alias,
                GRAPHTRAJ_PARENT_REGISTRATION=str(session_directory / "child-registration.yml"),
            )
        with capacity_positions(load_project_configuration(cwd), 1) as positions:
            with (session_directory / "worker-stderr.log").open(
                "w", encoding="utf-8"
            ) as diagnostics:
                worker = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "graphtraj.runner_worker",
                        str(resume_file),
                    ],
                    cwd=worktree,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=diagnostics,
                    text=True,
                    start_new_session=True,
                    env=worker_environment,
                    pass_fds=(positions[0].fileno(),),
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


def interrupt_session(alias: str, cwd: Path) -> Dict[str, str]:
    """Interrupt one exact running Runtime Session by alias."""

    runner_directory = discover_runner_directory(cwd)
    mapping, session_directory = read_alias_mapping(runner_directory, alias)
    return _interrupt_session(alias, session_directory, mapping)


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


def _team_runtime_environment(mapping: Dict[str, Any], cwd: Path) -> Dict[str, str]:
    """Restore the immutable Team context needed by a resumed member Session."""
    try:
        configuration = load_project_configuration(cwd)
        matches = []
        for evidence in (configuration.state / "tickets").iterdir():
            if (
                evidence.is_symlink()
                or not evidence.is_dir()
                or not evidence.name.startswith(mapping["ticket_id"] + "-")
            ):
                continue
            ticket = yaml.safe_load((evidence / "ticket.yml").read_text(encoding="utf-8"))
            if isinstance(ticket, dict) and ticket.get("ticket_id") == mapping["ticket_id"]:
                matches.append((evidence, ticket))
        if len(matches) != 1:
            raise ValueError("missing Ticket context")
        evidence, ticket = matches[0]
        ticket_name = ticket.get("ticket_name")
        team_file = evidence / "teams" / str(mapping["team_generation"]) / "team.yml"
        if not team_file.is_file():
            return {"GRAPHTRAJ_ROLE": mapping["role"]}
        project = discover_project(cwd)
        team = yaml.safe_load(team_file.read_text(encoding="utf-8"))
        round_ordinal = team["current_round"]
        if (
            not isinstance(ticket, dict)
            or not isinstance(ticket_name, str)
            or not ticket_name
            or not isinstance(team, dict)
            or type(round_ordinal) is not int
            or round_ordinal < 1
        ):
            raise ValueError("invalid Team context")
    except (OSError, TypeError, ValueError, yaml.YAMLError, ProjectConfigurationError) as error:
        raise RunnerError("session-not-resumable", "Cannot restore the Team Runtime context: {0}".format(error)) from error
    environment = {
        "GRAPHTRAJ_ROLE": mapping["role"],
        "GRAPHTRAJ_EVIDENCE": str(evidence),
        "GRAPHTRAJ_TICKET_ID": mapping["ticket_id"],
        "GRAPHTRAJ_TICKET_NAME": ticket_name,
        "GRAPHTRAJ_HARNESS_ROOT": str(configuration.harness_root),
        "GRAPHTRAJ_TEAM_GENERATION": str(mapping["team_generation"]),
        "GRAPHTRAJ_TEAM_ROUND": str(round_ordinal),
    }
    if mapping["role"] in {"standards-reviewer", "spec-reviewer"}:
        candidate = ticket.get("current_candidate")
        if not isinstance(candidate, str) or not candidate:
            raise _not_resumable()
        axis = "Standards" if mapping["role"] == "standards-reviewer" else "Spec"
        report = evidence / "reviews" / ("standards.md" if axis == "Standards" else "spec.md")
        try:
            if report.parent.is_symlink():
                raise OSError("review report directory is a symlink")
            report.parent.mkdir(exist_ok=True)
        except OSError as error:
            raise _not_resumable() from error
        environment.update(
            GRAPHTRAJ_REVIEW_CANDIDATE=candidate,
            GRAPHTRAJ_REVIEW_COMPARISON=project.dev_commit,
            GRAPHTRAJ_REVIEW_BRIEF=(
                "Review only for Repository Guidance and established project standards."
                if axis == "Standards"
                else "Review only against the accepted Ticket and its acceptance criteria."
            ),
            GRAPHTRAJ_REVIEW_REPORT=str(report),
        )
    return environment


def _refresh_current_team_report_request(
    request: Dict[str, Any],
    mapping: Dict[str, Any],
    worktree: Path,
    environment: Dict[str, str],
) -> Dict[str, Any]:
    if mapping["role"] in {
        "engineer-junior", "engineer-senior", "engineer-expert",
    }:
        names = ("engineer.md", "validation.md")
    elif mapping["role"] == "team-leader":
        names = ("leader.md",)
    else:
        return request
    evidence = environment.get("GRAPHTRAJ_EVIDENCE")
    generation = environment.get("GRAPHTRAJ_TEAM_GENERATION")
    ordinal = environment.get("GRAPHTRAJ_TEAM_ROUND")
    if not all(
        isinstance(value, str) and value
        for value in (evidence, generation, ordinal)
    ):
        raise _not_resumable()
    directory = Path(".state") / "teams" / generation / "rounds" / ordinal
    try:
        return refresh_codex_report_paths(
            request,
            worktree=worktree,
            evidence=Path(evidence),
            report_files=tuple(directory / name for name in names),
        )
    except RuntimeAdapterError as error:
        raise RunnerError(error.code, error.message) from error


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
