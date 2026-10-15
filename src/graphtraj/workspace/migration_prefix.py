"""Capture only a Main Session's explicitly declared Codex inherited prefix."""
from __future__ import annotations

import asyncio
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil

import yaml

from graphtraj.runtimes.codex.physical_history import rollout_identity, locate_physical_rollout, open_physical_rollout

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


def capture_prefix_chain(
    cwd: Path,
    session: str,
    expected: tuple[str, int, int],
    destination: Path,
    retained: Path | None = None,
) -> dict:
    """Capture only the decreasing chain declared by canonical source headers.

    A continuation verifies and copies retained segments, then locates only exact
    declared physical IDs inside the owning connection's sessions directory.
    Native logical ownership and header/boundary checks remain mandatory.
    A partial result preserves acquired segments with complete=false.
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

    previous_capture = verify_partial_chain(project, session, retained) if retained else None

    async def capture() -> None:
        """Read only each real header's next edge and its bounded physical segment."""
        async with proxy(connection) as client:
            current = await client.read_thread(session)
            path = Path(current.get('path') or '')
            if current.get('id') != session or not path.is_absolute():
                raise ValueError('Native Main source is unavailable.')
            if retained is not None:
                if current.get('cwd') != str(project) or current.get('historyMode') != 'paginated':
                    raise ValueError('Owning Main metadata does not match this paginated project Session.')
                with open_physical_rollout(Path(connection['codex_home']), path) as stream:
                    record = json.loads(stream.readline())
                metadata = record.get('payload', {})
                if (record.get('type') != 'session_meta' or metadata.get('id') != session
                        or metadata.get('cwd') != str(project) or metadata.get('history_mode') != 'paginated'):
                    raise ValueError('Owning Main header does not match its native project identity.')
            else:
                metadata, _ = _metadata(path, session)
            base = declared_prefix(metadata)
            if base != result['history_base']:
                raise ValueError('Main declaration differs from the exact authorized initial prefix.')
            result['forked_from_id'] = metadata.get('forked_from_id')
            result['logical_fork_cut'] = metadata.get('forked_from_ordinal_exclusive')
            visited = set()
            if previous_capture is not None and (previous_capture['history_base'] != base
                                                 or previous_capture.get('agent') != main['agent']):
                raise ValueError('Retained chain differs from the current Main declaration.')
            destination.mkdir(mode=0o700, parents=True)
            if previous_capture is not None:
                for item in previous_capture['segments']:
                    owner = owned.get(item['source_logical_session'])
                    if (owner is None or item.get('source_agent') != owner['agent']
                            or rollout_identity(Path(item['source'])) != (
                                item['source_logical_session'], item['source_rollout'])):
                        raise ValueError('Retained source no longer has matching physical/project ownership.')
                    local = destination / (item['source_rollout'] + '.jsonl')
                    shutil.copyfile(retained.parent / item['stored'], local)
                    local.chmod(0o600)
                    with local.open('rb') as stream:
                        if hashlib.file_digest(stream, 'sha256').hexdigest() != item['sha256']:
                            raise ValueError('Retained source changed during continuation copy.')
                    result['segments'].append({**item, 'stored': local.name})
                    visited.add(item['source_rollout'])
                base = previous_capture['next_reference']
                result['reused_segments'] = len(result['segments'])
            while True:
                if base['thread_id'] in visited:
                    raise ValueError('Declared physical inheritance chain contains a cycle.')
                visited.add(base['thread_id'])
                result['next_reference'] = base
                if retained is not None:
                    source = locate_physical_rollout(Path(connection['codex_home']), base['thread_id'])
                    logical, _ = rollout_identity(source)
                    if logical not in owned:
                        raise ValueError('Declared physical source has no existing project Session association.')
                    observed = await client.inspect_thread_reference(logical)
                    if observed.get('id') != logical:
                        raise ValueError('Native logical ownership differs from the physical source identity.')
                else:
                    observed = await client.inspect_thread_reference(base['thread_id'])
                    source = Path(observed.get('path') or '')
                logical = observed.get('id')
                owner = owned.get(logical)
                if (owner is None or not source.is_absolute()
                        or observed.get('cwd') != str(project) or observed.get('historyMode') != 'paginated'
                        or rollout_identity(source) != (logical, base['thread_id'])):
                    raise ValueError('Declared physical source lacks matching native/project ownership metadata.')
                local = destination / (base['thread_id'] + '.jsonl')
                digest = hashlib.sha256()
                remaining = base['end_byte_offset']
                source_reader = (open_physical_rollout(Path(connection['codex_home']), source)
                                 if retained is not None else source.open('rb'))
                with source_reader as reader:
                    line = reader.readline()
                    record = json.loads(line)
                    header = record.get('payload', {})
                    first_ordinal = record.get('ordinal')
                    if (not line.endswith(b'\n') or record.get('type') != 'session_meta'
                            or header.get('id') != logical or header.get('cwd') != str(project)
                            or header.get('history_mode') != 'paginated'
                            or header.get('forked_from_id') != observed.get('forkedFromId')
                            or type(first_ordinal) is not int
                            or not 0 <= first_ordinal < base['end_ordinal_exclusive']):
                        raise ValueError('Declared source header conflicts with native ownership or ordinal cut.')
                    reader.seek(0)
                    with local.open('xb') as writer:
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


