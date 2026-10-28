"""Runtime-neutral background owner for one Session execution."""

from __future__ import annotations

from graphtraj.configuration.project_configuration import runner_project_root

import json
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import yaml

from graphtraj.execution.runner_connection import worker_connection
from graphtraj.execution.execution_budget import (
    ExecutionBudgetMonitor,
    execution_budget_monitor_from_environment,
    execution_budget_stage,
)
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.execution.runner_heartbeat import (
    HEARTBEAT_INTERVAL_SECONDS,
    hold_ownership,
    execution_start_lock,
    write_heartbeat,
)
from graphtraj.execution.runner_status import (
    conflicting_binding_field,
    require_execution_allowed,
)
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_process import OPERATION_TIMEOUT_SECONDS
from graphtraj.execution.runner_transport import runtime_launch_failure
from graphtraj.runtimes.runtime_adapter import (
    RuntimeAdapterError, RuntimeTurn, select_runtime_adapter, runtime_process_owner,
)


# A stopped Worker must exit while stop_worker (runner_process.py) still waits
# to reap it; its last notice transport gets the rest of that window.
STOP_EXIT_MARGIN_SECONDS = 2.0
DELIVERY_JOIN_SECONDS = OPERATION_TIMEOUT_SECONDS - STOP_EXIT_MARGIN_SECONDS


