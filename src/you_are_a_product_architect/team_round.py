"""Run-free delivery of one registered Ticket through one Team Round."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any, Callable

import yaml

from .codex_adapter import codex_connection_environment, preflight_runtime_context
from .delivery_state import apply_delivery_state_request
from .delivery_worldline import read_worldline
from .runner_batch import read_batch, resolved_role_preset, retain_batch
from .runner_capacity import capacity_positions
from .runner_io import write_yaml_durably
from .runner_models import Batch, LaunchResponse, RunnerError, Task, role_alias_marker
from .runner_project import discover_project, preflight_worktree, provision_worktree, run_git, runtime_executable
from .runtime_adapter import RuntimeAdapterError


_COMMIT = re.compile(r"[0-9a-f]{40}")
_ENGINEER_ROLES = frozenset({"engineer-junior", "engineer-senior", "engineer-expert"})
_REVIEWER_ROLES = frozenset({"standards-reviewer", "spec-reviewer"})
_CHILD_ROLES = _ENGINEER_ROLES | _REVIEWER_ROLES


def register_child_batch(batch_file: Path, cwd: Path, registration: Path) -> LaunchResponse:
    """Retain and register the Team Leader's one direct child Batch."""

    batch = read_batch(batch_file, cwd)
    parent_ticket = os.environ.get("GRAPHTRAJ_TICKET_ID")
    if batch.run_id is not None or any(
        task.ticket_id != parent_ticket
        or (
            _task_policy(task) not in _CHILD_ROLES
            and not _is_inline_specialist(task)
        )
        for task in batch.tasks
    ):
        raise RunnerError("BATCH_SCHEMA_INVALID", "A direct child Batch must contain formal roles for its parent Ticket.")
    engineers = [task for task in batch.tasks if _task_policy(task) in _ENGINEER_ROLES]
    reviewers = [task for task in batch.tasks if _task_policy(task) in _REVIEWER_ROLES]
    if not (
        (len(batch.tasks) == 1 and len(engineers) == 1)
        or len(reviewers) == len(batch.tasks) and 1 <= len(reviewers) <= 2
        or len(batch.tasks) == 1 and _is_inline_specialist(batch.tasks[0])
    ):
        raise RunnerError("BATCH_SCHEMA_INVALID", "A direct child Batch must contain one Engineer, one or both Reviewers, or one temporary specialist.")
    project = discover_project(Path(os.environ.get("GRAPHTRAJ_HARNESS_ROOT", cwd)))
    children = [
        {"ticket_id": task.ticket_id, "role": task.role,
         "alias": _agent_alias(project, task, task.role), "launch_status": "registered"}
        for task in batch.tasks
    ]
    try:
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


def _is_inline_specialist(task: Task) -> bool:
    """Return whether a task uses the fixed non-Team temporary policy."""

    return task.inline_preset is not None and task.policy_role == "temporary-role"


def _task_policy(task: Task, role: str | None = None) -> str:
    """Return the fixed policy applied to this invocation."""

    if role is None or task.role == role:
        return task.policy_role or task.role
    return role


def launch_team_batch(batch: Batch, cwd: Path) -> LaunchResponse:
    """Deliver each Main-selected registered Ticket through generation 1."""

    if all(task.role == "team-leader" for task in batch.tasks):
        return _run_batch_workers(discover_project(cwd), batch)
    if any(task.policy_role != "temporary-role" for task in batch.tasks):
        raise RunnerError("ROLE_NOT_CONFIGURED", "A Main Batch must select the team-leader preset.")
    project = discover_project(cwd)
    with capacity_positions(project, len(batch.tasks)) as positions:
        retained = retain_batch(project.state_directory, batch)
        traces = project.runner_directory / "traces"
        evidence = project.runner_directory / "inline-evidence"
        traces.mkdir(parents=True, exist_ok=True)
        evidence.mkdir(parents=True, exist_ok=True)
        results = []
        for requested, position in zip(batch.tasks, positions):
            task = _registered_ticket_task(project, requested)
            alias, session = _run_agent(
                project,
                task,
                task.role,
                project.integration_worktree,
                evidence,
                traces,
                None,
                None,
                None,
                None,
                retained,
                capacity_fd=position.fileno(),
            )
            results.append(
                {
                    "ticket_id": task.ticket_id,
                    "ticket_name": task.ticket_name,
                    "role": task.role,
                    "launch_status": "completed",
                    "alias": alias,
                    "session": session,
                }
            )
        return LaunchResponse(
            document={"retained_batch_file": str(retained), "tasks": results},
            succeeded=True,
        )


