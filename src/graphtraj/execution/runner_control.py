"""Alias-addressed follow-up operations for recoverable Sessions."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import tempfile
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

import yaml

from graphtraj.runtimes import runtime_adapter
from graphtraj.graph.delivery_worldline import read_worldline
from graphtraj.execution.execution_budget import caller_notice_fd, execution_budget_monitor
from graphtraj.configuration.project_configuration import (
    ProjectConfigurationError,
    load_project_configuration,
)
from graphtraj.execution.runner_connection import connection_operation, session_operation
from graphtraj.execution.runner_io import confirm_alias_mapping_durable, write_yaml_durably
from graphtraj.execution.runner_capacity import capacity_positions
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_heartbeat import execution_start_lock
from graphtraj.execution.runner_process import (
    OPERATION_TIMEOUT_SECONDS,
    stop_worker,
)
from graphtraj.workspace.runner_project import discover_project, discover_project_root, discover_runner_directory
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


SESSION_IMMUTABLE_MAPPING_FIELDS = SESSION_BINDING_FIELDS + (
    "retained_batch_file",
    "worktree_path",
    "trace_file",
    "report_files",
)


def notify_direct_parent(
    session_directory: Path,
    notice: str,
    identity: Mapping[str, Any] | None = None,
    *,
    before_creation: bool = False,
) -> Dict[str, Any]:
    """Send an event to the actual parent, continuing its Session when idle.

    Reuse ordinary send's alias lock, native steering and retained continuation.
    The parent's original Driver remains responsible for any registered child
    aggregation. The returned receipt records transport acknowledgement; callers
    must observe the parent's actions to establish that it processed the event.

    Parameters
    ----------
    session_directory
        Session directory of the notifying Session. Its own record supplies
        the direct parent, never a value the caller carries.
    notice
        Event message wrapped with source, bound alias and existing event type.
    identity
        Optional facts of what produced the notice, retained in the record.
    before_creation
        Admission may use the Runner-owned launch binding when no Session
        mapping exists yet. This reports to its creator without creating a
        Session or granting the uncreated child any control authority.

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
        if before_creation and not os.path.lexists(session_directory / "mapping.yml"):
            try:
                launch = yaml.safe_load((session_directory / "launch.yml").read_text())
                mapping = launch["mapping"]
                if (
                    launch.get("operation") != "launch"
                    or mapping.get("alias") != session_directory.name
                ):
                    raise ValueError("Invalid admission binding")
            except (OSError, ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError) as error:
                raise RunnerError("invalid-mapping", "The Runner admission binding is unreadable.") from error
        else:
            mapping, _ = read_alias_mapping(runner_directory, session_directory.name)
        event = (
            (identity or {}).get("type") or (identity or {}).get("method")
            or (identity or {}).get("activity")
        )
        if not isinstance(event, str) or not event or not notice.strip():
            raise RunnerError("invalid-input", "A system notice needs an existing event and message.")
        message = json.dumps({
            "source": "graphtraj", "alias": mapping["alias"],
            "event": event, "message": notice,
        }, ensure_ascii=False)
        record["notice"] = message
        parent = mapping.get("parent")
        if isinstance(parent, str):
            record["parent"] = parent
            parent_mapping, parent_directory = read_alias_mapping(
                runner_directory, parent
            )
            # Reuse the same alias lock and continuation path as ordinary send.
            # A child's inherited capacity belongs to this existing task tree.
            # Only the Worker inherited this descriptor. Runtime-launched CLI
            # subprocesses can retain the environment string without the FD.
            capacity = (
                os.environ.get("GRAPHTRAJ_CAPACITY_FD")
                if mapping.get("worker_pid") == os.getpid() else None
            )
            receipt = _send_session(
                parent, message, parent_directory, parent_mapping, (),
                runner_directory.parent.parent,
                capacity_fd=int(capacity) if capacity is not None else None,
                system_notice=True,
                retain_notice_channel=mapping.get("worker_pid") == os.getpid(),
            )
            record.update({
                "delivery": "received",
                "parent_session": receipt["session"],
                "parent_execution_id": receipt["execution_id"],
            })
        elif mapping.get("parent_connection") is not None:
            address = mapping["parent_connection"]
            record["parent_connection"] = address
            connection_operation(address, json.loads(message))
            record["delivery"] = "received"
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


