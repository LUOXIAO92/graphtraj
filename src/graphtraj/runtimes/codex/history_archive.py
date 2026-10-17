"""Retain ordered ephemeral app-server history without inventing model items."""

from copy import deepcopy
from typing import Awaitable, Callable

from graphtraj.sessions.archive import SessionArchive
from graphtraj.sessions.protocol import retain_native


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
        self.id = 'codex:' + thread['id']
        self.previous: dict | None = None
        self.excluded: set[tuple] | None = None
        created = thread.get('createdAt')
        header = {
            'version': 4, 'id': self.id, 'createdAt': created * 1000 if type(created) is int else 0,
            'isSeeded': False, 'graphtraj': {
                'version': 1, 'projectId': str(archive.root), 'agentId': agent, 'taskIds': [],
                'native': {'runtime': 'codex', 'sessionId': thread['id'],
                           'locator': 'thread/items/list', 'thread': deepcopy(thread)},
                'missing': [{'path': 'history', 'reason':
                    'Codex ThreadItem projection does not expose exact model ResponseItems.'}],
            },
        }
        if thread.get('forkedFromId'):
            header['parentSession'] = 'codex:' + thread['forkedFromId']
        archive.map_session(header)

    async def collect(self) -> None:
        """Retain a collection failure as evidence without changing checker verdicts."""
        try:
            await self._collect()
        except Exception as error:
            store = self.archive.store(self.id)
            if store is None:
                return
            position = 0
            after = -1
            while True:
                page = store.page(after)
                position += len(page['events'])
                if not page['has_more']:
                    break
                after = page['after']
            event = retain_native('codex', {'collectionError': type(error).__name__,
                'code': getattr(error, 'code', None)}, session_id=self.thread['id'],
                locator=f'ordered-history:{position}', seq=position, time=0)
            event['graphtraj']['missing'] = [{
                'path': 'history', 'reason': 'Native ordered history request failed; retry required.',
            }]
            store.checkpoint(event, source='ordered-history', position=position + 1)

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
        if snapshot == self.previous:
            return
        events = []
        after = -1
        while True:
            page = store.page(after)
            events.extend(page['events'])
            if not page['has_more']:
                break
            after = page['after']
        index = len(events)
        event = retain_native('codex', snapshot, session_id=self.thread['id'],
                              locator=f'ordered-history:{index}', seq=index, time=0)
        event['graphtraj']['missing'] = [{
            'path': 'time', 'reason': 'Snapshot has no creation time; item timestamps remain native.',
        }]
        events.append(event)
        store.publish(events, source='ordered-history', position=index + 1)
        self.previous = snapshot
