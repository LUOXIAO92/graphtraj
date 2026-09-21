"""Runner's bounded execution of Main's observed integration conflict."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from graphtraj.graph.delivery_worldline import read_worldline
from graphtraj.runtimes.codex.codex_adapter import read_codex_last_agent_message
from graphtraj.execution.runner_batch import retain_batch
from graphtraj.execution.runner_models import Batch, LaunchResponse, RunnerError
from graphtraj.workspace.runner_project import discover_project, run_git
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError
from graphtraj.teams.coding.team_round import _agent_alias, _run_agent
from graphtraj.graph.ticket_graph import _load_states


def launch_merge_resolver(batch: Batch, cwd: Path) -> LaunchResponse:
    """Launch only the one conflict already selected by Main for recovery."""
    if os.environ.get("GRAPHTRAJ_ROLE") or len(batch.tasks) != 1:
        raise RunnerError("invalid-input", "Only Main may dispatch one Merge Resolver for an observed conflict.")
    project = discover_project(cwd, require_clean_integration=False)
    task = batch.tasks[0]
    current = _load_states(project.state_directory / "tickets")
    if task.ticket_id not in current:
        raise RunnerError("invalid-ticket", "The conflict Ticket is not registered.")
    directory, record = current[task.ticket_id]
    events = read_worldline(project.state_directory, project.harness_root)
    conflict = next((event for event in reversed(events) if event.get("ticket_id") == task.ticket_id
                     and event["kind"].startswith("ticket-integration-")), None)
    if (record["ticket_name"] != task.ticket_name or record["status"] != "resolving-integration"
        or conflict is None or conflict["kind"] != "ticket-integration-conflict-started"
        or conflict["candidate"] != record["current_candidate"]
        or run_git(project.integration_worktree, "rev-parse", "HEAD") != conflict["dev_commit"]):
        raise RunnerError("integration-not-ready", "Main must first select a retained integration conflict for resolution.")
    definition = directory / record["current_definition"]
    task = replace(task, ticket_file=definition, ticket_content=definition.read_text())
    retained = retain_batch(project.state_directory, batch)
    generation = int(record["active_team_ordinal"])
    traces = directory / "teams" / str(generation) / "traces"
    for _ in range(10000):
        alias = _agent_alias(project, task, task.role, generation)
        session_directory = project.runner_directory / "sessions" / alias
        try:
            session_directory.mkdir()
        except FileExistsError:
            continue
        break
    else:
        raise RunnerError("ALIAS_ALLOCATION_FAILED", "No fresh Merge Resolver Session alias is available.")
    trace = traces / alias / "events.jsonl"
    trace.parent.mkdir()
    # The Trace entry later reads the Runtime-owned native Session record;
    # this Session keeps the Runner's own records for the same execution.
    trace.touch()
    (session_directory / "events.jsonl").touch()
    prompt = (
        task.ticket_content
        + f"\nFixed incoming candidate: {conflict['candidate']}\nExisting dev state: {conflict['dev_before']}"
        + f"\nCurrent dev commit: {conflict['dev_commit']}\nMain's diagnosis: {conflict['diagnosis']}\n"
        + "Exact observed conflict:\n"
        + "\n".join((project.harness_root / ref).read_text() for ref in conflict["evidence_refs"])
    )
    result = {
        "ticket_id": task.ticket_id, "role": task.role, "alias": alias,
        "worktree_path": str(project.integration_worktree),
        "trace": trace.relative_to(project.harness_root).as_posix(),
        "launch_status": "failed",
    }
    try:
        _run_agent(project, task, task.role, project.integration_worktree, directory, traces,
                   alias, None, None, None, retained, prompt)
        message = read_codex_last_agent_message(trace)
        decisions = [line for line in (message.splitlines() if message else [])
                     if line in {"Decision: RESOLVED", "Decision: ESCALATE"}]
        result["launch_status"] = "resolved" if decisions == ["Decision: RESOLVED"] else "escalated"
    except (RunnerError, RuntimeAdapterError) as error:
        result["error"] = {"code": "launch-failed", "message": str(error)}
    return LaunchResponse(
        document={"retained_batch_file": str(retained), "tasks": [result]},
        succeeded=result["launch_status"] == "resolved",
    )
