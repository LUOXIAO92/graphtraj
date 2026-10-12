"""Incremental, credential-filtered views of existing native Session Traces.

Cursors retain offsets and source positions for rebuilding normalization context.
No Trace copy is persisted. Event IDs are stable across observer reconnection.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import json
import os
from pathlib import Path
import re
from typing import Any


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
        if block.get('type') in {'text', 'input_text', 'output_text', 'thinking', 'summary_text', 'reasoning', 'reasoning_text'}:
            parts.append(block.get('text', block.get('thinking', '')))
        elif block.get('type') not in {'toolCall', 'tool-call'}:
            parts.append('[Nontext content: ' + str(block.get('type', 'unknown')) + ']')
    return '\n'.join(parts)


_TEXT_BLOCK_TYPES = frozenset({
    'text', 'input_text', 'output_text', 'summary_text', 'reasoning_text', 'content',
})
_IMAGE_BLOCK_TYPES = frozenset({'image', 'input_image', 'output_image', 'image_url'})
_UNSET = object()


def tool_content(value: Any) -> list[dict]:
    """Project a native tool result into ordered, readable content parts.

    Each part is one of:

    - ``{'type': 'text', 'text': str}`` for text blocks and plain strings,
    - ``{'type': 'image', 'mime': str | None, 'data': str | None, ...}`` keeping
      the native media type and base64 payload (or a non-data ``url``),
    - ``{'type': 'unknown', 'label': str}`` for shapes this adapter cannot read.

    Native order and text/image association are preserved. A JSON-encoded block
    list (Codex ``custom_tool_call_output``) is decoded, a structured object
    payload is read by content meaning, and an unreadable shape becomes an
    explicit fallback note. The whole protocol object is never returned as one
    opaque blob, and image bytes never appear inside a text part.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return _string_content(value)
    if isinstance(value, list):
        return _block_content(value)
    if isinstance(value, dict):
        if _is_block(value):
            return _block_content([value])
        return [{'type': 'text', 'text': _object_text(value)}]
    return [{'type': 'text', 'text': str(value)}]


def _string_content(value: str) -> list[dict]:
    """Read a tool output that may be a JSON-encoded native content-block list."""
    stripped = value.strip()
    if stripped[:1] in ('[', '{'):
        try:
            parsed = json.loads(stripped)
        except ValueError:
            parsed = _UNSET
        if parsed is not _UNSET and isinstance(parsed, list) and all(_is_block(item) for item in parsed):
            return _block_content(parsed)
        if _is_block(parsed):
            return _block_content([parsed])
        if parsed is not _UNSET:
            if isinstance(parsed, dict):
                # A structured payload reads by content meaning, not as a protocol dump.
                return [{'type': 'text', 'text': _object_text(parsed)}]
            return [{'type': 'text', 'text': json.dumps(parsed, ensure_ascii=False)}]
    return [{'type': 'text', 'text': value}]


def _object_text(value: dict) -> str:
    """Read a structured object payload as ``key: value`` lines.

    Each top-level field becomes one readable line so meaningful fields such as
    a status or a summary stay visible; the full object is kept in the raw
    result for on-demand technical details. No tool name is special-cased.
    """
    return '\n'.join(f'{key}: {_field_text(item)}' for key, item in value.items())


