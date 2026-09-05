"""Run-free delivery of one registered Ticket through one Team Round."""

from __future__ import annotations

import os
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from .codex_adapter import create_codex_resume_turn, create_codex_turn, preflight_runtime_context
from .delivery_worldline import append_project_worldline_event
from .runner_batch import read_batch, retain_batch
from .runner_io import write_yaml_durably
from .runner_models import Batch, LaunchResponse, RunnerError, Task
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
        task.role not in _CHILD_ROLES or task.ticket_id != parent_ticket
        for task in batch.tasks
    ):
        raise RunnerError("BATCH_SCHEMA_INVALID", "A direct child Batch must contain formal roles for its parent Ticket.")
    engineers = [task for task in batch.tasks if task.role.startswith("engineer-")]
    reviewers = [task for task in batch.tasks if task.role.endswith("reviewer")]
    if not (
        (len(batch.tasks) == 1 and len(engineers) == 1)
        or {task.role for task in reviewers} == {"standards-reviewer", "spec-reviewer"}
        and len(batch.tasks) == 2
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


def launch_team_batch(batch: Batch, cwd: Path) -> LaunchResponse:
    """Deliver each Main-selected registered Ticket through generation 1."""

    if any(task.role != "team-leader" for task in batch.tasks):
        raise RunnerError("ROLE_NOT_CONFIGURED", "A Main Batch must select the team-leader preset.")
    project = discover_project(cwd)
    retained = retain_batch(project.state_directory, batch)
    results = [_deliver_ticket(project, task, retained) for task in batch.tasks]
    return LaunchResponse(
        document={"retained_batch_file": str(retained), "tasks": results},
        succeeded=True,
    )


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
    team = {
        "generation": 1,
        "status": "active",
        "current_round": 1,
        "seats": {
            "team-leader": None,
            "engineer": None,
            "standards-reviewer": None,
            "spec-reviewer": None,
        },
    }
    _write_team(team_directory / "team.yml", team)
    state.update(
        status="implementing",
        active_team_ordinal=1,
        worktree=str(worktree),
        branch=branch,
    )
    _write_ticket(state_file, state)
    start = append_project_worldline_event(
        project.state_directory,
        project.harness_root,
        {
            "kind": "team-round-started",
            "caused_by_event_ids": [],
            "evidence_refs": [(team_directory / "team.yml").relative_to(project.harness_root).as_posix()],
            "ticket_id": requested.ticket_id,
            "team_generation": 1,
            "team_round": 1,
        },
    )

    registration = project.runner_directory / "sessions" / (
        requested.ticket_id + "-" + requested.ticket_name + "@l1"
    ) / "child-registration.yml"
    leader_alias, leader_session = _run_agent(
        project, task, "team-leader", worktree, ticket_directory, traces, None, None, registration, None, retained_batch
    )
    team["seats"]["team-leader"] = _seat("team-leader", leader_alias, leader_session)
    _write_team(team_directory / "team.yml", team)

    while registration.is_file():
        registered = yaml.safe_load(registration.read_text(encoding="utf-8"))
        registration.unlink()
        child_batch = read_batch(Path(registered["retained_batch_file"]), worktree)
        expected_roles = (
            {next(task.role for task in child_batch.tasks)}
            if team["seats"]["engineer"] is None
            else {"standards-reviewer", "spec-reviewer"}
        )
        actual_roles = {child.role for child in child_batch.tasks}
        if (
            (team["seats"]["engineer"] is None and (
                len(child_batch.tasks) != 1
                or not next(iter(actual_roles)).startswith("engineer-")
            ))
            or (team["seats"]["engineer"] is not None and actual_roles != expected_roles)
            or team["seats"]["standards-reviewer"] is not None
        ):
            raise RunnerError("BATCH_SCHEMA_INVALID", "The Team Leader submitted children outside the current Team Round stage.")
        child_results = []
        for child in child_batch.tasks:
            child_task = replace(child, ticket_file=definition.resolve(), ticket_content=ticket_content)
            alias, session = _run_agent(
                project, child_task, child.role, worktree, ticket_directory, traces, None, None, None, leader_alias, Path(registered["retained_batch_file"])
            )
            seat_name = "engineer" if child.role.startswith("engineer-") else child.role
            team["seats"][seat_name] = _seat(child.role, alias, session)
            child_results.append({"role": child.role, "alias": alias, "session": session})
        _write_team(team_directory / "team.yml", team)
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
            "Direct child Batch completed:\n" + yaml.safe_dump(child_results, sort_keys=False),
        )

    candidate = _validate_round(round_directory, worktree)
    for path in round_directory.iterdir():
        path.chmod(0o444)
    round_directory.chmod(0o555)
    team["status"] = "accepted"
    _write_team(team_directory / "team.yml", team)
    state.update(status="awaiting-integration", current_candidate=candidate)
    _write_ticket(state_file, state)
    evidence = [
        path.relative_to(project.harness_root).as_posix()
        for path in sorted(round_directory.iterdir())
    ]
    append_project_worldline_event(
        project.state_directory,
        project.harness_root,
        {
            "kind": "team-round-accepted",
            "caused_by_event_ids": [start["event_id"]],
            "evidence_refs": evidence,
            "ticket_id": requested.ticket_id,
            "team_generation": 1,
            "team_round": 1,
            "candidate": candidate,
        },
    )
    return {
        "ticket_id": requested.ticket_id,
        "ticket_name": requested.ticket_name,
        "role": "team-leader",
        "launch_status": "accepted",
        "worktree_path": str(worktree),
        "alias": leader_alias,
        "session": leader_session,
    }


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
        marker = {"team-leader": "l", "engineer-junior": "j", "engineer-senior": "s", "engineer-expert": "e", "standards-reviewer": "r", "spec-reviewer": "r"}[role]
        suffix = "2" if role == "spec-reviewer" else "1"
        alias = "{0}-{1}@{2}{3}".format(task.ticket_id, task.ticket_name, marker, suffix)
        session_directory = project.runner_directory / "sessions" / alias
        session_directory.mkdir(parents=True, exist_ok=False)
        trace_directory = traces / alias
        trace_directory.mkdir()
        trace = trace_directory / "events.jsonl"
        trace.touch()
        os.link(trace, session_directory / "events.jsonl")
    else:
        session_directory = project.runner_directory / "sessions" / alias

    preset = project.role_bindings[role]
    context = preflight_runtime_context(
        runtime_store=project.runtime_store,
        executable=runtime_executable(preset.runtime),
        git_common_directory=project.common_directory,
        role=role,
        model=preset.model,
        base_url=preset.base_url,
        api_key_env=preset.api_key_env,
        worktree=worktree,
        evidence=evidence,
        repository_skill_source=worktree,
        requested_skills=(),
        report_file=None,
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
        report = "standards.md" if role == "standards-reviewer" else "spec.md"
        task_prompt += (
            "\nInspect HEAD without modifying it. Write the decision and exact candidate commit to "
            ".state/teams/1/rounds/1/{0}.\n".format(report)
        )
    environment = {
        "GRAPHTRAJ_ROLE": role,
        "GRAPHTRAJ_EVIDENCE": str(evidence),
        "GRAPHTRAJ_TICKET_ID": task.ticket_id,
        "GRAPHTRAJ_TICKET_NAME": task.ticket_name,
        "GRAPHTRAJ_HARNESS_ROOT": str(project.harness_root),
    }
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


def _seat(role: str, alias: str, session: str) -> dict[str, str]:
    return {"role": role, "alias": alias, "session": session}


def _write_team(path: Path, team: dict[str, Any]) -> None:
    expected_seats = {"team-leader", "engineer", "standards-reviewer", "spec-reviewer"}
    if (
        set(team) != {"generation", "status", "current_round", "seats"}
        or team["generation"] != 1
        or team["current_round"] != 1
        or team["status"] not in {"active", "accepted"}
        or not isinstance(team["seats"], dict)
        or set(team["seats"]) != expected_seats
        or any(
            seat is not None
            and (
                not isinstance(seat, dict)
                or set(seat) != {"role", "alias", "session"}
                or any(not isinstance(value, str) or not value for value in seat.values())
            )
            for seat in team["seats"].values()
        )
        or (team["status"] == "accepted" and any(seat is None for seat in team["seats"].values()))
    ):
        raise RunnerError("STATE_DIRECTORY_INVALID", "The requested Team state change is invalid.")
    write_yaml_durably(path, team)


def _write_ticket(path: Path, state: dict[str, Any]) -> None:
    if (
        state.get("status") not in {"implementing", "awaiting-integration"}
        or state.get("active_team_ordinal") != 1
        or not isinstance(state.get("worktree"), str)
        or not isinstance(state.get("branch"), str)
        or (
            state["status"] == "awaiting-integration"
            and (
                not isinstance(state.get("current_candidate"), str)
                or _COMMIT.fullmatch(state["current_candidate"]) is None
            )
        )
    ):
        raise RunnerError("STATE_DIRECTORY_INVALID", "The requested Ticket state change is invalid.")
    write_yaml_durably(path, state)


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
    engineer = (round_directory / "engineer.md").read_text(encoding="utf-8")
    match = _COMMIT.search(engineer)
    candidate = match.group(0) if match else ""
    if not candidate or run_git(worktree, "rev-parse", "HEAD") != candidate:
        raise RunnerError("RUNTIME_WORKER_FAILED", "The Engineer evidence does not identify the fixed candidate.")
    if any(candidate not in (round_directory / name).read_text(encoding="utf-8") for name in required):
        raise RunnerError("RUNTIME_WORKER_FAILED", "All Team evidence must inspect the same fixed candidate.")
    if "self-review" not in engineer.lower() or "accept" not in (
        round_directory / "leader.md"
    ).read_text(encoding="utf-8").lower():
        raise RunnerError("RUNTIME_WORKER_FAILED", "The Team Round is missing self-review or final acceptance.")
    return candidate
