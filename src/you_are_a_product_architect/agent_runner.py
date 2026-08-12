"""The Agent Runner command surface."""

import click


def _not_implemented(operation):
    click.echo("{0} is not implemented yet.".format(operation), err=True)
    raise click.exceptions.Exit(1)


@click.group(invoke_without_command=True)
@click.option(
    "--batch-input",
    metavar="YAML_FILE",
    help="Launch a selected batch (the default operation; not implemented yet).",
)
@click.pass_context
def main(context, batch_input):
    """Default operation: launch Engineers and transport their sessions."""
    if context.invoked_subcommand is None:
        _not_implemented("Launch")


@main.command()
@click.argument("aliases", nargs=-1, required=True)
def status(aliases):
    """Inspect session aliases (not implemented yet)."""
    _not_implemented("Status")


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
