"""Optional native DSH JSONL collection without project dependencies."""
from __future__ import annotations
import base64
from copy import deepcopy
from pathlib import Path
import json
from .protocol import snapshot_event, upgrade_header, validate_extra_fields
from .archive import SessionArchive
from .dsh_live import DshLiveFrames

SOURCE = 'dsh/session/event/v4'


def _require_free(value: dict, fields) -> None:
    """Refuse a native DSH value already using an archive field name; never overwrite it."""
    if any(field in value for field in fields):
        raise ValueError('Native DSH value already uses an archive field name.')

def collect_jsonl(
    archive: SessionArchive,
    header: dict,
    records: list[dict],
    *,
    historical: bool = False,
    extra_fields: dict | None = None,
) -> dict:
    """Save a complete native prefix to an explicitly mapped optional archive.

    The caller supplies Session events, including inherited seed events, in
    native seq order. Cursorless presentation frames are not Session records.
    This acknowledges the normalized copy only; native persistence still owns
    its separate awaited flush. No project configuration or global Session
    directory is consulted. ``header`` is the native DSH v4 header; the archive
    header is its v5 spelling plus provenance and the caller's ``extra_fields``.
    """
    archived = upgrade_header(header)
    _require_free(archived, ('native', 'extra_fields'))
    archived['id'] = archive.native_id('dsh', header['id'])
    if 'parentSession' in archived:
        archived['parentSession'] = archive.native_id('dsh', archived['parentSession'])
    if extra_fields is not None:
        validate_extra_fields(extra_fields)
        archived['extra_fields'] = deepcopy(extra_fields)
    archived['native'] = {'runtime': 'dsh', 'sessionId': header['id'],
                          'locator': 'header', 'record': deepcopy(header)}
    archived = archive.native_header('dsh', header['id']) or archived
    archive.map_session(archived)
    store = archive.store(archived['id'], historical=historical)
    if store is None:
        return {'session': archived['id'], 'saved': False}

    retained = {}
    after = -1
    while True:
        page = store.page(after=after)
        retained.update((row['seq'], row) for row in page['events'])
        if not page['has_more']:
            break
        after = page['after']
    events = []
    for seq, record in enumerate(records):
        native = record['event']
        event = snapshot_event(native)
        if event['seq'] != seq:
            raise ValueError('DSH JSONL collection requires the complete native prefix in seq order.')
        ext = {'native': {
            'runtime': 'dsh', 'sessionId': header['id'],
            'locator': f'event/{seq}', 'record': deepcopy(native),
        }}
        usage, usage_path = attempt_usage(native)
        if usage is not None:
            ext.update(usage=usage, usageSource=usage_path)
        copied = {}
        for path, reference in attachment_refs(native).items():
            supplied = record.get('attachments', {}).get(path, {})
            if 'base64' in supplied:
                content = base64.b64decode(supplied['base64'], validate=True)
                if len(content) != reference['bytes']:
                    raise ValueError('DSH attachment byte count does not match its reference.')
                copied[path] = store.put_attachment(content)
            else:
                previous = retained.get(seq, {}).get('attachments', {}).get(path)
                copied[path] = previous or {'missing': {'path': path, 'reason': supplied.get(
                    'missing', 'Native attachment bytes were not supplied.')}}
        if copied:
            ext['attachments'] = copied
        _require_free(event, ext)
        event.update(ext)
        events.append(event)
    if events:
        store.publish(events, source=SOURCE, position=events[-1]['seq'])
    return {'session': archived['id'], 'saved': True, 'position': store.position(SOURCE)}


