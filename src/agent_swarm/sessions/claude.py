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

from agent_swarm.sessions.archive import JsonlSessionStore, SessionArchive, archive_path
from agent_swarm.sessions.protocol import (
    SESSION_FORMAT_VERSION, SURFACE_TYPES, append_stream_record, validate_extra_fields,
)
from datetime import datetime

def timestamp(record: dict) -> tuple[int, list[dict]]:
    """Read native ISO time; zero is an explicitly missing protocol placeholder."""
    value = record.get('timestamp')
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is not None:
                return int(parsed.timestamp() * 1000), []
        except ValueError:
            pass
    return 0, [{
        'path': 'time', 'reason': 'Native timestamp unavailable; zero is a protocol placeholder.'}]
from agent_swarm.sessions.claude_history import (
    NO_HISTORY_SIZE, conversation, message_id, read_records, read_split, read_with_torn_tail,
)


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
        cwd: Path,
        execution: str,
        *,
        provider: str = 'anthropic',
        resumed: bool | None = None,
        child_id: str | None = None,
        history_count: int | None = None,
        extra_fields: dict | None = None,
    ) -> None:
        """Capture policy without creating files when collection is disabled.

        ``extra_fields`` is written verbatim (after redaction) to a new header.
        """
        if extra_fields is not None:
            validate_extra_fields(extra_fields)
        self.extra_fields = deepcopy(extra_fields)
        self.archive = archive
        self.session = session
        self.identity = archive.native_id('claude', session, agent_id=child_id) if archive else 'claude:' + session
        self.child_id = child_id
        self.cwd = cwd
        self.execution = execution
        self.provider = provider
        self.resumed = resumed
        self.cut_known = True
        self.live_ids: set[str] = set()
        self.history_count = 0
        self.activation_count = history_count
        self.before_bind: list[tuple[dict, int, int]] = []
        self.path: Path | None = None
        self.excluded: set[str] = set()
        self.history_ids: set[str] = set()
        self.current_inputs: set[str] = set()
        self.cut_unread = False
        self.header: dict | None = None
        self.api_id: str | None = None
        self.streams: dict[str, dict] = {}
        self.deferred: tuple[dict, int] | None = None
        self.position = 0

    def history_size(self, path: Path) -> int | None:
        """Measure the history for ``bind`` while Claude's hook is still unanswered.

        Claude's reply cannot exist until the hook is answered, so this size
        stays below it however late the bind runs. Only ``stat`` runs here: the
        caller must keep answering hooks. Returns ``None`` when no cut applies,
        and ``NO_HISTORY_SIZE`` when the transcript cannot be measured.
        """
        if (self.archive is None or not self.archive.save_normalized_sessions
                or self.archive.backfill_history or self.resumed is False
                or self.activation_count is not None):
            return None
        try:
            return path.stat().st_size
        except OSError:
            return NO_HISTORY_SIZE

    def bind(
        self,
        path: Path,
        current_inputs: set[str] | None = None,
        history_size: int | None = None,
    ) -> None:
        """Bind only the native hook's transcript and establish its history cut.

        ``history_size`` comes from ``history_size()`` at the hook. Without it,
        everything in the transcript when this runs counts as history, including
        a torn final line, which is one record once Claude finishes writing it.
        """
        if self.path is not None and self.path != path:
            raise ValueError('Claude changed the associated transcript path.')
        self.path = path
        if self.archive is None or not self.archive.save_normalized_sessions:
            return
        history, torn = 0, False
        try:
            if history_size is None:
                records, torn = read_with_torn_tail(path, self.session)
                history = len(records) + torn
            elif history_size == NO_HISTORY_SIZE:
                self.cut_known = False
                _, records = read_split(path, self.session, 0)
            else:
                inside, later = read_split(path, self.session, history_size)
                records, history = inside + later, len(inside)
        except (OSError, ValueError):
            records = []
            self.cut_known = self.resumed is False
        if not self.archive.backfill_history:
            self.history_count = (self.activation_count if self.activation_count is not None
                                  else history if self.resumed is not False else 0)
            self.current_inputs = set(current_inputs or ())
            self.cut_unread = torn and self.history_count > len(records)
            self._apply_cut(records)
        destination = archive_path(self.archive.root, self.identity)
        if destination.exists():
            self.header = JsonlSessionStore(destination).header
        else:
            parents = {r['forkedFrom']['sessionId'] for r in records
                       if isinstance(r.get('forkedFrom'), dict) and r['forkedFrom'].get('sessionId')}
            if len(parents) > 1:
                raise ValueError('Claude fork ancestry is ambiguous.')
            self.header = {
                'version': SESSION_FORMAT_VERSION, 'id': self.identity, 'createdAt': 0,
                'isSeeded': bool(parents), 'cwd': str(self.cwd),
                'native': {'runtime': 'claude', 'sessionId': self.session,
                           'locator': str(path), 'source': 'managed'},
                'missing': [{'path': 'createdAt', 'reason': 'Native Session creation time unavailable.'}],
            }
            if self.extra_fields is not None:
                self.header['extra_fields'] = deepcopy(self.extra_fields)
            if parents:
                self.header['parentSession'] = self.archive.native_id('claude', next(iter(parents)))
        if self.child_id and not destination.exists():
            self.header['origin'] = 'subagent'
            self.header['native'].update(agentId=self.child_id, parentNativeSessionId=self.session)
        self.archive.map_session(self.header)
        self.collect()
        pending, self.before_bind = self.before_bind, []
        for record, position, received_at in pending:
            self.accept(record, position, received_at)

    def _apply_cut(self, records: list[dict]) -> None:
        """Fix this activation's history from its prefix of ``records``.

        ``history_ids`` holds the conversation the prefix held, and stays fixed:
        a later compaction takes messages off the chain without collecting them.
        A prefix with no readable conversation falls back to every UUID in it,
        which errs toward reporting history as left out. So does a child, whose
        entries are all sidechain, which ``conversation`` never returns.
        """
        prefix = records[:self.history_count]
        self.excluded = {r['uuid'] for r in prefix if isinstance(r.get('uuid'), str)} - self.current_inputs
        self.live_ids.update(r['uuid'] for r in records if r.get('uuid') in self.current_inputs)
        self.history_ids = set(self.excluded)
        if self.child_id is None:
            try:
                self.history_ids = {message_id(r) for r in conversation(prefix)} - self.current_inputs
            except (ValueError, KeyError, TypeError):
                pass

    def _store(self) -> JsonlSessionStore | None:
        """Check the policy each time; never retain a store across disablement."""
        if self.archive is None or self.header is None:
            return None
        return self.archive.store(self.identity)

    def _event(self, locator: str, record: dict, kind: str = 'claude/observation') -> dict:
        """Retain source fields and native time without assigning receipt order."""
        when, missing = timestamp(record)
        event = {'type': kind, 'seq': 0, 'time': when, 'data': {},
                 'native': {'runtime': 'claude', 'sessionId': self.session,
                            'locator': locator, 'record': deepcopy(record)}}
        if missing:
            event['missing'] = missing
        if kind.startswith('claude/'):
            event['ignorable'] = True
        return event

    def flush(self) -> None:
        """Checkpoint the stream draft whose fragments a backlog deferred."""
        deferred, self.deferred = self.deferred, None
        store = self._store() if deferred is not None else None
        if store is not None:
            store.checkpoint(deferred[0], source=self.execution, position=deferred[1])

    def accept_batch(self, records: list[tuple[dict, int]]) -> None:
        """Collect an already received batch with one archive policy/snapshot read.

        Keep every record and its position; only existing stream checkpoints
        are deferred. The capability is released before the next batch so
        configuration changes still take effect at each collection operation.
        """
        self.batch_store = (self._store(),)
        try:
            for index, (record, position) in enumerate(records):
                self.accept(record, position, defer=index < len(records) - 1)
            # Every live observation is checkpointed above. Resolve the native
            # history once after this batch, rather than rebuilding the same
            # long transcript for every message already waiting in the queue.
            if any(record.get('type') in {'assistant', 'user', 'result'} for record, _ in records):
                self.collect()
        finally:
            del self.batch_store

    def accept(self, record: dict, position: int, received_at_ms: int | None = None,
               *, defer: bool = False) -> None:
        """Checkpoint compact live content; a notification cannot publish order.

        ``defer`` marks a fragment with more input already received behind it:
        each checkpoint rewrites the whole archive, so consecutive fragments of
        one draft share the checkpoint of the last, or of ``flush``. Received
        input that is not yet checkpointed is lost on a crash either way.
        """
        store = self.batch_store[0] if hasattr(self, 'batch_store') else self._store()
        received_at_ms = received_at_ms if received_at_ms is not None else int(time.time() * 1000)
        if store is None:
            if self.archive is not None and self.archive.save_normalized_sessions and self.header is None:
                self.before_bind.append((deepcopy(record), position, received_at_ms))
            return
        if record.get('session_id', self.session) != self.session:
            raise ValueError('Live record belongs to another Claude Session.')
        self.position = position
        event = record.get('event', {}) if record.get('type') == 'stream_event' else {}
        main = record.get('parent_tool_use_id') is None
        if main and event.get('type') == 'message_start':
            self.api_id = event.get('message', {}).get('id')
        api_id = self.api_id
        streaming = main and bool(api_id) and record.get('type') == 'stream_event'
        if self.deferred is not None and not (
                defer and streaming and self.deferred[0] is self.streams.get('stream:' + str(api_id))):
            self.flush()
        if streaming:
            key = 'stream:' + api_id
            if key not in self.streams:
                pending = next((p['event'] for p in store.pending()
                                if p['event']['native']['locator'] == key), None)
                draft = pending or self._event(key, {}, 'assistant/attempt')
                draft.setdefault('data', {}).update(turn=0, step=0)
                draft['data'].setdefault('stream', [])
                draft.setdefault('receivedAtMs', received_at_ms)
                self.streams[key] = draft
            draft = self.streams[key]
            draft['lastReceivedAtMs'] = received_at_ms
            delta = event.get('delta', {})
            plain = (event.get('type') == 'content_block_delta'
                    and set(record) <= {'type', 'event', 'session_id', 'parent_tool_use_id', 'uuid'}
                    and set(event) == {'type', 'index', 'delta'})
            if (plain and set(delta) in ({'type', 'text'}, {'type', 'thinking'})
                    and delta.get('type') in {'text_delta', 'thinking_delta'}):
                append_stream_record(draft['data']['stream'], {
                    'type': 'text-run', 'requestId': api_id, 'attemptId': self.execution,
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
            if defer:
                self.deferred = (draft, position)
            else:
                store.checkpoint(draft, source=self.execution, position=position)
        elif (main and record.get('type') in {'assistant', 'user'} and isinstance(record.get('uuid'), str)
              and record.get('graphtraj_direction') != 'sent'):
            self.live_ids.add(record['uuid'])
            draft = self._event('message:' + record['uuid'], record)
            store.checkpoint(draft, source=self.execution, position=position)
        elif main and record.get('type') == 'stream_event':
            draft = self._event(f'unidentified-stream:{self.execution}:{position}', record)
            draft['missing'] = [{'path': 'correspondence', 'reason': 'Native message_start identity was not received.'}]
            store.checkpoint(draft, source=self.execution, position=position)
        else:
            # Transport/permission/error facts are observations, not messages.
            # Publication retains their payload once in observations(), with a
            # small explicitly non-native marker in the log.
            draft = self._event(f'live:{self.execution}:{position}', record)
            store.checkpoint(draft, source=self.execution, position=position)
        if record.get('type') in {'assistant', 'user', 'result'} and not hasattr(self, 'batch_store'):
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
                block.update(type='encrypted', value=block['data'],
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
            event.setdefault('missing', []).append({'path': 'model', 'reason': 'Native model unavailable.'})
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
            raw = ({'unparsedTranscriptTail': error.doc} if isinstance(error, json.JSONDecodeError) else
                   {'unparsedBytes': base64.b64encode(error.object).decode()} if isinstance(error, UnicodeDecodeError) else {})
            # A failed read is its own fact, apart from the history-gap of history
            # left out. A published locator hides later drafts under it, so each
            # resolved failure leaves the next one a new key.
            failures = sum(e['native']['locator'].startswith('read-gap:') for e in _events(store))
            gap = self._event(f'read-gap:{failures}', raw)
            gap['missing'] = [{'path': 'history', 'reason': str(error)}]
            store.checkpoint(gap, source='read-gap', position=store.position('read-gap') + 1)
            return
        if self.cut_unread and len(records) >= self.history_count:
            # The line torn at bind is whole now, and it belongs to the history.
            self.cut_unread = False
            self._apply_cut(records)
        old = _events(store)
        surface = _surface(old)
        originals = {e['native']['record']['uuid']: e['native']['record']
                     for e in old if e['type'] in SURFACE_TYPES}
        if any(r['uuid'] in originals and originals[r['uuid']] != r for r in desired):
            gap = self._event('history-gap', {})
            gap['missing'] = [{'path': 'history', 'reason': 'A published native UUID changed content.'}]
            store.checkpoint(gap, source='history-gap', position=store.position('history-gap') + 1)
            return
        old_ids = [message_id(e['native']['record']) for e in surface]
        if not self.archive.backfill_history:
            desired = [r for r in desired if r['uuid'] not in self.excluded or message_id(r) in old_ids]
            if not self.cut_known:
                desired = [r for r in desired if message_id(r) in self.live_ids or message_id(r) in old_ids]
        ids = [message_id(r) for r in desired]
        events = deepcopy(old)
        locators = {e['native']['locator'] for e in events}
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
                event['native']['locator'] += ':context:' + ids[-1]
                event['contextReplay'] = True
                if index == 0 and surface:
                    event['surfaceOp'] = {'op': 'replace', 'startSeq': surface[0]['seq'], 'endSeq': surface[-1]['seq']}
                    event['sourceEventSeqs'] = [e['seq'] for e in surface]
            event['seq'] = len(events)
            events.append(event)
        if old_ids and not ids:
            gap = self._event('history-gap', {})
            gap['missing'] = [{'path': 'history', 'reason': 'Native context removed every retained message.'}]
            store.checkpoint(gap, source='history-gap', position=store.position('history-gap') + 1)
            return

        # Keep off-chain records and non-message entries as explicitly labelled
        # transcript observations. They never enter the DSH message surface.
        for index, record in enumerate(records):
            uid = record.get('uuid')
            if not self.archive.backfill_history and (index < self.history_count
                    or not self.cut_known and uid not in self.live_ids):
                continue
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
        archived = {message_id(e['native']['record']) for e in old if e['type'] in SURFACE_TYPES}
        history_left_out = (not self.archive.backfill_history
                            and (not self.cut_known or not self.history_ids <= archived))
        retained_failure = None
        for pending in store.pending():
            draft = pending['event']
            key = draft['native']['locator']
            if key in locators:
                continue
            target = None
            if key.startswith('stream:') and draft['data'].get('nativeMessageComplete'):
                target = responses.get(key.removeprefix('stream:'))
            elif key.startswith('message:') and key.removeprefix('message:') in available:
                # A context replay has a new DSH event locator; the original
                # live UUID still resolves to the same native transcript entry.
                target = [key.removeprefix('message:')]
            elif key == 'history-gap' and (self.cut_known and not self.excluded or self.archive.backfill_history):
                target = ids
            elif key.startswith('read-gap:'):
                # This read parsed the whole file, so what the failure hid is
                # collected now, subject to the cut.
                target = ids
            elif (key == 'history-gap' and not history_left_out
                  and {'unparsedTranscriptTail', 'unparsedBytes'} & draft['native']['record'].keys()):
                # Earlier versions kept read failures under history-gap. Only
                # these hold read bytes; history left out has an empty record.
                # The marker takes a read-gap key to keep history-gap unpublished.
                failures = sum(e['native']['locator'].startswith('read-gap:') for e in events)
                key = retained_failure = f'read-gap:{failures}'
                target = ids
            elif key.startswith('live:'):
                target = []
            if target is not None and key not in {e['native']['locator'] for e in events}:
                marker = self._event(key, {})
                marker.update(seq=len(events), data={'nativeMessageUuids': target, 'observationResolved': True})
                events.append(marker)
        store.publish(events, source='transcript', position=store.position('transcript') + 1)
        if retained_failure is not None:
            store.resolve_observation(('claude', self.session, 'history-gap'),
                                      ('claude', self.session, retained_failure))
        if history_left_out:
            gap = self._event('history-gap', {})
            gap['missing'] = [{'path': 'history', 'reason': 'History backfill is disabled; native prefix was not collected.'}]
            store.checkpoint(gap, source='history-gap', position=store.position('history-gap') + 1)

    def close(self) -> None:
        """Collect final native history; unresolved interrupted text stays pending."""
        self.flush()
        self.collect()
