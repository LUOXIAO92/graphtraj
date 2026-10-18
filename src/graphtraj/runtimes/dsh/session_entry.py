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


def collect_session(event: dict, cwd: Path) -> dict:
    """Archive only the native callback's Session under its observed ownership.

    Managed creation may precede Runner's native-ID receipt. Defer that early
    callback and replay it after binding, rather than registering it as Main.
    Native subagents and checkers never overwrite their owning Main's binding.
    """
    from graphtraj.configuration.project_configuration import load_project_configuration
    from graphtraj.execution.runner_status import process_caller_alias, read_alias_mapping
    from agent_swarm.sessions.dsh import DshArchive
    from graphtraj.interfaces.agents import configured_archive
    from graphtraj.workspace.runner_project import discover_runner_directory

    connection = current_connection()
    header = event['header']
    if (connection is None or header.get('id') != connection['session']
            or session_source(header) != connection['source']):
        raise ValueError('DSH collection does not match the native Session association.')
    runner = discover_runner_directory(cwd)
    alias = process_caller_alias(runner, os.getpid())
    task_ids = []
    agent_id = 'dsh:' + header['id']
    source = connection['source']
    if alias is not None:
        mapping, _ = read_alias_mapping(runner, alias)
        if mapping['runtime'] != 'dsh':
            raise ValueError('DSH collection belongs to another Runtime owner.')
        task_ids = [mapping['task_id']]
        if mapping['session'] == header['id']:
            agent_id, source = alias, 'member'
        elif source != 'child':
            raise ValueError('DSH collection belongs to another managed Session.')
    elif os.environ.get('GRAPHTRAJ_ROLE'):
        return {'deferred': True}
    elif source == 'main':
        caller_identity(runner, connection)

    configuration = load_project_configuration(cwd)
    archive = configured_archive(configuration.harness_root)
    boundary = event.get('history_boundary', -1)
    if type(boundary) is not int or boundary < -1:
        raise ValueError('DSH collection boundary must be a native sequence number.')
    collector = DshArchive(archive, resumed=boundary >= 0)
    collector.start({'header': header, 'cursor': boundary}, event['records'])
    if boundary >= 0 and not archive.backfill_history:
        for record in event['records']:
            if record['event']['seq'] > boundary:
                collector.event(record['event'])
    # This acknowledges receipt, including the explicit disabled-archive case;
    # it is not a claim that skipped historical events were normalized.
    position = max((record['event']['seq'] for record in event['records']), default=-1)
    return {'session': archive.native_id('dsh', header['id']), 'position': position,
            'saved': archive.save_normalized_sessions}
