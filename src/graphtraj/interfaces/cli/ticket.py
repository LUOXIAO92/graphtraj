"""Ticket command parsing and presentation."""

from pathlib import Path

import click
import yaml

from graphtraj.configuration.project_configuration import (
    ProjectConfigurationError,
)
from graphtraj.workspace.git_repository import GitRepositoryError
from graphtraj.execution.runner_models import RunnerError
from graphtraj.interfaces.tools import TOOLS


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
        directory = TOOLS["ticket_register"].handler(issue).document["ticket_directory"]
    except (
        OSError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    click.echo(directory)


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
        recorded = TOOLS["ticket_revise"].handler(revision).document
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
        view = TOOLS["ticket_graph"].handler({}).document
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
        recorded = TOOLS["ticket_update"].handler(change).document
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
    """Apply semantic state requests with their authoritative facts."""


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
        recorded = TOOLS["delivery_state_apply"].handler(
            {"request": request, "facts": facts}
        ).document
    except (OSError, UnicodeError, ValueError, yaml.YAMLError, RunnerError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(recorded, sort_keys=False), nl=False)


@click.command("integrate")
@click.option("--ticket-id", required=True)
@click.option(
    "--resolve-conflict", metavar="DIAGNOSIS",
    help="Dispatch an explicitly selected role for a retained conflict.",
)
@click.option(
    "--confirm-resolution", "confirmed_commit",
    help="Confirm the exact committed resolution when adopting an escalated integration.",
)
@click.option(
    "--role",
    help="Explicit configured role reference or inline YAML role definition for conflict work.",
)
@click.argument("validation_command", nargs=-1, required=True, type=click.UNPROCESSED)
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
            result = TOOLS["ticket_integrate"].handler({
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
