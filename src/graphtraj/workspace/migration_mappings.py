"""Adopt explicitly confirmed legacy remote identities without importing remote Task data."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit

import yaml

from graphtraj import file_lock
from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.graph.github_backup import _load, _save, _now, _REPOSITORY, _HOST
from graphtraj.graph.task_protocol import TASK_ID


def adopt_mappings(cwd: Path, source: Path, evidence_ref: str, *, preview: bool = False) -> dict:
    """Record confirmed local/remote pairs atomically, without any remote request.

    Input rows carry local_id, remote_number, remote_url, local_definition,
    mapping_source and mapping_confirmation. Remote title/body prefixes are
    evidence only and never become local definition or backup-baseline fields.
    Missing remote object IDs and full published content remain null; the first
    ordinary backup reads that exact Issue and requires explicit conflict review.
    """
    configuration = load_project_configuration(cwd)
    state = configuration.state
    if not (state / 'tasks').is_dir() or (state / 'tickets').exists():
        raise ValueError('Adopt remote mappings only after the complete Task-format migration.')
    if not isinstance(evidence_ref, str) or not evidence_ref.strip():
        raise ValueError('An explicit authoritative mapping evidence reference is required.')
    content = source.read_bytes()
    rows = json.loads(content)
    if not isinstance(rows, list) or not rows:
        raise ValueError('Mapping input must be a nonempty list of explicitly confirmed pairs.')
    digest = hashlib.sha256(content).hexdigest()
    proposed = []
    identities = set()
    remotes = set()
    tasks = {}
    for path in (state / 'tasks').glob('*/task.yml'):
        record = yaml.safe_load(path.read_text(encoding='utf-8'))
        tasks[record['task_id']] = path.parent.name
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('A mapping row must be an object.')
        local = row.get('local_id')
        number = row.get('remote_number')
        url = urlsplit(row.get('remote_url') or '')
        parts = url.path.strip('/').split('/')
        if (not isinstance(local, str) or not TASK_ID.fullmatch(local) or local not in tasks
                or type(number) is not int or number <= 0
                or url.scheme != 'https' or not url.hostname or not _HOST.fullmatch(url.netloc)
                or url.query or url.fragment or url.username or url.password
                or len(parts) != 4 or parts[2:] != ['issues', str(number)]
                or not _REPOSITORY.fullmatch('/'.join(parts[:2]))):
            raise ValueError('Mapping must identify an existing local Task and one exact remote Issue URL.')
        definition = row.get('local_definition')
        association = row.get('mapping_source')
        confirmation = row.get('mapping_confirmation')
        if (any(not isinstance(value, str) or not value for value in (definition, association, confirmation))
                or any(Path(value).is_absolute() or '..' in Path(value).parts for value in (definition, association))
                or tasks[local] not in Path(definition).parts):
            raise ValueError('Mapping must retain its local definition and authoritative confirmation evidence.')
        host, repository = url.netloc, '/'.join(parts[:2])
        identity, remote = (local, host, repository), (host, repository, number)
        if identity in identities or remote in remotes:
            raise ValueError('Mapping input repeats a Task target or assigns one remote Issue twice.')
        identities.add(identity)
        remotes.add(remote)
        proposed.append({'task_id': local, 'adapter': 'github', 'host': host, 'repository': repository,
                         'issue': {'number': number, 'id': None, 'node_id': None, 'url': row['remote_url']},
                         'published': None, 'migration': {'input_sha256': digest, 'evidence_ref': evidence_ref,
                             'local_definition': definition, 'mapping_source': association,
                             'confirmation': confirmation}})

    def merge(backups: list[dict]) -> list[dict]:
        """Reject conflicts before saving any pair; retries preserve established remote facts."""
        added = []
        for item in proposed:
            identity = tuple(item[key] for key in ('task_id', 'host', 'repository'))
            previous = next((entry for entry in backups
                             if tuple(entry[key] for key in ('task_id', 'host', 'repository')) == identity), None)
            if previous is not None:
                if (not previous.get('issue') or any(previous['issue'].get(key) != item['issue'][key]
                                                       for key in ('number', 'url'))):
                    raise ValueError('An existing backup mapping conflicts with the supplied remote identity.')
                continue
            if any(entry['host'] == item['host'] and entry['repository'] == item['repository']
                   and entry.get('issue', {}) and entry['issue']['number'] == item['issue']['number']
                   for entry in backups):
                raise ValueError('The remote Issue is already mapped to a different local Task.')
            added.append({**item, 'marker': secrets.token_hex(16), 'pending_since': _now(),
                          'last_error': None, 'last_published_at': None})
        return added

    if preview:
        added = merge(_load(state))
    else:
        descriptor = os.open(str(state / '.task-backups.lock'), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            file_lock.flock(descriptor, file_lock.LOCK_EX)
            backups = _load(state)
            added = merge(backups)
            if added:
                _save(state, backups + added)
        finally:
            file_lock.flock(descriptor, file_lock.LOCK_UN)
            os.close(descriptor)
    return {'preview': preview, 'input_sha256': digest, 'evidence_ref': evidence_ref,
            'added': len(added), 'unchanged': len(proposed) - len(added),
            'mappings': [{'task_id': item['task_id'], 'repository': item['repository'],
                          'issue_number': item['issue']['number'], 'url': item['issue']['url']}
                         for item in proposed],
            'notice': 'No remote request or Task modification. Unknown full remote baseline requires first-backup review.'}
