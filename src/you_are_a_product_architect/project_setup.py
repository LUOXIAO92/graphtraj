"""Interactive Click adapter for Harness Project initialization."""

from __future__ import annotations

from pathlib import Path

import click

from .project_initialization import ProjectSetupError, plan_project_setup


@click.command()
def setup() -> None:
    """Initialize GraphTraj in the current existing Git repository."""

    try:
        plan = plan_project_setup(Path.cwd().resolve())
    except ProjectSetupError as error:
        raise click.ClickException(str(error)) from error

    try:
        preview = plan.preflight()
    except ProjectSetupError as error:
        raise click.ClickException(str(error)) from error
    click.echo(preview.render())

    if plan.proposed_base is not None:
        click.echo("Proposed dev base: {0}".format(plan.proposed_base))
        if not click.confirm(
            "Create dev from {0}?".format(plan.proposed_base),
            default=False,
        ):
            raise click.Abort()

    try:
        result = plan.apply()
    except ProjectSetupError as error:
        raise click.ClickException(str(error)) from error

    click.echo(result)
    click.echo("GraphTraj project setup complete.")
