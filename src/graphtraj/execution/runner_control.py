"""Alias-addressed follow-up operations for recoverable Sessions."""

from __future__ import annotations

from graphtraj.configuration.project_configuration import runner_project_root

import hashlib
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

from graphtraj import file_lock
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
from graphtraj.execution.runner_heartbeat import execution_start_lock, read_heartbeat, ownership_is_held
from graphtraj.execution.runner_transport import runtime_launch_failure, valid_terminal_launch_failure
from graphtraj.execution.runner_process import (
    OPERATION_TIMEOUT_SECONDS,
    stop_worker,
    unstarted_worker_processes,
)
from graphtraj.workspace.runner_project import discover_project, discover_project_root, discover_runner_directory
from graphtraj.execution.runner_status import (
    SESSION_BINDING_FIELDS,
    is_session_mapping,
    owning_execution,
    read_alias_mapping,
    read_terminal_outcome,
    read_execution_result,
    require_direct_authority,
    require_project_reader,
    project_redact,
    session_occupied,
    require_descendant_authority,
    require_execution_allowed,
    read_retired_legacy_hosted_mapping,
    session_record_directory,
    _recorded_sessions,
    caller_alias,
    _terminal_unestablished_launch,
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
    ``no-direct-parent``. ``received`` means the parent's input channel took
    the notice; ``input`` says whether a resumed parent turn started on it or
    it is only queued in a running execution, which a later turn consumes.
    The same record is appended to ``parent-notices.jsonl`` in the notifying
    Session directory.
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
                runner_project_root(runner_directory),
                capacity_fd=int(capacity) if capacity is not None else None,
                system_notice=True,
                retain_notice_channel=mapping.get("worker_pid") == os.getpid(),
            )
            record.update({
                "delivery": "received",
                "parent_session": receipt["session"],
                "parent_execution_id": receipt["execution_id"],
                # A running parent only queued the input; its turn taking it
                # up is not confirmed here. Otherwise a resumed turn bound it.
                "input": (
                    "queued-in-running-execution"
                    if receipt["execution_id"] == parent_mapping.get("execution_id")
                    else "started-parent-turn"
                ),
            })
        elif mapping.get("parent_connection") is not None:
            address = _current_main_address(runner_directory, mapping["parent_connection"])
            record["parent_connection"] = address
            # Once the parent's host takes the notice, await its own receipt:
            # a late receipt must not make retries forward the notice twice.
            event = json.loads(message)
            if isinstance(address, Mapping) and address.get("runner") and (identity or {}).get("execution_id"):
                # A queued Main host identifies one execution's notice by it.
                event["execution"] = identity["execution_id"]
            connection_operation(address, event, await_accepted=True)
            record["delivery"] = "received"
    except RunnerError as error:
        record["delivery"] = "not-delivered"
        record["error"] = {"code": error.code, "message": error.message}
    except Exception as error:
        # Every failed attempt is retained, whatever failed.
        record["delivery"] = "not-delivered"
        record["error"] = {"code": "operation-failed", "message": f"{type(error).__name__}: {error}"}
    try:
        _append_notice_record(session_directory, record)
    except OSError:
        # A record this Runner cannot write never changes the request the
        # notice announces; the returned record still states what was observed.
        pass
    return record


def deliver_execution_end(
    session_directory: Path,
    mapping: Mapping[str, Any],
    terminal: Mapping[str, Any],
    *,
    parent_input: bool,
) -> Dict[str, Any]:
    """Tell the direct parent that one execution ended, when it must handle it.

    A ``completed`` round is kept in the records without a parent turn
    (:func:`retain_parent_receipt`) while members under this Session still
    execute or are registered to start (:func:`agent_swarm.notices.needs_parent`),
    while the parent's ``wait`` on this Session returns it (:func:`awaited`),
    and as an ordinary receipt of an execution the parent did not start
    (``parent_input`` false) where the parent can see it that way
    (:func:`receipt_is_display_only`). Every other end is delivered.
    """
    from agent_swarm.notices import needs_parent

    runner = session_directory.parent.parent
    notice = 'Session execution ended:\n' + json.dumps({
        'session': mapping['session'], 'execution_id': mapping.get('execution_id'), **terminal,
    }, ensure_ascii=False)
    identity = {'type': terminal['outcome'], 'session': mapping['session'],
                'execution_id': mapping.get('execution_id')}
    if terminal['outcome'] == 'completed' and (
            not needs_parent('completed', active_members=active_members(runner, session_directory.name))
            or awaited(session_directory)
            or not parent_input and receipt_is_display_only(mapping, runner)):
        return retain_parent_receipt(session_directory, notice, identity)
    return deliver_parent_event(session_directory, notice, identity)


# How long after a parent's wait returned an end of this Session still counts
# as that wait having shown it.
AWAIT_GRACE_SECONDS = 5.0


def mark_awaited(session_directory: Path, until: float) -> None:
    """Record that the direct parent's ``wait`` shows this Session's ends until ``until``."""
    try:
        (session_directory / 'awaited.json').write_text(json.dumps({'until': until}), encoding='utf-8')
    except OSError:
        pass


def awaited(session_directory: Path) -> bool:
    """Whether a parent's ``wait`` on this Session is returning its end now."""
    try:
        until = json.loads((session_directory / 'awaited.json').read_text(encoding='utf-8'))['until']
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return isinstance(until, (int, float)) and time.time() <= until


