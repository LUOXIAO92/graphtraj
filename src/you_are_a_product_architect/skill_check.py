"""Core Skill-check command placeholder."""

import click


@click.command()
def doctor():
    """Check required core Skills (not implemented yet)."""
    click.echo("Core Skill checking is not implemented yet.", err=True)
    raise click.exceptions.Exit(1)
