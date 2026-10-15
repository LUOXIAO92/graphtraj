"""Capture only a Main Session's explicitly declared Codex inherited prefix."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil

import yaml

from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.workspace.session_migration import session_sources


def _metadata(path: Path, session: str) -> dict:
    """Read only the native first header and require its exact queried identity."""
    with path.open('rb') as stream:
        line = stream.readline()
    try:
        record = json.loads(line)
        metadata = record['payload']
        if record.get('type') != 'session_meta' or metadata.get('id') != session:
            raise ValueError('Native source does not identify the declared Session.')
    except (KeyError, TypeError, json.JSONDecodeError):
        raise ValueError('Native Session header is unavailable or invalid.') from None
    if not line.endswith(b'\n'):
        raise ValueError('Native Session header is incomplete.')
    return metadata


def declared_prefix(metadata: dict) -> dict:
    """Validate the native inheritance coordinates without equating fork and storage IDs."""
    base = metadata.get('history_base')
    if (not isinstance(base, dict) or not isinstance(base.get('thread_id'), str)
            or not base['thread_id'] or base['thread_id'] == metadata.get('id')
            or any(type(base.get(key)) is not int or base[key] <= 0
                   for key in ('end_ordinal_exclusive', 'end_byte_offset'))):
        raise ValueError('Main does not declare a valid bounded history_base.')
    return {key: base[key] for key in ('thread_id', 'end_ordinal_exclusive', 'end_byte_offset')}


def inspect_prefix(cwd: Path, session: str, *, capture: Path | None = None) -> dict:
    """Inspect two exact native identities; optionally capture only the declared bytes.

    The existing owning daemon supplies paths through metadata-only thread/read.
    No thread listing, Runtime Home scan, other inheritance recursion, new Agent,
    source write or credential copy occurs. The reference establishes content
    provenance, not a fabricated Agent identity for the inherited source.
    """
    from graphtraj.runtimes.codex.finalize import proxy

    configuration = load_project_configuration(cwd)
    project = configuration.harness_root
    if (project / '.graphtraj/migration-snapshot.yml').exists():
        raise ValueError('Query inherited source metadata from the original lawful native host.')
    candidates = [item for item in session_sources(configuration.state, project / '.graphtraj/runner', project)
                  if item.get('runtime') == 'codex' and item.get('session') == session]
    if len(candidates) != 1 or candidates[0].get('kind') != 'main' or candidates[0].get('identity_conflicts'):
        raise ValueError('An unambiguous retained project Main association is required.')
    item = candidates[0]
    binding = yaml.safe_load(Path(item['association']).read_text(encoding='utf-8'))
    connection = binding.get('connection', {})
    if connection.get('runtime') != 'codex' or connection.get('session') != session:
        raise ValueError('Main owning native connection is unavailable.')

    async def read() -> tuple[dict, dict, Path, Path, dict]:
        """Resolve only the associated Main and the one ID declared by its own header."""
        async with proxy(connection) as client:
            child = await client.read_thread(session)
            child_path = Path(child.get('path') or '')
            if child.get('id') != session or not child_path.is_absolute():
                raise ValueError('Owning native host did not supply the Main source path.')
            metadata = _metadata(child_path, session)
            base = declared_prefix(metadata)
            parent = await client.read_thread(base['thread_id'])
            source = Path(parent.get('path') or '')
            if parent.get('id') != base['thread_id'] or not source.is_absolute():
                raise ValueError('Owning native host did not supply the declared inherited source path.')
            parent_metadata = _metadata(source, base['thread_id'])
            return metadata, base, child_path, source, parent_metadata

    metadata, base, child_path, source, parent_metadata = asyncio.run(read())
    result = {'version': 1, 'project': str(project), 'session': session, 'agent': item['agent'],
              'main_source': str(child_path), 'forked_from_id': metadata.get('forked_from_id'),
              'history_base': base, 'source': str(source), 'available_bytes': source.stat().st_size,
              'source_metadata': {key: parent_metadata[key] for key in ('id', 'cwd', 'forked_from_id', 'history_base')
                                  if key in parent_metadata},
              'source_agent': None,
              'identity_basis': 'Exact history_base declared by the associated Main; metadata-only owning-host lookup.'}
    if capture is None:
        return result
    capture = capture.resolve()
    if capture.exists() or capture.is_relative_to(project):
        raise ValueError('Prefix capture destination must be new and outside the source project.')
    capture.mkdir(mode=0o700, parents=True)
    try:
        path = capture / 'prefix.jsonl'
        digest = hashlib.sha256()
        remaining = base['end_byte_offset']
        with source.open('rb') as reader, path.open('xb') as writer:
            path.chmod(0o600)
            while remaining:
                block = reader.read(min(1024 * 1024, remaining))
                if not block:
                    raise ValueError('Declared inherited source is shorter than its byte boundary.')
                writer.write(block)
                digest.update(block)
                remaining -= len(block)
        # The captured file is evidence, including any gap. Do not silently
        # chase a further inherited source or publish a guessed canonical prefix.
        ordinals = []
        with path.open('rb') as stream:
            for line in stream:
                if not line.endswith(b'\n'):
                    raise ValueError('Declared inherited byte boundary splits a native record.')
                record = json.loads(line)
                ordinals.append(record.get('ordinal'))
        complete = ordinals == list(range(base['end_ordinal_exclusive']))
        result.update(stored='prefix.jsonl', sha256=digest.hexdigest(), bytes=path.stat().st_size,
                      records=len(ordinals), complete=complete,
                      first_ordinal=ordinals[0] if ordinals else None,
                      last_ordinal=ordinals[-1] if ordinals else None)
        if not complete:
            result['missing'] = 'Captured bytes do not establish the complete declared ordinal prefix; no further source read.'
        manifest = capture / 'prefix.yml'
        manifest.write_text(yaml.safe_dump(result, sort_keys=False), encoding='utf-8')
        manifest.chmod(0o600)
        return {**result, 'capture': str(capture)}
    except BaseException:
        shutil.rmtree(capture)
        raise
