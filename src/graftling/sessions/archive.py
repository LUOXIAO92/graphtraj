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
import operator
import os
from pathlib import Path
import tempfile
import threading
from typing import Callable, Iterator

from graftling.config import read_config

from .protocol import (
    LEGACY_FORMAT_VERSION, SURFACE_TYPES, snapshot_event, upgrade_event, upgrade_header,
    validate_extra_fields, validate_header, validate_session,
)

EventFields = Callable[[dict], 'dict | None']


def redact(value: object) -> object:
    """Redact credentials; loaded late so ``import graftling`` starts no Runtime package."""
    from graftling.codex.diagnostics import redact as redact_native

    return redact_native(value)


def native_session_files(root: Path) -> list[Path]:
    """Return the native Session files the Agents under data root ``root`` recorded.

    Each ``native/<agent>/session.yml`` may name one file. It counts only when
    the record names a Session and the file is an existing ``.jsonl`` at an
    absolute path. A record that cannot be read or has another shape is
    skipped. Nothing is searched for in a Runtime's home, so the result is safe
    to use as exact read grants. Returns resolved paths in sorted order.
    """
    import yaml

    files = set()
    for path in root.glob('native/*/session.yml'):
        try:
            record = yaml.safe_load(path.read_text(encoding='utf-8'))
            if not isinstance(record, dict) or not record.get('session'):
                continue
            activity = record.get('activity')
            source = record.get('rollout_path') or (activity.get('trace_file') if isinstance(activity, dict) else None)
            if isinstance(source, str):
                native = Path(source)
                if native.is_absolute() and native.suffix == '.jsonl' and native.is_file():
                    files.add(native.resolve())
        except (OSError, ValueError, yaml.YAMLError):
            continue
    return sorted(files)


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
    native = event.get('native', {})
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


class _Same:
    """A list's items, equal to another only if it holds the very same objects."""

    def __init__(self, items: list) -> None:
        self.items = list(items)

    def __eq__(self, other: object) -> bool:
        return (isinstance(other, _Same) and len(self.items) == len(other.items)
                and all(map(operator.is_, self.items, other.items)))


def _identity(status: os.stat_result) -> tuple:
    """Identify one version of a file: replacement or rewriting changes it."""
    return status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns


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
    if event['type'] == 'history':
        data['eventSeqs'] = [indices[n] for n in data['eventSeqs']]
    if event['type'] == 'developer/message' and 'headerSeq' in data:
        data['headerSeq'] = indices[data['headerSeq']]
    if event['type'] == 'compaction/summary':
        data['shadowedSeqs'] = [indices[n] for n in data['shadowedSeqs']]
        data['shadowedRange'] = {k: indices[v] for k, v in data['shadowedRange'].items()}
    if event['type'] in {'score', 'logprobs', 'derived'}:
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


def redact_extra_fields(value: dict) -> dict:
    """Validate an ``extra_fields`` container and apply credential redaction to it.

    Native content stays lossless; caller-attached namespaces are redacted
    like diagnostics: credential-named keys and recognizable secrets.
    """
    validate_extra_fields(value)
    return redact(deepcopy(value))


def _redacted(value: dict) -> dict:
    """Return a header or event whose ``extra_fields`` are redacted, if present."""
    if 'extra_fields' not in value:
        return value
    return {**value, 'extra_fields': redact_extra_fields(value['extra_fields'])}


def _upgrade(metadata: dict, events: list[dict]) -> tuple[dict, list[dict]]:
    """Read a version 4 snapshot in v5 form; the next commit rewrites the whole file.

    Drafts and resolved observations carry event templates and are upgraded
    with the log. Retained legacy exports remain exact old evidence.
    """
    if metadata.get('header', {}).get('version') != LEGACY_FORMAT_VERSION:
        return metadata, events
    metadata = deepcopy(metadata)
    metadata['header'] = upgrade_header(metadata['header'])
    for draft in [*metadata.get('pending', []), *metadata.get('observations', [])]:
        draft['event'] = upgrade_event(draft['event'])
    return metadata, [upgrade_event(event) for event in events]


