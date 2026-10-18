"""Archive DSH v4's complete append feed, not its conversation projection.

Protocol source: deepseek-ai/deepseek-harness at
d743267388641bc76f17c45ce8b4c231aed1d32c (see sessions/DSH-LICENSE).
One native seq is one atomic archive event/checkpoint. Failed attempts already
contain compact streams; their usage is a replacement snapshot, never a sum of
stream notifications. No upstream TypeScript module is used by this collector.
"""

from __future__ import annotations

import base64
from copy import deepcopy
import json
from pathlib import Path

from graphtraj.sessions.protocol import validate_header, snapshot_event
from graphtraj.sessions.storage import SessionStore, session_path
from graphtraj.sessions.archive import SessionArchive


UPSTREAM = 'd743267388641bc76f17c45ce8b4c231aed1d32c'
SOURCE = 'dsh/session/event/v4'


def collect_jsonl(
    archive: SessionArchive,
    header: dict,
    records: list[dict],
    *,
    historical: bool = False,
) -> dict:
    """Save a complete native prefix to an explicitly mapped optional archive.

    The caller supplies Session events, including inherited seed events, in
    native seq order. Cursorless presentation frames are not Session records.
    This acknowledges the normalized copy only; native persistence still owns
    its separate awaited flush. No project configuration or global Session
    directory is consulted.
    """
    validate_header(header)
    archived = deepcopy(header)
    archived['id'] = 'dsh:' + header['id']
    if 'parentSession' in archived:
        archived['parentSession'] = 'dsh:' + archived['parentSession']
    # The optional legacy GraphTraj header requires Project/Task metadata.
    # A standalone native Session has none; retain its provenance directly.
    archived['native'] = {'runtime': 'dsh', 'sessionId': header['id'],
                          'locator': 'header', 'record': deepcopy(header)}
    archive.map_session(archived)
    store = archive.store(archived['id'], historical=historical)
    if store is None:
        return {'session': archived['id'], 'saved': False}

    events = []
    for seq, record in enumerate(records):
        native = record['event']
        event = snapshot_event(native)
        if event['seq'] != seq:
            raise ValueError('DSH JSONL collection requires the complete native prefix in seq order.')
        ext = {'version': 1, 'native': {
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
                copied[path] = {'missing': {'path': path, 'reason': supplied.get(
                    'missing', 'Native attachment bytes were not supplied.')}}
        if copied:
            ext['attachments'] = copied
        event['graphtraj'] = ext
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

    def __init__(self, archive: SessionArchive, *, resumed: bool) -> None:
        """Bind the optional policy and whether an old Session is being resumed."""
        self.archive = archive
        self.resumed = resumed
        self.header: dict | None = None
        self.boundary = -1
        self.records: dict[int, dict] = {}

    def start(self, snapshot: dict, records: list[dict]) -> None:
        """Capture the native opening cut, never a receipt-time boundary."""
        self.header = snapshot['header']
        self.boundary = snapshot['cursor']
        collect_jsonl(self.archive, self.header, [])
        store = self.archive.store('dsh:' + self.header['id'])
        if store is not None:
            after = -1
            while True:
                page = store.page(after=after)
                for row in page['events']:
                    native = row['graphtraj']['native']['record']
                    self.records[native['seq']] = {'event': native}
                if not page['has_more']:
                    break
                after = page['after']
        if not self.resumed or self.archive.backfill_history:
            for record in records:
                self.records[record['event']['seq']] = record
            self._save()

    def event(self, native: dict) -> None:
        """Retain formal events by native seq; live presentation frames stay out."""
        if self.header is None:
            raise ValueError('DSH archive needs its native opening snapshot.')
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
            collect_jsonl(self.archive, self.header, [self.records[n] for n in positions])
            return
        session = 'dsh:' + self.header['id']
        for seq in positions:
            if seq <= self.boundary:
                continue
            event = snapshot_event(self.records[seq]['event'])
            event['graphtraj'] = {
                'version': 1, 'native': {'runtime': 'dsh', 'sessionId': self.header['id'],
                    'locator': f'event/{seq}', 'record': deepcopy(event)},
                'missing': [{'path': 'history', 'reason': 'Earlier native events are unavailable in this collection prefix.'}],
            }
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


def confirm_collection(state: Path, session_id: str, trace: Path) -> None:
    """Require the archive to contain the final owned native log before success.

    The native service is stopped before this check, so its JSONL prefix is
    stable. This checks the watermark without interpreting physical event
    payloads or using the browser projection as a complete log.
    """
    with trace.open(encoding='utf-8') as stream:
        header = json.loads(next(stream))
        if header.get('type') != 'session' or header.get('id') != session_id or header.get('version') != 4:
            raise ValueError('The owned DSH trace does not have its v4 Session header.')
        last = -1
        for line in stream:
            record = json.loads(line)
            if record.get('seq') != last + 1:
                raise ValueError('The owned DSH trace has a noncontiguous event position.')
            last = record['seq']
    with SessionStore(session_path(state, 'dsh:' + session_id), readonly=True) as store:
        if store.position(SOURCE) != last or store.next_seq != last + 1:
            raise ValueError('DSH Session collection has not committed its final native prefix.')


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


def collect(
    state: Path,
    header: dict,
    records: list[dict],
    *,
    project_id: str,
    agent_id: str,
    task_ids: list[str],
    source: str,
) -> dict:
    """Commit native callback records and return the inclusive durable seq.

    ``records`` carries each untouched event and optional base64 attachment
    bytes supplied by DSH's attachment capability. A failed copy is recorded
    at the exact native JSON path. Retrying an acknowledged seq is a no-op;
    gaps refuse rather than advancing past uncommitted input. Attachment bytes
    commit before their event, so an interruption can only leave unreferenced
    content, never a committed reference to bytes that were not saved.
    """
    validate_header(header)
    session_id = 'dsh:' + header['id']
    archived = deepcopy(header)
    archived['id'] = session_id
    if 'parentSession' in header:
        archived['parentSession'] = 'dsh:' + header['parentSession']
    archived['graphtraj'] = {
        'version': 1, 'projectId': project_id, 'agentId': agent_id,
        'taskIds': task_ids, 'source': source, 'upstream': UPSTREAM,
        'native': {'runtime': 'dsh', 'sessionId': header['id'],
                   'locator': 'header', 'record': deepcopy(header)},
    }
    with SessionStore.create(session_path(state, session_id), archived) as store:
        for record in records:
            native = record['event']
            event = snapshot_event(native)
            seq = event['seq']
            if seq <= store.position(SOURCE):
                continue
            if seq != store.next_seq:
                raise ValueError('DSH collection requires contiguous native event positions.')
            ext = {
                'version': 1,
                'native': {'runtime': 'dsh', 'sessionId': header['id'],
                           'locator': f'event/{seq}', 'record': deepcopy(native)},
            }
            usage, usage_path = attempt_usage(native)
            if usage is not None:
                ext.update(usage=usage, usageSource=usage_path)
            attachments = {}
            for path, reference in attachment_refs(native).items():
                supplied = record.get('attachments', {}).get(path, {})
                if 'base64' in supplied:
                    content = base64.b64decode(supplied['base64'], validate=True)
                    if len(content) != reference['bytes']:
                        raise ValueError('DSH attachment byte count does not match its reference.')
                    attachments[path] = store.put_attachment(content)
                else:
                    reason = supplied.get('missing', 'Native attachment bytes were not supplied.')
                    if not isinstance(reason, str) or not reason:
                        raise ValueError('DSH attachment missing reason must be nonempty.')
                    attachments[path] = {'missing': {'path': path, 'reason': reason}}
            if attachments:
                ext['attachments'] = attachments
            event['graphtraj'] = ext
            store.append_many([event], source=SOURCE, position=seq)
        return {'session': session_id, 'position': store.position(SOURCE)}
