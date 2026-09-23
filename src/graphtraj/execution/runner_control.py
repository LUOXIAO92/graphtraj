"""Alias-addressed follow-up operations for recoverable Engineer sessions."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

import yaml

from graphtraj.runtimes.codex.codex_adapter import (
    codex_connection_environment,
    read_codex_session_identity,
    refresh_codex_report_paths,
)
from graphtraj.configuration.project_roles import logical_role
from graphtraj.graph.delivery_worldline import read_worldline
from graphtraj.execution.execution_budget import caller_notice_fd, execution_budget_monitor
from graphtraj.configuration.project_configuration import (
    ProjectConfigurationError,
    load_project_configuration,
)
from graphtraj.execution.runner_connection import session_operation
from graphtraj.execution.runner_io import confirm_alias_mapping_durable, write_yaml_durably
from graphtraj.execution.runner_capacity import capacity_positions
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_heartbeat import execution_start_lock
from graphtraj.execution.runner_process import (
    OPERATION_TIMEOUT_SECONDS,
    stop_worker,
)
from graphtraj.workspace.runner_project import discover_project, discover_runner_directory
from graphtraj.execution.runner_status import (
    SESSION_BINDING_FIELDS,
    is_session_mapping,
    owning_execution,
    read_alias_mapping,
    read_terminal_outcome,
    require_direct_authority,
    session_occupied,
    require_descendant_authority,
    require_execution_allowed,
    _recorded_sessions,
)
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


SESSION_IDENTITY_READERS = {"codex": read_codex_session_identity}
SESSION_IMMUTABLE_MAPPING_FIELDS = SESSION_BINDING_FIELDS + (
    "retained_batch_file",
    "worktree_path",
    "trace_file",
)


def notify_direct_parent(
    session_directory: Path,
    notice: str,
    identity: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Deliver one notice into the recorded direct parent's existing execution.

    A child Session reports an event - a native request waiting for a decision,
    or an abnormal end - to the parent its own record names. The notice travels
    through the parent's control channel into the execution that parent already
    owns, so a parent that is running or waiting receives it in the same
    Session and execution without a second execution, a copied Session or a
    polling reader. What the parent's owning execution acknowledged is
    recorded; registering the event alone is not a delivery.

    Parameters
    ----------
    session_directory
        Session directory of the notifying Session. Its own record supplies
        the direct parent, never a value the caller carries.
    notice
        Plain-text input delivered to the parent's execution.
    identity
        Optional facts of what produced the notice, retained in the record.

    Returns
    -------
    The delivery record: ``parent``, the acknowledged ``parent_session`` and
    ``parent_execution_id``, and ``delivery`` - ``received``,
    ``not-delivered`` with the observed activity or error, or
    ``no-direct-parent``. The same record is appended to
    ``parent-notices.jsonl`` in the notifying Session directory.
    """
    record: Dict[str, Any] = {
        "at": time.time(), "notice": notice, "parent": None,
        "delivery": "no-direct-parent",
    }
    if identity is not None:
        record["identity"] = dict(identity)
    try:
        runner_directory = session_directory.parent.parent
        mapping, _ = read_alias_mapping(runner_directory, session_directory.name)
        parent = mapping.get("parent")
        if isinstance(parent, str):
            record["parent"] = parent
            parent_mapping, parent_directory = read_alias_mapping(
                runner_directory, parent
            )
            owning = owning_execution(parent, parent_directory, parent_mapping)
            if owning is None or owning.get("activity") != "running":
                record["delivery"] = "not-delivered"
                record["activity"] = (owning or {}).get("activity", "idle")
            else:
                session_operation(parent_mapping, "send", instruction=notice)
                record.update({
                    "delivery": "received",
                    "parent_session": parent_mapping["session"],
                    "parent_execution_id": parent_mapping["execution_id"],
                })
    except RunnerError as error:
        record["delivery"] = "not-delivered"
        record["error"] = {"code": error.code, "message": error.message}
    try:
        _append_notice_record(session_directory, record)
    except OSError:
        # A record this Runner cannot write never changes the request the
        # notice announces; the returned record still states what was observed.
        pass
    return record


