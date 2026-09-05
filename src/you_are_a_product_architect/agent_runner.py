"""The Agent Runner command surface."""

import os
from pathlib import Path

import click
import yaml

from .runner_cleanup import cleanup_ticket
from .runner_control import interrupt_session, send_instruction, send_legacy_instruction
from .runner_launch import launch_batch
from .runner_models import RunnerError
from .runner_status import status_aliases


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
            registration = os.environ.get("GRAPHTRAJ_PARENT_REGISTRATION")
            if registration:
                from .team_round import register_child_batch

                response = register_child_batch(
                    batch_input, Path.cwd().resolve(), Path(registration)
                )
            else:
                response = launch_batch(batch_input, Path.cwd().resolve())
        except RunnerError as error:
            _emit_result({"error": error.as_document()})
            click.echo(error.message, err=True)
            raise click.exceptions.Exit(1)
        _emit_result(response.document)
        if not response.succeeded:
            for task in response.document["tasks"]:
                error = task.get("error")
                if error is not None:
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
@click.option(
    "--caused-by-event-id",
    multiple=True,
)
@click.option(
    "--caused-by-worldline-seq",
    type=click.IntRange(min=1),
    multiple=True,
    hidden=True,
)
def send(alias, instruction, caused_by_event_id, caused_by_worldline_seq):
    """Send a follow-up to one recoverable Engineer session."""
    try:
        if caused_by_event_id and not caused_by_worldline_seq:
            response = send_instruction(
                alias,
                instruction,
                Path.cwd().resolve(),
                caused_by_event_id,
            )
        elif caused_by_worldline_seq and not caused_by_event_id:
            response = send_legacy_instruction(
                alias,
                instruction,
                Path.cwd().resolve(),
                caused_by_worldline_seq,
            )
        else:
            raise RunnerError(
                "invalid-input",
                "Send requires one or more causal Project Worldline event IDs.",
            )
    except RunnerError as error:
        _emit_result({"alias": alias, "error": error.as_document()})
        click.echo(error.message, err=True)
        raise click.exceptions.Exit(1)
    _emit_result(response)


@main.command()
@click.argument("alias")
def interrupt(alias):
    """Interrupt one active Engineer turn while preserving its alias."""
    try:
        response = interrupt_session(alias, Path.cwd().resolve())
    except RunnerError as error:
        _emit_result({"alias": alias, "error": error.as_document()})
        click.echo(error.message, err=True)
        raise click.exceptions.Exit(1)
    _emit_result(response)


@main.command()
@click.option("--ticket-id")
def cleanup(ticket_id):
    """Clean up one safely integrated ticket by stable identity."""
    if ticket_id is None:
        error = RunnerError(
            "invalid-input",
            "Cleanup requires --ticket-id.",
        )
        _emit_result({"error": error.as_document()})
        click.echo(error.message, err=True)
        raise click.exceptions.Exit(1)
    try:
        response = cleanup_ticket(Path.cwd().resolve(), ticket_id)
    except RunnerError as error:
        _emit_result({"error": error.as_document()})
        click.echo(error.message, err=True)
        raise click.exceptions.Exit(1)
    _emit_result(response.document)
    if not response.succeeded:
        error = response.document["error"]
        click.echo(error["message"], err=True)
        raise click.exceptions.Exit(1)
