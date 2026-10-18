"""Pi native projection and JSONL collection, independent of model execution."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from graphtraj.runtimes.pi.collection import PiArchive, archive_messages
from graphtraj.runtimes.pi.projection import native_time, project_messages
from graphtraj.sessions.archive import SessionArchive


def entry(identity: str, parent: str | None, **fields: object) -> dict:
    """Create one native record with intentionally conflicting write time."""
    return {'id': identity, 'parentId': parent, 'timestamp': '2026-10-18T00:00:00Z', **fields}


def message(identity: str, parent: str | None, role: str, text: str) -> dict:
    """Keep repeated content while giving each native message its own identity."""
    return entry(identity, parent, type='message', message={
        'role': role, 'timestamp': 7, 'content': [{'type': 'text', 'text': text}],
        **({'model': 'test', 'provider': 'test', 'opaque': {'ciphertext': 'retained'}}
           if role == 'assistant' else {}),
    })


def history() -> list[dict]:
    """Include equal-text messages, a discarded branch, edits and compaction."""
    return [message('u', None, 'user', 'question'),
            message('a', 'u', 'assistant', 'same'),
            message('discarded', 'a', 'user', 'other branch'),
            message('b', 'a', 'assistant', 'same'),
            entry('view', 'b', type='custom', customType='agents/display',
                  data={'text': 'not model input'}),
            entry('c', 'view', type='compaction', summary='previous conversation',
                  tokensBefore=100, firstKeptEntryId='b'),
            entry('edit', 'c', type='context_edit', targetId='b', replacement={'content': 'edited'}),
            entry('custom', 'edit', type='custom_message', customType='notice', content='', display=True),
            entry('branch', 'custom', type='branch_summary', fromId='discarded', summary='returned')]


def test_branch_compaction_and_edits_keep_native_semantics() -> None:
    """Native ancestry determines order; display entries never enter context."""
    entries = history()
    original = json.dumps(entries)
    assert [m['content'][0]['text'] for m in project_messages(entries, 'b')] == ['question', 'same', 'same']
    projected = project_messages(entries, 'branch')
    assert [m['role'] for m in projected] == ['compactionSummary', 'assistant', 'custom', 'branchSummary']
    assert projected[1]['content'] == [{'type': 'text', 'text': 'edited'}]
    assert projected[1]['timestamp'] == 7
    assert projected[1]['opaque'] == {'ciphertext': 'retained'}
    assert projected[2]['content'] == ''
    assert json.dumps(entries) == original
    assert project_messages(entries, None) == []
    with pytest.raises(ValueError, match='incomplete'):
        project_messages(entries[1:], 'b')
    assert native_time({}) is None


def test_projection_matches_installed_pi_sdk() -> None:
    """Use the actual SDK as a pure offline oracle; no Runtime or credentials."""
    executable = shutil.which('pi')
    if executable is None or shutil.which('node') is None:
        pytest.skip('Installed Pi SDK and Node are required for the native oracle.')
    root = Path(executable).resolve().parents[1]
    module = root / 'core/session-manager.js'
    if not module.is_file():
        pytest.skip('Installed Pi does not expose the unbundled Session SDK.')
    script = '''
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const sdk = await import(pathToFileURL(process.argv[1]).href);
const entries = JSON.parse(readFileSync(0, 'utf8'));
console.log(JSON.stringify(entries.map(e => sdk.buildSessionProjection(entries, e.id).messages)));
'''
    entries = history()
    result = subprocess.run(['node', '--input-type=module', '-e', script, str(module)],
                            input=json.dumps(entries), text=True, capture_output=True, check=True)
    assert [project_messages(entries, e['id']) for e in entries] == json.loads(result.stdout)


def test_native_order_stream_link_and_reopen(tmp_path: Path) -> None:
    """Native final entries resolve live drafts without duplicating messages."""
    archive = SessionArchive(tmp_path, save_normalized_sessions=True, backfill_history=True)
    header = {'id': 'pi-test', 'type': 'session', 'timestamp': 3}
    entries = [message('u', None, 'user', 'question')]
    collector = PiArchive(archive, header, agent='agent', project=str(tmp_path),
                          entries=entries, leaf_id='u')
    final = message('a', 'u', 'assistant', 'x' * 80000)
    collector.receive({'type': 'message_start', 'message': {**final['message'], 'content': []}})
    for _ in range(80):
        collector.receive({'type': 'message_update', 'message': {}, 'assistantMessageEvent': {
            'type': 'text_delta', 'contentIndex': 0, 'delta': 'x' * 1000}})
    collector.receive({'type': 'message_end', 'message': final['message']})
    store = archive.store(collector.key)
    assert len(store.pending()) == 1
    # Completion B arrives first; the native Session records A then B.
    tool_a = message('tool-a', 'a', 'toolResult', 'A')
    tool_b = message('tool-b', 'tool-a', 'toolResult', 'B')
    tool_a['message']['toolCallId'] = 'call-a'
    tool_b['message']['toolCallId'] = 'call-b'
    for tool in (tool_b, tool_a):
        collector.receive({'type': 'tool_execution_end', 'toolCallId': tool['message']['toolCallId'],
                           'result': tool['message']})
    native = [*entries, final, tool_a, tool_b]
    collector.sync(native, 'tool-b')
    assert collector.messages() == [item['message'] for item in native]
    assert archive.store(collector.key).pending() == []
    observations = archive.store(collector.key).observations()
    assert len(observations) == 3
    assert len(observations[0]['event']['data']['stream']) == 3
    reopened = PiArchive(archive, header, agent='agent', project=str(tmp_path),
                         entries=native, leaf_id='tool-b')
    assert reopened.messages() == collector.messages()
    assert sum(event['type'] == 'graphtraj/native' for event in archive.store(collector.key).page()['events']) == 4


def test_archive_disabled_and_interrupted_partial(tmp_path: Path) -> None:
    """Disabled collection creates no files; interruption retains a compact gap."""
    header = {'id': 'pi-test', 'type': 'session', 'timestamp': 0}
    archive = SessionArchive(tmp_path)
    collector = PiArchive(archive, header, agent='agent', project=str(tmp_path), entries=[], leaf_id=None)
    collector.receive({'type': 'message_start', 'message': {'role': 'assistant'}})
    collector.close()
    assert list(tmp_path.iterdir()) == []
    archive.save_normalized_sessions = True
    collector.receive({'type': 'message_start', 'message': {'role': 'assistant'}})
    collector.receive({'type': 'message_update', 'message': {}, 'assistantMessageEvent': {
        'type': 'text_delta', 'contentIndex': 0, 'delta': 'interrupted'}})
    collector.close()
    draft = archive.store(collector.key).pending()[0]['event']
    assert next(item['text'] for item in draft['data']['stream'] if item['type'] == 'graphtraj/text-run') == 'interrupted'
    with pytest.raises(ValueError, match='unambiguous'):
        collector.messages()


def test_native_read_ahead_does_not_duplicate_late_rpc(tmp_path: Path) -> None:
    """get_entries can include the next response before its RPC queue drains."""
    archive = SessionArchive(tmp_path, save_normalized_sessions=True, backfill_history=True)
    header = {'id': 'ahead', 'type': 'session', 'timestamp': 1}
    first = message('a', None, 'assistant', 'first')
    second = message('b', 'a', 'assistant', 'second')
    collector = PiArchive(archive, header, agent='agent', project=str(tmp_path), entries=[], leaf_id=None)
    collector.receive({'type': 'message_start', 'message': {**first['message'], 'content': []}})
    collector.receive({'type': 'message_end', 'message': first['message']})
    collector.sync([first, second], 'b')
    assert sum(event['type'] == 'graphtraj/native' for event in archive.store(collector.key).page()['events']) == 1
    collector.receive({'type': 'message_start', 'message': {**second['message'], 'content': []}})
    collector.receive({'type': 'message_end', 'message': second['message']})
    collector.sync([first, second], 'b', settled=True)
    assert collector.messages() == [first['message'], second['message']]
    assert len(archive.store(collector.key).observations()) == 2


def test_interrupted_recovery_and_deferred_header(tmp_path: Path) -> None:
    """A persisted aborted message supplies final identity after pipe loss."""
    archive = SessionArchive(tmp_path, save_normalized_sessions=True, backfill_history=True)
    header = {'id': 'interrupted', 'type': 'session'}
    collector = PiArchive(archive, header, agent='agent', project=str(tmp_path), entries=[], leaf_id=None)
    final = message('a', None, 'assistant', 'partial plus native tail')
    final['message']['stopReason'] = 'aborted'
    collector.receive({'type': 'message_start', 'message': {**final['message'], 'content': []}})
    collector.receive({'type': 'message_update', 'message': {}, 'assistantMessageEvent': {
        'type': 'text_delta', 'contentIndex': 0, 'delta': 'partial'}})
    collector.close()
    persisted_header = {**header, 'timestamp': 5, 'version': 3}
    reopened = PiArchive(archive, persisted_header, agent='agent', project=str(tmp_path),
                         entries=[final], leaf_id='a')
    assert reopened.messages() == [final['message']]
    store = archive.store(collector.key)
    assert store.page()['events'][0]['data']['record'] == persisted_header
    assert store.header['createdAt'] == 0
    assert store.page()['events'][0]['time'] == 5
    assert next(item['text'] for item in store.observations()[0]['event']['data']['stream'] if item['type'] == 'graphtraj/text-run') == 'partial'


def test_backfill_and_equal_native_messages_keep_each_identity(tmp_path: Path) -> None:
    """Backfill adds only supplied mapped entries, even when bodies/times match."""
    archive = SessionArchive(tmp_path, save_normalized_sessions=True, backfill_history=False)
    header = {'id': 'history', 'type': 'session', 'timestamp': 0}
    first = message('a', None, 'assistant', 'same')
    second = message('b', 'a', 'assistant', 'same')
    collector = PiArchive(archive, header, agent='agent', project=str(tmp_path), entries=[first], leaf_id='a')
    collector.sync([first, second], 'b', settled=True)
    assert sum(event['type'] == 'graphtraj/native' for event in archive.store(collector.key).page()['events']) == 1
    with pytest.raises(ValueError, match='incomplete'):
        collector.messages()
    archive.backfill_history = True
    reopened = PiArchive(archive, header, agent='agent', project=str(tmp_path), entries=[first, second], leaf_id='b')
    assert reopened.messages() == [first['message'], second['message']]
    events = [event for event in archive.store(collector.key).page()['events'] if event['type'] == 'graphtraj/native']
    assert [event['data']['record']['id'] for event in events] == ['a', 'b']
    reopened.sync([first, second], 'a', settled=True)
    # Offline export/read needs the captured native leaf, not the last file row.
    assert archive_messages(archive.store(collector.key)) == [first['message']]


def test_jsonl_attachments_keep_bytes_without_acquiring_private_paths(tmp_path: Path) -> None:
    """Portable bytes survive source deletion; a path cannot widen host grants."""
    cwd = tmp_path / 'work'
    cwd.mkdir()
    attachment = cwd / 'image.bin'
    attachment.write_bytes(b'original image bytes')
    archive = SessionArchive(tmp_path / 'swarm', save_normalized_sessions=True, backfill_history=True)
    header = {'id': 'attachments', 'type': 'session', 'timestamp': 0, 'cwd': str(cwd)}
    native = message('a', None, 'user', 'image')
    native['message']['content'] = [{'type': 'file', 'path': str(attachment)}]
    collector = PiArchive(archive, header, agent='agent', project=str(tmp_path), entries=[native],
                          leaf_id='a', attachment_root=cwd)
    attachment.unlink()
    store = archive.store(collector.key)
    reference = store.page()['events'][0]['graphtraj']['attachments'][0]
    assert store.attachment(reference['sha256']) == b'original image bytes'
    assert archive_messages(store) == [native['message']]
    private = archive.root / 'private.bin'
    private.write_bytes(b'must not be acquired')
    (cwd / 'link').symlink_to(private)
    blocked = message('b', 'a', 'user', 'private')
    blocked['message']['content'] = [{'type': 'file', 'path': str(cwd / 'link')}]
    collector.sync([native, blocked], 'b')
    with pytest.raises(ValueError, match='missing attachments'):
        collector.messages()


def test_public_session_read_uses_pi_jsonl_with_existing_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The normal project query sees Pi JSONL and still refuses another owner."""
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.execution.runner_status import runtime_caller
    from graphtraj.interfaces.gateway import handle_request
    from graphtraj.interfaces.local_tool import bind
    from test_result_submission import result_project

    runner, _, _ = result_project(tmp_path)
    archive = SessionArchive(tmp_path / '.graphtraj/swarm', save_normalized_sessions=True, backfill_history=True)
    native = message('a', None, 'user', 'retained JSONL')
    PiArchive(archive, {'id': 'query', 'type': 'session', 'timestamp': 0},
              agent='test-agent', project=str(tmp_path), entries=[native], leaf_id='a')
    request = {'action': 'execute', 'feature': 'session_read', 'arguments': {'session_id': 'pi:query'}}
    monkeypatch.setattr('graphtraj.sessions.query.caller_runtime', lambda: None)
    result = bind(tmp_path, desktop_observer=True)(request)
    assert not result.failed, result.document
    assert result.document['events'][0]['data']['record'] == native
    with runtime_caller(runner, 'research@x2'), pytest.raises(RunnerError, match='own verified'):
        handle_request(request, cwd=tmp_path)


