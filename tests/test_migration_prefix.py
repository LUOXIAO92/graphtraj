"""Public bounded prefix acquisition through the existing native owner."""
import json
from pathlib import Path

from click.testing import CliRunner
import pytest
import yaml

from graphtraj.interfaces.cli.graphtraj import main
from test_task_migration import _ticket_project, _snapshot


def _project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, bytes, list[str]]:
    """Bind an isolated Main and a metadata-only native host for two exact IDs."""
    root = tmp_path / 'project'
    root.mkdir()
    _ticket_project(root)
    parent = tmp_path / 'native-parent.jsonl'
    rows = [{'type': 'session_meta', 'ordinal': 0, 'payload': {'id': 'prefix', 'cwd': str(root)}},
            {'type': 'response_item', 'ordinal': 1, 'payload': {'encrypted_content': 'exact-ciphertext'}},
            {'type': 'response_item', 'ordinal': 2, 'payload': {'text': 'inherited'}}]
    content = ''.join(json.dumps(row) + '\n' for row in rows).encode()
    parent.write_bytes(content + b'{"ordinal":3,"payload":"outside-declared-prefix"}\n')
    child = tmp_path / 'native-main.jsonl'
    child.write_text(json.dumps({'type': 'session_meta', 'ordinal': 3, 'payload': {
        'id': 'main', 'forked_from_id': 'different-real-parent', 'history_base': {
            'thread_id': 'prefix', 'end_ordinal_exclusive': 3, 'end_byte_offset': len(content)}}}) + '\n')
    binding = root / '.graphtraj/runner/main-sessions/owned/session.yml'
    binding.parent.mkdir(parents=True)
    binding.write_text(yaml.safe_dump({'runtime': 'codex', 'session': 'main', 'cwd': str(root),
        'activity': {'trace_file': str(child)},
        'connection': {'runtime': 'codex', 'session': 'main', 'codex_home': '/never-scanned'}}))
    calls = []

    class NativeHost:
        """Represent only the existing metadata-query seam, without starting a Runtime."""
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def inspect_thread_reference(self, session: str) -> dict:
            calls.append(session)
            return {'id': 'prefix', 'path': str(parent), 'cwd': str(root)}

        async def read_thread(self, session: str) -> dict:
            calls.append(session)
            assert session in {'main', 'prefix'}
            return {'id': session, 'path': str(child if session == 'main' else parent)}

    monkeypatch.setattr('graphtraj.runtimes.codex.finalize.proxy', lambda connection: NativeHost())
    monkeypatch.chdir(root)
    return root, parent, content, calls


