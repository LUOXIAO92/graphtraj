"""Main's serialized integration of a Team-accepted candidate into dev."""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import click
import yaml

from .delivery_worldline import append_project_worldline_event, read_worldline
from .git_repository import GitRepositoryError, SourceRepository, _git
from .project_configuration import ProjectConfiguration, ProjectConfigurationError, load_project_configuration
from .ticket_graph import _load_states, _lock, _restore, _unlock, _write_yaml


@click.command("integrate")
@click.option("--ticket-id", required=True)
@click.option("--resolve-conflict", metavar="DIAGNOSIS", help="Main: delegate a retained textual or semantic conflict, then validate it.")
@click.argument("validation_command", nargs=-1, required=True, type=click.UNPROCESSED)
def integrate_command(ticket_id: str, resolve_conflict: str | None, validation_command: tuple[str, ...]) -> None:
    """Main: merge the accepted Ticket, then run COMMAND in dev (after --)."""

    try:
        if os.environ.get("GRAPHTRAJ_ROLE"):
            raise ValueError("Only Main may integrate a Ticket")
        configuration = load_project_configuration(Path.cwd())
        with (configuration.harness_root / ".graphtraj/integration.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError("Another Main integration is in progress") from error
            result = _integrate(configuration, ticket_id, validation_command, resolve_conflict)
    except (OSError, ValueError, GitRepositoryError, ProjectConfigurationError, yaml.YAMLError) as error:
        click.echo(yaml.safe_dump({"error": str(error)}, sort_keys=False), nl=False)
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(result, sort_keys=False), nl=False)
    if result["status"] != "integrated":
        raise click.ClickException("Integration failed; see retained evidence")


