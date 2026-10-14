"""DSH append collection through the native Runtime entry and installed API."""

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from click.testing import CliRunner
import pytest

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.execution.main_finalize import session_binding
from graphtraj.runtimes.native_entry import main
from graphtraj.sessions.protocol import native_record
from graphtraj.sessions.storage import SessionStore, session_path


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create an isolated configured project and native Main association."""
    config = tmp_path / '.graphtraj/config.yml'
    config.parent.mkdir()
    config.write_text(default_configuration_content(tmp_path, tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('GRAPHTRAJ_ROLE', raising=False)
    return tmp_path


def native(event: dict) -> dict:
    """Call the shipped native lifecycle command with an owned callback."""
    result = CliRunner().invoke(main, ['dsh'], input=json.dumps(event))
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def bind(monkeypatch: pytest.MonkeyPatch, header: dict) -> None:
    """Present the same native shell namespace as the DSH plugin."""
    monkeypatch.setenv('DSH_SESSION_ID', header['id'])
    monkeypatch.setenv('DSH_GRAPHTRAJ_SESSION', header['id'])
    monkeypatch.setenv('DSH_GRAPHTRAJ_SOURCE', 'child' if header.get('origin') else 'main')
    result = native({'event': 'agent/created', 'source': 'startup', 'header': header})
    assert 'error' not in result, result


def event(kind: str, seq: int, data: dict, **extra: object) -> dict:
    """Build a fixed-version native event with an explicit native position."""
    return {'type': kind, 'seq': seq, 'time': 100 + seq, 'data': data, **extra}


def collect(header: dict, events: list[dict], attachments: dict | None = None) -> dict:
    """Submit actual native events and optional capability-resolved bytes."""
    return native({'event': 'session/collect', 'header': header, 'records': [
        {'event': item, 'attachments': attachments or {}} for item in events
    ]})


def test_native_log_usage_resume_and_portable_attachments(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep surface, failed attempts, unknown records and bytes in one archive."""
    header = {'version': 4, 'id': 'main', 'createdAt': 1, 'isSeeded': False}
    bind(monkeypatch, header)
    usage = {'inputTokens': 13, 'cacheReadTokens': 7, 'cacheWriteTokens': 3, 'outputTokens': 2}
    chunk = {'type': 'chunk', 'time': 100, 'chunk': {'type': 'usage', 'usage': usage}}
    message = {'id': 'answer', 'role': 'assistant', 'source': {
        'kind': 'model', 'provider': 'deepseek', 'model': 'flash',
        'replayState': {'ciphertext': 'opaque-secret', 'signature': 'exact'}},
        'content': [{'type': 'text', 'text': 'done'}]}
    rows = [
        event('turn/start', 0, {'turn': 0}),
        event('assistant/attempt', 1, {'turn': 0, 'step': 0, 'stream': [chunk, {
            'type': 'chunk', 'time': 101, 'chunk': {'type': 'finish', 'reason': {
                'kind': 'error', 'failure': {'message': 'retry me', 'code': 'TIMEOUT'}}}}]}),
        event('tool/call', 2, {'turn': 0, 'step': 0, 'callId': 'c', 'name': 'read', 'arguments': '{}'}),
        event('tool/result', 3, {'turn': 0, 'step': 0, 'message': {
            'id': 'result', 'role': 'tool', 'toolCallId': 'c',
            'source': {'kind': 'tool', 'callId': 'c'}, 'content': [{'type': 'text', 'text': 'ok'}]}},
            surfaceOp='append'),
        event('assistant/message', 4, {'turn': 0, 'step': 1, 'message': message,
            'stream': [chunk], 'usage': {**usage, 'inputTokens': 17}}, surfaceOp='append'),
        event('extension/attachment', 5, {'file': {'attachmentId': 'file-id', 'bytes': 3, 'name': 'x'},
                                        'lost': {'attachmentId': 'lost-id', 'bytes': 1, 'name': 'gone'},
                                        'future': {'probabilities': None}}, ignorable=True),
    ]
    attached = {'$/data/file': {'base64': base64.b64encode(b'abc').decode()},
                '$/data/lost': {'missing': 'AttachmentError: object no longer available'}}
    assert collect(header, rows, attached) == {'session': 'dsh:main', 'position': 5}
    # A new native lifecycle replays from zero; already durable records are skipped.
    bind(monkeypatch, header)
    assert collect(header, rows, attached)['position'] == 5
    source = session_path(project / '.graphtraj/state', 'dsh:main')
    exported = project / 'standalone.sqlite3'
    with SessionStore(source) as store:
        store.validate()
        stored = store.page()['events']
        assert [native_record(row) for row in stored] == rows
        assert [row['type'] for row in stored if 'surfaceOp' in row] == ['tool/result', 'assistant/message']
        assert stored[1]['graphtraj']['usage'] == usage
        assert stored[4]['graphtraj']['usage'] == {**usage, 'inputTokens': 17}
        assert stored[4]['graphtraj']['usageSource'] == 'data/usage'
        # Exactly one usage snapshot per attempt; stream and final are not summed.
        assert sum(row.get('graphtraj', {}).get('usage', {}).get('inputTokens', 0) for row in stored) == 30
        refs = stored[5]['graphtraj']['attachments']
        assert refs['$/data/lost']['missing']['reason'].startswith('AttachmentError:')
        store.export(exported)
    source.unlink()
    with SessionStore(exported, readonly=True) as store:
        assert store.attachment(refs['$/data/file']['sha256']) == b'abc'
        assert native_record(store.page()['events'][4])['data']['message'] == message


