"""Claude's optional JSONL collection over its explicitly associated transcript.

Live input remains an observation until the native transcript establishes its
identity and order. Context changes are DSH surface replacements, not edits of
previously published records. No Task, Git, project discovery or home scan is
needed by this collector.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import json
from pathlib import Path
import time

from graphtraj.sessions.archive import JsonlSessionStore, SessionArchive, archive_path
from graphtraj.sessions.protocol import SURFACE_TYPES, append_stream_record
from graphtraj.runtimes.claude.collection import timestamp
from graphtraj.runtimes.claude.history import conversation, message_id, read_records


def _events(store: JsonlSessionStore) -> list[dict]:
    """Read the complete retained log through the archive's paged interface."""
    events, after, revision = [], -1, None
    while True:
        page = store.page(after, 1000, revision=revision)
        events.extend(page['events'])
        if not page['has_more']:
            return events
        after, revision = page['after'], page['revision']


def _surface(events: list[dict]) -> list[dict]:
    """Apply the same DSH replacements as the public messages projection."""
    surface = []
    for event in events:
        if event['type'] not in SURFACE_TYPES:
            continue
        op = event['surfaceOp']
        if op == 'append':
            surface.append(event)
        else:
            seqs = [item['seq'] for item in surface]
            start, end = seqs.index(op['startSeq']), seqs.index(op['endSeq'])
            surface[start:end + 1] = [event]
    return surface


