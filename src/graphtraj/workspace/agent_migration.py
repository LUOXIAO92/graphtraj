"""Public offline migration of retained Session archives to tool-owned JSONL.

Reuse the project snapshot inventory and captured native files. A snapshot is
not an active Harness: no Runtime is started and original paths are provenance,
never fallback reads. Original SQLite and dispatch/delivery records stay intact.
"""
from __future__ import annotations

from pathlib import Path
import json
import hashlib

import yaml

from agent_swarm import default_config
from agent_swarm.sessions.migration import import_native, import_sqlite, verify_sqlite
from agent_swarm.sessions.archive import SessionArchive, JsonlSessionStore
from agent_swarm.sessions.protocol import native_record
from graphtraj.sessions.storage import SessionStore
from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.interfaces.agents import graphtraj_fields
from graphtraj.execution.main_continuity import current_main
from graphtraj.workspace.migration_snapshot import MANIFEST, source_map
from graphtraj.workspace.session_migration import _source_order
from graphtraj.workspace.task_migration import foreign_entries


def _legacy_registrations(
    root: Path,
    manifest: dict,
    sources: list[dict],
    available: dict[str, Path],
    main_session: str | None,
    claimed_main: dict | None = None,
) -> dict:
    """Inventory associated headers and binding facts, without exposing bodies.

    A retained native declaration proves registration, not a live duplicate MCP
    tool list. Resume prerequisites are metadata evidence, never a resume probe.
    Main ownership identifies retained root owners, not the current GUI tab.
    """
    result = []
    backup = root / '.graphtraj/core/backups/before-agent-partition'
    roots = {manifest['runner_source']: backup / 'runner' if backup.is_dir() else root / '.graphtraj/migration-runner',
             manifest['state_source']: backup / 'state' if backup.is_dir() else root / '.graphtraj/state',
             manifest['project'] + '/.graphtraj/swarm': root / '.graphtraj/swarm'}
    seen = set()
    for item in sources:
        identity = (item.get('runtime'), item.get('session'), item.get('native_agent'))
        if not identity[1] or identity in seen:
            continue
        seen.add(identity)
        bindings = []
        associations = item.get('associations') or [{'path': item.get('association')}]
        for association in associations:
            original = association.get('path')
            if not original:
                continue
            path = None
            for source, target in roots.items():
                if original.startswith(source + '/'):
                    relative = Path(original).relative_to(source)
                    if '..' not in relative.parts:
                        path = target / relative
                    break
            if path is None or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
                continue
            if path.suffix not in {'.json', '.yml'}:
                continue
            retained = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
            record = retained.get('retirement', {}).get('mapping', retained)
            retired = bool(retained.get('retirement') or retained.get('retired_at'))
            current = ('/sessions/' in original and path.name == 'mapping.yml') or path.suffix == '.json'
            launch = path.parent / 'launch.yml'
            settings = bool(record.get('settings')) or launch.is_file()
            bindings.append({'reference': str(path.relative_to(root)),
                             'agent': record.get('alias', record.get('agent')),
                             'retired': retired, 'current': current and not retired,
                             'continuation_settings': settings})
        owners = [owner for association in associations
                  for owner in association.get('root_owners', []) if not owner.get('retired')]
        if item.get('kind') == 'main':
            group = ('current_main' if item.get('session') == main_session
                     else 'historical_or_retired' if main_session else 'main_unconfirmed')
        elif any(binding['current'] for binding in bindings):
            group = 'current_members'
        else:
            group = 'historical_or_retired'
        entry = {'runtime': identity[0], 'session': identity[1], 'agent': item.get('agent'),
                 'group': group, 'bindings': bindings, 'tools': [],
                 'resume_prerequisites': any(b['current'] and b['continuation_settings'] for b in bindings),
                 'duplicate_status': 'unknown', 'confirmed_live_duplicate': False}
        if item.get('kind') == 'main':
            entry['retained_current_root_owners'] = [owner['alias'] for owner in owners]
            entry['current_interactive_main'] = (item.get('session') == main_session if main_session
                                                 else 'Not established by offline ownership metadata.')
        path = available.get(item.get('source'))
        if identity[0] != 'codex':
            entry['missing'] = 'This Runtime does not retain its tool registry in the captured Session header.'
        elif path is None:
            entry['missing'] = 'Associated native header was not captured.'
        else:
            try:
                with path.open('rb') as stream:
                    header = json.loads(stream.readline())
                if header.get('type') != 'session_meta':
                    raise ValueError('No native header')
                metadata = header.get('payload', {})
                if metadata.get('id') != identity[1]:
                    raise ValueError('Header identity mismatch')
                declarations = metadata.get('dynamic_tools', metadata.get('dynamicTools', [])) or []
                owned = [tool['name'] for tool in declarations if isinstance(tool, dict)
                         and tool.get('namespace') in {None, '', 'graphtraj', 'agents', 'tasks'}
                         and (tool.get('name') in {'graphtraj', 'agents', 'tasks'}
                              or str(tool.get('name', '')).startswith('graphtraj_'))]
                entry['tools'] = sorted(set(owned))
                entry['duplicate_status'] = 'potential_on_mcp_resume' if owned else 'no_retained_product_declarations'
                entry['header_reference'] = str(path.relative_to(root))
            except (OSError, ValueError, TypeError):
                entry['missing'] = 'Copied header unavailable, invalid, or identity does not match.'
        result.append(entry)
    if claimed_main is not None and not any(entry['session'] == claimed_main['session'] for entry in result):
        # The current Main known only by its continuity claim (no completion binding).
        result.append({'runtime': claimed_main['runtime'], 'session': claimed_main['session'], 'agent': None,
                       'group': 'current_main', 'bindings': [{'reference': 'main-sessions/continuity.jsonl',
                                                              'agent': None, 'retired': False, 'current': True,
                                                              'continuation_settings': False}],
                       'tools': [], 'resume_prerequisites': False, 'duplicate_status': 'unknown',
                       'confirmed_live_duplicate': False, 'retained_current_root_owners': [],
                       'current_interactive_main': True,
                       'missing': 'This Runtime does not retain its tool registry in the captured Session header.'})
    counts = {}
    for entry in result:
        key = entry['group']
        counts.setdefault(key, {'sessions': 0, 'with_old_declarations': 0, 'unknown': 0})
        counts[key]['sessions'] += 1
        counts[key]['with_old_declarations'] += bool(entry['tools'])
        counts[key]['unknown'] += entry['duplicate_status'] == 'unknown'
    return {'counts': counts, 'sessions': result,
            'confirmed_live_duplicates': 0,
            'unidentified_associations': sum(not item.get('session') for item in sources),
            'limitation': 'No live tools/list was captured. Old declarations plus newly configured MCP establish potential exposure, not a confirmed live duplicate.'}


