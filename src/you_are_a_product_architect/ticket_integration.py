"""Main's serialized integration of a Team-accepted candidate into dev."""

from __future__ import annotations

import fcntl
import os
import subprocess
from pathlib import Path

import click
import yaml

from .delivery_worldline import append_project_worldline_event, read_worldline
from .git_repository import GitRepositoryError, SourceRepository, _git
from .project_configuration import ProjectConfiguration, ProjectConfigurationError, load_project_configuration
from .ticket_graph import _load_states, _lock, _restore, _unlock, _write_yaml


@click.command("integrate")
@click.option("--ticket-id", required=True)
@click.argument("validation_command", nargs=-1, required=True, type=click.UNPROCESSED)
def integrate_command(ticket_id: str, validation_command: tuple[str, ...]) -> None:
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
            result = _integrate(configuration, ticket_id, validation_command)
    except (OSError, ValueError, GitRepositoryError, ProjectConfigurationError, yaml.YAMLError) as error:
        click.echo(yaml.safe_dump({"error": str(error)}, sort_keys=False), nl=False)
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(result, sort_keys=False), nl=False)
    if result["status"] != "integrated":
        raise click.ClickException("Integration failed; see retained evidence")


def _integrate(configuration: ProjectConfiguration, ticket_id: str, validation_command: tuple[str, ...]) -> dict:
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
    if any(other_id != ticket_id and other["status"] in {"integrating", "resolving-integration"} for other_id, (_, other) in current.items()):
        raise ValueError("Another Ticket has unfinished integration")
    repository = SourceRepository.from_root(configuration.project_root)
    dev = configuration.integration_worktree
    if repository.worktree_for_branch("dev") != dev or _git(dev, "branch", "--show-current") != "dev":
        raise ValueError("Integration requires the configured dev Integration Worktree")
    if _git(dev, "status", "--porcelain"):
        raise ValueError("The dev Integration Worktree must be clean")
    before = _git(dev, "rev-parse", "HEAD")
    predecessor = next((event for event in reversed(events) if event.get("ticket_id") == ticket_id and event["kind"].startswith("ticket-integration-")), acceptance)
    started = _record(configuration, directory, record, "integrating", {
        "kind": "ticket-integration-started",
        "caused_by_event_ids": [predecessor["event_id"]],
        "evidence_refs": acceptance["evidence_refs"],
        "candidate": candidate,
        "dev_before": before,
    })
    evidence = directory / "integration" / (started["event_id"] + ".log")
    evidence.parent.mkdir(exist_ok=True)
    succeeded = False
    with evidence.open("x", encoding="utf-8") as log:
        log.write(f"Candidate: {candidate}\nIntegration Worktree: {dev.relative_to(root)}\nDev before: {before}\n")
        for command in (("git", "merge", "--no-edit", candidate), validation_command):
            log.write("Command: " + yaml.safe_dump(list(command), default_flow_style=True).strip() + "\n")
            log.flush()
            try:
                completed = subprocess.run(command, cwd=dev, stdout=log, stderr=subprocess.STDOUT, check=False)
            except OSError as error:
                log.write(str(error) + "\n")
                break
            log.write(f"Exit status: {completed.returncode}\n")
            if completed.returncode:
                break
        else:
            try:
                _git(dev, "merge-base", "--is-ancestor", candidate, "refs/heads/dev")
                if _git(dev, "branch", "--show-current") != "dev":
                    raise ValueError("Integration validation must leave dev checked out")
                if _git(dev, "status", "--porcelain"):
                    raise ValueError("Integration validation left dev dirty")
                succeeded = True
            except (GitRepositoryError, ValueError) as error:
                log.write(str(error) + "\n")
    evidence.chmod(0o444)
    integrated = _record(configuration, directory, record, "integrated" if succeeded else "integrating", {
        "kind": "ticket-integrated" if succeeded else "ticket-integration-failed",
        "caused_by_event_ids": [started["event_id"]],
        "evidence_refs": [evidence.relative_to(root).as_posix()],
        "candidate": candidate,
        "dev_commit": _git(dev, "rev-parse", "HEAD"),
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
    return {"ticket_id": ticket_id, "candidate": candidate, "status": "integrated" if succeeded else "integrating", "event_id": integrated["event_id"], "evidence": evidence.relative_to(root).as_posix(), "unlocked_ticket_ids": unlocked}


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