def _run_batch_workers(
    project: Any, batch: Batch, retained: Path | None = None, parent_alias: str = "",
    capacity_fd: int | None = None,
) -> LaunchResponse:
    workers = []
    with capacity_positions(project, len(batch.tasks), capacity_fd) as positions:
        if retained is None:
            retained = retain_batch(project.state_directory, batch)
        for index, position in enumerate(positions):
            try:
                worker = subprocess.Popen(
                    [sys.executable, "-m", "you_are_a_product_architect.team_round",
                     str(retained), str(index), str(position.fileno()), parent_alias],
                    cwd=project.harness_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    pass_fds=(position.fileno(),),
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


def _deliver_ticket(project: Any, requested: Task, retained_batch: Path, capacity_fd: int) -> dict[str, Any]:
    # The stopped Leader lends its worker-held position and resumes only after
    # the direct children have exited. PID values are never capacity positions.
    run_agent = partial(_run_agent, capacity_fd=capacity_fd)
    request_state = partial(_request_state, capacity_fd=capacity_fd)
    next_formal_batch = partial(_next_formal_batch, capacity_fd=capacity_fd)
    ticket_directory = project.state_directory / "tickets" / (
        requested.ticket_id + "-" + requested.ticket_name
    )
    state_file = ticket_directory / "ticket.yml"
    try:
        state = yaml.safe_load(state_file.read_text(encoding="utf-8"))
        definition = ticket_directory / state["current_definition"]
        ticket_content = definition.read_text(encoding="utf-8")
    except (KeyError, OSError, TypeError, yaml.YAMLError) as error:
        raise RunnerError("TICKET_FILE_INVALID", "The selected registered Ticket is invalid.") from error
    if (
        state.get("ticket_id") != requested.ticket_id
        or state.get("ticket_name") != requested.ticket_name
        or state.get("status") != "ready"
        or state.get("active_team_ordinal") is not None
        or state.get("current_candidate") is not None
    ):
        raise RunnerError("TICKET_ALREADY_ACTIVE", "The selected Ticket is not ready for a first Team.")

    task = replace(requested, ticket_file=definition.resolve(), ticket_content=ticket_content)
    worktree = (project.worktree_root / (requested.ticket_id + "-" + requested.ticket_name)).resolve()
    branch = "agent/{0}-{1}".format(requested.ticket_id, requested.ticket_name)
    preflight_worktree(project, task, branch, worktree)
    provision_worktree(project, task, branch, worktree)
    _link_worktree(project, worktree, ticket_directory)

    team_directory = ticket_directory / "teams" / "1"
    round_directory = team_directory / "rounds" / "1"
    traces = team_directory / "traces"
    round_directory.mkdir(parents=True)
    traces.mkdir()

    registration = project.runner_directory / "sessions" / (
        requested.ticket_id + "-" + requested.ticket_name + "@l1"
    ) / "child-registration.yml"
    leader_alias, leader_session = run_agent(
        project, task, "team-leader", worktree, ticket_directory, traces, None, None, registration, None, retained_batch,
    )
    engineer_batch, engineer_batch_path, leader_alias, leader_session = next_formal_batch(
        project,
        task,
        definition,
        ticket_content,
        worktree,
        ticket_directory,
        traces,
        leader_alias,
        leader_session,
        registration,
        retained_batch,
    )
    if (
        len(engineer_batch.tasks) != 1
        or _task_policy(engineer_batch.tasks[0]) not in _ENGINEER_ROLES
    ):
        raise RunnerError("BATCH_SCHEMA_INVALID", "The first direct child Batch must contain one Engineer.")
    engineer_task = replace(
        engineer_batch.tasks[0],
        ticket_file=definition.resolve(),
        ticket_content=ticket_content,
    )

    predecessor = _readiness_predecessor(project, task.ticket_id)
    members = {
        "team_leader": {"role": "team-leader", "session_ref": leader_alias},
        "engineer": {"role": engineer_task.role, "session_ref": None},
        "standards_reviewer": {"role": "standards-reviewer", "session_ref": None},
        "spec_reviewer": {"role": "spec-reviewer", "session_ref": None},
    }
    state_alias, state_session, event = request_state(
        project,
        task,
        worktree,
        ticket_directory,
        traces,
        None,
        None,
        leader_alias,
        retained_batch,
        {
            "phase": "start",
            "ticket_id": task.ticket_id,
            "caused_by_event_ids": [predecessor],
            "evidence_refs": [retained_batch.relative_to(project.harness_root).as_posix()],
            "worktree": worktree.relative_to(project.harness_root).as_posix(),
            "branch": branch,
            "members": members,
        },
        "start",
    )
    predecessor = event["event_id"]

    engineer_alias, engineer_session = run_agent(
        project,
        engineer_task,
        engineer_task.role,
        worktree,
        ticket_directory,
        traces,
        None,
        None,
        None,
        leader_alias,
        engineer_batch_path,
    )
    state_alias, state_session, event = request_state(
        project, task, worktree, ticket_directory, traces,
        state_alias, state_session, leader_alias, engineer_batch_path,
        {
            "phase": "member", "ticket_id": task.ticket_id,
            "caused_by_event_ids": [predecessor],
            "evidence_refs": [_trace_ref(project, traces, engineer_alias)],
            "member": "engineer", "role": engineer_task.role,
            "session_ref": engineer_alias,
        },
        "member-engineer",
    )
    predecessor = event["event_id"]
    candidate = _candidate(round_directory, worktree)
    state_alias, state_session, event = request_state(
        project, task, worktree, ticket_directory, traces,
        state_alias, state_session, leader_alias, engineer_batch_path,
        {
            "phase": "candidate", "ticket_id": task.ticket_id,
            "caused_by_event_ids": [predecessor],
            "evidence_refs": [_trace_ref(project, traces, engineer_alias)],
            "candidate": candidate,
        },
        "candidate",
    )
    predecessor = event["event_id"]

    sessions = {engineer_task.role: (engineer_task, engineer_alias, engineer_session, engineer_batch_path)}

    def correct_process() -> None:
        nonlocal state_alias, state_session, predecessor, leader_alias, leader_session
        leader_report = round_directory / "leader.md"
        while leader_report.is_file() and "Decision: CORRECT" in leader_report.read_text().splitlines():
            judgment = leader_report.read_text(encoding="utf-8")
            fields = {}
            for name in ("Responsible", "Rule", "Reason"):
                values = [line[len(name) + 2:] for line in judgment.splitlines() if line.startswith(name + ": ")]
                if len(values) != 1 or not values[0].strip():
                    raise RunnerError("BATCH_SCHEMA_INVALID", "Correction requires one responsible role, accepted rule, and evidence-backed reason.")
                fields[name] = values[0]
            role = fields["Responsible"]
            if role not in sessions or registration.exists():
                raise RunnerError("BATCH_SCHEMA_INVALID", "Correction must resume an existing member without registering a new Batch.")
            child, alias, session, child_batch = sessions[role]
            state_alias, state_session, event = request_state(
                project, task, worktree, ticket_directory, traces,
                state_alias, state_session, leader_alias, retained_batch,
                {
                    "phase": "correction", "ticket_id": task.ticket_id,
                    "caused_by_event_ids": [predecessor],
                    "evidence_refs": [_trace_ref(project, traces, leader_alias), _trace_ref(project, traces, alias)],
                    "responsible_role": role, "session_ref": alias,
                },
                "correction",
            )
            predecessor = event["event_id"]
            affected = [role]
            if _task_policy(sessions[role][0]) in _ENGINEER_ROLES:
                affected += [r for r in sessions if _task_policy(sessions[r][0]) in _REVIEWER_ROLES]
            leader_report.unlink()
            for affected_role in affected:
                names = ("engineer.md", "validation.md") if _task_policy(sessions[affected_role][0]) in _ENGINEER_ROLES else (
                    "standards.md" if affected_role == "standards-reviewer" else "spec.md",
                )
                for name in names:
                    (round_directory / name).unlink(missing_ok=True)
            for affected_role in affected:
                child, alias, session, child_batch = sessions[affected_role]
                followup = (
                    "Reflect on the Team Leader's judgment and correct your work against the accepted Ticket and review rules.\n" + judgment
                    if affected_role == role else
                    "Repeat your affected Review against the corrected fixed candidate and the accepted review rules.\n"
                )
                run_agent(
                    project, child, affected_role, worktree, ticket_directory, traces,
                    alias, session, None, leader_alias, child_batch,
                    followup + "\nCaused by Project Worldline event: " + predecessor,
                )
                if _task_policy(sessions[affected_role][0]) in _ENGINEER_ROLES:
                    candidate = _candidate(round_directory, worktree)
                    state_alias, state_session, event = request_state(
                        project, task, worktree, ticket_directory, traces,
                        state_alias, state_session, leader_alias, child_batch,
                        {
                            "phase": "candidate", "ticket_id": task.ticket_id,
                            "caused_by_event_ids": [predecessor],
                            "evidence_refs": [_trace_ref(project, traces, alias)],
                            "candidate": candidate,
                        }, "candidate",
                    )
                    predecessor = event["event_id"]
                else:
                    _collect_review_report(ticket_directory, round_directory, child.report_file.name)
            leader_alias, leader_session = run_agent(
                project, task, "team-leader", worktree, ticket_directory, traces,
                leader_alias, leader_session, registration, None, retained_batch,
                "Correction and affected Reviews completed in the same Team Round. Assess the current evidence.\n"
                + "Caused by Project Worldline event: " + predecessor,
            )

    next_formal_batch = partial(next_formal_batch, correct_process=correct_process)

    leader_alias, leader_session = run_agent(
        project, task, "team-leader", worktree, ticket_directory, traces,
        leader_alias, leader_session, registration, None, retained_batch,
        "Engineer completed:\n" + yaml.safe_dump(
            {"role": engineer_task.role, "alias": engineer_alias, "session": engineer_session,
             "trace": _trace_ref(project, traces, engineer_alias)},
            sort_keys=False,
        ),
    )
    child_results = []
    remaining = {"standards-reviewer", "spec-reviewer"}
    while remaining:
        reviewer_batch, reviewer_batch_path, leader_alias, leader_session = next_formal_batch(
            project, task, definition, ticket_content, worktree, ticket_directory,
            traces, leader_alias, leader_session, registration, retained_batch,
        )
        if not {child.role for child in reviewer_batch.tasks} <= remaining:
            raise RunnerError("BATCH_SCHEMA_INVALID", "The child Batch must select remaining Review axes for this candidate.")
        try:
            reviewed = _run_batch_workers(
                project, reviewer_batch, reviewer_batch_path, leader_alias, capacity_fd,
            )
        except RunnerError as error:
            if error.code != "insufficient-capacity":
                raise
            leader_alias, leader_session = run_agent(
                project, task, "team-leader", worktree, ticket_directory, traces,
                leader_alias, leader_session, registration, None, retained_batch,
                "Child Batch did not start:\n" + yaml.safe_dump(error.as_document()),
            )
            correct_process()
            if not registration.exists():
                raise error
            continue
        for child, result in zip(reviewer_batch.tasks, reviewed.document["tasks"]):
            if "error" in result:
                raise RunnerError(result["error"]["code"], result["error"]["message"])
            report_name = (
                "standards.md" if child.role == "standards-reviewer" else "spec.md"
            )
            alias, session = result["alias"], result["session"]
            sessions[child.role] = (
                replace(child, ticket_file=definition, ticket_content=ticket_content,
                        report_file=Path(".state") / "reviews" / report_name),
                alias, session, reviewer_batch_path,
            )
            _collect_review_report(ticket_directory, round_directory, report_name)
            member = "standards_reviewer" if child.role == "standards-reviewer" else "spec_reviewer"
            state_alias, state_session, event = request_state(
                project, task, worktree, ticket_directory, traces,
                state_alias, state_session, leader_alias, reviewer_batch_path,
                {
                    "phase": "member", "ticket_id": task.ticket_id,
                    "caused_by_event_ids": [predecessor],
                    "evidence_refs": [_trace_ref(project, traces, alias)],
                    "member": member, "role": child.role, "session_ref": alias,
                },
                "member-" + member,
            )
            predecessor = event["event_id"]
            remaining.remove(child.role)
            child_results.append({"role": child.role, "alias": alias, "session": session,
                                  "trace": _trace_ref(project, traces, alias)})

        leader_alias, leader_session = run_agent(
            project, task, "team-leader", worktree, ticket_directory, traces,
            leader_alias, leader_session, registration, None, retained_batch,
            "Reviewers completed:\n" + yaml.safe_dump(child_results, sort_keys=False),
        )
    _, _, leader_alias, leader_session = next_formal_batch(
        project, task, definition, ticket_content, worktree, ticket_directory,
        traces, leader_alias, leader_session, registration, retained_batch,
        allow_no_formal=True,
    )
    candidate = _validate_round(round_directory, worktree)
    decision = _leader_decision(round_directory / "leader.md")
    evidence = [
        path.relative_to(project.harness_root).as_posix()
        for path in sorted(round_directory.iterdir())
    ]
    request_state(
        project, task, worktree, ticket_directory, traces,
        state_alias, state_session, leader_alias, retained_batch,
        {
            "phase": "final", "ticket_id": task.ticket_id,
            "caused_by_event_ids": [predecessor], "evidence_refs": evidence,
            "candidate": candidate, "decision": decision,
        },
        "final",
    )
    return {
        "ticket_id": requested.ticket_id,
        "ticket_name": requested.ticket_name,
        "role": "team-leader",
        "launch_status": "accepted" if decision == "accepted" else "not-accepted",
        "worktree_path": str(worktree),
        "alias": leader_alias,
        "session": leader_session,
    }


def _registered_batch(registration: Path, worktree: Path) -> tuple[Batch, Path]:
    if not registration.is_file():
        raise RunnerError("BATCH_SCHEMA_INVALID", "The Team Leader did not register its required direct child Batch.")
    document = yaml.safe_load(registration.read_text(encoding="utf-8"))
    registration.unlink()
    retained = Path(document["retained_batch_file"])
    return read_batch(retained, worktree), retained


def _next_formal_batch(
    project: Any,
    task: Task,
    definition: Path,
    ticket_content: str,
    worktree: Path,
    ticket_directory: Path,
    traces: Path,
    leader_alias: str,
    leader_session: str,
    registration: Path,
    retained_batch: Path,
    *,
    capacity_fd: int,
    allow_no_formal: bool = False,
    correct_process: Callable[[], None] | None = None,
) -> tuple[Batch | None, Path | None, str, str]:
    """Run temporary child specialists before returning the next formal Batch."""

    run_agent = partial(_run_agent, capacity_fd=capacity_fd)
    while True:
        if correct_process is not None:
            correct_process()
        if not registration.exists():
            break
        batch, batch_path = _registered_batch(registration, worktree)
        if len(batch.tasks) != 1 or not _is_inline_specialist(batch.tasks[0]):
            if allow_no_formal:
                raise RunnerError("BATCH_SCHEMA_INVALID", "The completed Team Round cannot register another child Batch.")
            return batch, batch_path, leader_alias, leader_session
        specialist = replace(
            batch.tasks[0],
            ticket_file=definition.resolve(),
            ticket_content=ticket_content,
        )
        alias, session = run_agent(
            project,
            specialist,
            specialist.role,
            worktree,
            ticket_directory,
            traces,
            None,
            None,
            None,
            leader_alias,
            batch_path,
        )
        leader_alias, leader_session = run_agent(
            project,
            task,
            "team-leader",
            worktree,
            ticket_directory,
            traces,
            leader_alias,
            leader_session,
            registration,
            None,
            retained_batch,
            "Specialist completed:\n"
            + yaml.safe_dump(
                {"role": specialist.role, "alias": alias, "session": session,
                 "trace": _trace_ref(project, traces, alias)},
                sort_keys=False,
            ),
        )
    if allow_no_formal:
        return None, None, leader_alias, leader_session
    raise RunnerError("BATCH_SCHEMA_INVALID", "The Team Leader did not register its required direct child Batch.")


def _request_state(
    project: Any,
    task: Task,
    worktree: Path,
    evidence: Path,
    traces: Path,
    alias: str | None,
    session: str | None,
    parent_alias: str,
    retained_batch: Path,
    facts: dict[str, Any],
    request_name: str,
    *,
    capacity_fd: int,
) -> tuple[str, str, dict[str, Any]]:
    state_alias = alias or "{0}-{1}@d1".format(task.ticket_id, task.ticket_name)
    runtime_request = worktree / ".scratch" / "delivery-state" / (request_name + ".yml")
    runtime_request.parent.mkdir(parents=True, exist_ok=True)
    environment = {
        "GRAPHTRAJ_STATE_FACTS": json.dumps(facts, separators=(",", ":")),
        "GRAPHTRAJ_STATE_REQUEST": str(runtime_request),
    }
    previous = {name: os.environ.get(name) for name in environment}
    os.environ.update(environment)
    try:
        alias, session = _run_agent(
            project, task, "delivery-state", worktree, evidence, traces,
            alias, session, None, parent_alias, retained_batch,
            "Request the strict Delivery State change for these supplied facts:\n"
            + yaml.safe_dump(facts, sort_keys=False)
            + "\nWrite only that request to {0}.\n".format(runtime_request),
            capacity_fd=capacity_fd,
        )
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    if not runtime_request.is_file():
        raise RunnerError("RUNTIME_WORKER_FAILED", "Delivery State did not produce its requested state change.")
    request_file = project.runner_directory / "sessions" / alias / "requests" / (request_name + ".yml")
    request_file.parent.mkdir(exist_ok=True)
    shutil.move(runtime_request, request_file)
    request = yaml.safe_load(request_file.read_text(encoding="utf-8"))
    try:
        event = apply_delivery_state_request(
            project.state_directory, project.harness_root, request, facts
        )
    except (OSError, ValueError, yaml.YAMLError) as error:
        raise RunnerError("STATE_DIRECTORY_INVALID", "Delivery State produced an invalid state change.") from error
    return alias, session, event


def _trace_ref(project: Any, traces: Path, alias: str) -> str:
    return (traces / alias / "events.jsonl").relative_to(project.harness_root).as_posix()


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
) -> tuple[str, str]:
    with capacity_positions(project, 1, capacity_fd) as positions:
        return _execute_agent(
            project, task, role, worktree, evidence, traces, alias,
            expected_session, registration, parent_alias, retained_batch, prompt,
            positions[0].fileno(),
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
) -> tuple[str, str]:
    if alias is None:
        alias = _agent_alias(project, task, role)
        session_directory = project.runner_directory / "sessions" / alias
        session_directory.mkdir(parents=True, exist_ok=False)
        trace_directory = traces / alias
        trace_directory.mkdir()
        trace = trace_directory / "events.jsonl"
        trace.touch()
        os.link(trace, session_directory / "events.jsonl")
    else:
        session_directory = project.runner_directory / "sessions" / alias
        if not session_directory.is_dir():
            raise RunnerError("RUNTIME_WORKER_FAILED", "The mapped Session is unavailable.")

    policy_role = _task_policy(task, role)
    if expected_session is None:
        preset = (
            resolved_role_preset(task, project.role_bindings)
            if task.inline_preset is not None and task.role == role
            else project.role_bindings[role]
        )
        context = preflight_runtime_context(
            runtime_store=project.runtime_store,
            executable=runtime_executable(preset.runtime),
            git_common_directory=project.common_directory,
            role=policy_role,
            model=preset.model,
            base_url=preset.base_url,
            api_key_env=preset.api_key_env,
            allow_runtime_swarm=preset.allow_runtime_swarm,
            worktree=worktree,
            evidence=evidence,
            repository_skill_source=worktree,
            requested_skills=(),
            report_file=task.report_file,
        ).finalize()
        launch_file = session_directory / "launch.yml"
        write_yaml_durably(
            launch_file,
            {
                **context.launch_document(),
                "operation": "launch",
                "mapping": {
                    "alias": alias,
                    "runtime": context.runtime,
                    "ticket_id": task.ticket_id,
                    "team_generation": 1,
                    "role": role,
                    "parent": parent_alias,
                    "retained_batch_file": str(retained_batch),
                    "worktree_path": str(worktree),
                    "trace_file": str(session_directory / "events.jsonl"),
                },
            },
        )
        job_file = launch_file
        runtime_environment = context.runtime_environment()
    else:
        job_file, runtime_environment = _resume_job(
            session_directory, expected_session
        )

    task_prompt = prompt or task.ticket_content
    if task.instruction:
        task_prompt += "\n## Additional instruction\n\n" + task.instruction + "\n"
    if policy_role in _ENGINEER_ROLES:
        task_prompt += (
            "\nWrite the fixed candidate and self-review to "
            ".state/teams/1/rounds/1/engineer.md and its test results to "
            ".state/teams/1/rounds/1/validation.md. Include the candidate commit in both.\n"
        )
    elif policy_role in _REVIEWER_ROLES:
        if task.report_file is None:
            raise RunnerError(
                "REPORT_FILE_INVALID",
                "A Team Round Reviewer requires its writable report path.",
            )
        report = evidence / "reviews" / task.report_file.name
        report.parent.mkdir(exist_ok=True)
        if (
            report.parent.is_symlink()
            or not report.parent.is_dir()
            or os.path.lexists(report)
        ):
            raise RunnerError("REPORT_FILE_INVALID", "The Reviewer report path is not new.")
        comparison = project.dev_commit
        candidate = run_git(worktree, "rev-parse", "HEAD")
        brief = (
            "Review only for Repository Guidance and established project standards."
            if policy_role == "standards-reviewer"
            else "Review only against the accepted Ticket and its acceptance criteria."
        )
        task_prompt += (
            "\nCandidate: {0}\nComparison: {1}\nReview brief: {2}\n"
            "Inspect without modifying the candidate. Write the report only to {3}.\n".format(
                candidate, comparison, brief, task.report_file.as_posix()
            )
        )
    environment = {
        **runtime_environment,
        "GRAPHTRAJ_ROLE": role,
        "GRAPHTRAJ_EVIDENCE": str(evidence),
        "GRAPHTRAJ_TICKET_ID": task.ticket_id,
        "GRAPHTRAJ_TICKET_NAME": task.ticket_name,
        "GRAPHTRAJ_HARNESS_ROOT": str(project.harness_root),
    }
    if policy_role in _REVIEWER_ROLES:
        environment.update(
            GRAPHTRAJ_REVIEW_CANDIDATE=candidate,
            GRAPHTRAJ_REVIEW_COMPARISON=comparison,
            GRAPHTRAJ_REVIEW_BRIEF=brief,
            GRAPHTRAJ_REVIEW_REPORT=str(report),
        )
    if registration is not None:
        environment["GRAPHTRAJ_PARENT_REGISTRATION"] = str(registration)
        environment["GRAPHTRAJ_PARENT_ALIAS"] = alias
    previous = {name: os.environ.get(name) for name in environment}
    os.environ.update(environment)
    try:
        session_id, outcome = _run_session_worker(
            session_directory,
            job_file,
            worktree,
            task_prompt,
            runtime_environment,
            capacity_fd,
        )
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    if outcome != "completed":
        diagnostic = (session_directory / "stderr.log").read_text(encoding="utf-8")
        raise RunnerError(
            "RUNTIME_WORKER_FAILED",
            "The {0} Team member did not complete successfully: {1}".format(
                role, diagnostic.strip()
            ),
        )
    round_directory = evidence / "teams" / "1" / "rounds" / "1"
    reports = (
        [round_directory / "engineer.md", round_directory / "validation.md"]
        if policy_role in _ENGINEER_ROLES else
        [report] if policy_role in _REVIEWER_ROLES else
        [round_directory / "leader.md"] if role == "team-leader" else []
    )
    with (session_directory / "events.jsonl").open("a", encoding="utf-8") as trace:
        for path in reports:
            if path.is_file():
                trace.write(json.dumps({"type": "report-observed", "path": path.relative_to(evidence).as_posix(),
                                        "content": path.read_text(encoding="utf-8")}) + "\n")
    return alias, session_id


