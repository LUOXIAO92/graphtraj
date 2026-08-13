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


def _missing_skill_action(missing_skills: tuple[str, ...]) -> str:
    click.echo(
        "Missing required core Skills: {0}".format(
            ", ".join(missing_skills)
        )
    )
    return click.prompt(
        "Choose Skill installation",
        type=click.Choice(("project-local", "independent")),
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
        action = _missing_skill_action(plan.missing_skills)
        if action == "independent":
            raise click.ClickException(
                "Setup stopped before any setup mutation. Install the missing "
                "Skills independently in the Runtime user scope and rerun setup."
            )
        install_missing_skills = True
    else:
        click.echo("Core Skills: OK")

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
    click.echo("Review and commit the Runtime resources on dev.")
    click.echo(
        "Invoke $setup-matt-pocock-skills separately if repository metadata "
        "still needs configuration."
    )
