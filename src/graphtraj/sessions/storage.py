"""Transactional project Session archives and bounded, resumable stream collection.

Final events are append-only. A draft is a replaceable checkpoint, never a final
log event. SQLite's rollback journal and FULL synchronization commit the draft,
source position and attachments together; a returned commit survives process
termination. Bytes received since the last checkpoint are not yet durable and
must be replayed by the Runtime source. No transport-fragment log is retained.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Iterator

from graphtraj.sessions.protocol import (
    snapshot_event, validate_header, validate_session, validate_stream,
)


def _json(value: object) -> str:
    """Encode compact lossless JSON; protocol validation precedes storage."""
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def session_path(state: Path, session_id: str) -> Path:
    """Locate a canonical Session without interpreting its ID as a path."""
    if not isinstance(session_id, str) or not session_id:
        raise ValueError('A nonempty Session ID is required.')
    return state / 'sessions' / sha256(session_id.encode()).hexdigest() / 'session.sqlite3'


class SessionStore:
    """One independently readable archive, including actual attachment bytes.

    This low-level Runtime seam assumes its caller owns filesystem access.
    Public Agent queries must additionally authorize through the Runner binding;
    header identities and native IDs never grant read permission.
    """

    def __init__(self, path: Path, *, readonly: bool = False) -> None:
        """Open an existing archive; never silently create an empty read target."""
        self.path = Path(path)
        mode = 'ro' if readonly else 'rw'
        try:
            self.db = sqlite3.connect(self.path.resolve().as_uri() + f'?mode={mode}', uri=True)
        except sqlite3.Error as error:
            raise ValueError('Session archive is unavailable or unreadable.') from error
        self.db.execute('PRAGMA busy_timeout = 5000')
        self.db.execute('PRAGMA foreign_keys = ON')
        if not readonly:
            self.db.execute('PRAGMA synchronous = FULL')
        if self.db.execute('PRAGMA user_version').fetchone()[0] != 1:
            self.close()
            raise ValueError('Unsupported Session storage version.')

    @classmethod
    def create(cls, path: Path, header: dict) -> SessionStore:
        """Create an archive, or reopen exactly the same immutable header."""
        validate_header(header)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path)
        try:
            db.execute('PRAGMA synchronous = FULL')
            db.execute('BEGIN IMMEDIATE')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise ValueError('Unsupported Session storage version.')
            for statement in (
                'CREATE TABLE IF NOT EXISTS header (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, value TEXT NOT NULL, native TEXT UNIQUE)',
                'CREATE TABLE IF NOT EXISTS checkpoints (source TEXT PRIMARY KEY, position INTEGER NOT NULL)',
                'CREATE TABLE IF NOT EXISTS draft (id INTEGER PRIMARY KEY CHECK(id=1), source TEXT NOT NULL, value TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS attachments (digest TEXT PRIMARY KEY, content BLOB NOT NULL)',
            ):
                db.execute(statement)
            row = db.execute('SELECT value FROM header').fetchone()
            if row and json.loads(row[0]) != header:
                raise ValueError('Session header already exists with different metadata.')
            if row is None:
                db.execute('INSERT INTO header VALUES (1, ?)', (_json(header),))
            db.execute('PRAGMA user_version = 1')
            db.commit()
        finally:
            db.close()
        return cls(path)

    def close(self) -> None:
        """Close the archive; callers explicitly checkpoint buffered streams first."""
        self.db.close()

    def __enter__(self) -> SessionStore:
        """Return this opened archive."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Release the database connection without implicitly accepting output."""
        self.close()

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        """Serialize one writer and atomically commit all its durable facts."""
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    @property
    def header(self) -> dict:
        """Return detached immutable metadata, including fork provenance."""
        return json.loads(self.db.execute('SELECT value FROM header').fetchone()[0])

    @property
    def next_seq(self) -> int:
        """Return the next final event sequence without reading event bodies."""
        return self.db.execute('SELECT coalesce(max(seq)+1, 0) FROM events').fetchone()[0]

    def position(self, source: str) -> int:
        """Return the committed inclusive source offset, or -1 before collection."""
        row = self.db.execute('SELECT position FROM checkpoints WHERE source=?', (source,)).fetchone()
        return row[0] if row else -1

    def _advance(self, source: str, position: int) -> None:
        """Set one validated ordered source's checkpoint inside its transaction."""
        self.db.execute('INSERT INTO checkpoints VALUES (?, ?) ON CONFLICT(source) '
                        'DO UPDATE SET position=excluded.position', (source, position))

    def _fresh(self, source: str, position: int) -> bool:
        """Validate an ordered source coordinate and reject already received input."""
        if not isinstance(source, str) or not source or type(position) is not int or position < 0:
            raise ValueError('Source and nonnegative integer position are required.')
        return position > self.position(source)

    def _insert(self, event: dict) -> int:
        """Append a semantic event; identical native provenance is idempotent."""
        event = snapshot_event(event)
        native = event.get('graphtraj', {}).get('native')
        key = _json([native[k] for k in ('runtime', 'sessionId', 'locator')]) if native else None
        if key is not None:
            row = self.db.execute('SELECT seq, value FROM events WHERE native=?', (key,)).fetchone()
            if row:
                original = json.loads(row[1])
                event['seq'] = original['seq']
                if event != original:
                    raise ValueError('Native event identity was reused with different content.')
                return row[0]
        if event['seq'] != self.next_seq:
            raise ValueError('Events must append in contiguous sequence order.')
        self.db.execute('INSERT INTO events VALUES (?, ?, ?)', (event['seq'], _json(event), key))
        return event['seq']

    def append(self, event: dict, *, source: str, position: int) -> bool:
        """Commit one event and its source offset; replayed offsets do nothing.

        Each source must supply ordered, stable integer positions (for example
        native byte offsets). Start a new source ID if the underlying log resets.
        An unfinished stream must be finalized before another event is appended.
        """
        return self.append_many([event], source=source, position=position)

    def append_many(self, events: list[dict], *, source: str, position: int) -> bool:
        """Commit all semantic events mapped from one native source position together.

        For example, a message and its probability observation cannot commit
        independently while advancing past their shared original source record.
        """
        if not isinstance(events, list) or not events:
            raise ValueError('At least one semantic event is required.')
        with self._transaction():
            if not self._fresh(source, position):
                return False
            if self.pending() is not None:
                raise ValueError('Finalize the pending stream before appending a boundary event.')
            for event in events:
                self._insert(event)
            self._advance(source, position)
        return True

    def pending(self) -> dict | None:
        """Return the latest durable unfinished output separately from final events."""
        row = self.db.execute('SELECT source, value FROM draft').fetchone()
        return {'source': row[0], 'event': json.loads(row[1])} if row else None

    def page(self, after: int = -1, limit: int = 200) -> dict:
        """Read an indexed bounded page; its cursor remains valid as events append."""
        if type(after) is not int or after < -1 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('Use after >= -1 and a limit between 1 and 1000.')
        rows = self.db.execute('SELECT seq, value FROM events WHERE seq>? ORDER BY seq LIMIT ?',
                               (after, limit + 1)).fetchall()
        events = [json.loads(row[1]) for row in rows[:limit]]
        return {'events': events, 'after': events[-1]['seq'] if events else after,
                'has_more': len(rows) > limit}

    def put_attachment(self, content: bytes) -> dict:
        """Commit actual bytes in this archive and return a portable content reference."""
        if not isinstance(content, bytes):
            raise ValueError('Attachment content must be bytes.')
        digest = sha256(content).hexdigest()
        with self._transaction():
            self.db.execute('INSERT OR IGNORE INTO attachments VALUES (?, ?)', (digest, content))
        return {'storage': 'session', 'sha256': digest, 'size': len(content)}

    def copy_attachment(self, path: Path) -> dict:
        """Copy source bytes, or explicitly report unavailable original content."""
        try:
            return self.put_attachment(Path(path).read_bytes())
        except OSError as error:
            return {'missing': {'path': str(path), 'reason': type(error).__name__}}

    def attachment(self, digest: str) -> bytes:
        """Read retained bytes independently of any Runtime Home or native source."""
        row = self.db.execute('SELECT content FROM attachments WHERE digest=?', (digest,)).fetchone()
        if row is None:
            raise ValueError('Original attachment bytes are unavailable in this archive.')
        return row[0]

    def export(self, destination: Path) -> None:
        """Create a consistent standalone database, including draft and attachments."""
        destination = Path(destination)
        # Exclusive creation prevents accidental replacement of an existing archive.
        with destination.open('xb'):
            pass
        target = sqlite3.connect(destination)
        try:
            self.db.backup(target)
        finally:
            target.close()

    def validate(self) -> None:
        """Explicitly validate full-log references; ordinary pages never load the log."""
        events = [json.loads(row[0]) for row in self.db.execute('SELECT value FROM events ORDER BY seq')]
        validate_session(self.header, events)


