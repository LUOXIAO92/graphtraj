"""Reconnect root events to the Codex daemon that owns the launching terminal."""

from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import ExitStack, contextmanager
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


def parent_status(
    connection: Mapping[str, Any], timeout_seconds: float, *, include_hooks: bool = False,
) -> dict:
    """Read the bound host and optionally wait for native idle plus a terminal turn.

    Read metadata once, then recheck only on a relevant native notification.
    Waiting rejoins only the already-loaded thread to subscribe, without input
    or settings. A proxy that supplies no relevant notification times out;
    there is no polling fallback.
    """
    from graphtraj.execution.runner_process import OPERATION_TIMEOUT_SECONDS
    from graphtraj.runtimes.codex.app_server import CodexAppServer, CodexServerRequest
    from graphtraj.workspace.runner_project import runtime_executable

    if any(not isinstance(connection.get(key), str) or not connection[key]
           for key in ('session', 'codex_home')):
        raise RuntimeAdapterError('operation-failed', 'Invalid owning Codex connection')

    async def observe() -> dict:
        """Bound observations independently of the Agent's ordinary notifications."""
        async def leave_to_host(request: CodexServerRequest) -> dict:
            """Observe without answering replayed Main requests or approvals."""
            await asyncio.Future()

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
                    on_request=leave_to_host,
                    request_handler_timeout=None,
                ) as client:
                    if timeout_seconds:
                        await client.subscribe_host(connection['session'])
                    if include_hooks:
                        from graphtraj.runtimes.codex.session_entry import association_status

                        thread = await client.read_thread(connection['session'])
                        result['native_identity'] = {
                            key: thread[key] for key in
                            ('id', 'sessionId', 'source', 'parentThreadId', 'agentPath', 'depth', 'cwd')
                            if key in thread
                        }
                        result['completion_association'] = association_status(dict(connection), thread)
                        from graphtraj.runtimes.codex.usage import latest_check_usage

                        result['hook_configuration'] = await client.read_hooks(thread.get('cwd'))
                        result['hook_events'] = []
                        result['hook_observation_scope'] = (
                            'hooks/list is discovered configuration/trust, not an active-registry '
                            'snapshot. Events cover this connection only; absence is not proof '
                            'of failure or a historical execution record.'
                        )
                    trigger = None
                    def retain_hook(notification: dict) -> None:
                        """Keep only this owning thread's actual hook notifications."""
                        params = notification.get('params', {})
                        if (include_hooks and params.get('threadId') == connection['session']
                                and notification.get('method') in {'hook/started', 'hook/completed'}):
                            result['hook_events'].append({
                                'method': notification['method'], 'params': params,
                                'observed_at': datetime.now(timezone.utc).isoformat(),
                            })

                    while True:
                        state = await client.read_host_status(connection['session'])
                        observations.append({**state, 'observed_at': datetime.now(timezone.utc).isoformat(),
                                             'trigger': trigger})
                        terminal = state['turn'] is not None and state['turn']['status'] != 'inProgress'
                        idle = state['activity'] == 'idle' and terminal
                        if idle or not timeout_seconds or state['activity'] in {'notLoaded', 'systemError'}:
                            for notification in client.drain_notifications():
                                retain_hook(notification)
                            if include_hooks:
                                # The Stop may finish during this wait. Select the
                                # latest retained check now, not at subscription.
                                result['completion_usage'] = await latest_check_usage(
                                    client, result['completion_association'],
                                )
                            return {**result, 'outcome': 'idle' if idle else 'observed'}
                        while True:
                            notification = await client.next_notification()
                            params = notification.get('params', {})
                            method = notification.get('method')
                            retain_hook(notification)
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


# Events written to the host whose application is not yet known. They stay
# pending with their sender; this process checks the host record before any
# resubmission. A new process has no such memory and submits normally.
_UNRESOLVED: set[tuple[str, str, str]] = set()


