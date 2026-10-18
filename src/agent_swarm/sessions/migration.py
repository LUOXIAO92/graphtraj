"""Import explicitly supplied legacy archives and native histories, offline.

The original database stays untouched. Its records are retained separately from
native-ordered events: converting a storage format cannot repair message order.
No Runtime home, Task directory or credential discovery occurs here.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from .archive import JsonlSessionStore, SessionArchive, archive_path


def import_sqlite(source: Path, root: Path) -> dict:
    """Copy a consistent legacy SQLite archive to JSONL with exact old evidence.

    All old events, unfinished output, checkpoints and attachment bytes survive.
    Repeating an unchanged import is a no-op; changed evidence is refused.
    Native history must be supplied separately before messages are available.
    """
    connection = sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        connection.execute('BEGIN')
        if connection.execute('PRAGMA user_version').fetchone()[0] != 1:
            raise ValueError('Unsupported legacy Session storage version.')
        header = json.loads(connection.execute('SELECT value FROM header').fetchone()[0])
        events = [json.loads(row[0]) for row in connection.execute('SELECT value FROM events ORDER BY seq')]
        drafts = [{'source': row[0], 'event': json.loads(row[1])}
                  for row in connection.execute('SELECT source, value FROM draft')]
        checkpoints = dict(connection.execute('SELECT source, position FROM checkpoints'))
        store = JsonlSessionStore.create(archive_path(root, header['id']), header)
        attachments = []
        for digest, content in connection.execute('SELECT digest, content FROM attachments ORDER BY digest'):
            ref = store.put_attachment(content)
            if digest != ref['sha256']:
                raise ValueError('Legacy attachment digest mismatch.')
            attachments.append(ref)
        store.retain_legacy({'header': header, 'events': events, 'pending': drafts,
                             'checkpoints': checkpoints, 'attachments': attachments})
        native = header.get('graphtraj', {}).get('native', header.get('native', {}))
        return {'id': header['id'], 'native': native, 'archive': str(store.path),
                'events': len(events), 'pending': len(drafts), 'attachments': len(attachments),
                'missing': 'Legacy record order is not native message evidence; supply the associated native history.'}
    finally:
        connection.close()


def import_native(
    root: Path,
    runtime: str,
    session: str,
    source: Path,
    *,
    agent: str,
    project: str,
    child_id: str | None = None,
) -> dict:
    """Collect one explicitly associated native file through its Runtime mapper.

    Original provenance and header IDs are preserved. Callers importing a fork
    supply its associated parent first. Unknown/missing native content remains
    explicit; this entry neither invents order nor searches for another source.
    """
    archive = SessionArchive(root, save_normalized_sessions=True, backfill_history=True)
    if runtime == 'codex':
        from .codex import CodexJsonlArchive

        collector = CodexJsonlArchive(archive, agent, session, new_session=False, rollout=source)
        collector.collect(source)
    elif runtime == 'claude':
        from .claude import ClaudeJsonlCollector

        collector = ClaudeJsonlCollector(archive, session, agent, Path(project), 'migration', resumed=True, child_id=child_id)
        collector.bind(source)
        collector.collect()
    elif runtime == 'pi':
        from .pi import PiArchive

        with source.open('rb') as stream:
            header = json.loads(stream.readline())
            entries = []
            for line in stream:
                if not line.endswith(b'\n'):
                    raise ValueError('Pi native history has an incomplete final record.')
                entries.append(json.loads(line))
        if header.get('id') != session:
            raise ValueError('Pi native history does not match the associated Session.')
        leaf = entries[-1].get('id') if entries else None
        collector = PiArchive(archive, header, agent=agent, project=project,
                              entries=entries, leaf_id=leaf)
        collector.sync(entries, leaf, settled=True)
    elif runtime == 'dsh':
        from .dsh import collect_jsonl

        with source.open(encoding='utf-8') as stream:
            header = json.loads(next(stream))
            records = [{'event': json.loads(line)} for line in stream]
        if header.get('id') != session:
            raise ValueError('DSH native history does not match the associated Session.')
        collect_jsonl(archive, header, records, historical=True)
    else:
        raise ValueError('Unsupported native Runtime: ' + runtime)
    identity = archive.native_id(runtime, session, agent_id=child_id)
    store = JsonlSessionStore(archive_path(root, identity))
    try:
        count = len(collector.messages() if runtime == 'pi' else store.messages())
        missing = None
    except ValueError as error:
        count, missing = None, str(error)
    return {'id': identity, 'runtime': runtime, 'session': session,
            'archive': str(store.path), 'messages': count, 'missing': missing}
