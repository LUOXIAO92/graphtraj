"""Claude native transcript fixtures through the optional public JSONL archive."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess

import pytest

from graphtraj.runtimes.claude.history import conversation, message_id
from graphtraj.runtimes.claude.jsonl import ClaudeJsonlCollector
from graphtraj.sessions.archive import JsonlSessionStore, SessionArchive, archive_path


def message(uid: str, parent: str | None, text: str, *, role: str = 'user', **fields: object) -> dict:
    """Build a transcript entry, with intentionally backward native timestamps."""
    return {'type': role, 'uuid': uid, 'parentUuid': parent, 'sessionId': 's',
            'timestamp': '2026-01-01T00:00:00Z',
            'message': {'role': role, 'id': 'api-' + uid, 'model': 'native-model',
                        'content': [{'type': 'text', 'text': text}]}, **fields}


def write(path: Path, records: list[dict]) -> None:
    """Write a complete fixture transcript in the supplied native file order."""
    path.write_text(''.join(json.dumps(r) + '\n' for r in records))


def collector(tmp_path: Path, records: list[dict], *, backfill: bool = True):
    """Bind a single associated transcript with the chosen public archive policy."""
    path = tmp_path / 'native.jsonl'
    write(path, records)
    archive = SessionArchive(tmp_path / 'swarm', save_normalized_sessions=True,
                             backfill_history=backfill)
    result = ClaudeJsonlCollector(archive, 's', 'agent', tmp_path, 'execution')
    result.bind(path)
    return result, path, archive


def store(archive: SessionArchive) -> JsonlSessionStore:
    """Reopen JSONL so assertions include durable state, not collector memory."""
    return JsonlSessionStore(archive_path(archive.root, 'claude:s'))


def test_parent_links_not_notification_or_file_arrival_define_messages(tmp_path: Path) -> None:
    """Native results retain native chain order even with reversed file placement."""
    first = message('q', None, 'question')
    second = message('b', 'q', 'second result')
    third = message('a', 'b', 'first result')
    third['timestamp'] = '2025-01-01T00:00:00Z'
    final = message('answer', 'a', 'answer', role='assistant', completedAt='original', unknown={'keep': 7})
    c, path, archive = collector(tmp_path, [first, third, second, final])
    result = store(archive)
    assert [m['id'] for m in result.messages()] == ['q', 'b', 'a', 'answer']
    events = result.page()['events']
    assert events[2]['time'] < events[1]['time']
    assert events[3]['graphtraj']['native']['record'] == final
    before = deepcopy(events)
    c.collect()
    assert store(archive).page()['events'] == before
    assert path.exists()


def test_same_api_id_does_not_merge_distinct_sibling_blocks(tmp_path: Path) -> None:
    """The official loader restores sibling blocks excluded from the parent chain."""
    q = message('q', None, 'question')
    a = message('a', 'q', 'thinking', role='assistant')
    b = message('b', 'q', 'answer', role='assistant')
    a['message']['id'] = b['message']['id'] = 'shared-api-id'
    c, _, archive = collector(tmp_path, [q, a, b])
    assert [m['id'] for m in store(archive).messages()] == ['q', 'b', 'a']
    assert [m['content'][0]['text'] for m in store(archive).messages()] == ['question', 'answer', 'thinking']


def test_compaction_kept_uuid_order_and_context_replacement(tmp_path: Path) -> None:
    """Compaction's explicit retained order survives without rewriting old events."""
    original = [message('q', None, 'old'), message('a', 'q', 'one'), message('b', 'a', 'two')]
    c, path, archive = collector(tmp_path, original)
    before = store(archive).page()['events']
    boundary = {'type': 'system', 'subtype': 'compact_boundary', 'uuid': 'boundary',
                'parentUuid': None, 'sessionId': 's', 'logicalParentUuid': 'b',
                'compactMetadata': {'preservedMessages': {'anchorUuid': 'summary', 'uuids': ['b', 'a']}}}
    summary = message('summary', 'boundary', 'summary', isCompactSummary=True)
    end = message('end', 'summary', 'new question')
    write(path, [*original, boundary, summary, end])
    c.collect()
    result = store(archive)
    assert [m['id'] for m in result.messages()] == ['summary', 'b', 'a', 'end']
    assert result.page()['events'][:len(before)] == before
    c.collect()
    assert store(archive).messages() == result.messages()