def read_session(path: Path) -> dict:
    """Read one archive as ``{'header', 'events'}`` in v5 form, for v4 or v5 files.

    Events are the committed log in native order. Unfinished drafts and
    collection observations are not part of it; use ``JsonlSessionStore``.
    """
    store = JsonlSessionStore(path)
    return {'header': store.header, 'events': deepcopy(store._events)}


class JsonlSessionStore:
    """Read and update one portable JSONL Session with adjacent attachments.

    The first line holds the DSH header, source checkpoints and collection
    observations; remaining lines are final DSH events in native order. Atomic
    replacement commits these together. Readers see a single fixed snapshot.
    Pages carry a revision: callers must restart pagination after backfill.
    File access authorization belongs to the owning host, not header identities.
    """

    def __init__(self, path: Path, *, event_fields: EventFields | None = None) -> None:
        """Open an existing archive without creating directories or files.

        ``event_fields`` is a programmatic extension: for each event about to
        be written it receives a detached copy and returns an ``extra_fields``
        container (merged by namespace) or ``None``. Published events keep the
        fields they were first written with.
        """
        self.path = Path(path)
        self.event_fields = event_fields
        # The file this snapshot was read from or written as, kept open so
        # its identity cannot be reused, and its (inode, size, mtime) then.
        self._held = None
        self._identity: tuple | None = None
        self._depth = 0
        self._observation_lines: dict[int, tuple[dict, str]] = {}
        self._load()

    @classmethod
    def create(cls, path: Path, header: dict, *, event_fields: EventFields | None = None) -> JsonlSessionStore:
        """Create or reopen the same Session; never overwrite different metadata.

        A version 4 archive reopens in v5 form; its first change rewrites the
        whole file as v5, so one file never mixes versions.
        """
        validate_header(header)
        header = _redacted(header)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_suffix('.lock').open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not path.exists():
                metadata = {'archiveVersion': 1, 'header': header, 'revision': 0,
                            'sources': {}, 'pending': [], 'observations': []}
                _replace(path, (_encode(metadata) + '\n').encode())
            store = cls(path, event_fields=event_fields)
            if store.header != header:
                raise ValueError('Session header already exists with different metadata.')
        return store

    def _load(self) -> None:
        """Read one atomic snapshot and validate its protocol and identities."""
        stream = self.path.open('rb')
        try:
            lines = stream.read().decode('utf-8').split('\n')
            identity = _identity(os.fstat(stream.fileno()))
        except BaseException:
            stream.close()
            raise
        self._hold(stream, identity)
        if lines[-1] == '':
            lines.pop()
        metadata = json.loads(lines[0])
        lines = lines[1:]
        events = [json.loads(line) for line in lines]
        self._metadata, self._events = _upgrade(metadata, events)
        # Each event's committed line; an upgraded log is written anew.
        self._lines = lines if self._events is events else [_encode(event) for event in self._events]
        if self._metadata.get('archiveVersion') != 1:
            raise ValueError('Unsupported Session archive version.')
        validate_header(self._metadata['header'])
        if self._events:
            validate_session(self.header, self._events)
        keys = [_key(event) for event in self._events]
        if len(keys) != len(set(keys)):
            raise ValueError('Duplicate native event identity.')
        self._keys = keys

    def __del__(self) -> None:
        held = getattr(self, '_held', None)
        if held is not None:
            held.close()

    def _hold(self, stream, identity: tuple) -> None:
        """Keep the file the snapshot matches open, so its inode is not reused."""
        if self._held is not None:
            self._held.close()
        self._held, self._identity = stream, identity

    def _current(self) -> bool:
        """Whether the archive file is still exactly the one this snapshot matches.

        Writers replace the file atomically; any replacement or in-place change
        alters the inode, size or modification time.
        """
        try:
            return self._identity is not None and _identity(os.stat(self.path)) == self._identity
        except FileNotFoundError:
            return False

    def refresh(self) -> None:
        """Reload only when another writer changed the file since this snapshot."""
        if not self._current():
            self._load()

    @contextmanager
    def _update(self) -> Iterator[None]:
        """Serialize writers and reload their current committed snapshot.

        The snapshot is reused while the file is unchanged, and unchanged
        events keep their committed lines, so a commit parses and encodes only
        what changed (468). The file is still written whole: the archive is one
        atomic snapshot. Inside ``batch`` the outermost update commits.
        """
        if self._depth:
            yield
            return
        with self.path.with_suffix('.lock').open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.refresh()
            metadata, events, lines = self._metadata_state(), self._events, self._lines
            try:
                yield
                if self._metadata_state() != metadata or self._events is not events and self._lines != lines:
                    self._metadata['revision'] += 1
                    _replace(self.path, self._bytes())
                    stream = self.path.open('rb')
                    self._hold(stream, _identity(os.fstat(stream.fileno())))
            except BaseException:
                self._load()
                raise

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Apply several updates under one lock and commit them as one write.

        An error in any of them leaves the archive as it was before the batch.
        """
        with self._update():
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1

    def _bytes(self) -> bytes:
        """Serialize exactly one current snapshot, without transport snapshots."""
        return ''.join(line + '\n' for line in [self._metadata_line(), *self._lines]).encode()

    def _metadata_state(self) -> tuple:
        """Compare the first line's content: observations by identity, the rest encoded."""
        rest = {name: value for name, value in self._metadata.items() if name != 'observations'}
        return _encode(rest), _Same(self._metadata['observations'])

    def _metadata_line(self) -> str:
        """Encode the first line exactly as ``_encode`` does, reusing observations.

        Resolved observations only accumulate and are never changed in place,
        so each keeps the encoding it was first given (468).
        """
        encoded = {}
        parts = []
        for name, value in self._metadata.items():
            if name == 'observations':
                for item in value:
                    known = self._observation_lines.get(id(item))
                    encoded[id(item)] = known if known is not None and known[0] is item else (item, _encode(item))
                value = '[' + ','.join(encoded[id(item)][1] for item in value) + ']'
            else:
                value = _encode(value)
            parts.append(_encode(name) + ':' + value)
        self._observation_lines = encoded
        return '{' + ','.join(parts) + '}'

    @property
    def header(self) -> dict:
        """Return detached DSH metadata, including fork provenance."""
        return deepcopy(self._metadata['header'])

    @property
    def revision(self) -> int:
        """Return the snapshot revision that ``page`` reports."""
        return self._metadata['revision']

    def events(self) -> list[dict]:
        """Return a detached copy of every committed event in native order."""
        return deepcopy(self._events)

    def position(self, source: str) -> int:
        """Return the durable replay cursor, or -1 before this source is read."""
        return self._metadata['sources'].get(source, -1)

    def mark_boundary(self, source: str, position: int) -> None:
        """Retain a native activation cut for callbacks running in new processes.

        This metadata is not an event or a message-order claim. The Runtime
        mapper uses its native record count/offset to distinguish preexisting
        history from content created after archiving was enabled.
        """
        self._fresh(source, position)
        with self._update():
            self._metadata['sources'][source] = position

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
        use the protocol's integer placeholder with the event's missing explaining
        it. Keep creation/completion/send/write/receipt times under their actual
        source names in native evidence, never substitute receipt for creation.

        A final record moves its matching unfinished observation to
        ``observations()`` with an explicit final native identity, retaining the
        exact final event and the observed partial content separately. Final
        content and time are never inferred from receipt time.
        """
        # Events taken unchanged from ``committed()`` are this snapshot's own,
        # already validated and encoded; only the others are copied (468).
        held = self._held_prefix(events)
        events = events[:held] + [_redacted(event) for event in deepcopy(events[held:])]
        validate_session(self.header, events, validated=held)
        keys = self._keys[:held] + [_key(event) for event in events[held:]]
        key_set = set(keys)
        if len(keys) != len(key_set):
            raise ValueError('Duplicate native event identity.')
        with self._update():
            # A reload by another writer leaves fewer (or no) events held.
            held = self._held_prefix(events)
            stored = dict(zip(self._keys, self._events))
            for key, event in zip(keys[held:], events[held:]):
                if key not in stored:
                    self._extend(event)
                elif 'extra_fields' in stored[key] and 'extra_fields' not in event:
                    event['extra_fields'] = deepcopy(stored[key]['extra_fields'])
            fresh = self._fresh(source, position)
            completing = position == self.position(source) and any(
                draft['source'] == source and _key(draft['event']) in key_set
                for draft in self._metadata['pending']
            )
            if not fresh and not completing:
                return False
            by_key = dict(zip(keys, events))
            # When every committed event is republished itself in place, order
            # and content are unchanged by construction; otherwise check them.
            if held < len(self._events):
                old_key_set = set(self._keys)
                if [key for key in keys if key in old_key_set] != self._keys:
                    raise ValueError('Projection must retain existing native events in their original order.')
                indices = {old['seq']: by_key[key]['seq'] for key, old in zip(self._keys, self._events)}
                session_id = self._metadata['header']['id']
                for key, old in zip(self._keys, self._events):
                    current = by_key[key]
                    if current is not old and _relocate(old, indices, session_id) != current:
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
            validate_session(self.header, events, validated=held)
            self._lines = self._lines[:held] + [_encode(event) for event in events[held:]]
            self._keys = keys
            self._events = events
            self._metadata['pending'] = remaining
            self._metadata['sources'][source] = position
        return True

    def committed(self) -> list[dict]:
        """Return this snapshot's committed events themselves, not copies.

        For a collector that republishes them unchanged with ``publish``, which
        then neither copies, revalidates nor re-encodes them. Never modify them.
        """
        return list(self._events)

    def _held_prefix(self, events: list[dict]) -> int:
        """Count the leading events that are this snapshot's own, in place."""
        same = list(map(operator.is_, events, self._events))
        return same.index(False) if False in same else len(same)

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
        event = _redacted(snapshot_event(event))
        self._extend(event)
        key = _key(event)
        with self._update():
            if expected_position is not None and self.position(source) != expected_position:
                raise ValueError('Source changed; resume from its durable checkpoint.')
            if not self._fresh(source, position):
                return False
            if key in set(self._keys):
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

    def _extend(self, event: dict) -> None:
        """Attach the host's event fields to an event about to be written."""
        if self.event_fields is None:
            return
        fields = self.event_fields(deepcopy(event))
        if fields is not None:
            event['extra_fields'] = {**event.get('extra_fields', {}), **redact_extra_fields(fields)}
            snapshot_event(event)

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

    def retain_legacy(self, records: dict) -> None:
        """Retain an exact old archive export without asserting its message order.

        Old notification-derived events are evidence, never a native projection.
        The migration reader supplies the original header, events, draft and
        checkpoints; attachment bytes use the ordinary attachment interface.
        """
        with self._update():
            previous = self._metadata.get('legacy')
            if previous is not None and previous != records:
                raise ValueError('Legacy archive changed after its retained import.')
            self._metadata['legacy'] = deepcopy(records)

    def legacy(self) -> dict | None:
        """Read retained old evidence separately from native-ordered events."""
        return deepcopy(self._metadata.get('legacy'))

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
            if final not in set(self._keys):
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
        if self._metadata.get('legacy') and not self._events:
            raise ValueError('Legacy observations have no verified native history.')
        validate_session(self.header, self._events, reconstruct=True)
        for value in [self.header, *self._events]:
            if any(_message_gap(item['path'])
                   for item in value.get('missing', [])):
                raise ValueError('Missing native content, history or correspondence; messages are incomplete.')
        surface = []
        for event in self._events:
            if event['type'] == 'history':
                surface = [self._events[ref] for ref in event['data']['eventSeqs']]
                continue
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
        event_fields: EventFields | None = None,
    ) -> None:
        """Set independent choices without opening or creating an archive.

        ``event_fields`` is the programmatic event extension described on
        ``JsonlSessionStore``; it is never reachable from model arguments.
        """
        if type(save_normalized_sessions) is not bool or type(backfill_history) is not bool:
            raise ValueError('Archive choices must be booleans.')
        if event_fields is not None and not callable(event_fields):
            raise ValueError('event_fields must be callable.')
        self.event_fields = event_fields
        self.root = Path(root)
        self.save_normalized_sessions = save_normalized_sessions
        self.backfill_history = backfill_history
        self._mapped: dict[str, dict] = {}
        # Per thread, the last Session's open store, refreshed on each use, so
        # live collection reparses an archive only after another writer
        # changed it (468).
        self._stores: dict[int, tuple[str, JsonlSessionStore]] = {}
        self._native_headers: dict[tuple, dict[str, dict]] = {}
        self._native_revision: int | None = None

    def native_header(
        self,
        runtime: str,
        native_id: str,
        *,
        agent_id: str | None = None,
        locator: str | None = None,
    ) -> dict | None:
        """Resolve a native reference through retained headers, never ID spelling.

        Only this tool's archive root is inspected. Explicit predecessor links
        select the current project Session without changing native identity.
        Unrelated headers claiming one native reference remain a conflict.
        A locator selects the latest record for that physical native source.
        """
        directory = self.root / 'sessions'
        revision = directory.stat().st_mtime_ns if directory.exists() else 0
        if revision != self._native_revision:
            headers = {}
            for path in directory.glob('*/session.jsonl'):
                with path.open(encoding='utf-8') as stream:
                    metadata = json.loads(next(stream))
                if metadata.get('archiveVersion') != 1:
                    raise ValueError('Unsupported Session archive version.')
                header = upgrade_header(metadata['header'])
                native = header.get('native', {})
                key = (native.get('runtime'), native.get('sessionId'), native.get('agentId'))
                headers.setdefault(key, {})[header['id']] = header
            self._native_headers, self._native_revision = headers, revision
        matches = dict(self._native_headers.get((runtime, native_id, agent_id), {}))
        for header in self._mapped.values():
            native = header.get('native', {})
            if (native.get('runtime') == runtime and native.get('sessionId') == native_id
                    and native.get('agentId') == agent_id):
                matches[header['id']] = header
        if locator is not None:
            matches = {key: header for key, header in matches.items()
                       if header.get('native', {}).get('locator') == locator}
        predecessors = {header.get('previousSession') for header in matches.values()}
        latest = {key: header for key, header in matches.items() if key not in predecessors}
        if matches and len(latest) != 1:
            raise ValueError('Native Session maps to multiple canonical archive IDs.')
        if latest:
            current = next(iter(latest.values()))
            visited = set()
            cursor = current
            while cursor['id'] not in visited:
                visited.add(cursor['id'])
                previous = cursor.get('previousSession')
                if previous not in matches:
                    break
                cursor = matches[previous]
            if visited != set(matches):
                raise ValueError('Native Session maps to unrelated canonical archive IDs.')
            return deepcopy(current)
        return None

    def native_id(self, runtime: str, native_id: str, *, agent_id: str | None = None) -> str:
        """Return the retained archive ID, or the default ID for a new archive."""
        header = self.native_header(runtime, native_id, agent_id=agent_id)
        return header['id'] if header else runtime + ':' + native_id + (':agent:' + agent_id if agent_id else '')

    def map_session(self, header: dict) -> None:
        """Register an already verified mapping supplied by the owning host.

        Header ``extra_fields`` are redacted before they are retained. This is
        an explicit source allowlist, not identity authority.
        """
        validate_header(header)
        header = _redacted(header)
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
        # Each thread keeps only the store of the Session it used last: live
        # collection reuses it, and a caller going through many Sessions holds
        # one open archive, not one per Session. The file lock still orders
        # writers, and no thread sees another's uncommitted changes.
        thread = threading.get_ident()
        held = self._stores.get(thread)
        store = held[1] if held is not None and held[0] == session_id else None
        if store is not None and store._depth:
            return store  # Inside this thread's own batch, which holds the lock.
        if store is not None and store.path.exists():
            store.refresh()
            if store.header == _redacted(self._mapped[session_id]):
                store.event_fields = self.event_fields
                return store
        self._stores.pop(thread, None)
        store = JsonlSessionStore.create(archive_path(self.root, session_id), self._mapped[session_id],
                                         event_fields=self.event_fields)
        self._stores[thread] = (session_id, store)
        return store

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


class ConfiguredSessionArchive(SessionArchive):
    """Use the independent tool's current choices for every archive operation.

    A Runtime receives this through Run.archive when collection is enabled at
    activation. Disabling saving stops subsequent writes without deleting the
    archive or changing the Runtime's native Session.
    """

    def store(self, session_id: str, *, historical: bool = False) -> JsonlSessionStore | None:
        """Reload tool-owned settings before acquiring a collection capability."""
        choices = read_config(self.root)
        self.save_normalized_sessions = choices['save_normalized_sessions']
        self.backfill_history = choices['backfill_history']
        return super().store(session_id, historical=historical)


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
        if record.get('type') == 'text-run':
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
