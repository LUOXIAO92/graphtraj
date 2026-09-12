"""Batch launch application service for Agent Runner."""

from pathlib import Path

from graphtraj.execution.runner_batch import read_batch
from graphtraj.execution.runner_models import LaunchResponse, RunnerError
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


def launch_batch(batch_file: Path, cwd: Path) -> LaunchResponse:
    """Launch the exact supplied formal Team work."""
    batch = read_batch(batch_file, cwd)
    if any(task.role == "merge-resolver" for task in batch.tasks):
        from graphtraj.teams.coding.merge_resolution import launch_merge_resolver

        return launch_merge_resolver(batch, cwd)
    from graphtraj.teams.coding.team_round import launch_team_batch

    try:
        return launch_team_batch(batch, cwd)
    except RuntimeAdapterError as error:
        raise RunnerError(error.code, error.message) from error
