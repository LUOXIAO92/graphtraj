"""Fixed administrative MCP adoption through the existing native proxy transport."""
from __future__ import annotations

import asyncio
from pathlib import Path

import click
import yaml

from graphtraj.runtimes.codex.app_server import CodexAppServer
from graphtraj.runtimes.codex.codex_adapter import CodexAdapterError


@click.command('refresh-mcp')
@click.option('--socket', 'socket_path', required=True, type=click.Path(path_type=Path))
@click.option('--main-session', required=True)
@click.option('--server', default='graphtraj', show_default=True)
@click.option('--observe-only', is_flag=True, help='Read current service evidence without requesting another reload.')
def refresh_mcp_command(socket_path: Path, main_session: str, server: str, observe_only: bool) -> None:
    """Reload MCP via the current Codex host; never create or resume a Session.

    Supply the already verified current host socket and Main identity. The
    existing adapter performs HTTP Upgrade and WebSocket framing over pipes;
    raw JSON lines sent to a PTY are not this native transport.
    """
    async def execute() -> dict:
        """Close only this command's proxy connection after its bounded RPCs."""
        async with CodexAppServer(command=('codex', 'app-server', 'proxy', '--sock', str(socket_path)),
                                  cwd=Path.cwd(), experimental_api=True) as host:
            return await host.refresh_mcp(main_session, server, observe_only=observe_only)

    try:
        result = asyncio.run(execute())
    except (OSError, ValueError, CodexAdapterError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(yaml.safe_dump(result, sort_keys=False), nl=False)
    if not result['evidence_available']:
        click.echo('MCP serving-source evidence unavailable; inspect the bounded diagnostic output.', err=True)
        raise click.exceptions.Exit(1)
