"""Reconnect root events to the Codex daemon that owns the launching terminal."""

from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Iterator

from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


_calling_session: ContextVar[str | None] = ContextVar('codex_calling_session', default=None)


@contextmanager
def calling_session(session: str | None) -> Iterator[None]:
    """Scope native MCP metadata to this call instead of changing process state."""
    token = _calling_session.set(session)
    try:
        yield
    finally:
        _calling_session.reset(token)


def request_connection() -> dict | None:
    """Return only this native MCP callback's context, excluding inherited env."""
    return current_connection() if _calling_session.get() is not None else None


def parent_status(connection: Mapping[str, Any], timeout_seconds: float) -> dict:
    """Read the bound host and optionally wait for native idle plus a terminal turn.

    Read metadata once, then recheck only on a relevant native notification.
    Waiting rejoins only the already-loaded thread to subscribe, without input
    or settings. A proxy that supplies no relevant notification times out;
    there is no polling fallback.
    """
    from graphtraj.execution.runner_process import OPERATION_TIMEOUT_SECONDS
    from graphtraj.runtimes.codex.app_server import CodexAppServer
    from graphtraj.workspace.runner_project import runtime_executable

    if any(not isinstance(connection.get(key), str) or not connection[key]
           for key in ('session', 'codex_home')):
        raise RuntimeAdapterError('operation-failed', 'Invalid owning Codex connection')

    async def observe() -> dict:
        """Bound observations independently of the Agent's ordinary notifications."""
        observations = []
        result = {'runtime': 'codex', 'session': connection['session'],
                  'outcome': 'timeout', 'observations': observations,
                  'started_at': datetime.now(timezone.utc).isoformat()}
        try:
            async with asyncio.timeout(timeout_seconds or OPERATION_TIMEOUT_SECONDS):
                async with CodexAppServer(
                    cwd=Path.cwd(),
                    command=(str(runtime_executable('codex')), 'app-server', 'proxy'),
                    environment={'CODEX_HOME': connection['codex_home']},
                    experimental_api=True,
                    request_timeout=OPERATION_TIMEOUT_SECONDS,
                ) as client:
                    if timeout_seconds:
                        await client.subscribe_host(connection['session'])
                    trigger = None
                    while True:
                        state = await client.read_host_status(connection['session'])
                        observations.append({**state, 'observed_at': datetime.now(timezone.utc).isoformat(),
                                             'trigger': trigger})
                        terminal = state['turn'] is not None and state['turn']['status'] != 'inProgress'
                        if state['activity'] == 'idle' and terminal:
                            return {**result, 'outcome': 'idle'}
                        if not timeout_seconds or state['activity'] in {'notLoaded', 'systemError'}:
                            return {**result, 'outcome': 'observed'}
                        while True:
                            notification = await client.next_notification()
                            params = notification.get('params', {})
                            method = notification.get('method')
                            if (params.get('threadId') == connection['session'] and method in {
                                'turn/completed', 'thread/status/changed', 'thread/closed',
                            }):
                                trigger = {'method': method,
                                           'received_at': datetime.now(timezone.utc).isoformat()}
                                break
        except TimeoutError:
            return result
        except (RuntimeAdapterError, OSError) as error:
            return {**result, 'outcome': 'error', 'error': {
                'code': getattr(error, 'code', 'operation-failed'), 'message': str(error),
            }}

    return {**asyncio.run(observe()), 'finished_at': datetime.now(timezone.utc).isoformat()}


def current_connection() -> dict | None:
    """Capture native launch context, never a model-supplied recipient parameter.

    CODEX_HOME selects the same public control socket as the native proxy CLI.
    Retaining it and the native thread makes delivery independent of the CLI's
    lifetime. Formal children use their mapped parent or explicit host callback.
    """
    session = _calling_session.get() or os.environ.get('CODEX_THREAD_ID')
    if not session or (_calling_session.get() is None and os.environ.get('GRAPHTRAJ_ROLE')):
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
