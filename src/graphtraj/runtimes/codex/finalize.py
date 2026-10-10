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
from graphtraj.runtimes.codex.usage import CodexCheckUsage


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
    messages = {
        'SessionStart': 'GraphTraj: associating Main session',
        'Stop': 'GraphTraj: checking task completion',
    }
    return {'hooks': {
        event: [{'hooks': [{'type': 'command', 'command': command, 'statusMessage': message}]}]
        for event, message in messages.items()
    }}


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
    headings = {
        'completed': 'Main 可以结束本轮 · 任务已完成',
        'waiting': 'Main 可以结束本轮 · 等待中，任务未完成',
        'actionable': 'Main 需要继续本轮',
        'error': '无法判定 Main 是否可以结束本轮 · 检查故障',
    }
    sections = [headings[result['status']], result['reason'].strip()]
    if result['nodes']:
        sections.append('相关任务：' + '、'.join(dict.fromkeys(result['nodes'])))
    if result.get('usage_summary'):
        sections.append(result['usage_summary'])
    message = '\n\n'.join(sections)
    # Codex renders each of these fields as a separate hook entry. The block
    # reason is already both visible feedback and the same Main's continuation.
    if result['status'] in ('completed', 'waiting'):
        return {'systemMessage': message}
    if result['status'] == 'actionable':
        return {'decision': 'block', 'reason': message}
    return {'continue': False, 'stopReason': message}


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
            configuration = await client.subscribe_host(binding['session'])
            # Hook model is the active turn's slug; Thread.model is configuration,
            # and can differ from actual per-turn model selection.
            parent = {**parent, 'model': context['model'], 'configuration': configuration}
            parent['turn_settings'] = dict(context.get('settings', {}))
            if 'effort' not in parent['turn_settings'] and 'reasoningEffort' in configuration:
                parent['turn_settings']['effort'] = configuration['reasoningEffort']
            child = await client.fork_session(parent)
            child_id = child.thread_id
            created(child_id)
            usage = CodexCheckUsage(child.rollout_path, child_id,
                                    parent['turn_settings'].get('check_usage_baseline'))
            evidence = {
                'session': child_id, 'parent': binding['session'], 'parent_turn': context['turn'],
                'model': parent['model'], 'provider': parent['modelProvider'],
                'configuration': child.configuration,
                'parent_configuration': {key: configuration[key] for key in child.configuration
                                         if key != 'thread' and key in configuration},
            }
            # Stop's turn is still in progress, so native lastTurnId is invalid.
            # The fork itself fixes its history boundary. Reject a superseding
            # Main turn before starting any model request against that snapshot.
            if not await client.is_current_turn(binding['session'], context['turn']):
                return {**evidence, 'outcome': 'cancelled', 'usage': usage.finish('')}
            try:
                execution = await client.start_execution(child, prompt)
            except Exception as error:
                return {**evidence, 'outcome': 'error', 'error': str(error), 'usage': usage.finish('')}

            async def main_stopped() -> None:
                """Observe the owning turn's native stop without polling or waking it."""
                while True:
                    notice = await client.next_notification()
                    usage.observe(notice)
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

            async def cancel_execution() -> None:
                """Confirm termination even if completion raced with cancellation."""
                try:
                    await client.interrupt(execution)
                except RuntimeAdapterError:
                    # A terminal result proves no execution remains to interrupt.
                    # A failed wait still exposes the cleanup failure to the caller.
                    await client.wait(execution, timeout=10)
                else:
                    await client.wait(execution, timeout=10)

            outcome = 'completed'
            failure = None
            result = {}
            try:
                # Leave time for native cancellation before the default 600s hook deadline.
                finished, _ = await asyncio.wait((stopped, checked), return_when=asyncio.FIRST_COMPLETED)
                if stopped in finished:
                    stopped.result()
                    await cancel_execution()
                    outcome = 'cancelled'
                else:
                    result = checked.result()
            except BaseException as error:
                try:
                    await cancel_execution()
                except RuntimeAdapterError as cleanup_error:
                    error.add_note(f'Checker cancellation: {cleanup_error}')
                if not isinstance(error, Exception):
                    raise
                outcome = 'error'
                failure = str(error)
            finally:
                stopped.cancel()
                checked.cancel()
                await asyncio.gather(stopped, checked, return_exceptions=True)
                for notice in client.drain_notifications():
                    usage.observe(notice)
            try:
                if (not await client.is_current_turn(binding['session'], context['turn'])
                        and outcome != 'error'):
                    outcome = 'cancelled'
            except Exception as error:
                outcome = 'error'
                failure = failure or str(error)
            if outcome == 'completed' and result.get('outcome') != 'completed':
                outcome = 'error'
                failure = 'Completion checker was interrupted.'
            observed_usage = usage.finish(execution.turn_id)
            return {**evidence, 'output': result.get('last_agent_message'),
                    'outcome': outcome, 'error': failure, 'turn': execution.turn_id,
                    'usage': observed_usage, 'response_usage': usage.response_evidence(execution.turn_id)}
    return asyncio.run(run())
