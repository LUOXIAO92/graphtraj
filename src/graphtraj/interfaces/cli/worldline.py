"""Project Worldline command parsing and presentation."""

import json
from pathlib import Path

import click
import yaml

from graphtraj.configuration.project_configuration import (
    ProjectConfigurationError,
    load_project_configuration,
)
from graphtraj.graph.delivery_worldline import append_project_worldline_event, read_worldline


@click.group()
def worldline() -> None:
    """Append, read, and render the configured project's Worldline."""


@worldline.command("append")
@click.option(
    "--event-file",
    required=True,
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
def append_command(
    event_file: Path,
) -> None:
    """Append one explicit durable fact from a YAML file."""

    try:
        event = yaml.safe_load(event_file.read_text(encoding="utf-8"))
        if not isinstance(event, dict):
            raise ValueError("event file must contain one mapping")
        configuration = load_project_configuration(Path.cwd())
        recorded = append_project_worldline_event(
            configuration.state, configuration.harness_root, event
        )
    except (
        OSError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(recorded, sort_keys=False), nl=False)


@worldline.command("read")
def read_command() -> None:
    """Read the complete Worldline as chronological JSONL."""

    try:
        configuration = load_project_configuration(Path.cwd())
        events = read_worldline(configuration.state, configuration.harness_root)
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


@worldline.command("render")
def render_command() -> None:
    """Render a ledger-shaped YAML view without persisting it."""

    try:
        configuration = load_project_configuration(Path.cwd())
        events = read_worldline(configuration.state, configuration.harness_root)
    except (
        OSError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
        ProjectConfigurationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump({"trajectory": events}, sort_keys=False), nl=False)
