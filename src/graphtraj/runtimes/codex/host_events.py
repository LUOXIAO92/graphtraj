"""Reconnect root events to the Codex daemon that owns the launching terminal."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Mapping

from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


def current_connection() -> dict | None:
    """Capture native launch context, never a model-supplied recipient parameter.

    CODEX_HOME selects the same public control socket as the native proxy CLI.
    Retaining it and the native thread makes delivery independent of the CLI's
    lifetime. Formal children use their mapped parent or explicit host callback.
    """
    session = os.environ.get('CODEX_THREAD_ID')
    if not session or os.environ.get('GRAPHTRAJ_ROLE'):
        return None
    return {
        'runtime': 'codex', 'session': session,
        'codex_home': os.path.abspath(os.environ.get('CODEX_HOME', Path.home() / '.codex')),
    }


def send_event(connection: Mapping[str, Any], event: dict[str, str]) -> dict:
    """Use a bounded proxy connection to the existing service for this event only."""
    from graphtraj.runtimes.codex.app_server import CodexAppServer
    from graphtraj.workspace.runner_project import runtime_executable

    if (set(event) != {'source', 'alias', 'event', 'message'}
            or event['source'] != 'graphtraj'
            or any(not isinstance(value, str) or not value for value in event.values())):
        raise RuntimeAdapterError('operation-failed', 'Invalid parent event')
    if any(not isinstance(connection.get(key), str) or not connection[key]
           for key in ('session', 'codex_home')):
        raise RuntimeAdapterError('operation-failed', 'Invalid owning Codex connection')

    async def forward() -> dict:
        """Closing the proxy leaves the daemon and its original thread running."""
        async with CodexAppServer(
            cwd=Path.cwd(),
            command=(str(runtime_executable('codex')), 'app-server', 'proxy'),
            environment={'CODEX_HOME': connection['codex_home']},
            experimental_api=True,
        ) as client:
            return await client.send_host_event(connection['session'], event)

    return asyncio.run(forward())
