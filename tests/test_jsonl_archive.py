"""Controlled native-history fixtures exercise the public archive contract.

These are not real Runtime acceptance. The fixture's native messages, rather
than notification order or normalized output, supply the expected sequence.
"""
from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest

from agent_swarm.sessions.archive import (
    ArchiveStream, JsonlSessionStore, SessionArchive, archive_path,
)
from agent_swarm.sessions.protocol import append_stream_record, native_record


# Native history deliberately differs from tool-call and completion notice order.
NATIVE = [
    {'id': 'question', 'role': 'user', 'text': 'run both', 'created': 100},
    {'id': 'calls', 'role': 'assistant', 'text': '', 'created': 105,
     'calls': [{'id': 'a', 'name': 'first', 'arguments': '{}'},
               {'id': 'b', 'name': 'second', 'arguments': '{}'}]},
    {'id': 'result-b', 'role': 'tool', 'text': 'same', 'callId': 'b', 'created': None},
    {'id': 'result-a', 'role': 'tool', 'text': 'same', 'callId': 'a', 'created': 99},
    {'id': 'answer', 'role': 'assistant', 'text': 'done', 'created': 99,
     'ciphertext': 'opaque==', 'unknown': [None, {'x': 7}]},
]
NOTIFICATIONS = [('result-a', 300), ('answer', 300), ('result-b', None), ('calls', 20)]


def header(*, seeded: bool = False) -> dict:
    """Return a plain DSH header without requiring GraphTraj Task metadata."""
    value = {'version': 4, 'id': 'canonical', 'createdAt': 100, 'isSeeded': seeded}
    if seeded:
        value['parentSession'] = 'parent'
    return value


def mapped(records: list[dict]) -> list[dict]:
    """Map the fixture's native history as provided, without sorting any field."""
    events = []
    for seq, record in enumerate(records):
        role = record['role']
        source = {'kind': 'user'}
        if role == 'assistant':
            source = {'kind': 'model', 'model': 'fixture', 'provider': 'fixture'}
        elif role == 'tool':
            source = {'kind': 'tool', 'callId': record['callId']}
        message = {'id': record['id'], 'role': role, 'source': source,
                   'content': [{'type': 'text', 'text': record['text']}]}
        if role == 'assistant':
            message['content'] += [{'type': 'tool-call', **call} for call in record.get('calls', [])]
        if role == 'tool':
            message['toolCallId'] = record['callId']
        if 'ciphertext' in record:
            message['content'].append({'type': 'graphtraj/encrypted',
                                       'nativePath': 'ciphertext', 'value': record['ciphertext']})
        data = message if role == 'user' else {'turn': 0, 'step': 0, 'message': message}
        if role == 'assistant':
            data['stream'] = []
        event = {'type': 'tool/result' if role == 'tool' else role + '/message',
                 'seq': seq, 'time': record['created'] if record['created'] is not None else 0,
                 'surfaceOp': 'append', 'data': data,
                 'graphtraj': {'version': 1, 'native': {
                     'runtime': 'fixture', 'sessionId': 'native', 'locator': record['id'],
                     'record': deepcopy(record)}}}
        if record['created'] is None:
            event['graphtraj']['missing'] = [{'path': 'time', 'reason': 'Native creation time unavailable'}]
        events.append(event)
    return events


def run(text: str, *, message: str = 'answer', index: int = 0, **extra: object) -> dict:
    """Supply a semantic fragment whose identity includes message and block."""
    return {'type': 'graphtraj/text-run', 'requestId': 'request', 'attemptId': 'attempt',
            'messageId': message, 'index': index, 'blockType': 'text', 'text': text, **extra}