def test_identical_rpc_finals_link_in_native_message_sequence(tmp_path: Path) -> None:
    """Equal bodies and clocks need two distinct entry identities, not deduplication."""
    archive = SessionArchive(tmp_path, save_normalized_sessions=True, backfill_history=True)
    first = message('a', None, 'assistant', 'same')
    second = message('b', 'a', 'assistant', 'same')
    collector = PiArchive(archive, {'id': 'identical', 'type': 'session', 'timestamp': 0},
                          agent='agent', project=str(tmp_path), entries=[], leaf_id=None)
    collector.receive({'type': 'message_start', 'message': {**first['message'], 'content': []}})
    collector.receive({'type': 'message_end', 'message': first['message']})
    collector.sync([first, second], 'b')
    assert len(archive.store(collector.key).pending()) == 1
    collector.receive({'type': 'message_start', 'message': {**second['message'], 'content': []}})
    collector.receive({'type': 'message_end', 'message': second['message']})
    collector.sync([first, second], 'b', settled=True)
    assert collector.messages() == [first['message'], second['message']]
    store = archive.store(collector.key)
    assert not store.pending()
    assert len({tuple(item['final']) for item in store.observations()}) == 2
    assert [event['data']['record']['id'] for event in store.page()['events']
            if event['type'] == 'graphtraj/native'] == ['a', 'b']
    reopened = PiArchive(archive, {'id': 'identical', 'type': 'session', 'timestamp': 0},
                         agent='agent', project=str(tmp_path), entries=[first, second], leaf_id='b')
    assert reopened.messages() == collector.messages()


