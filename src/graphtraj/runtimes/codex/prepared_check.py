"""Native metadata, correlation and lifecycle for a Main-executed checker fork."""

from __future__ import annotations

import asyncio
import time
from typing import Callable

from graphtraj.runtimes.codex import finalize
from graphtraj.runtimes.codex.app_server import CodexAppServer
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


def failure(message: str) -> RuntimeAdapterError:
    """Return a visible native association failure without accepting caller claims."""
    return RuntimeAdapterError('operation-failed', message)


async def pages(client: CodexAppServer, method: str, parameters: dict) -> list[dict]:
    """Read a bounded native query through its own pagination contract."""
    result = []
    cursors = set()
    while True:
        reply = await client._call(method, parameters)
        data = reply.get('data')
        if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
            raise failure(f'{method}: invalid native collection.')
        result.extend(data)
        cursor = reply.get('nextCursor')
        if cursor is None:
            return result
        if not isinstance(cursor, str) or cursor in cursors:
            raise failure(f'{method}: invalid native pagination.')
        cursors.add(cursor)
        parameters = {**parameters, 'cursor': cursor}


def user_input_ids(entries: list[dict]) -> list[str]:
    """Keep only native input identifiers so same-turn steering invalidates old checks."""
    identifiers = []
    for entry in entries:
        item = entry.get('item')
        if isinstance(item, dict) and item.get('type') == 'userMessage':
            if not isinstance(item.get('id'), str) or not item['id']:
                raise failure('Native Main input has no stable identifier.')
            identifiers.append(item['id'])
    return identifiers


def prepare(connection: dict, task_name: str, prompt: str, turn: str | None) -> dict:
    """Bind materials to the actual active Main turn without setting any Runtime option."""
    async def run() -> dict:
        async with finalize.proxy(connection) as client:
            status = await client.read_host_status(connection['session'])
            current = status.get('turn')
            if not isinstance(current, dict):
                raise failure('The owning Main has no current native turn.')
            current_id = current.get('id')
            if not isinstance(current_id, str) or not await client.is_current_turn(connection['session'], current_id):
                raise failure('The owning Main turn is no longer active.')
            if turn is not None and current_id != turn:
                raise failure('Preparation cannot substitute a later Main turn.')
            entries = await pages(client, 'thread/items/list', {
                'threadId': connection['session'], 'turnId': current_id, 'limit': 100,
            })
            return {'session': connection['session'], 'turn': current_id, 'task_name': task_name,
                    'input_ids': user_input_ids(entries),
                    'native_action': {'tool': 'collaboration.spawn_agent', 'arguments': {
                        'task_name': task_name, 'message': prompt, 'fork_turns': 'all'}},
                    'configuration_status': 'Native full-history model/effort inheritance; '
                    'remaining effective settings require native confirmation.'}
    return asyncio.run(run())


async def association(client: CodexAppServer, preparation: dict, task_path: str | None) -> dict | None:
    """Resolve the actual returned task path and prove this preparation's native spawn."""
    if task_path is not None and (not task_path.startswith('/') or
                                 task_path.rsplit('/', 1)[-1] != preparation['task_name']):
        raise failure('The returned task path does not match this prepared checker.')
    parent = preparation['session']
    threads = []
    for archived in (False, True):
        threads.extend(await pages(client, 'thread/list', {
            'parentThreadId': parent, 'sourceKinds': ['subAgentThreadSpawn'],
            'archived': archived, 'limit': 100,
        }))
    matches = []
    for thread in threads:
        source = thread.get('source')
        source = source.get('subAgent', {}) if isinstance(source, dict) else {}
        source = source.get('thread_spawn', {}) if isinstance(source, dict) else {}
        path = source.get('agent_path')
        if (isinstance(path, str) and path.rsplit('/', 1)[-1] == preparation['task_name']
                and (task_path is None or path == task_path)):
            parents = {'source.parent_thread_id': source.get('parent_thread_id'),
                       'parentThreadId': thread.get('parentThreadId')}
            # Native full-history spawn can leave this optional field null.
            # The source parents and prepared-turn spawn receiver below remain
            # mandatory; a supplied contradictory fork origin still refuses.
            if thread.get('forkedFromId') is not None:
                parents['forkedFromId'] = thread['forkedFromId']
            conflicts = {name: value for name, value in parents.items() if value != parent}
            if conflicts:
                raise failure('Prepared checker lacks genuine native fork provenance: '
                              f'expected parent {parent!r}; differing native fields {conflicts!r}.')
            matches.append(thread)
    if not matches:
        return None
    if len(matches) != 1 or not isinstance(matches[0].get('id'), str):
        raise failure('Prepared checker has ambiguous native associations.')
    child = matches[0]
    entries = await pages(client, 'thread/items/list', {
        'threadId': parent, 'turnId': preparation['turn'], 'limit': 100,
    })
    matching_calls = [entry['item'] for entry in entries
                      if entry.get('turnId') == preparation['turn']
                      and isinstance(entry.get('item'), dict)
                      and entry['item'].get('type') == 'collabAgentToolCall'
                      and entry['item'].get('tool') == 'spawnAgent'
                      and entry['item'].get('senderThreadId') == parent
                      and child['id'] in entry['item'].get('receiverThreadIds', [])
                      and entry['item'].get('status') in ('inProgress', 'completed')]
    if len(matching_calls) != 1:
        raise failure('No unique native spawn links this checker to the prepared Main turn.')
    return {'session': child['id'], 'task_path': child['source']['subAgent']['thread_spawn']['agent_path'],
            'spawn_call': matching_calls[0]['id'], 'model': child.get('model'),
            'provider': child.get('modelProvider'), 'effort': child.get('reasoningEffort')}