def run(job_file: Path) -> int:
    """Own one current Session execution without creating a Turn record."""

    session_directory = job_file.parent
    turn_handle: RuntimeTurn | None = None
    mapping_recorded = False
    terminal_published = False
    terminal: dict[str, object] | None = None
    operation = "launch"
    previous_sigterm = None
    budget_monitor: ExecutionBudgetMonitor | None = None
    monitor_stop: threading.Event | None = None
    monitor_thread: threading.Thread | None = None
    budget_stopped = threading.Event()
    startup_lock = None
    execution_mapping: dict[str, object] | None = None
    restored_cwd: Path | None = None
    task_agent = None
    agent_reported = False

    def request_termination(signum: int, frame: object) -> None:
        """Pass Worker/budget termination to the owned native execution."""
        if turn_handle is not None:
            turn_handle.terminate()

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
            if operation == "resume" and job.get("restored_cwd") is True:
                restored_cwd = Path(base_mapping["worktree_path"])
            # The Session's own record owns the Agent Entity and its direct
            # parent, so a launch input or request that disagrees is refused
            # before this Worker starts any Runtime or changes the record.
            _require_recorded_binding(session_directory, operation, base_mapping)
            monitor_execution_budget = job.get("monitor_execution_budget", False)
            if not isinstance(monitor_execution_budget, bool):
                raise ValueError("budget monitor request is invalid")
            if monitor_execution_budget:
                budget_monitor = execution_budget_monitor_from_environment(
                    base_mapping
                )
                if budget_monitor is not None:
                    role = base_mapping.get("role")
                    if not isinstance(role, str) or not role:
                        raise ValueError("session role is invalid")
                    monitor_stop = threading.Event()
                    if budget_monitor.check(role, execution_budget_stage(role)):
                        budget_monitor.deliver_parent_notices(session_directory)
                        raise RuntimeAdapterError(
                            "EXECUTION_BUDGET_STOPPED", "Runner selected stopping before Session creation.",
                            terminal_confirmed=True,
                        )
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
            adapter = select_runtime_adapter(runtime)

            # A report collection resumed into a stopped subtree keeps its
            # admission; it drives no children and samples no budget.
            reports_only = operation == "resume" and job.get("reports_only") is True
            startup_lock = execution_start_lock(session_directory.parent.parent)
            try:
                require_execution_allowed(
                    session_directory.parent.parent, base_mapping["alias"], base_mapping,
                    reports_only=reports_only,
                )
            except RunnerError as error:
                raise RuntimeAdapterError(error.code, error.message, terminal_confirmed=True) from error

            # Publish ownership from Worker startup, and keep publishing through
            # every normal wait until this Worker stops holding the Session.
            # The stream stays referenced here: closing it, or ending the
            # process, is what releases the ownership the heartbeat names.
            owner_lock = hold_ownership(session_directory, os.getpid())
            heartbeat = {
                "alias": base_mapping["alias"],
                "worker_pid": os.getpid(),
            }
            heartbeat_stop = threading.Event()
            heartbeat_thread = threading.Thread(
                target=_publish_heartbeat,
                args=(session_directory, heartbeat, heartbeat_stop),
                daemon=True,
            )
            heartbeat_thread.start()

            def record_created(session: str, runtime_pid: int) -> None:
                """Bind the native Session and register assignment before its first turn.

                This runs while the Runtime waits for its startup hook reply, so
                it never waits for the project startup lock held by unrelated
                startups. ``record_session`` rechecks stops once this execution
                is addressable; see there.
                """
                nonlocal mapping_recorded, execution_mapping
                try:
                    require_execution_allowed(session_directory.parent.parent, base_mapping["alias"], base_mapping,
                                              reports_only=reports_only)
                except RunnerError as error:
                    raise RuntimeAdapterError(error.code, error.message) from error
                if operation == "resume" and session != expected_session:
                    raise RuntimeAdapterError(
                        "RUNTIME_SESSION_NOT_RESUMABLE", "The mapped Runtime session could not be resumed.",
                    )
                mapping = {
                    **{key: value for key, value in base_mapping.items()
                       if key not in {"execution_id", "last_outcome"}},
                    "session": session, "worker_pid": os.getpid(),
                    "runtime_pid": runtime_pid, "control_directory": control_directory,
                    **_agent_reference(task_agent, session, runtime_pid),
                }
                write_yaml_durably(session_directory / "mapping.yml", mapping)
                execution_mapping = mapping
                mapping_recorded = True
                launch_file = session_directory / "launch.yml"
                assignment = yaml.safe_load(launch_file.read_text()).get("member_registration")
                if assignment is not None:
                    try:
                        _register_created_member(launch_file, mapping, created=operation == "launch")
                    except (RunnerError, OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as error:
                        raise RuntimeAdapterError(
                            "MEMBER_REGISTRATION_FAILED", str(error), terminal_confirmed=True,
                        ) from error

                if budget_monitor is not None:
                    if operation == "launch":
                        budget_monitor.record_session(role, execution_budget_stage(role))
                    if budget_monitor.check(role, execution_budget_stage(role)):
                        budget_stopped.set()
                        assert turn_handle is not None
                        turn_handle.terminate()

            def record_process(runtime_pid: int, outcome: dict | None) -> None:
                """Retain control of the owned process before native Session creation."""
                assert turn_handle is not None
                heartbeat.update(runtime_pid=runtime_pid, execution_id=turn_handle.execution_id,
                                 control_directory=control_directory)
                if outcome is not None:
                    heartbeat["process_outcome"] = outcome
                write_heartbeat(session_directory, heartbeat)
                startup_lock.close()

            def record_session(session: str, runtime_pid: int) -> None:
                """Persist native execution identity before acknowledging its caller."""
                nonlocal mapping_recorded, execution_mapping
                if operation == "resume" and session != expected_session:
                    raise RuntimeAdapterError(
                        "RUNTIME_SESSION_NOT_RESUMABLE",
                        "The mapped Runtime session could not be resumed.",
                    )
                previous_outcome = _previous_outcome(
                    session_directory / "execution.yml"
                )
                assert turn_handle is not None and turn_handle.execution_id is not None
                mapping = {
                    **{
                        key: value
                        for key, value in base_mapping.items()
                        if key != "last_outcome"
                    },
                    "session": session,
                    "worker_pid": os.getpid(),
                    "runtime_pid": runtime_pid,
                    "execution_id": turn_handle.execution_id,
                    "control_directory": control_directory,
                    **_agent_reference(task_agent, session, runtime_pid),
                }
                if previous_outcome is not None:
                    mapping["last_outcome"] = previous_outcome
                if causes:
                    _append_follow_up(session_directory / "events.jsonl", causes)
                (session_directory / "execution.yml").unlink(missing_ok=True)
                write_yaml_durably(session_directory / "mapping.yml", mapping)
                execution_mapping = mapping
                mapping_recorded = True
                heartbeat["execution_id"] = mapping["execution_id"]
                write_heartbeat(session_directory, heartbeat)
                startup_lock.close()

                # A stop publisher writes stop.yml under the startup lock, then
                # interrupts the mapping it reads. This execution's mapping is
                # now durable before stop facts are read, so either this check
                # sees the stop or the publisher interrupts this execution.
                try:
                    require_execution_allowed(session_directory.parent.parent, base_mapping["alias"], base_mapping,
                                              reports_only=reports_only)
                except RunnerError as error:
                    raise RuntimeAdapterError(error.code, error.message) from error

            if runtime in {'pi', 'dsh'}:
                from graphtraj.configuration.project_configuration import core_directory
                from graphtraj.execution.task_agents import native_directory

                root = Path(request['harness_root'])
                if core_directory(root) != root / '.graphtraj':
                    request = {**request, 'native_directory': str(native_directory(root, base_mapping['alias'], runtime))}
            turn_handle = adapter.managed_execution(
                request, prompt, session_directory, record_session,
                job.get("context_evidence", {}),
                expected_session=expected_session if operation == "resume" else None,
                trace_file=Path(base_mapping["trace_file"]),
                session_created=record_created,
            )
            from graphtraj.execution.task_agents import begin_task_agent

            # The core records this execution and its Agent before native work.
            runner_directory = session_directory.parent.parent
            task_agent = begin_task_agent(
                runner_project_root(runner_directory), runner_directory, operation, base_mapping, prompt, turn_handle,
            )
            previous_sigterm = signal.signal(signal.SIGTERM, request_termination)
            if budget_monitor is not None and monitor_stop is not None:
                monitor_thread = threading.Thread(
                    target=_monitor_execution_budget,
                    args=(budget_monitor, base_mapping, session_directory, monitor_stop,
                          budget_stopped, turn_handle.terminate),
                    daemon=True,
                )
                monitor_thread.start()
            try:
                with worker_connection(
                    session_directory, task_agent.operate if task_agent is not None else turn_handle.operate,
                ) as control_directory:
                    with runtime_process_owner(record_process):
                        result = turn_handle.run()
                    terminal = _terminal_turn(result)
                    if budget_stopped.is_set() and terminal["outcome"] == "interrupted":
                        terminal["budget_stopped"] = True
                    # The core ends the execution before the terminal record lets
                    # a continuation start the next one.
                    if task_agent is not None:
                        task_agent.finished(terminal)
                        agent_reported = True
                    write_yaml_durably(session_directory / "execution.yml", terminal)
                    terminal_published = True
            finally:
                heartbeat_stop.set()
                heartbeat_thread.join()
                if monitor_stop is not None:
                    monitor_stop.set()
                if monitor_thread is not None:
                    monitor_thread.join()
        except RuntimeAdapterError as error:
            if startup_lock is not None:
                startup_lock.close()
            if mapping_recorded:
                terminal = {
                    "outcome": "runtime-error",
                    "terminal_confirmed": error.terminal_confirmed,
                    "error": {"code": error.code, "message": error.message},
                }
                if budget_stopped.is_set() and error.code == "RUNTIME_EXECUTION_INTERRUPTED":
                    terminal.update(outcome="interrupted", terminal_confirmed=True, budget_stopped=True)
            else:
                _write_worker_error(
                    session_directory,
                    operation,
                    error.code,
                    error.message,
                    terminal_confirmed=error.terminal_confirmed,
                )
        except (KeyError, OSError, TypeError, ValueError, yaml.YAMLError) as error:
            if startup_lock is not None:
                startup_lock.close()
            if mapping_recorded:
                terminal = {
                    "outcome": "runtime-error",
                    "error": {"code": "RUNTIME_WORKER_FAILED", "message": str(error)},
                }
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
            # Reply cleanup may have allowed a successor to take ownership.
            if task_agent is not None and not agent_reported:
                task_agent.finished(terminal)
                agent_reported = True
            if not terminal_published:
                write_yaml_durably(session_directory / "execution.yml", terminal)
            if execution_mapping is not None:
                from graphtraj.execution.runner_control import deliver_execution_end

                # A successor may already own mapping.yml. This notice belongs
                # to the native execution that produced this terminal result.
                deliver_execution_end(session_directory, execution_mapping, terminal,
                                      parent_input=job.get('parent_input') is not False,
                                      driver_reports_end=operation == "launch"
                                      and job.get("driver_reports_end") is True)
            return 0
    finally:
        if startup_lock is not None:
            startup_lock.close()
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)
        if task_agent is not None and not agent_reported:
            # A start that failed before any terminal record still ends the core execution.
            task_agent.finished({"outcome": "runtime-error", "terminal_confirmed": False,
                                 "error": {"code": "RUNTIME_WORKER_FAILED",
                                           "message": "The member execution did not start."}})
        if restored_cwd is not None:
            from graphtraj.execution.runner_control import _remove_restored_cwd

            # The continuation-only cwd of a cleaned Task ends with its execution.
            _remove_restored_cwd(session_directory, restored_cwd)
    return 1


