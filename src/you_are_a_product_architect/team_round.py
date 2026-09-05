"""Run-free delivery of one registered Ticket through one Team Round."""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from .codex_adapter import create_codex_resume_turn, create_codex_turn, preflight_runtime_context
from .delivery_state import apply_delivery_state_request
from .delivery_worldline import read_worldline
from .runner_batch import read_batch, resolved_role_preset, retain_batch
from .runner_io import write_yaml_durably
from .runner_models import Batch, LaunchResponse, RunnerError, Task, role_alias_marker
from .runner_project import discover_project, preflight_worktree, provision_worktree, run_git, runtime_executable


_COMMIT = re.compile(r"[0-9a-f]{40}")
_CHILD_ROLES = frozenset(
    {
        "engineer-junior",
        "engineer-senior",
        "engineer-expert",
        "standards-reviewer",
        "spec-reviewer",
    }
)


def register_child_batch(batch_file: Path, cwd: Path, registration: Path) -> LaunchResponse:
    """Retain and register the Team Leader's one direct child Batch."""

    batch = read_batch(batch_file, cwd)
    parent_ticket = os.environ.get("GRAPHTRAJ_TICKET_ID")
    if batch.run_id is not None or any(
        task.ticket_id != parent_ticket
        or (
            task.role not in _CHILD_ROLES
            and not _is_inline_specialist(task)
        )
        for task in batch.tasks
    ):
        raise RunnerError("BATCH_SCHEMA_INVALID", "A direct child Batch must contain formal roles for its parent Ticket.")
    engineers = [task for task in batch.tasks if task.role.startswith("engineer-")]
    reviewers = [task for task in batch.tasks if task.role.endswith("reviewer")]
    if not (
        (len(batch.tasks) == 1 and len(engineers) == 1)
        or {task.role for task in reviewers} == {"standards-reviewer", "spec-reviewer"}
        and len(batch.tasks) == 2
        or len(batch.tasks) == 1 and _is_inline_specialist(batch.tasks[0])
    ):
        raise RunnerError("BATCH_SCHEMA_INVALID", "A direct child Batch must contain one Engineer or both Reviewers.")
    project = discover_project(Path(os.environ.get("GRAPHTRAJ_HARNESS_ROOT", cwd)))
    retained = retain_batch(project.state_directory, batch)
    try:
        if registration.exists():
            raise OSError("a child Batch is already registered")
        write_yaml_durably(registration, {"retained_batch_file": str(retained)})
    except (OSError, yaml.YAMLError) as error:
        raise RunnerError("BATCH_RETENTION_FAILED", "The parent worker could not register the child Batch.") from error
    return LaunchResponse(
        document={
            "retained_batch_file": str(retained),
            "tasks": [
                {"ticket_id": task.ticket_id, "role": task.role, "launch_status": "registered"}
                for task in batch.tasks
            ],
        },
        succeeded=True,
    )


def _is_inline_specialist(task: Task) -> bool:
    """Return whether a task uses the fixed non-Team temporary policy."""

    return task.inline_preset is not None and task.policy_role == "temporary-role"


def launch_team_batch(batch: Batch, cwd: Path) -> LaunchResponse:
    """Deliver each Main-selected registered Ticket through generation 1."""

    if all(task.role == "team-leader" for task in batch.tasks):
        project = discover_project(cwd)
        retained = retain_batch(project.state_directory, batch)
        results = [_deliver_ticket(project, task, retained) for task in batch.tasks]
        return LaunchResponse(
            document={"retained_batch_file": str(retained), "tasks": results},
            succeeded=True,
        )
    if any(task.policy_role != "temporary-role" for task in batch.tasks):
        raise RunnerError("ROLE_NOT_CONFIGURED", "A Main Batch must select the team-leader preset.")
    project = discover_project(cwd)
    retained = retain_batch(project.state_directory, batch)
    traces = project.runner_directory / "traces"
    evidence = project.runner_directory / "inline-evidence"
    traces.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)
    results = []
    for requested in batch.tasks:
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


