"""Pi Session entry facts and supported plugin delegation markers.

Supported plugins are nicobailon/pi-subagents and mjakl/pi-subagent. An absent
persistent Session (including the basic --no-session example) is not Main.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping


def session_source(header: dict, entries: list[dict], environment: Mapping[str, str]) -> str:
    """Read origin from the native Session and the plugins' startup markers.

    A copied delegation entry belongs only to its containing childSessionId.
    parentSession is history lineage, so a user fork is not itself delegation.
    """
    if environment.get('PI_SUBAGENT_CHILD') == '1':
        return 'child'
    depth = environment.get('PI_SUBAGENT_DEPTH', '0')
    try:
        if int(depth) > 0:
            return 'child'
    except ValueError:
        return 'unknown'
    if header.get('parentSessionId') or header.get('depth', 0) > 0:
        return 'child'
    for entry in entries:
        if entry.get('type') == 'custom' and entry.get('customType') == 'graphtraj:completion-checker':
            if entry.get('data', {}).get('session') == header.get('id'):
                return 'child'
        if entry.get('type') == 'custom' and entry.get('customType') == 'pi-subagent:delegation':
            data = entry.get('data', {})
            if data.get('childSessionId') == header.get('id'):
                if data.get('version') == 1 and isinstance(data.get('parentSessionId'), str):
                    return 'child'
                return 'unknown'
    if (header.get('type') == 'session' and header.get('version') == 3
            and isinstance(header.get('id'), str) and header['id']
            and isinstance(header.get('cwd'), str)):
        return 'main'
    return 'unknown'


def session_record(path: Path, session: str) -> tuple[dict, list[dict]]:
    """Read Pi's own JSONL, refusing inherited paths for another active Session."""
    with path.open(encoding='utf-8') as stream:
        header = json.loads(next(stream))
        entries = [json.loads(line) for line in stream]
    if header.get('id') != session:
        raise ValueError('The Pi Session association is stale.')
    return header, entries


def current_connection() -> dict | None:
    """Capture only the per-call association injected by Pi's native extension."""
    if os.environ.get('GRAPHTRAJ_NATIVE_RUNTIME') != 'pi':
        return None
    session = os.environ.get('GRAPHTRAJ_NATIVE_SESSION')
    path = os.environ.get('GRAPHTRAJ_NATIVE_SESSION_FILE')
    if not session or not path:
        raise ValueError('The Pi native Session association is unavailable.')
    return {'runtime': 'pi', 'session': session, 'session_file': path}


def verify_main(connection: dict) -> str:
    """Associate only a native start/resume root, never a supported plugin child."""
    header = connection.pop('native_header', None)
    entries = connection.pop('native_entries', [])
    if header is None:
        header, entries = session_record(Path(connection['session_file']), connection['session'])
    if header.get('id') != connection['session'] or session_source(header, entries, os.environ) != 'main':
        raise ValueError('A child or unknown Pi source cannot associate Main.')
    return connection['session']


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