def test_public_prefix_preview_and_capture_do_not_write_originals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Capture the exact byte cut, preserve native identities, and never read a later tail."""
    root, parent, content, calls = _project(tmp_path, monkeypatch)
    original = _snapshot(root)
    original_parent = parent.read_bytes()
    preview = CliRunner().invoke(main, ['migration-prefix', '--expect-prefix', 'prefix', '3', str(len(content)), '--session', 'main'])
    assert preview.exit_code == 0, preview.output
    metadata = yaml.safe_load(preview.output)
    assert metadata['history_base']['thread_id'] == 'prefix'
    assert metadata['forked_from_id'] == 'different-real-parent'
    assert metadata['source_agent'] is None and calls == ['main', 'prefix']
    assert 'inherited' not in preview.output and 'exact-ciphertext' not in preview.output
    destination = tmp_path / 'capture'
    result = CliRunner().invoke(main, ['migration-prefix', '--expect-prefix', 'prefix', '3', str(len(content)), '--session', 'main', '--capture', str(destination)])
    assert result.exit_code == 0, result.output
    saved = yaml.safe_load(result.output)
    assert saved['complete'] is True and saved['records'] == 3
    assert (destination / 'prefix.jsonl').read_bytes() == content
    assert _snapshot(root) == original and parent.read_bytes() == original_parent
    assert calls == ['main', 'prefix', 'main', 'prefix']
    assert CliRunner().invoke(main, ['migration-prefix', '--expect-prefix', 'prefix', '3', str(len(content)), '--session', 'unassociated']).exit_code != 0
    assert calls == ['main', 'prefix', 'main', 'prefix']
    result = CliRunner().invoke(main, ['migration-prefix', '--session', 'main',
        '--expect-prefix', 'different-source', '3', str(len(content))])
    assert result.exit_code != 0 and calls[-1] == 'main'
    assert calls.count('prefix') == 2


def test_prefix_capture_refuses_identity_mismatch_and_partial_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A declared source does not authorize unrelated IDs, split records or project writes."""
    root, parent, content, calls = _project(tmp_path, monkeypatch)
    for destination in (root / 'nested', tmp_path):
        result = CliRunner().invoke(main, ['migration-prefix', '--expect-prefix', 'prefix', '3', str(len(content)), '--session', 'main', '--capture', str(destination)])
        assert result.exit_code != 0
    parent.write_bytes(content.replace(b'"prefix"', b'"others"', 1))
    result = CliRunner().invoke(main, ['migration-prefix', '--expect-prefix', 'prefix', '3', str(len(content)), '--session', 'main'])
    assert result.exit_code != 0 and 'does not identify' in result.output
    parent.write_bytes(content[:-1] + b'x')
    destination = tmp_path / 'broken'
    result = CliRunner().invoke(main, ['migration-prefix', '--expect-prefix', 'prefix', '3', str(len(content)), '--session', 'main', '--capture', str(destination)])
    assert result.exit_code != 0 and not destination.exists()


def test_reference_diagnostic_does_not_read_the_referenced_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only metadata is read during diagnosis, with no capture authority implied."""
    root, parent, content, calls = _project(tmp_path, monkeypatch)
    before = _snapshot(root)
    parent.unlink()
    result = CliRunner().invoke(main, ['migration-prefix', '--session', 'main',
        '--expect-prefix', 'prefix', '3', str(len(content)), '--diagnose'])
    assert result.exit_code == 0, result.output
    report = yaml.safe_load(result.output)
    assert report['expected_id'] == 'prefix' and report['actual_id'] == 'prefix'
    assert report['identity_matches'] is True and report['referenced_file_read'] is False
    assert calls == ['main', 'prefix'] and _snapshot(root) == before


def test_native_diagnostic_filters_content_without_weakening_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Normal native identity reads still refuse a redirect; diagnosis emits no preview/turns."""
    import asyncio
    from graphtraj.runtimes.codex.app_server import CodexAppServer
    from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError

    client = CodexAppServer(cwd=tmp_path, command=('unused',))
    calls = []

    async def reply(method: str, arguments: dict) -> dict:
        calls.append((method, arguments))
        return {'thread': {'id': 'actual', 'path': '/native/actual.jsonl', 'cwd': str(tmp_path),
                           'preview': 'private conversation', 'turns': [{'text': 'private'}],
                           'sessionId': 'native-hook', 'forkedFromId': 'origin'}}

    monkeypatch.setattr(client, '_call', reply)
    with pytest.raises(RuntimeAdapterError, match='different native Session'):
        asyncio.run(client.read_thread('requested'))
    result = asyncio.run(client.inspect_thread_reference('requested'))
    assert result['id'] == 'actual' and result['forkedFromId'] == 'origin'
    assert 'preview' not in result and 'turns' not in result
    assert calls == [('thread/read', {'threadId': 'requested', 'includeTurns': False})] * 2


