"""Interactive Click adapter for Harness Project initialization."""

from __future__ import annotations

from pathlib import Path

import click

from graphtraj.workspace.project_initialization import (
    ProjectSetupError,
    existing_source_repository,
    require_source_repository,
)
from graphtraj.configuration.project_diagnosis import DoctorError
from graphtraj.configuration.project_roles import ProjectRolesError
from graphtraj.configuration.project_configuration import configuration_exists
from graphtraj.interfaces.tools import TOOLS


def _select_source_repository(harness_root: Path) -> Path:
    """Select the existing repository, asking when the default is ambiguous."""
    selected = existing_source_repository(harness_root)
    if selected is not None:
        return selected
    return require_source_repository(harness_root, click.prompt(
        "Source Repository directory",
        type=click.Path(
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            resolve_path=True,
            path_type=Path,
        ),
    ))


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
        arguments = {
            "source_repository": (
                None if source_repository is None else str(source_repository)
            ),
            "apply": False,
        }
        preview = TOOLS["project_setup"].handler(arguments).document
    except (ProjectSetupError, ValueError) as error:
        raise click.ClickException(str(error)) from error
    click.echo("Setup plan:")
    for action in preview["actions"]:
        click.echo("- {0}: {1}".format(action["disposition"], action["description"]))

    if preview["proposed_base"] is not None:
        click.echo("Proposed dev base: {0}".format(preview["proposed_base"]))
        if not click.confirm(
            "Create dev from {0}?".format(preview["proposed_base"]),
            default=False,
        ):
            raise click.Abort()

    try:
        result = TOOLS["project_setup"].handler(
            {**arguments, "apply": True, "create_dev": True}
        ).document
    except (ProjectSetupError, ValueError) as error:
        raise click.ClickException(str(error)) from error

    click.echo({
        "created": "Created Integration Worktree on dev.",
        "registered": "Registered Integration Worktree on existing dev.",
        "reused": "Using registered Integration Worktree on dev.",
    }[result["integration_action"]])
    click.echo("GraphTraj project setup complete.")


@click.command()
def doctor() -> None:
    """Report configuration and roles from the active Harness Project context."""
    try:
        result = TOOLS["project_doctor"].handler({})
    except DoctorError as error:
        raise click.UsageError(str(error)) from error
    if result.document["role_diagnostics"]:
        click.echo(str(ProjectRolesError(tuple(result.document["role_diagnostics"]))))
    elif result.document["roles_checked"]:
        click.echo("roles: OK")
    if result.failed:
        raise click.exceptions.Exit(1)
