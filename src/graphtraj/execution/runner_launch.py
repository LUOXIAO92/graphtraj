"""Swarm launch application service for Agent Runner."""

import os
from pathlib import Path

import yaml

from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.execution.runner_batch import parse_swarm, read_swarm
from graphtraj.execution.runner_models import Batch, LaunchResponse, RunnerError
from graphtraj.execution.runner_status import caller_alias, read_alias_mapping
from graphtraj.graph.task_graph import UnknownTask, _load_task_state
from graphtraj.workspace.runner_project import (
    discover_project_root,
    discover_runner_directory,
)
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


def launch_swarm_file(swarm_input: Path, cwd: Path) -> LaunchResponse:
    """Dispatch one swarm input file from the calling Session's Task context.

    Returns the same LaunchResponse as launch_swarm, including per-task
    failures; the caller's Task is resolved before anything is retained.
    """

    caller_task_id, registered_tasks = _swarm_context(cwd)
    return launch_batch(
        read_swarm(swarm_input, cwd, caller_task_id, registered_tasks), cwd
    )


def launch_swarm(document: object, cwd: Path) -> LaunchResponse:
    """Dispatch one structured swarm input from the calling Session's context.

    Returns LaunchResponse (including per-task failures), or raises RunnerError
    before dispatch.
    """

    caller_task_id, registered_tasks = _swarm_context(cwd)
    return launch_batch(
        parse_swarm(document, caller_task_id, registered_tasks), cwd
    )


def _swarm_context(cwd: Path) -> tuple[str | None, "_RegisteredTaskNames"]:
    """Return the calling Session's Task and the registered Task names.

    A caller that runs inside a Task Session already works inside one Task,
    so its launch input does not repeat that identity. Main has no Session of
    its own and selects the Task through the DAG, so each task it launches
    names that selection.
    """
    # A Session may call this entry from its own Task Worktree, so the
    # Harness Project Root is resolved from the working directory upwards.
    root = discover_project_root(cwd)
    runner_directory = discover_runner_directory(root)
    configuration = load_project_configuration(root)
    caller = caller_alias(runner_directory)
    caller_task_id = (
        read_alias_mapping(runner_directory, caller)[0]["task_id"]
        if caller is not None else None
    )
    return caller_task_id, _RegisteredTaskNames(configuration.state)


class _RegisteredTaskNames:
    """Look up a registered Task's name by its stable identity.

    Each lookup reads only the selected Task, so an unrelated Task directory
    that is partly written or damaged cannot refuse this launch.
    """

    def __init__(self, state_directory: Path) -> None:
        self._tasks = state_directory / "tasks"

    def get(self, task_id: object, default: str | None = None) -> str | None:
        """Return the Task's name, or ``default`` when it is not registered."""
        try:
            return _load_task_state(self._tasks, task_id)[1]["task_name"]
        except UnknownTask:
            return default
        except (OSError, ValueError, yaml.YAMLError) as error:
            raise RunnerError(
                "TASK_FILE_INVALID", "The registered Task state is invalid."
            ) from error


def launch_batch(batch: Batch, cwd: Path) -> LaunchResponse:
    """Dispatch a Batch from parse_batch/read_batch using the current authority.

    A calling Session registers direct children with its owning worker; Main
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
        from graphtraj.teams.team_round import register_child_batch

        # Only this Session's own registration file may be written; a request
        # that names another Session's file is refused there.
        return register_child_batch(
            batch,
            cwd,
            Path(registration) if registration else
            runner_directory / "sessions" / caller / "child-registration.yml",
        )
    from graphtraj.teams.team_round import launch_team_batch

    try:
        return launch_team_batch(batch, cwd)
    except RuntimeAdapterError as error:
        raise RunnerError(error.code, error.message) from error