def _append_notice_record(
    session_directory: Path, record: Mapping[str, Any]
) -> None:
    """Retain one notice record beside the Session's other Runner records."""
    with (session_directory / "parent-notices.jsonl").open(
        "a", encoding="utf-8"
    ) as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")


def pending_requests(
    alias: str, cwd: Path, *, execution_id: str | None = None,
) -> dict:
    """Query the mapped execution's native requests without consuming them.

    Supply ``execution_id`` to reject a mapping that has moved to a successor.
    Each returned request carries the identity required by ``reply_to_request``.
    """
    runner_directory = discover_runner_directory(cwd)
    mapping, directory = read_alias_mapping(runner_directory, alias)
    require_direct_authority(runner_directory, alias, mapping)
    if execution_id is not None and execution_id != mapping.get('execution_id'):
        raise RunnerError('operation-failed', 'The requested execution is no longer mapped.')
    identity = {'alias': alias, 'session': mapping['session'],
                'execution_id': mapping['execution_id']}
    terminal = directory / 'execution.yml'
    if terminal.is_file():
        read_terminal_outcome(terminal)
        return {**identity, 'requests': []}
    try:
        return {**identity, **session_operation(mapping, 'requests')}
    except RunnerError:
        if terminal.is_file():
            read_terminal_outcome(terminal)
            return {**identity, 'requests': []}
        raise


def reply_to_request(alias: str, request: dict, response: dict, cwd: Path) -> dict:
    """Submit a JSON response to one request returned by ``pending_requests``.

    Session, execution and request token must still match the current owner.
    Submission acknowledges the callback reply; observe status for the native
    execution's eventual result. No response decision is inferred or defaulted.
    """
    if not isinstance(request, dict) or any(
        not isinstance(request.get(key), str) or not request[key]
        for key in ('session', 'execution_id', 'request_token')
    ) or not isinstance(response, dict):
        raise RunnerError('invalid-input', 'Supply a pending request and a native JSON response object.')
    try:
        json.dumps(response, allow_nan=False)
    except (ValueError, TypeError) as error:
        raise RunnerError('invalid-input', 'The native response must be a JSON object.') from error
    runner_directory = discover_runner_directory(cwd)
    mapping, directory = read_alias_mapping(runner_directory, alias)
    require_direct_authority(runner_directory, alias, mapping)
    if any(request[key] != mapping.get(key) for key in ('session', 'execution_id')):
        raise RunnerError('operation-failed', 'The requested native execution is no longer mapped.')
    if (directory / 'execution.yml').exists():
        raise RunnerError('operation-failed', 'The native request is no longer pending.')
    result = session_operation(
        mapping, 'reply', request_token=request['request_token'], response=response,
    )
    return {'alias': alias, 'session': mapping['session'],
            'execution_id': mapping['execution_id'], **result}


def send_instruction(
    alias: str,
    instruction: str,
    cwd: Path,
    caused_by_event_ids: tuple[str, ...],
    *,
    reports_only: bool = False,
) -> Dict[str, str]:
    """Steer an active execution or continue an idle mapped Session.

    ``reports_only`` selects report collection: the Session is resumed to
    return evidence it already holds, so it starts no new work and samples no
    stopping check. The default keeps a continuation under budget control.
    """

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
    require_direct_authority(runner_directory, alias, mapping)
    if is_session_mapping(mapping):
        _require_project_events(cwd, caused_by_event_ids)
        from graphtraj.teams.coding.team_replacement import require_active_session

        require_active_session(
            discover_project(cwd, require_clean_integration=False), alias
        )
        return _send_session(
            alias,
            instruction,
            session_directory,
            mapping,
            caused_by_event_ids,
            cwd,
            reports_only=reports_only,
        )
    raise _not_resumable()


def _execution_identity(alias: str, mapping: Mapping[str, Any]) -> Dict[str, str]:
    """Return the identity of the execution a successor can deliver to or stop."""
    return {
        "alias": alias,
        "session": mapping["session"],
        "execution_id": mapping["execution_id"],
    }


