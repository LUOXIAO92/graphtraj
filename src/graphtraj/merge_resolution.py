"""Runner's bounded execution of Main's observed integration conflict."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

from .delivery_worldline import read_worldline
from .runner_batch import retain_batch
from .runner_models import Batch, LaunchResponse, RunnerError
from .runner_project import discover_project, run_git
from .runtime_adapter import RuntimeAdapterError
from .team_round import _run_agent
from .ticket_graph import _load_states


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
    traces = directory / "teams" / str(record["active_team_ordinal"]) / "traces"
    for ordinal in range(1, 10000):
        alias = f"{task.ticket_id}-{task.ticket_name}@m{ordinal}"
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
    trace.touch()
    os.link(trace, session_directory / "events.jsonl")
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
        messages = [event["item"]["text"] for line in trace.read_text().splitlines()
                    if (event := json.loads(line)).get("type") == "item.completed"
                    and event.get("item", {}).get("type") == "agent_message"]
        decisions = [line for line in (messages[-1].splitlines() if messages else [])
                     if line in {"Decision: RESOLVED", "Decision: ESCALATE"}]
        result["launch_status"] = "resolved" if decisions == ["Decision: RESOLVED"] else "escalated"
    except (RunnerError, RuntimeAdapterError) as error:
        result["error"] = {"code": "launch-failed", "message": str(error)}
    return LaunchResponse(
        document={"retained_batch_file": str(retained), "tasks": [result]},
        succeeded=result["launch_status"] == "resolved",
    )
