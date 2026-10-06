"""Codex Stop carrier and native context fork for one bound Main."""

from __future__ import annotations

import asyncio
import json
import shlex
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

from graphtraj.runtimes.codex.app_server import CodexAppServer, CodexServerRequest
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError
from graphtraj.workspace.runner_project import runtime_executable


def proxy(
    connection: dict,
    on_request: Callable[[CodexServerRequest], Awaitable[dict]] | None = None,
) -> CodexAppServer:
    """Connect to the already owning daemon; never start a replacement service."""
    if any(not isinstance(connection.get(k), str) or not connection[k]
           for k in ('session', 'codex_home')):
        raise ValueError('Invalid owning Codex connection.')
    return CodexAppServer(
        cwd=Path.cwd(), command=(str(runtime_executable('codex')), 'app-server', 'proxy'),
        environment={'CODEX_HOME': connection['codex_home']}, experimental_api=True,
        on_request=on_request,
    )


def verify_main(connection: dict) -> str:
    """Resolve transport handles; GraphTraj already verified the Agent purpose."""
    async def read() -> str:
        """Read metadata through the existing host, without reading conversation turns."""
        async with proxy(connection) as client:
            thread = await client.read_thread(connection['session'])
            hook_session = thread.get('sessionId')
            if not isinstance(hook_session, str) or not hook_session:
                raise ValueError('The native hook Session identity is unavailable.')
            connection['hook_session'] = hook_session
            return thread['id']
    return asyncio.run(read())


def hook(path: Path, binding: dict) -> dict:
    """Prepare the native command carrier without modifying enable/trust settings."""
    carrier = '--host-binding' if binding.get('trusted_host') else '--channel'
    command = shlex.join([sys.executable, '-m', 'graphtraj.runtimes.codex.stop_hook',
                          carrier, str(path), '--project', binding['cwd']])
    return {'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': command,
                                         'statusMessage': '[GraphTraj hook: finish-check]'}]}]}}


def event_context(binding: dict, event: dict) -> dict | None:
    """Confirm Main's exact native turn, ignoring other lifecycle events."""
    if not isinstance(event, dict) or not isinstance(event.get('hook_event_name'), str):
        raise ValueError('The native lifecycle event is unavailable.')
    if event['hook_event_name'] in ('Interrupt', 'SubagentStop'):
        return None
    if event['hook_event_name'] != 'Stop':
        raise ValueError('Unknown native finish-check lifecycle event.')
    if not isinstance(event.get('session_id'), str) or not event['session_id']:
        raise ValueError('The native event execution handle is unavailable.')
    if event['session_id'] != binding['connection']['hook_session']:
        return None
    if not isinstance(event.get('turn_id'), str) or not event['turn_id']:
        raise ValueError('Stop did not identify its native turn.')
    if type(event.get('stop_hook_active')) is not bool:
        raise ValueError('Stop did not identify continuation state.')
    if not isinstance(event.get('model'), str) or not event['model']:
        raise ValueError('Stop did not identify its actual native model.')

    async def belongs_to_main() -> bool:
        """A fork shares session_id; the exact native Main turn owns this Stop."""
        async with proxy(binding['connection']) as client:
            return await client.is_current_turn(binding['session'], event['turn_id'])

    if not asyncio.run(belongs_to_main()):
        return None
    return {'turn': event['turn_id'], 'continued': event['stop_hook_active'],
            'model': event['model']}


def response(result: dict | None, continued: bool) -> dict:
    """Return a Stop decision; repeated checker errors cannot self-continue forever."""
    prefix = '[GraphTraj hook: finish-check]'
    if result is None:
        return {'systemMessage': f'{prefix} skip: owning turn stopped, changed or unrelated.'}
    outcome = {'completed': 'pass', 'waiting': 'pass', 'actionable': 'continue', 'error': 'failure'}[result['status']]
    reason = f"{prefix} {outcome}: {result['reason']}"
    if result['status'] in ('completed', 'waiting'):
        return {'systemMessage': reason}
    if result['status'] == 'actionable':
        return {'decision': 'block', 'reason': '\n'.join([reason, *result['nodes']])}
    if continued:
        return {'continue': False, 'stopReason': reason, 'systemMessage': reason}
    return {'decision': 'block', 'reason': reason}


def check(
    binding: dict,
    context: dict,
    prompt: str,
    created: Callable[[str], None],
) -> dict[str, Any] | None:
    """Fork native context, bind the returned child and append only its check task."""
    async def run() -> dict | None:
        """Keep the child owned until terminal; inherited hooks filter its distinct ID."""
        child_id: str | None = None

        async def handle(request: CodexServerRequest) -> dict:
            """Expose only read-only GraphTraj task summaries to this exact checker."""
            if (request.method != 'item/tool/call' or child_id is None
                    or request.params.get('threadId') != child_id
                    or request.params.get('tool') != 'graphtraj'):
                raise RuntimeAdapterError('authority-denied', 'The checker cannot approve or control work.')

            def call() -> dict:
                """Keep the fork's caller identity separate from the root Main."""
                result = binding['checker_tool'](request.params.get('arguments', {}))
                return {'contentItems': [{'type': 'inputText', 'text': json.dumps(result.document)}],
                        'success': not result.failed}
            return await asyncio.to_thread(call)

        async with proxy(binding['connection'], handle) as client:
            parent = await client.read_thread(binding['session'])
            if not await client.is_current_turn(binding['session'], context['turn']):
                return None
            # Hook model is the active turn's slug; Thread.model is configuration,
            # and can differ from actual per-turn model selection.
            parent = {**parent, 'model': context['model']}
            child = await client.fork_session(parent)
            child_id = child.thread_id
            created(child_id)
            execution = await client.start_execution(child, prompt)
            try:
                # Leave time for native cancellation before the default 600s hook deadline.
                pending = asyncio.create_task(client.wait(execution, timeout=540))
                while not pending.done():
                    await asyncio.wait({pending}, timeout=1)
                    await asyncio.to_thread(binding['execution_allowed'])
                    if not await client.is_current_turn(binding['session'], context['turn']):
                        if not pending.done():
                            await client.interrupt(execution)
                        await pending
                        return None
                result = await pending
            except BaseException as error:
                if not pending.done():
                    pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
                try:
                    await client.interrupt(execution)
                    await client.wait(execution, timeout=10)
                except RuntimeAdapterError as cleanup_error:
                    error.add_note(f'Checker cancellation: {cleanup_error}')
                raise
            if not await client.is_current_turn(binding['session'], context['turn']):
                return None
            if result['outcome'] != 'completed':
                raise RuntimeAdapterError('operation-failed', 'Completion checker was interrupted.')
            return {'output': result['last_agent_message'], 'session': child_id,
                    'model': parent['model'], 'provider': parent['modelProvider'],
                    'usage': client.token_usage(child)}
    return asyncio.run(run())