def test_same_main_physical_rollout_requires_native_and_header_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A paginated storage segment is not a second logical Session or an arbitrary redirect."""
    main_id = '11111111-1111-4111-8111-111111111111'
    rollout_id = '22222222-2222-4222-8222-222222222222'
    fork = '33333333-3333-4333-8333-333333333333'
    root = tmp_path / 'project'
    root.mkdir()
    _ticket_project(root)
    source = tmp_path / f'rollout-2026-10-12T05-52-41-{main_id}_{rollout_id}.jsonl'
    metadata = {'id': main_id, 'session_id': main_id, 'cwd': str(root),
                'history_mode': 'paginated', 'forked_from_id': fork}
    rows = [{'type': 'session_meta', 'ordinal': 0, 'payload': metadata},
            {'type': 'response_item', 'ordinal': 1, 'payload': {'encrypted_content': 'original'}}]
    content = ''.join(json.dumps(row) + '\n' for row in rows).encode()
    source.write_bytes(content + b'{"ordinal":2,"payload":"beyond-prefix"}\n')
    child = tmp_path / 'current.jsonl'
    child.write_text(json.dumps({'type': 'session_meta', 'ordinal': 2, 'payload': {
        **metadata, 'history_base': {'thread_id': rollout_id,
                                   'end_ordinal_exclusive': 2, 'end_byte_offset': len(content)}}}) + '\n')
    binding = root / '.graphtraj/runner/main-sessions/owned/session.yml'
    binding.parent.mkdir(parents=True)
    binding.write_text(yaml.safe_dump({'runtime': 'codex', 'session': main_id, 'cwd': str(root),
        'activity': {'trace_file': str(child)},
        'connection': {'runtime': 'codex', 'session': main_id, 'codex_home': '/never-scanned'}}))
    observed = {'id': main_id, 'sessionId': main_id, 'cwd': str(root), 'path': str(source),
                'historyMode': 'paginated', 'forkedFromId': fork, 'source': 'vscode'}
    calls = []

    class Host:
        """Supply exact logical metadata for an explicitly requested physical segment."""
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def read_thread(self, identity: str) -> dict:
            assert identity == main_id
            calls.append(identity)
            return {'id': main_id, 'path': str(child)}

        async def inspect_thread_reference(self, identity: str) -> dict:
            assert identity == rollout_id
            calls.append(identity)
            return observed

    monkeypatch.setattr('graphtraj.runtimes.codex.finalize.proxy', lambda connection: Host())
    monkeypatch.chdir(root)
    command = ['migration-prefix', '--session', main_id,
               '--expect-prefix', rollout_id, '2', str(len(content))]
    preview = CliRunner().invoke(main, command)
    assert preview.exit_code == 0, preview.output
    facts = yaml.safe_load(preview.output)
    assert facts['source_logical_session'] == main_id and facts['source_rollout'] == rollout_id
    assert facts['source_agent'] == 'main' and facts['forked_from_id'] == fork
    captured = tmp_path / 'captured'
    result = CliRunner().invoke(main, command + ['--capture', str(captured)])
    assert result.exit_code == 0, result.output
    assert yaml.safe_load(result.output)['complete'] is True
    assert (captured / 'prefix.jsonl').read_bytes() == content
    observed['id'] = fork
    assert CliRunner().invoke(main, command).exit_code != 0
    observed['id'] = main_id
    observed['historyMode'] = 'copied'
    assert CliRunner().invoke(main, command).exit_code != 0
    observed['historyMode'] = 'paginated'
    source.write_bytes(content.replace(main_id.encode(), fork.encode(), 1))
    assert CliRunner().invoke(main, command).exit_code != 0
    assert set(calls) == {main_id, rollout_id}


def test_chain_follows_only_owned_declared_segments_and_stops_cycles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bounded ranges join exactly; a physical cycle stops before querying it twice."""
    main_id = '11111111-1111-4111-8111-111111111111'
    parent_id = '33333333-3333-4333-8333-333333333333'
    first_id = '44444444-4444-4444-8444-444444444444'
    second_id = '55555555-5555-4555-8555-555555555555'
    root = tmp_path / 'project'
    root.mkdir()
    _ticket_project(root)
    first = tmp_path / f'rollout-2026-10-12T05-52-41-{parent_id}_{first_id}.jsonl'
    second = tmp_path / f'rollout-2026-10-12T05-52-42-{main_id}_{second_id}.jsonl'
    current = tmp_path / 'current.jsonl'

    def write(path: Path, identity: str, ordinal: int, base: dict | None, fork: str | None) -> bytes:
        """Write one immutable native segment with explicit global coordinates."""
        metadata = {'id': identity, 'cwd': str(root), 'history_mode': 'paginated',
                    'forked_from_id': fork, 'forked_from_ordinal_exclusive': 2 if fork else None}
        if base:
            metadata['history_base'] = base
        rows = [{'type': 'session_meta', 'ordinal': ordinal, 'payload': metadata},
                {'type': 'response_item', 'ordinal': ordinal + 1, 'payload': {'encrypted_content': 'retained'}}]
        content = ''.join(json.dumps(row) + '\n' for row in rows).encode()
        path.write_bytes(content)
        return content

    older = write(first, parent_id, 0, None, None)
    newer = write(second, main_id, 2, {'thread_id': first_id, 'end_ordinal_exclusive': 2,
                                     'end_byte_offset': len(older)}, parent_id)
    write(current, main_id, 4, {'thread_id': second_id, 'end_ordinal_exclusive': 4,
                               'end_byte_offset': len(newer)}, parent_id)
    for identity, path in ((main_id, current), (parent_id, first)):
        binding = root / '.graphtraj/runner/main-sessions' / identity / 'session.yml'
        binding.parent.mkdir(parents=True)
        binding.write_text(yaml.safe_dump({'runtime': 'codex', 'session': identity, 'cwd': str(root),
            'activity': {'trace_file': str(path)},
            'connection': {'runtime': 'codex', 'session': identity, 'codex_home': '/never-scanned'}}))
    calls = []

    class Host:
        """Resolve only two physically declared, independently project-associated sources."""
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def read_thread(self, identity: str) -> dict:
            assert identity == main_id
            calls.append(identity)
            return {'id': main_id, 'path': str(current)}

        async def inspect_thread_reference(self, identity: str) -> dict:
            assert identity in {first_id, second_id}
            calls.append(identity)
            logical, path, fork = ((parent_id, first, None) if identity == first_id
                                   else (main_id, second, parent_id))
            return {'id': logical, 'path': str(path), 'cwd': str(root), 'historyMode': 'paginated',
                    'forkedFromId': fork}

    monkeypatch.setattr('graphtraj.runtimes.codex.finalize.proxy', lambda connection: Host())
    monkeypatch.chdir(root)
    command = ['migration-prefix', '--session', main_id, '--chain',
               '--expect-prefix', second_id, '4', str(len(newer))]
    destination = tmp_path / 'chain'
    result = CliRunner().invoke(main, command + ['--capture', str(destination)])
    assert result.exit_code == 0, result.output
    report = yaml.safe_load(result.output)
    assert report['complete'] is True and report['captured_records'] == 4
    assert report['logical_fork_cut'] == 2
    assert [item['source_logical_session'] for item in report['segments']] == [main_id, parent_id]
    assert (destination / (first_id + '.jsonl')).read_bytes() == older
    assert (destination / (second_id + '.jsonl')).read_bytes() == newer
    assert calls == [main_id, second_id, first_id]

    # The header now names its own physical ID; preserve the failed partial
    # capture and stop before a second query or any guessed alternative source.
    newer = write(second, main_id, 2, {'thread_id': second_id, 'end_ordinal_exclusive': 2,
                                     'end_byte_offset': len(older)}, parent_id)
    write(current, main_id, 4, {'thread_id': second_id, 'end_ordinal_exclusive': 4,
                               'end_byte_offset': len(newer)}, parent_id)
    calls.clear()
    destination = tmp_path / 'cycle'
    result = CliRunner().invoke(main, ['migration-prefix', '--session', main_id, '--chain',
        '--expect-prefix', second_id, '4', str(len(newer)), '--capture', str(destination)])
    assert result.exit_code == 1
    report = yaml.safe_load((destination / 'chain.yml').read_text())
    assert report['complete'] is False and 'cycle' in report['missing']
    assert calls == [main_id, second_id] and len(report['segments']) == 1
