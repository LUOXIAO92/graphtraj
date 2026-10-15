"""Copy an explicitly owned Codex rollout into the project's Session archive.

Rollouts are semantic native logs, not activity projections or transport delta
snapshots. Unknown records and ciphertext remain intact. Only complete lines
advance the durable byte cursor, in the same transaction as their events.
"""

import base64
import binascii
from datetime import datetime
import json
from pathlib import Path
import time
from typing import BinaryIO

from graphtraj.sessions.protocol import native_record, retain_native
from graphtraj.sessions.storage import SessionStore, StreamWriter, session_path


def _timestamp(value: object) -> int | None:
    """Read native ISO timestamps without inventing missing creation times."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return int(parsed.timestamp() * 1000) if parsed.tzinfo else None
    except ValueError:
        return None


def _attachments(store: SessionStore, value: object, path: str = '') -> list[dict]:
    """Retain inline native input bytes without following arbitrary file/URL references.

    A transcript is content, not permission to read additional private files.
    External references retain an explicit missing-byte reason instead.
    """
    found = []
    if isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_attachments(store, item, f'{path}/{index}'))
    elif isinstance(value, dict):
        kind = value.get('type')
        field = ({'input_image': 'image_url', 'input_file': 'file_data',
                  'local_image': 'path'}.get(kind) if isinstance(kind, str) else None)
        if field and isinstance(value.get(field), str):
            source = value[field]
            location = f'{path}/{field}'
            if source.startswith('data:') and ';base64,' in source:
                try:
                    content = base64.b64decode(source.split(';base64,', 1)[1], validate=True)
                    attachment = store.put_attachment(content)
                except (ValueError, binascii.Error):
                    attachment = {'missing': {'path': location, 'reason': 'Invalid inline base64 bytes.'}}
            else:
                attachment = {'missing': {'path': location,
                                         'reason': 'Native reference supplied without inline bytes; not fetched.'}}
            found.append({'nativePath': location, **attachment})
        for key, item in value.items():
            escaped = key.replace('~', '~0').replace('/', '~1')
            found.extend(_attachments(store, item, f'{path}/{escaped}'))
    return found


class HistoryUnavailable(ValueError):
    """The declared inherited prefix is not available in this project's archive."""