class DshArchive:
    """Collect only one owned native Session, keeping gaps explicit.

    When historical collection is disabled, pre-existing native records are
    not imported. New records following an unavailable prefix are retained as
    pending observations; messages cannot claim completeness. Enabling backfill
    later resolves these exact native identities with the complete prefix.
    """

    def __init__(self, archive: SessionArchive, *, resumed: bool, extra_fields: dict | None = None) -> None:
        """Bind the optional policy and whether an old Session is being resumed.

        ``extra_fields`` is written verbatim (after redaction) to a new header.
        """
        if extra_fields is not None:
            validate_extra_fields(extra_fields)
        self.extra_fields = deepcopy(extra_fields)
        self.archive = archive
        self.resumed = resumed
        self.header: dict | None = None
        self.boundary = -1
        self.observed_cursor = -1
        self.records: dict[int, dict] = {}
        self.live: DshLiveFrames | None = None

    def start(self, snapshot: dict, records: list[dict], *, execution_id: str | None = None) -> None:
        """Capture the native opening cut, never a receipt-time boundary."""
        self.header = snapshot['header']
        self.boundary = snapshot['cursor']
        self.observed_cursor = self.boundary
        collect_jsonl(self.archive, self.header, [], extra_fields=self.extra_fields)
        store = self.archive.store(self.archive.native_id('dsh', self.header['id']))
        if store is not None:
            after = -1
            while True:
                page = store.page(after=after)
                for row in page['events']:
                    native = row['native']['record']
                    self.records[native['seq']] = {'event': native}
                if not page['has_more']:
                    break
                after = page['after']
        if not self.resumed or self.archive.backfill_history:
            for record in records:
                self.records[record['event']['seq']] = record
            self._save()
        if execution_id is not None:
            session = self.archive.native_id('dsh', self.header['id'])
            self.live = DshLiveFrames(
                self.header['id'], execution_id,
                lambda event, revision: self.archive.checkpoint(
                    session, event, source=f'dsh/assistant-stream/{execution_id}', position=revision,
                ),
                lambda observation, final: self._resolve_pending(),
            )
            self.live.baseline(snapshot.get('assistantStream', {'revision': 0}))
        self._resolve_pending()

    def frame(self, frame: dict) -> None:
        """Persist cursorless native chunks separately from formal Session events."""
        if self.live is None:
            raise ValueError('DSH live collection needs its owning execution identity.')
        self.live.accept(frame)

    def _resolve_pending(self) -> None:
        """Resolve only native committed end(seq) facts whose final prefix exists.

        The end frame is retained in the pending observation before linking,
        so interruption between these commits is recoverable during backfill.
        No message text, receipt time or guessed next sequence participates.
        """
        if self.header is None:
            return
        store = self.archive.store(self.archive.native_id('dsh', self.header['id']))
        if store is None:
            return
        for pending in store.pending():
            native = pending['event'].get('native', {})
            outcome = native.get('record', {}).get('outcome', {})
            if (native.get('runtime') != 'dsh' or native.get('sessionId') != self.header['id']
                    or not native.get('locator', '').startswith('live/')
                    or outcome.get('kind') != 'committed'):
                continue
            seq = outcome['seq']
            if store.position(SOURCE) >= seq:
                if self.records[seq]['event']['type'] != outcome['eventType']:
                    raise ValueError('DSH terminal frame does not match its native final event type.')
                store.resolve_observation(
                    ('dsh', self.header['id'], native['locator']),
                    ('dsh', self.header['id'], f'event/{seq}'),
                )

    def event(self, native: dict) -> None:
        """Retain formal events by native seq; live presentation frames stay out."""
        if self.header is None:
            raise ValueError('DSH archive needs its native opening snapshot.')
        self.observed_cursor = max(self.observed_cursor, native['seq'])
        if native['seq'] <= self.boundary:
            return
        self.records[native['seq']] = {'event': native}
        self._save()

    def _save(self) -> None:
        """Publish a complete prefix or retain explicitly incomplete observations."""
        if not self.records:
            return
        # Native seq defines the log order. Notification timestamps never do.
        positions = sorted(self.records)
        if positions == list(range(positions[-1] + 1)):
            collect_jsonl(self.archive, self.header, [self.records[n] for n in positions],
                          extra_fields=self.extra_fields)
            self._resolve_pending()
            return
        session = self.archive.native_id('dsh', self.header['id'])
        for seq in positions:
            if seq <= self.boundary:
                continue
            event = snapshot_event(self.records[seq]['event'])
            fields = {
                'native': {'runtime': 'dsh', 'sessionId': self.header['id'],
                           'locator': f'event/{seq}', 'record': deepcopy(event)},
                'missing': [{'path': 'history', 'reason': 'Earlier native events are unavailable in this collection prefix.'}],
            }
            _require_free(event, fields)
            event.update(fields)
            self.archive.checkpoint(session, event, source=f'{SOURCE}/pending/{seq}', position=seq)

    def finish(self, trace: Path) -> None:
        """Reconcile the final owned disk log only after native shutdown/flush."""
        with trace.open(encoding='utf-8') as stream:
            header = json.loads(next(stream))
            if self.header is None or header['id'] != self.header['id']:
                raise ValueError('DSH persisted Session identity differs from its opening snapshot.')
            records = [{'event': json.loads(line)} for line in stream]
        if any(seq >= len(records) or record['event'] != records[seq]['event']
               for seq, record in self.records.items()):
            raise ValueError('DSH observed events are not confirmed by its final persisted prefix.')
        for seq, record in enumerate(records):
            if record['event']['seq'] != seq:
                raise ValueError('DSH disk log has a noncontiguous native prefix.')
            if not self.resumed or self.archive.backfill_history or seq > self.boundary:
                self.records[seq] = record
        self._save()


def attachment_refs(value: object, path: str = '$') -> dict[str, dict]:
    """Find native attachment references, including those in opaque extensions."""
    found = {}
    if isinstance(value, dict):
        if isinstance(value.get('attachmentId'), str):
            found[path] = value
        else:
            for key, item in value.items():
                found.update(attachment_refs(item, f'{path}/{key}'))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.update(attachment_refs(item, f'{path}/{index}'))
    return found


def attempt_usage(event: dict) -> tuple[dict | None, str | None]:
    """Select final usage, otherwise the last stream snapshot for this attempt.

    DSH inputTokens excludes both cache counters. Keep all counters verbatim;
    absence means unknown. Failed attempts remain separate billable attempts.
    """
    if event['type'] not in {'assistant/message', 'assistant/attempt', 'compaction/summary'}:
        return None, None
    data = event['data']
    if isinstance(data.get('usage'), dict):
        return deepcopy(data['usage']), 'data/usage'
    for index, item in reversed(list(enumerate(data.get('stream', [])))):
        if item.get('type') == 'chunk' and item.get('chunk', {}).get('type') == 'usage':
            return deepcopy(item['chunk']['usage']), f'data/stream/{index}/chunk/usage'
    return None, None