async def _recorded_turn(connection: Mapping[str, Any], event: dict[str, str]) -> str:
    """Return the turn recording this exact event, or raise while it is unresolved."""
    from graphtraj.runtimes.codex.app_server import CodexAppServer, host_event_output
    from graphtraj.workspace.runner_project import runtime_executable

    try:
        async with CodexAppServer(
            cwd=Path.cwd(),
            command=(str(runtime_executable('codex')), 'app-server', 'proxy'),
            environment={'CODEX_HOME': connection['codex_home']},
            experimental_api=True,
        ) as client:
            turn = await client.host_tool_output_turn(
                connection['session'], 'graphtraj', host_event_output(event))
    except RuntimeAdapterError as error:
        raise RuntimeAdapterError(
            'delivery-unresolved',
            'The parent host may have received this event; its record is unreadable now.',
        ) from error
    if turn is None:
        raise RuntimeAdapterError(
            'delivery-unresolved',
            'The parent host may still record this event; it is not resubmitted.',
        )
    return turn


def send_event(connection: Mapping[str, Any], event: dict[str, str]) -> dict:
    """Use a bounded proxy connection to the existing service for this event only."""
    from graphtraj.runtimes.codex.app_server import CodexAppServer, host_event_output
    from graphtraj.workspace.runner_project import discover_project_root, runtime_executable

    if (set(event) != {'source', 'alias', 'event', 'message'}
            or event['source'] != 'graphtraj'
            or any(not isinstance(value, str) or not value for value in event.values())):
        raise RuntimeAdapterError('operation-failed', 'Invalid parent event')
    if any(not isinstance(connection.get(key), str) or not connection[key]
           for key in ('session', 'codex_home')):
        raise RuntimeAdapterError('operation-failed', 'Invalid owning Codex connection')

    key = (connection['codex_home'], connection['session'], host_event_output(event))

    async def forward(receipts: ExitStack) -> dict:
        """Closing the proxy leaves the daemon and its original thread running."""
        async with CodexAppServer(
            cwd=Path.cwd(),
            command=(str(runtime_executable('codex')), 'app-server', 'proxy'),
            environment={'CODEX_HOME': connection['codex_home']},
            experimental_api=True,
        ) as client:
            from graphtraj.execution.main_finalize import session_binding
            from graphtraj.execution.runner_models import RunnerError

            # Capture before submission: a delayed acknowledgement must never
            # invalidate a newer fork that already includes this notification.
            pending = []
            try:
                # Completion senders run in their assigned Worktree, whereas
                # Main's binding belongs to the containing Harness Project.
                root = discover_project_root(Path.cwd())
                directory = session_binding(root, 'codex', connection['session']).parent
            except RunnerError:
                directory = None  # This host has no project completion binding.
            if directory is not None:
                for path in directory.glob('pending-*/turn'):
                    try:
                        # Open the existing address before sending. Cleanup may
                        # unlink it during the request; an open descriptor cannot
                        # recreate it or accidentally target the next check.
                        stream = receipts.enter_context(os.fdopen(
                            os.open(path, os.O_RDWR | os.O_APPEND), 'r+', encoding='utf-8',
                        ))
                        pending.append((stream, stream.readline().strip()))
                    except FileNotFoundError:
                        pass  # The check ended before submission.
            submitted_at = time.time()
            if key in _UNRESOLVED:
                # Already written once: only the host's own record decides.
                result = {'turn': {'id': await _recorded_turn(connection, event)}}
                _UNRESOLVED.discard(key)
            else:
                try:
                    result = await client.send_host_event(connection['session'], event)
                except RuntimeAdapterError as error:
                    if not getattr(error, 'request_written', False):
                        raise  # Nothing reached the host; ordinary retry applies.
                    # The host may still apply it later, so absence now is not
                    # final: never resubmit, only look for its record again.
                    _UNRESOLVED.add(key)
                    result = {'turn': {'id': await _recorded_turn(connection, event)}}
                    _UNRESOLVED.discard(key)
            accepted_at = time.time()
            for stream, turn in pending:
                if result['turn']['id'] != turn:
                    continue
                stream.write(json.dumps({'turn': turn, 'submitted_at': submitted_at,
                                         'accepted_at': accepted_at}) + '\n')
                stream.flush()
            return result

    with ExitStack() as receipts:
        return asyncio.run(forward(receipts))