def _send_session(
    alias: str,
    instruction: str,
    session_directory: Path,
    mapping: Dict[str, Any],
    caused_by_event_ids: tuple[str, ...],
    cwd: Path,
    *,
    budget_notice: bool = False,
    leader_notice_keys: tuple[str, ...] = (),
    capacity_fd: int | None = None,
    reports_only: bool = False,
) -> Dict[str, str]:
    """Serialize alias changes so two idle sends cannot create competing owners."""
    launch_file = session_directory / "launch.yml"
    if launch_file.is_symlink() or not launch_file.is_file():
        raise _not_resumable()
    with launch_file.open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        mapping, _ = read_alias_mapping(session_directory.parent.parent, alias)
        with execution_start_lock(session_directory.parent.parent):
            require_execution_allowed(session_directory.parent.parent, alias, mapping)
        return _send_session_locked(
            alias, instruction, session_directory, mapping, caused_by_event_ids, cwd,
            budget_notice=budget_notice, leader_notice_keys=leader_notice_keys,
            capacity_fd=capacity_fd, reports_only=reports_only,
        )


def _send_session_locked(
    alias: str,
    instruction: str,
    session_directory: Path,
    mapping: Dict[str, Any],
    caused_by_event_ids: tuple[str, ...],
    cwd: Path,
    *,
    budget_notice: bool = False,
    leader_notice_keys: tuple[str, ...] = (),
    capacity_fd: int | None = None,
    reports_only: bool = False,
) -> Dict[str, str]:
    """Deliver input or restore the retained Context under the alias lock.

    A report collection never attaches the budget monitor, so returning
    evidence the Session already holds advances no stopping check, emits no
    new stop notice and produces no new retro input. Every other resume keeps
    the monitor and the Ticket's budget control.
    """
    execution_file = session_directory / "execution.yml"
    if not os.path.lexists(str(execution_file)):
        # One execution owns this Session at a time: a live one receives this
        # input, and only its retained terminal record lets the next one start.
        owning = owning_execution(alias, session_directory, mapping)
        if owning is not None:
            if owning["activity"] != "running":
                raise session_occupied(alias, owning)
            with execution_start_lock(session_directory.parent.parent):
                require_execution_allowed(session_directory.parent.parent, alias, mapping)
                session_operation(mapping, "send", instruction=instruction)
            from graphtraj.execution.runner_worker import _append_follow_up

            if caused_by_event_ids:
                _append_follow_up(session_directory / "events.jsonl", list(caused_by_event_ids))
            return {**_execution_identity(alias, mapping), "send_status": "sent"}
        # Native completion can precede the owner's final Trace drain and close.
        deadline = time.monotonic() + OPERATION_TIMEOUT_SECONDS
        while not execution_file.is_file():
            if time.monotonic() >= deadline:
                raise RunnerError("operation-failed", "The previous execution is still closing.")
            time.sleep(0.01)
    read_terminal_outcome(execution_file)
    worktree = Path(mapping["worktree_path"])
    if not worktree.is_absolute() or worktree.is_symlink() or not worktree.is_dir():
        raise _invalid_mapping()
    request, connection, context_evidence = _read_session_resume_request(session_directory, mapping)
    _attest_runtime_session(session_directory, mapping)
    team_environment = _team_runtime_environment(mapping, cwd)
    evidence = team_environment.get("GRAPHTRAJ_EVIDENCE")
    ticket_name = team_environment.get("GRAPHTRAJ_TICKET_NAME")
    monitor = (
        execution_budget_monitor(Path(evidence), mapping["ticket_id"], ticket_name)
        if isinstance(evidence, str) and isinstance(ticket_name, str)
        else None
    )
    stopped = budget_notice or (monitor is not None and monitor.is_stopped())
    pending_notices = (
        monitor.pending_leader_notices()
        if stopped
        and not budget_notice
        and logical_role(mapping["role"]) == "team-leader"
        and monitor is not None
        else []
    )
    notice_monitor = monitor
    if stopped and logical_role(mapping["role"]) not in {"engineer", "team-leader"}:
        raise RunnerError(
            "EXECUTION_BUDGET_STOPPED",
            "Runner selected stopping; this Session cannot start new work.",
        )
    request = _refresh_current_team_report_request(
        request, mapping, worktree, team_environment,
        reports_only=stopped or reports_only,
        session_directory=session_directory,
    )
    if stopped:
        instruction = (
            (
                "This continuation has read-only Worktree access and can only "
                "receive the system notices below.\n"
                if budget_notice
                else "Execution was stopped by Runner. Ordinary implementation and "
                "new dispatch are prohibited. Report only the existing result and "
                "commit only already-made authorized changes.\n"
            )
            + "".join(notice["message"] + "\n" for notice in pending_notices)
            + instruction
        )
        monitor = None
    elif reports_only:
        monitor = None
    resume_file = session_directory / "resume.yml"
    error_file = session_directory / "resume-error.yml"
    error_file.unlink(missing_ok=True)
    notice_fd = None
    close_notice_fd = False
    try:
        resume = {
            "operation": "resume",
            "runtime": mapping["runtime"],
            "adapter_request": request,
            "context_evidence": context_evidence,
            "expected_session": mapping["session"],
            "caused_by_event_ids": list(caused_by_event_ids),
            "mapping": {
                key: value
                for key, value in mapping.items()
                if key not in {"worker_pid", "runtime_pid"}
            },
        }
        if monitor is not None:
            resume["monitor_execution_budget"] = True
            if logical_role(mapping["role"]) == "team-leader":
                resume["deliver_parentless_leader_notices"] = True
            if leader_notice_keys:
                resume["leader_notice_keys"] = list(leader_notice_keys)
        write_yaml_durably(
            resume_file,
            resume,
        )
        worker_environment = dict(os.environ)
        worker_environment.update(_resume_environment(mapping, connection))
        worker_environment.update(team_environment)
        # Every resumed Session carries its own Agent Entity alias, so its
        # control requests are judged against the Runner's recorded owner.
        worker_environment["GRAPHTRAJ_PARENT_ALIAS"] = alias
        if monitor is not None:
            notice_fd, close_notice_fd = caller_notice_fd()
            if notice_fd is not None:
                worker_environment["GRAPHTRAJ_BUDGET_NOTICE_FD"] = str(notice_fd)
        if logical_role(mapping["role"]) == "team-leader":
            worker_environment["GRAPHTRAJ_PARENT_REGISTRATION"] = str(
                session_directory / "child-registration.yml"
            )
        with capacity_positions(
            load_project_configuration(cwd), 1, capacity_fd
        ) as positions:
            worker_environment["GRAPHTRAJ_CAPACITY_FD"] = str(
                positions[0].fileno()
            )
            with (session_directory / "worker-stderr.log").open(
                "w", encoding="utf-8"
            ) as diagnostics:
                worker = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "graphtraj.execution.runner_worker",
                        str(resume_file),
                    ],
                    cwd=worktree,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=diagnostics,
                    text=True,
                    start_new_session=True,
                    env=worker_environment,
                    pass_fds=(positions[0].fileno(),) if notice_fd is None else (
                        positions[0].fileno(), notice_fd,
                    ),
                )
                assert worker.stdin is not None
                worker.stdin.write(instruction)
                worker.stdin.close()
        _await_session_resume(worker, session_directory, error_file, mapping["session"])
        if pending_notices and notice_monitor is not None:
            notice_monitor.mark_leader_notices_delivered(
                [notice["key"] for notice in pending_notices]
            )
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
    finally:
        if close_notice_fd and notice_fd is not None:
            os.close(notice_fd)
    # The started execution is the one the resumed Worker recorded, so the
    # caller can deliver to or stop exactly that execution.
    mapping, _ = read_alias_mapping(session_directory.parent.parent, alias)
    return {**_execution_identity(alias, mapping), "send_status": "sent"}


