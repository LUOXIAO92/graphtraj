"""Offline collection of native histories explicitly associated with one project.

No Runtime Home is enumerated. Inventory is derived from retained Runner
associations; missing bindings and missing source bytes are different gaps.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from graphtraj.sessions.storage import SessionStore, session_path


def session_sources(state: Path, runner: Path, project: Path) -> list[dict]:
    """Inventory associated Main and member sources without reading transcripts."""
    tasks = state / 'tickets'
    if not tasks.exists():
        tasks = state / 'tasks'
    task_ids = {p.name.split('-', 1)[0] for p in tasks.iterdir()} if tasks.is_dir() else set()
    paths = set(runner.glob('sessions/*/mapping.yml'))
    paths.update(tasks.glob('*/teams/*/traces/*/runner/session.yml'))
    paths.update(runner.glob('main-sessions/*/session.yml'))
    paths.update(runner.glob('main-sessions/*/checks/*/session.yml'))
    sources = {}
    aliases = set()
    for path in sorted(paths):
        retained = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        record = retained.get('retirement', {}).get('mapping', retained)
        main = path.parent.parent.name == 'main-sessions'
        checker = path.parent.parent.name == 'checks'
        task = record.get('ticket_id', record.get('task_id'))
        if main:
            if record.get('cwd') != str(project):
                continue
            source = record.get('activity', {}).get('trace_file')
        elif checker:
            owner = yaml.safe_load((path.parents[2] / 'session.yml').read_text(encoding='utf-8'))
            if owner.get('cwd') != str(project):
                continue
            source = record.get('trace_file')
        else:
            if task not in task_ids:
                continue
            source = record.get('trace_file')
        if record.get('alias'):
            aliases.add(record['alias'])
        runtime, session = record.get('runtime'), record.get('session')
        if not main and not checker:
            native_file = path.parent / 'session.yml'
            observed = (yaml.safe_load(native_file.read_text(encoding='utf-8')) or {}
                        if native_file.is_file() else {})
            if observed.get('session') == session and observed.get('rollout_path'):
                source = observed['rollout_path']
            elif runtime == 'claude':
                # Managed stdout is a transport log, not the native transcript.
                source = None
        if not runtime or not session:
            sources[('unavailable', str(path))] = {
                'association': str(path), 'agent': record.get('alias'), 'task_ids': [task] if task else [],
                'missing': 'Retained association lacks Runtime or Session identity.'}
            continue
        agent = ('checker:' + session if checker else record.get('alias')) if not main else (
            'main' if runtime == 'codex' else runtime + ':' + session)
        item = {'runtime': runtime, 'session': session, 'agent': agent,
                'task_ids': [task] if task else [], 'kind': 'main' if main else ('checker' if checker else 'member'),
                'association': str(path), 'source': source}
        archived = session_path(state, runtime + ':' + session)
        if archived.exists():
            with SessionStore(archived, readonly=True) as store:
                owner = store.header['graphtraj']
                if owner['projectId'] != str(project):
                    raise ValueError('Archived Session belongs to another project.')
                if not main and not checker and agent != owner['agentId']:
                    raise ValueError('Archived Session has a conflicting Agent association.')
                # Existing canonical provenance is retained, never reconstructed.
                item['agent'] = agent = owner['agentId']
                item['archive'] = str(archived)
                item['archived_events'] = store.next_seq
                item['pending'] = store.pending() is not None
                source = source or owner['native'].get('sourcePath')
                item['source'] = source
        if not source:
            item['missing'] = 'Association has no native transcript source.'
        else:
            native = Path(source)
            if not native.is_absolute():
                native = project / native
            item['source'] = str(native)
            try:
                item['resolved_source'] = str(native.resolve(strict=True))
                if not native.is_file():
                    raise FileNotFoundError('Native source is not a regular file.')
                item['bytes'] = native.stat().st_size
            except OSError as error:
                item['missing'] = type(error).__name__ + ': associated source unavailable.'
        if not agent:
            item['missing'] = 'Retained association lacks Agent identity.'
        identity = (runtime, session)
        previous = sources.get(identity)
        if previous:
            if previous['agent'] != agent:
                raise ValueError(f'Conflicting Agent associations for {runtime}:{session}')
            item['task_ids'] = sorted(set(item['task_ids'] + previous['task_ids']))
            if 'missing' in item and 'missing' not in previous:
                previous['task_ids'] = item['task_ids']
                continue
        sources[identity] = item
    # Team membership without a surviving binding is a gap, not an invented ID.
    for team_path in sorted(tasks.glob('*/teams/*/team.yml')):
        team = yaml.safe_load(team_path.read_text(encoding='utf-8')) or {}
        for member in team.get('members', {}).values():
            alias = member.get('session_ref')
            if alias and alias not in aliases:
                sources[('missing-member', alias)] = {
                    'agent': alias, 'association': str(team_path),
                    'task_ids': [team_path.parents[2].name.split('-', 1)[0]],
                    'missing': 'Team member has no retained Runtime/Session source association.'}
    # Native children may already have a canonical archive without a Runner
    # control binding. Keep that actual project content in the inventory.
    known_archives = {item.get('archive') for item in sources.values()}
    for path in sorted((state / 'sessions').glob('*/session.sqlite3')):
        if str(path) in known_archives:
            continue
        with SessionStore(path, readonly=True) as store:
            owner = store.header['graphtraj']
            if owner['projectId'] != str(project):
                continue
            sources[('archive', store.header['id'])] = {
                'runtime': owner['native']['runtime'], 'session': owner['native']['sessionId'],
                'agent': owner['agentId'], 'task_ids': owner['taskIds'],
                'archive': str(path), 'archived_events': store.next_seq,
                'pending': store.pending() is not None, 'archive_only': True,
                'association': str(path)}
    return list(sources.values())


def archive_sources(state: Path, project: Path, sources: list[dict]) -> list[dict]:
    """Collect available associated transcripts using existing Runtime collectors.

    An unavailable file remains an explicit gap. Malformed or mismatched data
    raises instead of silently claiming successful collection. Exact source bytes
    are attachments, including any incomplete final line the collector defers.
    """
    result = []
    for item in sources:
        if 'missing' in item or item.get('archive_only'):
            result.append(item)
            continue
        runtime, session = item['runtime'], item['session']
        native = Path(item['source'])
        if runtime == 'codex':
            from graphtraj.runtimes.codex.session_archive import CodexSessionArchive

            CodexSessionArchive(state, str(project), item['agent'], session,
                                tuple(item['task_ids'])).collect(native)
        elif runtime == 'pi':
            from graphtraj.runtimes.pi.collector import PiCollector

            collector = PiCollector(state, native, session, project=str(project),
                                    agent=item['agent'], source=item['kind'], tasks=item['task_ids'])
            collector.close()
        elif runtime == 'dsh':
            from graphtraj.runtimes.dsh.collection import collect

            with native.open(encoding='utf-8') as stream:
                header = json.loads(next(stream))
                if header.get('id') != session:
                    raise ValueError('DSH migration source belongs to another Session.')
                records = [{'event': json.loads(line)} for line in stream]
            origin, tasks = item['kind'], item['task_ids']
            if item.get('archive'):
                with SessionStore(Path(item['archive']), readonly=True) as store:
                    owner = store.header['graphtraj']
                    origin, tasks = owner['source'], owner['taskIds']
            collect(state, header, records, project_id=str(project), agent_id=item['agent'],
                    task_ids=tasks, source=origin)
        elif runtime == 'claude':
            from graphtraj.runtimes.claude.collection import (
                collect_transcript, finish_transcript_collection, open_archive,
            )

            with open_archive(state, project, session, item['agent'], source=item['kind'],
                              task_ids=item['task_ids']) as store:
                collect_transcript(store, native)
                finish_transcript_collection(store, session, terminal=True)
        else:
            result.append({**item, 'missing': 'Unsupported historical Runtime; source retained unchanged.'})
            continue
        path = session_path(state, runtime + ':' + session)
        if not path.exists():
            result.append({**item, 'missing': 'No complete native header; source retained unchanged.'})
            continue
        with SessionStore(path) as store:
            raw = store.copy_attachment(native)
            result.append({**item, 'archive': str(path), 'original_bytes': raw,
                           'events': store.next_seq, 'pending': store.pending() is not None})
    return result
