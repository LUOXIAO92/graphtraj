"""GraphTraj's Pi Main association over the independent native Session facts."""

from __future__ import annotations

import os
from pathlib import Path

from agent_swarm.pi.session import current_connection, session_record, session_source, verify_main

__all__ = ['caller_identity', 'current_connection', 'session_record', 'session_source', 'verify_main']


def caller_identity(runner: Path, connection: dict) -> str | None:
    """Use the current native Session before looking for any Main association."""
    import hashlib
    import yaml
    from graphtraj.execution.runner_models import RunnerError

    session = connection['session']
    header, entries = session_record(Path(connection['session_file']), session)
    source = session_source(header, entries, os.environ)
    if source == 'child':
        return session
    key = hashlib.sha256(('pi:' + session).encode()).hexdigest()
    path = runner / 'main-sessions' / ('finalize_' + key) / 'session.yml'
    if source != 'main' or not path.is_file():
        raise RunnerError('authority-denied', 'Pi SessionStart/resume association is unavailable.')
    binding = yaml.safe_load(path.read_text(encoding='utf-8'))
    if binding['connection'] != connection:
        raise RunnerError('authority-denied', 'The Pi Session association is stale.')
    return None
