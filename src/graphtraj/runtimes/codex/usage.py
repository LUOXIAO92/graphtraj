"""Incremental finish-check facts from Codex's existing native rollout."""

from __future__ import annotations

import json
from pathlib import Path

from graphtraj.runtimes.runtime_adapter import CheckUsage


def tool_call_id(payload: dict) -> str | None:
    """Identify native requests, sharing the Session operation counter's rules."""
    kind = payload.get('type')
    if kind in {'function_call', 'custom_tool_call'}:
        value = payload.get('call_id')
    elif kind in {'local_shell_call', 'tool_search_call'}:
        value = payload.get('call_id') or payload.get('id')
    elif kind in {'web_search_call', 'image_generation_call'}:
        value = payload.get('id')
    else:
        return None
    return value if isinstance(value, str) and value else None


def _total(record: dict) -> dict | None:
    """Read only an explicit native lifetime token snapshot."""
    payload = record.get('payload', {})
    if record.get('type') != 'event_msg' or payload.get('type') != 'token_count':
        return None
    info = payload.get('info')
    total = info.get('total_token_usage') if isinstance(info, dict) else None
    return total if isinstance(total, dict) else None


class CodexCheckUsage:
    """Capture a fork baseline before execution and consume its appended records.

    Codex total_token_usage is cumulative across inherited history; last usage
    can be replayed with rate-limit updates and has no independent request ID.
    Subtract only observed baseline fields, never infer them from last usage.
    output_tokens already includes reasoning_output_tokens: expose reasoning
    separately without adding it to output. Model requests remain unavailable.
    Missing/unreadable telemetry does not change the completion decision.
    """

    def __init__(self, path: Path | None, session: str) -> None:
        """Remember the exact native file boundary before the checker starts."""
        self.path = path
        self.offset = 0
        self.baseline: dict = {}
        self.calls: set[str] = set()
        self.ready = False
        if path is None:
            return
        try:
            identity = None
            with path.open('rb') as stream:
                # Read the inherited history once; keep only counters and IDs.
                for line in stream:
                    if not line.endswith(b'\n'):
                        return
                    record = json.loads(line)
                    if record.get('type') == 'session_meta':
                        identity = record['payload'].get('id')
                    total = _total(record)
                    if total is not None:
                        self.baseline = total
                    if record.get('type') == 'response_item':
                        call = tool_call_id(record.get('payload', {}))
                        if call is not None:
                            self.calls.add(call)
                self.offset = stream.tell()
            self.ready = identity == session
        except (OSError, ValueError, TypeError, KeyError):
            return

    def finish(self, turn: str) -> CheckUsage:
        """Count only complete appended records associated with this native turn."""
        if not self.ready or self.path is None:
            return CheckUsage()
        try:
            with self.path.open('rb') as stream:
                stream.seek(self.offset)
                data = stream.read()
            lines = data.splitlines()
            if data and not data.endswith(b'\n'):
                lines = lines[:-1]
            current = None
            total = None
            calls = set()
            completed = False
            for line in lines:
                record = json.loads(line)
                payload = record.get('payload', {})
                if record.get('type') == 'turn_context':
                    current = payload.get('turn_id')
                elif record.get('type') == 'event_msg' and payload.get('type') == 'task_started':
                    current = payload.get('turn_id')
                if current != turn:
                    continue
                snapshot = _total(record)
                if snapshot is not None:
                    total = snapshot
                if record.get('type') == 'response_item':
                    call = tool_call_id(payload)
                    if call is not None and call not in self.calls:
                        calls.add(call)
                if record.get('type') == 'event_msg' and payload.get('type') == 'task_complete':
                    completed = payload.get('turn_id') == turn
                    current = None
            # A partial native flush cannot establish a whole-check aggregate.
            if not completed:
                return CheckUsage()
            values = {}
            for field, native in (
                ('input_tokens', 'input_tokens'),
                ('cached_input_tokens', 'cached_input_tokens'),
                ('output_tokens', 'output_tokens'),
                ('reasoning_tokens', 'reasoning_output_tokens'),
            ):
                before = self.baseline.get(native)
                after = total.get(native) if total is not None else None
                if type(before) is int and type(after) is int and 0 <= before <= after:
                    values[field] = after - before
            return CheckUsage(**values, tool_calls=len(calls))
        except (OSError, ValueError, TypeError, KeyError):
            return CheckUsage()