def active_members(runner_directory: Path, alias: str) -> int:
    """Count members under ``alias`` still executing or registered to start.

    A registered child Batch starts after this Session's round ends; an
    admitted child without a native Session yet counts as starting.
    """
    from graphtraj.execution.runner_status import _status_session

    sessions = runner_directory / 'sessions'
    count = int((sessions / alias / 'child-registration.yml').is_file())
    for directory in sessions.iterdir() if sessions.is_dir() else ():
        try:
            if (directory / 'mapping.yml').is_file():
                child, _ = read_alias_mapping(runner_directory, directory.name)
                if child.get('parent') == alias and _status_session(
                        child, directory, directory.name, respond_to_abnormal=False)['activity'] != 'idle':
                    count += 1
            elif (directory / 'launch.yml').is_file():
                launch = yaml.safe_load((directory / 'launch.yml').read_text(encoding='utf-8'))
                if launch['mapping'].get('parent') == alias:
                    count += 1
        except (RunnerError, OSError, ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError):
            continue
    return count


def retain_parent_receipt(
    session_directory: Path, notice: str, identity: Mapping[str, Any],
) -> Dict[str, Any]:
    """Keep an ordinary end notice in the existing record without resuming the parent.

    The record has the same message and parent fields as a delivered notice,
    with ``delivery: retained``. People see it in the Session's records, and a
    Codex Main host shows it once at its next native hook.
    """
    mapping, _ = read_alias_mapping(session_directory.parent.parent, session_directory.name)
    record: Dict[str, Any] = {
        "at": time.time(), "identity": dict(identity), "delivery": "retained",
        "parent": mapping.get("parent") if isinstance(mapping.get("parent"), str) else None,
        "notice": json.dumps({"source": "graphtraj", "alias": mapping["alias"],
                              "event": identity["type"], "message": notice}, ensure_ascii=False),
    }
    if record["parent"] is None and mapping.get("parent_connection") is not None:
        record["parent_connection"] = _current_main_address(
            session_directory.parent.parent, mapping["parent_connection"])
    try:
        _append_notice_record(session_directory, record)
    except OSError:
        pass
    return record


def _current_main_address(runner_directory: Path, address: str | dict) -> str | dict:
    """Deliver a root's notice to the Main now continuing its recorded Main.

    The member's recorded ``parent_connection`` is never rewritten.
    """
    from graphtraj.execution.main_continuity import route_notice

    return dict(route_notice(runner_directory, address)) if isinstance(address, dict) else address


def receipt_is_display_only(mapping: Mapping[str, Any], runner_directory: Path) -> bool:
    """Whether an ordinary receipt to this Session's parent can be kept unsent.

    A Runner member parent sees it in the records and a Codex Main host shows
    it at its next hook. Other hosts keep their current delivery. A root's
    receipt follows the Main now continuing it (``runner_directory``).
    """
    if isinstance(mapping.get("parent"), str):
        return True
    connection = mapping.get("parent_connection")
    if isinstance(connection, Mapping):
        connection = _current_main_address(runner_directory, dict(connection))
    return isinstance(connection, Mapping) and connection.get("runtime") == "codex"


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
    return {**identity, 'requests': _execution_requests(mapping, directory)}


def _execution_requests(mapping: Mapping[str, Any], directory: Path) -> list:
    """Read the mapped execution's pending native requests; a terminal one has none."""
    terminal = directory / 'execution.yml'
    if terminal.is_file():
        read_terminal_outcome(terminal)
        return []
    try:
        return session_operation(dict(mapping), 'requests')['requests']
    except RunnerError:
        if terminal.is_file():
            read_terminal_outcome(terminal)
            return []
        raise


def owned_root_requests(runner_directory: Path, connection: Mapping[str, Any]) -> list[tuple[dict, dict]]:
    """Return pending native requests of the top-level Sessions a host Main owns.

    The trusted host binding supplies ``connection``; ownership is the recorded
    native owner, as in ``is_direct_owner``. An unreadable record or owner
    raises, so a caller never treats missing evidence as no request.

    Returns
    -------
    Each owned Session mapping with one of its pending requests.
    """
    pending = []
    for alias, mapping in _owned_roots(runner_directory, connection):
        _, directory = read_alias_mapping(runner_directory, alias)
        pending.extend((mapping, request) for request in _execution_requests(mapping, directory))
    return pending


def owned_root_undecided_results(harness_root: Path, connection: Mapping[str, Any]) -> list[tuple[dict, dict]]:
    """Return a host Main's root Sessions whose latest-Round submission is undecided.

    Main directly owns these Sessions, so their submitted results are Main's
    to decide. An unreadable Session, Task, Team or Worldline record raises.

    Returns
    -------
    Each owned Session mapping with its undecided ``result-submitted`` event.
    """
    from graphtraj.graph.delivery_state import RESULT_DECISION_EVENTS, read_team
    from graphtraj.graph.delivery_worldline import read_worldline
    from graphtraj.graph.task_graph import _load_states

    roots = _owned_roots(discover_runner_directory(harness_root), connection)
    if not roots:
        return []
    configuration = load_project_configuration(harness_root)
    events = read_worldline(configuration.state, configuration.harness_root)
    decided = {event['submission_id'] for event in events if event['event'] in RESULT_DECISION_EVENTS}
    tasks = _load_states(configuration.state / 'tasks')
    undecided = []
    for alias, mapping in roots:
        directory, _ = tasks[mapping['task_id']]
        team = read_team(directory / 'teams' / str(mapping['team_generation']) / 'team.yml')
        # Only the latest submission in the current Round can be decided.
        submissions = [event for event in events if event['event'] == 'result-submitted'
                       and event.get('task_id') == mapping['task_id']
                       and event.get('team_ordinal') == mapping['team_generation']
                       and event.get('round') == team['current_round']]
        if (submissions and submissions[-1].get('alias') == alias
                and submissions[-1]['event_id'] not in decided):
            undecided.append((mapping, submissions[-1]))
    return undecided