def deliver_parent_event(
    session_directory: Path, message: str, identity: Mapping[str, Any],
) -> Dict[str, Any]:
    """Deliver an existing event, retrying transient refusal for one operation window.

    Retain each transport attempt through the existing notice path. Completion
    of this function establishes acknowledgement only, never Agent processing.
    No parent binding means no resumable recipient; do not invent one.
    """
    deadline = time.monotonic() + OPERATION_TIMEOUT_SECONDS
    while True:
        receipt = notify_direct_parent(session_directory, message, identity)
        remaining = deadline - time.monotonic()
        if receipt['delivery'] != 'not-delivered' or remaining <= 0:
            return receipt
        time.sleep(min(1, remaining))


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
        from graphtraj.teams.team_replacement import require_active_session

        require_active_session(
            discover_project(cwd, require_clean_integration=False), alias,
            reports_only=reports_only,
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


def _session_report_paths(alias: str, cwd: Path) -> tuple[Path, ...]:
    """Resolve the target's retained assignments without inferring role ownership."""
    from graphtraj.execution.runner_results import task_report_paths

    runner = discover_runner_directory(cwd)
    mapping, directory = read_alias_mapping(runner, alias)
    if 'report_files' not in mapping:
        request, _, _ = _read_session_resume_request(directory, mapping)
        environment = _team_runtime_environment(mapping, cwd)
        mapping = _recover_report_mapping(request, mapping, environment)
    return task_report_paths(mapping, cwd)


def read_session_reports(alias: str, cwd: Path) -> dict:
    """Read only the target's declared current report files for its direct owner."""
    runner = discover_runner_directory(cwd)
    mapping, directory = read_alias_mapping(runner, alias)
    require_direct_authority(runner, alias, mapping)
    paths = _session_report_paths(alias, cwd)
    reports = [{'path': str(path), 'text': path.read_text(encoding='utf-8')}
               for path in paths if path.is_file()]
    result = {'alias': alias, 'reports': reports}
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        result['missing_reports'] = missing
    from graphtraj.execution.runner_results import session_submissions
    submissions = session_submissions(mapping, cwd)
    if submissions:
        result['submissions'] = submissions
    terminal = directory / 'execution.yml'
    if terminal.is_file():
        read_terminal_outcome(terminal)
        message = yaml.safe_load(terminal.read_text()).get('last_agent_message')
        if isinstance(message, str):
            result['last_agent_message'] = message
    return result


def submit_session_report(name: str, text: str, cwd: Path) -> dict:
    """Write the issuing formal Session's own assigned report, never another's."""
    from graphtraj.execution.runner_status import caller_alias
    from graphtraj.execution.runner_status import require_task_authority

    alias = caller_alias(discover_runner_directory(cwd))
    if alias is None:
        raise RunnerError('authority-denied', 'Main has no Team report to submit.')
    runner = discover_runner_directory(cwd)
    mapping, _ = read_alias_mapping(runner, alias)
    require_task_authority(
        load_project_configuration(cwd).state, runner, mapping['ticket_id'], alias, 'submit',
    )
    paths = [path for path in _session_report_paths(alias, cwd) if path.name == name]
    if len(paths) != 1:
        raise RunnerError('authority-denied', 'The report is not assigned to this Session.')
    from graphtraj.execution.runner_results import start_result_correction

    start_result_correction(mapping, cwd)
    path = next(path for path in _session_report_paths(alias, cwd) if path.name == name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {'alias': alias, 'report': str(path)}


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
    capacity_fd: int | None = None,
    reports_only: bool = False,
    system_notice: bool = False,
    retain_notice_channel: bool = False,
) -> Dict[str, str]:
    """Serialize alias changes so two idle sends cannot create competing owners."""
    launch_file = session_directory / "launch.yml"
    if launch_file.is_symlink() or not launch_file.is_file():
        raise _not_resumable()
    with launch_file.open("rb") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | (fcntl.LOCK_NB if system_notice else 0))
        except BlockingIOError as error:
            raise RunnerError(
                "operation-failed", "The parent Session input lock is busy; retry this notice.",
            ) from error
        mapping, _ = read_alias_mapping(session_directory.parent.parent, alias)
        with execution_start_lock(session_directory.parent.parent):
            require_execution_allowed(session_directory.parent.parent, alias, mapping)
        return _send_session_locked(
            alias, instruction, session_directory, mapping, caused_by_event_ids, cwd,
            capacity_fd=capacity_fd, reports_only=reports_only,
            system_notice=system_notice,
            retain_notice_channel=retain_notice_channel,
        )


