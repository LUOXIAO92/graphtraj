"""Incremental, credential-filtered views of existing native Session Traces.

Cursors retain only offsets and normalization context in the observing process.
No Trace copy is persisted. Event IDs are stable across observer reconnection.
"""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
import uuid


_SECRET = re.compile(
    r'(?i)(api[_-]?key|authorization|password|secret|credential|access[_-]?token|'
    r'refresh[_-]?token|(?:^|[_-])token$|cookie)'
)
_ASSIGNMENT = re.compile(
    r'''(?ix)((?:["']?[\w-]*(?:api[_-]?key|secret|password|access[_-]?token|
    refresh[_-]?token|credential|token)["']?|authorization|cookie)\s*[:=]\s*)
    (?:"[^"]*"|'[^']*'|[^\s,{};]+)'''
)


def redact(value: Any) -> Any:
    """Remove credential fields and recognizable credentials before IPC or copying."""
    if isinstance(value, dict):
        return {key: '[redacted]' if _SECRET.search(key) else redact(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if not isinstance(value, str):
        return value
    for name, secret in os.environ.items():
        if _SECRET.search(name) and len(secret) >= 6:
            value = value.replace(secret, '[redacted]')
    value = re.sub(r'(?i)\bBearer\s+[^\s"\'<>]+', 'Bearer [redacted]', value)
    value = re.sub(r'\bsk-[A-Za-z0-9_-]{8,}', '[redacted]', value)
    value = re.sub(r'(https?://)[^/\s:@]+:[^/\s@]+@', r'\1[redacted]@', value)
    return _ASSIGNMENT.sub(r'\1"[redacted]"', value)


def text_content(content: Any) -> str:
    """Render readable native text, explicitly identifying nontext blocks."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ''
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get('type') in {'text', 'input_text', 'output_text', 'thinking', 'summary_text', 'reasoning'}:
            parts.append(block.get('text', block.get('thinking', '')))
        elif block.get('type') not in {'toolCall', 'tool-call'}:
            parts.append('[Nontext content: ' + str(block.get('type', 'unknown')) + ']')
    return '\n'.join(parts)


def usage_fact(raw: dict, runtime: str, call_id: str | None, phase: str) -> dict:
    """Keep reported fields and semantic token names; never fill missing metrics."""
    names = {
        'codex': {'input_tokens': 'input', 'output_tokens': 'output',
                  'cached_input_tokens': 'cache_read', 'cache_write_input_tokens': 'cache_write',
                  'reasoning_output_tokens': 'reasoning'},
        'pi': {'input': 'input_uncached', 'output': 'output', 'cacheRead': 'cache_read',
               'cacheWrite': 'cache_write'},
        'dsh': {'inputTokens': 'input_uncached', 'outputTokens': 'output', 'cacheReadTokens': 'cache_read',
                'cacheWriteTokens': 'cache_write', 'reasoningTokens': 'reasoning'},
    }
    tokens = {target: raw[key] for key, target in names[runtime].items()
              if isinstance(raw.get(key), (int, float)) and not isinstance(raw[key], bool)}
    # Pi and DSH's DeepSeek Messages adapter keep cache input separate.
    if runtime in {'pi', 'dsh'} and all(key in tokens for key in ('input_uncached', 'cache_read', 'cache_write')):
        tokens['input'] = tokens['input_uncached'] + tokens['cache_read'] + tokens['cache_write']
    return {'provider_usage': raw, 'tokens': tokens, 'call_id': call_id,
            'phase': phase, 'attributable': call_id is not None}


class TraceReader:
    """Read bounded pages, with opaque in-memory cursors and stable source identities."""

    def __init__(self, path: Path, runtime: str, session: str) -> None:
        """Bind one recorded native Trace, never a renderer-supplied path."""
        self.path = path
        self.runtime = runtime
        self.session = session
        self.used_cursors: set[str] = set()
        self.cursors: OrderedDict[str, tuple[int, dict, tuple[int, int]]] = OrderedDict()

    def page(self, cursor: str | None = None) -> dict:
        """Read up to 200 records, stopping after 2 MiB or one larger record.

        Incomplete trailing JSON lines remain pending until the writer finishes.
        Repeated cursors replay the same source IDs. A replaced/truncated Trace
        or expired observer cursor requires explicit replay from the beginning.
        """
        replay = cursor in self.used_cursors if cursor else bool(self.cursors)
        offset, context, identity = (0, {}, None)
        if cursor:
            if cursor not in self.cursors:
                return {'events': [], 'availability': 'cursor-expired', 'cursor': None}
            offset, previous, identity = self.cursors[cursor]
            self.used_cursors.add(cursor)
            context = dict(previous)
        try:
            with self.path.open('rb') as stream:
                stat = os.fstat(stream.fileno())
                current = (stat.st_dev, stat.st_ino)
                if identity is not None and (identity != current or stat.st_size < offset):
                    return {'events': [], 'availability': 'trace-changed', 'cursor': None}
                stream.seek(offset)
                events = []
                start = offset
                for _ in range(200):
                    position = stream.tell()
                    line = stream.readline()
                    if not line or not line.endswith(b'\n'):
                        stream.seek(position)
                        break
                    record = None
                    try:
                        record = json.loads(line)
                        projected = normalize(self.runtime, record, context)
                    except (ValueError, TypeError, KeyError, AttributeError):
                        projected = [{'kind': 'notice', 'text': 'Native record is unreadable.'}]
                    for index, event in enumerate(projected):
                        event.update(replayed=replay, id=f'{self.session}:{current[0]}:{current[1]}:{position}:{index}',
                                     source={'runtime': self.runtime, 'trace': str(self.path), 'offset': position},
                                     time=record.get('timestamp', record.get('time')) if isinstance(record, dict) else None)
                        events.append(redact(event))
                    if stream.tell() - start >= 2 * 1024 * 1024:
                        break
                offset = stream.tell()
                more = offset < stat.st_size
        except (OSError, UnicodeError):
            return {'events': [], 'availability': 'unavailable', 'cursor': cursor,
                    'reason': 'Native Trace is missing or inaccessible.'}
        token = uuid.uuid4().hex
        self.cursors[token] = (offset, context, current)
        # ponytail: retain 512 page checkpoints; older cursors explicitly replay.
        while len(self.cursors) > 512:
            expired, _ = self.cursors.popitem(last=False)
            self.used_cursors.discard(expired)
        return {'events': events, 'cursor': token, 'has_more': more,
                'availability': 'available', 'waiting_for_record': more and offset == start}


def normalize(runtime: str, record: dict, context: dict) -> list[dict]:
    """Delegate native record interpretation to its Runtime's implementation."""
    if runtime == 'codex':
        from graphtraj.runtimes.codex.activity import project
    elif runtime == 'pi':
        from graphtraj.runtimes.pi.activity import project
    elif runtime == 'dsh':
        from graphtraj.runtimes.dsh.activity import project
    else:
        return [{'kind': 'notice', 'text': 'Runtime activity format is unsupported.'}]
    return project(record, context)


def fingerprint(value: Any) -> str:
    """Give a replayed usage observation a stable identity, not a provider request ID."""
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:24]