def _owned_roots(runner_directory: Path, connection: Mapping[str, Any]) -> list[tuple[str, dict]]:
    """Return the top-level Sessions whose recorded native owner is ``connection``.

    Ownership follows ``is_direct_owner``; the current Main also continues
    roots of earlier Main Sessions. Any other unreadable record raises. A
    retired hosted record or a launch that stopped before creating its Session
    has no execution, request or result, so it is not unreadable evidence.
    """
    from graphtraj.execution.main_continuity import owns_main_root

    records, failures = _recorded_sessions(runner_directory)
    for alias, error in failures:
        if (read_retired_legacy_hosted_mapping(runner_directory, alias) is None
                and not _terminal_unestablished_launch(session_record_directory(runner_directory, alias))):
            raise error
    return [
        (alias, mapping) for alias, mapping in sorted(records.items())
        if mapping.get('parent') is None and isinstance(mapping.get('parent_connection'), dict)
        and owns_main_root(runner_directory, mapping['parent_connection'], connection)
    ]


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
    """Continue a Task member Session under GraphTraj's causal recording policy.

    GraphTraj delivery requires the causing Project Worldline events before it
    calls the same continuation ``agents send`` uses, then records them with
    the follow-up. ``reports_only`` selects report collection: the Session is
    resumed to return evidence it already holds, so it starts no new work and
    samples no stopping check.
    """

    if not caused_by_event_ids:
        raise RunnerError(
            "invalid-input",
            "GraphTraj delivery continuation requires at least one causal Project "
            "Worldline event ID; plain messages use agents send without one.",
        )
    if (
        len(caused_by_event_ids) != len(set(caused_by_event_ids))
        or any(not event_id for event_id in caused_by_event_ids)
    ):
        raise RunnerError(
            "invalid-input", "causal Project Worldline event IDs must be unique."
        )
    _require_project_events(cwd, caused_by_event_ids)
    return continue_member(alias, instruction, cwd, caused_by_event_ids, reports_only=reports_only)


def continue_member(
    alias: str,
    instruction: str,
    cwd: Path,
    caused_by_event_ids: tuple[str, ...] = (),
    *,
    reports_only: bool = False,
) -> Dict[str, str]:
    """Steer an active execution or continue an idle mapped Session.

    This is the one native continuation for Task member Sessions; ``agents``
    calls it with no causes. The recorded direct parent alone may continue
    it, in the same native Session.
    """

    if not instruction.strip():
        raise RunnerError(
            "invalid-input", "instruction must be non-empty plain text."
        )
    runner_directory = discover_runner_directory(cwd)
    mapping, session_directory = read_alias_mapping(runner_directory, alias)
    require_direct_authority(runner_directory, alias, mapping)
    if is_session_mapping(mapping):
        from graphtraj.teams.team_replacement import completed_task_member, require_active_session

        project = discover_project(cwd, require_clean_integration=False)
        # A finished Task's standby member answers follow-ups without
        # reopening Task work, budget or its accepted result.
        reports_only = reports_only or completed_task_member(project, mapping)
        require_active_session(project, alias, reports_only=reports_only)
        with execution_start_lock(runner_directory):
            _continue_after_parent_interrupt(session_directory, alias, runner_directory)
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


