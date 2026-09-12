"""Ticket command parsing and presentation."""

from pathlib import Path

import click
import yaml

from graphtraj.configuration.project_configuration import (
    ProjectConfigurationError,
    load_project_configuration,
)
from graphtraj.workspace.git_repository import GitRepositoryError
from graphtraj.teams.coding.ticket_integration import integrate_ticket
from graphtraj.graph.delivery_state import apply_delivery_state_request
from graphtraj.graph.ticket_graph import (
    register_ticket,
    read_graph,
    revise_tickets,
    update_ticket_state,
)


@click.group()
def ticket() -> None:
    """Register Tickets and inspect their current Task Graph."""


@ticket.command("register")
@click.option(
    "--ticket-file",
    required=True,
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
def register_command(ticket_file: Path) -> None:
    """Register one accepted GitHub Issue from a YAML file."""

    try:
        issue = yaml.safe_load(ticket_file.read_text(encoding="utf-8"))
        configuration = load_project_configuration(Path.cwd())
        directory = register_ticket(configuration.state, configuration.harness_root, issue)
    except (
        OSError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    click.echo(str(directory))


@ticket.command("revise")
@click.option(
    "--revision-file",
    required=True,
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
def revise_command(revision_file: Path) -> None:
    """Apply one validated product-preserving Task Graph revision."""

    try:
        revision = yaml.safe_load(revision_file.read_text(encoding="utf-8"))
        configuration = load_project_configuration(Path.cwd())
        recorded = revise_tickets(
            configuration.state, configuration.harness_root, revision
        )
    except (
        OSError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(recorded, sort_keys=False), nl=False)


@ticket.command("graph")
def graph_command() -> None:
    """Generate the current Ticket DAG and readiness view as YAML."""

    try:
        configuration = load_project_configuration(Path.cwd())
        view = read_graph(configuration.state)
    except (
        OSError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(view, sort_keys=False), nl=False)


@ticket.command("update")
@click.option(
    "--state-file",
    required=True,
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
def update_command(state_file: Path) -> None:
    """Apply one evidence-backed current Ticket state transition."""

    try:
        change = yaml.safe_load(state_file.read_text(encoding="utf-8"))
        configuration = load_project_configuration(Path.cwd())
        recorded = update_ticket_state(
            configuration.state, configuration.harness_root, change
        )
    except (
        OSError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(recorded, sort_keys=False), nl=False)


@click.group("delivery-state")
def delivery_state() -> None:
    """Apply strict requests produced by the Delivery State Agent."""


@delivery_state.command("apply")
@click.option(
    "--request-file",
    required=True,
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
@click.option(
    "--facts-file",
    required=True,
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
def apply_command(request_file: Path, facts_file: Path) -> None:
    """Validate and atomically apply one semantic state request."""

    try:
        request = yaml.safe_load(request_file.read_text(encoding="utf-8"))
        facts = yaml.safe_load(facts_file.read_text(encoding="utf-8"))
        configuration = load_project_configuration(Path.cwd())
        recorded = apply_delivery_state_request(
            configuration.state, configuration.harness_root, request, facts
        )
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(recorded, sort_keys=False), nl=False)


@click.command("integrate")
@click.option("--ticket-id", required=True)
@click.option(
    "--resolve-conflict", metavar="DIAGNOSIS",
    help="Main: delegate a retained textual or semantic conflict, then validate it.",
)
@click.argument("validation_command", nargs=-1, required=True, type=click.UNPROCESSED)
def integrate_command(
    ticket_id: str,
    resolve_conflict: str | None,
    validation_command: tuple[str, ...],
) -> None:
    """Main: merge the accepted Ticket, then run COMMAND in dev (after --)."""

    try:
        configuration = load_project_configuration(Path.cwd())
        result = integrate_ticket(
            configuration, ticket_id, validation_command, resolve_conflict
        )
    except (OSError, ValueError, GitRepositoryError, ProjectConfigurationError, yaml.YAMLError) as error:
        click.echo(yaml.safe_dump({"error": str(error)}, sort_keys=False), nl=False)
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(result, sort_keys=False), nl=False)
    if result["status"] != "integrated":
        raise click.ClickException("Integration failed; see retained evidence")


ticket.add_command(integrate_command)