def observe(
    connection: dict,
    preparation: dict,
    task_path: str | None,
    wait_seconds: float,
    cancel: bool,
    allowed: Callable[[], None],
    associated: Callable[[dict], None],
) -> dict:
    """Verify and read an external child's native result, or interrupt that exact child."""
    async def run() -> dict:
        async with finalize.proxy(connection) as client:
            native = await association(client, preparation, task_path)
            if native is None:
                if cancel:
                    return {'state': 'cancelled', 'reason': 'No matching native execution exists.'}
                raise failure('The returned native task is not visible through thread/list.')
            associated(native)
            deadline = time.monotonic() + wait_seconds
            interrupted = False
            while True:
                response = await client._call('thread/turns/list', {
                    'threadId': native['session'], 'limit': 1, 'itemsView': 'notLoaded',
                })
                turns = response.get('data')
                if not isinstance(turns, list) or not turns or not isinstance(turns[0], dict):
                    raise failure('External checker turn metadata is unavailable.')
                turn = turns[0]
                if (not isinstance(turn.get('id'), str) or not turn['id']
                        or turn['id'] == preparation['turn']):
                    raise failure('The external checker has no distinct native execution turn.')
                if turn.get('status') not in ('inProgress', 'completed', 'interrupted', 'failed'):
                    raise failure('External checker has unknown native status.')
                stale = not await client.is_current_turn(preparation['session'], preparation['turn'])
                try:
                    allowed()
                except Exception:
                    stale = True
                if (cancel or stale) and turn['status'] == 'inProgress' and not interrupted:
                    await client._call('turn/interrupt', {'threadId': native['session'], 'turnId': turn['id']})
                    interrupted = True
                    deadline = max(deadline, time.monotonic() + 5)
                elif turn['status'] != 'inProgress':
                    current_inputs = await pages(client, 'thread/items/list', {
                        'threadId': preparation['session'], 'turnId': preparation['turn'], 'limit': 100,
                    })
                    stale = stale or user_input_ids(current_inputs) != preparation['input_ids']
                    if turn['status'] == 'failed' and not cancel and not stale:
                        return {**native, 'state': 'failed', 'turn': turn['id'],
                                'reason': 'The native checker execution failed.'}
                    if cancel or stale or turn['status'] != 'completed':
                        return {**native, 'state': 'cancelled', 'turn': turn['id'],
                                'reason': 'Checker stopped or its prepared Main turn is no longer current.'}
                    entries = await pages(client, 'thread/items/list', {
                        'threadId': native['session'], 'turnId': turn['id'], 'limit': 100,
                    })
                    messages = [entry['item']['text'] for entry in entries
                                if entry.get('turnId') == turn['id'] and isinstance(entry.get('item'), dict)
                                and entry['item'].get('type') == 'agentMessage'
                                and entry['item'].get('phase') in (None, 'final_answer')
                                and isinstance(entry['item'].get('text'), str)]
                    if not messages:
                        raise failure('The native checker produced no readable final result.')
                    return {**native, 'state': 'completed', 'turn': turn['id'], 'output': messages[-1],
                            'configuration_confirmed': False,
                            'configuration_error': 'Native public metadata does not confirm service tier, '
                            'output schema and effective collaboration instructions for the checked turn.'}
                if time.monotonic() >= deadline:
                    if interrupted:
                        raise failure('Native checker interruption was not confirmed.')
                    return {**native, 'state': 'running', 'turn': turn['id']}
                await asyncio.sleep(0.2)
    return asyncio.run(run())