class ClaudeJsonlCollector:
    """Collect one bound native Session under the supplied archive policy.

    ``bind`` must receive the path attested by the owned native hook. On resume,
    history disabled means the pre-prompt prefix is excluded from new collection;
    existing archives are retained. Explicit backfill later supplies that prefix.
    """

    def __init__(
        self,
        archive: SessionArchive | None,
        session: str,
        agent: str,
        cwd: Path,
        execution: str,
        *,
        provider: str = 'anthropic',
    ) -> None:
        """Capture policy without creating files when collection is disabled."""
        self.archive = archive
        self.session = session
        self.identity = 'claude:' + session
        self.agent = agent
        self.cwd = cwd
        self.execution = execution
        self.provider = provider
        self.path: Path | None = None
        self.excluded: set[str] = set()
        self.header: dict | None = None
        self.api_id: str | None = None
        self.streams: dict[str, dict] = {}
        self.position = 0

    def bind(self, path: Path) -> None:
        """Bind only the native hook's transcript and establish its history cut."""
        if self.path is not None and self.path != path:
            raise ValueError('Claude changed the associated transcript path.')
        self.path = path
        if self.archive is None or not self.archive.save_normalized_sessions:
            return
        try:
            records = read_records(path, self.session)
        except FileNotFoundError:
            records = []
        if not self.archive.backfill_history:
            self.excluded = {r['uuid'] for r in records if isinstance(r.get('uuid'), str)}
        destination = archive_path(self.archive.root, self.identity)
        if destination.exists():
            self.header = JsonlSessionStore(destination).header
        else:
            parents = {r['forkedFrom']['sessionId'] for r in records
                       if isinstance(r.get('forkedFrom'), dict) and r['forkedFrom'].get('sessionId')}
            if len(parents) > 1:
                raise ValueError('Claude fork ancestry is ambiguous.')
            self.header = {
                'version': 4, 'id': self.identity, 'createdAt': 0, 'isSeeded': bool(parents),
                'cwd': str(self.cwd), 'graphtraj': {
                    'version': 1, 'projectId': str(self.cwd), 'agentId': self.agent, 'taskIds': [],
                    'native': {'runtime': 'claude', 'sessionId': self.session,
                               'locator': str(path), 'source': 'managed'},
                    'missing': [{'path': 'createdAt', 'reason': 'Native Session creation time unavailable.'}],
                },
            }
            if parents:
                self.header['parentSession'] = 'claude:' + next(iter(parents))
        self.archive.map_session(self.header)
        self.collect()

    def _store(self) -> JsonlSessionStore | None:
        """Check the policy each time; never retain a store across disablement."""
        if self.archive is None or self.header is None:
            return None
        return self.archive.store(self.identity)

    def _event(self, locator: str, record: dict, kind: str = 'claude/observation') -> dict:
        """Retain source fields and native time without assigning receipt order."""
        when, missing = timestamp(record)
        event = {'type': kind, 'seq': 0, 'time': when, 'data': {},
                 'graphtraj': {'version': 1, 'native': {
                     'runtime': 'claude', 'sessionId': self.session,
                     'locator': locator, 'record': deepcopy(record)}}}
        if missing:
            event['graphtraj']['missing'] = missing
        if kind.startswith('claude/'):
            event['ignorable'] = True
        return event

    def accept(self, record: dict, position: int) -> None:
        """Checkpoint compact live content; a notification cannot publish order."""
        store = self._store()
        if store is None:
            return
        if record.get('session_id', self.session) != self.session:
            raise ValueError('Live record belongs to another Claude Session.')
        self.position = position
        event = record.get('event', {}) if record.get('type') == 'stream_event' else {}
        main = record.get('parent_tool_use_id') is None
        if main and event.get('type') == 'message_start':
            self.api_id = event.get('message', {}).get('id')
        api_id = self.api_id
        if main and api_id and record.get('type') == 'stream_event':
            key = 'stream:' + api_id
            if key not in self.streams:
                pending = next((p['event'] for p in store.pending()
                                if p['event']['graphtraj']['native']['locator'] == key), None)
                draft = pending or self._event(key, {}, 'assistant/attempt')
                draft.setdefault('data', {}).update(turn=0, step=0)
                draft['data'].setdefault('stream', [])
                draft['graphtraj'].setdefault('receivedAtMs', int(time.time() * 1000))
                self.streams[key] = draft
            draft = self.streams[key]
            delta = event.get('delta', {})
            plain = (event.get('type') == 'content_block_delta'
                    and set(record) <= {'type', 'event', 'session_id', 'parent_tool_use_id', 'uuid'}
                    and set(event) == {'type', 'index', 'delta'})
            if (plain and set(delta) in ({'type', 'text'}, {'type', 'thinking'})
                    and delta.get('type') in {'text_delta', 'thinking_delta'}):
                append_stream_record(draft['data']['stream'], {
                    'type': 'graphtraj/text-run', 'requestId': api_id, 'attemptId': self.execution,
                    'messageId': api_id, 'index': event['index'],
                    'blockType': 'text' if 'text' in delta else 'reasoning',
                    'text': delta.get('text', delta.get('thinking')),
                })
            elif plain and set(delta) == {'type', 'partial_json'} and delta['type'] == 'input_json_delta':
                stream = draft['data']['stream']
                chunk = {'type': 'claude/input-json-run', 'messageId': api_id,
                         'index': event['index'], 'partialJson': delta['partial_json']}
                if (stream and stream[-1].get('type') == chunk['type']
                        and stream[-1].get('messageId') == api_id and stream[-1].get('index') == event['index']):
                    stream[-1]['partialJson'] += chunk['partialJson']
                else:
                    append_stream_record(stream, chunk)
            else:
                append_stream_record(draft['data']['stream'], {'type': 'claude/native', 'record': record})
            if event.get('type') == 'message_stop':
                draft['data']['nativeMessageComplete'] = True
            store.checkpoint(draft, source=self.execution, position=position)
        elif (main and record.get('type') in {'assistant', 'user'} and isinstance(record.get('uuid'), str)
              and record.get('graphtraj_direction') != 'sent'):
            draft = self._event('message:' + record['uuid'], record)
            store.checkpoint(draft, source=self.execution, position=position)
        else:
            # Transport/permission/error facts are observations, not messages.
            # Publication retains their payload once in observations(), with a
            # small explicitly non-native marker in the log.
            draft = self._event(f'live:{self.execution}:{position}', record)
            store.checkpoint(draft, source=self.execution, position=position)
        if record.get('type') in {'assistant', 'user', 'result'}:
            self.collect()

    def _message(self, record: dict, store: JsonlSessionStore) -> dict:
        """Map one transcript UUID, preserving shared API IDs as provenance only."""
        role, uid = record['type'], message_id(record)
        native = record.get('message', {})
        if role == 'attachment':
            role, native = 'user', {'role': 'user', 'content': record['attachment']['prompt']}
        content = native.get('content', [])
        content = [{'type': 'text', 'text': content}] if isinstance(content, str) else deepcopy(content)
        for index, block in enumerate(content):
            if block.get('type') == 'thinking':
                block.update(type='reasoning', text=block['thinking'])
            elif block.get('type') == 'tool_use':
                block.update(type='tool-call', arguments=json.dumps(block.get('input', {}), ensure_ascii=False))
            elif block.get('type') == 'redacted_thinking':
                block.update(type='graphtraj/encrypted', value=block['data'],
                             nativePath=f'message.content[{index}].data')
            elif block.get('type') in {'image', 'document'}:
                source = block.get('source', {})
                if source.get('type') == 'base64':
                    attachment = store.put_attachment(base64.b64decode(source['data'], validate=True))
                    block.update(type='image' if block['type'] == 'image' else 'file', attachment=attachment)
                else:
                    block.update(type='claude/' + block['type'])
        message = {'id': uid, 'role': role, 'content': content,
                   'source': {'kind': 'user'} if role == 'user' else {
                       'kind': 'model', 'provider': self.provider, 'model': native.get('model', '<unknown>')}}
        event = self._event('message:' + uid, record, role + '/message')
        event['surfaceOp'] = 'append'
        event['data'] = message if role == 'user' else {'turn': 0, 'step': 0, 'message': message, 'stream': []}
        if role == 'assistant' and not native.get('model'):
            event['graphtraj'].setdefault('missing', []).append({'path': 'model', 'reason': 'Native model unavailable.'})
        return event

    def collect(self) -> None:
        """Publish the native chain, with explicit replay at native context changes."""
        store = self._store()
        if store is None or self.path is None:
            return
        try:
            records = read_records(self.path, self.session)
            desired = conversation(records)
        except (OSError, ValueError, KeyError, TypeError) as error:
            gap = self._event('history-gap', {})
            gap['graphtraj']['missing'] = [{'path': 'history', 'reason': str(error)}]
            store.checkpoint(gap, source='history-gap', position=store.position('history-gap') + 1)
            return
        old = _events(store)
        surface = _surface(old)
        originals = {e['graphtraj']['native']['record']['uuid']: e['graphtraj']['native']['record']
                     for e in old if e['type'] in SURFACE_TYPES}
        if any(r['uuid'] in originals and originals[r['uuid']] != r for r in desired):
            gap = self._event('history-gap', {})
            gap['graphtraj']['missing'] = [{'path': 'history', 'reason': 'A published native UUID changed content.'}]
            store.checkpoint(gap, source='history-gap', position=store.position('history-gap') + 1)
            return
        old_ids = [message_id(e['graphtraj']['native']['record']) for e in surface]
        if not self.archive.backfill_history:
            desired = [r for r in desired if r['uuid'] not in self.excluded or message_id(r) in old_ids]
        ids = [message_id(r) for r in desired]
        events = deepcopy(old)
        locators = {e['graphtraj']['native']['locator'] for e in events}
        same_prefix = ids[:len(old_ids)] == old_ids
        added = desired[len(old_ids):] if same_prefix else desired
        for index, record in enumerate(added):
            if (store.header['isSeeded'] and not record.get('forkedFrom')
                    and not any(e['type'] == 'session/end-seed' for e in events)):
                marker = self._event('fork-inheritance', {}, 'session/end-seed')
                marker.update(seq=len(events), data={'inherited': True})
                events.append(marker)
            event = self._message(record, store)
            if not same_prefix:
                # Native compaction/fork changes the current context. Retain
                # earlier log entries and replay the new native context through
                # DSH replacement; consumers need no Claude-specific sorting.
                event['graphtraj']['native']['locator'] += ':context:' + ids[-1]
                event['graphtraj']['contextReplay'] = True
                if index == 0 and surface:
                    event['surfaceOp'] = {'op': 'replace', 'startSeq': surface[0]['seq'], 'endSeq': surface[-1]['seq']}
                    event['sourceEventSeqs'] = [e['seq'] for e in surface]
            event['seq'] = len(events)
            events.append(event)
        if old_ids and not ids:
            gap = self._event('history-gap', {})
            gap['graphtraj']['missing'] = [{'path': 'history', 'reason': 'Native context removed every retained message.'}]
            store.checkpoint(gap, source='history-gap', position=store.position('history-gap') + 1)
            return

        # Keep off-chain records and non-message entries as explicitly labelled
        # transcript observations. They never enter the DSH message surface.
        for index, record in enumerate(records):
            uid = record.get('uuid')
            if uid in {r['uuid'] for r in desired} or uid in self.excluded and not self.archive.backfill_history:
                continue
            key = 'transcript:' + str(index)
            if key not in locators:
                event = self._event(key, record)
                event['seq'] = len(events)
                events.append(event)
        if store.header['isSeeded'] and not any(e['type'] == 'session/end-seed' for e in events):
            marker = self._event('fork-inheritance', {}, 'session/end-seed')
            marker.update(seq=len(events), data={'inherited': True})
            events.append(marker)

        available = set(ids)
        responses = {}
        for record in desired:
            if record['type'] == 'assistant' and record.get('message', {}).get('id'):
                responses.setdefault(record['message']['id'], []).append(record['uuid'])
        for pending in store.pending():
            draft = pending['event']
            key = draft['graphtraj']['native']['locator']
            if key in locators:
                continue
            target = None
            if key.startswith('stream:') and draft['data'].get('nativeMessageComplete'):
                target = responses.get(key.removeprefix('stream:'))
            elif key.startswith('message:') and key.removeprefix('message:') in available:
                # A context replay has a new DSH event locator; the original
                # live UUID still resolves to the same native transcript entry.
                target = [key.removeprefix('message:')]
            elif key == 'history-gap' and (not self.excluded or self.archive.backfill_history):
                target = ids
            elif key.startswith('live:'):
                target = []
            if target is not None and key not in {e['graphtraj']['native']['locator'] for e in events}:
                marker = self._event(key, {})
                marker.update(seq=len(events), data={'nativeMessageUuids': target, 'observationResolved': True})
                events.append(marker)
        store.publish(events, source='transcript', position=store.position('transcript') + 1)
        if self.excluded and not self.archive.backfill_history and not set(self.excluded) <= set(old_ids):
            gap = self._event('history-gap', {})
            gap['graphtraj']['missing'] = [{'path': 'history', 'reason': 'History backfill is disabled; native prefix was not collected.'}]
            store.checkpoint(gap, source='history-gap', position=store.position('history-gap') + 1)

    def close(self) -> None:
        """Collect final native history; unresolved interrupted text stays pending."""
        self.collect()