def test_extra_identical_native_message_remains_explicitly_ambiguous(tmp_path: Path) -> None:
    """A missing RPC message cannot authorize guessing which native entry it was."""
    archive = SessionArchive(tmp_path, save_normalized_sessions=True, backfill_history=True)
    native = [message('a', None, 'assistant', 'same'), message('b', 'a', 'assistant', 'same'),
              message('c', 'b', 'assistant', 'same')]
    collector = PiArchive(archive, {'id': 'missing-rpc', 'type': 'session', 'timestamp': 0},
                          agent='agent', project=str(tmp_path), entries=[], leaf_id=None)
    for entry in native[:2]:
        collector.receive({'type': 'message_start', 'message': {**entry['message'], 'content': []}})
        collector.receive({'type': 'message_end', 'message': entry['message']})
    collector.sync(native, 'c', settled=True)
    assert len(archive.store(collector.key).pending()) == 2
    assert sum(event['type'] == 'graphtraj/native'
               for event in archive.store(collector.key).page()['events']) == 3
    with pytest.raises(ValueError, match='unambiguous'):
        collector.messages()


def test_message_end_without_start_retains_rpc_fields_and_native_identity(tmp_path: Path) -> None:
    """Mid-turn collection retains the first seen final event without inventing its start."""
    archive = SessionArchive(tmp_path, save_normalized_sessions=True, backfill_history=True)
    collector = PiArchive(archive, {'id': 'late-attach', 'type': 'session', 'timestamp': 0},
                          agent='agent', project=str(tmp_path), entries=[], leaf_id=None)
    final = message('a', None, 'assistant', 'complete body')
    collector.receive({'type': 'message_end', 'message': final['message'],
                       'opaqueEnd': {'ciphertext': 'end-only'}})
    collector.sync([final], 'a', settled=True)
    assert collector.messages() == [final['message']]
    [observation] = archive.store(collector.key).observations()
    evidence = observation['event']['piObservation']
    assert evidence['missingStart'] is True
    assert 'messageStart' not in evidence
    assert evidence['endFields'] == {'opaqueEnd': {'ciphertext': 'end-only'}}
    assert not archive.store(collector.key).pending()


def test_abort_before_first_delta_links_native_empty_attempt(tmp_path: Path) -> None:
    """Zero generated text does not strand a known aborted native attempt."""
    archive = SessionArchive(tmp_path, save_normalized_sessions=True, backfill_history=True)
    collector = PiArchive(archive, {'id': 'empty-abort', 'type': 'session', 'timestamp': 0},
                          agent='agent', project=str(tmp_path), entries=[], leaf_id=None)
    final = message('a', None, 'assistant', '')
    final['message']['content'] = []
    final['message']['stopReason'] = 'aborted'
    collector.receive({'type': 'message_start', 'message': final['message']})
    collector.close()
    collector.sync([final], 'a', settled=True)
    assert collector.messages() == [final['message']]
    assert len(archive.store(collector.key).observations()) == 1
