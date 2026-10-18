"""Optional JSONL archives of Runtime-ordered DSH Session projections.

This module has no Project, Task, Runner or Runtime filesystem dependency.
Adapters supply an already ordered, complete retained native history, not RPC
notifications. Native chain traversal, branch selection and compaction mapping
belong to the Runtime adapter. Unresolved observations remain separate drafts.
The old SQLite collector is intentionally not switched by this new API.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import fcntl
import json
import os
from pathlib import Path
import tempfile
from typing import Iterator

from .protocol import SURFACE_TYPES, snapshot_event, validate_header, validate_session


def archive_path(root: Path, session_id: str) -> Path:
    """Locate JSONL under a caller-owned root without treating IDs as paths."""
    if not isinstance(session_id, str) or not session_id:
        raise ValueError('A nonempty Session ID is required.')
    return Path(root) / 'sessions' / sha256(session_id.encode()).hexdigest() / 'session.jsonl'


def _key(event: dict) -> tuple[str, str, str]:
    """Require stable source identity; text equality never identifies an event.

    A mapper emitting several events per native record gives each a distinct
    locator, stable across live/final/backfill mapping. Protocol-only markers
    use a locator for their source boundary and retain their non-native type.
    """
    native = event.get('graphtraj', {}).get('native', {})
    values = tuple(native.get(k) for k in ('runtime', 'sessionId', 'locator'))
    if not all(isinstance(value, str) and value for value in values):
        raise ValueError('Every archived event needs stable native provenance.')
    return values


def _encode(value: object) -> str:
    """Encode strict, compact UTF-8 JSON without coercing non-finite numbers."""
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def _replace(path: Path, content: bytes) -> None:
    """Publish a fully synchronized file atomically on supported POSIX hosts."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _relocate(event: dict, indices: dict[int, int], session_id: str) -> dict:
    """Translate existing DSH sequence references when verified history is added."""
    event = deepcopy(event)
    event['seq'] = indices[event['seq']]
    op = event.get('surfaceOp')
    if isinstance(op, dict):
        for key in ('startSeq', 'endSeq'):
            op[key] = indices[op[key]]
    if 'sourceEventSeqs' in event:
        event['sourceEventSeqs'] = [indices[n] for n in event['sourceEventSeqs']]
    data = event['data']
    if event['type'] == 'developer/message' and 'headerSeq' in data:
        data['headerSeq'] = indices[data['headerSeq']]
    if event['type'] == 'compaction/summary':
        data['shadowedSeqs'] = [indices[n] for n in data['shadowedSeqs']]
        data['shadowedRange'] = {k: indices[v] for k, v in data['shadowedRange'].items()}
    if event['type'] in {'graphtraj/score', 'graphtraj/logprobs', 'graphtraj/derived'}:
        data['target']['eventSeq'] = indices[data['target']['eventSeq']]
        for ref in data['source'].get('context', []):
            if ref['sessionId'] == session_id:
                ref['eventSeq'] = indices[ref['eventSeq']]
    return event


def _message_gap(path: str) -> bool:
    """Treat unclassified missing facts as gaps, except known non-message metadata.

    Missing paths use existing dotted or slash-separated field names. Optional
    time, usage and probability data do not determine message content, identity
    or order. Unknown paths stay conservative: their meaning cannot be inferred
    from a prose reason or silently discarded during reconstruction.
    """
    parts = path.replace('/', '.').replace('[', '.').strip('.').split('.')
    while parts and parts[0] in {'$', 'header', 'event', 'data', 'graphtraj', 'native',
                                'message', 'source'}:
        parts.pop(0)
    metadata = {
        'time', 'timestamp', 'createdAt', 'completedAt', 'emittedAtMs',
        'receivedAtMs', 'loggedAt', 'usage', 'logprobs', 'probabilities',
        'probabilitySemantics', 'score', 'scores', 'model', 'provider', 'tokenizer',
        'taskIds', 'rawModelStream', 'stream',
    }
    return not parts or parts[0] not in metadata


