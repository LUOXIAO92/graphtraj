"""Retain ordered ephemeral app-server history without inventing model items."""

from copy import deepcopy
import asyncio
from typing import Awaitable, Callable

from agent_swarm.sessions.archive import JsonlSessionStore, SessionArchive
from agent_swarm.sessions.protocol import retain_native


def _events(store: JsonlSessionStore) -> list[dict]:
    """Read the retained log so new evidence cannot replace earlier records."""
    events = []
    after = -1
    while True:
        page = store.page(after)
        events.extend(page['events'])
        if not page['has_more']:
            return events
        after = page['after']


class CodexHistoryArchive:
    """Collect owned thread snapshots through native pagination.

    App-server 0.163 exposes display ThreadItems, not the ResponseItems consumed
    by the model. Snapshots are retained as required opaque evidence: consumers
    must not mistake this projection for a complete model message history.
    Each page and native timestamp remains intact; notifications only wake I/O.
    """

    def __init__(
        self,
        archive: SessionArchive,
        agent: str,
        thread: dict,
        call: Callable[[str, dict], Awaitable[dict]],
    ) -> None:
        """Bind only the child returned by the owning app-server connection."""
        self.archive = archive
        self.thread = deepcopy(thread)
        self.call = call
        self.id = archive.native_id('codex', thread['id'])
        self.previous: dict | None = None
        self.excluded: set[tuple] | None = None
        self.lock = asyncio.Lock()
        created = thread.get('createdAt')
        header = {
            'version': 4, 'id': self.id, 'createdAt': created * 1000 if type(created) is int else 0,
            'isSeeded': False, 'graphtraj': {
                'version': 1, 'projectId': str(archive.root), 'agentId': agent, 'taskIds': [],
                'native': {'runtime': 'codex', 'sessionId': thread['id'],
                           'locator': 'thread/items/list', 'thread': {
                               key: deepcopy(thread[key]) for key in (
                                   'id', 'forkedFromId', 'ephemeral', 'historyMode',
                                   'source', 'cliVersion', 'createdAt', 'updatedAt',
                               ) if key in thread
                           }},
                'missing': [{'path': 'history', 'reason':
                    'Codex ThreadItem projection does not expose exact model ResponseItems.'}],
            },
        }
        if thread.get('forkedFromId'):
            header['parentSession'] = archive.native_id('codex', thread['forkedFromId'])
        if type(created) is not int:
            header['graphtraj']['missing'].append({
                'path': 'createdAt', 'reason': 'Native thread creation time is unavailable; zero is a placeholder.',
            })
        header = archive.native_header('codex', thread['id']) or header
        archive.map_session(header)

    async def collect(self) -> None:
        """Serialize terminal notices, explicit waits and the close boundary."""
        async with self.lock:
            await self._attempt()

    async def _attempt(self) -> None:
        """Retain a collection failure as evidence without changing checker verdicts."""
        try:
            await self._collect()
        except Exception as error:
            store = self.archive.store(self.id)
            if store is None:
                return
            events = _events(store)
            position = len(events)
            snapshot = sum(item['type'] == 'graphtraj/native' for item in events)
            event = retain_native('codex', {'collectionError': type(error).__name__,
                'code': getattr(error, 'code', None), 'message': str(error),
                'nativeError': getattr(error, 'native_error', None)}, session_id=self.thread['id'],
                locator=f'ordered-history:{snapshot}', seq=position, time=0)
            event['graphtraj']['missing'] = [{
                'path': 'history', 'reason': 'Native ordered history request failed; retry required.',
            }]
            store.checkpoint(event, source='ordered-history', position=position + 1)

    def transport(self, message: dict, *, outbound: bool = False) -> None:
        """Keep native function/permission evidence outside the ordered history.

        These ignorable records are observations of this connection, never model
        messages or evidence of delivery. Native emission fields remain intact.
        """
        store = self.archive.store(self.id)
        if store is None:
            return
        events = _events(store)
        index = len(events)
        event = retain_native('codex', message, session_id=self.thread['id'],
                              locator=f'transport:{index}', seq=index, time=0)
        event.update(type='codex/transport', ignorable=True, data={})
        event['graphtraj']['native']['record'] = deepcopy(message)
        event['graphtraj']['native']['direction'] = 'outbound-attempt' if outbound else 'inbound'
        event['graphtraj']['missing'] = [{'path': 'time', 'reason':
            'Transport observation has no item creation time; native emission fields are retained.'}]
        events.append(event)
        store.publish(events, source='transport', position=index + 1)

    async def _collect(self) -> None:
        """Save a complete ascending native snapshot, keeping pagination order."""
        store = self.archive.store(self.id)
        if store is None:
            self.excluded = None
            return
        pages = []
        cursor = None
        seen = set()
        while True:
            params = {'threadId': self.thread['id'], 'sortDirection': 'asc', 'limit': 100}
            if cursor is not None:
                params['cursor'] = cursor
            page = await self.call('thread/items/list', params)
            if not isinstance(page.get('data'), list):
                raise ValueError('Native ordered history page has no items.')
            pages.append(deepcopy(page))
            cursor = page.get('nextCursor')
            if cursor is None:
                break
            if not isinstance(cursor, str) or cursor in seen:
                raise ValueError('Native ordered history cursor did not advance.')
            seen.add(cursor)
        if not self.archive.backfill_history:
            if self.excluded is None:
                self.excluded = {(entry['turnId'], entry['item']['id'])
                                 for page in pages for entry in page['data']}
            for page in pages:
                page['data'] = [entry for entry in page['data']
                                if (entry['turnId'], entry['item']['id']) not in self.excluded]
        snapshot = {'method': 'thread/items/list', 'threadId': self.thread['id'], 'pages': pages,
                    'historyExcluded': not self.archive.backfill_history}
        if snapshot == self.previous and not store.pending():
            return
        events = _events(store)
        index = len(events)
        snapshot_index = sum(item['type'] == 'graphtraj/native' for item in events)
        event = retain_native('codex', snapshot, session_id=self.thread['id'],
                              locator=f'ordered-history:{snapshot_index}', seq=index, time=0)
        event['graphtraj']['missing'] = [{
            'path': 'time', 'reason': 'Snapshot has no creation time; item timestamps remain native.',
        }]
        events.append(event)
        store.publish(events, source='ordered-history', position=index + 1)
        self.previous = snapshot
