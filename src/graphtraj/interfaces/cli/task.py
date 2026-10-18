"""Task command parsing and presentation."""

from pathlib import Path

import click
import yaml

from graphtraj.configuration.project_configuration import (
    ProjectConfigurationError,
)
from graphtraj.workspace.git_repository import GitRepositoryError
from graphtraj.execution.runner_models import RunnerError
from graphtraj.interfaces.cli.projection import OperationCommand, OperationGroup, invoke_tool


@click.group(cls=OperationGroup)
def task() -> None:
    """Register Tasks and inspect their current Task Graph."""


@task.command("register", cls=OperationCommand, feature="task_register")
@click.option(
    "--task-file",
    required=True,
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
def register_command(task_file: Path) -> None:
    """Register one accepted Task definition from a YAML file."""

    try:
        issue = yaml.safe_load(task_file.read_text(encoding="utf-8"))
        directory = invoke_tool("task_register", issue).document["task_directory"]
    except (
        OSError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    click.echo(directory)


@task.command("revise", cls=OperationCommand, feature="task_revise")
@click.option(
    "--revision-file",
    required=True,
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
@click.option("--dry-run", is_flag=True)
def revise_command(revision_file: Path, dry_run: bool) -> None:
    """Apply one validated product-preserving Task Graph revision."""

    try:
        revision = yaml.safe_load(revision_file.read_text(encoding="utf-8"))
        if dry_run and isinstance(revision, dict):
            revision["dry_run"] = True
        recorded = invoke_tool("task_revise", revision).document
    except (
        OSError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(recorded, sort_keys=False), nl=False)


@task.command("graph", cls=OperationCommand, feature="task_graph")
@click.option("--schema", is_flag=True)
@click.option("--view", type=click.Choice(["current", "full"]), default="current")
@click.option("--task-id", default=None)
@click.option("--details", multiple=True)
def graph_command(schema: bool, view: str, task_id: str | None, details: tuple[str, ...]) -> None:
    """Generate the current Task DAG and readiness view as YAML."""

    arguments = {"schema": schema, "view": view, "details": list(details)}
    if task_id is not None:
        arguments["task_id"] = task_id
    try:
        view = invoke_tool("task_graph", arguments).document
    except (
        OSError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(view, sort_keys=False), nl=False)


@task.command("members", cls=OperationCommand, feature="task_members")
@click.option("--summary-task-id", default=None)
def members_command(summary_task_id: str | None) -> None:
    """List member Agents of current summary Tasks or of one chosen summary."""

    arguments = {} if summary_task_id is None else {"summary_task_id": summary_task_id}
    try:
        members = invoke_tool("task_members", arguments).document
    except (OSError, UnicodeError, ValueError, yaml.YAMLError,
            ProjectConfigurationError, RunnerError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(members, sort_keys=False), nl=False)


@task.command("complete", cls=OperationCommand, feature="task_complete")
@click.option("--completion-file", required=True,
              type=click.Path(path_type=Path, exists=True, dir_okay=False))
def complete_command(completion_file: Path) -> None:
    """Accept a task's own non-file result after its necessary children finish."""
    try:
        request = yaml.safe_load(completion_file.read_text(encoding="utf-8"))
        result = invoke_tool("task_complete", request).document
    except (OSError, UnicodeError, ValueError, yaml.YAMLError, ProjectConfigurationError, RunnerError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(result, sort_keys=False), nl=False)


@task.command("update", cls=OperationCommand, feature="task_update")
@click.option(
    "--state-file",
    required=True,
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
def update_command(state_file: Path) -> None:
    """Apply one evidence-backed current Task state transition."""

    try:
        change = yaml.safe_load(state_file.read_text(encoding="utf-8"))
        recorded = invoke_tool("task_update", change).document
    except (
        OSError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(recorded, sort_keys=False), nl=False)


@task.command("backup", cls=OperationCommand, feature="task_backup")
@click.option("--task-id", required=True)
@click.option("--repository", required=True)
@click.option("--host")
@click.option("--confirm-remote")
def backup_command(
    task_id: str, repository: str, host: str, confirm_remote: str | None,
) -> None:
    """Back up one local Task to its mapped GitHub Issue."""

    try:
        result = invoke_tool("task_backup", {
            "task_id": task_id, "repository": repository,
            "host": host, "confirm_remote": confirm_remote,
        })
    except (OSError, ValueError, ProjectConfigurationError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(result.document, sort_keys=False), nl=False)
    if result.failed:
        raise click.ClickException("Backup was not published; see the reported result")


@click.group("delivery-state", cls=OperationGroup)
def delivery_state() -> None:
    """Apply semantic state requests with their authoritative facts."""


@delivery_state.command("apply", cls=OperationCommand, feature="delivery_state_apply")
@click.option(
    "--request-file",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
@click.option(
    "--facts-file",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
def apply_command(request_file: Path, facts_file: Path) -> None:
    """Validate and atomically apply one semantic state request."""

    try:
        request = yaml.safe_load(request_file.read_text(encoding="utf-8"))
        facts = yaml.safe_load(facts_file.read_text(encoding="utf-8"))
        recorded = invoke_tool("delivery_state_apply",
            {"request": request, "facts": facts}
        ).document
    except (OSError, UnicodeError, ValueError, yaml.YAMLError, RunnerError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(recorded, sort_keys=False), nl=False)


@click.command("integrate", cls=OperationCommand, feature="task_integrate")
@click.option("--task-id")
@click.option("--resolve-conflict", metavar="DIAGNOSIS")
@click.option("--confirm-resolution", "confirmed_commit")
@click.option("--role")
@click.argument("validation_command", nargs=-1, type=click.UNPROCESSED)
def integrate_command(
    task_id: str,
    resolve_conflict: str | None,
    role: str | None,
    confirmed_commit: str | None,
    validation_command: tuple[str, ...],
) -> None:
    """Merge or recover an accepted Task under its actual task authority.

    After escalation, COMMAND (after --) must match the retained validation.
    """

    from graphtraj.interfaces.cli.agent_runner import _budget_notices, _emit_result

    with _budget_notices():
        try:
            result = invoke_tool("task_integrate", {
                "task_id":          task_id,
                "validation_command": list(validation_command),
                "resolve_conflict":   resolve_conflict,
                "confirmed_commit":   confirmed_commit,
                "role":               yaml.safe_load(role) if role is not None else None,
            })
        except (OSError, ValueError, GitRepositoryError, ProjectConfigurationError, yaml.YAMLError, RunnerError) as error:
            _emit_result({"error": str(error)})
            raise click.ClickException(str(error)) from error
        _emit_result(result.document)
    if result.failed:
        raise click.ClickException("Integration failed; see retained evidence")


task.add_command(integrate_command)
