"""Batch launch application service for Agent Runner."""

import os
from pathlib import Path

from graphtraj.configuration.project_roles import logical_role
from graphtraj.execution.runner_models import Batch, LaunchResponse, RunnerError
from graphtraj.execution.runner_status import caller_alias
from graphtraj.workspace.runner_project import (
    discover_project_root,
    discover_runner_directory,
)
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


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