def _agent_reference(task_agent: object, session: str, runtime_pid: int) -> dict[str, str]:
    """Report the native Session to the core and return the mapping's Agent reference.

    A mapping recorded before core Agents keeps its existing path and gains none.
    """
    if task_agent is None:
        return {}
    task_agent.run.events.session(session)
    task_agent.run.events.process(runtime_pid=runtime_pid)
    return {"agent": task_agent.run.agent}


def _register_created_member(
    job_file: Path, mapping: dict[str, object], *, created: bool,
) -> None:
    """Register only a native Session owned by this trusted Runner creation job.

    Runtime files are protected from Agent writes. In addition to that boundary,
    verify the canonical launch file, persisted native identity and live Worker
    ownership; an Agent's request, role or environment cannot grant this path.
    The caller does not hold the project startup lock; a stop published
    meanwhile is rechecked before the first turn and refuses the execution.
    """
    from graphtraj.execution.runner_heartbeat import ownership_is_held
    from graphtraj.execution.runner_status import read_alias_mapping
    from graphtraj.graph.delivery_state import apply_delivery_state_request, read_team
    from graphtraj.graph.delivery_worldline import read_worldline
    from graphtraj.graph.task_graph import _load_states
    from graphtraj.workspace.runner_project import discover_project, discover_project_root

    project = discover_project(discover_project_root(job_file.parent), require_clean_integration=False)
    directory = project.runner_directory / "sessions" / mapping["alias"]
    recorded, _ = read_alias_mapping(project.runner_directory, mapping["alias"])
    if (
        job_file != directory / "launch.yml" or job_file.is_symlink()
        or recorded != mapping or mapping["worker_pid"] != os.getpid()
        or not ownership_is_held(directory, os.getpid())
        or yaml.safe_load((directory / "session.yml").read_text())["session"] != mapping["session"]
    ):
        raise ValueError("Member registration requires the owning Runner creation job")
    job = yaml.safe_load(job_file.read_text())
    launch_binding = job["mapping"]
    if not created and mapping.get('parent') is None:
        # Recovery may change only the root's delivery host. Admission has
        # already checked this execution against the current durable mapping.
        launch_binding = {**launch_binding, 'parent_connection': mapping.get('parent_connection')}
    if job.get("operation") != "launch" or conflicting_binding_field(launch_binding, mapping):
        raise ValueError("Member registration conflicts with the trusted launch binding")
    assignment = job["member_registration"]
    if not isinstance(assignment, dict) or set(assignment) != {"member", "replaces"}:
        raise ValueError("Invalid Runner member assignment")
    task_directory, task = _load_states(project.state_directory / "tasks")[mapping["task_id"]]
    team_file = task_directory / "teams" / str(mapping["team_generation"]) / "team.yml"
    if not created:
        if (task["active_team_ordinal"] != mapping["team_generation"] or not team_file.is_file()
                or not any(member["session_ref"] == mapping["alias"]
                           for member in read_team(team_file)["members"].values())):
            raise ValueError("A resumed task Session must already be a registered member")
        return
    predecessor = next(
        event["event_id"] for event in reversed(read_worldline(project.state_directory, project.harness_root))
        if event.get("task_id") == mapping["task_id"]
    )
    request = {
        "task_id": mapping["task_id"], "caused_by_event_ids": [predecessor],
        "evidence_refs": [(directory / "mapping.yml").relative_to(project.harness_root).as_posix()],
    }
    if not team_file.exists():
        expected = (task["active_team_ordinal"] or 0) + 1
        if mapping["team_generation"] != expected or assignment["replaces"] is not None:
            raise ValueError("The created Session does not start the next Team")
        request.update(
            phase="start", worktree=Path(mapping["worktree_path"]).relative_to(project.harness_root).as_posix(),
            branch="agent/" + task["task_id"] + "-" + task["task_name"],
            members={assignment["member"]: {"role": mapping["role"], "session_ref": mapping["alias"]}},
        )
    else:
        if task["active_team_ordinal"] != mapping["team_generation"]:
            raise ValueError("The created Session does not belong to the active Team")
        team = read_team(team_file)
        member = assignment["member"]
        if assignment["replaces"] is not None:
            previous, previous_directory = read_alias_mapping(project.runner_directory, assignment["replaces"])
            if any(previous[key] != mapping[key] for key in ("parent", "task_id", "team_generation", "role")):
                raise ValueError("Replacement must retain the actual parent and task binding")
            retirement = yaml.safe_load((previous_directory / "session.yml").read_text()).get("retirement")
            member = retirement["member"] if retirement else None
            if member not in team["members"] or team["members"][member]["session_ref"] is not None:
                raise ValueError("Replacement must identify a vacant retired member")
            phase = "member"
        else:
            phase = "member"
            if member in team["members"] and team["members"][member]["session_ref"] is not None:
                member = mapping["alias"]
        request.update(phase=phase, member=member, role=mapping["role"], session_ref=mapping["alias"])
    apply_delivery_state_request(project.state_directory, project.harness_root, request, request)


