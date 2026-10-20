"""Serialized integration of an accepted task result into dev."""

from __future__ import annotations

from graphtraj.configuration.project_configuration import runner_directory as project_runner_directory

import subprocess
from pathlib import Path
from typing import TextIO

import yaml

from graphtraj import file_lock
from graphtraj.execution.runner_models import Batch
from graphtraj.execution.runner_status import caller_alias, read_alias_mapping, require_task_authority
from graphtraj.graph.delivery_worldline import append_project_worldline_event, read_worldline
from graphtraj.workspace.git_repository import GitRepositoryError, SourceRepository, _git
from graphtraj.configuration.project_configuration import ProjectConfiguration
from graphtraj.graph.task_graph import _load_states, _lock, _restore, _unlock, _write_yaml, _result_complete


def integrate_task(
    configuration: ProjectConfiguration,
    task_id: str,
    validation_command: tuple[str, ...],
    diagnosis: str | None = None,
    role: str | dict | None = None,
    confirmed_commit: str | None = None,
) -> dict:
    """Integrate under the actual task authority and retain its version evidence.

    Run validation_command as argv in dev after merging the Team-accepted
    candidate. A failed merge or validation returns a non-integrated status and
    retained evidence. Authority, lock and readiness failures raise ValueError;
    Caller verification, configuration and filesystem errors retain their existing
    exception types.
    """
    if (
        not isinstance(validation_command, tuple)
        or not validation_command
        or not validation_command[0]
        or any(not isinstance(arg, str) for arg in validation_command)
    ):
        raise ValueError("Integration requires a non-empty validation command argv")
    with (configuration.harness_root / ".graphtraj/integration.lock").open("a") as lock:
        try:
            file_lock.flock(lock, file_lock.LOCK_EX | file_lock.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Another integration is in progress") from error
        return _integrate(configuration, task_id, validation_command, diagnosis, role, confirmed_commit)


def _integrate(
    configuration: ProjectConfiguration,
    task_id: str,
    validation_command: tuple[str, ...],
    diagnosis: str | None = None,
    role: str | dict | None = None,
    confirmed_commit: str | None = None,
) -> dict:
    """Merge or adopt the retained accepted version, then validate completion."""
    root, state = configuration.harness_root, configuration.state
    current = _load_states(state / "tasks")
    if task_id not in current:
        raise ValueError("Task is not registered")
    directory, record = current[task_id]
    candidate = record["current_candidate"]
    events = read_worldline(state, root)
    acceptance = next((event for event in reversed(events) if (
        event["event"] == "team-round-accepted"
        and event.get("task_id") == task_id
        and event.get("candidate") == candidate
        and event.get("team_ordinal") == record["active_team_ordinal"]
    )), None)
    runner = project_runner_directory(root)
    caller = caller_alias(runner)
    if caller is not None:
        submission = next((event for event in events if acceptance is not None
                           and event['event_id'] == acceptance.get('submission_id')), None)
        if submission is None:
            raise ValueError("Integration requires the actual accepted result's parent")
        require_task_authority(state, runner, task_id, submission['alias'], 'integrate')
    if (diagnosis is None) != (role is None):
        raise ValueError("Conflict resolution requires an explicitly selected role and diagnosis")
    batch = None
    if diagnosis is not None:
        from graphtraj.execution.runner_batch import parse_batch
        from graphtraj.teams.team_round import _require_dispatch_roles
        from graphtraj.workspace.runner_project import discover_project

        batch = parse_batch({"tasks": [{"task_id": task_id, "task_name": record["task_name"],
                                       "role": role, "instruction": diagnosis}]})
        parent = read_alias_mapping(runner, caller)[0] if caller is not None else None
        _require_dispatch_roles(discover_project(root, require_clean_integration=False), batch, parent)
    resolving = record["status"] == "resolving-integration"
    retrying = record["status"] == "escalated" and diagnosis is not None
    recovering = record["status"] == "escalated" and not retrying
    if not record["active"] or record["status"] not in {"awaiting-integration", "integrating", "escalated", "resolving-integration"} or acceptance is None:
        raise ValueError("Integration requires acceptance of the current candidate")
    escalated_integrations = {
        event.get("task_id") for event in events
        if event["event"] == "task-integration-escalated"
    }
    if any(other_id != task_id and (
        other["status"] in {"integrating", "resolving-integration"}
        or other["status"] == "escalated" and other_id in escalated_integrations
    ) for other_id, (_, other) in current.items()):
        raise ValueError("Another Task has unfinished integration")
    repository = SourceRepository.from_root(configuration.project_root)
    dev = configuration.integration_worktree
    if repository.worktree_for_branch("dev") != dev or _git(dev, "branch", "--show-current") != "dev":
        raise ValueError("Integration requires the configured dev Integration Worktree")
    if diagnosis is None and (_git(dev, "status", "--porcelain")
                              or (dev / _git(dev, "rev-parse", "--git-path", "MERGE_HEAD")).exists()):
        raise ValueError("The dev Integration Worktree must be clean")
    before = _git(dev, "rev-parse", "HEAD")
    predecessor = next((event for event in reversed(events) if event.get("task_id") == task_id and event["event"].startswith("task-integration-")), acceptance)
    if resolving and diagnosis is None:
        conflict = next(event for event in reversed(events)
                        if event.get('task_id') == task_id
                        and event['event'] == 'task-integration-conflict-started')
        submitted = next((event for event in reversed(events)
                          if event['event'] == 'result-submitted' and event.get('task_id') == task_id
                          and event.get('team_ordinal') == record['active_team_ordinal']
                          and event['event_id'] > conflict['event_id']), None)
        decision = next((event for event in reversed(events)
                         if submitted is not None and event.get('submission_id') == submitted['event_id']
                         and event['event'] == 'team-round-accepted'), None)
        if decision is None or submitted['candidate'] != before:
            raise ValueError("Integration requires acceptance of the latest committed resolution")
        mapping = read_alias_mapping(runner, submitted['alias'])[0]
        if (Path(mapping['worktree_path']) != dev
                or predecessor.get('validation_command') != list(validation_command)):
            raise ValueError("Resolution acceptance must match this retained integration")
        _git(dev, 'merge-base', '--is-ancestor', candidate, before)
        _git(dev, 'merge-base', '--is-ancestor', predecessor['dev_commit'], before)
    if confirmed_commit is not None and (not recovering or confirmed_commit != before):
        raise ValueError("Confirmation must name the current committed escalated integration")
    if recovering:
        if confirmed_commit != before:
            raise ValueError("Recovery requires explicit confirmation of the committed resolution")
        if (diagnosis is not None or predecessor["event"] != "task-integration-escalated"
            or predecessor.get("candidate") != candidate
            or predecessor.get("validation_command") != list(validation_command)):
            raise ValueError("Recovery requires the retained accepted candidate and the same integration validation")
        # A committed resolution must contain both sides of the retained attempt.
        # Adoption runs no specialist and never resets the stopped task budget.
        try:
            _git(dev, "merge-base", "--is-ancestor", candidate, before)
            _git(dev, "merge-base", "--is-ancestor", predecessor["dev_commit"], before)
        except GitRepositoryError as error:
            raise ValueError("Recovery requires the accepted candidate and retained dev commit in HEAD") from error
    if diagnosis is not None:
        if (not diagnosis.strip() or predecessor["event"] != (
                "task-integration-escalated" if retrying else "task-integration-failed")
            or predecessor.get("conflict_kind") not in {"textual", "semantic"}
            or predecessor.get("candidate") != candidate or predecessor.get("dev_commit") != before
            or predecessor.get("validation_command") != list(validation_command)):
            raise ValueError("Resolution requires a retained conflict at the same candidate and dev state, with the same integration validation")
        if predecessor["conflict_kind"] == "textual" and _git(dev, "rev-parse", "MERGE_HEAD") != candidate:
            raise ValueError("The retained merge must still target the fixed candidate")
        if retrying:
            from graphtraj.teams.merge_resolution import require_unestablished_resolution

            require_unestablished_resolution(configuration, record, events, batch.tasks[0], caller)
    started = _record(configuration, directory, record, "integrating" if diagnosis is None else "resolving-integration", {
        "event": "task-integration-started" if diagnosis is None else "task-integration-conflict-started",
        "caused_by_event_ids": [predecessor["event_id"]] + ([decision["event_id"]] if resolving and diagnosis is None else []),
        "alias": caller,
        "session": read_alias_mapping(runner, caller)[0]["session"] if caller is not None else None,
        "evidence_refs": acceptance["evidence_refs"] if diagnosis is None else predecessor["evidence_refs"],
        "candidate": candidate,
        **({"confirmed_commit": confirmed_commit} if recovering else {}),
        "dev_before": before if diagnosis is None else predecessor["dev_before"],
        **({"dev_commit": before, "diagnosis": diagnosis,
            "role_reference": batch.tasks[0].role_reference or batch.tasks[0].role,
            "instruction": batch.tasks[0].instruction, "parent": caller,
            "validation_command": list(validation_command)} if diagnosis is not None else {}),
    })
    evidence = directory / "integration" / (started["event_id"] + ".log")
    evidence.parent.mkdir(exist_ok=True)
    succeeded = False
    conflict_kind = predecessor["conflict_kind"] if diagnosis is not None else None
    resolution = None
    validated_commit = None
    with evidence.open("x", encoding="utf-8") as log:
        log.write(f"Candidate: {candidate}\nIntegration Worktree: {dev.relative_to(root)}\nDev before: {before}\n")
        commands = [validation_command] if recovering or resolving else [("git", "merge", "--no-edit", candidate), validation_command]
        if diagnosis is not None:
            resolution = _resolve(configuration, batch, log)
            commands = []
        for command in commands:
            if command == validation_command:
                validated_commit = _git(dev, "rev-parse", "HEAD")
            log.write("Command: " + yaml.safe_dump(list(command), default_flow_style=True).strip() + "\n")
            log.flush()
            try:
                completed = subprocess.run(command, cwd=dev, stdout=log, stderr=subprocess.STDOUT, check=False)
            except OSError as error:
                log.write(str(error) + "\n")
                break
            log.write(f"Exit status: {completed.returncode}\n")
            if completed.returncode:
                if command == validation_command:
                    conflict_kind = "semantic"
                elif command[:2] == ("git", "merge") and _git(dev, "diff", "--name-only", "--diff-filter=U"):
                    conflict_kind = "textual"
                break
        else:
            try:
                _git(dev, "merge-base", "--is-ancestor", candidate, "refs/heads/dev")
                if validated_commit is not None and _git(dev, "rev-parse", "HEAD") != validated_commit:
                    raise ValueError("Integration validation changed the committed version")
                if _git(dev, "branch", "--show-current") != "dev":
                    raise ValueError("Integration validation must leave dev checked out")
                if (_git(dev, "status", "--porcelain")
                        or (dev / _git(dev, "rev-parse", "--git-path", "MERGE_HEAD")).exists()):
                    raise ValueError("Integration validation left dev dirty")
                succeeded = bool(commands)
            except (GitRepositoryError, ValueError) as error:
                log.write(str(error) + "\n")
    evidence.chmod(0o444)
    evidence_refs = [evidence.relative_to(root).as_posix()]
    if resolution and resolution.get("alias") and resolution.get("launch_status") != "registered":
        mapping, _ = read_alias_mapping(runner, resolution["alias"])
        evidence_refs.append(Path(mapping["trace_file"]).relative_to(root).as_posix())
        resolution["submissions"] = [event for event in read_worldline(state, root)
                                     if event['event'] == 'result-submitted'
                                     and event.get('alias') == resolution['alias']
                                     and event['event_id'] > started['event_id']]
    if resolving and diagnosis is None:
        evidence_refs.extend(decision['evidence_refs'])
    if diagnosis is not None or recovering:
        evidence_refs.extend(ref for ref in predecessor["evidence_refs"] if ref not in evidence_refs)
    status = ("integrated" if succeeded else "escalated" if recovering or (
        resolution and resolution.get('launch_status') != 'registered' and not resolution.get('submissions')
    ) else "resolving-integration" if resolution or resolving else "integrating")
    integrated = _record(configuration, directory, record, status, {
        "event": ("task-integration-conflict-resolved" if resolving else "task-integrated") if succeeded else "task-integration-escalated" if status == "escalated" else "task-integration-conflict-dispatched" if resolution else "task-integration-failed",
        "caused_by_event_ids": [started["event_id"]],
        "evidence_refs": evidence_refs,
        "candidate": candidate,
        "dev_before": started["dev_before"],
        "dev_commit": before if resolution else _git(dev, "rev-parse", "HEAD"),
        "validation_command": list(validation_command),
        **({"conflict_kind": conflict_kind} if conflict_kind else {}),
        **({"session_ref": resolution["alias"]} if resolution and resolution.get("alias") else {}),
    })
    unlocked = []
    if succeeded:
        current = _load_states(state / "tasks")
        for dependent_id, (dependent_directory, dependent) in current.items():
            if (dependent["active"] and dependent["status"] == "pending"
                and task_id in dependent["dependencies"]
                and all(_result_complete({key: value for key, (_, value) in current.items()}, blocker)
                        for blocker in dependent["dependencies"])):
                _record(configuration, dependent_directory, dependent, "ready", {
                    "event": "task-dependency-unlocked",
                    "caused_by_event_ids": [integrated["event_id"]],
                    "evidence_refs": integrated["evidence_refs"],
                })
                unlocked.append(dependent_id)
    return {"task_id": task_id, "candidate": candidate, "status": status, **({"resolution": resolution} if resolution else {}), "event_id": integrated["event_id"], "evidence": evidence.relative_to(root).as_posix(), "unlocked_task_ids": unlocked}


def _resolve(configuration: ProjectConfiguration, batch: Batch, log: TextIO) -> dict:
    """Dispatch the explicitly selected role through ordinary Runner execution."""
    from graphtraj.execution.runner_launch import launch_batch
    from graphtraj.execution.runner_models import RunnerError

    log.flush()
    try:
        response = launch_batch(batch, configuration.harness_root)
    except RunnerError as error:
        log.write(yaml.safe_dump({"error": error.as_document()}, sort_keys=False))
        return {"launch_status": "failed"}
    log.write(yaml.safe_dump(response.document, sort_keys=False))
    return response.document["tasks"][0]


def _record(configuration: ProjectConfiguration, directory: Path, record: dict, status: str, event: dict) -> dict:
    """Recheck the current version and record one integration lifecycle event."""
    lock = _lock(configuration.state / "tasks", exclusive=True)
    try:
        current = _load_states(configuration.state / "tasks")
        latest = current[record["task_id"]][1]
        if (latest["current_definition"] != record["current_definition"]
                or latest["current_candidate"] != record["current_candidate"]):
            raise ValueError("The Task changed during integration; inspect its current definition and result")
        if status == "integrated":
            records = {key: value for key, (_, value) in current.items()}
            required = list(latest["dependencies"]) + [
                key for key, child in records.items()
                if child.get("parent_id") == record["task_id"] and child.get("disposition") != "cancelled"
            ]
            if any(not _result_complete(records, key) for key in required):
                raise ValueError("Integration completion requires the task's necessary child and dependency results")
        path = directory / "task.yml"
        previous = path.read_bytes()
        updated = {**record, "status": status}
        event.update(task_id=record["task_id"], from_status=record["status"], to_status=status)

        def mutation(_):
            try:
                _write_yaml(path, updated)
            except Exception:
                _restore(path, previous)
                raise
            return lambda: _restore(path, previous)

        result = append_project_worldline_event(configuration.state, configuration.harness_root, event, mutation)
        record.update(updated)
        return result
    finally:
        _unlock(lock)
