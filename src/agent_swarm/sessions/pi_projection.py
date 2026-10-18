"""Reconstruct Pi 1.0 Session messages from retained native entries.

The rules follow Pi's ``buildSessionProjection`` in core/session-manager.
Entry write times never order messages. The selected parent chain, latest
compaction and context edits determine the model context. Callers must supply
the actual leaf ID, including ``None`` for an empty selected branch.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime


def native_time(record: dict) -> int | None:
    """Return native epoch milliseconds, leaving unavailable times unknown."""
    value = record.get('timestamp')
    if type(value) is int:
        return value
    if isinstance(value, str):
        try:
            return int(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() * 1000)
        except ValueError:
            pass
    return None


def _entry_messages(entry: dict) -> list[dict]:
    """Apply Pi's entry-to-context mapping without altering retained records."""
    kind = entry['type']
    if kind == 'message':
        message = deepcopy(entry['message'])
        if message.get('content') is None:
            if message['role'] == 'system':
                message['content'] = ''
            elif message['role'] in {'user', 'assistant', 'toolResult'}:
                message['content'] = []
        return [message]
    if kind == 'custom_message':
        return [{'role': 'custom', 'customType': entry['customType'],
                 'content': deepcopy(entry['content']) if entry.get('content') is not None else [],
                 'display': entry['display'],
                 **({'details': deepcopy(entry['details'])} if 'details' in entry else {}),
                 'timestamp': native_time(entry)}]
    if kind == 'branch_summary' and entry.get('summary'):
        return [{'role': 'branchSummary', 'summary': entry['summary'],
                 'fromId': entry['fromId'], 'timestamp': native_time(entry)}]
    if kind == 'compaction':
        summary = {'role': 'compactionSummary', 'summary': entry['summary'],
                   'tokensBefore': entry['tokensBefore'], 'timestamp': native_time(entry)}
        return ([deepcopy(entry['systemMessage'])] if entry.get('systemMessage') else []) + [summary]
    return []


def project_messages(entries: list[dict], leaf_id: str | None) -> list[dict]:
    """Return Pi runtime messages for one native branch and context boundary.

    Entries stay in native file order. Missing chain members are reported
    rather than silently turning a partial collection into complete history.
    Display-only custom entries never add model messages. Unknown message
    fields, signatures, ciphertext and both timestamp representations survive.
    """
    if leaf_id is None:
        return []
    by_id = {entry['id']: entry for entry in entries}
    path = []
    current = leaf_id
    seen = set()
    while current is not None:
        if current not in by_id or current in seen:
            raise ValueError('Pi selected native parent chain is incomplete.')
        seen.add(current)
        entry = by_id[current]
        path.append(entry)
        current = entry['parentId']
    path.reverse()

    compaction_index = next((i for i in range(len(path) - 1, -1, -1)
                             if path[i]['type'] == 'compaction'), None)
    if compaction_index is not None:
        compaction = path[compaction_index]
        kept = []
        found = False
        for entry in path[:compaction_index]:
            found |= entry['id'] == compaction['firstKeptEntryId']
            if found and not (entry['type'] == 'message' and entry['message']['role'] == 'system'):
                kept.append(entry)
        path = [compaction, *kept, *path[compaction_index + 1:]]

    edits = {entry['targetId']: entry for entry in path if entry['type'] == 'context_edit'}
    messages = []
    for index, entry in enumerate(path):
        if entry['type'] == 'compaction' and index > 0:
            continue
        projected = _entry_messages(entry)
        if entry['id'] in edits:
            replacement = edits[entry['id']]['replacement']
            if replacement is None:
                continue
            for message in projected:
                if message['role'] in {'user', 'assistant', 'toolResult', 'custom'}:
                    content = deepcopy(replacement['content'])
                    if message['role'] in {'assistant', 'toolResult'} and isinstance(content, str):
                        content = [{'type': 'text', 'text': content}]
                    message['content'] = content
        messages.extend(projected)
    return messages