def _require_recorded_binding(
    session_directory: Path, operation: str, requested: dict[str, object]
) -> None:
    """Refuse a request that would change the entity this Session records.

    A launch establishes one Agent Entity and its direct parent. Every later
    execution resumes that recorded entity, so a re-submitted launch input
    cannot create a second entity for the alias and a modified request parent
    cannot re-parent the existing one. The refusal keeps the record readable
    and leaves its own failure document as evidence.
    """
    mapping_file = session_directory / "mapping.yml"
    if not os.path.lexists(str(mapping_file)):
        return
    try:
        recorded = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        recorded = None
    if not isinstance(recorded, dict):
        raise RuntimeAdapterError(
            "AGENT_BINDING_CONFLICT",
            "The Session record could not be read, so this request cannot own it.",
        )
    if operation == "launch":
        reason = "The Session record already binds this alias to an Agent Entity."
    else:
        field = conflicting_binding_field(recorded, requested)
        if field is None:
            return
        reason = "The request changes the recorded {0} of this Agent Entity.".format(field)
    raise RuntimeAdapterError("AGENT_BINDING_CONFLICT", reason)


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


def _publish_heartbeat(
    session_directory: Path,
    record: dict[str, object],
    stop: threading.Event,
) -> None:
    """Keep one Session's ownership record current independently of its work."""
    while not stop.is_set():
        write_heartbeat(session_directory, record)
        stop.wait(HEARTBEAT_INTERVAL_SECONDS)


