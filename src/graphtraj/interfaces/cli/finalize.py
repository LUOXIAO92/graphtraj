"""CLI binding for Main completion checks through the common operation."""

from __future__ import annotations

import json

import click

from graphtraj.interfaces.cli.projection import OperationCommand, invoke_tool


@click.command('bind-finalize', cls=OperationCommand, feature='bind_main_finalize')
@click.option('--summary-issue', required=True)
def bind_command(summary_issue: str) -> None:
    """Bind the actual Main and print hook material for host review/adoption."""
    try:
        result = invoke_tool('bind_main_finalize', {'summary_issue': summary_issue})
    except Exception as error:
        raise click.ClickException(str(error)) from error
    click.echo(json.dumps(result.document, ensure_ascii=False))