def _continue_after_parent_interrupt(session_directory: Path, alias: str, runner_directory: Path) -> None:
    """Lift only the verified direct parent's own ordinary interrupt of this Session.

    The caller holds the execution startup lock; the send that follows
    re-checks admission under it. A stop written by anyone
    else, one without an interrupt origin (Runner recovery, replacement or an
    abnormal-session answer), an ancestor's stop and a stop whose interrupted
    execution still runs all remain. The execution budget is separate and
    unaffected.
    """
    stop_file = session_directory / "stop.yml"
    if stop_file.is_symlink() or not stop_file.is_file():
        return
    record = yaml.safe_load(stop_file.read_text())
    if (not isinstance(record, dict) or record.get("alias") != alias
            or record.get("kind") != "interrupt" or "by" not in record
            or record.get("resumed") is True):
        return
    caller = caller_alias(runner_directory)
    if record["by"] != caller or caller == alias:
        return
    mapping, _ = read_alias_mapping(runner_directory, alias)
    owning = owning_execution(alias, session_directory, mapping)
    if owning is not None and owning["activity"] == "running":
        return
    write_yaml_durably(stop_file, {**record, "resumed": True})


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
    """Read the target's declared report files for any verified project caller.

    Project development records cross Agents and non-direct relations; control
    material and credentials are redacted from the projection, never granted.
    """
    runner = discover_runner_directory(cwd)
    mapping, directory = read_alias_mapping(runner, alias)
    require_project_reader(runner)
    paths = _session_report_paths(alias, cwd)
    # A follow-up report beside a closed Round's retained one is <stem>-<n>.md.
    listed = []
    for path in paths:
        follow_ups = [item for item in path.parent.glob(f'{path.stem}-*.md')
                      if item.stem[len(path.stem) + 1:].isdigit()]
        listed += [path, *sorted(follow_ups, key=lambda item: int(item.stem[len(path.stem) + 1:]))]
    reports = [{'path': str(path), 'text': path.read_text(encoding='utf-8')}
               for path in listed if path.is_file()]
    result = {'alias': alias, 'reports': reports}
    notices = directory / 'parent-notices.jsonl'
    if notices.is_file():
        from graphtraj.runtimes.activity import redact

        # Project the retained receipt, not another send. Only the direct
        # owner reaches this report query; no private Session body is exposed.
        for line in reversed(notices.read_text(encoding='utf-8').splitlines()):
            receipt = json.loads(line)
            if receipt.get('identity', {}).get('type') != 'report-submitted':
                continue
            summary = {key: receipt[key] for key in (
                'at', 'delivery', 'parent', 'parent_session', 'parent_execution_id',
            ) if key in receipt}
            connection = receipt.get('parent_connection')
            if isinstance(connection, dict):
                summary['parent_connection'] = {key: connection[key] for key in
                                                ('runtime', 'session') if key in connection}
            if isinstance(receipt.get('error'), dict):
                summary['error'] = {key: redact(str(receipt['error'][key])) for key in
                                    ('code', 'message') if key in receipt['error']}
            result['report_notification'] = summary
            break
    if mapping.get('runtime') == 'claude' and mapping.get('execution_id'):
        diagnostic_path = directory / f"claude-diagnostics-{mapping['execution_id']}.yml"
        if diagnostic_path.is_file() and not diagnostic_path.is_symlink():
            diagnostics = yaml.safe_load(diagnostic_path.read_text())
            if (isinstance(diagnostics, dict)
                    and diagnostics.get('execution_id') == mapping['execution_id']
                    and diagnostics.get('session_id') == mapping['session']):
                result['runtime_diagnostics'] = diagnostics
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        result['missing_reports'] = missing
    from graphtraj.execution.runner_results import session_submissions
    submissions = session_submissions(mapping, cwd)
    if submissions:
        result['submissions'] = submissions
    terminal = directory / 'execution.yml'
    if terminal.is_file():
        retained = read_execution_result(terminal)
        # Only the direct owner reaches this projection; missing historical
        # confirmation or stop-source fields remain unknown, not inferred.
        result['execution'] = {
            key: retained[key] for key in (
                'outcome', 'session_id', 'execution_id', 'terminal_confirmed', 'budget_stopped', 'permissions',
            ) if key in retained
        }
        if isinstance(retained.get('error'), dict):
            from graphtraj.runtimes.activity import redact

            result['execution']['error'] = {
                key: redact(str(retained['error'][key]))
                for key in ('code', 'message') if key in retained['error']
            }
        message = retained.get('last_agent_message')
        if isinstance(message, str):
            result['last_agent_message'] = message
        if retained.get('terminal_confirmed') is False:
            try:
                read_terminal_outcome(terminal)
            except RunnerError:
                pass
            else:
                confirmation = directory / f"terminal-confirmation-{mapping['execution_id']}.yml"
                result['termination_confirmation'] = yaml.safe_load(confirmation.read_text())
    return project_redact(result)


def submit_session_report(name: str, text: str, cwd: Path, *, notify_parent: bool = False) -> dict:
    """Write the issuing formal Session's own assigned report, never another's.

    With ``notify_parent`` a notice naming the written report and its path is
    then sent to the direct parent through the same child-to-parent notice
    path as completion and request notices, continuing the parent's turn; the
    parent reads the text through session_reports. The result's
    ``delivery`` is that notice's actual receipt, such as ``received`` or
    ``no-direct-parent``; without a direct parent only the report is written.
    """
    from graphtraj.execution.runner_status import caller_alias
    from graphtraj.execution.runner_status import require_task_authority

    # A follow-up may run in a cleaned Task's continuation cwd, outside any checkout.
    cwd = discover_project_root(cwd)
    alias = caller_alias(discover_runner_directory(cwd))
    if alias is None:
        raise RunnerError('authority-denied', 'Main has no Team report to submit.')
    runner = discover_runner_directory(cwd)
    mapping, _ = read_alias_mapping(runner, alias)
    require_task_authority(
        load_project_configuration(cwd).state, runner, mapping['task_id'], alias, 'submit',
    )
    paths = [path for path in _session_report_paths(alias, cwd) if path.name == name]
    if len(paths) != 1:
        raise RunnerError('authority-denied', 'The report is not assigned to this Session.')
    from graphtraj.execution.runner_results import RESULT_STATUSES, start_result_correction
    from graphtraj.graph.task_graph import _load_states

    state = load_project_configuration(cwd).state
    if _load_states(state / 'tasks')[mapping['task_id']][1]['status'] not in RESULT_STATUSES:
        # A Task not accepting results, e.g. finished or blocked, opens no Round;
        # its member, e.g. after a follow-up or a stopped report collection,
        # adds its own report beside the retained one in the closed Round.
        path = next(path for path in _session_report_paths(alias, cwd) if path.name == name)
        written = _add_closed_round_report(path, text)
        return _reported(runner / 'sessions' / alias, alias, written, notify_parent)
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
    return _reported(runner / 'sessions' / alias, alias, path, notify_parent)


