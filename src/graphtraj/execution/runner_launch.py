"""Swarm launch application service for Agent Runner."""

import os
from pathlib import Path

import yaml

from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.configuration.project_roles import logical_role
from graphtraj.execution.runner_batch import parse_swarm, read_swarm
from graphtraj.execution.runner_models import Batch, LaunchResponse, RunnerError
from graphtraj.execution.runner_status import caller_alias, read_alias_mapping
from graphtraj.graph.ticket_graph import read_graph
from graphtraj.workspace.runner_project import (
    discover_project_root,
    discover_runner_directory,
)
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


def launch_swarm_file(swarm_input: Path, cwd: Path) -> LaunchResponse:
    """Dispatch one swarm input file from the calling Session's Ticket context.

    Returns the same LaunchResponse as launch_swarm, including per-task
    failures; the caller's Ticket is resolved before anything is retained.
    """

    caller_ticket_id, registered_tickets = _swarm_context(cwd)
    return launch_batch(
        read_swarm(swarm_input, cwd, caller_ticket_id, registered_tickets), cwd
    )


def launch_swarm(document: object, cwd: Path) -> LaunchResponse:
    """Dispatch one structured swarm input from the calling Session's context.

    Returns LaunchResponse (including per-task failures), or raises RunnerError
    before dispatch.
    """

    caller_ticket_id, registered_tickets = _swarm_context(cwd)
    return launch_batch(
        parse_swarm(document, caller_ticket_id, registered_tickets), cwd
    )


def _swarm_context(cwd: Path) -> tuple[str | None, dict[str, str]]:
    """Return the calling Session's Ticket and the registered Ticket names.

    A caller that runs inside a Ticket Session already works inside one Ticket,
    so its launch input does not repeat that identity. Main has no Session of
    its own and selects the Ticket through the DAG, so each task it launches
    names that selection.
    """
    # A Session may call this entry from its own Ticket Worktree, so the
    # Harness Project Root is resolved from the working directory upwards.
    root = discover_project_root(cwd)
    runner_directory = discover_runner_directory(root)
    configuration = load_project_configuration(root)
    caller = caller_alias(runner_directory)
    caller_ticket_id = (
        read_alias_mapping(runner_directory, caller)[0]["ticket_id"]
        if caller is not None else None
    )
    return caller_ticket_id, _registered_ticket_names(configuration.state)


def _registered_ticket_names(state_directory: Path) -> dict[str, str]:
    """Return each registered Ticket's name, keyed by its stable identity."""

    try:
        graph = read_graph(state_directory)
    except (OSError, ValueError, yaml.YAMLError) as error:
        raise RunnerError(
            "TICKET_FILE_INVALID", "The registered Ticket state is invalid."
        ) from error
    return {
        ticket["ticket_id"]: ticket["ticket_name"]
        for ticket in graph["tickets"]
    }


def launch_batch(batch: Batch, cwd: Path) -> LaunchResponse:
    """Dispatch a Batch from parse_batch/read_batch using the current authority.

    A Team Leader registers direct children with its owning worker; Main
    dispatches the selected work. The dispatching Session is identified by the
    process tree the command runs in, so a supplied registration path cannot
    promote a caller: ``register_child_batch`` still requires it to be that
    Session's own. Returns LaunchResponse (including per-task failures), or
    raises RunnerError before dispatch. No terminal I/O is needed.
    """
    runner_directory = discover_runner_directory(discover_project_root(cwd))
    registration = os.environ.get("GRAPHTRAJ_PARENT_REGISTRATION")
    caller = caller_alias(runner_directory)
    if caller is not None:
        from graphtraj.teams.coding.team_round import register_child_batch

        # Only this Session's own registration file may be written; a request
        # that names another Session's file is refused there.
        return register_child_batch(
            batch,
            cwd,
            Path(registration) if registration else
            runner_directory / "sessions" / caller / "child-registration.yml",
        )
    if any(logical_role(task.role) == "merge-resolver" for task in batch.tasks):
        from graphtraj.teams.coding.merge_resolution import launch_merge_resolver

        return launch_merge_resolver(batch, cwd)
    from graphtraj.teams.coding.team_round import launch_team_batch

    try:
        return launch_team_batch(batch, cwd)
    except RuntimeAdapterError as error:
        raise RunnerError(error.code, error.message) from error