def adopt_prefix_chain(cwd: Path, session: str, manifest: Path) -> dict:
    """Resolve one pending archive using only a fully verified local captured chain.

    The exact pre-operation SQLite archive is exported first and restored on any
    failed publication. Input/source bytes and other Task/Session state remain
    unchanged. Retrying an identical successful prefix is idempotent.
    """
    from datetime import timezone
    from graphtraj.sessions.storage import SessionStore, session_path
    from graphtraj.runtimes.codex.session_archive import CodexSessionArchive

    configuration = load_project_configuration(cwd)
    state = configuration.state
    if not (state / 'tasks').is_dir() or (state / 'tickets').exists():
        raise ValueError('Complete Task-format migration before adopting a captured prefix.')
    snapshot = configuration.harness_root / '.graphtraj/migration-snapshot.yml'
    project = (yaml.safe_load(snapshot.read_text(encoding='utf-8'))['project'] if snapshot.is_file()
               else str(configuration.harness_root))
    chain = yaml.safe_load(manifest.read_text(encoding='utf-8'))
    if (not isinstance(chain, dict) or chain.get('complete') is not True
            or chain.get('project') != project or chain.get('session') != session):
        raise ValueError('A complete captured chain for this exact project/Main is required.')
    edge = dict(chain['history_base'])
    segments = []
    visited = set()
    for item in chain['segments']:
        if (edge is None or item['source_rollout'] in visited or item['source_rollout'] != edge['thread_id']
                or item['end_ordinal_exclusive'] != edge['end_ordinal_exclusive']
                or item['bytes'] != edge['end_byte_offset']
                or not 0 <= item['first_ordinal'] < item['end_ordinal_exclusive']
                or rollout_identity(Path(item['source'])) != (item['source_logical_session'], item['source_rollout'])):
            raise ValueError('Captured manifest has a conflicting physical edge or ordinal boundary.')
        visited.add(item['source_rollout'])
        relative = Path(item['stored'])
        path = manifest.parent / relative
        if (relative.is_absolute() or '..' in relative.parts
                or not path.resolve().is_relative_to(manifest.parent.resolve())):
            raise ValueError('Captured source path escapes its authorized artifact.')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != item['sha256']:
                raise ValueError('Captured source hash differs from its manifest.')
        if path.stat().st_size != item['bytes']:
            raise ValueError('Captured source size differs from its declared byte cut.')
        header, ordinal = _metadata(path, item['source_logical_session'])
        if (ordinal != item['first_ordinal'] or header.get('cwd') != project
                or header.get('history_mode') != 'paginated'
                or header.get('history_base') != item['history_base']):
            raise ValueError('Captured source header differs from its declared project/physical edge.')
        segments.append({**item, 'path': path})
        if ordinal == 0:
            if header.get('history_base'):
                raise ValueError('An ordinal-zero source cannot claim a further inherited prefix.')
            edge = None
        else:
            edge = declared_prefix(header)
            if edge['end_ordinal_exclusive'] != ordinal:
                raise ValueError('Captured physical segments leave an ordinal gap.')
    if not segments or edge is not None:
        raise ValueError('Captured chain does not reach ordinal zero.')
    archive = session_path(state, 'codex:' + session)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = configuration.harness_root / '.graphtraj/backups' / ('session-prefix-' + stamp)
    with SessionStore(archive, readonly=True) as store:
        header = store.header
        if header['graphtraj']['projectId'] != project or header['graphtraj']['agentId'] != chain['agent']:
            raise ValueError('Captured chain does not match the retained real Agent/project identity.')
        backup.mkdir(parents=True, mode=0o700)
        store.export(backup / 'session.sqlite3')
    # Keep the entire recovery input set locally, independent of the supplied
    # capture directory or cleaned original Runtime files. Business reads use
    # the resulting archive, never this backup as a fallback.
    saved = {**chain, 'segments': []}
    (backup / 'native-sources').mkdir(mode=0o700)
    for segment in segments:
        relative = 'native-sources/' + segment['sha256'] + '.jsonl'
        shutil.copy2(segment['path'], backup / relative)
        segment['path'] = backup / relative
        saved['segments'].append({key: value for key, value in segment.items() if key != 'path'})
        saved['segments'][-1]['stored'] = relative
    (backup / 'source.yml').write_text(yaml.safe_dump(saved, sort_keys=False), encoding='utf-8')
    try:
        result = CodexSessionArchive(state, project, chain['agent'], session).collect_history_prefix(
            segments, chain['history_base'])
    except BaseException:
        # The store is closed before replacing it; no process is resumed here.
        temporary = archive.with_suffix('.restoring')
        shutil.copy2(backup / 'session.sqlite3', temporary)
        temporary.replace(archive)
        raise
    return {**result, 'session': session, 'agent': chain['agent'],
            'segments': len(segments), 'backup': backup.relative_to(configuration.harness_root).as_posix(),
            'logical_parent': header.get('parentSession'), 'pending': False}

