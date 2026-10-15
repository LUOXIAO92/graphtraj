"""Capture only a Main Session's explicitly declared Codex inherited prefix."""
from __future__ import annotations

import asyncio
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
from uuid import UUID

import yaml

from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.workspace.session_migration import session_sources


def _metadata(path: Path, session: str) -> tuple[dict, int | None]:
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
    return metadata, record.get('ordinal')


def rollout_identity(path: Path) -> tuple[str, str]:
    """Read Codex's documented logical/physical IDs from a canonical basename.

    This is only one check: native metadata and the actual first header must
    independently agree before any bounded content acquisition is allowed.
    """
    name = path.name
    if not name.startswith('rollout-') or not name.endswith('.jsonl'):
        raise ValueError('Declared physical source lacks a canonical uncompressed rollout name.')
    core = name[8:-6]
    try:
        datetime.strptime(core[:19], '%Y-%m-%dT%H-%M-%S')
        if core[19:20] != '-':
            raise ValueError
        ids = core[20:].split('_')
        if len(ids) not in (1, 2):
            raise ValueError
        return str(UUID(ids[0])), str(UUID(ids[-1]))
    except (ValueError, IndexError):
        raise ValueError('Invalid canonical logical/physical rollout identity.') from None


def declared_prefix(metadata: dict) -> dict:
    """Validate the native inheritance coordinates without equating fork and storage IDs."""
    base = metadata.get('history_base')
    if (not isinstance(base, dict) or not isinstance(base.get('thread_id'), str)
            or not base['thread_id']
            or any(type(base.get(key)) is not int or base[key] <= 0
                   for key in ('end_ordinal_exclusive', 'end_byte_offset'))):
        raise ValueError('Main does not declare a valid bounded history_base.')
    return {key: base[key] for key in ('thread_id', 'end_ordinal_exclusive', 'end_byte_offset')}