def _reported(session_directory: Path, alias: str, path: Path, notify: bool) -> dict:
    """Return the written report, first notifying the direct parent when requested."""
    result = {'alias': alias, 'report': str(path)}
    if notify:
        # The notice names the report; the parent reads its text through session_reports.
        receipt = deliver_parent_event(
            session_directory,
            'Submitted report {0} for its direct parent to handle; read it through '
            'session_reports: {1}'.format(path.name, path),
            {'type': 'report-submitted', 'report': str(path)},
        )
        result['delivery'] = receipt['delivery']
        if isinstance(receipt.get('error'), dict):
            from graphtraj.runtimes.activity import redact

            result['delivery_error'] = {key: redact(str(receipt['error'][key])) for key in
                                       ('code', 'message') if key in receipt['error']}
        if receipt.get('parent') is not None:
            result['parent'] = receipt['parent']
    return result


def _add_closed_round_report(path: Path, text: str) -> Path:
    """Create a new report beside ``path`` without changing any retained file.

    The assigned name is used when absent, otherwise the first free
    ``<stem>-<n>.md`` from 2. A closed Round directory stays read-only except
    for this one exclusive creation; its mode is restored afterwards.
    """
    directory = path.parent
    mode      = directory.stat().st_mode & 0o7777
    directory.chmod(mode | 0o200)
    try:
        number = 1
        while True:
            target = path if number == 1 else path.with_stem(f'{path.stem}-{number}')
            try:
                with target.open('x', encoding='utf-8') as stream:
                    stream.write(text)
                    stream.flush()
                    os.fsync(stream.fileno())
                # Like the Round's retained reports, the new one is not rewritten later.
                target.chmod(0o444)
                return target
            except FileExistsError:
                number += 1
    finally:
        directory.chmod(mode)


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
    parent_input: bool = True,
) -> Dict[str, str]:
    """Serialize alias changes so two idle sends cannot create competing owners.

    ``parent_input`` is false when the input is not the direct parent's own,
    such as delivered child results; a system notice is never parent input.
    """
    launch_file = session_directory / "launch.yml"
    if launch_file.is_symlink() or not launch_file.is_file():
        raise _not_resumable()
    with launch_file.open("rb") as lock:
        try:
            file_lock.flock(lock, file_lock.LOCK_EX | (file_lock.LOCK_NB if system_notice else 0))
        except BlockingIOError as error:
            raise RunnerError(
                "operation-failed", "The parent Session input lock is busy; retry this notice.",
            ) from error
        mapping, _ = read_alias_mapping(session_directory.parent.parent, alias)
        worktree = Path(mapping["worktree_path"])
        restored = False
        with execution_start_lock(session_directory.parent.parent):
            require_execution_allowed(
                session_directory.parent.parent, alias, mapping, reports_only=reports_only,
            )
            absent = not os.path.lexists(str(worktree))
            if reports_only and worktree.is_absolute() and (absent or (
                    worktree.is_dir() and not worktree.is_symlink() and not any(worktree.iterdir()))):
                from graphtraj.teams.team_replacement import completed_task_member

                # Each Runtime resumes its native Session in the recorded cwd
                # (Claude finds its transcript by it). Cleanup removed that
                # Worktree, so an empty directory stands at the same path for
                # these continuations only; the last one to end removes it.
                if completed_task_member(discover_project(cwd, require_clean_integration=False), mapping):
                    if absent:
                        worktree.mkdir()
                    restored = True
        try:
            return _send_session_locked(
                alias, instruction, session_directory, mapping, caused_by_event_ids, cwd,
                capacity_fd=capacity_fd, reports_only=reports_only,
                system_notice=system_notice,
                retain_notice_channel=retain_notice_channel,
                restored_cwd=restored,
                parent_input=parent_input and not system_notice,
            )
        except BaseException:
            if restored:
                _remove_restored_cwd(session_directory, worktree)
            raise


