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


def _confirm_missing_skill_installation(missing_skills: tuple[str, ...]) -> bool:
    click.echo(
        "Missing required core Skills: {0}".format(
            ", ".join(missing_skills)
        )
    )
    return click.confirm(
        "Install the missing Skills into this Harness Project?",
        default=True,
    )


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

    install_missing_skills = False
    if plan.missing_skills:
        if not _confirm_missing_skill_installation(plan.missing_skills):
            raise click.ClickException(
                "Setup stopped before any setup mutation. Install the missing "
                "Skills independently in the Runtime user scope and rerun setup."
            )
        install_missing_skills = True
    else:
        click.echo("Core Skills: OK")

    try:
        preview = plan.preflight(
            install_missing_skills=install_missing_skills,
        )
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
        result = plan.apply(install_missing_skills=install_missing_skills)
    except ProjectSetupError as error:
        raise click.ClickException(str(error)) from error

    if install_missing_skills:
        click.echo("Core Skills: OK")
    click.echo(result)
    click.echo("Harness Project setup complete.")
    click.echo("Harness Runtime Store installed at {0}.".format(Path.cwd() / ".codex"))
    click.echo(
        "Invoke $setup-matt-pocock-skills separately if repository metadata "
        "still needs configuration."
    )
