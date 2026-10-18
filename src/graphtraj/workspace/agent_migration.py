"""Public offline migration of retained Session archives to tool-owned JSONL.

Reuse the project snapshot inventory and captured native files. A snapshot is
not an active Harness: no Runtime is started and original paths are provenance,
never fallback reads. Original SQLite and dispatch/delivery records stay intact.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from agent_swarm import default_config
from agent_swarm.sessions.migration import import_native, import_sqlite
from graphtraj.sessions.storage import SessionStore
from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.workspace.migration_snapshot import MANIFEST, source_map
from graphtraj.workspace.session_migration import _source_order


def migrate_agents(cwd: Path, *, preview: bool = False, sessions: tuple[str, ...] = ()) -> dict:
    """Convert only an isolated public snapshot, with repeatable native imports.

    Production cutover is deliberately refused until the complete stopped
    control/configuration/Worktree transition can be applied atomically. This
    operation establishes archive evidence without changing active identities.
    """
    configuration = load_project_configuration(cwd)
    manifest_path = cwd / MANIFEST
    if not manifest_path.is_file():
        raise ValueError('Use migrate-agents --snapshot first; active project migration is not permitted.')
    manifest = yaml.safe_load(manifest_path.read_text(encoding='utf-8'))
    available = source_map(cwd, manifest)
    archives = sorted((configuration.state / 'sessions').glob('*/session.sqlite3'))
    root = cwd / '.graphtraj/swarm'
    sources = manifest['sources']
    if sessions:
        sources = [item for item in sources
                   if item.get('runtime', '') + ':' + item.get('session', '') in sessions]
        found = {item.get('runtime', '') + ':' + item.get('session', '') for item in sources}
        if set(sessions) - found:
            raise ValueError('Selected native Session is not in the snapshot inventory.')
        selected = []
        for path in archives:
            with SessionStore(path, readonly=True) as store:
                native = store.header.get('graphtraj', {}).get('native', {})
                if native.get('runtime', '') + ':' + native.get('sessionId', '') in sessions:
                    selected.append(path)
        archives = selected
    report = {'snapshot': str(cwd), 'original_project': manifest['project'],
              'archive_root': str(root), 'sqlite_archives': len(archives),
              'sources': sources, 'missing_links': manifest.get('missing_links', []),
              'production_cutover': False}
    if preview:
        return report
    imports = [import_sqlite(path, root) for path in archives]
    results = []
    for item in _source_order(sources, available):
        if item.get('identity_conflicts'):
            results.append({**item, 'missing': 'Conflicting retained native associations; no history imported.'})
            continue
        if item.get('missing') or not item.get('source'):
            results.append(item)
            continue
        source = available.get(item['source'])
        if source is None:
            results.append({**item, 'missing': 'Associated native source was not captured; original not read.'})
            continue
        try:
            result = import_native(root, item['runtime'], item['session'], source,
                                   agent=item['agent'], project=manifest['project'], child_id=item.get('native_agent'))
            results.append({**result, 'source': item['source']})
        except (OSError, ValueError, KeyError, TypeError) as error:
            results.append({**item, 'missing': str(error)})
    default_config(root, save_normalized_sessions=True)
    return {**report, 'imports': imports, 'native_results': results,
            'notice': 'Archive rehearsal only. Original state, identities and native sources are unchanged.'}