class JsonlSessionStore:
    """Read and update one portable JSONL Session with adjacent attachments.

    The first line holds the DSH header, source checkpoints and collection
    observations; remaining lines are final DSH events in native order. Atomic
    replacement commits these together. Readers see a single fixed snapshot.
    Pages carry a revision: callers must restart pagination after backfill.
    File access authorization belongs to the owning host, not header identities.
    """

    def __init__(self, path: Path) -> None:
        """Open an existing archive without creating directories or files."""
        self.path = Path(path)
        self._load()

    @classmethod
    def create(cls, path: Path, header: dict) -> JsonlSessionStore:
        """Create or reopen the same Session; never overwrite different metadata."""
        validate_header(header)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_suffix('.lock').open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not path.exists():
                metadata = {'archiveVersion': 1, 'header': header, 'revision': 0,
                            'sources': {}, 'pending': [], 'observations': []}
                _replace(path, (_encode(metadata) + '\n').encode())
            store = cls(path)
            if store.header != header:
                raise ValueError('Session header already exists with different metadata.')
        return store

    def _load(self) -> None:
        """Read one atomic snapshot and validate its protocol and identities."""
        with self.path.open(encoding='utf-8') as stream:
            self._metadata = json.loads(next(stream))
            self._events = [json.loads(line) for line in stream]
        if self._metadata.get('archiveVersion') != 1:
            raise ValueError('Unsupported Session archive version.')
        validate_header(self._metadata['header'])
        if self._events:
            validate_session(self.header, self._events)
        keys = [_key(event) for event in self._events]
        if len(keys) != len(set(keys)):
            raise ValueError('Duplicate native event identity.')

    @contextmanager
    def _update(self) -> Iterator[None]:
        """Serialize writers and reload their current committed snapshot."""
        with self.path.with_suffix('.lock').open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self._load()
            before = self._bytes()
            try:
                yield
                if self._bytes() != before:
                    self._metadata['revision'] += 1
                    # ponytail: O(history) per commit; add a derived index or
                    # segmented JSONL only after measured archive costs need it.
                    _replace(self.path, self._bytes())
            except BaseException:
                self._load()
                raise

    def _bytes(self) -> bytes:
        """Serialize exactly one current snapshot, without transport snapshots."""
        return ''.join(_encode(value) + '\n' for value in
                       [self._metadata, *self._events]).encode()

    @property
    def header(self) -> dict:
        """Return detached DSH metadata, including fork provenance."""
        return deepcopy(self._metadata['header'])

    def position(self, source: str) -> int:
        """Return the durable replay cursor, or -1 before this source is read."""
        return self._metadata['sources'].get(source, -1)

    def _fresh(self, source: str, position: int) -> bool:
        """Check a replay cursor; it is never used to sort messages."""
        if not isinstance(source, str) or not source or type(position) is not int or position < 0:
            raise ValueError('A source and nonnegative replay position are required.')
        return position > self.position(source)

    def publish(self, events: list[dict], *, source: str, position: int) -> bool:
        """Commit a complete Runtime-ordered retained projection and replay cursor.

        ``seq`` is contiguous DSH log order, supplied by the mapper from native
        record/chain order. Never pass arrival-ordered notifications here. New
        history may precede existing events, but cannot change their relative
        order, content, timestamps or associations. DSH references must already
        reflect the supplied complete projection. Repeated identities within a
        projection are errors; replay of the same projection is idempotent.
        Source positions identify replay progress, not native message order.
        Finalization may reuse the matching draft's last committed position.
        Event time is the mapper's declared native epoch-ms time; when absent,
        use the protocol's integer placeholder with graphtraj.missing explaining
        it. Keep creation/completion/send/write/receipt times under their actual
        source names in native evidence, never substitute receipt for creation.

        A final record moves its matching unfinished observation to
        ``observations()`` with an explicit final native identity, retaining the
        exact final event and the observed partial content separately. Final
        content and time are never inferred from receipt time.
        """
        events = deepcopy(events)
        validate_session(self.header, events)
        keys = [_key(event) for event in events]
        if len(keys) != len(set(keys)):
            raise ValueError('Duplicate native event identity.')
        with self._update():
            fresh = self._fresh(source, position)
            completing = position == self.position(source) and any(
                draft['source'] == source and _key(draft['event']) in keys
                for draft in self._metadata['pending']
            )
            if not fresh and not completing:
                return False
            by_key = dict(zip(keys, events))
            old_keys = [_key(event) for event in self._events]
            old_key_set = set(old_keys)
            if [key for key in keys if key in old_key_set] != old_keys:
                raise ValueError('Projection must retain existing native events in their original order.')
            indices = {old['seq']: by_key[_key(old)]['seq'] for old in self._events}
            for old in self._events:
                current = by_key[_key(old)]
                if _relocate(old, indices, self.header['id']) != current:
                    raise ValueError('Final native event identity was reused with different content.')
            remaining = []
            for draft in self._metadata['pending']:
                key = _key(draft['event'])
                if key in by_key:
                    final = by_key[key]
                    partial_data = draft['event']['data']
                    partial_message = partial_data.get('message') if isinstance(partial_data, dict) else None
                    final_data = final['data']
                    final_message = final_data.get('message') if isinstance(final_data, dict) else None
                    if partial_message and (
                        not final_message or partial_message['id'] != final_message['id']
                    ):
                        raise ValueError('Final record does not match the unfinished message identity.')
                    self._metadata['observations'].append({**draft, 'final': list(key)})
                else:
                    remaining.append(draft)
            validate_session(self.header, events)
            self._events = events
            self._metadata['pending'] = remaining
            self._metadata['sources'][source] = position
        return True

    def checkpoint(
        self,
        event: dict,
        *,
        source: str,
        position: int,
        expected_position: int | None = None,
    ) -> bool:
        """Persist an unresolved/partial event without assigning canonical order.

        The caller supplies a compact cumulative observation. Distinct native
        messages can be pending concurrently. Its seq is only a template until
        the Runtime publishes its ordered projection. On restart, read pending
        and position, then replay input after that durable source position.
        Sources without replay must checkpoint before acknowledging input.
        """
        event = snapshot_event(event)
        key = _key(event)
        with self._update():
            if expected_position is not None and self.position(source) != expected_position:
                raise ValueError('Source changed; resume from its durable checkpoint.')
            if not self._fresh(source, position):
                return False
            if any(_key(final) == key for final in self._events):
                # A late live notification cannot create a second final message.
                self._metadata['sources'][source] = position
                return False
            pending = self._metadata['pending']
            replacement = {'source': source, 'position': position, 'event': event}
            for index, draft in enumerate(pending):
                if _key(draft['event']) == key:
                    if draft['source'] != source:
                        raise ValueError('An unfinished native event already belongs to another source.')
                    pending[index] = replacement
                    break
            else:
                pending.append(replacement)
            self._metadata['sources'][source] = position
        return True

    def pending(self) -> list[dict]:
        """Return unfinished observations; list order is not native message order."""
        return deepcopy(self._metadata['pending'])

    def observations(self) -> list[dict]:
        """Return resolved collection evidence linked by final native identity.

        Observations are not canonical events, do not enter messages(), and
        their collection order cannot determine native history order. The
        observed template seq is retained as evidence, never a final reference.
        """
        return deepcopy(self._metadata['observations'])

    def resolve_observation(
        self,
        observation: tuple[str, str, str],
        final: tuple[str, str, str],
    ) -> bool:
        """Link exactly one pending observation to an already published native key.

        The Runtime adapter must supply the native terminal association. This
        operation neither infers matching content nor changes canonical order.
        Repeating the same association is a no-op; conflicting links refuse.
        Original partial content remains collection evidence outside messages.
        """
        for key in (observation, final):
            if len(key) != 3 or not all(isinstance(part, str) and part for part in key):
                raise ValueError('A native observation and final key are required.')
        with self._update():
            for resolved in self._metadata['observations']:
                if _key(resolved['event']) == observation:
                    if tuple(resolved['final']) != final:
                        raise ValueError('Observation already resolves to another native event.')
                    return False
            if not any(_key(event) == final for event in self._events):
                raise ValueError('The final native event has not been published.')
            for index, pending in enumerate(self._metadata['pending']):
                if _key(pending['event']) == observation:
                    self._metadata['observations'].append({**pending, 'final': list(final)})
                    del self._metadata['pending'][index]
                    return True
        return False

    def page(self, after: int = -1, limit: int = 200, *, revision: int | None = None) -> dict:
        """Read native-order events; refuse a cursor from a different snapshot."""
        if type(after) is not int or after < -1 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('Use after >= -1 and limit between 1 and 1000.')
        if revision is not None and revision != self._metadata['revision']:
            raise ValueError('Archive changed; restart pagination from its new snapshot.')
        events = deepcopy(self._events[after + 1:after + 1 + limit])
        return {'events': events, 'after': events[-1]['seq'] if events else after,
                'has_more': after + 1 + limit < len(self._events),
                'revision': self._metadata['revision'], 'pending': bool(self._metadata['pending'])}

    def messages(self) -> list[dict]:
        """Apply DSH surface operations, retaining the Runtime's message order.

        Header/event missing facts about content, history or correspondence
        refuse reconstruction, including unclassified paths. Known optional
        time/usage/probability and stream-detail metadata do not block messages;
        their missing explanations remain available through header/page reads.
        Unknown required events and opaque-native records refuse reconstruction;
        the caller must finish Runtime interpretation instead of guessing order.
        Native compaction/branch semantics must be mapped to DSH operations by
        the adapter. This does not invent a second causal sorting algorithm.
        """
        if self._metadata['pending']:
            raise ValueError('Unresolved observations remain; native history is incomplete.')
        validate_session(self.header, self._events, reconstruct=True)
        for value in [self.header, *self._events]:
            if any(_message_gap(item['path'])
                   for item in value.get('graphtraj', {}).get('missing', [])):
                raise ValueError('Missing native content, history or correspondence; messages are incomplete.')
        surface = []
        for event in self._events:
            if event['type'] not in SURFACE_TYPES:
                continue
            if event['surfaceOp'] == 'append':
                surface.append(event)
            else:
                op = event['surfaceOp']
                seqs = [item['seq'] for item in surface]
                start, end = seqs.index(op['startSeq']), seqs.index(op['endSeq'])
                surface[start:end + 1] = [event]
        return deepcopy([event['data'] if event['type'] == 'user/message'
                         else event['data']['message'] for event in surface])

    def put_attachment(self, content: bytes) -> dict:
        """Save original bytes before committing any referencing event."""
        if not isinstance(content, bytes):
            raise ValueError('Attachment content must be bytes.')
        digest = sha256(content).hexdigest()
        directory = self.path.parent / 'attachments'
        directory.mkdir(exist_ok=True)
        _replace(directory / digest, content)
        return {'storage': 'session', 'sha256': digest, 'size': len(content)}

    def attachment(self, digest: str) -> bytes:
        """Read and verify portable bytes, without consulting a native home."""
        if not isinstance(digest, str) or len(digest) != 64 or any(
            c not in '0123456789abcdef' for c in digest
        ):
            raise ValueError('Invalid attachment digest.')
        content = (self.path.parent / 'attachments' / digest).read_bytes()
        if sha256(content).hexdigest() != digest:
            raise ValueError('Attachment digest mismatch.')
        return content


