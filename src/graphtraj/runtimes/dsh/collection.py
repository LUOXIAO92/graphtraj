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

from agent_swarm.sessions.protocol import validate_header, snapshot_event
from graphtraj.sessions.storage import SessionStore, session_path
from agent_swarm.sessions.archive import SessionArchive
from agent_swarm.sessions.dsh_live import DshLiveFrames


UPSTREAM = 'd743267388641bc76f17c45ce8b4c231aed1d32c'
SOURCE = 'dsh/session/event/v4'


from agent_swarm.sessions.dsh import collect_jsonl, DshArchive, attachment_refs, attempt_usage


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