def test_native_history_not_notifications_defines_order_and_pagination(tmp_path: Path) -> None:
    """Reverse completion, equal/backward/absent times never determine log order."""
    path = archive_path(tmp_path, 'canonical')
    store = JsonlSessionStore.create(path, header())
    events = mapped(NATIVE)
    for position, (identity, notification_time) in enumerate(NOTIFICATIONS):
        event = deepcopy(next(event for event in events if event['graphtraj']['native']['locator'] == identity))
        event['graphtraj']['notificationTime'] = notification_time
        store.checkpoint(event, source='notices', position=position)
    assert store.page()['events'] == []
    assert len(store.pending()) == 4
    with pytest.raises(ValueError, match='incomplete'):
        store.messages()
    assert store.publish(events, source='native-history', position=0)
    store = JsonlSessionStore(path)
    assert store.pending() == []
    collected = []
    after = -1
    while True:
        page = store.page(after, 2)
        collected.extend(page['events'])
        after = page['after']
        if not page['has_more']:
            break
    assert [native_record(event) for event in collected] == NATIVE
    assert collected == events
    assert [item['event']['graphtraj']['notificationTime'] for item in store.observations()] == [300, 300, None, 20]
    messages = store.messages()
    assert [(m['id'], m['role'], m['content'][0]['text']) for m in messages] == [
        (record['id'], record['role'], record['text']) for record in NATIVE]
    assert [m['toolCallId'] for m in messages if m['role'] == 'tool'] == ['b', 'a']
    assert collected[2]['time'] == 0 and collected[2]['graphtraj']['missing']
    assert collected[4]['data']['message']['content'][1]['value'] == 'opaque=='
    assert not store.publish(events, source='native-history', position=0)
    assert store.publish(events, source='backfill', position=0)
    assert len(store.messages()) == len(NATIVE)
    # JSONL is the body authority, readable without a database or source home.
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert lines[0]['header'] == header()
    assert [event['seq'] for event in lines[1:]] == list(range(len(NATIVE)))


def test_reject_reordering_dropped_identity_and_changed_final(tmp_path: Path) -> None:
    """A new snapshot cannot silently rewrite established native history."""
    store = JsonlSessionStore.create(tmp_path / 'session.jsonl', header())
    store.publish(mapped(NATIVE), source='history', position=0)
    for records in (NATIVE[::-1], NATIVE[:-1], [{**NATIVE[0], 'text': 'changed'}, *NATIVE[1:]]):
        with pytest.raises(ValueError):
            store.publish(mapped(records), source='history', position=1)
        assert store.position('history') == 0
        assert [m['id'] for m in store.messages()] == [r['id'] for r in NATIVE]
    duplicate = mapped([NATIVE[0], NATIVE[0]])
    with pytest.raises(ValueError, match='Duplicate'):
        store.publish(duplicate, source='history', position=1)


def test_optional_policy_and_late_backfill_preserve_existing_records(tmp_path: Path) -> None:
    """Disabled collection creates nothing; explicit mapped backfill adds prefix."""
    root = tmp_path / 'independent'
    archive = SessionArchive(root)
    archive.map_session(header())
    assert archive.store('canonical') is None
    assert not archive.collect('canonical', mapped(NATIVE), source='history', position=0)
    assert not archive.checkpoint('canonical', mapped(NATIVE)[0], source='notices', position=0)
    assert not root.exists()
    with pytest.raises(ValueError, match='mapped'):
        archive.store('unrelated-global-session')
    archive.save_normalized_sessions = True
    assert archive.store('canonical', historical=True) is None
    store = archive.store('canonical')
    assert archive.collect('canonical', mapped(NATIVE[2:]), source='live-history', position=10)
    store = JsonlSessionStore(store.path)
    first = store.page(limit=1)
    archive.backfill_history = True
    store = archive.store('canonical', historical=True)
    assert archive.collect('canonical', mapped(NATIVE), source='backfill', position=0, historical=True)
    store = JsonlSessionStore(store.path)
    with pytest.raises(ValueError, match='restart pagination'):
        store.page(first['after'], revision=first['revision'])
    assert [m['id'] for m in store.messages()] == [r['id'] for r in NATIVE]
    before = store.path.read_bytes()
    archive.save_normalized_sessions = False
    assert archive.store('canonical') is None
    assert not archive.collect('canonical', mapped(NATIVE), source='later', position=0)
    assert not archive.checkpoint('canonical', mapped(NATIVE)[-1], source='later', position=0)
    assert store.path.read_bytes() == before
    assert JsonlSessionStore(store.path).messages() == store.messages()


