"""Project Worldline command parsing and presentation."""

import json
from pathlib import Path

import click
import yaml

from graphtraj.configuration.project_configuration import ProjectConfigurationError
from graphtraj.interfaces.cli.projection import OperationCommand, OperationGroup, invoke_tool


@click.group(cls=OperationGroup)
def worldline() -> None:
    """Append, read, and render the configured project's Worldline."""


@worldline.command("append", cls=OperationCommand, feature="worldline_append")
@click.option(
    "--event-file",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
def append_command(
    event_file: Path,
) -> None:
    """Append one explicit durable fact from a YAML file."""

    try:
        event = yaml.safe_load(event_file.read_text(encoding="utf-8"))
        recorded = invoke_tool("worldline_append", {"event": event}).document
    except (
        OSError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(recorded, sort_keys=False), nl=False)


@worldline.command("read", cls=OperationCommand, feature="worldline_read")
def read_command() -> None:
    """Read the complete Worldline as chronological JSONL."""

    try:
        events = invoke_tool("worldline_read", {}).document["events"]
    except (
        OSError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    for event in events:
        click.echo(json.dumps(event, ensure_ascii=False, separators=(",", ":")))


@worldline.command("render", cls=OperationCommand, feature="worldline_render")
def render_command() -> None:
    """Render a ledger-shaped YAML view without persisting it."""

    try:
        events = invoke_tool("worldline_render", {}).document["events"]
    except (
        OSError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump({"trajectory": events}, sort_keys=False), nl=False)
