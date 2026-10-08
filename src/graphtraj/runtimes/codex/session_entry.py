"""Read Codex's own lifecycle records at the external Main boundary."""

from __future__ import annotations

import json
import asyncio
from pathlib import Path
from typing import Any


def session_record(path: Path, turn: str | None = None) -> tuple[dict, dict]:
    """Read identity and the requested turn settings from a native rollout.

    Conversation items are neither returned nor copied into environment values.
    A fork's historical contexts cannot substitute for the requested live turn.
    """
    metadata: dict[str, Any] = {}
    context: dict[str, Any] = {}
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            record = json.loads(line)
            payload = record.get('payload', {})
            if record.get('type') == 'session_meta':
                metadata = payload
            elif record.get('type') == 'turn_context':
                if turn is None or payload.get('turn_id') == turn:
                    context = payload
    if not isinstance(metadata.get('id'), str) or not metadata['id']:
        raise ValueError('Codex Session metadata is unavailable.')
    if turn is not None and not context:
        raise ValueError('Codex settings for the checked turn are unavailable.')
    return metadata, context


def session_source(metadata: dict) -> str:
    """Distinguish an explicit native root from delegated and unknown sources.

    forked_from_id is history lineage, not delegation. Both persisted and public
    thread metadata spellings are accepted at their respective native entries.
    """
    source = metadata.get('source')
    if isinstance(source, dict) and ('subagent' in source or 'subAgent' in source):
        return 'child'
    if metadata.get('parent_thread_id') or metadata.get('parentThreadId'):
        return 'child'
    if isinstance(source, str) and source in {'cli', 'vscode', 'exec', 'appServer'}:
        return 'main'
    return 'unknown'


def event_record(event: dict) -> tuple[dict, dict]:
    """Read the transcript supplied by SessionStart/Stop, never a model hint."""
    path = event.get('transcript_path')
    if not isinstance(path, str) or not path:
        raise ValueError('Codex did not supply its native transcript path.')
    turn = event.get('turn_id') if event.get('hook_event_name') == 'Stop' else None
    if event.get('hook_event_name') == 'Stop' and not turn:
        raise ValueError('Codex Stop did not identify its current turn.')
    metadata, context = session_record(Path(path), turn)
    return metadata, context


def caller_identity(runner: Path, connection: dict) -> str | None:
    """Resolve the native caller against its source and existing association.

    A native child remains a child even if it inherited the parent's GraphTraj
    environment. Ordinary human CLI calls never enter this Runtime boundary.
    """
    import hashlib
    import yaml
    from graphtraj.runtimes.codex.finalize import proxy
    from graphtraj.execution.runner_models import RunnerError

    async def read() -> dict:
        """Query metadata through the already owning native service."""
        async with proxy(connection) as client:
            return await client.read_thread(connection['session'])

    thread = asyncio.run(read())
    session = thread['id']
    source = session_source(thread)
    if source == 'child':
        return session
    for path in (runner / 'main-sessions').glob('*/checks/*/session.yml'):
        child = yaml.safe_load(path.read_text(encoding='utf-8'))
        if child['runtime'] == 'codex' and child['session'] == session:
            return session
    key = hashlib.sha256(('codex:' + session).encode()).hexdigest()
    path = runner / 'main-sessions' / ('finalize_' + key) / 'session.yml'
    if source != 'main' or not path.is_file():
        raise RunnerError('authority-denied', 'Native Main SessionStart/resume association is unavailable.')
    binding = yaml.safe_load(path.read_text(encoding='utf-8'))
    if (binding['session'] != session or binding['runtime'] != 'codex'
            or binding['connection']['hook_session'] != thread.get('sessionId')):
        raise RunnerError('authority-denied', 'The native Main Session association is stale.')
    return None
