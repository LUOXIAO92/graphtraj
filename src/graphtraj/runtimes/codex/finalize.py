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
from graphtraj.runtimes.codex.session_entry import session_source, event_record


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
        request_handler_timeout=None,
    )


def verify_main(connection: dict) -> str:
    """Check native root metadata for the Session captured by the caller boundary."""
    async def read() -> str:
        """Read metadata through the existing host, without reading conversation turns."""
        async with proxy(connection) as client:
            thread = await client.read_thread(connection['session'])
            if session_source(thread) != 'main':
                raise RuntimeAdapterError('authority-denied', 'A child or unknown native source cannot bind Main Stop.')
            hook_session = thread.get('sessionId')
            if not isinstance(hook_session, str) or not hook_session:
                raise ValueError('The native hook Session identity is unavailable.')
            if 'hook_session' in connection and connection['hook_session'] != hook_session:
                raise ValueError('Codex lifecycle event belongs to a different native Session.')
            connection['hook_session'] = hook_session
            return thread['id']
    return asyncio.run(read())


def hook(path: Path, binding: dict) -> dict:
    """Return Session-scoped adoption material without installing or trusting it."""
    command = shlex.join([
        sys.executable, '-m', 'graphtraj.runtimes.codex.stop_hook',
    ])
    return {'hooks': {event: [{'hooks': [{'type': 'command', 'command': command}]}]
                      for event in ('SessionStart', 'Stop')}}


def event_context(binding: dict, event: dict) -> dict | None:
    """Confirm Main's exact native turn, ignoring other lifecycle events."""
    if event.get('hook_event_name') != 'Stop' or event.get('session_id') != binding['connection']['hook_session']:
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
    context = {'turn': event['turn_id'], 'continued': event['stop_hook_active'],
               'model': event['model']}
    if event.get('transcript_path'):
        metadata, settings = event_record(event)
        if metadata['id'] != binding['session'] or session_source(metadata) != 'main':
            raise ValueError('The Stop transcript does not belong to the bound Main.')
        if settings.get('model') != event['model']:
            raise ValueError('The Stop model conflicts with its native turn settings.')
        context['settings'] = settings
    return context


def response(result: dict | None, continued: bool) -> dict:
    """Return a Stop decision; repeated checker errors cannot self-continue forever."""
    if result is None:
        return {}
    reason = result['reason']
    visible = {'systemMessage': f"Completion check {result['status']}: {reason}"}
    if result['status'] in ('completed', 'waiting'):
        return visible
    if result['status'] == 'actionable':
        return {**visible, 'decision': 'block', 'reason': '\n'.join([reason, *result['nodes']])}
    return {**visible, 'continue': False, 'stopReason': reason}


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
            from graphtraj.interfaces.gateway import handle_request
            from graphtraj.execution.runner_status import runtime_caller
            from graphtraj.workspace.runner_project import discover_runner_directory

            if child_id is None or request.params.get('threadId') != child_id:
                # Subscribing to Main can replay its pending native requests.
                # Its UI owns the response; serverRequest/resolved or connection
                # shutdown cancels this observer without answering on its behalf.
                await asyncio.Future()
            if request.method.endswith('/requestApproval'):
                raise RuntimeAdapterError(
                    'native-approval-unavailable',
                    'The checker requires native approval, but this hook connection '
                    'has no bound user approval interface. No approval was granted.',
                )
            if (request.method != 'item/tool/call'
                    or request.params.get('tool') != 'graphtraj'):
                raise RuntimeAdapterError('authority-denied', 'The checker cannot approve or control work.')

            def call() -> dict:
                """Keep the fork's caller identity separate from the root Main."""
                root = Path(binding['cwd'])
                with runtime_caller(discover_runner_directory(root), child_id):
                    result = handle_request(request.params.get('arguments', {}), cwd=root,
                                            allowed_features={'ticket_graph', 'alias_status'})
                return {'contentItems': [{'type': 'inputText', 'text': json.dumps(result.document)}],
                        'success': not result.failed}
            return await asyncio.to_thread(call)

        async with proxy(binding['connection'], handle) as client:
            parent = await client.read_thread(binding['session'])
            if not await client.is_current_turn(binding['session'], context['turn']):
                return None
            await client.subscribe_host(binding['session'])
            # Hook model is the active turn's slug; Thread.model is configuration,
            # and can differ from actual per-turn model selection.
            parent = {**parent, 'model': context['model']}
            if 'settings' in context:
                parent['turn_settings'] = context['settings']
            child = await client.fork_session(parent)
            child_id = child.thread_id
            created(child_id)
            execution = await client.start_execution(child, prompt)

            async def main_stopped() -> None:
                """Observe the owning turn's native stop without polling or waking it."""
                while True:
                    notice = await client.next_notification()
                    params = notice.get('params', {})
                    if params.get('threadId') != binding['session']:
                        continue
                    if notice.get('method') == 'thread/closed':
                        return
                    if notice.get('method') == 'turn/completed':
                        return
                    if notice.get('method') == 'turn/started' and params.get('turn', {}).get('id') != context['turn']:
                        return

            stopped = asyncio.create_task(main_stopped())
            checked = asyncio.create_task(client.wait(execution, timeout=540))
            try:
                # Leave time for native cancellation before the default 600s hook deadline.
                finished, _ = await asyncio.wait((stopped, checked), return_when=asyncio.FIRST_COMPLETED)
                if stopped in finished:
                    stopped.result()
                    await client.interrupt(execution)
                    await client.wait(execution, timeout=10)
                    return None
                result = checked.result()
            except BaseException as error:
                try:
                    await client.interrupt(execution)
                    await client.wait(execution, timeout=10)
                except RuntimeAdapterError as cleanup_error:
                    error.add_note(f'Checker cancellation: {cleanup_error}')
                raise
            finally:
                stopped.cancel()
                checked.cancel()
                await asyncio.gather(stopped, checked, return_exceptions=True)
            if not await client.is_current_turn(binding['session'], context['turn']):
                return None
            if result['outcome'] != 'completed':
                raise RuntimeAdapterError('operation-failed', 'Completion checker was interrupted.')
            return {'output': result['last_agent_message'], 'session': child_id,
                    'model': parent['model'], 'provider': parent['modelProvider'],
                    'usage': client.token_usage(child)}
    return asyncio.run(run())
