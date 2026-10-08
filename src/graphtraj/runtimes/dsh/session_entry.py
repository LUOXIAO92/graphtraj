"""DSH native Session headers and per-execution shell associations."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import yaml

from graphtraj.execution.runner_models import RunnerError


def session_source(header: dict) -> str:
    """Use durable delegation facts; ordinary fork lineage is not delegation."""
    if header.get('origin') == 'subagent' or header.get('delegationDepth', 0) > 0:
        return 'child'
    if (header.get('version') == 4 and isinstance(header.get('id'), str) and header['id']
            and header.get('origin') is None and isinstance(header.get('isSeeded'), bool)):
        return 'main'
    return 'unknown'


def current_connection() -> dict | None:
    """Use DSH's rebuilt shell namespace, never inherited GraphTraj Main flags."""
    session = os.environ.get('DSH_SESSION_ID')
    if not session:
        return None
    if os.environ.get('DSH_GRAPHTRAJ_SESSION') != session:
        raise RunnerError('authority-denied', 'The DSH native Session association is unavailable or stale.')
    source = os.environ.get('DSH_GRAPHTRAJ_SOURCE')
    if source not in {'main', 'child'}:
        raise RunnerError('authority-denied', 'Unknown DSH Session source; Main was not associated.')
    return {'runtime': 'dsh', 'session': session, 'source': source}


def verify_main(connection: dict) -> str:
    """Verify the actual agent/created header before retaining a Main association."""
    header = connection.pop('native_header', None)
    if (not isinstance(header, dict) or header.get('id') != connection['session']
            or session_source(header) != 'main' or connection.get('source') != 'main'):
        raise RunnerError('authority-denied', 'A child or unknown DSH source cannot associate Main.')
    return connection['session']


def caller_identity(runner: Path, connection: dict) -> str | None:
    """Keep native children outside Main even under a shared DSH process."""
    if connection['source'] == 'child':
        return connection['session']
    key = hashlib.sha256(('dsh:' + connection['session']).encode()).hexdigest()
    path = runner / 'main-sessions' / ('finalize_' + key) / 'session.yml'
    if not path.is_file():
        raise RunnerError('authority-denied', 'DSH native start/resume association is unavailable.')
    binding = yaml.safe_load(path.read_text(encoding='utf-8'))
    if binding['connection'] != connection:
        raise RunnerError('authority-denied', 'The DSH native Session association is stale.')
    return None
