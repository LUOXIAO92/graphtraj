"""Bounded, redacted reads of one archived Session (the ``session_read`` feature).

A read chooses a view of the Session's ordered events, then takes one Python
slice of that view or searches it for a keyword. The views are:

- ``text`` (default): message events that carry conversation text, as text only;
- ``tools``: those plus tool calls and tool results;
- ``all``: every archived event as stored, attached records included.

Positions (``index``) count within the chosen view, so a search and the slice
that reads around its hits must use the same ``content``. Nothing here decides
who may read; callers authorize first.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .archive import JsonlSessionStore, SessionArchive, archive_path, redact

CONTENTS = ('text', 'tools', 'all')
# A read without start and stop returns this many of the last events.
DEFAULT_COUNT = 5
# A search returns at most this many hits, the last ones in its range.
SEARCH_HITS = 20
# Characters kept on each side of a search match.
SNIPPET_CHARACTERS = 80
RUNTIMES = ('codex', 'claude', 'pi', 'dsh')
MESSAGES = frozenset({'user/message', 'assistant/message', 'system/message', 'developer/message'})
OMITTED = {
    'text': "Tool calls, tool results, reasoning and attached records are omitted; "
            "set content to 'tools' or 'all' to include them.",
    'tools': "Reasoning and attached records are omitted; set content to 'all' to include them.",
}
_CONTROL = re.compile(r'(?i)(control[_-]?(key|socket|directory)|socket|request[_-]?token)')


def redact_session(value: Any) -> Any:
    """Remove credentials and control material (control keys, sockets, request tokens)."""
    return redact(_without_control(value))


def _without_control(value: Any) -> Any:
    """Replace values under control-material keys at any depth."""
    if isinstance(value, dict):
        return {key: '[redacted]' if _CONTROL.search(str(key)) else _without_control(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [_without_control(item) for item in value]
    return value


def find_session(root: Path, reference: str) -> JsonlSessionStore | None:
    """Open the archive under ``root`` for an archive ID or a native Session ID.

    A native ID selects the latest archive retained for it in any Runtime.
    Returns ``None`` when nothing under ``root`` matches; the reference is
    never used as a path.
    """
    path = archive_path(root, reference)
    if not path.is_file():
        archive = SessionArchive(root)
        for runtime in RUNTIMES:
            header = archive.native_header(runtime, reference)
            if header:
                reference, path = header['id'], archive_path(root, header['id'])
                break
    if not path.is_file():
        return None
    store = JsonlSessionStore(path)
    if store.header['id'] != reference:
        raise ValueError('Session archive identity does not match its location.')
    return store


def read_events(
    store: JsonlSessionStore,
    *,
    start: int | None = None,
    stop: int | None = None,
    content: str = 'text',
    search: str | None = None,
    redacted: bool = True,
) -> dict:
    """Read one slice of a view, or search it, and return a bounded document.

    ``start`` and ``stop`` slice the view exactly like a Python list; without
    both, a read returns the last ``DEFAULT_COUNT`` events and a search covers
    the whole view. A search is a case-insensitive literal match on the view's
    text values and returns hits (``index``, ``seq``, ``type``, ``snippet``),
    at most the last ``SEARCH_HITS`` of them. It also counts, over every
    archived event as grepping the archive would, the matching events that only
    a wider ``content`` shows (``outside_view``), and ``repeat`` says which
    ``content`` to search again with. ``redacted`` False is for an owner
    reading its own files; search then sees the unredacted text too.
    """
    for name, value in (('start', start), ('stop', stop)):
        if value is not None and type(value) is not int:
            raise ValueError(f'{name} must be an integer.')
    if content not in CONTENTS:
        raise ValueError(f"content must be one of {', '.join(CONTENTS)}.")
    if search is not None and (not isinstance(search, str) or not search):
        raise ValueError('search must be a nonempty string.')
    clean = redact_session if redacted else (lambda value: value)
    events = store.events()
    view = [item for item in (_view_item(event, content) for event in events) if item is not None]
    if search is None and start is None and stop is None:
        start = -DEFAULT_COUNT
    selected = range(len(view))[start:stop]
    # Only the selected range is returned or searched, so only it is redacted.
    picked = clean([view[index] for index in selected])
    document = {'session': store.header['id'], 'content': content, 'total': len(view),
                'start': selected.start, 'stop': max(selected.start, selected.stop)}
    if search is not None:
        document.update(_search(picked, selected, search))
        document.update(_outside_view(events, content, search, clean))
    else:
        document['events'] = [{'index': index, **item} for index, item in zip(selected, picked)]
        if selected.start > 0:
            count = len(selected) or DEFAULT_COUNT
            document['earlier'] = {'start': max(0, selected.start - count), 'stop': selected.start}
        drafts = clean(store.pending())
        document['pending'] = drafts if content == 'all' else [
            item for item in (_view_item(draft['event'], content) for draft in drafts) if item is not None]
    if content in OMITTED:
        document['omitted'] = OMITTED[content]
    else:
        document.update(header=clean(store.header), revision=store.revision)
        legacy = store.legacy()
        if legacy and search is not None:
            # Old evidence is not searched; a search names its size, and a read slices it.
            document['legacy'] = {'total': len(legacy['events'])}
        elif legacy:
            retained = range(len(legacy['events']))[start:stop]
            document['legacy'] = clean({**legacy, 'events': [legacy['events'][index] for index in retained],
                                        'total': len(legacy['events'])})
    return document


def _search(items: list[dict], selected: range, search: str) -> dict:
    """Return the last hits of ``search`` in ``items``, the view items at positions ``selected``."""
    pattern = re.compile(re.escape(search), re.IGNORECASE)
    hits = []
    for index, value in zip(selected, items):
        text = '\n'.join(_strings(value))
        match = pattern.search(text)
        if match:
            begin, end = max(0, match.start() - SNIPPET_CHARACTERS), match.end() + SNIPPET_CHARACTERS
            snippet = ('…' if begin else '') + text[begin:end] + ('…' if end < len(text) else '')
            item = value.get('event', value)
            hits.append({'index': index, 'seq': item['seq'], 'type': item['type'], 'snippet': snippet})
    found = {'search': search, 'hits_total': len(hits), 'hits': hits[-SEARCH_HITS:]}
    if len(hits) > SEARCH_HITS:
        found['earlier_hits'] = {'count': len(hits) - SEARCH_HITS, 'stop': found['hits'][0]['index']}
    return found


def _outside_view(events: list[dict], content: str, search: str, clean: Any) -> dict:
    """Count the archived events that match ``search`` only in a wider view than ``content``.

    The scope is every archived event in the Session, whatever ``start`` and
    ``stop`` are. Only events whose raw text matches are redacted and checked
    (all of them when the search matches the redaction mark), so the count
    stays cheap and a credential value never matches.
    """
    pattern = re.compile(re.escape(search), re.IGNORECASE)
    wider = CONTENTS[CONTENTS.index(content) + 1:]
    counts = dict.fromkeys(wider, 0)
    every = bool(pattern.search('[redacted]'))

    def matches(event: dict, view: str) -> bool:
        item = _view_item(event, view)
        return item is not None and bool(pattern.search('\n'.join(_strings(clean(item)))))

    for event in events:
        if (every or any(pattern.search(text) for text in _strings(event))) and not matches(event, content):
            for view in wider:
                counts[view] += matches(event, view)
    if not wider:
        repeat = 'This search covered every archived event.'
    elif not any(counts.values()):
        repeat = f"No archived event outside content '{content}' matches."
    else:
        repeat = (f"{max(counts.values())} more archived events match outside content '{content}'. Repeat the "
                  "search with " + ' or '.join(f"content '{view}' ({count} of them)" for view, count in counts.items()
                                               if count) + ' to get their positions.')
    return {'outside_view': counts, 'repeat': repeat}


def _strings(value: Any) -> list[str]:
    """Return the string values in ``value``, depth first; keys are not searched."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    return []