def test_stream_restart_final_backfill_and_late_notification(tmp_path: Path) -> None:
    """Interrupted partial output survives restart; final/backfill expose it once."""
    path = tmp_path / 'session.jsonl'
    store = JsonlSessionStore.create(path, header())
    template = mapped([NATIVE[-1]])[0]
    template['data']['message']['content'] = []
    writer = ArchiveStream(store, 'answer-stream', template)
    writer.feed(run('d'), 0)
    writer.feed(run('do'), 1, cumulative=True)
    writer.checkpoint()
    writer.feed(run('lost until replay'), 2)
    resumed = JsonlSessionStore(path)
    writer = ArchiveStream(resumed, 'answer-stream', template)
    assert not writer.feed(run('do'), 1, cumulative=True)
    writer.feed(run('done'), 2, cumulative=True)
    writer.checkpoint()
    assert resumed.pending()[0]['event']['data']['stream'] == [run('done')]
    assert resumed.page()['events'] == []
    resumed.publish(mapped(NATIVE), source='history', position=0)
    assert resumed.pending() == []
    final = resumed.page()['events'][-1]
    assert final['data']['message']['content'][0]['text'] == 'done'
    assert resumed.observations()[0]['event']['data']['stream'] == [run('done')]
    assert resumed.observations()[0]['final'] == ['fixture', 'native', 'answer']
    assert not resumed.checkpoint(template, source='answer-stream', position=3)
    assert resumed.pending() == []
    resumed.publish(mapped(NATIVE), source='backfill', position=0)
    assert len(resumed.messages()) == 5


def test_stream_semantic_boundaries_and_stale_writer(tmp_path: Path) -> None:
    """Only adjacent same-message/block fragments merge, including cumulative input."""
    stream = []
    for record in [run('a'), run('b'), run('c', index=1), run('d'),
                   {'type': 'native-boundary', 'opaque': 7}, run('e'), run('f', time=123)]:
        append_stream_record(stream, record)
    assert stream == [run('ab'), run('c', index=1), run('d'),
                      {'type': 'native-boundary', 'opaque': 7}, run('e'), run('f', time=123)]
    append_stream_record(stream, run('abdefg'), cumulative=True)
    assert stream[-1] == run('g')
    with pytest.raises(ValueError, match='prefix|changed'):
        append_stream_record(stream, run('replacement'), cumulative=True)
    store = JsonlSessionStore.create(tmp_path / 'session.jsonl', header())
    template = mapped([NATIVE[-1]])[0]
    one = ArchiveStream(store, 'stream', template)
    two = ArchiveStream(JsonlSessionStore(store.path), 'stream', template)
    one.feed(run('a'), 0)
    one.checkpoint()
    one.feed(run('b'), 1)
    one.checkpoint()
    two.feed(run('overwrite'), 2)
    with pytest.raises(ValueError, match='Source changed'):
        two.checkpoint()
    with pytest.raises(ValueError, match='another message'):
        one.feed(run('wrong', message='other'), 2)
    assert JsonlSessionStore(store.path).pending()[0]['event']['data']['stream'] == [run('ab')]


def test_attachments_portable_and_unknown_required_event_refuses_projection(tmp_path: Path) -> None:
    """Attachment bytes and unknown event fields survive copying the archive."""
    directory = tmp_path / 'original'
    store = JsonlSessionStore.create(directory / 'session.jsonl', header())
    ref = store.put_attachment(b'\x00\xffimage')
    events = mapped(NATIVE)
    events[0]['data']['content'].append({'type': 'file', 'attachment': ref})
    events.append({'type': 'future/native', 'seq': 5, 'time': -1,
                   'data': {'ciphertext': 'unknown==', 'opaque': [1, None]},
                   'graphtraj': {'version': 1, 'native': {
                       'runtime': 'fixture', 'sessionId': 'native', 'locator': 'future'}}})
    store.publish(events, source='history', position=0)
    shutil.copytree(directory, tmp_path / 'copied')
    shutil.rmtree(directory)
    copied = JsonlSessionStore(tmp_path / 'copied' / 'session.jsonl')
    assert copied.attachment(ref['sha256']) == b'\x00\xffimage'
    assert copied.page()['events'] == events
    with pytest.raises(ValueError, match='unknown-required'):
        copied.messages()
    with pytest.raises(ValueError, match='digest'):
        copied.attachment('../outside')


