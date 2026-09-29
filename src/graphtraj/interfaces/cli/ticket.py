"""Ticket command parsing and presentation."""

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
def ticket() -> None:
    """Register Tickets and inspect their current Task Graph."""


@ticket.command("register", cls=OperationCommand, feature="ticket_register")
@click.option(
    "--ticket-file",
    required=True,
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
def register_command(ticket_file: Path) -> None:
    """Register one accepted GitHub Issue from a YAML file."""

    try:
        issue = yaml.safe_load(ticket_file.read_text(encoding="utf-8"))
        directory = invoke_tool("ticket_register", issue).document["ticket_directory"]
    except (
        OSError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    click.echo(directory)


@ticket.command("revise", cls=OperationCommand, feature="ticket_revise")
@click.option(
    "--revision-file",
    required=True,
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
def revise_command(revision_file: Path) -> None:
    """Apply one validated product-preserving Task Graph revision."""

    try:
        revision = yaml.safe_load(revision_file.read_text(encoding="utf-8"))
        recorded = invoke_tool("ticket_revise", revision).document
    except (
        OSError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(recorded, sort_keys=False), nl=False)


@ticket.command("graph", cls=OperationCommand, feature="ticket_graph")
def graph_command() -> None:
    """Generate the current Ticket DAG and readiness view as YAML."""

    try:
        view = invoke_tool("ticket_graph", {}).document
    except (
        OSError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(view, sort_keys=False), nl=False)


@ticket.command("update", cls=OperationCommand, feature="ticket_update")
@click.option(
    "--state-file",
    required=True,
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
def update_command(state_file: Path) -> None:
    """Apply one evidence-backed current Ticket state transition."""

    try:
        change = yaml.safe_load(state_file.read_text(encoding="utf-8"))
        recorded = invoke_tool("ticket_update", change).document
    except (
        OSError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(recorded, sort_keys=False), nl=False)


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


@click.command("integrate", cls=OperationCommand, feature="ticket_integrate")
@click.option("--ticket-id")
@click.option("--resolve-conflict", metavar="DIAGNOSIS")
@click.option("--confirm-resolution", "confirmed_commit")
@click.option("--role")
@click.argument("validation_command", nargs=-1, type=click.UNPROCESSED)
def integrate_command(
    ticket_id: str,
    resolve_conflict: str | None,
    role: str | None,
    confirmed_commit: str | None,
    validation_command: tuple[str, ...],
) -> None:
    """Merge or recover an accepted Ticket under its actual task authority.

    After escalation, COMMAND (after --) must match the retained validation.
    """

    from graphtraj.interfaces.cli.agent_runner import _budget_notices, _emit_result

    with _budget_notices():
        try:
            result = invoke_tool("ticket_integrate", {
                "ticket_id":          ticket_id,
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


ticket.add_command(integrate_command)