def _remove_restored_cwd(session_directory: Path, worktree: Path) -> None:
    """Remove a continuation-only cwd once no other execution can still use it.

    Another member mapped to the same path keeps it while it has no terminal
    record or its send still holds the input lock; that member removes it when
    it ends. A directory the Runtime left content in also stays, so a reopened
    launch refuses it as a Worktree conflict instead of discarding the content.
    """
    runner_directory = session_directory.parent.parent
    with execution_start_lock(runner_directory):
        for other in (runner_directory / "sessions").iterdir():
            if other == session_directory or not (other / "mapping.yml").is_file():
                continue
            try:
                mapping = yaml.safe_load((other / "mapping.yml").read_text(encoding="utf-8"))
            except (OSError, UnicodeError, yaml.YAMLError):
                return
            if not isinstance(mapping, dict) or mapping.get("worktree_path") != str(worktree):
                continue
            if not (other / "execution.yml").is_file():
                return
            with (other / "launch.yml").open("a+b") as lock:
                try:
                    file_lock.flock(lock, file_lock.LOCK_EX | file_lock.LOCK_NB)
                except BlockingIOError:
                    return
                file_lock.flock(lock, file_lock.LOCK_UN)
        try:
            worktree.rmdir()
        except OSError:
            pass


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
    restored_cwd: bool = False,
    parent_input: bool = True,
) -> Dict[str, str]:
    """Deliver input or restore the retained Context under the alias lock.

    A report collection never attaches the budget monitor, so returning
    evidence the Session already holds advances no stopping check, emits no
    new stop notice and produces no new stop input. Every other resume keeps
    the monitor and the Task's budget control.
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
                # A reports-only follow-up, such as a retry after a client
                # timeout, may steer a running report collection, never
                # ordinary work. The last resume record names that execution.
                require_execution_allowed(
                    session_directory.parent.parent, alias, mapping,
                    reports_only=reports_only and _running_reports_only(session_directory),
                )
                try:
                    session_operation(mapping, "send", instruction=instruction)
                except RunnerError as error:
                    # Only an explicit refusal before writing input permits
                    # continuation after close. Unknown delivery is not retried.
                    if error.code not in {"runtime-input-closed", "request-not-accepted"}:
                        raise
                else:
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
    task_name = team_environment.get("GRAPHTRAJ_TASK_NAME")
    monitor = (
        execution_budget_monitor(Path(evidence), mapping["task_id"], task_name)
        if isinstance(evidence, str) and isinstance(task_name, str)
        else None
    )
    stopped = monitor is not None and monitor.is_stopped()
    if stopped and require_budget_permission:
        raise RunnerError(
            "execution-budget-stopped",
            "The Task stopped again before approved recovery could resume it.",
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
            "reports_only": reports_only,
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
        if restored_cwd:
            resume["restored_cwd"] = True
        # The execution's end is an ordinary receipt unless the parent started it.
        resume["parent_input"] = parent_input and not system_notice
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


def interrupt_session(alias: str, cwd: Path, *, ordinary: bool = False) -> Dict[str, Any]:
    """Prevent further subtree work and interrupt every recorded descendant.

    Each member is addressed directly through its native execution owner.
    Failure to reach one member does not prevent the others being stopped,
    and only native terminal evidence counts as a complete confirmation.
    An ``ordinary`` interrupt (the public ``agents interrupt``) records who
    issued it, so that same direct parent can continue the Session later. It
    never rewrites a stop already in force from another origin.
    """

    runner_directory = discover_runner_directory(cwd)
    try:
        mapping, _ = read_alias_mapping(runner_directory, alias)
    except RunnerError:
        return _interrupt_allocation(runner_directory, alias)
    require_descendant_authority(runner_directory, alias, mapping)
    with execution_start_lock(runner_directory):
        mapping, session_directory = read_alias_mapping(runner_directory, alias)
        stop = {"alias": alias}
        if ordinary:
            stop_file = session_directory / "stop.yml"
            previous = yaml.safe_load(stop_file.read_text()) if stop_file.is_file() else None
            caller = caller_alias(runner_directory)
            if (not isinstance(previous, dict) or previous.get("resumed") is True
                    or (previous.get("kind") == "interrupt" and previous.get("by") == caller)):
                # A native Main caller is a str subclass; the record keeps its plain value.
                stop = {"alias": alias, "kind": "interrupt",
                        "by": str(caller) if caller is not None else None}
            else:
                stop = previous  # a stop in force from another origin stays exactly as recorded
        write_yaml_durably(session_directory / "stop.yml", stop)
        records, failures = _recorded_sessions(runner_directory, ownership_only=True)
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
        from graphtraj.teams.team_round import withdraw_pending_children

        # The stop prohibits further subtree work, including registered
        # children no completed parent turn has started yet.
        for member in members:
            withdraw_pending_children(runner_directory / "sessions" / member)

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


def _interrupt_allocation(runner: Path, alias: str) -> dict:
    """Address only an attributed pre-Session allocation's original live owner."""
    directory = runner / "sessions" / alias
    if (Path(alias).name != alias or alias in {".", ".."} or directory.resolve() != directory
            or any(os.path.lexists(directory / name) for name in
                   ("mapping.yml", "session.yml", "native-session.yml", "execution.yml"))):
        raise _invalid_mapping()
    launch_file = directory / "launch.yml"
    try:
        if launch_file.is_symlink():
            raise _invalid_mapping()
        launch = yaml.safe_load(launch_file.read_text())
        mapping = launch["mapping"]
        if (not isinstance(launch, dict) or not isinstance(mapping, dict)
                or launch.get("operation") != "launch" or mapping.get("alias") != alias
                or any(field not in mapping for field in SESSION_BINDING_FIELDS)):
            raise _invalid_mapping()
        from graphtraj.graph.task_graph import _load_states

        configuration = load_project_configuration(runner_project_root(runner))
        task_directory, task = _load_states(configuration.state / "tasks")[mapping["task_id"]]
        trace = task_directory / "teams" / str(mapping["team_generation"]) / "traces" / alias / "events.jsonl"
        worktree = configuration.agent_worktrees / (mapping["task_id"] + "-" + task["task_name"])
        if (mapping.get("trace_file") != str(trace)
                or mapping.get("worktree_path") != str(worktree)):
            raise _invalid_mapping()
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as error:
        raise _invalid_mapping() from error
    require_descendant_authority(runner, alias, mapping)
    with execution_start_lock(runner):
        if any(os.path.lexists(directory / name) for name in ("mapping.yml", "session.yml", "native-session.yml")):
            raise RunnerError("operation-failed", "Session creation completed; retry interruption by alias.")
        heartbeat = read_heartbeat(directory)
        if heartbeat is None:
            return _stop_before_runtime(directory, mapping)
        if heartbeat.get("alias") != alias:
            raise _invalid_mapping()
        if not ownership_is_held(directory, heartbeat["worker_pid"]):
            failure = directory / "launch-error.yml"
            if failure.is_file() and not failure.is_symlink() and valid_terminal_launch_failure(yaml.safe_load(failure.read_text())):
                return {"alias": alias, "interrupt_status": "stopped"}
            raise RunnerError("operation-failed", "The allocation has no live native owner or confirmed terminal failure.")
        control = Path(heartbeat.get("control_directory", ""))
        if (control.parent != directory or control.resolve() != control or not control.is_dir()
                or not isinstance(heartbeat.get("execution_id"), str) or not heartbeat["execution_id"]
                or type(heartbeat.get("runtime_pid")) is not int or heartbeat["runtime_pid"] <= 0):
            raise _invalid_mapping()
        write_yaml_durably(directory / "stop.yml", {"alias": alias})
    session_operation({**heartbeat, "session": None}, "interrupt")
    return {"alias": alias, "interrupt_status": "interrupted"}


