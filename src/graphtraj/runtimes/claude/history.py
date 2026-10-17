"""Interpret Claude 2.1.299 transcript links, independently of notification order.

The ordering contract is the official SDK 0.3.299 getSessionMessages loader:
parentUuid, compactMetadata's retained links, and sibling assistant blocks.
Original records are never modified when applying the native retained links.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path


def read_records(path: Path, session: str) -> list[dict]:
    """Read complete lines from the one attested transcript, never scan a home."""
    records = []
    with path.open('rb') as stream:
        for line in stream:
            if not line.endswith(b'\n'):
                break
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError('Claude transcript entry must be an object.')
            if record.get('sessionId', session) != session:
                raise ValueError('Claude transcript belongs to another Session.')
            records.append(record)
    return records


def conversation(records: list[dict]) -> list[dict]:
    """Return native main-conversation records, retaining distinct UUID blocks.

    File position selects the native terminal branch. It never substitutes for
    parent links. Native compaction explicitly supplies the retained ordering;
    logicalParentUuid is historical provenance, not a link back into context.
    Missing links and ambiguous duplicate UUIDs are errors, not invented roots.
    """
    original = {}
    for record in records:
        if record.get('type') not in {'user', 'assistant', 'system', 'progress', 'attachment'}:
            continue
        uid = record.get('uuid')
        if not isinstance(uid, str) or not uid:
            raise ValueError('Native chain entry has no UUID.')
        if uid in original and original[uid] != record:
            raise ValueError('Native UUID was reused with different content.')
        original[uid] = record
    linked = deepcopy(original)
    for record in list(linked.values()):
        if record.get('subtype') != 'compact_boundary':
            continue
        metadata = record.get('compactMetadata', {})
        kept = metadata.get('preservedMessages')
        segment = metadata.get('preservedSegment')
        if kept is not None:
            uuids, anchor = kept['uuids'], kept['anchorUuid']
            if not uuids or len(set(uuids)) != len(uuids) or any(u not in linked for u in uuids):
                raise ValueError('Native preserved messages are incomplete.')
            parent = anchor
            for uid in uuids:
                linked[uid]['parentUuid'] = parent
                parent = uid
            head, tail = uuids[0], uuids[-1]
        elif segment is not None:
            head, tail, anchor = (segment[k] for k in ('headUuid', 'tailUuid', 'anchorUuid'))
            if head not in linked or tail not in linked:
                raise ValueError('Native preserved segment is incomplete.')
            linked[head]['parentUuid'] = anchor
        else:
            continue
        if anchor not in linked:
            raise ValueError('Native compaction anchor is missing.')
        for uid, entry in linked.items():
            if entry.get('parentUuid') == anchor and uid != head:
                entry['parentUuid'] = tail

    def main(record: dict) -> bool:
        """Use the SDK's main-terminal filter; progress cannot select a branch."""
        return (not record.get('isSidechain') and not record.get('teamName')
                and record['type'] != 'progress'
                and not (record['type'] == 'attachment'
                         and record.get('attachment', {}).get('type') == 'fork_briefing'))

    parents = {r.get('parentUuid') for r in linked.values() if main(r)}
    terminals = [uid for uid, r in linked.items() if main(r) and uid not in parents]
    leaf = None
    for uid in reversed(terminals):
        seen = set()
        while uid:
            if uid in seen or uid not in linked:
                raise ValueError('Native conversation has a cycle or missing parent.')
            seen.add(uid)
            record = linked[uid]
            if record['type'] in {'user', 'assistant'}:
                leaf = uid
                break
            uid = record.get('parentUuid')
        if leaf:
            break
    if leaf is None:
        if any(main(r) and r['type'] in {'user', 'assistant'} for r in linked.values()):
            raise ValueError('Native conversation has no terminal message.')
        return []
    native_leaf = leaf
    chain, seen = [], set()
    while leaf:
        if leaf in seen or leaf not in linked:
            raise ValueError('Native conversation has a cycle or missing parent.')
        seen.add(leaf)
        chain.append(original[leaf])
        leaf = linked[leaf].get('parentUuid')
    chain.reverse()

    # The SDK restores response siblings omitted from a parent chain, including
    # tool results parented to another block of the same API message. Its sibling
    # tie-break uses native transcript timestamps, never notification clocks.
    responses = {}
    for record in original.values():
        if record['type'] == 'assistant' and record.get('message', {}).get('id'):
            responses.setdefault(record['message']['id'], []).append(record)
    last = {r.get('message', {}).get('id'): r['uuid'] for r in chain if r['type'] == 'assistant'}
    additions = {}
    for api_id, anchor in last.items():
        siblings = responses.get(api_id, [])
        ids = {r['uuid'] for r in siblings}
        calls = {b['id'] for r in siblings for b in r.get('message', {}).get('content', [])
                 if isinstance(b, dict) and b.get('type') == 'tool_use'}
        extra = [r for r in siblings if r['uuid'] not in seen]
        results = []
        for record in original.values():
            content = record.get('message', {}).get('content', [])
            if record['type'] != 'user' or record['uuid'] in seen or not isinstance(content, list):
                continue
            if (bool(record.get('isSidechain')) != bool(siblings[0].get('isSidechain'))
                    or record.get('agentId') != siblings[0].get('agentId')):
                continue
            tool_ids = {b.get('tool_use_id') for b in content
                        if isinstance(b, dict) and b.get('type') == 'tool_result'}
            if tool_ids and (record.get('parentUuid') in ids
                             or record.get('sourceToolAssistantUUID') in ids or tool_ids & calls):
                results.append(record)
        extra.sort(key=lambda r: r.get('timestamp') or '')
        results.sort(key=lambda r: r.get('timestamp') or '')
        additions[anchor] = extra + results
        seen.update(r['uuid'] for r in extra + results)
    expanded = [entry for record in chain for entry in [record, *additions.get(record['uuid'], [])]]

    # The native API also exposes queued input after the last assistant, unless
    # that attachment belongs to a different message branch. Keep its source
    # entry intact; the mapper projects its prompt as the SDK's user message.
    other_ancestors = set()
    for record in original.values():
        if record['type'] not in {'user', 'assistant'} or not main(record) or record['uuid'] in seen:
            continue
        parent = record.get('parentUuid')
        while parent and parent not in seen and parent not in other_ancestors and parent in original:
            other_ancestors.add(parent)
            parent = original[parent].get('parentUuid')
    children = {}
    for record in original.values():
        if record['type'] not in {'user', 'assistant'}:
            children.setdefault(record.get('parentUuid'), []).append(record)
    trailing = set()
    stack = [native_leaf]
    while stack:
        uid = stack.pop()
        if uid != native_leaf:
            if uid in seen:
                continue
            seen.add(uid)
            record = original[uid]
            if record.get('attachment', {}).get('type') == 'queued_command' and uid not in other_ancestors:
                trailing.add(uid)
                expanded.append(record)
        stack.extend(r['uuid'] for r in sorted(children.get(uid, []),
                                              key=lambda r: r.get('timestamp') or '', reverse=True)
                     if r['uuid'] not in seen)

    # An absorbed input is acknowledged by native delivery records, not by our
    # receipt time. Different copies sharing a delivery ID are not all delivered.
    delivered, copies, content_copies, mixed = {}, {}, {}, set()
    for record in records:
        if record.get('type') == 'queue-operation' and record.get('operation') == 'remove' and record.get('reason') == 'absorbed_mid_turn':
            key = ('delivery', record['deliveryId']) if record.get('deliveryId') else ('source', record.get('commandUuid'))
            if key[1]:
                delivered[key] = delivered.get(key, 0) + 1
        attachment = record.get('attachment', {})
        if attachment.get('type') != 'queued_command':
            continue
        if attachment.get('delivery_id'):
            key = ('delivery', attachment['delivery_id'])
            values = copies.setdefault(key, [])
            if record['uuid'] not in values:
                values.append(record['uuid'])
        elif attachment.get('source_uuid'):
            uid = attachment['source_uuid']
            value = json.dumps(attachment, sort_keys=True)
            if uid in content_copies and content_copies[uid] != value:
                mixed.add(uid)
            content_copies[uid] = value
    for uid in mixed:
        delivered.pop(('source', uid), None)
    selected = {uid for key, values in copies.items() if delivered.get(key)
                for uid in values[-delivered[key]:]}
    overrides, groups = {}, {}
    for index, record in enumerate(expanded):
        attachment = record.get('attachment', {})
        key = (('delivery', attachment['delivery_id']) if attachment.get('delivery_id')
               else ('source', attachment.get('source_uuid')))
        if key in delivered:
            groups.setdefault(key, []).append(index)
    for key, indices in groups.items():
        for offset, index in enumerate(indices):
            overrides[index] = (expanded[index]['uuid'] in selected if key[0] == 'delivery'
                                else offset >= len(indices) - delivered[key])

    acknowledged, state = {}, None
    for index in range(len(expanded) - 1, -1, -1):
        record = expanded[index]
        acknowledged[index] = state == 'reply'
        content = record.get('message', {}).get('content', [])
        tool_result = isinstance(content, list) and any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in content)
        if record['type'] == 'assistant' or record['type'] == 'user' and tool_result:
            state = 'reply'
        elif record['type'] == 'user' and not record.get('isMeta') and not record.get('isCompactSummary'):
            state = 'prompt'
    ids = {r['uuid'] for r in expanded}
    result = []
    visible_origins = {'channel', 'observer', 'observer-activity', 'slack-ping', 'peer'}
    for index, record in enumerate(expanded):
        if not main(record):
            continue
        if record['type'] == 'attachment' and record.get('attachment', {}).get('type') == 'queued_command':
            attachment = record['attachment']
            if attachment.get('forwardedIntent') is not None:
                raise ValueError('Native forwarded queued intent needs explicit interpretation.')
            visible = attachment.get('origin', {}).get('kind') in visible_origins
            delivered_input = overrides.get(index, acknowledged[index] or record['uuid'] in trailing)
            if not delivered_input or attachment.get('isMeta') and not visible:
                continue
            uid = message_id(record)
            if uid != record['uuid'] and uid in ids:
                continue
            ids.add(uid)
            if not isinstance(attachment.get('prompt'), (str, list)):
                raise ValueError('Native queued input has no prompt.')
            result.append(deepcopy(record))
        elif record['type'] in {'user', 'assistant'}:
            if not record.get('isMeta') or record.get('origin', {}).get('kind') in visible_origins:
                result.append(deepcopy(record))
    return result


def message_id(record: dict) -> str:
    """Return the SDK's message identity without replacing the source entry UUID."""
    if record['type'] == 'attachment':
        return record.get('attachment', {}).get('source_uuid') or record['uuid']
    return record['uuid']