class SessionArchive:
    """Optional collection policy for explicitly mapped Sessions only.

    The host owns durable Agent/native mappings and configuration. Pass its
    chosen values here; the archive never scans Runtime global directories.
    Disabling either flag does not delete archives or affect Runtime control.
    Adapters decide which records are historical using their native boundary,
    not a notification time. When history is disabled, provide a self-contained
    projection of records collected after activation and explicit missing facts.
    """

    def __init__(
        self,
        root: Path,
        *,
        save_normalized_sessions: bool = False,
        backfill_history: bool = False,
    ) -> None:
        """Set independent choices without opening or creating an archive."""
        if type(save_normalized_sessions) is not bool or type(backfill_history) is not bool:
            raise ValueError('Archive choices must be booleans.')
        self.root = Path(root)
        self.save_normalized_sessions = save_normalized_sessions
        self.backfill_history = backfill_history
        self._mapped: dict[str, dict] = {}

    def map_session(self, header: dict) -> None:
        """Register an already verified mapping supplied by the owning host.

        The optional GraphTraj header extension is not required for plain DSH
        sessions. This is an explicit source allowlist, not identity authority.
        """
        validate_header(header)
        existing = self._mapped.get(header['id'])
        if existing is not None and existing != header:
            raise ValueError('Session mapping cannot change its retained header.')
        self._mapped[header['id']] = deepcopy(header)

    def store(self, session_id: str, *, historical: bool = False) -> JsonlSessionStore | None:
        """Open collection only for mapped sources and enabled policy.

        Call on every collection operation so a changed choice takes effect.
        A returned low-level store is an explicit capability for that operation;
        do not retain it across policy changes. Read existing archives directly
        with JsonlSessionStore even when collection is disabled.
        """
        if session_id not in self._mapped:
            raise ValueError('Only explicitly mapped Sessions may be collected.')
        if not self.save_normalized_sessions or (historical and not self.backfill_history):
            return None
        return JsonlSessionStore.create(archive_path(self.root, session_id), self._mapped[session_id])

    def collect(
        self,
        session_id: str,
        events: list[dict],
        *,
        source: str,
        position: int,
        historical: bool = False,
    ) -> bool:
        """Publish mapped history under the current archive/backfill choices."""
        store = self.store(session_id, historical=historical)
        return False if store is None else store.publish(events, source=source, position=position)

    def checkpoint(
        self,
        session_id: str,
        event: dict,
        *,
        source: str,
        position: int,
    ) -> bool:
        """Save current partial content only while normalized saving is enabled."""
        store = self.store(session_id)
        return False if store is None else store.checkpoint(event, source=source, position=position)