def interrupt_session(alias: str, cwd: Path) -> Dict[str, Any]:
    """Prevent further subtree work and interrupt every recorded descendant.

    Each member is addressed directly through its native execution owner.
    Failure to reach one member does not prevent the others being stopped,
    and only native terminal evidence counts as a complete confirmation.
    """

    runner_directory = discover_runner_directory(cwd)
    mapping, _ = read_alias_mapping(runner_directory, alias)
    require_descendant_authority(runner_directory, alias, mapping)
    with execution_start_lock(runner_directory):
        mapping, session_directory = read_alias_mapping(runner_directory, alias)
        write_yaml_durably(session_directory / "stop.yml", {"alias": alias})
        records, failures = _recorded_sessions(runner_directory)
        # Allocations still preparing a job have no native Session yet. They
        # must pass the Worker guard after we release this lock. Retain any
        # unreadable record with native identity as explicitly unconfirmed.
        failures = [
            (name, error) for name, error in failures
            if any(os.path.lexists(runner_directory / "sessions" / name / filename)
                   for filename in ("mapping.yml", "session.yml", "native-session.yml"))
        ]
        pending = [alias]
        members = []
        seen = set()
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            members.append(current)
            pending.extend(
                name for name, child in records.items() if child.get("parent") == current
            )

    def stop_member(member: str) -> Dict[str, Any]:
        """Return terminal confirmation or the member whose stop is unconfirmed."""
        try:
            current, directory = read_alias_mapping(runner_directory, member)
            return _interrupt_session(member, directory, current)
        except RunnerError as error:
            return {"alias": member, "interrupt_status": "unconfirmed",
                    "error": error.as_document()}

    with ThreadPoolExecutor() as pool:
        results = list(pool.map(stop_member, members))
    results.extend(
        {"alias": name, "interrupt_status": "unconfirmed", "error": error.as_document()}
        for name, error in failures
    )
    complete = all(item["interrupt_status"] in {"interrupted", "stopped"} for item in results)
    return {"alias": alias, "interrupt_status": "interrupted" if complete else "incomplete",
            "members": results}


