"""Formal task execution with retained Ticket, Team and Session evidence."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from graphtraj.workspace.project_files import ignore_worktree_documents
from graphtraj.runtimes.codex.codex_adapter import (
    codex_connection_environment,
    refresh_codex_report_paths,
)
from graphtraj.execution.execution_budget import (
    caller_notice_fd,
    execution_budget_monitor,
)
from graphtraj.configuration.role_definitions import resolve_child_role
from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.graph.delivery_worldline import append_project_worldline_event, read_worldline
from graphtraj.configuration.project_roles import (
    ProjectRolesError,
    configured_role_name,
)
from graphtraj.execution.runner_batch import (
    read_batch,
    read_session_task,
    retain_batch,
    valid_ticket_id,
)
from graphtraj.execution.runner_capacity import capacity_positions
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.execution.runner_heartbeat import execution_start_lock
from graphtraj.execution.runner_models import (
    Batch,
    LaunchResponse,
    RunnerError,
    Task,
)
from graphtraj.workspace.runner_project import (
    discover_project,
    discover_project_root,
    provision_worktree,
    run_git,
)
from graphtraj.execution.runner_status import (
    caller_alias,
    conflicting_binding_field,
    owning_execution,
    read_alias_mapping,
    read_terminal_outcome,
    session_occupied,
    require_execution_allowed,
    require_direct_authority,
    require_stopped_subtree,
)
from graphtraj.execution.runner_transport import record_runtime_identity
from graphtraj.runtimes import runtime_adapter
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError
from graphtraj.graph.ticket_graph import _load_states


_AGENT_EVIDENCE_ERROR = "AGENT_EVIDENCE_INVALID"


def register_child_batch(batch: Batch, cwd: Path, registration: Path) -> LaunchResponse:
    """Register authorized direct children for the actual calling Session."""

    # The entry's own working directory locates the project, and the Runner's
    # own record decides which Session this registration belongs to; a request
    # cannot name another Session's registration path.
    project = discover_project(
        discover_project_root(cwd), require_clean_integration=False
    )
    caller = caller_alias(project.runner_directory)
    parent = (
        read_alias_mapping(project.runner_directory, caller)[0]
        if caller is not None else None
    )
    if (
        parent is None
        or registration
        != project.runner_directory / "sessions" / caller / "child-registration.yml"
    ):
        raise RunnerError(
            "authority-denied",
            "A caller may register a direct child Batch only "
            "through its own Session registration.",
        )
    parent_ticket = parent["ticket_id"]
    _require_dispatch_roles(project, batch, parent)
    if any(task.ticket_id != parent_ticket for task in batch.tasks):
        raise RunnerError("authority-denied", "Children must belong to their parent's Ticket.")
    limit = load_project_configuration(project.harness_root).dispatch_depth
    depth = 1
    parent_alias = caller
    # Count retained Session ancestry, not Batches or resumptions.
    while parent_alias is not None:
        depth += 1
        if depth > limit:
            raise RunnerError(
                "authority-denied",
                f"The child Batch exceeds project dispatch_depth={limit}. No child registered.",
            )
        ancestor, _ = read_alias_mapping(project.runner_directory, parent_alias)
        parent_alias = ancestor["parent"]
    from graphtraj.teams.team_replacement import require_active_session

    require_active_session(project, caller)
    children = [
        {"ticket_id": task.ticket_id, "role": task.role,
         "alias": _agent_alias(project, task, task.role, parent["team_generation"]),
         "launch_status": "registered"}
        for task in batch.tasks
    ]
    try:
        with execution_start_lock(project.runner_directory):
            require_execution_allowed(
                project.runner_directory, caller,
                read_alias_mapping(project.runner_directory, caller)[0],
            )
            with registration.open("x", encoding="utf-8") as stream:
                retained = retain_batch(project.state_directory, batch)
                yaml.safe_dump({"retained_batch_file": str(retained), "tasks": children}, stream)
    except (OSError, yaml.YAMLError) as error:
        raise RunnerError("BATCH_RETENTION_FAILED", "The parent worker could not register the child Batch.") from error
    return LaunchResponse(
        document={
            "retained_batch_file": str(retained),
            "tasks": children,
        },
        succeeded=True,
    )


def _task_policy(task: Task, role: str | None = None) -> str:
    """Return the fixed policy applied to this invocation."""

    if role is None or task.role == role:
        return task.policy_role or task.role
    return role


def _require_dispatch_roles(project: Any, batch: Batch, parent: dict | None) -> None:
    """Validate every configured direct edge before retaining or starting work."""
    parent_reference = parent.get("role_reference", parent["role"]) if parent else None
    for task in batch.tasks:
        reference = task.role_reference or task.role
        if not project.roles.permits_dispatch(parent_reference, reference):
            raise RunnerError("authority-denied", "role_tree does not permit this direct dispatch.")
        if task.inline_preset is None:
            try:
                project.roles.preset(reference)
            except ProjectRolesError as error:
                raise RunnerError("ROLE_NOT_CONFIGURED", str(error)) from error


def launch_team_batch(batch: Batch, cwd: Path) -> LaunchResponse:
    """Execute the selected authorized roles through the common task driver."""
    project = discover_project(cwd, require_clean_integration=False)
    _require_dispatch_roles(project, batch, None)
    return _run_batch_workers(project, batch)


def continue_stopped_ticket(
    ticket_id: str,
    caused_by_event_ids: tuple[str, ...],
    cwd: Path,
    *,
    budget_only: bool = False,
) -> dict[str, Any]:
    """Restore budget permission, optionally leaving all original Sessions stopped."""

    if not valid_ticket_id(ticket_id):
        raise RunnerError("invalid-input", "Ticket identity is invalid.")
    if (
        not caused_by_event_ids
        or len(caused_by_event_ids) != len(set(caused_by_event_ids))
        or any(not event_id for event_id in caused_by_event_ids)
    ):
        raise RunnerError(
            "invalid-input",
            "Continuation requires unique causal Project Worldline event IDs.",
        )
    project = discover_project(cwd, require_clean_integration=False)
    try:
        states = _load_states(project.state_directory / "tickets")
        ticket_directory, state = states[ticket_id]
    except KeyError:
        raise RunnerError("invalid-input", "The supplied Ticket is not registered.") from None
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as error:
        raise RunnerError(
            "TICKET_FILE_INVALID", "The selected registered Ticket is invalid."
        ) from error
    generation = state["active_team_ordinal"]
    roots = {}
    team_context = {}
    if not state["active"]:
        raise RunnerError("invalid-input", "Explicit continuation requires an active Ticket.")
    if generation is None:
        # Before native creation there is no member whose parent can authorize
        # recovery. Use the same actual root caller identity as root dispatch.
        if caller_alias(project.runner_directory) is not None:
            raise RunnerError("authority-denied", "Only the root caller may continue this Ticket.")
        if state["status"] != "ready" or any(
            states[dependency][1]["status"] != "integrated"
            for dependency in state["dependencies"]
        ):
            raise RunnerError("invalid-input", "Explicit continuation requires a ready Ticket.")
    elif state["status"] not in {"implementing", "reviewing", "reworking"}:
        raise RunnerError(
            "invalid-input", "Explicit continuation requires the current active Team."
        )
    if generation is not None:
        try:
            team = yaml.safe_load(
                (ticket_directory / "teams" / str(generation) / "team.yml").read_text(
                    encoding="utf-8"
                )
            )
            if team["status"] != "active":
                raise ValueError("Team is not active")
            members = {}
            for member in team["members"].values():
                alias = member.get("session_ref")
                if isinstance(alias, str):
                    mapping, _ = read_alias_mapping(project.runner_directory, alias)
                    if (mapping["ticket_id"] != ticket_id
                            or mapping["team_generation"] != generation):
                        raise ValueError("Member mapping does not match the current Team")
                    members[alias] = mapping
            team_context = {"team_ordinal": generation, "team_round": team["current_round"]}
            for alias, mapping in members.items():
                parent = mapping["parent"]
                if parent is not None:
                    parent_mapping, _ = read_alias_mapping(project.runner_directory, parent)
                    # Replacing a parent does not promote its retained children to
                    # task roots or transfer their control to the replacement.
                    if (parent_mapping["ticket_id"] == ticket_id
                            and parent_mapping["team_generation"] == generation):
                        continue
                roots[alias] = mapping
            if not roots:
                raise ValueError("The Team has no actual root Sessions")
            # Validate the whole operation before clearing its sampled stop. Explicit
            # subtree stops stay bound to the old entities and require replacement.
            for alias, mapping in roots.items():
                require_direct_authority(project.runner_directory, alias, mapping)
                require_stopped_subtree(project.runner_directory, alias)
                require_execution_allowed(project.runner_directory, alias, mapping)
        except (OSError, TypeError, ValueError, yaml.YAMLError, RunnerError) as error:
            if isinstance(error, RunnerError):
                raise
            raise RunnerError(
                "operation-failed", "The stopped Team cannot resume its retained lifecycle."
            ) from error
    monitor = execution_budget_monitor(ticket_directory, ticket_id, state["ticket_name"])
    if monitor is None or not monitor.is_stopped():
        raise RunnerError(
            "invalid-input", "Explicit continuation requires a sampled stopped Ticket."
        )
    try:
        events = read_worldline(project.state_directory, project.harness_root)
    except (OSError, ValueError) as error:
        raise RunnerError(
            "operation-failed", "The Project Worldline could not be read."
        ) from error
    decisions = [
        event for event in events if event["event_id"] in caused_by_event_ids
    ]
    if len(decisions) != len(caused_by_event_ids):
        raise RunnerError(
            "invalid-input",
            "causal Project Worldline event IDs must identify retained events.",
        )
    try:
        continuation = append_project_worldline_event(
            project.state_directory,
            project.harness_root,
            {
                "kind": "team-continuation-started",
                "caused_by_event_ids": list(caused_by_event_ids),
                "evidence_refs": list(
                    dict.fromkeys(
                        reference
                        for event in decisions
                        for reference in event["evidence_refs"]
                    )
                ),
                "ticket_id": ticket_id,
                **team_context,
            },
        )
    except (OSError, ValueError) as error:
        raise RunnerError(
            "operation-failed", "The continuation could not be recorded in the Project Worldline."
        ) from error
    monitor.continue_after_stop()
    from graphtraj.execution.runner_control import send_instruction

    resumed = [
        send_instruction(
            alias,
            "Continue the accepted task in this original Session within its retained "
            "budget and permissions. Preserve prior reports, results and Trace evidence.",
            cwd, (continuation["event_id"],),
        )
        for alias in roots if not budget_only
    ]
    return {"ticket_id": ticket_id, "continuation_event_id": continuation["event_id"],
            "tasks": resumed}


def _run_batch_workers(
    project: Any,
    batch: Batch,
    retained: Path | None = None,
    parent_alias: str = "",
    capacity_fd: int | None = None,
) -> LaunchResponse:
    """Dispatch the retained Batch through its task workers."""
    notice_fd, close_notice_fd = caller_notice_fd()
    try:
        workers = []
        with capacity_positions(project, len(batch.tasks), capacity_fd) as positions:
            if retained is None:
                retained = retain_batch(project.state_directory, batch)
            for index, position in enumerate(positions):
                try:
                    environment = dict(os.environ)
                    if notice_fd is not None:
                        environment["GRAPHTRAJ_BUDGET_NOTICE_FD"] = str(notice_fd)
                    worker = subprocess.Popen(
                        [sys.executable, "-I", "-m", "graphtraj.teams.team_round",
                         str(retained), str(index), str(position.fileno()), parent_alias],
                        cwd=project.harness_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                        env=environment,
                        pass_fds=(position.fileno(),) if notice_fd is None else (position.fileno(), notice_fd),
                    )
                except OSError as error:
                    worker = RunnerError("RUNTIME_WORKER_START_FAILED", str(error))
                workers.append(worker)
                position.close()
        results = []
        for task, worker in zip(batch.tasks, workers):
            if isinstance(worker, RunnerError):
                results.append(_failed_task(task, worker))
                continue
            output, diagnostic = worker.communicate()
            if worker.returncode == 0:
                results.append(yaml.safe_load(output))
            else:
                results.append(_failed_task(task, RunnerError("RUNTIME_WORKER_FAILED", diagnostic.strip())))
        return LaunchResponse(
            document={"retained_batch_file": str(retained), "tasks": results},
            succeeded=all("error" not in result for result in results),
        )
    finally:
        if close_notice_fd and notice_fd is not None:
            os.close(notice_fd)


def _failed_task(task: Task, error: RunnerError) -> dict[str, Any]:
    return {
        "ticket_id": task.ticket_id, "ticket_name": task.ticket_name,
        "role": task.role, "launch_status": "failed", "error": error.as_document(),
    }


def _registered_ticket_task(project: Any, requested: Task) -> Task:
    """Read one registered Ticket definition without changing its state."""

    ticket_directory = project.state_directory / "tickets" / (
        requested.ticket_id + "-" + requested.ticket_name
    )
    try:
        state = yaml.safe_load((ticket_directory / "ticket.yml").read_text(encoding="utf-8"))
        definition = ticket_directory / state["current_definition"]
        content = definition.read_text(encoding="utf-8")
    except (KeyError, OSError, TypeError, yaml.YAMLError) as error:
        raise RunnerError("TICKET_FILE_INVALID", "The selected registered Ticket is invalid.") from error
    if state.get("ticket_id") != requested.ticket_id or state.get("ticket_name") != requested.ticket_name:
        raise RunnerError("TICKET_FILE_INVALID", "The selected registered Ticket is invalid.")
    return replace(requested, ticket_file=definition.resolve(), ticket_content=content)


def _deliver_ticket(
    project: Any,
    requested: Task,
    retained_batch: Path,
    capacity_fd: int,
    parent_alias: str | None = None,
) -> dict[str, Any]:
    """Prepare a Ticket workspace and run exactly the selected actual member.

    The existing native Worker creates, binds and registers the Session before
    its first turn. Execution completion does not decide task acceptance.
    """
    task = _registered_ticket_task(project, requested)
    evidence = project.state_directory / "tickets" / (task.ticket_id + "-" + task.ticket_name)
    with execution_start_lock(project.runner_directory):
        state = yaml.safe_load((evidence / "ticket.yml").read_text())
        generation = state.get("active_team_ordinal")
        if parent_alias is None and generation is None:
            if state["status"] != "ready":
                raise RunnerError("TICKET_ALREADY_ACTIVE", "The selected Ticket is not ready.")
            generation = 1
            worktree = (project.worktree_root / (task.ticket_id + "-" + task.ticket_name)).resolve()
            branch = "agent/" + task.ticket_id + "-" + task.ticket_name
            if worktree.exists():
                # Another selected root may be preparing this same Team.
                if (worktree / ".state").resolve() != evidence or run_git(worktree, "branch", "--show-current") != branch:
                    raise RunnerError("WORKTREE_CONFLICT", "The task Worktree belongs to another launch.")
            else:
                provision_worktree(project, task, branch, worktree)
                _link_worktree(project, worktree, evidence)
        else:
            team_file = evidence / "teams" / str(generation) / "team.yml"
            team = yaml.safe_load(team_file.read_text())
            if team["status"] != "active":
                raise RunnerError("team-not-active", "The task Team has stopped starting work.")
            worktree = project.harness_root / state["worktree"]
            if parent_alias is not None:
                parent, _ = read_alias_mapping(project.runner_directory, parent_alias)
                _require_dispatch_roles(project, Batch((task,), b""), parent)
                if parent["ticket_id"] != task.ticket_id or parent["team_generation"] != generation:
                    raise RunnerError("authority-denied", "Child must retain its parent's active task.")
    if state["status"] == "resolving-integration":
        from graphtraj.teams.merge_resolution import integration_assignment

        worktree, prompt = integration_assignment(project, task, parent_alias)
    else:
        prompt = None
    traces = evidence / "teams" / str(generation) / "traces"
    traces.mkdir(parents=True, exist_ok=True)
    (traces.parent / "rounds/1").mkdir(parents=True, exist_ok=True)
    alias, session = _run_agent(
        project, task, task.role, worktree, evidence, traces, None, None,
        None, parent_alias, retained_batch, prompt, capacity_fd=capacity_fd,
        register_member=True, wait_for_completion=parent_alias is not None or prompt is not None,
    )
    if parent_alias is not None:
        _run_registered_children(project, task, alias, session, retained_batch, capacity_fd)
    return {"ticket_id": task.ticket_id, "ticket_name": task.ticket_name,
            "role": task.role, "alias": alias, "session": session,
            "execution_id": read_alias_mapping(project.runner_directory, alias)[0]["execution_id"],
            "worktree_path": str(worktree),
            "launch_status": "completed" if parent_alias is not None or prompt is not None else "launched"}


def run_session_children(job_file: Path) -> None:
    """Drive registered children after a standalone launch or send turn ends."""
    registration = job_file.parent / "child-registration.yml"
    if not registration.exists() or read_terminal_outcome(job_file.parent / "execution.yml") != "completed":
        return
    project = discover_project(discover_project_root(job_file), require_clean_integration=False)
    mapping, _ = read_alias_mapping(project.runner_directory, job_file.parent.name)
    retained = Path(mapping["retained_batch_file"])
    task = read_session_task(mapping, project.harness_root)
    _run_registered_children(
        project, _registered_ticket_task(project, task), mapping["alias"],
        mapping["session"], retained, int(os.environ["GRAPHTRAJ_CAPACITY_FD"]),
    )


def _run_registered_children(
    project: Any,
    task: Task,
    alias: str,
    session: str,
    retained_batch: Path,
    capacity_fd: int,
) -> None:
    """Execute registered children, then deliver their outcomes to their parent."""
    registration = project.runner_directory / "sessions" / alias / "child-registration.yml"
    while registration.exists():
        mapping, _ = read_alias_mapping(project.runner_directory, alias)
        worktree = Path(mapping["worktree_path"])
        batch, retained = _registered_batch(registration, worktree)
        children = _run_batch_workers(project, batch, retained, alias, capacity_fd)
        evidence = project.state_directory / "tickets" / (task.ticket_id + "-" + task.ticket_name)
        traces = evidence / "teams" / str(mapping["team_generation"]) / "traces"
        _run_agent(
            project, task, task.role, worktree, evidence, traces, alias, session,
            registration, mapping["parent"], retained_batch,
            "Direct child execution results:\n" + yaml.safe_dump(children.document),
            capacity_fd=capacity_fd, register_member=True,
        )


def _registered_batch(registration: Path, worktree: Path) -> tuple[Batch, Path]:
    if not registration.is_file():
        raise RunnerError("BATCH_SCHEMA_INVALID", "The parent did not register its required direct child Batch.")
    document = yaml.safe_load(registration.read_text(encoding="utf-8"))
    registration.unlink()
    retained = Path(document["retained_batch_file"])
    return read_batch(retained, worktree), retained


def _trace_ref(project: Any, traces: Path, alias: str) -> str:
    return (traces / alias / "events.jsonl").relative_to(project.harness_root).as_posix()


def _current_runtime_diagnostic(
    session_directory: Path,
    trace_file: Path,
    stderr_offset: int,
    trace_offset: int,
) -> str:
    """Collect Runtime output recorded since this execution started.

    The Runtime writes its own records into the Runtime-owned Session file,
    which reaches the Harness only through the retained Trace entry, so that
    entry supplies the Runtime's error records for the current execution.
    """

    diagnostics = [_diagnostic_since(session_directory / "stderr.log", stderr_offset)]
    try:
        diagnostics.append(
            (session_directory / "worker-stderr.log").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError):
        pass
    try:
        with trace_file.open("rb") as events:
            events.seek(trace_offset)
            diagnostics.extend(_runtime_event_errors(events.read()))
    except OSError:
        pass
    return "\n".join(diagnostic for diagnostic in diagnostics if diagnostic)


def _diagnostic_since(path: Path, offset: int) -> str:
    try:
        with path.open("rb") as diagnostic:
            diagnostic.seek(offset)
            return diagnostic.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _runtime_event_errors(events: bytes) -> list[str]:
    errors = []
    for line in events.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type in {"error", "turn.failed"}:
            error = _runtime_error_text(event)
        else:
            item = event.get("item")
            if event_type == "event_msg" and isinstance(event.get("payload"), dict):
                item = event["payload"].get("item")
            error = (
                _runtime_error_text(item)
                if isinstance(item, dict)
                and (
                    item.get("type") in {"error", "tool_error", "Error", "ToolError"}
                    or (
                        item.get("type") in {"command_execution", "CommandExecution", "FileChange"}
                        and (
                            item.get("status") in {"failed", "error"}
                            or isinstance(item.get("error"), (dict, str))
                            or (
                                isinstance(item.get("exit_code"), int)
                                and item["exit_code"] != 0
                            )
                        )
                    )
                )
                else ""
            )
        if error:
            errors.append(error)
    return errors


def _runtime_error_text(event: dict[str, Any]) -> str:
    values = []
    for key in ("aggregated_output", "stderr", "stdout", "message", "detail"):
        value = event.get(key)
        if isinstance(value, str) and value:
            values.append(value)
    error = event.get("error")
    if isinstance(error, str) and error:
        values.append(error)
    elif isinstance(error, dict):
        values.extend(
            value
            for key in ("message", "detail")
            if isinstance(value := error.get(key), str) and value
        )
    return "\n".join(values)


def _runtime_access_failure(
    diagnostic: str, reports: tuple[Path, ...]
) -> bool:
    observed = diagnostic.lower()
    if any(
        marker in observed
        for marker in (
            "permission denied",
            "operation not permitted",
            "filesystem sandbox",
        )
    ):
        return True
    if (
        "writable root" in observed
        and "symlink" in observed
        and "not supported" in observed
    ):
        return True
    condition = "the report target is not authorized for this role"
    return condition in observed and any(
        "resolved={0}; condition={1}".format(
            report.resolve(strict=False), condition
        ) in diagnostic
        for report in reports
    )


def _runtime_command_parse_error(diagnostic: str) -> str | None:
    observed = diagnostic.lower()
    for marker in ("cannot verify ", "cannot parse "):
        index = observed.rfind(marker)
        if index >= 0:
            return diagnostic[index:].splitlines()[0].strip()
    return None


def _readiness_predecessor(project: Any, ticket_id: str) -> str:
    event = next(
        (
            item
            for item in reversed(
                read_worldline(project.state_directory, project.harness_root)
            )
            if item.get("ticket_id") == ticket_id
            and item.get("to_status") == "ready"
        ),
        None,
    )
    if event is None:
        raise RunnerError(
            "TICKET_FILE_INVALID",
            "The ready Ticket has no causal readiness event.",
        )
    return event["event_id"]


def _run_agent(
    project: Any,
    task: Task,
    role: str,
    worktree: Path,
    evidence: Path,
    traces: Path,
    alias: str | None,
    expected_session: str | None,
    registration: Path | None,
    parent_alias: str | None,
    retained_batch: Path,
    prompt: str | None = None,
    *,
    capacity_fd: int | None = None,
    reports_only: bool = False,
    wait_for_completion: bool = True,
    task_environment: dict[str, str] | None = None,
    register_member: bool = False,
    replaces_alias: str | None = None,
) -> tuple[str, str]:
    team_file = traces.parent / "team.yml"
    if team_file.exists():
        team = yaml.safe_load(team_file.read_text())
        if team["status"] != "active":
            raise RunnerError("team-not-active", "The Team has stopped starting new work.")
    with capacity_positions(project, 1, capacity_fd) as positions:
        return _execute_agent(
            project, task, role, worktree, evidence, traces, alias,
            expected_session, registration, parent_alias, retained_batch, prompt,
            positions[0].fileno(), reports_only,
            wait_for_completion=wait_for_completion,
            task_environment=task_environment,
            register_member=register_member, replaces_alias=replaces_alias,
        )


def _execute_agent(
    project: Any,
    task: Task,
    role: str,
    worktree: Path,
    evidence: Path,
    traces: Path,
    alias: str | None,
    expected_session: str | None,
    registration: Path | None,
    parent_alias: str | None,
    retained_batch: Path,
    prompt: str | None,
    capacity_fd: int,
    reports_only: bool = False,
    input_delivered: threading.Event | None = None,
    wait_for_completion: bool = True,
    task_environment: dict[str, str] | None = None,
    register_member: bool = False,
    replaces_alias: str | None = None,
) -> tuple[str, str]:
    """Prepare a permitted execution; the Worker checks again at native startup."""
    with execution_start_lock(project.runner_directory):
        requested = (
            read_alias_mapping(project.runner_directory, alias)[0]
            if alias is not None and expected_session is not None
            else {"parent": parent_alias}
        )
        require_execution_allowed(project.runner_directory, alias or "new child", requested)
    generation = int(traces.parent.name) if traces.parent.name.isdigit() else 1
    new_session = alias is None
    if new_session:
        alias = _agent_alias(project, task, role, generation)
    else:
        session_directory = project.runner_directory / "sessions" / alias
        if not session_directory.is_dir():
            raise RunnerError("RUNTIME_WORKER_FAILED", "The mapped Session is unavailable.")
        # A continue starts the next execution only after the retained terminal
        # record confirms the recorded one ended; a create claims no record.
        owning = owning_execution(
            alias,
            session_directory,
            None if expected_session is None
            else read_alias_mapping(project.runner_directory, alias)[0],
        )
        if owning is not None:
            raise session_occupied(alias, owning)

    trace = traces / alias / "events.jsonl"

    policy_role = _task_policy(task, role)
    monitor = (
        None
        if reports_only
        else execution_budget_monitor(evidence, task.ticket_id, task.ticket_name)
    )
    team_file = traces.parent / "team.yml"
    ordinal = yaml.safe_load(team_file.read_text())["current_round"] if team_file.exists() else 1
    if (new_session and team_file.exists()
            and yaml.safe_load((evidence / "ticket.yml").read_text())["status"] == "resolving-integration"
            and not (traces.parent / "rounds" / str(ordinal)).stat().st_mode & 0o200):
        ordinal += 1
    report_files: tuple[Path, ...] = ()
    if expected_session is not None:
        from graphtraj.execution.runner_control import _session_report_paths

        report_files = tuple(
            Path('.state') / path.relative_to(evidence)
            for path in _session_report_paths(alias, project.harness_root)
        )
    # The launched entity keeps its role name; the configured reference that
    # selected its Runtime settings travels with this Session's records. A seat
    # another identity occupies is selected by its own role, not by its batch's.
    own_seat = task.role == role
    reference = task.role_reference if own_seat and task.role_reference is not None else role
    if expected_session is None:
        try:
            preset = (
                task.inline_preset
                if own_seat and task.inline_preset is not None
                else project.roles.preset(reference)
            )
        except ProjectRolesError as error:
            raise RunnerError("ROLE_NOT_CONFIGURED", str(error)) from error
        report_files = _role_report_files(task, preset.reports, role, generation, ordinal, alias)
        resolved_role = resolve_child_role(policy_role, preset, project.harness_root)
        adapter = runtime_adapter.select_runtime_adapter(resolved_role.settings.runtime)
        context = adapter.preflight_runtime_context(
            harness_root=project.harness_root,
            git_common_directory=project.common_directory,
            role=resolved_role,
            worktree=worktree,
            evidence=evidence,
            requested_skills=task.requested_skills,
            report_files=report_files,
        ).finalize()

    if task.report_file is not None:
        task = replace(task, report_file=report_files[0])

    # Validate Runtime inputs before publishing an allocation. Native creation
    # still follows the atomic directory reservation and durable launch request.
    if new_session:
        session_directory = project.runner_directory / "sessions" / alias
        # One Session directory owns one Agent Entity and at most one live
        # execution, so this create claims a directory nothing records yet.
        recorded = owning_execution(alias, session_directory, None)
        if recorded is not None:
            raise session_occupied(alias, recorded)
        try:
            session_directory.mkdir(parents=True, exist_ok=False)
        except FileExistsError as error:
            # A concurrent create claimed this alias after the scan, so this
            # create is refused like any other request for an owned directory.
            raise session_occupied(
                alias, owning_execution(alias, session_directory, None)
            ) from error
        trace_directory = traces / alias
        trace_directory.mkdir()
        # The Trace entry later reads the Runtime-owned native Session record;
        # this Session keeps the Runner's own records for the same execution.
        (trace_directory / "events.jsonl").touch()
        (session_directory / "events.jsonl").touch()

    if expected_session is None:
        launch_file = session_directory / "launch.yml"
        write_yaml_durably(
            launch_file,
            {
                **context.launch_document(),
                "context_evidence": context.evidence_document(),
                "operation": "launch",
                "drive_children": not wait_for_completion,
                "monitor_execution_budget": monitor is not None,
                "member_registration": ({"member": configured_role_name(role).replace("-", "_"), "replaces": replaces_alias}
                                        if register_member else None),
                "mapping": {
                    "alias": alias,
                    "runtime": context.runtime,
                    "ticket_id": task.ticket_id,
                    "team_generation": generation,
                    "role": role,
                    "role_reference": reference,
                    "parent": parent_alias,
                    "retained_batch_file": str(retained_batch),
                    "worktree_path": str(worktree),
                    "trace_file": str(trace),
                    "report_files": [path.as_posix() for path in report_files],
                    "report_file": (
                        task.report_file.as_posix()
                        if task.report_file is not None else None
                    ),
                },
            },
        )
        job_file = launch_file
        runtime_environment = context.runtime_environment()
    else:
        job_file, runtime_environment = _resume_job(
            session_directory, expected_session, role, worktree, evidence, report_files,
            reports_only=reports_only,
        )

    task_prompt = prompt or task.ticket_content
    if task.instruction:
        task_prompt += "\n## Additional instruction\n\n" + task.instruction + "\n"
    round_directory = traces.parent / "rounds" / str(ordinal)
    task_prompt += "\nAssigned report paths: " + ', '.join(map(str, report_files)) + ".\n"
    task_prompt += (
        "To submit a task result, use graphtraj_submit_result (or agent-runner submit-result) "
        "including Worktree-relative result_refs, evidence_refs, completion and unresolved items.\n"
        "An authorized parent records its decision with graphtraj_decide_result (or agent-runner "
        "decide-result), supplying submission_id, commit, decision (accepted or rejected), reason "
        "and Harness-relative evidence_refs. Read the child's submission through graphtraj_reports. "
        "A report alone does not record acceptance.\n"
    )
    if reports_only:
        task_prompt += (
            "\nThis continuation has read-only Worktree access. New implementation "
            "and dispatch are prohibited. Use only the exact report paths and Git "
            "metadata already authorized by Runner.\n"
        )
    reports = [evidence.joinpath(*path.parts[1:]) for path in report_files]
    events_file = session_directory / "events.jsonl"
    if expected_session is None:
        record_runtime_identity(events_file, context.runtime)
    try:
        stderr_offset = (session_directory / "stderr.log").stat().st_size
    except OSError:
        stderr_offset = 0
    with events_file.open("a", encoding="utf-8") as events:
        events.write(json.dumps({"type": "runner-execution-start"}) + "\n")
    try:
        # The Trace entry reads the Runtime-owned native record, which this
        # execution keeps appending to while it runs.
        trace_offset = trace.stat().st_size
    except OSError:
        trace_offset = 0
    environment = {
        **runtime_environment,
        **(task_environment or {}),
        "GRAPHTRAJ_TEAM_ROUND": str(ordinal),
        "GRAPHTRAJ_ROLE": role,
        "GRAPHTRAJ_EVIDENCE": str(evidence),
        "GRAPHTRAJ_TICKET_ID": task.ticket_id,
        "GRAPHTRAJ_TICKET_NAME": task.ticket_name,
        "GRAPHTRAJ_HARNESS_ROOT": str(project.harness_root),
        "GRAPHTRAJ_TEAM_GENERATION": str(generation),
    }
    # The recorded entity, never its role spelling, identifies the caller.
    environment["GRAPHTRAJ_PARENT_ALIAS"] = alias
    environment["GRAPHTRAJ_PARENT_REGISTRATION"] = str(session_directory / "child-registration.yml")
    session_id, outcome = _run_session_worker(
        session_directory, job_file, worktree, task_prompt, environment,
        capacity_fd, input_delivered, wait_for_completion,
    )
    if outcome == "budget-stopped":
        raise RunnerError(
            "EXECUTION_BUDGET_STOPPED",
            "Runner selected stopping for the Ticket execution budget.",
        )
    if not wait_for_completion:
        return alias, session_id
    diagnostic = _current_runtime_diagnostic(
        session_directory, trace, stderr_offset, trace_offset
    )
    if outcome != "completed":
        if _runtime_access_failure(diagnostic, tuple(reports)):
            raise RunnerError(
                "RUNTIME_ACCESS_DENIED",
                "The {0} Team member encountered a Runtime access/configuration failure. "
                "Return it to the responsible operator; do not ask the Agent to self-correct. "
                "Evidence: {1}. {2}".format(
                    role, _trace_ref(project, traces, alias), diagnostic.strip()
                ),
            )
        raise RunnerError(
            "RUNTIME_PROVIDER_FAILED",
            "The {0} Team member ended with {1}. Return this system/provider failure "
            "to the caller or superior for a later retry; do not ask the Agent to "
            "self-correct. Evidence: {2}. {3}".format(
                role, outcome, _trace_ref(project, traces, alias), diagnostic.strip()
            ),
        )
    if (
        any(not path.is_file() for path in reports)
        and _runtime_access_failure(diagnostic, tuple(reports))
    ):
        raise RunnerError(
            "RUNTIME_ACCESS_DENIED",
            "The {0} Team member encountered a Runtime access/configuration failure. "
            "Return it to the responsible operator; do not ask the Agent to "
            "self-correct. Evidence: {1}. {2}".format(
                role, _trace_ref(project, traces, alias), diagnostic.strip()
            ),
        )
    if any(not path.is_file() for path in reports):
        command_error = _runtime_command_parse_error(diagnostic)
        if command_error is not None:
            with events_file.open("a", encoding="utf-8") as events:
                events.write(
                    json.dumps(
                        {
                            "type": "runtime-command-parse",
                            "message": command_error,
                        }
                    )
                    + "\n"
                )
    with (session_directory / "events.jsonl").open("a", encoding="utf-8") as trace:
        for path in reports:
            if path.is_file():
                trace.write(json.dumps({"type": "report-observed", "path": path.relative_to(evidence).as_posix(),
                                        "content": path.read_text(encoding="utf-8")}) + "\n")
    return alias, session_id


def _resume_job(
    session_directory: Path,
    expected_session: str,
    role: str,
    worktree: Path,
    evidence: Path,
    report_files: tuple[Path, ...],
    *,
    reports_only: bool = False,
) -> tuple[Path, dict[str, str]]:
    launch_file = session_directory / "launch.yml"
    mapping_file = session_directory / "mapping.yml"
    try:
        launch = yaml.safe_load(launch_file.read_text(encoding="utf-8"))
        mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise RunnerError("RUNTIME_WORKER_FAILED", "The mapped Session is unavailable.") from error
    if (
        not isinstance(launch, dict)
        or not isinstance(mapping, dict)
        or launch.get("runtime") != mapping.get("runtime")
        or not isinstance(launch.get("adapter_request"), dict)
        or not isinstance(launch.get("mapping"), dict)
        or mapping.get("session") != expected_session
        or not isinstance(launch.get("connection"), dict)
    ):
        raise RunnerError("RUNTIME_WORKER_FAILED", "The mapped Session is unavailable.")
    # The Session record owns the Agent Entity and its direct parent; a retained
    # launch input that disagrees cannot re-attach or re-parent it.
    if conflicting_binding_field(mapping, launch["mapping"]) is not None:
        raise RunnerError(
            "AGENT_BINDING_CONFLICT",
            "The retained launch input does not match this Session's recorded "
            "Agent Entity, so it cannot change its ownership.",
        )
    connection = launch["connection"]
    if any(
        key not in {"base_url", "api_key_env"}
        or not isinstance(value, str)
        or not value
        for key, value in connection.items()
    ):
        raise RunnerError("RUNTIME_WORKER_FAILED", "The mapped Session is unavailable.")
    try:
        adapter_request = refresh_codex_report_paths(
            launch["adapter_request"],
            worktree=worktree,
            evidence=evidence,
            report_files=report_files,
            role=role,
            reports_only=reports_only,
            session_directory=session_directory,
        )
    except RuntimeAdapterError as error:
        raise RunnerError(error.code, error.message) from error
    resume_file = session_directory / "resume.yml"
    write_yaml_durably(
        resume_file,
        {
            "operation": "resume",
            "runtime": mapping["runtime"],
            "adapter_request": adapter_request,
            "context_evidence": launch.get("context_evidence", {}),
            "expected_session": expected_session,
            "monitor_execution_budget": not reports_only,
            "mapping": {
                key: value
                for key, value in mapping.items()
                if key not in {"worker_pid", "runtime_pid"}
            },
        },
    )
    return resume_file, dict(
        codex_connection_environment(
            connection.get("base_url"), connection.get("api_key_env")
        )
    )


def _run_session_worker(
    session_directory: Path,
    job_file: Path,
    worktree: Path,
    prompt: str,
    runtime_environment: object,
    capacity_fd: int,
    input_delivered: threading.Event | None,
    wait_for_completion: bool = True,
) -> tuple[str, str]:
    """Run a native Worker, retaining any caller notice channel until it exits.

    A root Worker still drives its own registered children. Waiting here keeps
    the original CLI/MCP reader alive through that execution, without waiting
    for task acceptance, which belongs to the caller after this call returns.
    """
    if not isinstance(runtime_environment, dict):
        raise RunnerError("RUNTIME_WORKER_FAILED", "The Runtime Session could not be started.")
    execution = session_directory / "execution.yml"
    error = session_directory / (
        "resume-error.yml" if job_file.name == "resume.yml" else "launch-error.yml"
    )
    error.unlink(missing_ok=True)
    worker_environment = dict(os.environ)
    worker_environment.update(runtime_environment)
    worker_environment["GRAPHTRAJ_CAPACITY_FD"] = str(capacity_fd)
    notice_fd, close_notice_fd = caller_notice_fd()
    if notice_fd is not None:
        worker_environment["GRAPHTRAJ_BUDGET_NOTICE_FD"] = str(notice_fd)
    try:
        with (session_directory / "worker-stderr.log").open(
            "w", encoding="utf-8"
        ) as diagnostics:
            worker = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-m",
                    "graphtraj.execution.runner_worker",
                    str(job_file),
                ],
                cwd=worktree,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=diagnostics,
                text=True,
                start_new_session=True,
                env=worker_environment,
                pass_fds=(capacity_fd,) + ((int(notice_fd),) if notice_fd else ()),
            )
            assert worker.stdin is not None
            worker.stdin.write(prompt)
            worker.stdin.close()
            if not wait_for_completion and notice_fd is None:
                from graphtraj.execution.runner_control import _await_session_resume

                _await_session_resume(worker, session_directory, error, None)
                mapping, _ = read_alias_mapping(session_directory.parent.parent, session_directory.name)
                return mapping["session"], "running"
            try:
                while worker.poll() is None:
                    if input_delivered is not None and not input_delivered.is_set():
                        try:
                            current_mapping = yaml.safe_load(
                                (session_directory / "mapping.yml").read_text(
                                    encoding="utf-8"
                                )
                            )
                        except (OSError, UnicodeError, yaml.YAMLError):
                            current_mapping = None
                        if (
                            isinstance(current_mapping, dict)
                            and current_mapping.get("worker_pid") == worker.pid
                            and current_mapping.get("execution_id")
                        ):
                            input_delivered.set()
                    try:
                        worker.wait(timeout=0.05)
                    except subprocess.TimeoutExpired:
                        pass
                if input_delivered is not None and not input_delivered.is_set():
                    try:
                        final_mapping = yaml.safe_load(
                            (session_directory / "mapping.yml").read_text(
                                encoding="utf-8"
                            )
                        )
                    except (OSError, UnicodeError, yaml.YAMLError):
                        final_mapping = None
                    if (
                        isinstance(final_mapping, dict)
                        and final_mapping.get("worker_pid") == worker.pid
                    ):
                        input_delivered.set()
                exit_code = worker.returncode
            except BaseException:
                worker.terminate()
                worker.wait()
                raise
        if exit_code != 0:
            if error.is_file():
                failure = yaml.safe_load(error.read_text())
                raise RunnerError(failure["code"], failure["message"])
            raise OSError("Session worker failed")
        mapping = yaml.safe_load(
            (session_directory / "mapping.yml").read_text(encoding="utf-8")
        )
        terminal = yaml.safe_load(execution.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as failure:
        raise RunnerError("RUNTIME_WORKER_FAILED", "The Runtime Session could not be started.") from failure
    finally:
        if close_notice_fd and notice_fd is not None:
            os.close(notice_fd)
    if (
        not isinstance(mapping, dict)
        or not isinstance(mapping.get("session"), str)
        or not mapping["session"]
        or not isinstance(terminal, dict)
        or terminal.get("outcome") not in {"completed", "interrupted", "runtime-error"}
    ):
        raise RunnerError("RUNTIME_WORKER_FAILED", "The Runtime Session could not be started.")
    return mapping["session"], (
        "budget-stopped" if terminal.get("budget_stopped") else terminal["outcome"]
    )


def _agent_alias(project: Any, task: Task, role: str, generation: int = 1) -> str:
    """Return a free Agent alias for one Session of this Team generation.

    The alias names the Ticket, the whole-Team handover generation counted from
    zero, the configured role and the entity. Word groups inside one component
    use '_'; the entity starts as the role name and takes a numbered successor
    when that name is occupied, so no existing Session is overwritten.
    """
    role_name = configured_role_name(role).replace("-", "_")
    prefix = "{0}-{1}-handover{2}-{3}@".format(
        task.ticket_id, task.ticket_name.replace("-", "_"), generation - 1, role_name
    )
    suffix = 1
    while True:
        entity = role_name if suffix == 1 else "{0}_{1}".format(role_name, suffix)
        alias = prefix + entity
        if not (project.runner_directory / "sessions" / alias).exists():
            return alias
        suffix += 1


def _role_report_files(
    task: Task,
    selected_reports: tuple[str, ...],
    role: str,
    generation: int,
    ordinal: int,
    alias: str,
) -> tuple[Path, ...]:
    """Allocate explicit reports or one actual-role report without collisions."""
    from graphtraj.execution.runner_results import assign_session_reports

    directory = Path('.state') / 'teams' / str(generation) / 'rounds' / str(ordinal)
    if task.report_file is not None:
        reports = (task.report_file,)
    else:
        reports = tuple(directory / name for name in selected_reports)
    return assign_session_reports(role, alias, generation, ordinal, reports)


def _link_worktree(project: Any, worktree: Path, evidence: Path) -> None:
    (worktree / ".scratch").mkdir(exist_ok=True)
    links = {
        ".state": evidence,
        "CONTEXT.md": project.harness_root / "CONTEXT.md",
        "docs": project.documents_directory,
    }
    created_documents = []
    for name, target in links.items():
        link = worktree / name
        if os.path.lexists(link):
            if (name == "docs" and (link.is_dir() or link.is_symlink())) or (
                name == "CONTEXT.md" and (link.is_file() or link.is_symlink())
            ):
                continue
            if not link.is_symlink() or link.resolve() != target.resolve():
                raise RunnerError("STATE_LINK_FAILED", "A Ticket Worktree retained path points elsewhere.")
            continue
        link.symlink_to(os.path.relpath(target, worktree), target_is_directory=target.is_dir())
        if name in {"docs", "CONTEXT.md"}:
            created_documents.append(name)
    ignore_worktree_documents(worktree, created_documents)


def _worker_main() -> None:
    # Unwind the Session worker before releasing the Team worker's capacity.
    def stop(signum: int, frame: Any) -> None:
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, stop)
    retained = Path(sys.argv[1])
    task = read_batch(retained, Path.cwd()).tasks[int(sys.argv[2])]
    try:
        project = discover_project(Path.cwd(), require_clean_integration=False)
        capacity_fd = int(sys.argv[3])
        result = _deliver_ticket(project, task, retained, capacity_fd, sys.argv[4] or None)
    except (RunnerError, RuntimeAdapterError) as error:
        result = _failed_task(task, RunnerError(error.code, error.message))
        if error.code == "EXECUTION_BUDGET_STOPPED":
            result["launch_status"] = "stopped"
    print(yaml.safe_dump(result, sort_keys=False), end="")


if __name__ == "__main__":
    _worker_main()
