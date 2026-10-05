"""The product command surface."""

from pathlib import Path

import click
import yaml

from graphtraj.execution.runner_models import RunnerError
from graphtraj.interfaces.cli.projection import (
    OperationCommand,
    OperationGroup,
    invoke_tool,
)

from graphtraj.interfaces.cli.worldline import worldline
from graphtraj.interfaces.cli.project_setup import setup, doctor
from graphtraj.interfaces.cli.ticket import delivery_state, ticket
from graphtraj.interfaces.cli.finalize import bind_command


@click.group(cls=OperationGroup)
def main() -> None:
    """Set up GraphTraj and manage Ticket, Team, and Project Worldline evidence.

    Configuration lives in .graphtraj; historical Delivery Runs have no
    compatibility reader or migration."""


@click.group("roles", cls=OperationGroup)
def roles() -> None:
    """Read or authorized-change child role presets and dispatch edges."""


@roles.command("organize", cls=OperationCommand, feature="role_organization")
@click.option(
    "--change-file",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
def organize_command(change_file: Path | None) -> None:
    """Preview the declared roles, or write one change the reviewer approves."""

    arguments: dict = {}
    try:
        if change_file is not None:
            arguments["change"] = yaml.safe_load(change_file.read_text(encoding="utf-8"))
        result = invoke_tool("role_organization", arguments).document
    except (OSError, UnicodeError, ValueError, yaml.YAMLError, RunnerError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(result, sort_keys=False), nl=False)


main.add_command(setup)
main.add_command(doctor)
main.add_command(worldline)
main.add_command(ticket)
main.add_command(delivery_state)
main.add_command(roles)

main.add_command(bind_command)