class StreamWriter:
    """Compact one assistant message/attempt, checkpointing bounded input batches.

    ``event`` is a complete protocol template with an empty stream. Message
    content remains the Runtime mapper's responsibility: use ``finish`` with its
    final content, or retrieve ``event`` to build an interrupted message. Text
    runs already preserve received partial text even before a message is built.
    Unknown fields are semantic boundaries and are never silently merged away.
    """

    def __init__(
        self,
        store: SessionStore,
        source: str,
        event: dict | None = None,
        *,
        checkpoint_bytes: int = 65536,
    ) -> None:
        """Resume a durable draft or start an explicitly supplied assistant event."""
        if type(checkpoint_bytes) is not int or checkpoint_bytes < 1:
            raise ValueError('checkpoint_bytes must be positive.')
        self.store = store
        self.source = source
        pending = store.pending()
        if pending:
            if pending['source'] != source or event is not None:
                raise ValueError('A different unfinished output already exists.')
            event = pending['event']
        if event is None:
            raise ValueError('An event template is required for a new stream.')
        self.event = snapshot_event(event)
        if event['type'] not in {'assistant/message', 'assistant/attempt'} or event['seq'] != store.next_seq:
            raise ValueError('A stream must use the next assistant event sequence.')
        self.position = store.position(source)
        self.committed_position = self.position
        self.committed_draft = pending
        self.checkpoint_bytes = checkpoint_bytes
        self.buffered = 0
        self.closed = False

    def feed(self, record: dict, position: int, *, cumulative: bool = False) -> bool:
        """Receive one semantic stream record; combine only adjacent plain text runs.

        ``cumulative`` means the run's text is the full block prefix. Only its
        new suffix is retained. A non-prefix snapshot is an error, not silent
        replacement. The source position becomes durable only at checkpoint.
        """
        if self.closed:
            raise ValueError('Stream is finalized.')
        self.store._fresh(self.source, position)
        if position <= self.position:
            return False
        validate_stream([record])
        record = deepcopy(record)
        stream = self.event['data']['stream']
        keys = {'type', 'requestId', 'attemptId', 'messageId', 'index', 'blockType', 'text'}
        plain = record['type'] == 'graphtraj/text-run' and set(record) == keys
        if cumulative:
            if record['type'] != 'graphtraj/text-run':
                raise ValueError('Cumulative input requires a text run.')
            previous = ''.join(item['text'] for item in stream if item.get('type') == record['type']
                               and all(item.get(k) == record[k] for k in keys - {'text'}))
            if not record['text'].startswith(previous):
                raise ValueError('Cumulative snapshot changed already received text.')
            record['text'] = record['text'][len(previous):]
        if plain and stream and set(stream[-1]) == keys and all(
            stream[-1][key] == record[key] for key in keys - {'text'}
        ):
            stream[-1]['text'] += record['text']
        else:
            stream.append(record)
        self.position = position
        self.buffered += len(_json(record).encode())
        if self.buffered >= self.checkpoint_bytes:
            self.checkpoint()
        return True

    def checkpoint(self) -> None:
        """Atomically make received output and its inclusive source offset durable."""
        if self.closed:
            raise ValueError('Stream is finalized.')
        snapshot_event(self.event)
        with self.store._transaction():
            self._check_owner()
            self.store.db.execute('INSERT INTO draft VALUES (1, ?, ?) ON CONFLICT(id) '
                                  'DO UPDATE SET source=excluded.source, value=excluded.value',
                                  (self.source, _json(self.event)))
            self.store._advance(self.source, self.position)
        self.committed_position = self.position
        self.committed_draft = {'source': self.source, 'event': deepcopy(self.event)}
        self.buffered = 0

    def _check_owner(self) -> None:
        """Reject stale writers rather than overwrite another collector's commit."""
        pending = self.store.pending()
        if (self.store.position(self.source) != self.committed_position
                or self.store.next_seq != self.event['seq']
                or pending != self.committed_draft):
            raise ValueError('Session changed; reopen the stream from its committed checkpoint.')

    def finish(
        self,
        *,
        content: list | None = None,
        interrupted: bool = False,
        following: list[dict] | None = None,
    ) -> int:
        """Append received output on completion, cancellation, failure or abort.

        For a message without explicit final content, construct text/reasoning
        blocks from retained runs. Other block kinds must be mapped explicitly
        by the Runtime; their original stream records remain intact regardless.
        ``following`` commits observations or boundary events from the same
        source position atomically with the output, before advancing its cursor.
        """
        if self.closed:
            raise ValueError('Stream is finalized.')
        event = deepcopy(self.event)
        if interrupted:
            event['data']['interrupted'] = True
        if event['type'] == 'assistant/message':
            if content is None:
                content = deepcopy(event['data']['message']['content'])
                for record in event['data']['stream']:
                    if record['type'] == 'graphtraj/text-run':
                        index = record['index']
                        if index > len(content):
                            raise ValueError('Map intervening non-text blocks explicitly before finishing.')
                        if index == len(content):
                            content.append({'type': record['blockType'], 'text': ''})
                        if content[index]['type'] != record['blockType']:
                            raise ValueError('Map non-text blocks explicitly before finishing.')
                        content[index]['text'] += record['text']
            event['data']['message']['content'] = content
        snapshot_event(event)
        with self.store._transaction():
            self._check_owner()
            self.store._insert(event)
            for observation in following or []:
                self.store._insert(observation)
            self.store.db.execute('DELETE FROM draft')
            self.store._advance(self.source, self.position)
        self.closed = True
        return event['seq']
