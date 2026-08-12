"""Interactive Click adapter for Harness Project initialization."""

from __future__ import annotations

import shutil
from pathlib import Path

import click

from .project_initialization import ProjectSetupError, plan_project_setup


def _primary_worktree_prompt() -> Path:
    return click.prompt(
        "Primary Worktree directory",
        type=click.Path(
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            resolve_path=True,
            path_type=Path,
        ),
    ).resolve()


@click.command()
def setup() -> None:
    """Initialize a Harness Project from an existing Primary Worktree."""

    runtime = shutil.which("codex")
    if runtime is None:
        raise click.ClickException(
            "The Codex Runtime executable was not found on PATH."
        )

    try:
        plan = plan_project_setup(
            Path.cwd().resolve(),
            _primary_worktree_prompt(),
            Path(runtime).resolve(),
        )
    except ProjectSetupError as error:
        raise click.ClickException(str(error)) from error

    if plan.missing_skills:
        raise click.ClickException(
            "Missing required core Skills: {0}".format(
                ", ".join(plan.missing_skills)
            )
        )
    click.echo("Core Skills: OK")

    if plan.proposed_base is not None:
        click.echo("Proposed dev base: {0}".format(plan.proposed_base))
        if not click.confirm(
            "Create dev from {0}?".format(plan.proposed_base),
            default=False,
        ):
            raise click.Abort()

    try:
        click.echo(plan.apply())
    except ProjectSetupError as error:
        raise click.ClickException(str(error)) from error

    click.echo("Harness Project setup complete.")
    click.echo("Review and commit the Runtime resources on dev.")
    click.echo(
        "Invoke $setup-matt-pocock-skills separately if repository metadata "
        "still needs configuration."
    )