def _integrate(configuration: ProjectConfiguration, ticket_id: str, validation_command: tuple[str, ...], diagnosis: str | None = None) -> dict:
    root, state = configuration.harness_root, configuration.state
    current = _load_states(state / "tickets")
    if ticket_id not in current:
        raise ValueError("Ticket is not registered")
    directory, record = current[ticket_id]
    candidate = record["current_candidate"]
    events = read_worldline(state, root)
    acceptance = next((event for event in reversed(events) if (
        event["kind"] == "team-round-accepted"
        and event.get("ticket_id") == ticket_id
        and event.get("candidate") == candidate
        and event.get("team_ordinal") == record["active_team_ordinal"]
    )), None)
    if not record["active"] or record["status"] not in {"awaiting-integration", "integrating"} or acceptance is None:
        raise ValueError("Integration requires the current candidate accepted by its Team Leader")
    escalated_integrations = {
        event.get("ticket_id") for event in events
        if event["kind"] == "ticket-integration-escalated"
    }
    if any(other_id != ticket_id and (
        other["status"] in {"integrating", "resolving-integration"}
        or other["status"] == "escalated" and other_id in escalated_integrations
    ) for other_id, (_, other) in current.items()):
        raise ValueError("Another Ticket has unfinished integration")
    repository = SourceRepository.from_root(configuration.project_root)
    dev = configuration.integration_worktree
    if repository.worktree_for_branch("dev") != dev or _git(dev, "branch", "--show-current") != "dev":
        raise ValueError("Integration requires the configured dev Integration Worktree")
    if diagnosis is None and _git(dev, "status", "--porcelain"):
        raise ValueError("The dev Integration Worktree must be clean")
    before = _git(dev, "rev-parse", "HEAD")
    predecessor = next((event for event in reversed(events) if event.get("ticket_id") == ticket_id and event["kind"].startswith("ticket-integration-")), acceptance)
    if diagnosis is not None:
        if (not diagnosis.strip() or predecessor["kind"] != "ticket-integration-failed"
            or predecessor.get("conflict_kind") not in {"textual", "semantic"}
            or predecessor.get("candidate") != candidate or predecessor.get("dev_commit") != before
            or predecessor.get("validation_command") != list(validation_command)):
            raise ValueError("Resolution requires a retained conflict at the same candidate and dev state, with the same integration validation")
        if predecessor["conflict_kind"] == "textual" and _git(dev, "rev-parse", "MERGE_HEAD") != candidate:
            raise ValueError("The retained merge must still target the fixed candidate")
    started = _record(configuration, directory, record, "integrating" if diagnosis is None else "resolving-integration", {
        "kind": "ticket-integration-started" if diagnosis is None else "ticket-integration-conflict-started",
        "caused_by_event_ids": [predecessor["event_id"]],
        "evidence_refs": acceptance["evidence_refs"] if diagnosis is None else predecessor["evidence_refs"],
        "candidate": candidate,
        "dev_before": before if diagnosis is None else predecessor["dev_before"],
        **({"dev_commit": before, "diagnosis": diagnosis} if diagnosis is not None else {}),
    })
    evidence = directory / "integration" / (started["event_id"] + ".log")
    evidence.parent.mkdir(exist_ok=True)
    succeeded = False
    conflict_kind = predecessor["conflict_kind"] if diagnosis is not None else None
    resolution = None
    with evidence.open("x", encoding="utf-8") as log:
        log.write(f"Candidate: {candidate}\nIntegration Worktree: {dev.relative_to(root)}\nDev before: {before}\n")
        commands = [("git", "merge", "--no-edit", candidate), validation_command]
        if diagnosis is not None:
            resolution = _resolve(configuration, record, log)
            if resolution.get("launch_status") == "resolved":
                if _git(dev, "rev-parse", "HEAD") != before:
                    log.write("Merge Resolver changed dev history; Main must inspect the retained Trace.\n")
                    resolution["launch_status"] = "escalated"
                elif predecessor["conflict_kind"] == "textual" and _git(dev, "rev-parse", "MERGE_HEAD") != candidate:
                    log.write("Merge Resolver changed the incoming merge; Main must inspect the retained Trace.\n")
                    resolution["launch_status"] = "escalated"
            commands = [("git", "commit", "--no-edit") if predecessor["conflict_kind"] == "textual"
                        else ("git", "commit", "-m", f"Reconcile Ticket {ticket_id} integration"), validation_command]
            if resolution.get("launch_status") != "resolved":
                commands = []
        for command in commands:
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
                if _git(dev, "branch", "--show-current") != "dev":
                    raise ValueError("Integration validation must leave dev checked out")
                if _git(dev, "status", "--porcelain"):
                    raise ValueError("Integration validation left dev dirty")
                succeeded = bool(commands)
            except (GitRepositoryError, ValueError) as error:
                log.write(str(error) + "\n")
    evidence.chmod(0o444)
    evidence_refs = [evidence.relative_to(root).as_posix()]
    if resolution and resolution.get("trace"):
        evidence_refs.append(resolution["trace"])
    if diagnosis is not None:
        evidence_refs.extend(ref for ref in predecessor["evidence_refs"] if ref not in evidence_refs)
    status = "integrated" if succeeded else "escalated" if resolution and resolution.get("launch_status") == "escalated" else "integrating"
    integrated = _record(configuration, directory, record, status, {
        "kind": ("ticket-integration-conflict-resolved" if diagnosis is not None else "ticket-integrated") if succeeded else "ticket-integration-escalated" if status == "escalated" else "ticket-integration-failed",
        "caused_by_event_ids": [started["event_id"]],
        "evidence_refs": evidence_refs,
        "candidate": candidate,
        "dev_before": started["dev_before"],
        "dev_commit": _git(dev, "rev-parse", "HEAD"),
        "validation_command": list(validation_command),
        **({"conflict_kind": conflict_kind} if conflict_kind else {}),
        **({"session_ref": resolution["alias"]} if resolution and resolution.get("alias") else {}),
    })
    unlocked = []
    if succeeded:
        current = _load_states(state / "tickets")
        for dependent_id, (dependent_directory, dependent) in current.items():
            if (dependent["active"] and dependent["status"] == "pending"
                and ticket_id in dependent["dependencies"]
                and all(current[blocker][1]["status"] == "integrated" for blocker in dependent["dependencies"])):
                _record(configuration, dependent_directory, dependent, "ready", {
                    "kind": "ticket-dependency-unlocked",
                    "caused_by_event_ids": [integrated["event_id"]],
                    "evidence_refs": integrated["evidence_refs"],
                })
                unlocked.append(dependent_id)
    return {"ticket_id": ticket_id, "candidate": candidate, "status": status, "event_id": integrated["event_id"], "evidence": evidence.relative_to(root).as_posix(), "unlocked_ticket_ids": unlocked}


def _resolve(configuration: ProjectConfiguration, record: dict, log) -> dict:
    batch = {"tasks": [{"ticket_id": record["ticket_id"], "ticket_name": record["ticket_name"], "role": "coding-team.merge-resolver"}]}
    with tempfile.TemporaryDirectory(dir=configuration.harness_root / ".graphtraj") as temporary:
        path = Path(temporary) / "batch.yml"
        path.write_text(yaml.safe_dump(batch))
        completed = subprocess.run(
            [str(Path(sys.executable).parent / "agent-runner"), "--batch-input", str(path)],
            cwd=configuration.harness_root, capture_output=True, text=True, check=False,
        )
    log.write(completed.stdout + completed.stderr)
    output = yaml.safe_load(completed.stdout)
    return output["tasks"][0] if isinstance(output, dict) and output.get("tasks") else {"launch_status": "failed"}


def _record(configuration: ProjectConfiguration, directory: Path, record: dict, status: str, event: dict) -> dict:
    lock = _lock(configuration.state / "tickets", exclusive=True)
    try:
        path = directory / "ticket.yml"
        previous = path.read_bytes()
        updated = {**record, "status": status}
        event.update(ticket_id=record["ticket_id"], from_status=record["status"], to_status=status)

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