def inspect_prefix(
    cwd: Path,
    session: str,
    expected: tuple[str, int, int],
    *,
    capture: Path | None = None,
    diagnose: bool = False,
) -> dict:
    """Inspect two exact native identities; optionally capture only the declared bytes.

    The existing owning daemon supplies paths through metadata-only thread/read.
    No thread listing, Runtime Home scan, other inheritance recursion, new Agent,
    source write or credential copy occurs. The reference establishes content
    provenance, not a fabricated Agent identity for the inherited source.
    """
    from graphtraj.runtimes.codex.finalize import proxy

    if diagnose and capture is not None:
        raise ValueError('Choose metadata diagnosis or prefix capture, not both.')
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

    async def read() -> tuple[dict, dict, Path, Path | None, dict, dict, int | None]:
        """Resolve only the associated Main and the one ID declared by its own header."""
        async with proxy(connection) as client:
            child = await client.read_thread(session)
            child_path = Path(child.get('path') or '')
            if child.get('id') != session or not child_path.is_absolute():
                raise ValueError('Owning native host did not supply the Main source path.')
            metadata, _ = _metadata(child_path, session)
            base = declared_prefix(metadata)
            if tuple(base[key] for key in ('thread_id', 'end_ordinal_exclusive', 'end_byte_offset')) != expected:
                raise ValueError('Main declared a different inherited prefix; no referenced source queried: ' + json.dumps(base))
            observed = await client.inspect_thread_reference(base['thread_id'])
            if diagnose:
                return metadata, base, child_path, None, {}, observed, None
            source = Path(observed.get('path') or '')
            if not source.is_absolute():
                raise ValueError('Owning native host did not supply the declared inherited source path.')
            logical = observed.get('id')
            if logical != base['thread_id']:
                # history_base can name an immutable rollout of this same logical
                # Main. Never generalize a mismatched thread/read identity to an
                # unrelated Session or choose a path by guessing its filename.
                if (logical != session or observed.get('sessionId') != session
                        or observed.get('cwd') != str(project)
                        or observed.get('historyMode') != 'paginated'
                        or observed.get('forkedFromId') != metadata.get('forked_from_id')
                        or rollout_identity(source) != (session, base['thread_id'])):
                    raise ValueError('Native reference is neither the exact Session nor its verified same-Main physical rollout.')
            parent_metadata, ordinal = _metadata(source, logical)
            if logical != base['thread_id'] and (
                    parent_metadata.get('history_mode') != 'paginated'
                    or parent_metadata.get('cwd') != str(project)
                    or parent_metadata.get('forked_from_id') != metadata.get('forked_from_id')):
                raise ValueError('Physical rollout header conflicts with the native Main metadata.')
            return metadata, base, child_path, source, parent_metadata, observed, ordinal

    metadata, base, child_path, source, parent_metadata, observed, ordinal = asyncio.run(read())
    if diagnose:
        return {'project': str(project), 'session': session, 'agent': item['agent'],
                'forked_from_id': metadata.get('forked_from_id'), 'history_base': base,
                'expected_id': base['thread_id'], 'actual_id': observed['id'],
                'identity_matches': observed['id'] == base['thread_id'],
                'native_metadata': observed, 'referenced_file_read': False,
                'notice': 'Metadata only; returned identity/path does not authorize capture or change ownership.'}
    result = {'version': 1, 'project': str(project), 'session': session, 'agent': item['agent'],
              'main_source': str(child_path), 'forked_from_id': metadata.get('forked_from_id'),
              'history_base': base, 'source': str(source), 'available_bytes': source.stat().st_size,
              'source_logical_session': observed['id'], 'source_rollout': base['thread_id'],
              'first_record_ordinal': ordinal,
              'source_metadata': {key: parent_metadata[key] for key in (
                  'id', 'session_id', 'cwd', 'cli_version', 'history_mode', 'forked_from_id',
                  'forked_from_ordinal_exclusive', 'history_base')
                                  if key in parent_metadata},
              'source_agent': item['agent'] if observed['id'] == session else None,
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


def capture_prefix_chain(cwd: Path, session: str, expected: tuple[str, int, int], destination: Path) -> dict:
    """Capture only the decreasing chain declared by canonical source headers.

    Every physical source must resolve through the same owning daemon, have a
    matching canonical physical/logical name and header, and retain an existing
    project association. No filename search, third-party path or guessed parent
    is accepted. A partial result preserves acquired segments with complete=false.
    """
    from graphtraj.runtimes.codex.finalize import proxy
    from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError

    configuration = load_project_configuration(cwd)
    project = configuration.harness_root
    if (project / '.graphtraj/migration-snapshot.yml').exists():
        raise ValueError('Capture a declared chain only through the original lawful native host.')
    inventory = session_sources(configuration.state, project / '.graphtraj/runner', project)
    owned = {item['session']: item for item in inventory
             if item.get('runtime') == 'codex' and item.get('agent') and not item.get('identity_conflicts')}
    main = owned.get(session)
    if main is None or main.get('kind') != 'main':
        raise ValueError('An unambiguous associated Main is required.')
    binding = yaml.safe_load(Path(main['association']).read_text(encoding='utf-8'))
    connection = binding.get('connection', {})
    if connection.get('runtime') != 'codex' or connection.get('session') != session:
        raise ValueError('The original owning Main connection is unavailable.')
    destination = destination.resolve()
    if destination.exists() or destination.is_relative_to(project):
        raise ValueError('Chain capture must use a new destination outside the source project.')
    result = {'version': 1, 'project': str(project), 'session': session, 'agent': main['agent'],
              'history_base': dict(zip(('thread_id', 'end_ordinal_exclusive', 'end_byte_offset'), expected)),
              'segments': [], 'complete': False}

    async def capture() -> None:
        """Read only each real header's next edge and its bounded physical segment."""
        async with proxy(connection) as client:
            current = await client.read_thread(session)
            path = Path(current.get('path') or '')
            if current.get('id') != session or not path.is_absolute():
                raise ValueError('Native Main source is unavailable.')
            metadata, _ = _metadata(path, session)
            base = declared_prefix(metadata)
            if base != result['history_base']:
                raise ValueError('Main declaration differs from the exact authorized initial prefix.')
            result['forked_from_id'] = metadata.get('forked_from_id')
            result['logical_fork_cut'] = metadata.get('forked_from_ordinal_exclusive')
            visited = set()
            destination.mkdir(mode=0o700, parents=True)
            while True:
                if base['thread_id'] in visited:
                    raise ValueError('Declared physical inheritance chain contains a cycle.')
                visited.add(base['thread_id'])
                result['next_reference'] = base
                observed = await client.inspect_thread_reference(base['thread_id'])
                logical = observed.get('id')
                owner = owned.get(logical)
                source = Path(observed.get('path') or '')
                if (owner is None or not source.is_absolute()
                        or observed.get('cwd') != str(project) or observed.get('historyMode') != 'paginated'
                        or rollout_identity(source) != (logical, base['thread_id'])):
                    raise ValueError('Declared physical source lacks matching native/project ownership metadata.')
                header, first_ordinal = _metadata(source, logical)
                if (header.get('cwd') != str(project) or header.get('history_mode') != 'paginated'
                        or header.get('forked_from_id') != observed.get('forkedFromId')
                        or type(first_ordinal) is not int or not 0 <= first_ordinal < base['end_ordinal_exclusive']):
                    raise ValueError('Declared source header conflicts with its native metadata or ordinal cut.')
                local = destination / (base['thread_id'] + '.jsonl')
                digest = hashlib.sha256()
                remaining = base['end_byte_offset']
                with source.open('rb') as reader, local.open('xb') as writer:
                    local.chmod(0o600)
                    while remaining:
                        block = reader.read(min(1024 * 1024, remaining))
                        if not block:
                            raise ValueError('Declared source is shorter than its bounded prefix.')
                        writer.write(block)
                        digest.update(block)
                        remaining -= len(block)
                captured_header, captured_first = _metadata(local, logical)
                if captured_header != header or captured_first != first_ordinal:
                    raise ValueError('Native source header changed during bounded capture.')
                ordinal = first_ordinal
                with local.open('rb') as stream:
                    for line in stream:
                        record = json.loads(line)
                        if not line.endswith(b'\n') or record.get('ordinal') != ordinal:
                            raise ValueError('Captured segment has a split record or noncontiguous ordinals.')
                        ordinal += 1
                if ordinal != base['end_ordinal_exclusive']:
                    raise ValueError('Captured byte cut does not reach the declared exclusive ordinal.')
                result['segments'].append({
                    'source': str(source), 'source_rollout': base['thread_id'],
                    'source_logical_session': logical, 'source_agent': owner['agent'],
                    'association': owner['association'], 'stored': local.name,
                    'first_ordinal': first_ordinal, 'end_ordinal_exclusive': ordinal,
                    'bytes': base['end_byte_offset'], 'sha256': digest.hexdigest(),
                    'records': ordinal - first_ordinal, 'history_base': header.get('history_base'),
                    'forked_from_id': header.get('forked_from_id'),
                    'logical_fork_cut': header.get('forked_from_ordinal_exclusive')})
                if first_ordinal == 0:
                    if header.get('history_base'):
                        raise ValueError('An ordinal-zero source unexpectedly declares another inherited prefix.')
                    result['complete'] = True
                    result.pop('next_reference', None)
                    return
                previous = declared_prefix(header)
                if previous['end_ordinal_exclusive'] != first_ordinal:
                    raise ValueError('The next declared segment does not meet the exact preceding ordinal boundary.')
                base = previous

    try:
        asyncio.run(capture())
    except (OSError, ValueError, RuntimeAdapterError) as error:
        if not destination.exists():
            raise
        result['missing'] = str(error)
    result['captured_records'] = sum(item['records'] for item in result['segments'])
    result['captured_bytes'] = sum(item['bytes'] for item in result['segments'])
    manifest = destination / 'chain.yml'
    manifest.write_text(yaml.safe_dump(result, sort_keys=False), encoding='utf-8')
    manifest.chmod(0o600)
    return {**result, 'capture': str(destination)}
