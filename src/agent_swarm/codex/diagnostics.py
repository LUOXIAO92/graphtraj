"""Redact native connection diagnostics before returning them."""
from typing import Any
import os
import re

_SECRET = re.compile(
    r'(?i)(api[_-]?key|authorization|password|secret|credential|access[_-]?token|'
    r'refresh[_-]?token|(?:^|[_-])token$|cookie)'
)
_ASSIGNMENT = re.compile(
    # Start once per key, not at every character of long text/image payloads.
    r'''(?ix)(?<![\w-])(["']?[\w-]*(?:api[_-]?key|secret|password|access[_-]?token|
    refresh[_-]?token|credential|token|authorization|cookie)["']?\s*[:=]\s*)
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