def test_native_fork_provenance_is_not_agent_parentage(tmp_path: Path) -> None:
    """The source's explicit fork identity survives JSONL publication."""
    inherited = message('inherited', None, 'remember', forkedFrom={'sessionId': 'parent', 'messageUuid': 'old'})
    _, _, archive = collector(tmp_path, [inherited, message('local', 'inherited', 'new')])
    result = store(archive)
    assert result.header['parentSession'] == 'claude:parent'
    assert result.header['isSeeded']
    assert [m['id'] for m in result.messages()] == ['inherited', 'local']


def test_history_switch_only_collects_associated_session(tmp_path: Path) -> None:
    """Later opt-in backfill fills the prefix; unrelated files are never scanned."""
    old = message('old', None, 'old')
    c, path, archive = collector(tmp_path, [old], backfill=False)
    write(tmp_path / 'unrelated.jsonl', [{**old, 'sessionId': 'another'}])
    write(path, [old, message('new', 'old', 'new')])
    c.collect()
    assert [e['data']['id'] for e in store(archive).page()['events'] if e['type'] == 'user/message'] == ['new']
    with pytest.raises(ValueError, match='incomplete'):
        store(archive).messages()
    archive.backfill_history = True
    c.collect()
    assert [m['id'] for m in store(archive).messages()] == ['old', 'new']
    assert not any('another' in json.dumps(e) for e in store(archive).page()['events'])


def test_disabled_archive_creates_nothing_and_retains_old_content(tmp_path: Path) -> None:
    """Disabling policy stops collection without removing saved history."""
    c, path, archive = collector(tmp_path, [message('q', None, 'first')])
    destination = archive_path(archive.root, 'claude:s')
    before = destination.read_bytes()
    archive.save_normalized_sessions = False
    write(path, [message('q', None, 'first'), message('n', 'q', 'next')])
    c.collect()
    c.accept({'type': 'assistant', 'uuid': 'new'}, 1)
    assert destination.read_bytes() == before
    disabled = ClaudeJsonlCollector(None, 'disabled', 'agent', tmp_path, 'other')
    disabled.bind(tmp_path / 'missing')
    disabled.close()
    assert not archive_path(archive.root, 'claude:disabled').exists()


def test_live_final_transcript_resolve_once_by_native_identity(tmp_path: Path) -> None:
    """Compact per-block live fragments and map final UUIDs without text dedup."""
    c, path, archive = collector(tmp_path, [])
    records = [
        {'type': 'message_start', 'message': {'id': 'api', 'model': 'native-model'}},
        {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'hel'}},
        {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'lo'}},
        {'type': 'content_block_delta', 'index': 1, 'delta': {'type': 'text_delta', 'text': 'hello'}},
        {'type': 'message_stop'},
    ]
    for index, event in enumerate(records):
        c.accept({'type': 'stream_event', 'event': event}, index)
    final = message('uuid', None, 'hello', role='assistant')
    final['message']['id'] = 'api'
    final['message']['content'].append({'type': 'text', 'text': 'hello'})
    c.accept({**final, 'session_id': 's'}, len(records))
    with pytest.raises(ValueError, match='incomplete'):
        store(archive).messages()
    write(path, [final])
    c.close()
    result = store(archive)
    assert [m['id'] for m in result.messages()] == ['uuid']
    assert len(result.messages()[0]['content']) == 2
    stream, = [o for o in result.observations() if o['event']['type'] == 'assistant/attempt']
    chunks = [r for r in stream['event']['data']['stream'] if r['type'] == 'graphtraj/text-run']
    assert [(r['index'], r['text']) for r in chunks] == [(0, 'hello'), (1, 'hello')]
    c.collect()
    assert store(archive).messages() == result.messages()


def test_interrupted_output_and_missing_parent_are_explicit(tmp_path: Path) -> None:
    """An unresolved partial or missing chain link never becomes complete history."""
    c, path, archive = collector(tmp_path, [])
    c.accept({'type': 'stream_event', 'event': {'type': 'message_start', 'message': {'id': 'api'}}}, 0)
    c.accept({'type': 'stream_event', 'event': {'type': 'content_block_delta', 'index': 0,
              'delta': {'type': 'text_delta', 'text': 'partial'}}}, 1)
    write(path, [message('orphan', 'missing', 'incomplete')])
    c.close()
    result = store(archive)
    assert result.page()['events'] == []
    assert len(result.pending()) == 2
    with pytest.raises(ValueError, match='incomplete'):
        result.messages()
    with pytest.raises(ValueError, match='missing parent'):
        conversation([message('orphan', 'missing', 'incomplete')])