class ArchiveStream:
    """Compact one native message between durable checkpoints.

    The adapter supplies fragment positions from a replayable source. For a
    non-replayable source call checkpoint before acknowledging each batch.
    Explicit checkpoints bound loss and avoid saving per-character snapshots.
    Finalization uses JsonlSessionStore.publish with the Runtime's ordered log;
    interruption leaves the durable partial event in pending, without guessing
    its canonical sequence or prematurely treating it as a final message.
    """

    def __init__(self, store: JsonlSessionStore, source: str, event: dict) -> None:
        """Start or resume a specific native message, preserving compact content."""
        self.store = store
        self.source = source
        self.event = snapshot_event(event)
        key = _key(event)
        for pending in store.pending():
            if _key(pending['event']) == key:
                if pending['source'] != source:
                    raise ValueError('An unfinished event belongs to another source.')
                self.event = pending['event']
        if self.event['type'] not in {'assistant/message', 'assistant/attempt'}:
            raise ValueError('A stream requires an assistant message or attempt.')
        self.position = store.position(source)
        self.committed_position = self.position

    def feed(self, record: dict, position: int, *, cumulative: bool = False) -> bool:
        """Retain one fragment without using its arrival time for message order."""
        from .protocol import append_stream_record

        self.store._fresh(self.source, position)
        if position <= self.position:
            return False
        if record.get('type') == 'graphtraj/text-run':
            message = self.event['data'].get('message')
            if message and record.get('messageId') != message['id']:
                raise ValueError('A stream fragment belongs to another message.')
        append_stream_record(self.event['data']['stream'], record, cumulative=cumulative)
        self.position = position
        return True

    def checkpoint(self) -> bool:
        """Save the compact partial event and cursor, rejecting stale writers."""
        changed = self.store.checkpoint(
            self.event, source=self.source, position=self.position,
            expected_position=self.committed_position,
        )
        self.committed_position = self.position
        return changed