def _resume_job(
    session_directory: Path, expected_session: str
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
        or mapping.get("session") != expected_session
        or not isinstance(launch.get("connection"), dict)
    ):
        raise RunnerError("RUNTIME_WORKER_FAILED", "The mapped Session is unavailable.")
    connection = launch["connection"]
    if any(
        key not in {"base_url", "api_key_env"}
        or not isinstance(value, str)
        or not value
        for key, value in connection.items()
    ):
        raise RunnerError("RUNTIME_WORKER_FAILED", "The mapped Session is unavailable.")
    resume_file = session_directory / "resume.yml"
    write_yaml_durably(
        resume_file,
        {
            "operation": "resume",
            "runtime": mapping["runtime"],
            "adapter_request": launch["adapter_request"],
            "expected_session": expected_session,
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
) -> tuple[str, str]:
    if not isinstance(runtime_environment, dict):
        raise RunnerError("RUNTIME_WORKER_FAILED", "The Runtime Session could not be started.")
    execution = session_directory / "execution.yml"
    error = session_directory / (
        "resume-error.yml" if job_file.name == "resume.yml" else "launch-error.yml"
    )
    error.unlink(missing_ok=True)
    worker_environment = dict(os.environ)
    worker_environment.update(runtime_environment)
    try:
        with (session_directory / "worker-stderr.log").open(
            "w", encoding="utf-8"
        ) as diagnostics:
            worker = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "you_are_a_product_architect.runner_worker",
                    str(job_file),
                ],
                cwd=worktree,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=diagnostics,
                text=True,
                start_new_session=True,
                env=worker_environment,
                pass_fds=(capacity_fd,),
            )
            assert worker.stdin is not None
            worker.stdin.write(prompt)
            worker.stdin.close()
            try:
                exit_code = worker.wait()
            except BaseException:
                worker.terminate()
                worker.wait()
                raise
        if exit_code != 0:
            raise OSError("Session worker failed")
        mapping = yaml.safe_load(
            (session_directory / "mapping.yml").read_text(encoding="utf-8")
        )
        terminal = yaml.safe_load(execution.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as failure:
        raise RunnerError("RUNTIME_WORKER_FAILED", "The Runtime Session could not be started.") from failure
    if (
        not isinstance(mapping, dict)
        or not isinstance(mapping.get("session"), str)
        or not mapping["session"]
        or not isinstance(terminal, dict)
        or terminal.get("outcome") not in {"completed", "interrupted", "runtime-error"}
    ):
        raise RunnerError("RUNTIME_WORKER_FAILED", "The Runtime Session could not be started.")
    return mapping["session"], terminal["outcome"]


def _agent_alias(project: Any, task: Task, role: str) -> str:
    marker = role_alias_marker(role)
    suffix = 2 if role == "spec-reviewer" else 1
    alias = "{0}-{1}@{2}{3}".format(task.ticket_id, task.ticket_name, marker, suffix)
    while marker == "x" and (project.runner_directory / "sessions" / alias).exists():
        suffix += 1
        alias = "{0}-{1}@{2}{3}".format(task.ticket_id, task.ticket_name, marker, suffix)
    return alias



def _link_worktree(project: Any, worktree: Path, evidence: Path) -> None:
    (worktree / ".scratch").mkdir(exist_ok=True)
    links = {
        ".state": evidence,
        "CONTEXT.md": project.harness_root / "CONTEXT.md",
        "docs": project.documents_directory,
    }
    for name, target in links.items():
        link = worktree / name
        if os.path.lexists(link):
            if not link.is_symlink() or link.resolve() != target.resolve():
                raise RunnerError("STATE_LINK_FAILED", "A Ticket Worktree retained path points elsewhere.")
            continue
        link.symlink_to(os.path.relpath(target, worktree), target_is_directory=target.is_dir())


def _validate_round(round_directory: Path, worktree: Path) -> str:
    required = {"engineer.md", "validation.md", "standards.md", "spec.md", "leader.md"}
    paths = tuple(round_directory.iterdir())
    if (
        {path.name for path in paths} != required
        or any(path.is_symlink() or not path.is_file() for path in paths)
    ):
        raise RunnerError("RUNTIME_WORKER_FAILED", "The Team Round did not produce its complete evidence.")
    candidate = _candidate(round_directory, worktree)
    engineer = (round_directory / "engineer.md").read_text(encoding="utf-8")
    if any(candidate not in (round_directory / name).read_text(encoding="utf-8") for name in required):
        raise RunnerError("RUNTIME_WORKER_FAILED", "All Team evidence must inspect the same fixed candidate.")
    if "self-review" not in engineer.lower():
        raise RunnerError("RUNTIME_WORKER_FAILED", "The Team Round is missing Engineer self-review.")
    return candidate


def _candidate(round_directory: Path, worktree: Path) -> str:
    engineer = (round_directory / "engineer.md").read_text(encoding="utf-8")
    match = _COMMIT.search(engineer)
    candidate = match.group(0) if match else ""
    if (
        not candidate
        or run_git(worktree, "rev-parse", "HEAD") != candidate
        or candidate not in (round_directory / "validation.md").read_text(encoding="utf-8")
    ):
        raise RunnerError("RUNTIME_WORKER_FAILED", "The Engineer evidence does not identify the fixed candidate.")
    return candidate


def _leader_decision(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    decisions = [
        line for line in lines if line in {"Decision: ACCEPT", "Decision: REJECT"}
    ]
    return "accepted" if decisions == ["Decision: ACCEPT"] else "rejected"


def _collect_review_report(
    evidence: Path,
    round_directory: Path,
    report_name: str,
) -> None:
    source = evidence / "reviews" / report_name
    target = round_directory / report_name
    if source.is_symlink() or not source.is_file() or target.exists():
        raise RunnerError("REPORT_FILE_INVALID", "The Reviewer did not produce its exact report.")
    source.replace(target)
    if not any(source.parent.iterdir()):
        source.parent.rmdir()


def _worker_main() -> None:
    # Unwind the Session worker before releasing the Team worker's capacity.
    def stop(signum: int, frame: Any) -> None:
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, stop)
    retained = Path(sys.argv[1])
    task = read_batch(retained, Path.cwd()).tasks[int(sys.argv[2])]
    try:
        project = discover_project(Path.cwd())
        capacity_fd = int(sys.argv[3])
        if task.role == "team-leader":
            result = _deliver_ticket(project, task, retained, capacity_fd)
        else:
            evidence = project.state_directory / "tickets" / (task.ticket_id + "-" + task.ticket_name)
            state = yaml.safe_load((evidence / "ticket.yml").read_text())
            definition = evidence / state["current_definition"]
            report_name = "standards.md" if task.role == "standards-reviewer" else "spec.md"
            task = replace(
                task, ticket_file=definition, ticket_content=definition.read_text(),
                report_file=Path(".state") / "reviews" / report_name,
            )
            alias, session = _run_agent(
                project, task, task.role, project.harness_root / state["worktree"],
                evidence, evidence / "teams" / "1" / "traces",
                None, None, None, sys.argv[4], retained, capacity_fd=capacity_fd,
            )
            result = {"role": task.role, "alias": alias, "session": session, "launch_status": "completed"}
    except (RunnerError, RuntimeAdapterError) as error:
        result = _failed_task(task, RunnerError(error.code, error.message))
    print(yaml.safe_dump(result, sort_keys=False), end="")


if __name__ == "__main__":
    _worker_main()
