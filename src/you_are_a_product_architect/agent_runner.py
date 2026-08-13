"""The Agent Runner command surface."""

from pathlib import Path

import click
import yaml

from .runner_launch import launch_batch
from .runner_models import RunnerError
from .runner_status import status_aliases


def _not_implemented(operation):
    click.echo("{0} is not implemented yet.".format(operation), err=True)
    raise click.exceptions.Exit(1)


@click.group(invoke_without_command=True)
@click.option(
    "--batch-input",
    metavar="YAML_FILE",
    type=click.Path(path_type=Path),
    help="Launch a Main-selected task batch (the default operation).",
)
@click.pass_context
def main(context, batch_input):
    """Default operation: launch Engineers and transport their sessions."""
    if context.invoked_subcommand is None:
        if batch_input is None:
            error = RunnerError(
                "BATCH_INPUT_REQUIRED", "Launch requires --batch-input YAML_FILE."
            )
            _emit_result({"error": error.as_document()})
            click.echo(error.message, err=True)
            raise click.exceptions.Exit(1)
        try:
            response = launch_batch(batch_input, Path.cwd().resolve())
        except RunnerError as error:
            _emit_result({"error": error.as_document()})
            click.echo(error.message, err=True)
            raise click.exceptions.Exit(1)
        _emit_result(response.document)
        if not response.succeeded:
            error = response.document["tasks"][0]["error"]
            click.echo(error["message"], err=True)
            raise click.exceptions.Exit(1)


def _emit_result(document):
    click.echo(yaml.safe_dump(document, sort_keys=False), nl=False)


@main.command()
@click.argument("aliases", nargs=-1, required=True)
def status(aliases):
    """Inspect the explicitly supplied Engineer aliases."""
    try:
        response = status_aliases(aliases, Path.cwd().resolve())
    except RunnerError as error:
        _emit_result({"error": error.as_document()})
        click.echo(error.message, err=True)
        raise click.exceptions.Exit(1)
    _emit_result(response.document)
    if not response.succeeded:
        for error in response.errors:
            click.echo(error.message, err=True)
        raise click.exceptions.Exit(1)


@main.command()
@click.argument("alias")
@click.option("--instruction", required=True)
def send(alias, instruction):
    """Send a follow-up to one session (not implemented yet)."""
    _not_implemented("Send")


@main.command()
@click.argument("alias")
def interrupt(alias):
    """Interrupt one session (not implemented yet)."""
    _not_implemented("Interrupt")


@main.command()
@click.option("--run-id", required=True)
@click.option("--ticket-id", required=True)
def cleanup(run_id, ticket_id):
    """Clean up one integrated ticket (not implemented yet)."""
    _not_implemented("Cleanup")
