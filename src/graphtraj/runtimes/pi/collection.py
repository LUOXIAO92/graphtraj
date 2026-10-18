"""Pi native-order JSONL collection using the shared optional archive.

RPC observations have no entry ID. They remain pending until one exact native
message after their captured entry boundary identifies them. Ambiguous matches
remain explicit gaps, never content-based deletion or guessed ordering.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import uuid

from graphtraj.sessions.archive import ArchiveStream, JsonlSessionStore, SessionArchive, archive_path
from graphtraj.sessions.protocol import append_stream_record, retain_native
from .projection import native_time, project_messages


def archive_events(store: JsonlSessionStore) -> list[dict]:
    """Read a complete archive snapshot using its public pagination."""
    events = []
    after = -1
    while True:
        page = store.page(after=after, limit=1000)
        events.extend(page['events'])
        if not page['has_more']:
            return events
        after = page['after']


def archive_messages(store: JsonlSessionStore) -> list[dict]:
    """Reconstruct Pi messages offline from entries and the captured native leaf.

    Collection markers never determine message order; they retain which
    native branch/context boundary was selected at the last complete read.
    Generic DSH reconstruction refuses opaque Pi entries. This mapper applies
    Pi's native rules and refuses unresolved observations or missing ancestry.
    """
    if store.pending():
        raise ValueError('Pi observations still lack an unambiguous native entry.')
    events = archive_events(store)
    if any(item['path'] != 'timestamp' for event in events
           for item in event.get('graphtraj', {}).get('missing', [])):
        raise ValueError('Pi native content has explicitly missing attachments or fields.')
    projection = next((event['data'] for event in reversed(events) if event['type'] == 'pi/projection'), None)
    if projection is None:
        raise ValueError('Pi native projection boundary is unavailable.')
    return project_messages([event['data']['record'] for event in events
                             if event['type'] == 'graphtraj/native'], projection['leafId'])


class PiArchive:
    """Collect one explicitly mapped Session; never scan a Runtime directory."""

    def __init__(
        self,
        archive: SessionArchive,
        header: dict,
        *,
        agent: str,
        project: str,
        entries: list[dict],
        leaf_id: str | None,
        source: str | None = None,
        tasks: list[str] | None = None,
        attachment_root: Path | None = None,
    ) -> None:
        """Bind a verified native header and the activation's history boundary."""
        self.archive = archive
        self.session = header['id']
        self.key = 'pi:' + self.session
        self.entries = deepcopy(entries)
        self.leaf_id = leaf_id
        self.source = 'rpc:' + uuid.uuid4().hex
        self.position = 0
        self.stream: ArchiveStream | None = None
        self.buffered = 0
        self.snapshots = {}
        self.native_header = deepcopy(header)
        self.live = False
        self.activation_entries = {entry['id'] for entry in entries}
        self.tools = {}
        self.tool_buffers = {}
        self.attachment_root = attachment_root.resolve() if attachment_root is not None else None
        self.project = Path(project).resolve()
        self.exclude = set() if archive.backfill_history else {entry['id'] for entry in entries}
        created = native_time(header)
        canonical = {'version': 4, 'id': self.key, 'createdAt': created or 0,
                     'isSeeded': False,
                     'graphtraj': {'version': 1, 'projectId': project, 'agentId': agent,
                                  'taskIds': tasks or [], 'native': {'runtime': 'pi',
                                  'sessionId': self.session, 'locator': 'header',
                                  'record': deepcopy(header)},
                                  'missing': [] if created is not None else [
                                      {'path': 'timestamp', 'reason': 'Native header time unavailable.'}]}}
        if source is not None:
            canonical['graphtraj']['source'] = source
        if source in {'child', 'member'}:
            canonical['origin'] = 'subagent'
        # A fork contains copied native entries. Its header keeps parentSession
        # as native provenance; no unassociated parent file is opened here.
        path = archive_path(archive.root, self.key)
        if path.is_file():
            retained = JsonlSessionStore(path).header
            if retained.get('graphtraj', {}).get('native', {}).get('sessionId') != self.session:
                raise ValueError('Pi archive identity does not match its verified Session.')
            canonical = retained
        archive.map_session(canonical)
        self.sync(entries, leaf_id)

    def _events(self) -> list[dict]:
        """Read all canonical records through the archive's public pagination."""
        store = self.archive.store(self.key)
        if store is None:
            return []
        return archive_events(store)

    def _known_entries(self) -> list[str]:
        """Return native identities already published, excluding collection markers."""
        return [event['data']['record']['id'] for event in self._events()
                if event['type'] == 'graphtraj/native']

    def sync(
        self,
        entries: list[dict],
        leaf_id: str | None,
        *,
        header: dict | None = None,
        settled: bool = False,
    ) -> None:
        """Publish records strictly in native get_entries order, retaining IDs.

        tool_execution_end and other RPC notifications never supply canonical
        sequence numbers. A late native entry resolves an observation only when
        its entire final message and captured native boundary identify it.
        """
        self.entries = deepcopy(entries)
        self.leaf_id = leaf_id
        if header is not None:
            if header.get('id') != self.session:
                raise ValueError('Pi native header belongs to another Session.')
            self.native_header = deepcopy(header)
        store = self.archive.store(self.key)
        if store is None:
            return
        old = self._events()
        # Pi can defer its header until the first message. Keep later native
        # header evidence without rewriting the original mapping's timestamp.
        original_header = store.header['graphtraj']['native']['record']
        if self.native_header != original_header:
            entries = [self.native_header, *entries]
        old_by_id = {event['data']['record']['id']: event for event in old if event['type'] == 'graphtraj/native'}
        pending = store.pending()
        claims = {}
        for draft in pending:
            observation = draft['event'].get('piObservation', {})
            boundary = set(observation['knownEntries'])
            matches = [entry['id'] for entry in entries if entry['id'] not in boundary
                       and entry.get('type') == 'message'
                       and self._matches(observation, draft['event']['data']['stream'], entry['message'])]
            if len(matches) == 1:
                claims.setdefault(matches[0], []).append(draft)

        events = []
        for entry in entries:
            identity = entry['id']
            if identity in self.exclude and identity not in old_by_id:
                continue
            if identity in old_by_id:
                event = deepcopy(old_by_id[identity])
                if event['data']['record'] != entry:
                    raise ValueError('Pi reused a native entry ID with different content.')
                event['seq'] = len(events)
            else:
                if (self.live and not settled and identity not in self.activation_entries
                        and entry.get('message', {}).get('role') in {'assistant', 'toolResult'}
                        and len(claims.get(identity, [])) != 1):
                    # get_entries may run ahead of queued RPC notifications.
                    # Publish only the native prefix whose stream correspondence
                    # is known; later message_end resumes the same native order.
                    break
                locator = 'entry:' + identity
                if len(claims.get(identity, [])) == 1:
                    locator = claims[identity][0]['event']['graphtraj']['native']['locator']
                timestamp = native_time(entry)
                event = retain_native('pi', deepcopy(entry), session_id=self.session,
                                      locator=locator, seq=len(events), time=timestamp or 0)
                event['graphtraj']['native']['entryId'] = identity
                if timestamp is None:
                    event['graphtraj']['missing'] = [
                        {'path': 'timestamp', 'reason': 'Native entry time unavailable.'}]
                self._attachments(event, store)
            events.append(event)
        markers = [deepcopy(event) for event in old if event['type'] == 'pi/projection']
        projection = {'leafId': leaf_id, 'entryCount': len(self.entries),
                      'lastEntryId': self.entries[-1]['id'] if self.entries else None}
        if not markers or markers[-1]['data'] != projection:
            markers.append({'type': 'pi/projection', 'ignorable': True, 'seq': 0, 'time': 0,
                            'data': projection, 'graphtraj': {'version': 1,
                            'native': {'runtime': 'pi', 'sessionId': self.session,
                                       'locator': 'projection:' + str(len(markers)),
                                       'source': 'SessionManager entries/leafId'},
                            'missing': [{'path': 'timestamp', 'reason': 'Native projection has no timestamp.'}]}})
        for marker in markers:
            marker['seq'] = len(events)
            events.append(marker)
        if events == old:
            return
        # Native record count is a replay position, never the sorting key.
        # A late message_end can resolve a draft without a newly appended entry.
        position = max(store.position('native') + 1, len(entries))
        store.publish(events, source='native', position=position)

    def _attachments(self, event: dict, store: JsonlSessionStore) -> None:
        """Copy only files inside the host-authorized cwd, never private state."""
        content = event['data']['record'].get('message', {}).get('content', [])
        if not isinstance(content, list):
            return
        references = []
        for index, block in enumerate(content):
            if not isinstance(block, dict) or block.get('type') not in {'image', 'file'} or not isinstance(block.get('path'), str):
                continue
            location = f'/message/content/{index}/path'
            path = Path(block['path'])
            if not path.is_absolute():
                path = Path(self.native_header.get('cwd') or self.project) / path
            path = path.resolve()
            private = (self.archive.root.resolve(), self.project / '.graphtraj',
                       self.project / '.codex', Path.home() / '.codex')
            if (self.attachment_root is None or not path.is_relative_to(self.attachment_root)
                    or any(path.is_relative_to(root) for root in private)):
                reference = {'missing': {'path': location, 'reason': 'Outside the host-authorized attachment directory.'}}
            else:
                try:
                    reference = store.put_attachment(path.read_bytes())
                except OSError as error:
                    reference = {'missing': {'path': location, 'reason': type(error).__name__}}
            references.append({'nativePath': location, **reference})
            if 'missing' in reference:
                event['graphtraj'].setdefault('missing', []).append(reference['missing'])
        if references:
            event['graphtraj']['attachments'] = references

    @staticmethod
    def _matches(observation: dict, stream: list[dict], message: dict) -> bool:
        """Use exact final content, or an interrupted native attempt's prefix."""
        if 'toolCallId' in observation:
            return message.get('role') == 'toolResult' and message.get('toolCallId') == observation['toolCallId']
        if 'messageEnd' in observation:
            return observation['messageEnd'] == message
        start = observation.get('messageStart', {})
        if message.get('stopReason') not in {'aborted', 'error'} or not all(
            key in start and start[key] == message.get(key)
            for key in ('timestamp', 'role', 'provider', 'model')
        ):
            return False
        content = message.get('content', [])
        runs = {}
        for record in stream:
            if record.get('type') == 'graphtraj/text-run' and not record['messageId'].endswith(':tool'):
                key = record['index'], record['blockType']
                runs[key] = runs.get(key, '') + record['text']
        for (index, kind), text in runs.items():
            if index >= len(content):
                return False
            final = content[index].get('thinking' if kind == 'reasoning' else 'text')
            if not isinstance(final, str) or not final.startswith(text):
                return False
        return bool(runs)

    def _snapshot(self, message: dict, slot: str) -> None:
        """Keep intermediate unknown fields while omitting cumulative text."""
        if not isinstance(message, dict) or not message:
            return
        metadata = deepcopy(message)
        for block in metadata.get('content', []):
            if not isinstance(block, dict):
                continue
            for field in {'text': ('text',), 'thinking': ('thinking',),
                          'toolCall': ('arguments', 'partialJson')}.get(block.get('type'), ()):
                block.pop(field, None)
        previous = self.snapshots.get(slot, {})
        changes = {key: value for key, value in metadata.items() if previous.get(key) != value or key not in previous}
        removed = sorted(set(previous) - set(metadata))
        if changes or removed:
            self.position += 1
            self.stream.feed({'type': 'pi/snapshot-metadata', 'slot': slot,
                              'fields': changes, 'removed': removed}, self.position)
        self.snapshots[slot] = metadata

    def _tool_event(self, event: dict) -> None:
        """Retain tool progress by call ID without using completion order."""
        call = event['toolCallId']
        if not self.archive.save_normalized_sessions:
            return
        if call not in self.tools:
            locator = self.source + ':tool:' + call
            self.tools[call] = {
                'type': 'pi/tool-observation', 'seq': 0, 'time': native_time(event) or 0,
                'data': {'stream': []},
                'graphtraj': {'version': 1, 'native': {'runtime': 'pi',
                              'sessionId': self.session, 'locator': locator},
                              'missing': [{'path': 'nativeEntry', 'reason': 'Awaiting the native tool result.'}]},
                'piObservation': {'knownEntries': self._known_entries(),
                                  'toolCallId': call},
            }
            if native_time(event) is None:
                self.tools[call]['graphtraj']['missing'].append({
                    'path': 'timestamp', 'reason': 'Native tool event time unavailable; zero is a placeholder.'})
            self.tool_buffers[call] = 0
        draft = self.tools[call]
        stream = draft['data']['stream']
        metadata = deepcopy(event)
        result = metadata.get('partialResult', metadata.get('result', {}))
        for index, block in enumerate(result.get('content', []) if isinstance(result, dict) else []):
            if not isinstance(block, dict) or block.get('type') != 'text' or not isinstance(block.get('text'), str):
                continue
            text = block.pop('text')
            slot = f'tool:{call}:{index}'
            previous = self.snapshots.get(slot, '')
            if text.startswith(previous):
                delta = text[len(previous):]
            else:
                stream.append({'type': 'pi/tool-content-replaced', 'index': index})
                delta = text
            if delta:
                self.tool_buffers[call] += len(delta.encode())
                append_stream_record(stream, {'type': 'graphtraj/text-run', 'requestId': self.source,
                                             'attemptId': call, 'messageId': call, 'index': index,
                                             'blockType': 'text', 'text': delta})
            self.snapshots[slot] = text
        slot = 'tool-metadata:' + call
        if metadata != self.snapshots.get(slot):
            stream.append({'type': 'pi/tool-fields', 'fields': metadata})
            self.snapshots[slot] = metadata
            self.tool_buffers[call] += len(json.dumps(metadata).encode())
        self.position += 1
        if event['type'] != 'tool_execution_update' or self.tool_buffers[call] >= 65536:
            self.archive.store(self.key).checkpoint(draft, source=self.source + ':tool:' + call,
                                                     position=self.position)
            self.tool_buffers[call] = 0

    def receive(self, event: dict) -> None:
        """Merge assistant deltas; checkpoint semantic boundaries and 64 KiB runs."""
        if not self.archive.save_normalized_sessions:
            return
        store = self.stream.store if self.stream is not None else self.archive.store(self.key)
        kind = event.get('type')
        message = event.get('message', {})
        if kind == 'message_update' and self.stream is None:
            self.receive({'type': 'message_start', 'message': {'role': 'assistant', **message}})
        if kind in {'tool_execution_start', 'tool_execution_update', 'tool_execution_end'} and isinstance(event.get('toolCallId'), str):
            self._tool_event(event)
            return
        if kind == 'message_start' and message.get('role') == 'assistant':
            self.close()
            self.live = True
            self.position += 1
            locator = self.source + ':' + str(self.position)
            observed = native_time(message)
            draft = {'type': 'assistant/attempt', 'seq': 0, 'time': observed or 0,
                     'data': {'turn': 0, 'step': 0, 'stream': []},
                     'graphtraj': {'version': 1, 'native': {'runtime': 'pi',
                                   'sessionId': self.session, 'locator': locator},
                                   'missing': [{'path': 'nativeEntry',
                                                'reason': 'RPC has not supplied a persisted entry identity.'}]},
                     'piObservation': {'knownEntries': self._known_entries(),
                                       'messageStart': deepcopy(message),
                                       'startFields': {key: deepcopy(value) for key, value in event.items()
                                                       if key not in {'type', 'message'}}}}
            if observed is None:
                draft['graphtraj']['missing'].append({
                    'path': 'timestamp', 'reason': 'Native message time unavailable; zero is a placeholder.'})
            self.stream = ArchiveStream(store, self.source, draft)
            self.snapshots = {key: value for key, value in self.snapshots.items() if key.startswith('tool')}
            self.buffered = 0
            self.stream.feed({'type': 'pi/message-start'}, self.position)
            self.stream.checkpoint()
            return
        if self.stream is None:
            return
        self.position += 1
        if kind == 'message_update':
            update = deepcopy(event['assistantMessageEvent'])
            partial = update.pop('partial', None)
            part = update.get('type')
            if part in {'text_delta', 'thinking_delta', 'toolcall_delta'}:
                delta = update['delta']
                self.stream.feed({'type': 'graphtraj/text-run', 'requestId': self.source,
                                  'attemptId': self.source,
                                  'messageId': self.stream.event['graphtraj']['native']['locator']
                                               + (':tool' if part == 'toolcall_delta' else ''),
                                  'index': update['contentIndex'],
                                  'blockType': 'reasoning' if part == 'thinking_delta' else 'text',
                                  'text': delta}, self.position)
                self.buffered += len(delta.encode())
            else:
                self.stream.feed({'type': 'pi/assistant-event', 'event': update}, self.position)
            extras = {key: deepcopy(value) for key, value in event.items()
                      if key not in {'type', 'message', 'assistantMessageEvent'}}
            if part in {'text_delta', 'thinking_delta', 'toolcall_delta'}:
                fields = {key: value for key, value in update.items()
                          if key not in {'type', 'contentIndex', 'delta'}}
                if fields:
                    extras['assistantMessageEvent'] = fields
            if extras:
                self.position += 1
                self.stream.feed({'type': 'pi/update-fields', 'fields': extras}, self.position)
            self._snapshot(message, 'message')
            self._snapshot(partial, 'partial')
            if self.buffered < 65536 and part in {'text_delta', 'thinking_delta', 'toolcall_delta'}:
                return
        elif kind == 'message_end' and message.get('role') == 'assistant':
            self.stream.event['piObservation']['messageEnd'] = deepcopy(message)
            if message.get('stopReason') in {'aborted', 'error'}:
                self.stream.event['data']['interrupted'] = True
            self.stream.event['piObservation']['endFields'] = {
                key: deepcopy(value) for key, value in event.items() if key not in {'type', 'message'}}
            self.stream.feed({'type': 'pi/message-end'}, self.position)
            self.stream.checkpoint()
            self.stream = None
            self.sync(self.entries, self.leaf_id)
            return
        else:
            self.stream.feed({'type': 'pi/boundary', 'event': deepcopy(event)}, self.position)
        self.stream.checkpoint()
        self.buffered = 0

    def close(self) -> None:
        """Retain interrupted output as unresolved, without inventing a final entry."""
        if not self.archive.save_normalized_sessions:
            self.stream = None
            self.tool_buffers = {}
            return
        if self.stream is not None:
            self.stream.event['data']['interrupted'] = True
            self.position += 1
            self.stream.feed({'type': 'pi/transport-closed'}, self.position)
            self.stream.checkpoint()
            self.stream = None
        for call, buffered in self.tool_buffers.items():
            if buffered and self.archive.save_normalized_sessions:
                self.position += 1
                self.archive.store(self.key).checkpoint(self.tools[call], source=self.source + ':tool:' + call,
                                                       position=self.position)
                self.tool_buffers[call] = 0

    def messages(self) -> list[dict]:
        """Reconstruct native messages from the archive for its selected leaf.

        Generic DSH reconstruction correctly refuses opaque Pi entries. This
        Runtime mapper supplies Pi's own branch/compaction/context-edit rules.
        A partial archive or unresolved transport observation cannot claim a
        complete native message history.
        """
        store = self.archive.store(self.key)
        if store is None:
            raise ValueError('Pi normalized collection is disabled.')
        return archive_messages(store)
