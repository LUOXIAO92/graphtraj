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
    preview = CliRunner().invoke(main, ['migration-prefix', '--session', 'main'])
    assert preview.exit_code == 0, preview.output
    metadata = yaml.safe_load(preview.output)
    assert metadata['history_base']['thread_id'] == 'prefix'
    assert metadata['forked_from_id'] == 'different-real-parent'
    assert metadata['source_agent'] is None and calls == ['main', 'prefix']
    assert 'inherited' not in preview.output and 'exact-ciphertext' not in preview.output
    destination = tmp_path / 'capture'
    result = CliRunner().invoke(main, ['migration-prefix', '--session', 'main', '--capture', str(destination)])
    assert result.exit_code == 0, result.output
    saved = yaml.safe_load(result.output)
    assert saved['complete'] is True and saved['records'] == 3
    assert (destination / 'prefix.jsonl').read_bytes() == content
    assert _snapshot(root) == original and parent.read_bytes() == original_parent
    assert calls == ['main', 'prefix', 'main', 'prefix']
    assert CliRunner().invoke(main, ['migration-prefix', '--session', 'unassociated']).exit_code != 0
    assert calls == ['main', 'prefix', 'main', 'prefix']


def test_prefix_capture_refuses_identity_mismatch_and_partial_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A declared source does not authorize unrelated IDs, split records or project writes."""
    root, parent, content, calls = _project(tmp_path, monkeypatch)
    for destination in (root / 'nested', tmp_path):
        result = CliRunner().invoke(main, ['migration-prefix', '--session', 'main', '--capture', str(destination)])
        assert result.exit_code != 0
    parent.write_bytes(content.replace(b'"prefix"', b'"others"', 1))
    result = CliRunner().invoke(main, ['migration-prefix', '--session', 'main'])
    assert result.exit_code != 0 and 'does not identify' in result.output
    parent.write_bytes(content[:-1] + b'x')
    destination = tmp_path / 'broken'
    result = CliRunner().invoke(main, ['migration-prefix', '--session', 'main', '--capture', str(destination)])
    assert result.exit_code != 0 and not destination.exists()