def _monitor_execution_budget(
    monitor: ExecutionBudgetMonitor,
    mapping: dict[str, object],
    session_directory: Path,
    stop: threading.Event,
    budget_stopped: threading.Event,
    terminate: Callable[[], bool],
) -> None:
    """Enforce stops independently of parent notice transport or handling."""
    role = mapping["role"]
    assert isinstance(role, str)
    delivery: threading.Thread | None = None
    retry_at = 0.0
    # Only this Session's own notices keep its delivery going (372 6c).
    observer = session_directory.name

    def deliver() -> None:
        """Retry transient native failures within the existing cleanup window.

        This thread is independent of termination. A stop's last notice gets
        the same retry opportunity even after the monitor stops sampling work.
        """
        deadline = time.monotonic() + OPERATION_TIMEOUT_SECONDS
        while True:
            try:
                if monitor.deliver_parent_notices(session_directory):
                    return  # Held for the stopped parent's continuation.
            except (RunnerError, OSError, ValueError, yaml.YAMLError):
                pass
            if (mapping.get("parent") is None and not mapping.get("parent_connection")) or not monitor.pending_parent_notices(observer):
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(1, remaining))

    while not stop.is_set():
        stopped = monitor.check(role, execution_budget_stage(role))
        # Termination is requested before any notice lock or transport. The
        # managed execution retains this request even before thread/start ends.
        if stopped:
            budget_stopped.set()
            terminate()
        if (session_directory / "launch.yml").is_file():
            pending = {notice["key"] for notice in monitor.pending_parent_notices(observer)}
            if pending and time.monotonic() >= retry_at and (delivery is None or not delivery.is_alive()):
                retry_at = time.monotonic() + 1
                delivery = threading.Thread(target=deliver, daemon=True)
                delivery.start()
        if stopped:
            break
        stop.wait(0.05)
    # The native execution has already received interruption independently.
    # Allow its outstanding transport to finish, bounded inside the stop's own
    # reap window; an unavailable parent cannot retain the Worker forever.
    if delivery is not None:
        delivery.join(timeout=DELIVERY_JOIN_SECONDS)


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


def _terminal_turn(turn: object) -> dict[str, object]:
    if not isinstance(turn, dict):
        raise ValueError("Runtime turn result is not a mapping")
    outcome = turn.get("outcome")
    if outcome not in {"completed", "runtime-error", "interrupted"}:
        raise ValueError("Runtime turn result has an invalid outcome")
    return dict(turn)


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
    """Own a native execution and any child Batch registered during its turn."""
    if len(sys.argv) != 2:
        raise SystemExit(2)
    job_file = Path(sys.argv[1])
    result = run(job_file)
    if result == 0 and yaml.safe_load(job_file.read_text()).get("drive_children", False):
        from graphtraj.teams.team_round import run_session_children

        try:
            run_session_children(job_file)
        except RunnerError as error:
            if error.code != "EXECUTION_BUDGET_STOPPED":
                raise
            # Child execution may stop a resumed parent after its first turn.
            # Preserve that confirmed stop across the outer Worker boundary.
            job = yaml.safe_load(job_file.read_text())
            _write_worker_error(
                job_file.parent, job.get("operation", "launch"),
                error.code, error.message, terminal_confirmed=True,
            )
            result = 1
    raise SystemExit(result)


if __name__ == "__main__":
    main()