def verify_partial_chain(project: Path, session: str, manifest: Path) -> dict:
    """Verify retained bytes and the exact next header declaration without source access."""
    chain = yaml.safe_load(manifest.read_text(encoding='utf-8'))
    if (not isinstance(chain, dict) or chain.get('project') != str(project)
            or chain.get('session') != session or chain.get('complete') is not False
            or not chain.get('segments')):
        raise ValueError('An incomplete retained chain for this exact project/Main is required.')
    edge = chain['history_base']
    visited = set()
    for item in chain['segments']:
        relative = Path(item['stored'])
        local = manifest.parent / relative
        if (relative.is_absolute() or '..' in relative.parts
                or not local.resolve().is_relative_to(manifest.parent.resolve())):
            raise ValueError('Retained segment must remain within its capture directory.')
        if (item['source_rollout'] in visited or item['source_rollout'] != edge['thread_id']
                or item['end_ordinal_exclusive'] != edge['end_ordinal_exclusive']
                or item['bytes'] != edge['end_byte_offset']
                or local.stat().st_size != item['bytes']):
            raise ValueError('Retained chain has a conflicting edge or byte boundary.')
        visited.add(item['source_rollout'])
        with local.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != item['sha256']:
            raise ValueError('Retained segment hash differs from its capture manifest.')
        header, ordinal = _metadata(local, item['source_logical_session'])
        if (header.get('cwd') != str(project) or header.get('history_mode') != 'paginated'
                or type(ordinal) is not int or ordinal != item['first_ordinal']):
            raise ValueError('Retained source header conflicts with its capture metadata.')
        with local.open('rb') as stream:
            for line in stream:
                if not line.endswith(b'\n') or json.loads(line).get('ordinal') != ordinal:
                    raise ValueError('Retained segment ordinal sequence is incomplete.')
                ordinal += 1
        if ordinal != edge['end_ordinal_exclusive']:
            raise ValueError('Retained segment does not meet its declared ordinal cut.')
        edge = declared_prefix(header)
        if edge['end_ordinal_exclusive'] != item['first_ordinal']:
            raise ValueError('Retained declaration does not meet the preceding boundary.')
    if edge != chain.get('next_reference') or edge['thread_id'] in visited:
        raise ValueError('Next reference conflicts with the retained declaration or forms a cycle.')

    return chain


def diagnose_next_prefix(cwd: Path, session: str, manifest: Path) -> dict:
    """Diagnose only a verified partial capture's next declared native reference.

    Retained bytes authenticate the chain and boundary before any daemon query.
    The returned native source is never opened, even when its identity matches.
    """
    from graphtraj.runtimes.codex.finalize import proxy

    configuration = load_project_configuration(cwd)
    project = configuration.harness_root
    chain = verify_partial_chain(project, session, manifest)
    edge = chain['next_reference']

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

    async def diagnose() -> dict:
        """Query the exact next edge without reading its returned source path."""
        async with proxy(connection) as client:
            current = await client.read_thread(session)
            path = Path(current.get('path') or '')
            if current.get('id') != session or not path.is_absolute():
                raise ValueError('Native Main source is unavailable.')
            header, _ = _metadata(path, session)
            if declared_prefix(header) != chain['history_base']:
                raise ValueError('Current Main declaration differs from the retained chain.')
            observed = await client.inspect_thread_reference(edge['thread_id'])
            logical = observed.get('id')
            source = Path(observed.get('path') or '')
            try:
                identities = rollout_identity(source)
                name_error = None
            except ValueError as error:
                identities = (None, None)
                name_error = str(error)
            checks = {'associated_native_session': logical in owned,
                      'absolute_native_path': source.is_absolute(),
                      'native_project_matches': observed.get('cwd') == str(project),
                      'native_history_paginated': observed.get('historyMode') == 'paginated',
                      'canonical_logical_id_matches': identities[0] == logical,
                      'canonical_physical_id_matches': identities[1] == edge['thread_id']}
            return {'project': str(project), 'session': session, 'next_reference': edge,
                    'verified_retained_segments': len(chain['segments']),
                    'native_metadata': observed, 'parsed_logical_id': identities[0],
                    'parsed_physical_id': identities[1], 'canonical_name_error': name_error,
                    'ownership_checks': checks, 'source_eligible': all(checks.values()),
                    'referenced_file_read': False, 'complete': False}

    return asyncio.run(diagnose())