def _interrupt_session(
    alias: str, session_directory: Path, mapping: Dict[str, Any]
) -> Dict[str, str]:
    """Confirm a terminal member or await its exact native Turn interruption."""
    execution_file = session_directory / "execution.yml"
    if os.path.lexists(str(execution_file)):
        read_terminal_outcome(execution_file)
        return {"alias": alias, "interrupt_status": "stopped"}
    try:
        session_operation(mapping, "interrupt")
    except RunnerError:
        # Native completion can precede the Worker's terminal-file drain.
        # Reuse its live terminal acknowledgement as well as durable outcomes;
        # lost contact or a stale heartbeat still cannot establish stopping.
        if owning_execution(alias, session_directory, mapping) is not None:
            raise
        return {"alias": alias, "interrupt_status": "stopped"}
    return {"alias": alias, "interrupt_status": "interrupted"}


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
) -> Tuple[Dict[str, Any], Dict[str, str], Dict[str, Any]]:
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
    return launch["adapter_request"], connection, launch.get("context_evidence", {})


def _await_session_resume(
    worker: subprocess.Popen[str],
    session_directory: Path,
    error_file: Path,
    expected_session: str | None,
) -> None:
    """Wait only for durable ownership; execution continues after this returns."""
    mapping_file = session_directory / "mapping.yml"
    deadline = time.monotonic() + OPERATION_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if error_file.is_file():
            if expected_session is None:
                failure = yaml.safe_load(error_file.read_text(encoding="utf-8"))
                raise RunnerError(failure["code"], failure["message"])
            raise _read_resume_error(error_file)
        try:
            mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            mapping = None
        if (
            isinstance(mapping, dict)
            and is_session_mapping(mapping)
            and mapping.get("worker_pid") == worker.pid
            and (expected_session is None or mapping.get("session") == expected_session)
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
        if (
            not isinstance(ticket, dict)
            or not isinstance(ticket_name, str)
            or not ticket_name
        ):
            raise ValueError("invalid Ticket context")
        environment = {
            "GRAPHTRAJ_ROLE": mapping["role"],
            "GRAPHTRAJ_EVIDENCE": str(evidence),
            "GRAPHTRAJ_TICKET_ID": mapping["ticket_id"],
            "GRAPHTRAJ_TICKET_NAME": ticket_name,
            "GRAPHTRAJ_HARNESS_ROOT": str(configuration.harness_root),
            "GRAPHTRAJ_TEAM_GENERATION": str(mapping["team_generation"]),
        }
        team_file = evidence / "teams" / str(mapping["team_generation"]) / "team.yml"
        if not team_file.is_file():
            return environment
        project = discover_project(cwd, require_clean_integration=False)
        team = yaml.safe_load(team_file.read_text(encoding="utf-8"))
        round_ordinal = team["current_round"]
        if (
            not isinstance(team, dict)
            or type(round_ordinal) is not int
            or round_ordinal < 1
        ):
            raise ValueError("invalid Team context")
    except (OSError, TypeError, ValueError, yaml.YAMLError, ProjectConfigurationError) as error:
        raise RunnerError("session-not-resumable", "Cannot restore the Team Runtime context: {0}".format(error)) from error
    environment["GRAPHTRAJ_TEAM_ROUND"] = str(round_ordinal)
    reviewer = logical_role(mapping["role"]) in {"standards-reviewer", "spec-reviewer"}
    if reviewer:
        candidate = ticket.get("current_candidate")
        if not isinstance(candidate, str) or not candidate:
            raise _not_resumable()
        axis = (
            "Standards"
            if logical_role(mapping["role"]) == "standards-reviewer"
            else "Spec"
        )
        try:
            report_path = _reviewer_report_file(mapping)
        except ValueError:
            raise _not_resumable() from None
        report = evidence.joinpath(*report_path.parts[1:])
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
    *,
    reports_only: bool = False,
    session_directory: Path | None = None,
) -> Dict[str, Any]:
    role = logical_role(mapping["role"])
    if role == "team-leader" and "GRAPHTRAJ_TEAM_ROUND" not in environment:
        if not reports_only:
            return request
        evidence = environment.get("GRAPHTRAJ_EVIDENCE")
        if not isinstance(evidence, str) or not evidence:
            raise _not_resumable()
        try:
            return refresh_codex_report_paths(
                request,
                worktree=worktree,
                evidence=Path(evidence),
                report_files=(),
                role=role,
                reports_only=True,
                session_directory=session_directory,
            )
        except RuntimeAdapterError as error:
            raise RunnerError(error.code, error.message) from error
    if role == "engineer":
        names = ("engineer.md", "validation.md")
    elif role == "team-leader":
        names = ("leader.md",)
    elif role in {"standards-reviewer", "spec-reviewer"}:
        try:
            report_files = (_reviewer_report_file(mapping),)
        except ValueError:
            raise _not_resumable() from None
    else:
        return request
    evidence = environment.get("GRAPHTRAJ_EVIDENCE")
    generation = environment.get("GRAPHTRAJ_TEAM_GENERATION")
    ordinal = environment.get("GRAPHTRAJ_TEAM_ROUND")
    if not isinstance(evidence, str) or not evidence:
        raise _not_resumable()
    if role not in {"standards-reviewer", "spec-reviewer"}:
        if not all(
            isinstance(value, str) and value
            for value in (generation, ordinal)
        ):
            raise _not_resumable()
        directory = Path(".state") / "teams" / generation / "rounds" / ordinal
        report_files = tuple(directory / name for name in names)
    try:
        return refresh_codex_report_paths(
            request,
            worktree=worktree,
            evidence=Path(evidence),
            report_files=report_files,
            role=role,
            reports_only=reports_only,
            session_directory=session_directory,
        )
    except RuntimeAdapterError as error:
        raise RunnerError(error.code, error.message) from error


def _reviewer_report_file(mapping: Dict[str, Any]) -> Path:
    names = {
        "standards-reviewer": "standards.md",
        "spec-reviewer": "spec.md",
    }
    default_name = names.get(mapping.get("role"))
    if default_name is None:
        raise ValueError("invalid Reviewer role")
    value = mapping.get("report_file")
    if value is None:
        return Path(".state") / "reviews" / default_name
    report = Path(value) if isinstance(value, str) else None
    if (
        report is None
        or report.is_absolute()
        or len(report.parts) != 3
        or report.parts[:2] != (".state", "reviews")
        or ".." in report.parts
        or report.suffix != ".md"
    ):
        raise ValueError("invalid Reviewer report")
    return report


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
    if isinstance(failure, dict) and failure.get("code") == "subtree-stopped":
        return RunnerError("subtree-stopped", failure["message"])
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