def test_native_fork_chain_compaction_and_original_times(tmp_path: Path) -> None:
    """An explicit native branch inherits its prefix and replaces only its cut."""
    # Controlled native chain and projection; the other branch is not selected.
    native_chain = [
        {'id': 'root', 'parentId': None, 'role': 'user', 'text': 'old', 'created': 10},
        {'id': 'selected', 'parentId': 'root', 'role': 'user', 'text': 'keep', 'created': 9},
        {'id': 'summary', 'parentId': 'selected', 'role': 'user', 'text': 'summary', 'created': 12},
    ]
    native_messages = [native_chain[-1]]
    events = mapped(native_chain[:2])
    for event in events:
        event['graphtraj']['native']['sessionId'] = 'parent-native'
    events.append({'type': 'session/end-seed', 'seq': 2, 'time': 0,
                   'data': {'inherited': True}, 'graphtraj': {'version': 1,
                   'native': {'runtime': 'fixture', 'sessionId': 'child-native',
                              'locator': 'inherited-boundary'},
                   'missing': [{'path': 'time', 'reason': 'Protocol marker, not a native event time'}]}})
    events.append({'type': 'compaction/summary', 'seq': 3, 'time': 12,
                   'data': {'compactionId': 'compact', 'summary': [{'type': 'text', 'text': 'summary'}],
                            'shadowedRange': {'start': 0, 'end': 1}, 'shadowedSeqs': [0, 1],
                            'shadowedTokenCount': 2, 'provider': 'fixture', 'model': 'fixture'},
                   'graphtraj': {'version': 1, 'native': {
                       'runtime': 'fixture', 'sessionId': 'child-native', 'locator': 'compact'}}})
    summary = mapped([native_chain[-1]])[0]
    summary.update(seq=4, sourceEventSeqs=[0, 1],
                   surfaceOp={'op': 'replace', 'startSeq': 0, 'endSeq': 1})
    events.append(summary)
    store = JsonlSessionStore.create(tmp_path / 'child.jsonl', header(seeded=True))
    store.publish(events, source='branch-chain', position=0)
    assert [(m['id'], m['content'][0]['text']) for m in store.messages()] == [
        (m['id'], m['text']) for m in native_messages]
    retained = store.page()['events']
    assert [native_record(retained[i]) for i in (0, 1, 4)] == native_chain
    assert [event['time'] for event in retained] == [10, 9, 0, 12, 12]
    assert retained[3]['data']['shadowedSeqs'] == [0, 1]
    assert store.header['parentSession'] == 'parent'
    assert retained[2]['type'] == 'session/end-seed'


def test_score_probability_alignment_survives_jsonl_and_history_prefix(tmp_path: Path) -> None:
    """Accepted RL extensions remain aligned when missing native history is added."""
    from test_session_protocol import observation

    metadata = header()
    metadata['graphtraj'] = {'version': 1, 'projectId': 'fixture',
                            'agentId': 'fixture', 'taskIds': []}
    current = mapped([{'id': 'probability-target', 'role': 'user', 'text': 'é', 'created': 10}])
    for seq, kind in enumerate(('graphtraj/logprobs', 'graphtraj/score'), 1):
        event = observation(kind)
        event['seq'] = seq
        event['graphtraj'] = {'version': 1, 'native': {
            'runtime': 'fixture', 'sessionId': 'native', 'locator': kind}}
        current.append(event)
    store = JsonlSessionStore.create(tmp_path / 'session.jsonl', metadata)
    store.publish(current, source='live', position=0)
    prefixed = mapped([NATIVE[0]]) + deepcopy(current)
    for event in prefixed[1:]:
        event['seq'] += 1
        if event['type'].startswith('graphtraj/'):
            event['data']['target']['eventSeq'] = 1
    store.publish(prefixed, source='backfill', position=0)
    retained = JsonlSessionStore(store.path).page()['events']
    assert retained == prefixed
    assert retained[2]['data']['tokens'][0]['span'] == {'blockIndex': 0, 'start': 0, 'end': 2}
    assert retained[2]['data']['tokens'][1]['missing'] == 'Provider withheld probability'
    assert retained[3]['data']['target']['eventSeq'] == 1


def test_process_exit_keeps_partial_output_and_requires_resolution(tmp_path: Path) -> None:
    """A killed process needs no destructor/final response to preserve its checkpoint."""
    import os
    import subprocess
    import sys

    path = tmp_path / 'session.jsonl'
    template = mapped([NATIVE[-1]])[0]
    template['data']['message']['content'] = []
    source = '''
import json, os, sys
from pathlib import Path
from agent_swarm.sessions.archive import JsonlSessionStore, ArchiveStream
path, header, event, run = sys.argv[1:]
store = JsonlSessionStore.create(Path(path), json.loads(header))
writer = ArchiveStream(store, 'stream', json.loads(event))
writer.feed(json.loads(run), 0)
writer.checkpoint()
os._exit(17)
'''
    environment = {**os.environ, 'PYTHONPATH': str(Path(__file__).parents[1] / 'src')}
    result = subprocess.run([sys.executable, '-c', source, str(path), json.dumps(header()),
                             json.dumps(template), json.dumps(run('partial'))], env=environment)
    assert result.returncode == 17
    store = JsonlSessionStore(path)
    assert store.position('stream') == 0
    assert store.pending()[0]['event']['data']['stream'] == [run('partial')]
    assert store.page()['pending']
    with pytest.raises(ValueError, match='incomplete'):
        store.messages()
    final = deepcopy(template)
    final['data']['interrupted'] = True
    final['data']['message']['content'] = [{'type': 'text', 'text': 'partial'}]
    store.publish([final], source='native-history', position=0)
    assert store.messages()[0]['content'][0]['text'] == 'partial'
    assert store.page()['events'][0]['data']['interrupted']


