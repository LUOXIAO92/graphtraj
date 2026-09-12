"""Batch launch application service for Agent Runner."""

import os
from pathlib import Path

from graphtraj.execution.runner_models import Batch, LaunchResponse, RunnerError
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


def launch_batch(batch: Batch, cwd: Path) -> LaunchResponse:
    """Dispatch a Batch from parse_batch/read_batch using the current authority.

    A Team Leader registers direct children with its owning worker; Main
    dispatches the selected work. Returns LaunchResponse (including per-task
    failures), or raises RunnerError before dispatch. No terminal I/O is needed.
    """
    registration = os.environ.get("GRAPHTRAJ_PARENT_REGISTRATION")
    if registration:
        from graphtraj.teams.coding.team_round import register_child_batch

        return register_child_batch(batch, cwd, Path(registration))
    if any(task.role == "merge-resolver" for task in batch.tasks):
        from graphtraj.teams.coding.merge_resolution import launch_merge_resolver

        return launch_merge_resolver(batch, cwd)
    from graphtraj.teams.coding.team_round import launch_team_batch

    try:
        return launch_team_batch(batch, cwd)
    except RuntimeAdapterError as error:
        raise RunnerError(error.code, error.message) from error