def test_checkpoint_replays_uncommitted_input_and_rejects_gaps(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed event leaves its cursor untouched; restart replays that event."""
    header = {'version': 4, 'id': 'replay', 'createdAt': 1, 'isSeeded': False}
    bind(monkeypatch, header)
    first = event('turn/start', 0, {'turn': 0})
    next_event = event('extension/file', 1, {'attachment': {'attachmentId': 'a', 'bytes': 3}})
    assert collect(header, [first])['position'] == 0
    assert 'error' in collect(header, [next_event], {'$/data/attachment': {'base64': 'not valid!'}})
    assert 'error' in collect(header, [event('turn/end', 2, {'turn': 0, 'reason': {'kind': 'completed'}})])
    with SessionStore(session_path(project / '.graphtraj/state', 'dsh:replay')) as store:
        assert store.next_seq == 1
        assert store.position('dsh/session/event/v4') == 0
    assert collect(header, [first, next_event])['position'] == 1
    future = {**header, 'version': 5}
    assert 'error' in collect(future, [])


def test_main_native_child_and_managed_member_sources(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Native lineage does not claim Main; the actual process binding owns members."""
    from graphtraj.execution import runner_status

    main_header = {'version': 4, 'id': 'main', 'createdAt': 1, 'isSeeded': False}
    bind(monkeypatch, main_header)
    assert collect(main_header, [])['position'] == -1
    binding = session_binding(project, 'dsh', 'main').read_bytes()
    child = {**main_header, 'id': 'child', 'origin': 'subagent', 'delegationDepth': 1,
             'isSeeded': True, 'parentSession': 'main'}
    bind(monkeypatch, child)
    assert collect(child, [event('session/end-seed', 0, {'inherited': True})])['position'] == 0
    assert session_binding(project, 'dsh', 'main').read_bytes() == binding
    with SessionStore(session_path(project / '.graphtraj/state', 'dsh:child')) as store:
        store.validate()
        assert store.header['parentSession'] == 'dsh:main'
        assert store.header['graphtraj']['source'] == 'child'
        assert store.header['graphtraj']['agentId'] != 'dsh:main'

    member = {**main_header, 'id': 'member'}
    monkeypatch.setenv('GRAPHTRAJ_ROLE', 'engineer')
    monkeypatch.setenv('DSH_SESSION_ID', 'member')
    monkeypatch.setenv('DSH_GRAPHTRAJ_SESSION', 'member')
    monkeypatch.setenv('DSH_GRAPHTRAJ_SOURCE', 'main')
    assert collect(member, []) == {'deferred': True}
    monkeypatch.setattr(runner_status, 'process_caller_alias', lambda *args: 'owned-member')
    monkeypatch.setattr(runner_status, 'read_alias_mapping', lambda *args: (
        {'runtime': 'dsh', 'session': 'member', 'ticket_id': '315'}, project))
    assert collect(member, [])['position'] == -1
    with SessionStore(session_path(project / '.graphtraj/state', 'dsh:member')) as store:
        assert store.header['graphtraj']['source'] == 'member'
        assert store.header['graphtraj']['agentId'] == 'owned-member'
        assert store.header['graphtraj']['taskIds'] == ['315']
    assert 'error' in collect(main_header, [])


def test_installed_dsh_append_flush_and_resume(project: Path) -> None:
    """Run real DSH Session services through Python collection, without a model."""
    node, dsh = shutil.which('node'), shutil.which('dsh')
    if node is None or dsh is None:
        pytest.skip('Installed DSH and Node are required for native API evidence.')
    root = Path(__file__).resolve().parents[1]
    environment = {**os.environ, 'PYTHONPATH': str(root / 'src')}
    environment.pop('GRAPHTRAJ_ROLE', None)
    result = subprocess.run([
        node, str(root / 'tests/fixtures/dsh_collection.mjs'), str(Path(dsh).resolve()),
        str(root / 'src/graphtraj/runtimes/dsh/collection.mjs'), sys.executable,
    ], cwd=project, env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    facts = json.loads(result.stdout.strip().splitlines()[-1])
    assert facts['count'] == 5
    with SessionStore(session_path(project / '.graphtraj/state', 'dsh:real-main')) as store:
        store.validate()
        assert store.next_seq == 6
        assert store.page()['events'][2]['data']['content'][0]['text'] == 'native append sentinel'
    with SessionStore(session_path(project / '.graphtraj/state', 'dsh:real-child')) as store:
        store.validate()
        assert store.header['graphtraj']['source'] == 'child'
        assert store.header['parentSession'] == 'dsh:real-main'
        assert store.next_seq > 5