def _stop_before_runtime(directory: Path, mapping: dict) -> dict:
    """Stop a verified pre-Runtime allocation under the held startup lock.

    Worker writes its owner lock before creating a Runtime. The exact retained
    pre-start inventory therefore excludes an already-created Runtime; the
    native process observation addresses a Worker still waiting before that
    boundary. The stop barrier also prevents a late spawn from crossing it.
    """
    allowed = {'launch.yml', 'events.jsonl', 'worker-stderr.log', 'stop.yml'}
    try:
        entries = list(directory.iterdir())
        if (mapping.get('runtime') != 'codex'
                or {path.name for path in entries} - allowed
                or any(path.is_symlink() or not path.is_file() for path in entries)
                or (directory / 'worker-stderr.log').stat().st_size != 0):
            raise ValueError('Allocation is not before Runtime ownership')
        records = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
        if records != [{'type': 'runtime', 'runtime': 'codex'}, {'type': 'runner-execution-start'}]:
            raise ValueError('Allocation contains other execution evidence')
        trace = Path(mapping['trace_file'])
        if trace.is_symlink() or not trace.is_file() or trace.stat().st_size:
            raise ValueError('Trace is not an unstarted allocation')
        workers = unstarted_worker_processes(directory / 'launch.yml')
        write_yaml_durably(directory / 'stop.yml', {'alias': mapping['alias']})
        for pid in workers:
            # Repeat identity validation immediately before the existing stop
            # primitive; do not signal a process whose binding has changed.
            if pid in unstarted_worker_processes(directory / 'launch.yml') and not stop_worker(pid):
                raise OSError('Worker stopping was not confirmed')
        if unstarted_worker_processes(directory / 'launch.yml'):
            raise OSError('A Worker still references this launch')
        if ({path.name for path in directory.iterdir()} - allowed
                or (directory / 'worker-stderr.log').stat().st_size != 0):
            raise OSError('Allocation evidence changed during stopping')
        evidence = {'runtime_started': False, 'worker_pids': workers, 'startup_barrier': True}
        write_yaml_durably(directory / 'launch-error.yml', runtime_launch_failure(
            'RUNTIME_EXECUTION_INTERRUPTED',
            'Native pre-Runtime stop confirmed under the execution startup lock.',
            json.dumps(evidence, sort_keys=True),
            terminal_confirmed=True,
        ))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        raise RunnerError('operation-failed',
                          'Pre-Runtime allocation stop could not be confirmed: ' + str(error)) from error
    return {'alias': mapping['alias'], 'interrupt_status': 'stopped',
            'evidence': evidence}


# A Worker answers interrupt only after its own close and confirmation, waiting
# at most 30 seconds for that (claude/execution.py:647, pi/managed_session.py:552).
# The ordinary control deadline covers the remaining round trip.
INTERRUPT_RESPONSE_SECONDS = 30 + OPERATION_TIMEOUT_SECONDS


def _interrupt_session(
    alias: str, session_directory: Path, mapping: Dict[str, Any]
) -> Dict[str, str]:
    """Confirm a terminal member or await its exact native Turn interruption."""
    execution_file = session_directory / "execution.yml"
    if os.path.lexists(str(execution_file)):
        try:
            read_terminal_outcome(execution_file)
        except RunnerError:
            if read_execution_result(execution_file).get('terminal_confirmed') is not False:
                raise
            return _confirm_termination(alias, session_directory, mapping)
        return {"alias": alias, "interrupt_status": "stopped"}
    try:
        session_operation(mapping, "interrupt", response_timeout=INTERRUPT_RESPONSE_SECONDS)
    except RunnerError:
        # Native completion can precede the Worker's terminal-file drain.
        # Reuse its live terminal acknowledgement as well as durable outcomes;
        # lost contact or a stale heartbeat still cannot establish stopping.
        owning = owning_execution(alias, session_directory, mapping)
        if owning is None:
            return {"alias": alias, "interrupt_status": "stopped"}
        if owning["activity"] != "abnormal":
            raise
        # The owner released its lock without a terminal record. Retain that
        # exit as an unconfirmed outcome; only the Runtime's own termination
        # confirmation, retained separately, can then establish stopping.
        _record_owner_exit(alias, session_directory, mapping)
        return _interrupt_session(alias, session_directory, mapping)
    return {"alias": alias, "interrupt_status": "interrupted"}


