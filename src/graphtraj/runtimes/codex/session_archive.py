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
from graphtraj.sessions.storage import SessionStore, session_path


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


class CodexSessionArchive:
    """Incrementally archive one trusted native Session, independently of Tasks.

    The owner supplies Agent identity; neither transcript fields nor task names
    establish it. No Runtime Home search or historical import happens here.
    Reopening uses the original header and committed cursor, including after a
    source moves or a Worktree is deleted.
    """

    def __init__(
        self,
        state: Path,
        project_id: str,
        agent_id: str,
        session_id: str,
        task_ids: tuple[str, ...] = (),
    ) -> None:
        """Capture authorized associations without opening a native transcript."""
        self.path = session_path(state, 'codex:' + session_id)
        self.state = state
        self.project_id = project_id
        self.agent_id = agent_id
        self.session_id = session_id
        self.task_ids = task_ids

    def seed_fork(self, thread: dict) -> None:
        """Retain the history returned atomically by native thread/fork.

        This handles ephemeral checkers without substituting their parent's
        later history. An omitted turns field is an explicit unknown, never an
        invented empty inherited prefix.
        """
        if thread.get('id') != self.session_id or not thread.get('forkedFromId'):
            raise ValueError('Native fork did not identify its Session and parent.')
        now = time.time_ns() // 1000000
        seeded = isinstance(thread.get('turns'), list)
        missing = [{'path': 'createdAt', 'reason': 'Archive receipt time; native creation time unknown.'}]
        if not seeded:
            missing.append({'path': 'inheritedPrefix', 'reason': 'Native fork response omitted history.'})
        header = {
            'version': 4, 'id': 'codex:' + self.session_id, 'createdAt': now,
            'isSeeded': seeded, 'parentSession': 'codex:' + thread['forkedFromId'],
            'graphtraj': {'version': 1, 'projectId': self.project_id,
                         'agentId': self.agent_id, 'taskIds': list(self.task_ids),
                         'native': {'runtime': 'codex', 'sessionId': self.session_id,
                                    'locator': 'thread/fork'}, 'missing': missing},
        }
        with SessionStore.create(self.path, header) as store:
            event = retain_native('codex', thread, session_id=self.session_id,
                                  locator='thread/fork', seq=0, time=now)
            event['graphtraj']['missing'] = [{
                'path': 'rawModelStream',
                'reason': 'Unknown: public fork history is not the original model stream.',
            }]
            event['graphtraj']['attachments'] = _attachments(store, thread)
            events = [event]
            if seeded:
                events.append({'type': 'session/end-seed', 'seq': 1, 'time': now,
                               'data': {'inherited': True}})
            store.append_many(events, source='thread/fork', position=0)

    def notice(self, message: dict) -> None:
        """Archive an ephemeral Session's native notifications in arrival order.

        Only its owning connection calls this, before dispatching the notice.
        Notification usage remains native cumulative evidence, not additive cost.
        The transport cannot replay unreceived messages after a connection loss.
        """
        if message.get('params', {}).get('threadId') != self.session_id:
            return
        self._connection_record(message, 'received')

    def reply(self, message: dict) -> None:
        """Retain an owned native result or error before attempting delivery."""
        self._connection_record(message, 'outbound')

    def _connection_record(self, message: dict, direction: str) -> None:
        """Commit one connection record and its local ordered receipt coordinate."""
        with SessionStore(self.path) as store:
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

    def _copied_fork_cut(self, stream: BinaryIO) -> int | None:
        """Locate the first child-owned settings record after native copied history.

        Codex 0.161.0 record_initial_history appends this record after the copied
        prefix; inherited settings retain their original thread_id. Neither
        timestamps nor the parent's current length establish this boundary.
        """
        while True:
            start = stream.tell()
            line = stream.readline()
            if not line.endswith(b'\n'):
                return None
            record = json.loads(line)
            payload = record.get('payload', {})
            if (record.get('type') == 'event_msg'
                    and payload.get('type') == 'thread_settings_applied'
                    and payload.get('thread_id') == self.session_id):
                return start

    def _seed_reference(self, store: SessionStore, base: dict) -> None:
        """Copy the native exclusive prefix from an already owned project archive.

        Native history_base coordinates name the immutable source prefix, not
        whichever records the parent has acquired since the fork. No Runtime
        Home search or unrelated Session import is authorized by the reference.
        """
        if store.position('history-base') >= 0:
            return
        cutoff = base['end_ordinal_exclusive']
        with SessionStore(session_path(self.state, 'codex:' + base['thread_id']), readonly=True) as parent:
            owner = parent.header['graphtraj']
            if owner['projectId'] != self.project_id:
                raise ValueError('Native inherited history belongs to another project.')
            if parent.position('rollout') < base['end_byte_offset']:
                # A still-open Main may have flushed its terminal record after
                # Stop. Refresh only this already-owned source, never scan Home.
                source = owner['native'].get('sourcePath')
                if source:
                    CodexSessionArchive(self.state, self.project_id, owner['agentId'],
                                        owner['native']['sessionId']).collect(Path(source))
            events = []
            after = -1
            while len(events) < cutoff:
                page = parent.page(after)
                for event in page['events']:
                    if event['type'] == 'session/end-seed':
                        continue
                    record = native_record(event)
                    if record.get('ordinal') != len(events):
                        raise ValueError('Native inherited ordinal prefix is unavailable.')
                    event['seq'] = len(events)
                    for attachment in event.get('graphtraj', {}).get('attachments', []):
                        if attachment.get('storage') == 'session':
                            store.put_attachment(parent.attachment(attachment['sha256']))
                    events.append(event)
                    if len(events) == cutoff:
                        break
                if not page['has_more']:
                    break
                after = page['after']
            if len(events) != cutoff:
                raise ValueError('Native inherited prefix has not been collected in this project.')
        events.append({'type': 'session/end-seed', 'seq': len(events),
                       'time': store.header['createdAt'], 'data': {'inherited': True}})
        store.append_many(events, source='history-base', position=base['end_byte_offset'])

    def collect(self, rollout: Path) -> None:
        """Commit complete native records; retry unfinished input on the next call.

        Each call closes its database so shutdown and cleanup do not own archive
        lifetime. A malformed complete line fails visibly without skipping it.
        """
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
                cut = None
                if parent and base is None:
                    cut = self._copied_fork_cut(stream)
                    if cut is None:
                        # Native creation may still be writing its prefix. Keep
                        # the entire input replayable until the boundary exists.
                        return
                created = _timestamp(metadata.get('timestamp') or metadata_record.get('timestamp'))
                missing = [] if created is not None else [{
                    'path': 'createdAt', 'reason': 'Native creation time unknown; archive receipt time used.',
                }]
                header = {
                    'version': 4, 'id': 'codex:' + self.session_id,
                    'createdAt': created if created is not None else time.time_ns() // 1000000,
                    'isSeeded': bool(parent),
                    'graphtraj': {'version': 1, 'projectId': self.project_id,
                                 'agentId': self.agent_id, 'taskIds': list(self.task_ids),
                                 'native': {'runtime': 'codex', 'sessionId': self.session_id,
                                            'locator': 'byte:0', 'sourcePath': str(rollout.resolve())},
                                 'missing': missing},
                }
                if parent:
                    header['parentSession'] = 'codex:' + parent
                    header['graphtraj']['native']['inheritedEndByte'] = cut
                store = SessionStore.create(self.path, header)
            with store:
                header = store.header['graphtraj']
                if header['projectId'] != self.project_id or header['agentId'] != self.agent_id:
                    raise ValueError('Codex archive already belongs to another project or Agent.')
                if metadata.get('forked_from_id') and metadata.get('history_base'):
                    self._seed_reference(store, metadata['history_base'])
                position = store.position('rollout')
                if rollout.stat().st_size < position:
                    raise ValueError('Codex rollout was truncated before its committed cursor.')
                stream.seek(max(position, 0))
                while True:
                    start = stream.tell()
                    line = stream.readline()
                    if not line.endswith(b'\n'):
                        break
                    record = json.loads(line)
                    native_time = _timestamp(record.get('timestamp'))
                    event = retain_native(
                        'codex', record, session_id=self.session_id, locator=f'byte:{start}',
                        seq=store.next_seq,
                        time=native_time if native_time is not None else time.time_ns() // 1000000,
                    )
                    missing = [{'path': field, 'reason': 'Unknown: native record does not establish this mapping.'}
                               for field in ('rawModelStream', 'rawLogprobs', 'sampledLogprobs')]
                    if native_time is None:
                        missing.append({'path': 'time', 'reason': 'Native time unknown; receipt time used.'})
                    event['graphtraj']['missing'] = missing
                    event['graphtraj']['attachments'] = _attachments(store, record)
                    # Preserve cumulative usage as a native observation. It is not
                    # an additive DSH charge, and replay cannot count it twice.
                    events = [event]
                    if start == header['native'].get('inheritedEndByte'):
                        events.insert(0, {'type': 'session/end-seed', 'seq': event['seq'],
                                          'time': event['time'], 'data': {'inherited': True}})
                        event['seq'] += 1
                    store.append_many(events, source='rollout', position=stream.tell())