def migrate_agents(
    cwd: Path,
    *,
    preview: bool = False,
    sessions: tuple[str, ...] = (),
    verify: bool = False,
    main_session: str | None = None,
    against: Path | None = None,
) -> dict:
    """Convert only an isolated public snapshot, with repeatable native imports.

    Production cutover is not implemented here. It still needs the stopped
    control/configuration/Worktree transition and retained recovery inputs.
    This operation establishes archive evidence without changing active identities.
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
    # A Claude/Pi/DSH Main has no Codex completion binding; only the current
    # continuity claim (main_continuity) identifies it as the current Main.
    backup = cwd / '.graphtraj/core/backups/before-agent-partition/runner'
    current = current_main(backup if backup.is_dir() else cwd / '.graphtraj/migration-runner')
    claimed = current if current is not None and current['session'] == main_session else None
    if main_session and claimed is None and not any(
            item.get('kind') == 'main' and item.get('session') == main_session for item in sources):
        raise ValueError('The supplied current Main identity has no retained Main binding in this snapshot.')
    if sessions:
        sources = [item for item in sources
                   if item.get('runtime', '') + ':' + item.get('session', '') in sessions]
        found = {item.get('runtime', '') + ':' + item.get('session', '') for item in sources}
        if set(sessions) - found:
            raise ValueError('Selected native Session is not in the snapshot inventory.')
        selected = []
        for path in archives:
            with SessionStore(path, readonly=True) as store:
                native = store.header.get('native', {})
                if native.get('runtime', '') + ':' + native.get('sessionId', '') in sessions:
                    selected.append(path)
        archives = selected
    report = {'snapshot': str(cwd), 'original_project': manifest['project'],
              'archive_root': str(root), 'sqlite_archives': len(archives),
              'sources': sources, 'missing_links': manifest.get('missing_links', []),
              'git_worktree_consistency': manifest.get('git_worktrees_unchanged'),
              'foreign_entries': foreign_entries(configuration.state / 'tasks'),
              'legacy_native_registrations': _legacy_registrations(cwd, manifest, sources, available, main_session, claimed),
              'production_cutover': False}
    if preview:
        return report
    if verify:
        if not archives:
            archives = sorted((cwd / '.graphtraj/core/backups/before-agent-partition/state/sessions').glob('*/session.sqlite3'))
        checks = []
        for path in archives:
            try:
                checks.append(verify_sqlite(path, root))
            except (OSError, ValueError, KeyError) as error:
                checks.append({'archive': str(path), 'mismatches': [str(error)]})
        files = []
        for item in manifest.get('files', []):
            if not item.get('stored'):
                continue
            path = available[item['paths'][0]]
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            files.append({'reference': item['stored'], 'matches': digest == item['sha256']})
        from graphtraj.workspace.agent_cutover import verify_partition

        layout = verify_partition(cwd, manifest)
        swarm = _verify_retained_swarm(cwd, against, manifest) if against else None
        return {**report, 'sqlite_archives': len(archives), 'verification': {'sqlite': checks, 'native_files': files,
                'layout': layout, 'retained_swarm': swarm,
                'matches': (all(not check['mismatches'] for check in checks) and all(f['matches'] for f in files)
                            and (layout is None or layout['matches']) and (swarm is None or swarm['matches'])),
                'scope': 'Exact legacy values and attachment bytes; captured native file hashes. Native history gaps and live tails are not repaired by this check.'}}
    imports = [import_sqlite(path, root) for path in archives]
    results = []
    archive = SessionArchive(root, save_normalized_sessions=True, backfill_history=True)
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
                                   project=manifest['project'], child_id=item.get('native_agent'), archive=archive,
                                   extra_fields=graphtraj_fields(manifest['project'], item['agent']))
            results.append({**result, 'source': item['source']})
        except (OSError, ValueError, KeyError, TypeError) as error:
            results.append({**item, 'missing': str(error)})
    default_config(root, save_normalized_sessions=True)
    return {**report, 'imports': imports, 'native_results': results,
            'notice': 'Archive rehearsal only. Original state, identities and native sources are unchanged.'}


def _retained_event(event: dict, by_seq: dict[int, dict]) -> dict:
    """Return what an existing archive event must keep through import, in order.

    A native event keeps its original record. Codex's history event (a
    replacement or rollback selection) has no record: it keeps its complete
    content, with each selected seq named by that event's native identity,
    since import may renumber seqs when it adds earlier native records.
    """
    native = event['native']
    if event['type'] != 'history':
        return {'native': native, 'record': native_record(event)}
    selected = [by_seq[seq].get('native', {}) for seq in event['data']['eventSeqs']]
    content = {key: value for key, value in event.items() if key not in {'seq', 'data'}}
    return {'native': native, 'event': {**content, 'data': {**event['data'], 'eventSeqs': [
        (item.get('runtime'), item.get('sessionId'), item.get('locator')) for item in selected]}}}


def _verify_retained_swarm(root: Path, original: Path, manifest: dict) -> dict:
    """Compare copied tool-owned identities, native resources and existing JSONL.

    The explicit immutable input is another public snapshot of this project.
    Existing native event records and their relative order must survive; new
    native prefixes may have been added. No transcript is returned to callers.
    """
    if original.resolve() == root.resolve():
        raise ValueError('Comparison requires a distinct retained input snapshot.')
    original_manifest = yaml.safe_load((original / MANIFEST).read_text(encoding='utf-8'))
    if original_manifest.get('project') != manifest['project']:
        raise ValueError('The comparison input belongs to another project.')
    source = original / '.graphtraj/swarm'
    mismatches = []
    counts = {'files': 0, 'jsonl_archives': 0, 'native_events': 0, 'attachments': 0, 'controls': 0}
    for path in source.rglob('*'):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(source)
        target = root / '.graphtraj/swarm' / relative
        if not target.is_file() or target.is_symlink():
            mismatches.append(relative.as_posix())
            continue
        if relative.parts[0] == 'sessions' and path.name == 'session.jsonl':
            before, after = JsonlSessionStore(path), JsonlSessionStore(target)
            counts['jsonl_archives'] += 1
            if before.header != after.header:
                mismatches.append(relative.as_posix() + ':header')
            old_events, new_events = [], []
            for store, records in ((before, old_events), (after, new_events)):
                events, cursor = [], -1
                while True:
                    page = store.page(after=cursor)
                    events.extend(page['events'])
                    if not page['has_more']:
                        break
                    cursor = page['after']
                by_seq = {event['seq']: event for event in events}
                records.extend(_retained_event(event, by_seq) for event in events)
            old_keys = {(item['native']['runtime'], item['native']['sessionId'], item['native']['locator'])
                        for item in old_events}
            selected = [item for item in new_events
                        if (item['native']['runtime'], item['native']['sessionId'], item['native']['locator']) in old_keys]
            counts['native_events'] += len(old_events)
            if selected != old_events:
                mismatches.append(relative.as_posix() + ':native-records-or-order')
            continue
        # Normalized metadata can grow during native collection. Its originals
        # remain in the immutable input; archive identity/events are checked above.
        if relative.parts[0] == 'sessions' and path.name != 'session.jsonl' and 'attachments' not in relative.parts:
            continue
        counts['files'] += 1
        counts['attachments'] += 'attachments' in relative.parts
        counts['controls'] += relative.parts[:2] == ('control', 'agents')
        with path.open('rb') as before, target.open('rb') as after:
            if hashlib.file_digest(before, 'sha256').digest() != hashlib.file_digest(after, 'sha256').digest():
                mismatches.append(relative.as_posix())
    return {**counts, 'matches': not mismatches, 'mismatches': mismatches,
            'input': str(original), 'scope': 'Existing headers/native records/order and unchanged configuration/control/native-resource/attachment bytes; evolving normalized metadata remains backed up in the input.'}
