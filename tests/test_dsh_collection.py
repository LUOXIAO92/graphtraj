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
from conftest import unsupported_dsh

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.execution.main_finalize import session_binding
from graphtraj.runtimes.native_entry import main
from agent_swarm.sessions.protocol import native_record
from agent_swarm.sessions.archive import JsonlSessionStore, archive_path
from agent_swarm.sessions.protocol import validate_session


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
    assert collect(header, rows, attached) == {'session': 'dsh:main', 'position': 5, 'saved': True}
    # A new native lifecycle replays from zero; already durable records are skipped.
    bind(monkeypatch, header)
    assert collect(header, rows, attached)['position'] == 5
    source = archive_path(project / '.graphtraj/swarm', 'dsh:main')
    exported = project / 'standalone' / 'session.jsonl'
    store = JsonlSessionStore(source)
    validate_session(store.header, store.page()['events'])
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
    shutil.copytree(source.parent, exported.parent)
    source.unlink()
    store = JsonlSessionStore(exported)
    assert store.attachment(refs['$/data/file']['sha256']) == b'abc'
    assert native_record(store.page()['events'][4])['data']['message'] == message


def test_checkpoint_replays_uncommitted_input_and_retains_gaps(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed event leaves its cursor untouched; restart replays that event."""
    header = {'version': 4, 'id': 'replay', 'createdAt': 1, 'isSeeded': False}
    bind(monkeypatch, header)
    first = event('turn/start', 0, {'turn': 0})
    next_event = event('extension/file', 1, {'attachment': {'attachmentId': 'a', 'bytes': 3}})
    assert collect(header, [first])['position'] == 0
    assert 'error' in collect(header, [next_event], {'$/data/attachment': {'base64': 'not valid!'}})
    final = event('turn/end', 2, {'turn': 0, 'reason': {'kind': 'completed'}})
    assert collect(header, [final])['position'] == 2
    store = JsonlSessionStore(archive_path(project / '.graphtraj/swarm', 'dsh:replay'))
    assert len(store.page()['events']) == 1
    assert store.position('dsh/session/event/v4') == 0
    assert store.pending()
    with pytest.raises(ValueError, match='incomplete'):
        store.messages()
    assert collect(header, [first, next_event])['position'] == 1
    assert collect(header, [first, next_event, final])['position'] == 2
    assert not JsonlSessionStore(store.path).pending()
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
    store = JsonlSessionStore(archive_path(project / '.graphtraj/swarm', 'dsh:child'))
    validate_session(store.header, store.page()['events'])
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
        {'runtime': 'dsh', 'session': 'member', 'task_id': '315'}, project))
    assert collect(member, [])['position'] == -1
    store = JsonlSessionStore(archive_path(project / '.graphtraj/swarm', 'dsh:member'))
    assert store.header['graphtraj']['source'] == 'member'
    assert store.header['graphtraj']['agentId'] == 'owned-member'
    assert store.header['graphtraj']['taskIds'] == ['315']
    assert 'error' in collect(main_header, [])


def test_installed_dsh_append_flush_and_resume(project: Path) -> None:
    """Run real DSH Session services through Python collection, without a model."""
    node, dsh = shutil.which('node'), shutil.which('dsh')
    if node is None or dsh is None:
        pytest.skip('Installed DSH and Node are required for native API evidence.')
    if (reason := unsupported_dsh()) is not None:
        pytest.skip(reason)
    root = Path(__file__).resolve().parents[1]
    environment = {**os.environ, 'PYTHONPATH': str(root / 'src')}
    environment.pop('GRAPHTRAJ_ROLE', None)
    result = subprocess.run([
        node, str(root / 'tests/fixtures/dsh_collection.mjs'), str(Path(dsh).resolve()),
        str(root / 'src/graphtraj/runtimes/dsh/collection.mjs'), sys.executable,
    ], cwd=project, env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    facts = json.loads(result.stdout.strip().splitlines()[-1])
    assert facts['callbackBeforeDisk']
    assert facts['nativeDiskEvents'] == facts['events']
    assert facts['count'] == 5
    # Compare Python reconstruction to the installed Runtime's own projection,
    # including the native fork seed and the event drained during disposal.
    from agent_swarm.sessions.dsh import collect_jsonl
    from agent_swarm.sessions.archive import SessionArchive, JsonlSessionStore, archive_path

    archive = SessionArchive(project / 'optional', save_normalized_sessions=True, backfill_history=True)
    for sample in (facts, facts['child']):
        records = [{'event': item} for item in sample['events']]
        saved = collect_jsonl(archive, sample['header'], records)
        replay = collect_jsonl(archive, sample['header'], records, historical=True)
        assert replay == saved
        store = JsonlSessionStore(archive_path(archive.root, saved['session']))
        assert store.messages() == sample['messages']
        assert [native_record(row) for row in store.page()['events']] == sample['events']
    store = JsonlSessionStore(archive_path(project / '.graphtraj/swarm', 'dsh:real-main'))
    assert len(store.page()['events']) == 6
    assert store.page()['events'][2]['data']['content'][0]['text'] == 'native append sentinel'
    child = JsonlSessionStore(archive_path(project / '.graphtraj/swarm', 'dsh:real-child'))
    assert child.header['origin'] == 'subagent'
    assert child.header['parentSession'] == 'dsh:real-main'
    assert len(child.page()['events']) > 5
    assert not (project / '.graphtraj/state/sessions').exists()


def test_optional_jsonl_uses_native_order_and_backfill_policy(tmp_path: Path) -> None:
    """Archive only mapped supplied history; native seq wins over timestamps."""
    from agent_swarm.sessions.dsh import collect_jsonl
    from agent_swarm.sessions.archive import SessionArchive, JsonlSessionStore, archive_path

    header = {'version': 4, 'id': 'optional', 'createdAt': 1, 'isSeeded': False}
    rows = [event('user/message', index, {
        'id': str(index), 'role': 'user', 'source': {'kind': 'user'},
        'content': [{'type': 'text', 'text': 'same text'}],
    }, surfaceOp='append') for index in range(2)]
    rows[0]['time'], rows[1]['time'] = 900, 100
    records = [{'event': row} for row in rows]
    archive = SessionArchive(tmp_path / 'optional')
    assert not collect_jsonl(archive, header, records)['saved']
    assert not archive.root.exists()
    archive.save_normalized_sessions = True
    assert not collect_jsonl(archive, header, records, historical=True)['saved']
    assert not archive.root.exists()
    saved = collect_jsonl(archive, header, records)
    store = JsonlSessionStore(archive_path(archive.root, saved['session']))
    assert [message['id'] for message in store.messages()] == ['0', '1']
    assert [row['time'] for row in store.page()['events']] == [900, 100]
    with pytest.raises(ValueError, match='complete native prefix'):
        collect_jsonl(archive, header, list(reversed(records)))
    archive.save_normalized_sessions = False
    assert not collect_jsonl(archive, header, records)['saved']
    assert JsonlSessionStore(store.path).messages() == store.messages()


def test_native_gap_backfill_and_disk_confirmation(tmp_path: Path) -> None:
    """Retain new content with a gap, then resolve it using the same native log."""
    from agent_swarm.sessions.dsh import DshArchive
    from agent_swarm.sessions.archive import SessionArchive, JsonlSessionStore, archive_path

    header = {'version': 4, 'id': 'gap', 'createdAt': 1, 'isSeeded': False}
    old = event('user/message', 0, {
        'id': 'old', 'role': 'user', 'source': {'kind': 'user'},
        'content': [{'type': 'text', 'text': 'old memory'}],
    }, surfaceOp='append')
    new = event('user/message', 1, {
        'id': 'new', 'role': 'user', 'source': {'kind': 'user'},
        'content': [{'type': 'text', 'text': 'new input'}],
    }, surfaceOp='append')
    archive = SessionArchive(tmp_path / 'archive', save_normalized_sessions=True)
    capture = DshArchive(archive, resumed=True)
    capture.start({'header': header, 'cursor': 0}, [])
    capture.event(new)
    store = JsonlSessionStore(archive_path(archive.root, 'dsh:gap'))
    assert store.page()['events'] == []
    assert store.pending()[0]['event']['data']['content'][0]['text'] == 'new input'
    with pytest.raises(ValueError, match='incomplete'):
        store.messages()
    trace = tmp_path / 'native.jsonl'
    trace.write_text('\n'.join(json.dumps(row) for row in [header, old]) + '\n')
    with pytest.raises(ValueError, match='persisted prefix'):
        capture.finish(trace)  # A callback is not proof of native disk flush.
    trace.write_text('\n'.join(json.dumps(row) for row in [header, old, new]) + '\n')
    capture.finish(trace)
    archive.backfill_history = True
    resumed = DshArchive(archive, resumed=True)
    resumed.start({'header': header, 'cursor': 1}, [{'event': old}, {'event': new}])
    resumed.finish(trace)
    store = JsonlSessionStore(store.path)
    assert not store.pending()
    assert [message['id'] for message in store.messages()] == ['old', 'new']
    assert len(store.observations()) == 1


@pytest.mark.parametrize('end_before_event', [False, True])
def test_live_frames_resolve_only_native_terminal_seq(tmp_path: Path, end_before_event: bool) -> None:
    """Live/final arrival variations retain native order and one final message."""
    from agent_swarm.sessions.dsh import DshArchive
    from agent_swarm.sessions.archive import SessionArchive, JsonlSessionStore, archive_path

    header = {'version': 4, 'id': 'live', 'createdAt': 1, 'isSeeded': False}
    archive = SessionArchive(tmp_path / 'archive', save_normalized_sessions=True)
    capture = DshArchive(archive, resumed=False)
    capture.start({'header': header, 'cursor': -1}, [], execution_id='execution')
    capture.frame({'type': 'start', 'attemptId': 'live:0', 'revision': 1,
                   'startedAfterSeq': -1, 'turn': 0, 'step': 0})
    chunk = {'type': 'chunk', 'attemptId': 'live:0', 'revision': 2, 'index': 0,
             'time': 90, 'chunk': {'type': 'text-delta', 'index': 0, 'text': 'body'}}
    capture.frame(chunk)
    capture.frame(chunk)
    path = archive_path(archive.root, 'dsh:live')
    partial = JsonlSessionStore(path).pending()[0]['event']
    assert partial['data']['stream'][0]['texts'] == ['body']
    final = event('assistant/message', 0, {'turn': 0, 'step': 0, 'stream': partial['data']['stream'],
        'message': {'id': 'answer', 'role': 'assistant',
                    'source': {'kind': 'model', 'provider': 'deepseek', 'model': 'native'},
                    'content': [{'type': 'text', 'text': 'body'}]}}, surfaceOp='append')
    end = {'type': 'end', 'attemptId': 'live:0', 'revision': 3, 'index': 1,
           'outcome': {'kind': 'committed', 'eventType': 'assistant/message', 'seq': 0}}
    if end_before_event:
        capture.frame(end)
        assert len(JsonlSessionStore(path).pending()) == 1
        capture.event(final)
    else:
        capture.event(final)
        assert len(JsonlSessionStore(path).pending()) == 1
        capture.frame(end)
    store = JsonlSessionStore(path)
    assert not store.pending()
    assert store.messages() == [final['data']['message']]
    assert native_record(store.page()['events'][0]) == final
    observation = store.observations()[0]
    assert observation['event']['data']['stream'] == partial['data']['stream']
    assert observation['final'] == ['dsh', 'live', 'event/0']
    before = path.read_bytes()
    assert not store.resolve_observation(('dsh', 'live', 'live/execution/live:0'), ('dsh', 'live', 'event/0'))
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match='another native event'):
        store.resolve_observation(('dsh', 'live', 'live/execution/live:0'), ('dsh', 'live', 'event/1'))


def test_terminal_observation_survives_gap_and_later_backfill(tmp_path: Path) -> None:
    """A saved end(seq) survives interruption before final publication."""
    from agent_swarm.sessions.dsh import DshArchive
    from agent_swarm.sessions.archive import SessionArchive, JsonlSessionStore, archive_path

    header = {'version': 4, 'id': 'resume-live', 'createdAt': 1, 'isSeeded': False}
    first = event('turn/start', 0, {'turn': 0})
    final = event('assistant/attempt', 1, {'turn': 0, 'step': 0, 'stream': []})
    archive = SessionArchive(tmp_path / 'archive', save_normalized_sessions=True)
    capture = DshArchive(archive, resumed=True)
    capture.start({'header': header, 'cursor': 0}, [], execution_id='old-execution')
    capture.frame({'type': 'start', 'attemptId': 'attempt', 'revision': 1,
                   'startedAfterSeq': 0, 'turn': 0, 'step': 0})
    capture.frame({'type': 'end', 'attemptId': 'attempt', 'revision': 2, 'index': 0,
                   'outcome': {'kind': 'committed', 'eventType': 'assistant/attempt', 'seq': 1}})
    capture.event(final)
    path = archive_path(archive.root, 'dsh:resume-live')
    assert len(JsonlSessionStore(path).pending()) == 2
    archive.backfill_history = True
    restored = DshArchive(archive, resumed=True)
    restored.start({'header': header, 'cursor': 1}, [{'event': first}, {'event': final}], execution_id='new-execution')
    store = JsonlSessionStore(path)
    assert not store.pending()
    assert len(store.observations()) == 2
    assert [native_record(row) for row in store.page()['events']] == [first, final]
    # Another abandoned observation remains separate, even with identical text.
    restored.frame({'type': 'start', 'attemptId': 'attempt', 'revision': 1,
                    'startedAfterSeq': 1, 'turn': 1, 'step': 0})
    restored.frame({'type': 'end', 'attemptId': 'attempt', 'revision': 2, 'index': 0,
                    'outcome': {'kind': 'abandoned'}})
    store = JsonlSessionStore(path)
    assert len(store.pending()) == 1
    assert store.pending()[0]['event']['graphtraj']['native']['locator'] == 'live/new-execution/attempt'
    assert len(store.observations()) == 2