def _send_session_locked(
    alias: str,
    instruction: str,
    session_directory: Path,
    mapping: Dict[str, Any],
    caused_by_event_ids: tuple[str, ...],
    cwd: Path,
    *,
    capacity_fd: int | None = None,
    reports_only: bool = False,
    system_notice: bool = False,
    retain_notice_channel: bool = False,
    require_budget_permission: bool = False,
) -> Dict[str, str]:
    """Deliver input or restore the retained Context under the alias lock.

    A report collection never attaches the budget monitor, so returning
    evidence the Session already holds advances no stopping check, emits no
    new stop notice and produces no new stop input. Every other resume keeps
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
    stopped = monitor is not None and monitor.is_stopped()
    if stopped and require_budget_permission:
        raise RunnerError(
            "execution-budget-stopped",
            "The Ticket stopped again before approved recovery could resume it.",
        )
    from graphtraj.teams.team_replacement import require_active_session

    require_active_session(
        discover_project(cwd, require_clean_integration=False), alias,
        reports_only=reports_only or stopped,
    )
    request = _refresh_current_team_report_request(
        request, mapping, worktree, team_environment,
        reports_only=stopped or reports_only,
        session_directory=session_directory,
    )
    if stopped:
        restriction = (
            "Execution was stopped by Runner. New task work and dispatch are "
            "prohibited. Report only the existing result and commit only "
            "already-made authorized changes.\n"
        )
        if system_notice:
            message = json.loads(instruction)
            message["message"] = restriction + message["message"]
            instruction = json.dumps(message, ensure_ascii=False)
        else:
            instruction = restriction + instruction
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
            "drive_children": not (reports_only or stopped),
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
        worker_environment["GRAPHTRAJ_PARENT_REGISTRATION"] = str(session_directory / "child-registration.yml")
        # Send returns after ownership ACK. Its caller channel ends with that
        # call; inheriting it retains a CLI capture pipe until the new Worker
        # exits. Later events use the recorded parent Session instead.
        worker_environment.pop("GRAPHTRAJ_BUDGET_NOTICE_FD", None)
        if retain_notice_channel:
            notice_fd, close_notice_fd = caller_notice_fd()
            if notice_fd is not None:
                worker_environment["GRAPHTRAJ_BUDGET_NOTICE_FD"] = str(notice_fd)
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
                        "-I",
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
                    pass_fds=(positions[0].fileno(),) + (
                        (notice_fd,) if notice_fd is not None else ()
                    ),
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
            "operation-failed", "The mapped Runtime session could not be resumed: " + str(error),
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


ABNORMAL_RESPONSE_FILE = "abnormal-response.yml"

# One answer at a time in this process. The judgment that starts an answer is
# also made by the stop itself, because interrupt_session reads each member's
# owner through owning_execution, so a judgment made inside an answer may not
# start a second one. The lock is coarse on purpose: one Runner process answers
# one judged abnormality at a time. ponytail: a process-wide lock, use per
# Session locks if concurrent answers ever need to overlap.
_abnormal_response_lock = threading.Lock()


def respond_to_abnormal_session(
    alias: str, session_directory: Path, abnormal: Mapping[str, Any]
) -> None:
    """Answer one Session the Runner judged abnormal, from its own records.

    An abnormal judgment names an Agent whose recorded owner is gone and that
    published no terminal record. The Runner answers it directly: the Session's
    recorded direct parent receives the notice in the execution that parent
    already owns, and the Session's recorded subtree is stopped, so no member
    keeps working under an Agent that lost control of it. Neither step depends
    on the lost Agent forwarding anything.

    Parameters
    ----------
    alias
        Session the Runner judged abnormal.
    session_directory
        Directory of that Session, whose own record names the direct parent.
    abnormal
        The judged status document: ``activity`` and, when the recorded
        heartbeat names this Worker, ``heartbeat_at``.

    A judgment observed from outside the caller's own descent changes nothing
    here: that caller keeps reading the abnormal activity, and the caller
    entitled to control this subtree answers it by asking. The answer is
    claimed durably before it runs and retained afterwards, so a later caller
    repeats neither the notice nor the stop, and a stop that cannot be
    confirmed stays visible in the notice instead of being reported as done.
    """
    if not _abnormal_response_lock.acquire(blocking=False):
        return
    try:
        runner_directory = session_directory.parent.parent
        mapping, _ = read_alias_mapping(runner_directory, alias)
        try:
            require_descendant_authority(runner_directory, alias, mapping)
        except RunnerError:
            return
        claim = session_directory / ABNORMAL_RESPONSE_FILE
        try:
            with claim.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps({"alias": alias, "at": time.time()}) + "\n")
        except FileExistsError:
            return
        try:
            # A public control entry locates the Runner from a working
            # directory; this Session's own record names that project.
            stopped = interrupt_session(alias, runner_directory.parent.parent)
        except RunnerError as error:
            stopped = {
                "alias": alias, "interrupt_status": "unconfirmed",
                "members": [], "error": error.as_document(),
            }
        identity = {**stopped, "activity": abnormal["activity"]}
        if "heartbeat_at" in abnormal:
            identity["heartbeat_at"] = abnormal["heartbeat_at"]
        notify_direct_parent(
            session_directory,
            _abnormal_notice(alias, abnormal, stopped),
            identity,
        )
    finally:
        _abnormal_response_lock.release()


def _abnormal_notice(
    alias: str, abnormal: Mapping[str, Any], stopped: Mapping[str, Any]
) -> str:
    """Return the abnormality and the stop result as text the parent reads."""
    basis = "activity=abnormal, ownership lock released, no terminal record"
    heartbeat_at = abnormal.get("heartbeat_at")
    if isinstance(heartbeat_at, (int, float)) and not isinstance(heartbeat_at, bool):
        basis += ", last heartbeat " + time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.localtime(heartbeat_at)
        )
    members = ", ".join(
        "{0}={1}".format(item["alias"], item["interrupt_status"])
        for item in stopped["members"]
    ) or "no member result"
    failure = stopped.get("error")
    return "Runner judged Agent {0} abnormal ({1}). Subtree stop {2}: {3}{4}".format(
        alias,
        basis,
        stopped["interrupt_status"],
        members,
        "" if failure is None else " ({0}: {1})".format(
            failure["code"], failure["message"]
        ),
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
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
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
            launch["mapping"].get(field) != mapping.get(field)
            for field in SESSION_IMMUTABLE_MAPPING_FIELDS
        )
    ):
        raise _invalid_mapping()
    connection = launch["connection"]
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
            and mapping.get("execution_id")
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
            terminal_file = session_directory / "execution.yml"
            if terminal_file.is_file():
                terminal = yaml.safe_load(terminal_file.read_text())
                if terminal.get("budget_stopped"):
                    raise RunnerError(
                        "EXECUTION_BUDGET_STOPPED", "Runner stopped execution during Session creation.",
                    )
            raise _not_resumable()
        time.sleep(0.01)
    raise _not_resumable()


def _resume_environment(
    mapping: Dict[str, Any],
    connection: Dict[str, Any],
) -> Dict[str, str]:
    """Resolve one resume environment from the immutable launch Context."""
    try:
        return dict(runtime_adapter.select_runtime_adapter(
            mapping["runtime"]
        ).recovery_environment(connection))
    except RuntimeAdapterError as error:
        raise RunnerError(error.code, error.message) from error


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
    """Project current report paths from the same assignments used by Runner."""
    from graphtraj.execution.runner_results import task_report_paths

    mapping = _recover_report_mapping(request, mapping, environment)
    harness = discover_project_root(worktree)
    evidence = Path(environment['GRAPHTRAJ_EVIDENCE'])
    report_files = tuple(Path('.state') / path.relative_to(evidence)
                         for path in task_report_paths(mapping, harness))
    try:
        return runtime_adapter.select_runtime_adapter(mapping["runtime"]).refresh_report_paths(
            request, worktree=worktree, evidence=evidence,
            report_files=report_files, role=mapping['role'],
            reports_only=reports_only, session_directory=session_directory,
        )
    except RuntimeAdapterError as error:
        raise RunnerError(error.code, error.message) from error


def _recover_report_mapping(
    request: Mapping[str, Any],
    mapping: Dict[str, Any],
    environment: Mapping[str, str],
) -> Dict[str, Any]:
    """Recover historical assignments in memory from exact retained grants.

    A singular report reference is an assignment. Otherwise only exact writable
    Markdown paths within this Ticket's evidence establish report ownership;
    readable paths can belong to other members and must never become writable.
    The original mapping and launch records remain unchanged.
    """
    if 'report_files' in mapping:
        return mapping
    if mapping.get('report_file') is not None:
        return {**mapping, 'report_files': [mapping['report_file']]}

    try:
        reports = runtime_adapter.select_runtime_adapter(mapping["runtime"]).recover_report_files(
            request, Path(environment["GRAPHTRAJ_EVIDENCE"]),
        )
    except RuntimeAdapterError as error:
        raise RunnerError(error.code, error.message) from error
    return {**mapping, 'report_files': list(reports)}


def _attest_runtime_session(
    session_directory: Path, mapping: Dict[str, Any]
) -> None:
    try:
        identity = runtime_adapter.select_runtime_adapter(mapping["runtime"]).read_session_identity(
            session_directory,
        )
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
        "subtree-stopped", "EXECUTION_BUDGET_STOPPED",
    }:
        return RunnerError(failure["code"], failure["message"])
    if isinstance(failure, dict) and failure.get("code") in {
        "PROJECT_CONFIG_MISMATCH",
        "ROLE_GUARD_MISMATCH",
        "RUNTIME_REQUEST_INVALID",
        "RUNTIME_SESSION_MISSING",
        "RUNTIME_SESSION_NOT_RESUMABLE",
        "RUNTIME_START_FAILED",
    }:
        return RunnerError(
            "session-not-resumable", "{0}: {1}".format(failure["code"], failure["message"]),
        )
    return RunnerError(
        "operation-failed",
        "The mapped Runtime Session could not be resumed: " + str(failure),
    )


def _invalid_mapping() -> RunnerError:
    return RunnerError(
        "operation-failed", "The requested Agent alias mapping is invalid."
    )
