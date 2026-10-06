"""CLI binding for Main completion checks through the common operation."""

from __future__ import annotations

import json
from pathlib import Path

import click

from graphtraj.interfaces.cli.projection import OperationCommand, invoke_tool


@click.command('bind-finalize', cls=OperationCommand, feature='bind_main_finalize')
@click.option('--summary-issue')
def bind_command(summary_issue: str | None) -> None:
    """Prepare reviewable native hook material on the adopted Main channel."""
    try:
        arguments = {'summary_issue': summary_issue} if summary_issue is not None else {}
        result = invoke_tool('bind_main_finalize', arguments)
    except Exception as error:
        raise click.ClickException(str(error)) from error
    click.echo(json.dumps(result.document, ensure_ascii=False))


@click.command('adopt-main', cls=OperationCommand, feature='adopt_main')
@click.option('--resume')
def adopt_command(resume: str | None) -> None:
    """Retain the existing Main's reviewed owner and print disabled hook material."""
    from graphtraj.execution.runner_worker import run_external_main
    from graphtraj.interfaces.tools import adopt_external_main

    def execute(cwd: Path, alias: str | None) -> dict:
        """Keep ownership in this terminal after publishing the ready document."""
        return run_external_main(cwd, alias, lambda ready: click.echo(json.dumps(ready)))

    try:
        arguments = {'resume': resume} if resume else {}
        result = adopt_external_main(arguments, cwd=Path.cwd(), execute=execute)
        click.echo(json.dumps(result.document))
    except Exception as error:
        raise click.ClickException(f'External Main adoption failed: {error}') from error