def _running_reports_only(directory: Path) -> bool:
    """Return whether the running execution was started as a report collection.

    Only a resume starts a later execution, and each one rewrites resume.yml
    under the alias lock, so that record names the running one. A first
    launch has none; an unreadable record admits nothing.
    """
    try:
        resume = yaml.safe_load((directory / "resume.yml").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return False
    return isinstance(resume, dict) and resume.get("reports_only") is True


def _record_owner_exit(alias: str, directory: Path, mapping: dict) -> None:
    """Retain an exited owner's missing end as an unconfirmed runtime error.

    Written under the startup lock only while the same execution is mapped,
    its owner lock is released and no terminal record exists. A record that
    an abnormal response already wrote is kept. No native terminal event is
    implied: ``terminal_confirmed`` stays false.
    """
    runner = directory.parent.parent
    execution_file = directory / "execution.yml"
    with execution_start_lock(runner):
        current, _ = read_alias_mapping(runner, alias)
        if current != mapping or ownership_is_held(directory, mapping["worker_pid"]):
            raise RunnerError("termination-unconfirmed",
                              "The execution changed while its owner exit was being recorded.")
        if os.path.lexists(str(execution_file)):
            return
        write_yaml_durably(execution_file, {
            "outcome": "runtime-error",
            "session_id": mapping["session"],
            "execution_id": mapping["execution_id"],
            "terminal_confirmed": False,
            "error": {"code": "owner-exited",
                      "message": "The process owning this execution exited before reporting its end."},
        })


def _confirm_termination(alias: str, directory: Path, mapping: dict) -> dict:
    """Recheck an ended owner's native evidence without replacing its failure.

    Startup and confirmation share the same lock. The Adapter may stop an
    exactly verified owned group; resume and administrative changes stay separate.
    """
    runner = directory.parent.parent
    with execution_start_lock(runner):
        current, _ = read_alias_mapping(runner, alias)
        if current != mapping or ownership_is_held(directory, mapping['worker_pid']):
            raise RunnerError('termination-unconfirmed', 'The original Worker still owns this execution or its mapping changed.')
        adapter = runtime_adapter.select_runtime_adapter(mapping['runtime'])
        confirm = getattr(adapter, 'confirm_termination', None)
        if confirm is None:
            raise RunnerError('termination-unconfirmed', 'This Runtime has no retained native termination confirmation.')
        request, _, _ = _read_session_resume_request(directory, mapping)
        try:
            evidence = confirm(directory, mapping, request)
        except RuntimeAdapterError as error:
            raise RunnerError(error.code, error.message) from error
        execution_file = directory / 'execution.yml'
        receipt = {
            **{key: mapping[key] for key in ('session', 'execution_id', 'worker_pid', 'runtime_pid')},
            'execution_sha256': hashlib.sha256(execution_file.read_bytes()).hexdigest(),
            'original_execution': read_execution_result(execution_file),
            'terminal_confirmed': True, 'evidence': evidence,
        }
        path = directory / f"terminal-confirmation-{mapping['execution_id']}.yml"
        write_yaml_durably(path, receipt)
        read_terminal_outcome(execution_file)
    return {'alias': alias, 'interrupt_status': 'stopped', 'evidence': str(path)}


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
            stopped = interrupt_session(alias, runner_project_root(runner_directory))
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
            # Root host recovery updates the authoritative current mapping;
            # its original launch remains history. Worker admission still
            # compares the new job against that current binding in full.
            if field != 'parent_connection' or mapping.get('parent') is not None
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
    # Session loading remains owned by the Worker and its execution budget;
    # ordinary control deadlines must not reject a still-starting Session.
    while True:
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
        for evidence in (configuration.state / "tasks").iterdir():
            if (
                evidence.is_symlink()
                or not evidence.is_dir()
                or not evidence.name.startswith(mapping["task_id"] + "-")
            ):
                continue
            task = yaml.safe_load((evidence / "task.yml").read_text(encoding="utf-8"))
            if isinstance(task, dict) and task.get("task_id") == mapping["task_id"]:
                matches.append((evidence, task))
        if len(matches) != 1:
            raise ValueError("missing Task context")
        evidence, task = matches[0]
        task_name = task.get("task_name")
        if (
            not isinstance(task, dict)
            or not isinstance(task_name, str)
            or not task_name
        ):
            raise ValueError("invalid Task context")
        environment = {
            "GRAPHTRAJ_ROLE": mapping["role"],
            "GRAPHTRAJ_EVIDENCE": str(evidence),
            "GRAPHTRAJ_TASK_ID": mapping["task_id"],
            "GRAPHTRAJ_TASK_NAME": task_name,
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
    Markdown paths within this Task's evidence establish report ownership;
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