@pytest.mark.skipif(not os.environ.get('CLAUDE_SDK_MODULE'), reason='Explicit pinned official SDK comparison')
@pytest.mark.parametrize('case', ['chain', 'siblings', 'preserved-messages', 'preserved-segment', 'tools', 'replay',
                                'queued', 'queued-tail', 'queued-delivery'])
def test_order_matches_official_sdk_session_store(case: str) -> None:
    """Compare the official public SessionStore API, with no login or home scan."""
    records = [message('q', None, 'q'), message('a', 'q', 'a', role='assistant'),
               message('b', 'a', 'b', role='assistant')]
    if case == 'siblings':
        records[1]['message']['id'] = records[2]['message']['id'] = 'api'
        records[2]['parentUuid'] = 'q'
    if case == 'tools':
        records[1]['message']['id'] = records[2]['message']['id'] = 'api'
        records[1]['message']['content'] = [{'type': 'tool_use', 'id': 'one', 'name': 'Read', 'input': {}}]
        records[2]['message']['content'] = [{'type': 'tool_use', 'id': 'two', 'name': 'Read', 'input': {}}]
        records[2]['parentUuid'] = 'q'
        second = message('result-two', 'b', 'same')
        second['message']['content'] = [{'type': 'tool_result', 'tool_use_id': 'two', 'content': 'same'}]
        first = message('result-one', 'a', 'same')
        first['message']['content'] = [{'type': 'tool_result', 'tool_use_id': 'one', 'content': 'same'}]
        records.extend([second, first, message('end', 'result-two', 'done', role='assistant')])
    if case == 'replay':
        records.append(deepcopy(records[1]))
    if case.startswith('queued'):
        attachment = {'type': 'attachment', 'uuid': 'queued', 'parentUuid': 'a', 'sessionId': 's',
                      'attachment': {'type': 'queued_command', 'prompt': 'next', 'source_uuid': 'source'}}
        final = records.pop()
        records.append(attachment)
        if case == 'queued-delivery':
            attachment['attachment']['delivery_id'] = 'delivery'
            records.append({**deepcopy(attachment), 'uuid': 'queued-copy', 'parentUuid': 'queued'})
            records.append({'type': 'queue-operation', 'operation': 'remove',
                            'reason': 'absorbed_mid_turn', 'deliveryId': 'delivery'})
            final['parentUuid'] = 'queued-copy'
        else:
            final['parentUuid'] = 'queued'
        if case != 'queued-tail':
            records.append(final)
    if case.startswith('preserved'):
        kept = ({'preservedMessages': {'anchorUuid': 'summary', 'uuids': ['b', 'a']}}
                if case == 'preserved-messages' else
                {'preservedSegment': {'anchorUuid': 'summary', 'headUuid': 'a', 'tailUuid': 'b'}})
        records.extend([{'type': 'system', 'subtype': 'compact_boundary', 'uuid': 'boundary',
                         'parentUuid': None, 'sessionId': 's', 'compactMetadata': kept},
                        message('summary', 'boundary', 'summary', isCompactSummary=True),
                        message('end', 'summary', 'next')])
    program = """
        import {readFileSync} from 'node:fs';
        const {getSessionMessages} = await import(process.argv[1]);
        const entries = JSON.parse(readFileSync(0, 'utf8'));
        const sessionStore = {load: async () => entries, append: async () => {}};
        const messages = await getSessionMessages('00000000-0000-4000-8000-000000000332',
            {dir: '/task332-controlled-source', sessionStore});
        process.stdout.write(JSON.stringify(messages));
    """
    response = subprocess.run(['node', '--input-type=module', '-e', program, os.environ['CLAUDE_SDK_MODULE']],
                              input=json.dumps(records), capture_output=True, text=True, check=True, timeout=20)
    native = json.loads(response.stdout)
    assert native
    actual = [(message_id(r), {'role': 'user', 'content': r['attachment']['prompt']}
               if r['type'] == 'attachment' else r['message']) for r in conversation(records)]
    assert actual == [(r['uuid'], r['message']) for r in native]