def _view_item(event: dict, content: str) -> dict | None:
    """Return ``event`` as it appears in the ``content`` view, or ``None`` when it is left out."""
    if content == 'all':
        return {'event': event}
    kind = event.get('type')
    if event.get('ignorable') or not isinstance(event.get('data'), dict):
        return None
    if kind == 'tool/call':
        data = event['data']
        return ({'seq': event['seq'], 'type': kind, 'content': [
            {'type': 'tool-call', 'name': data.get('name'), 'arguments': data.get('arguments')}]}
            if content == 'tools' else None)
    if kind not in MESSAGES and kind != 'tool/result':
        return None
    message = event['data'] if kind == 'user/message' else event['data'].get('message')
    blocks = message.get('content') if isinstance(message, dict) else None
    if isinstance(blocks, str):
        blocks = [{'type': 'text', 'text': blocks}]
    if not isinstance(blocks, list):
        return None
    if kind == 'tool/result':
        return ({'seq': event['seq'], 'type': kind, 'content': [
            {'type': 'tool-result', 'content': _text(blocks)}]} if content == 'tools' else None)
    kept = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get('type') == 'text' and isinstance(block.get('text'), str) and block['text'].strip():
            kept.append({'type': 'text', 'text': block['text']})
        elif content == 'tools' and block.get('type') == 'tool-call':
            kept.append({'type': 'tool-call', 'name': block.get('name'), 'arguments': block.get('arguments')})
        elif content == 'tools' and block.get('type') == 'tool_result':
            kept.append({'type': 'tool-result', 'content': _text(block.get('content')),
                         **({'is_error': True} if block.get('is_error') else {})})
    if not kept:
        return None
    if content == 'text':
        return {'seq': event['seq'], 'type': kind, 'text': '\n\n'.join(block['text'] for block in kept)}
    return {'seq': event['seq'], 'type': kind, 'content': kept}


def _text(value: Any) -> str:
    """Render a tool result's content as text, naming blocks that are not text."""
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ''
    return '\n'.join(block['text'] if isinstance(block, dict) and isinstance(block.get('text'), str)
                     else f"[{block.get('type') if isinstance(block, dict) else 'value'}]" for block in value)