def _deliver_ticket(project: Any, requested: Task, retained_batch: Path) -> dict[str, Any]:
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
    leader_alias, leader_session = _run_agent(
        project, task, "team-leader", worktree, ticket_directory, traces, None, None, registration, None, retained_batch
    )
    engineer_batch, engineer_batch_path, leader_alias, leader_session = _next_formal_batch(
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
    if len(engineer_batch.tasks) != 1 or not engineer_batch.tasks[0].role.startswith("engineer-"):
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
    state_alias, state_session, event = _request_state(
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

    engineer_alias, engineer_session = _run_agent(
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
    state_alias, state_session, event = _request_state(
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
    state_alias, state_session, event = _request_state(
        project, task, worktree, ticket_directory, traces,
        state_alias, state_session, leader_alias, engineer_batch_path,
        {
            "phase": "candidate", "ticket_id": task.ticket_id,
            "caused_by_event_ids": [predecessor],
            "evidence_refs": [
                (round_directory / name).relative_to(project.harness_root).as_posix()
                for name in ("engineer.md", "validation.md")
            ],
            "candidate": candidate,
        },
        "candidate",
    )
    predecessor = event["event_id"]

    leader_alias, leader_session = _run_agent(
        project, task, "team-leader", worktree, ticket_directory, traces,
        leader_alias, leader_session, registration, None, retained_batch,
        "Engineer completed:\n" + yaml.safe_dump(
            {"role": engineer_task.role, "alias": engineer_alias, "session": engineer_session},
            sort_keys=False,
        ),
    )
    reviewer_batch, reviewer_batch_path, leader_alias, leader_session = _next_formal_batch(
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
    if {child.role for child in reviewer_batch.tasks} != {"standards-reviewer", "spec-reviewer"}:
        raise RunnerError("BATCH_SCHEMA_INVALID", "The second direct child Batch must contain both Reviewers.")
    child_results = []
    for child in reviewer_batch.tasks:
        report_name = (
            "standards.md" if child.role == "standards-reviewer" else "spec.md"
        )
        child_task = replace(
            child,
            ticket_file=definition.resolve(),
            ticket_content=ticket_content,
            report_file=Path(".state") / "reviews" / report_name,
        )
        alias, session = _run_agent(
            project, child_task, child.role, worktree, ticket_directory, traces,
            None, None, None, leader_alias, reviewer_batch_path,
        )
        _collect_review_report(ticket_directory, round_directory, report_name)
        member = "standards_reviewer" if child.role == "standards-reviewer" else "spec_reviewer"
        state_alias, state_session, event = _request_state(
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
        child_results.append({"role": child.role, "alias": alias, "session": session})

    leader_alias, leader_session = _run_agent(
        project, task, "team-leader", worktree, ticket_directory, traces,
        leader_alias, leader_session, registration, None, retained_batch,
        "Reviewers completed:\n" + yaml.safe_dump(child_results, sort_keys=False),
    )
    if registration.exists():
        raise RunnerError("BATCH_SCHEMA_INVALID", "The completed Team Round cannot register another child Batch.")
    candidate = _validate_round(round_directory, worktree)
    decision = _leader_decision(round_directory / "leader.md")
    evidence = [
        path.relative_to(project.harness_root).as_posix()
        for path in sorted(round_directory.iterdir())
    ]
    _request_state(
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
) -> tuple[Batch, Path, str, str]:
    """Run temporary child specialists before returning the next formal Batch."""

    while True:
        batch, batch_path = _registered_batch(registration, worktree)
        if len(batch.tasks) != 1 or not _is_inline_specialist(batch.tasks[0]):
            return batch, batch_path, leader_alias, leader_session
        specialist = replace(
            batch.tasks[0],
            ticket_file=definition.resolve(),
            ticket_content=ticket_content,
        )
        alias, session = _run_agent(
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
        leader_alias, leader_session = _run_agent(
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
                {"role": specialist.role, "alias": alias, "session": session},
                sort_keys=False,
            ),
        )


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
) -> tuple[str, str]:
    if alias is None:
        marker = role_alias_marker(role)
        suffix = "2" if role == "spec-reviewer" else "1"
        alias = "{0}-{1}@{2}{3}".format(task.ticket_id, task.ticket_name, marker, suffix)
        session_directory = project.runner_directory / "sessions" / alias
        while marker == "x" and session_directory.exists():
            suffix = str(int(suffix) + 1)
            alias = "{0}-{1}@{2}{3}".format(
                task.ticket_id, task.ticket_name, marker, suffix
            )
            session_directory = project.runner_directory / "sessions" / alias
        session_directory.mkdir(parents=True, exist_ok=False)
        trace_directory = traces / alias
        trace_directory.mkdir()
        trace = trace_directory / "events.jsonl"
        trace.touch()
        os.link(trace, session_directory / "events.jsonl")
    else:
        session_directory = project.runner_directory / "sessions" / alias

    inline_role = task.inline_preset is not None and task.role == role
    preset = (
        resolved_role_preset(task, project.role_bindings)
        if inline_role
        else project.role_bindings[role]
    )
    context = preflight_runtime_context(
        runtime_store=project.runtime_store,
        executable=runtime_executable(preset.runtime),
        git_common_directory=project.common_directory,
        role=(task.policy_role or role) if inline_role else role,
        model=preset.model,
        base_url=preset.base_url,
        api_key_env=preset.api_key_env,
        worktree=worktree,
        evidence=evidence,
        repository_skill_source=worktree,
        requested_skills=(),
        report_file=task.report_file,
    ).finalize()
    session_id: str | None = expected_session

    def record_session(value: str, runtime_pid: int) -> None:
        nonlocal session_id
        session_id = value
        write_yaml_durably(
            session_directory / "mapping.yml",
            {
                "alias": alias,
                "runtime": context.runtime,
                "session": value,
                "ticket_id": task.ticket_id,
                "team_generation": 1,
                "role": role,
                "parent": parent_alias,
                "retained_batch_file": str(retained_batch),
                "worker_pid": os.getpid(),
                "runtime_pid": runtime_pid,
            },
        )

    task_prompt = prompt or task.ticket_content
    if task.instruction:
        task_prompt += "\n## Additional instruction\n\n" + task.instruction + "\n"
    if role.startswith("engineer-"):
        task_prompt += (
            "\nWrite the fixed candidate and self-review to "
            ".state/teams/1/rounds/1/engineer.md and its test results to "
            ".state/teams/1/rounds/1/validation.md. Include the candidate commit in both.\n"
        )
    elif role.endswith("reviewer"):
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
            if role == "standards-reviewer"
            else "Review only against the accepted Ticket and its acceptance criteria."
        )
        task_prompt += (
            "\nCandidate: {0}\nComparison: {1}\nReview brief: {2}\n"
            "Inspect without modifying the candidate. Write the report only to {3}.\n".format(
                candidate, comparison, brief, task.report_file.as_posix()
            )
        )
    environment = {
        "GRAPHTRAJ_ROLE": role,
        "GRAPHTRAJ_EVIDENCE": str(evidence),
        "GRAPHTRAJ_TICKET_ID": task.ticket_id,
        "GRAPHTRAJ_TICKET_NAME": task.ticket_name,
        "GRAPHTRAJ_HARNESS_ROOT": str(project.harness_root),
    }
    if role.endswith("reviewer"):
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
        request = context.launch_document()["adapter_request"]
        turn = (
            create_codex_turn(request, task_prompt, session_directory, record_session)
            if expected_session is None
            else create_codex_resume_turn(request, task_prompt, expected_session, session_directory, record_session)
        )
        outcome = turn.run()
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    if outcome.get("outcome") != "completed" or session_id is None:
        diagnostic = (session_directory / "stderr.log").read_text(encoding="utf-8")
        raise RunnerError(
            "RUNTIME_WORKER_FAILED",
            "The {0} Team member did not complete successfully ({1}): {2}".format(
                role, outcome.get("runtime_exit_code"), diagnostic.strip()
            ),
        )
    return alias, session_id


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