class CodexSessionArchive:
    """Incrementally archive one trusted native Session, independently of Tasks.

    The owner supplies Agent identity; neither transcript fields nor task names
    establish it. No Runtime Home search or historical import happens here.
    Reopening preserves owner identity and committed cursors, including after a
    source moves or a Worktree is deleted.
    """

    def __init__(
        self,
        state: Path,
        project_id: str,
        agent_id: str,
        session_id: str,
        task_ids: tuple[str, ...] = (),
        *,
        source_paths: dict[str, Path] | None = None,
    ) -> None:
        """Capture authorized associations without opening a native transcript."""
        self.path = session_path(state, 'codex:' + session_id)
        self.state = state
        self.project_id = project_id
        self.agent_id = agent_id
        self.session_id = session_id
        self.task_ids = task_ids
        self.source_paths = source_paths

    def seed_fork(self, thread: dict, *, history_excluded: bool = False) -> None:
        """Retain the history returned atomically by native thread/fork.

        This handles ephemeral checkers without substituting their parent's
        later history. An omitted turns field is an explicit unknown, never an
        invented empty inherited prefix. With excludeTurns, an empty returned
        list is unavailable history, not evidence of an empty inherited seed.
        """
        if thread.get('id') != self.session_id or not thread.get('forkedFromId'):
            raise ValueError('Native fork did not identify its Session and parent.')
        now = time.time_ns() // 1000000
        seeded = not history_excluded and isinstance(thread.get('turns'), list)
        missing = [{'path': 'createdAt', 'reason': 'Archive receipt time; native creation time unknown.'}]
        if not seeded:
            missing.append({'path': 'inheritedPrefix', 'reason': (
                'Unknown: excludeTurns requested; returned turns do not establish an inherited cut.'
                if history_excluded else 'Unknown: native fork response omitted history.'
            )})
        header = {
            'version': 4, 'id': 'codex:' + self.session_id, 'createdAt': now,
            'isSeeded': seeded, 'parentSession': 'codex:' + thread['forkedFromId'],
            'graphtraj': {'version': 1, 'projectId': self.project_id,
                         'agentId': self.agent_id, 'taskIds': list(self.task_ids),
                         'native': {'runtime': 'codex', 'sessionId': self.session_id,
                                    'locator': 'thread/fork'}, 'missing': missing},
        }
        with SessionStore.create(self.path, header) as store:
            events = []
            if seeded:
                for index, turn in enumerate(thread['turns']):
                    event = retain_native('codex', turn, session_id=self.session_id,
                                          locator=f'thread/fork/turns/{index}', seq=len(events), time=now)
                    event['graphtraj']['attachments'] = _attachments(store, turn)
                    events.append(event)
                events.append({'type': 'session/end-seed', 'seq': len(events), 'time': now,
                               'data': {'inherited': True}})
            # The response describes the newly created child. Only its returned
            # turns are inherited; the response envelope is a local observation.
            event = retain_native('codex', thread, session_id=self.session_id,
                                  locator='thread/fork', seq=len(events), time=now)
            event['graphtraj']['missing'] = [{
                'path': 'rawModelStream',
                'reason': 'Unknown: public fork history is not the original model stream.',
            }]
            event['graphtraj']['attachments'] = _attachments(store, thread)
            events.append(event)
            store.append_many(events, source='thread/fork', position=0)

    def notice(self, message: dict) -> None:
        """Archive an ephemeral Session's native notifications in arrival order.

        Only its owning connection calls this, before dispatching the notice.
        Notification usage remains native cumulative evidence, not additive cost.
        The transport cannot replay unreceived messages after a connection loss.
        """
        if message.get('params', {}).get('threadId') != self.session_id:
            return
        if not self._compact_delta(message):
            self._connection_record(message, 'received')

    def _compact_delta(self, message: dict) -> bool:
        """Checkpoint known plain text deltas as one run, preserving semantic boundaries.

        Unknown envelope/parameter fields stay native records. Each received
        delta is checkpointed because the ephemeral connection cannot replay it.
        This replaces per-delta finalized events with one recoverable draft.
        """
        method = message.get('method')
        kinds = {'item/agentMessage/delta': ('text', None),
                 'item/plan/delta': ('text', None),
                 'item/reasoning/textDelta': ('reasoning', 'contentIndex'),
                 'item/reasoning/summaryTextDelta': ('reasoning', 'summaryIndex')}
        if method not in kinds or set(message) != {'method', 'params'}:
            return False
        kind, index_key = kinds[method]
        params = message['params']
        keys = {'threadId', 'turnId', 'itemId', 'delta'} | ({index_key} if index_key else set())
        if set(params) != keys or any(not isinstance(params[key], str)
                                     for key in ('threadId', 'turnId', 'itemId', 'delta')):
            return False
        index = params[index_key] if index_key else 0
        if type(index) is not int or index < 0:
            return False
        template = {'method': method, 'params': {key: value for key, value in params.items() if key != 'delta'}}
        with SessionStore(self.path) as store:
            pending = store.pending()
            if pending and pending['event']['graphtraj']['native'].get('deltaTemplate') != template:
                StreamWriter(store, 'connection').finish()
                pending = None
            event = None
            if pending is None:
                event = {'type': 'assistant/attempt', 'seq': store.next_seq,
                         'time': time.time_ns() // 1000000,
                         'data': {'turn': 0, 'step': 0, 'stream': []},
                         'graphtraj': {'version': 1, 'direction': 'received', 'native': {
                             'runtime': 'codex', 'sessionId': self.session_id,
                             'locator': f"connection:{store.position('connection') + 1}",
                             'deltaTemplate': template}, 'missing': [
                                 {'path': 'turn/step', 'reason': 'Local output grouping; native numeric indices unknown.'},
                                 {'path': 'requestId/attemptId',
                                  'reason': 'Mapping IDs from turn/item; model request and attempt IDs unknown.'},
                                 {'path': 'time', 'reason': 'Native time unknown; receipt time used.'},
                                 {'path': 'rawModelStream', 'reason': 'Unknown: semantic native text, not raw model bytes.'},
                                 {'path': 'logprobs', 'reason': 'Unknown: native text delta supplied no probabilities.'},
                             ]}}
            writer = StreamWriter(store, 'connection', event)
            writer.feed({'type': 'graphtraj/text-run', 'requestId': params['turnId'],
                         'attemptId': params['itemId'], 'messageId': params['itemId'],
                         'index': index, 'blockType': kind, 'text': params['delta']},
                        store.position('connection') + 1)
            writer.checkpoint()
        return True

    def close(self) -> None:
        """Finalize a retained partial checker output when its native connection ends."""
        with SessionStore(self.path) as store:
            if store.pending() is not None:
                StreamWriter(store, 'connection').finish(interrupted=True)

    def reply(self, message: dict) -> None:
        """Retain an owned native result or error before attempting delivery."""
        self._connection_record(message, 'outbound')

    def _connection_record(self, message: dict, direction: str) -> None:
        """Commit one connection record and its local ordered receipt coordinate."""
        with SessionStore(self.path) as store:
            if store.pending() is not None:
                StreamWriter(store, 'connection').finish()
            position = store.position('connection') + 1
            event = retain_native('codex', message, session_id=self.session_id,
                                  locator=f'connection:{position}', seq=store.next_seq,
                                  time=time.time_ns() // 1000000)
            event['graphtraj']['direction'] = direction
            event['graphtraj']['missing'] = [
                {'path': 'time', 'reason': 'Native time unknown; receipt time used.'},
                {'path': 'rawModelStream', 'reason': 'Unknown: native notifications are not a raw model stream.'},
                {'path': 'logprobs', 'reason': 'Unknown unless explicitly present in the native notification.'},
            ]
            event['graphtraj']['attachments'] = _attachments(store, message)
            store.append_many([event], source='connection', position=position)

    def _seed_reference(self, store: SessionStore, base: dict) -> None:
        """Copy the native exclusive prefix from an already owned project archive.

        Native history_base coordinates name the immutable source prefix, not
        whichever records the parent has acquired since the fork. No Runtime
        Home search or unrelated Session import is authorized by the reference.
        """
        if store.position('history-base') >= base['end_byte_offset'] and store.next_seq:
            return
        cutoff = base['end_ordinal_exclusive']
        parent_path = session_path(self.state, 'codex:' + base['thread_id'])
        if not parent_path.is_file():
            raise HistoryUnavailable('Declared parent archive is unavailable in this project.')
        with SessionStore(parent_path, readonly=True) as parent:
            owner = parent.header['graphtraj']
            if owner['projectId'] != self.project_id:
                raise ValueError('Native inherited history belongs to another project.')
            if parent.position('rollout') < base['end_byte_offset']:
                # A still-open Main may have flushed its terminal record after
                # Stop. Refresh only this already-owned source, never scan Home.
                source = owner['native'].get('sourcePath')
                if source and (self.source_paths is None or source in self.source_paths):
                    CodexSessionArchive(self.state, self.project_id, owner['agentId'],
                                        owner['native']['sessionId'], source_paths=self.source_paths).collect(Path(source))
            events = []
            after = -1
            while len(events) < cutoff:
                page = parent.page(after)
                for event in page['events']:
                    if event['type'] == 'session/end-seed':
                        continue
                    record = native_record(event)
                    if type(record.get('ordinal')) is not int:
                        raise HistoryUnavailable('Native inherited ordinal prefix is unavailable.')
                    if record['ordinal'] >= cutoff:
                        continue
                    for attachment in event.get('graphtraj', {}).get('attachments', []):
                        if attachment.get('storage') == 'session':
                            store.put_attachment(parent.attachment(attachment['sha256']))
                    events.append(event)
                    if len(events) == cutoff:
                        break
                if not page['has_more']:
                    break
                after = page['after']
            events.sort(key=lambda event: native_record(event)['ordinal'])
            if [native_record(event)['ordinal'] for event in events] != list(range(cutoff)):
                raise HistoryUnavailable('Native inherited prefix has not been collected in this project.')
            for seq, event in enumerate(events):
                event['seq'] = seq
        if store.pending() is not None:
            inherited = []
            observations = []
            for index, event in enumerate(events):
                position = base['end_byte_offset'] if index == len(events) - 1 else index
                observations.append({'event': event, 'source': 'history-base', 'position': position})
                inherited.append(('history-base', position))
            store.stage_initial_observations(observations)
            store.finish_initial_collection(parent_session=store.header['parentSession'], inherited=inherited)
        else:
            events.append({'type': 'session/end-seed', 'seq': len(events),
                           'time': store.header['createdAt'], 'data': {'inherited': True}})
            store.append_many(events, source='history-base', position=base['end_byte_offset'])

    def _rollout_event(
        self,
        store: SessionStore,
        record: dict,
        start: int,
        seq: int,
    ) -> dict:
        """Preserve one source record and byte coordinate without inferring model data."""
        native_time = _timestamp(record.get('timestamp'))
        event = retain_native(
            'codex', record, session_id=self.session_id, locator=f'byte:{start}', seq=seq,
            time=native_time if native_time is not None else time.time_ns() // 1000000,
        )
        missing = [{'path': field, 'reason': 'Unknown: native record does not establish this mapping.'}
                   for field in ('rawModelStream', 'rawLogprobs', 'sampledLogprobs')]
        if native_time is None:
            missing.append({'path': 'time', 'reason': 'Native time unknown; receipt time used.'})
        event['graphtraj']['missing'] = missing
        event['graphtraj']['attachments'] = _attachments(store, record)
        return event

    def _promote_copied_prefix(self, store: SessionStore, parent: str) -> bool:
        """Resume promotion even if a prior process stopped after staging the cut."""
        pending = store.pending()
        if pending is None:
            return False
        observations = pending['event']['data']['observations']
        inherited = []
        for item in observations:
            event = item['event']
            record = native_record(event)
            payload = record.get('payload', {})
            if (record.get('type') == 'event_msg'
                    and payload.get('type') == 'thread_settings_applied'
                    and payload.get('thread_id') == self.session_id):
                store.finish_initial_collection(parent_session='codex:' + parent, inherited=inherited)
                return True
            if event['graphtraj']['native']['locator'] != 'byte:0':
                inherited.append((item['source'], item['position']))
        return False

    def _collect_copied_prefix(self, store: SessionStore, stream: BinaryIO, parent: str) -> bool:
        """Stage owned observations until native settings establish the inherited cut.

        The shared initial-collection draft retains complete records/cursors
        independently of the Runtime file. Promotion publishes only parent
        records before the marker; child metadata/settings remain local.
        """
        if self._promote_copied_prefix(store, parent):
            return True
        stream.seek(max(store.position('rollout'), 0))
        observations = []
        while True:
            start = stream.tell()
            line = stream.readline()
            if not line.endswith(b'\n'):
                store.stage_initial_observations(observations)
                return False
            record = json.loads(line)
            event = self._rollout_event(store, record, start, 0)
            observations.append({'event': event, 'source': 'rollout', 'position': stream.tell()})
            if self.source_paths is None or len(observations) >= 256:
                store.stage_initial_observations(observations)
                observations.clear()
            payload = record.get('payload', {})
            if (record.get('type') == 'event_msg'
                    and payload.get('type') == 'thread_settings_applied'
                    and payload.get('thread_id') == self.session_id):
                store.stage_initial_observations(observations)
                return self._promote_copied_prefix(store, parent)

    def collect(self, rollout: Path) -> None:
        """Commit complete native records; retry unfinished input on the next call.

        Each call closes its database so shutdown and cleanup do not own archive
        lifetime. A malformed complete line fails visibly without skipping it.
        """
        provenance = str(rollout)
        if self.source_paths is not None:
            captured = self.source_paths.get(provenance)
            if captured is None:
                raise FileNotFoundError('Native source is not in the captured project set.')
            rollout = captured
        else:
            provenance = str(rollout.resolve())
        with rollout.open('rb') as stream:
            first = stream.readline()
            if not first.endswith(b'\n'):
                return
            metadata_record = json.loads(first)
            metadata = metadata_record.get('payload', {})
            if metadata_record.get('type') != 'session_meta' or metadata.get('id') != self.session_id:
                raise ValueError('Codex archive source does not match its owned Session.')
            if self.path.exists():
                store = SessionStore(self.path)
            else:
                parent = metadata.get('forked_from_id')
                base = metadata.get('history_base')
                created = _timestamp(metadata.get('timestamp') or metadata_record.get('timestamp'))
                missing = [] if created is not None else [{
                    'path': 'createdAt', 'reason': 'Native creation time unknown; archive receipt time used.',
                }]
                header = {
                    'version': 4, 'id': 'codex:' + self.session_id,
                    'createdAt': created if created is not None else time.time_ns() // 1000000,
                    'isSeeded': bool(parent and base),
                    'graphtraj': {'version': 1, 'projectId': self.project_id,
                                 'agentId': self.agent_id, 'taskIds': list(self.task_ids),
                                 'native': {'runtime': 'codex', 'sessionId': self.session_id,
                                            'locator': 'byte:0', 'sourcePath': provenance},
                                 'missing': missing},
                }
                if parent and base:
                    header['parentSession'] = 'codex:' + parent
                store = SessionStore.create(self.path, header)
            with store:
                header = store.header['graphtraj']
                if header['projectId'] != self.project_id or header['agentId'] != self.agent_id:
                    raise ValueError('Codex archive already belongs to another project or Agent.')
                if metadata.get('forked_from_id') and metadata.get('history_base'):
                    try:
                        self._seed_reference(store, metadata['history_base'])
                    except HistoryUnavailable as error:
                        if self.source_paths is None or store.next_seq:
                            raise
                        stream.seek(max(0, store.position('rollout')))
                        observations = []
                        while True:
                            start = stream.tell()
                            line = stream.readline()
                            if not line.endswith(b'\n'):
                                break
                            event = self._rollout_event(store, json.loads(line), start, 0)
                            event['graphtraj']['missing'].append({'path': 'history_base', 'reason': str(error)})
                            observations.append({'event': event, 'source': 'rollout', 'position': stream.tell()})
                            if len(observations) >= 256:
                                store.stage_initial_observations(observations)
                                observations.clear()
                        store.stage_initial_observations(observations)
                        return
                position = store.position('rollout')
                if rollout.stat().st_size < position:
                    raise ValueError('Codex rollout was truncated before its committed cursor.')
                if metadata.get('forked_from_id') and not metadata.get('history_base') and not store.next_seq:
                    if not self._collect_copied_prefix(store, stream, metadata['forked_from_id']):
                        return
                    position = store.position('rollout')
                stream.seek(max(position, 0))
                while True:
                    start = stream.tell()
                    line = stream.readline()
                    if not line.endswith(b'\n'):
                        break
                    record = json.loads(line)
                    event = self._rollout_event(store, record, start, store.next_seq)
                    # Native cumulative usage is evidence, never an additive charge.
                    store.append_many([event], source='rollout', position=stream.tell())
