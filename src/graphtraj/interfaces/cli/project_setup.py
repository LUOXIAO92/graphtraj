"""Interactive Click adapter for Harness Project initialization."""

from __future__ import annotations

import os
from pathlib import Path

import click

from graphtraj.workspace.project_initialization import ProjectSetupError, plan_project_setup
from graphtraj.configuration.skill_check import DoctorError, diagnose_project
from graphtraj.configuration.project_roles import ProjectRolesError
from graphtraj.configuration.project_configuration import configuration_exists


def _has_git_entry(directory: Path) -> bool:
    """Identify a local Git entry for the interactive repository choice."""
    return os.path.lexists(str(directory / ".git"))


def _select_source_repository(harness_root: Path) -> Path:
    """Select the existing repository, asking when the default is ambiguous."""
    if _has_git_entry(harness_root):
        return harness_root
    try:
        candidates = tuple(
            child.resolve()
            for child in harness_root.iterdir()
            if child.is_dir() and _has_git_entry(child)
        )
    except OSError as error:
        raise ProjectSetupError(
            "Setup could not inspect the Harness Project Root."
        ) from error
    if len(candidates) == 1:
        return candidates[0]
    selected = click.prompt(
        "Source Repository directory",
        type=click.Path(
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            resolve_path=True,
            path_type=Path,
        ),
    ).resolve()
    if selected.parent != harness_root or not _has_git_entry(selected):
        raise ProjectSetupError(
            "The selected Source Repository must be an existing direct Git child "
            "of the Harness Project Root."
        )
    return selected


def _confirm_missing_skill_installation(missing_skills: tuple[str, ...]) -> bool:
    """Ask the operator whether to install the listed missing Skills."""
    click.echo(
        "Missing required core Skills: {0}".format(", ".join(missing_skills))
    )
    return click.confirm(
        "Install the missing Skills into this Harness Project?",
        default=True,
    )


@click.command()
def setup() -> None:
    """Initialize GraphTraj in the current existing Git repository."""

    try:
        harness_root = Path.cwd().resolve()
        source_repository = (
            None
            if configuration_exists(harness_root)
            else _select_source_repository(harness_root)
        )
        plan = plan_project_setup(harness_root, source_repository)
    except ProjectSetupError as error:
        raise click.ClickException(str(error)) from error

    install_missing_skills = False
    if plan.missing_skills:
        if not _confirm_missing_skill_installation(plan.missing_skills):
            raise click.ClickException(
                "Setup stopped before any setup mutation. Install the missing "
                "Skills independently and rerun setup."
            )
        install_missing_skills = True
    else:
        click.echo("Core Skills: OK")

    try:
        preview = plan.preflight(install_missing_skills=install_missing_skills)
    except ProjectSetupError as error:
        raise click.ClickException(str(error)) from error
    click.echo("Setup plan:")
    for action in preview.actions:
        click.echo("- {0}: {1}".format(action.disposition, action.description))

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
    click.echo({
        "created": "Created Integration Worktree on dev.",
        "registered": "Registered Integration Worktree on existing dev.",
        "reused": "Using registered Integration Worktree on dev.",
    }[result.integration_action])
    click.echo("GraphTraj project setup complete.")


@click.command()
def doctor() -> None:
    """Report required core Skills from the active Harness Project context."""
    try:
        result = diagnose_project(Path.cwd(), Path.home() / ".agents" / "skills")
    except DoctorError as error:
        raise click.UsageError(str(error)) from error
    for status in result.skills:
        click.echo("{0}: {1}".format(status.name, "OK" if status.discovered else "MISSING"))
    if result.role_diagnostics:
        click.echo(str(ProjectRolesError(result.role_diagnostics)))
    elif result.roles_checked:
        click.echo("roles: OK")
    if not result.succeeded:
        raise click.exceptions.Exit(1)
