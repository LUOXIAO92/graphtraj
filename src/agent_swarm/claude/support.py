"""Native transcript, credential and diagnostic helpers."""
from __future__ import annotations
import os
import re
import tempfile
from pathlib import Path
from typing import Any
import yaml
from agent_swarm.runtime import RuntimeAdapterError

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


def credential_environment(name: str | None) -> dict[str, str]:
    """Require a named execution credential without retaining or exposing its value."""
    import os
    import re

    if name is None:
        return {}
    if not isinstance(name, str) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
        raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'api_key_env must name an environment variable.')
    value = os.environ.get(name)
    if not value:
        raise RuntimeAdapterError('RUNTIME_CREDENTIAL_MISSING', 'The configured api_key_env is missing or empty.')
    return {name: value}


def write_yaml_durably(path: Path, value: dict) -> None:
    """Atomically replace one owner's nonsecret diagnostic document."""
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            yaml.safe_dump(value, stream, allow_unicode=True)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