def test_same_source_finalization_at_last_checkpoint_and_parallel_pending(tmp_path: Path) -> None:
    """Finishing need not invent a source offset after the last durable fragment."""
    store = JsonlSessionStore.create(tmp_path / 'session.jsonl', header())
    first, second = mapped([NATIVE[1], NATIVE[-1]])
    one = ArchiveStream(store, 'calls-stream', first)
    two = ArchiveStream(store, 'answer-stream', second)
    one.feed(run('first', message='calls'), 0)
    one.checkpoint()
    two.feed(run('answer'), 0)
    two.checkpoint()
    assert len(store.pending()) == 2
    assert store.publish([first, second], source='answer-stream', position=0)
    assert store.pending() == []
    assert len(store.messages()) == 2
    assert not store.publish([first, second], source='answer-stream', position=0)
    assert len(store.observations()) == 2


@pytest.mark.parametrize('missing_path', [
    'data.content', '/data/content', 'history', 'history_base', 'inheritedPrefix',
    'messageOrder', 'data.message.id', 'data.message.toolCallId', 'unknownNativeGap',
])
def test_messages_refuse_declared_content_history_or_identity_gaps(
    tmp_path: Path, missing_path: str,
) -> None:
    """Readable archives cannot turn declared gaps into apparently complete messages."""
    events = mapped([NATIVE[0]])
    if missing_path in {'data.content', '/data/content'}:
        events[0]['data']['content'] = []
    events[0]['graphtraj']['missing'] = [
        {'path': missing_path, 'reason': 'Native message body or history unavailable'}]
    store = JsonlSessionStore.create(tmp_path / 'session.jsonl', header())
    assert store.publish(events, source='native', position=0)
    reopened = JsonlSessionStore(store.path)
    assert reopened.page()['events'] == events
    with pytest.raises(ValueError, match='incomplete'):
        reopened.messages()


@pytest.mark.parametrize('missing_path', ['parentSession', 'history', '/inheritedPrefix'])
def test_messages_refuse_header_history_gaps(tmp_path: Path, missing_path: str) -> None:
    """An unavailable inherited prefix cannot become an apparently complete root."""
    metadata = header()
    metadata['graphtraj'] = {'version': 1, 'projectId': 'fixture', 'agentId': 'fixture',
                            'taskIds': [], 'missing': [
                                {'path': missing_path, 'reason': 'Native prefix unavailable'}]}
    store = JsonlSessionStore.create(tmp_path / 'session.jsonl', metadata)
    events = mapped([NATIVE[0]])
    store.publish(events, source='native', position=0)
    assert store.header == metadata
    assert store.page()['events'] == events
    with pytest.raises(ValueError, match='incomplete'):
        store.messages()


def test_missing_optional_metadata_does_not_block_complete_messages(tmp_path: Path) -> None:
    """Creation times and probability/usage details do not alter native messages."""
    metadata = header()
    metadata['graphtraj'] = {'version': 1, 'projectId': 'fixture', 'agentId': 'fixture',
                            'taskIds': [], 'missing': [
                                {'path': 'createdAt', 'reason': 'Native creation time unavailable'}]}
    events = mapped(NATIVE)
    events[0]['graphtraj']['missing'] = [
        {'path': path, 'reason': 'Optional native metadata unavailable'}
        for path in ('time', '/data/message/createdAt', 'logprobs',
                     'data.usage', 'probabilitySemantics', '/data/stream')]
    store = JsonlSessionStore.create(tmp_path / 'session.jsonl', metadata)
    store.publish(events, source='native', position=0)
    assert [(message['id'], message['content'][0]['text']) for message in store.messages()] == [
        (record['id'], record['text']) for record in NATIVE]
    assert store.header == metadata
    assert store.page()['events'] == events
