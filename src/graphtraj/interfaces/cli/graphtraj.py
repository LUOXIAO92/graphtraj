"""The product command surface."""

from pathlib import Path

import click
import yaml

from graphtraj.execution.runner_models import RunnerError
from graphtraj.interfaces.cli.projection import (
    OperationCommand,
    OperationGroup,
    invoke_tool,
)

from graphtraj.interfaces.cli.worldline import worldline
from graphtraj.interfaces.cli.project_setup import setup, doctor
from graphtraj.interfaces.cli.task import delivery_state, task
from graphtraj.interfaces.cli.finalize import bind_command


@click.group(cls=OperationGroup)
def main() -> None:
    """Set up GraphTraj and manage Task, Team, and Project Worldline evidence.

    Configuration lives in .graphtraj; historical Delivery Runs have no
    compatibility reader or migration."""


@click.group("roles", cls=OperationGroup)
def roles() -> None:
    """Read or authorized-change child role presets and dispatch edges."""


@roles.command("organize", cls=OperationCommand, feature="role_organization")
@click.option(
    "--change-file",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
def organize_command(change_file: Path | None) -> None:
    """Preview the declared roles, or write one change the reviewer approves."""

    arguments: dict = {}
    try:
        if change_file is not None:
            arguments["change"] = yaml.safe_load(change_file.read_text(encoding="utf-8"))
        result = invoke_tool("role_organization", arguments).document
    except (OSError, UnicodeError, ValueError, yaml.YAMLError, RunnerError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(result, sort_keys=False), nl=False)


main.add_command(setup)
main.add_command(doctor)
main.add_command(worldline)
main.add_command(task)
main.add_command(delivery_state)
main.add_command(roles)

main.add_command(bind_command)


@main.command("migrate-tickets")
@click.option("--preview", is_flag=True, help="List project sources and gaps without changing state.")
@click.option("--restore", type=click.Path(path_type=Path), help="Restore a complete local pre-cutover backup.")
@click.option("--snapshot", type=click.Path(path_type=Path), help="Copy project migration data and associated source bytes to a new isolated directory.")
def migrate_tickets_command(preview: bool, restore: Path | None, snapshot: Path | None) -> None:
    """Convert this project's retained Ticket state to the Task format once.

    Stop all Agents first. The previous state and Runner records are copied
    to .graphtraj/backups and restored automatically if conversion fails."""
    from graphtraj.workspace.task_migration import migrate_project, restore_project

    try:
        if sum((preview, restore is not None, snapshot is not None)) > 1:
            raise ValueError("Choose only one of preview, snapshot or restore.")
        if snapshot is not None:
            from graphtraj.workspace.migration_snapshot import snapshot_project

            result = snapshot_project(Path.cwd(), snapshot)
        else:
            result = (restore_project(Path.cwd(), restore) if restore
                      else migrate_project(Path.cwd(), preview=preview))
    except (OSError, ValueError, yaml.YAMLError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(result, sort_keys=False), nl=False)


@main.command("connections", cls=OperationCommand, feature="runtime_connections")
@click.option("--action", type=click.Choice(["read", "preview", "save", "discover"]), default="read")
@click.option("--catalog-file", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option("--expected-revision")
@click.option("--runtime")
def connections_command(
    action: str,
    catalog_file: Path | None,
    expected_revision: str | None,
    runtime: str | None,
) -> None:
    """Manage the user's Runtime connections independently of the desktop."""
    arguments = {"action": action}
    if expected_revision is not None:
        arguments["expected_revision"] = expected_revision
    if runtime is not None:
        arguments["runtime"] = runtime
    try:
        if catalog_file is not None:
            arguments["catalog"] = yaml.safe_load(catalog_file.read_text(encoding="utf-8"))
        result = invoke_tool("runtime_connections", arguments).document
    except (OSError, ValueError, yaml.YAMLError, RunnerError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(result, sort_keys=False), nl=False)


@main.command("migration-prefix")
@click.option("--session", required=True, help="Exact associated Main native Session ID.")
@click.option("--expect-prefix", type=(str, int, int), required=True, metavar="THREAD ORDINAL BYTES",
              help="Refuse any different source ID or exclusive ordinal/byte boundary before querying it.")
@click.option("--capture", type=click.Path(path_type=Path), help="Capture only its declared inherited prefix in a new directory.")
@click.option("--diagnose", is_flag=True, help="Return only requested/actual reference metadata; do not read its file.")
@click.option("--chain", is_flag=True, help="Capture only the verified decreasing chain declared by source headers.")
def migration_prefix_command(
    session: str,
    expect_prefix: tuple[str, int, int],
    capture: Path | None,
    diagnose: bool,
    chain: bool,
) -> None:
    """Read declared inheritance metadata through Main's existing native host."""
    from graphtraj.workspace.migration_prefix import inspect_prefix

    try:
        if chain:
            if capture is None or diagnose:
                raise ValueError('Chain capture requires --capture and cannot be combined with --diagnose.')
            from graphtraj.workspace.migration_prefix import capture_prefix_chain

            result = capture_prefix_chain(Path.cwd(), session, expect_prefix, capture)
        else:
            result = inspect_prefix(Path.cwd(), session, expect_prefix, capture=capture, diagnose=diagnose)
    except (OSError, ValueError, yaml.YAMLError, RunnerError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(result, sort_keys=False), nl=False)
    if chain and not result['complete']:
        raise click.exceptions.Exit(1)


@main.command("migration-mappings")
@click.option("--file", "source", type=click.Path(path_type=Path, exists=True, dir_okay=False), required=True)
@click.option("--evidence-ref", required=True)
@click.option("--preview", is_flag=True)
def migration_mappings_command(source: Path, evidence_ref: str, preview: bool) -> None:
    """Adopt explicitly confirmed remote identities after Task-format migration."""
    from graphtraj.workspace.migration_mappings import adopt_mappings

    try:
        result = adopt_mappings(Path.cwd(), source, evidence_ref, preview=preview)
    except (OSError, ValueError, yaml.YAMLError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(result, sort_keys=False), nl=False)