def _field_text(value: Any) -> str:
    """Read one object field: scalars plainly, flat lists inline, else compact JSON."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if value is None:
        return 'null'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list) and all(not isinstance(item, (dict, list)) for item in value):
        return ', '.join(_field_text(item) for item in value)
    return json.dumps(value, ensure_ascii=False)


def _block_content(blocks: list) -> list[dict]:
    """Project native content blocks in their recorded order."""
    parts: list[dict] = []
    for block in blocks:
        if isinstance(block, str):
            parts.append({'type': 'text', 'text': block})
        elif isinstance(block, dict):
            parts.extend(_block_parts(block))
        else:
            parts.append({'type': 'text', 'text': json.dumps(block, ensure_ascii=False)})
    return parts


def _block_parts(block: dict) -> list[dict]:
    """Project one content block, descending into wrapper blocks to keep order."""
    kind = block.get('type')
    if kind in _IMAGE_BLOCK_TYPES:
        image = _image_part(block)
        if image is not None:
            return [image]
    if kind in _TEXT_BLOCK_TYPES:
        text = block.get('text', block.get('content'))
        if isinstance(text, str):
            return [{'type': 'text', 'text': text}]
        return [{'type': 'unknown', 'label': str(kind)}]
    # Wrapper blocks (for example a nested tool-result) keep their inner content.
    nested = block.get('content')
    if isinstance(nested, (str, list, dict)):
        return _block_content(nested if isinstance(nested, list) else [nested])
    text = block.get('text')
    if isinstance(text, str) and text:
        return [{'type': 'text', 'text': text}]
    return [{'type': 'unknown', 'label': str(kind or 'object')}]


def _is_block(value: Any) -> bool:
    """Report whether a parsed JSON value is a typed native content block."""
    return isinstance(value, dict) and isinstance(value.get('type'), str)


def _image_part(block: dict) -> dict | None:
    """Keep a native image block as a previewable mime/data (or url) part."""
    source = block.get('source') if isinstance(block.get('source'), dict) else {}
    mime = (block.get('mimeType') or block.get('mime_type') or block.get('media_type')
            or block.get('mime') or source.get('media_type') or source.get('mime_type'))
    data = block.get('data') if isinstance(block.get('data'), str) else source.get('data')
    url = block.get('image_url', block.get('imageUrl', block.get('url')))
    if isinstance(url, dict):
        url = url.get('url')
    if isinstance(url, str) and url.startswith('data:'):
        # Split a data URL so the renderer never has to parse the encoding itself.
        header, _, payload = url.partition(',')
        mime = mime or header[5:].split(';')[0]
        data = data or payload
        url = None
    part: dict = {'type': 'image', 'mime': mime if isinstance(mime, str) else None,
                  'data': data if isinstance(data, str) else None}
    if isinstance(url, str):
        part['url'] = url
    if part['data'] is None and 'url' not in part:
        return None
    return part


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


_CURSOR_KEY = secrets.token_bytes(32)


class TraceReader:
    """Read bounded pages with restartable, source-bound byte checkpoints.

    A cursor carries record positions, never caller-supplied normalization data
    or a path. Context is reconstructed from the selected source's own records.
    """

    def __init__(self, path: Path, runtime: str, session: str) -> None:
        """Bind one recorded native Trace, never a renderer-supplied path."""
        self.path = path
        self.runtime = runtime
        self.session = session
        self.source = fingerprint([str(path), runtime, session])
        # Desktop owns a persistent random key; other observers use process lifetime.
        self.key = os.environ.get('GRAPHTRAJ_DESKTOP_CURSOR_KEY', '').encode() or _CURSOR_KEY
        self.used: set[str | None] = set()

    def page(self, cursor: str | None = None) -> dict:
        """Read at most 200 lines/2 MiB; partial final lines remain pending.

        Small head/tail fingerprints detect replacement and truncate/regrow at
        the checkpoint. Rotation requires replay; native usage identities dedup
        retained facts. Missing rotated-away records are explicitly uncovered.
        """
        replay = cursor in self.used
        self.used.add(cursor)
        if len(self.used) > 512:
            self.used.pop()
        checkpoint = None
        if cursor:
            try:
                data, signature = cursor.rsplit('.', 1)
                expected = hmac.new(self.key, data.encode(), 'sha256').hexdigest()
                if not hmac.compare_digest(expected, signature):
                    raise ValueError('Invalid checkpoint signature')
                checkpoint = json.loads(base64.urlsafe_b64decode(data))
                if (checkpoint['version'] != 1 or checkpoint['source'] != self.source
                        or type(checkpoint['offset']) is not int or checkpoint['offset'] < 0
                        or not isinstance(checkpoint.get('tools', {}), dict)
                        or any(not isinstance(call, str) or type(pos) is not int
                               or not 0 <= pos < checkpoint['offset']
                               for call, pos in checkpoint.get('tools', {}).items())
                        or not isinstance(checkpoint['context'], list)
                        or len(checkpoint['context']) > 64
                        or any(type(pos) is not int or not 0 <= pos < checkpoint['offset']
                               for pos in checkpoint['context'])):
                    raise ValueError('Invalid checkpoint')
            except (ValueError, KeyError, TypeError):
                return {'events': [], 'availability': 'cursor-expired', 'cursor': None}
        offset = checkpoint['offset'] if checkpoint else 0
        context: dict = {}
        positions: dict = {}
        read_records = 0
        tool_positions = dict(checkpoint.get('tools', {})) if checkpoint else {}
        try:
            with self.path.open('rb') as stream:
                stat = os.fstat(stream.fileno())
                current = [stat.st_dev, stat.st_ino]

                def guards(end: int) -> list[str]:
                    """Fingerprint bounded bytes already consumed, ignoring later appends."""
                    stream.seek(0)
                    head = stream.read(min(end, 256))
                    stream.seek(max(0, end - 256))
                    tail = stream.read(min(end, 256))
                    return [hashlib.sha256(part).hexdigest() for part in (head, tail)]

                if checkpoint and (checkpoint['file'] != current or stat.st_size < offset
                                   or checkpoint['guards'] != guards(offset)):
                    return {'events': [], 'availability': 'trace-changed', 'cursor': None,
                            'reason': 'Source changed; replaying retained records. Unread rotated history may be unavailable.'}
                if checkpoint:
                    for position in sorted(set(checkpoint['context'])):
                        stream.seek(position)
                        record = json.loads(stream.readline())
                        before = dict(context)
                        normalize(self.runtime, record, context)
                        read_records += 1
                        for key in context:
                            if key != 'tools' and (key not in before or context[key] != before[key]):
                                positions[key] = position
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
                        # Resolve only the requested result's call. Rebuilding every
                        # historical tool name on each page defeats incremental reads.
                        payload = record.get('payload', {})
                        call_id = payload.get('call_id')
                        if (self.runtime == 'codex' and payload.get('type') in {
                                'function_call_output', 'custom_tool_call_output', 'local_shell_call_output'}
                                and call_id in tool_positions and call_id not in context.get('tools', {})):
                            resume = stream.tell()
                            stream.seek(tool_positions[call_id])
                            call = json.loads(stream.readline())
                            tool_context: dict = {}
                            normalize(self.runtime, call, tool_context)
                            context.setdefault('tools', {}).update(tool_context.get('tools', {}))
                            read_records += 1
                            stream.seek(resume)
                        before = dict(context)
                        projected = normalize(self.runtime, record, context)
                        for key in context:
                            if key == 'tools':
                                for tool, name in context[key].items():
                                    if before.get(key, {}).get(tool) != name:
                                        tool_positions[tool] = position
                            elif key not in before or context[key] != before[key]:
                                positions[key] = position
                    except (ValueError, TypeError, KeyError, AttributeError):
                        projected = [{'kind': 'notice', 'text': 'Native record is unreadable.'}]
                    read_records += 1
                    for index, event in enumerate(projected):
                        event.update(replayed=replay, id=f'{self.session}:{current[0]}:{current[1]}:{position}:{index}',
                                     source={'runtime': self.runtime, 'trace': str(self.path), 'offset': position},
                                     time=record.get('timestamp', record.get('time')) if isinstance(record, dict) else None)
                        events.append(redact(event))
                    if stream.tell() - start >= 2 * 1024 * 1024:
                        break
                offset = stream.tell()
                more = offset < stat.st_size
                token = base64.urlsafe_b64encode(json.dumps({
                    'version': 1, 'source': self.source, 'offset': offset,
                    'file': current, 'guards': guards(offset),
                    'context': sorted(set(positions[key] for key in context if key in positions)),
                    'tools': tool_positions,
                }, separators=(',', ':')).encode()).decode()
                token += '.' + hmac.new(self.key, token.encode(), 'sha256').hexdigest()
        except (OSError, UnicodeError, ValueError, KeyError, TypeError):
            return {'events': [], 'availability': 'unavailable', 'cursor': cursor,
                    'reason': 'Native Trace or checkpoint context is missing or unreadable.'}
        return {'events': events, 'cursor': token, 'has_more': more,
                'availability': 'available', 'waiting_for_record': more and offset == start,
                'read_records': read_records}


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
