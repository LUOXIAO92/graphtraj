"""Claude native transcript fixtures through the optional public JSONL archive."""
import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess

import pytest

from agent_swarm.sessions.claude_history import conversation, message_id
from agent_swarm.sessions.claude import ClaudeJsonlCollector
from agent_swarm.sessions.archive import JsonlSessionStore, SessionArchive, archive_path


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
    result = ClaudeJsonlCollector(archive, 's', tmp_path, 'execution')
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
    assert events[3]['native']['record'] == final
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
    assert result.page()['events'][1]['type'] == 'session/end-seed'


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
    disabled = ClaudeJsonlCollector(None, 'disabled', tmp_path, 'other')
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
    chunks = [r for r in stream['event']['data']['stream'] if r['type'] == 'text-run']
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


def test_incomplete_native_tail_is_retained_until_native_replay_completes(tmp_path: Path) -> None:
    """A torn native write remains a gap; its completed value resolves it once."""
    q, answer = message('q', None, 'question'), message('a', 'q', 'answer', role='assistant')
    c, path, archive = collector(tmp_path, [q])
    tail = json.dumps(answer)
    path.write_text(json.dumps(q) + '\n' + tail[:30])
    c.collect()
    pending = store(archive).pending()
    assert pending[0]['event']['native']['record']['unparsedTranscriptTail'] == tail[:30]
    with pytest.raises(ValueError, match='incomplete'):
        store(archive).messages()
    path.write_text(json.dumps(q) + '\n' + tail)
    c.collect()
    assert [m['id'] for m in store(archive).messages()] == ['q', 'a']


def test_jsonl_retains_native_ciphertext_attachments_and_completion(tmp_path: Path) -> None:
    """Opaque blocks and native fields survive without being presented as plaintext."""
    q = message('q', None, '')
    q['message']['content'] = [{'type': 'image', 'source': {'type': 'base64', 'data': 'AP8='}}]
    a = message('a', 'q', '', role='assistant', completedAt='native-completion', future={'x': [None]})
    a['message']['content'] = [{'type': 'thinking', 'thinking': 'visible', 'signature': 'signature'},
                               {'type': 'redacted_thinking', 'data': 'opaque=='},
                               {'type': 'future-block', 'payload': ['original']}]
    _, _, archive = collector(tmp_path, [q, a])
    result = store(archive)
    first, second = result.messages()
    assert result.attachment(first['content'][0]['attachment']['sha256']) == b'\0\xff'
    assert second['content'][0]['signature'] == 'signature'
    assert second['content'][1]['value'] == 'opaque=='
    assert second['content'][2] == a['message']['content'][2]
    assert result.page()['events'][1]['native']['record'] == a


def test_unknown_live_fields_and_tool_input_blocks_are_retained(tmp_path: Path) -> None:
    """Only known homogeneous fragments compact; semantic/unknown boundaries remain."""
    c, _, archive = collector(tmp_path, [])
    c.accept({'type': 'stream_event', 'event': {'type': 'message_start', 'message': {'id': 'api'}}}, 0)
    for position, partial in enumerate(['{"x":', '1}'], 1):
        c.accept({'type': 'stream_event', 'event': {'type': 'content_block_delta', 'index': 0,
                  'delta': {'type': 'input_json_delta', 'partial_json': partial}}}, position)
    unknown = {'type': 'stream_event', 'future': 'keep', 'event': {'type': 'content_block_delta', 'index': 1,
               'delta': {'type': 'text_delta', 'text': 'text'}}}
    c.accept(unknown, 3)
    draft = store(archive).pending()[0]['event']
    assert draft['data']['stream'][1]['partialJson'] == '{"x":1}'
    assert draft['data']['stream'][2]['record'] == unknown


def test_prebind_input_and_resume_cut_use_native_input_uuid(tmp_path: Path) -> None:
    """The current prompt is not mistaken for history if written before its hook."""
    old, current = message('old', None, 'old'), message('current', 'old', 'current')
    path = tmp_path / 'native.jsonl'
    write(path, [old, current])
    archive = SessionArchive(tmp_path / 'swarm', save_normalized_sessions=True, backfill_history=False)
    c = ClaudeJsonlCollector(archive, 's', tmp_path, 'execution', resumed=True)
    sent = {'type': 'user', 'uuid': 'current', 'session_id': 's', 'graphtraj_direction': 'sent',
            'message': current['message']}
    c.accept(sent, 0)
    c.bind(path, {'current'})
    result = store(archive)
    assert [e['data']['id'] for e in result.page()['events'] if e['type'] == 'user/message'] == ['current']
    assert any(o['event']['native']['record'] == sent for o in result.observations())
    assert any(p['event']['native']['locator'] == 'history-gap' for p in result.pending())


def test_history_size_is_measured_only_when_a_cut_is_needed(tmp_path: Path) -> None:
    """The run loop gets a file size, or nothing when no history cut applies."""
    from agent_swarm.sessions.claude_history import NO_HISTORY_SIZE

    path = tmp_path / 'native.jsonl'
    path.write_bytes(b'not parsed here')

    def size(*, save: bool = True, backfill: bool = False, resumed: bool | None = True,
             count: int | None = None) -> int | None:
        """Measure under one policy."""
        archive = SessionArchive(tmp_path / 'swarm', save_normalized_sessions=save, backfill_history=backfill)
        return ClaudeJsonlCollector(archive, 's', tmp_path, 'e', resumed=resumed,
                                    history_count=count).history_size(path)

    assert size() == len(b'not parsed here')
    assert size(resumed=None) == len(b'not parsed here')
    assert size(save=False) is None
    assert size(backfill=True) is None
    assert size(resumed=False) is None
    assert size(count=3) is None
    assert ClaudeJsonlCollector(None, 's', tmp_path, 'e', resumed=True).history_size(path) is None

    path.unlink()
    assert size() == NO_HISTORY_SIZE
    assert size(resumed=False) is None


def cut_collector(tmp_path: Path) -> tuple[ClaudeJsonlCollector, Path, SessionArchive]:
    """Build a resumed collector under saving on and history backfill off."""
    archive = SessionArchive(tmp_path / 'swarm', save_normalized_sessions=True, backfill_history=False)
    return ClaudeJsonlCollector(archive, 's', tmp_path, 'e', resumed=True), tmp_path / 'native.jsonl', archive


def test_bind_at_a_size_keeps_later_records_out_of_history(tmp_path: Path) -> None:
    """Records after the measured size are new, whenever the bind reads them."""
    c, path, archive = cut_collector(tmp_path)
    old, off_chain = message('old', None, 'old'), {'type': 'note', 'uuid': 'off-before', 'sessionId': 's'}
    write(path, [old, off_chain])
    size = path.stat().st_size

    later = {'type': 'note', 'uuid': 'off-after', 'sessionId': 's'}
    reply = message('reply', 'old', 'reply', role='assistant')
    with path.open('a') as stream:
        stream.write(json.dumps(later) + '\n' + json.dumps(reply) + '\n')
    c.bind(path, set(), size)

    assert c.history_count == 2 and c.cut_known
    assert c.excluded == {'old', 'off-before'}
    result = store(archive)
    assert [e['data']['message']['id'] for e in result.page()['events'] if e['type'] == 'assistant/message'] == ['reply']
    observed = [e['native']['record'].get('uuid') for e in result.page()['events'] if e['type'] == 'claude/observation']
    assert observed == ['off-after']


def test_bind_at_a_size_sees_a_current_input_on_either_side(tmp_path: Path) -> None:
    """The current input is never history, wherever the hook's size fell."""
    for inside in (True, False):
        root = tmp_path / str(inside)
        root.mkdir()
        c, path, _ = cut_collector(root)
        old, current = message('old', None, 'old'), message('current', 'old', 'current')
        write(path, [old, current] if inside else [old])
        size = path.stat().st_size
        write(path, [old, current])
        c.bind(path, {'current'}, size)
        assert c.history_count == (2 if inside else 1)
        assert c.excluded == {'old'} and c.live_ids == {'current'}


def test_bind_at_a_size_ignores_a_write_still_arriving_after_it(tmp_path: Path) -> None:
    """A torn value past the size is in flight; it does not make the cut unknown."""
    c, path, _ = cut_collector(tmp_path)
    old = message('old', None, 'old')
    write(path, [old])
    size = path.stat().st_size
    with path.open('a') as stream:
        stream.write(json.dumps(message('current', 'old', 'current')) + '\n' + '{"type": "assis')
    c.bind(path, {'current'}, size)
    assert c.cut_known and c.history_count == 1
    assert c.excluded == {'old'} and c.live_ids == {'current'}


def test_bind_at_a_size_treats_a_torn_prefix_as_unreadable(tmp_path: Path) -> None:
    """A size inside a value means the hook saw a torn tail, as an unreadable file."""
    c, path, _ = cut_collector(tmp_path)
    write(path, [message('old', None, 'old')])
    size = path.stat().st_size - 5
    c.bind(path, set(), size)
    assert not c.cut_known
    assert c.history_count == 0 and c.excluded == set()


def test_bind_with_no_size_measured_keeps_the_cut_unknown(tmp_path: Path) -> None:
    """A transcript the hook could not measure stays unknown, even if it now exists."""
    from agent_swarm.sessions.claude_history import NO_HISTORY_SIZE

    c, path, _ = cut_collector(tmp_path)
    write(path, [message('current', None, 'current'), message('reply', 'current', 'reply', role='assistant')])
    c.bind(path, {'current'}, NO_HISTORY_SIZE)
    assert not c.cut_known
    assert c.history_count == 0 and c.excluded == set()
    assert c.live_ids == {'current'}


def test_bind_without_a_size_still_reads_history_at_the_bind(tmp_path: Path) -> None:
    """Callers with no hook-time fact keep today's meaning: the whole file is history."""
    c, path, _ = cut_collector(tmp_path)
    write(path, [message('old', None, 'old'), message('older', 'old', 'older')])
    c.bind(path)
    assert c.cut_known and c.history_count == 2
    assert c.excluded == {'old', 'older'}

    missing = ClaudeJsonlCollector(c.archive, 'other', tmp_path, 'e', resumed=True)
    missing.bind(tmp_path / 'absent.jsonl')
    assert not missing.cut_known


def first_start(tmp_path: Path, records: list[dict]) -> tuple[ClaudeJsonlCollector, Path, SessionArchive]:
    """Archive a whole transcript from its first start, with history backfill off."""
    path = tmp_path / 'native.jsonl'
    write(path, records)
    archive = SessionArchive(tmp_path / 'swarm', save_normalized_sessions=True, backfill_history=False)
    c = ClaudeJsonlCollector(archive, 's', tmp_path, 'first', resumed=False)
    c.bind(path, set())
    assert store(archive).pending() == []
    return c, path, archive


def resume(path: Path, archive: SessionArchive) -> ClaudeJsonlCollector:
    """Bind a later activation, with everything now in the transcript as its history."""
    c = ClaudeJsonlCollector(archive, 's', path.parent, 'later', resumed=True)
    c.bind(path, set(), path.stat().st_size)
    return c


def resume_with_full_archive(tmp_path: Path, records: list[dict]) -> tuple[ClaudeJsonlCollector, Path, SessionArchive]:
    """Resume a Session whose whole history is already in its archive."""
    first, path, archive = first_start(tmp_path, records)
    first.close()
    return resume(path, archive), path, archive


def append_torn(path: Path, record: dict) -> str:
    """Append the start of a record, as a reader sees a write still in progress."""
    tail = json.dumps(record)[:30]
    with path.open('a') as stream:
        stream.write(tail)
    return tail


def pending_locators(archive: SessionArchive) -> list[str]:
    """Name the observations that keep messages() refusing."""
    return [item['event']['native']['locator'] for item in store(archive).pending()]


def retain_history_gap(archive: SessionArchive, record: dict, reason: str) -> None:
    """Leave the draft an earlier version checkpointed under ``history-gap``."""
    store(archive).checkpoint(
        {'type': 'claude/observation', 'seq': 0, 'time': 0, 'data': {}, 'ignorable': True,
         'native': {'runtime': 'claude', 'sessionId': 's', 'locator': 'history-gap', 'record': record},
         'missing': [{'path': 'history', 'reason': reason}]},
        source='history-gap', position=0)


BACKFILL_DISABLED = 'History backfill is disabled; native prefix was not collected.'


def test_resume_with_a_full_archive_collects_a_torn_line_once_it_completes(tmp_path: Path) -> None:
    """A read that met a write in progress stops mattering when the write ends."""
    q, a, n = message('q', None, 'q'), message('a', 'q', 'a', role='assistant'), message('n', 'a', 'n')
    c, path, archive = resume_with_full_archive(tmp_path, [q, a])
    tail = append_torn(path, n)
    c.collect()
    with pytest.raises(ValueError, match='incomplete'):
        store(archive).messages()

    write(path, [q, a, n])
    c.close()
    result = store(archive)
    assert [m['id'] for m in result.messages()] == ['q', 'a', 'n']
    assert result.pending() == []
    assert any(o['event']['native']['record'].get('unparsedTranscriptTail') == tail for o in result.observations())


def test_resume_with_a_full_archive_collects_a_line_torn_inside_a_character(tmp_path: Path) -> None:
    """Bytes cut inside a UTF-8 character are the same read failure."""
    q, n = message('q', None, 'q'), message('n', 'q', 'é')
    c, path, archive = resume_with_full_archive(tmp_path, [q])
    whole = json.dumps(n, ensure_ascii=False).encode()
    torn = whole[:whole.index('é'.encode()) + 1]
    path.write_bytes(path.read_bytes() + torn)
    c.collect()
    with pytest.raises(ValueError, match='incomplete'):
        store(archive).messages()

    path.write_bytes(path.read_bytes().removesuffix(torn) + whole + b'\n')
    c.close()
    result = store(archive)
    assert [m['id'] for m in result.messages()] == ['q', 'n']
    assert result.pending() == []
    expected = base64.b64encode(torn).decode()
    assert any(o['event']['native']['record'].get('unparsedBytes') == expected for o in result.observations())


def test_resume_with_a_full_archive_recovers_from_a_transcript_briefly_unreadable(tmp_path: Path) -> None:
    """A read failure with no bytes to keep clears on the next read too."""
    q, n = message('q', None, 'q'), message('n', 'q', 'n')
    c, path, archive = resume_with_full_archive(tmp_path, [q])
    aside = path.with_suffix('.aside')
    path.rename(aside)
    c.collect()
    with pytest.raises(ValueError, match='incomplete'):
        store(archive).messages()

    aside.rename(path)
    write(path, [q, n])
    c.close()
    assert [m['id'] for m in store(archive).messages()] == ['q', 'n']


def test_resume_without_an_archive_keeps_its_gap_after_a_torn_line_completes(tmp_path: Path) -> None:
    """The history a resume left out stays reported, whatever the read did."""
    c, path, archive = cut_collector(tmp_path)
    old, n = message('old', None, 'old'), message('n', 'old', 'n')
    write(path, [old])
    c.bind(path, set(), path.stat().st_size)
    append_torn(path, n)
    c.collect()

    write(path, [old, n])
    c.close()
    assert pending_locators(archive) == ['history-gap']
    result = store(archive)
    assert result.pending()[0]['event']['missing'] == [{'path': 'history', 'reason': BACKFILL_DISABLED}]
    with pytest.raises(ValueError, match='Unresolved observations'):
        result.messages()
    assert [e['data']['id'] for e in result.page()['events'] if e['type'] == 'user/message'] == ['n']
    assert 'old' not in {e['native']['record'].get('uuid') for e in result.page()['events']}


def test_a_gap_from_an_earlier_activation_survives_a_later_torn_read(tmp_path: Path) -> None:
    """A later activation finding its own history archived does not clear an older gap."""
    from agent_swarm.sessions.claude_history import NO_HISTORY_SIZE

    current, reply = message('current', None, 'current'), message('reply', 'current', 'reply', role='assistant')
    first, path, archive = cut_collector(tmp_path)
    write(path, [current, reply])
    first.bind(path, {'current'}, NO_HISTORY_SIZE)
    first.accept({**reply, 'session_id': 's'}, 0)
    first.close()
    assert pending_locators(archive) == ['history-gap']

    later = resume(path, archive)
    assert later.excluded == {'current', 'reply'}
    n = message('n', 'reply', 'n')
    append_torn(path, n)
    later.collect()
    write(path, [current, reply, n])
    later.close()

    assert pending_locators(archive) == ['history-gap']
    with pytest.raises(ValueError, match='Unresolved observations'):
        store(archive).messages()


@pytest.mark.parametrize('resumed', [False, True])
def test_a_second_torn_read_is_reported_and_clears_in_turn(tmp_path: Path, resumed: bool) -> None:
    """One read resolving does not silence the next, on a first start or a resume."""
    q, n, m = message('q', None, 'q'), message('n', 'q', 'n'), message('m', 'n', 'm')
    c, path, archive = resume_with_full_archive(tmp_path, [q]) if resumed else first_start(tmp_path, [q])
    append_torn(path, n)
    c.collect()
    write(path, [q, n])
    c.collect()

    append_torn(path, m)
    c.close()
    assert store(archive).pending()
    with pytest.raises(ValueError, match='Unresolved observations'):
        store(archive).messages()

    write(path, [q, n, m])
    c.close()
    assert store(archive).pending() == []
    assert [item['id'] for item in store(archive).messages()] == ['q', 'n', 'm']


def test_repeated_torn_reads_of_one_tail_are_one_observation(tmp_path: Path) -> None:
    """Reads of one unfinished tail replace a draft; a later tail gets its own."""
    q, n, m = message('q', None, 'q'), message('n', 'q', 'n'), message('m', 'n', 'm')
    c, path, archive = resume_with_full_archive(tmp_path, [q])
    append_torn(path, n)
    c.collect()
    longer = json.dumps(n)[:40]
    write(path, [q])
    with path.open('a') as stream:
        stream.write(longer)
    c.collect()
    assert pending_locators(archive) == ['read-gap:0']
    assert store(archive).pending()[0]['event']['native']['record']['unparsedTranscriptTail'] == longer

    write(path, [q, n])
    c.collect()
    append_torn(path, m)
    c.collect()
    assert pending_locators(archive) == ['read-gap:1']


def test_a_resolved_torn_read_does_not_hide_a_later_real_gap(tmp_path: Path) -> None:
    """A published read failure leaves history-gap free for history really missed."""
    q, n, missed = message('q', None, 'q'), message('n', 'q', 'n'), message('missed', 'n', 'missed')
    c, path, archive = first_start(tmp_path, [q])
    append_torn(path, n)
    c.collect()
    write(path, [q, n])
    c.close()
    assert store(archive).pending() == []

    # An activation nothing collected wrote this; the next resume reads it as history.
    write(path, [q, n, missed])
    resume(path, archive).close()
    assert pending_locators(archive) == ['history-gap']
    result = store(archive)
    assert result.pending()[0]['event']['missing'] == [{'path': 'history', 'reason': BACKFILL_DISABLED}]
    with pytest.raises(ValueError, match='Unresolved observations'):
        result.messages()


@pytest.mark.parametrize('raw', [{'unparsedTranscriptTail': '{"type": "us'}, {'unparsedBytes': 'AP8='}])
def test_retained_torn_read_gap_resolves_on_a_resume_with_a_full_archive(tmp_path: Path, raw: dict) -> None:
    """An archive from an earlier version is not stuck on its old read failure."""
    q = message('q', None, 'q')
    first, path, archive = first_start(tmp_path, [q])
    retain_history_gap(archive, raw, 'Expecting value')
    resume(path, archive).close()
    result = store(archive)
    assert result.pending() == []
    assert [m['id'] for m in result.messages()] == ['q']
    assert any(o['event']['native']['record'] == raw for o in result.observations())


def test_a_resolved_retained_torn_read_does_not_hide_a_later_real_gap(tmp_path: Path) -> None:
    """Clearing an old read failure leaves history-gap free for history really missed."""
    q, missed = message('q', None, 'q'), message('missed', 'q', 'missed')
    first, path, archive = first_start(tmp_path, [q])
    retain_history_gap(archive, {'unparsedTranscriptTail': '{"type": "us'}, 'Expecting value')
    resume(path, archive).close()
    assert store(archive).pending() == []

    write(path, [q, missed])
    resume(path, archive).close()
    assert pending_locators(archive) == ['history-gap']
    with pytest.raises(ValueError, match='Unresolved observations'):
        store(archive).messages()


def test_retained_design_gap_stays_on_a_resume_with_a_full_archive(tmp_path: Path) -> None:
    """A retained gap without read bytes is history left out, not a failed read."""
    q = message('q', None, 'q')
    first, path, archive = first_start(tmp_path, [q])
    retain_history_gap(archive, {}, BACKFILL_DISABLED)
    resume(path, archive).close()
    assert pending_locators(archive) == ['history-gap']
    with pytest.raises(ValueError, match='Unresolved observations'):
        store(archive).messages()


def test_retained_torn_read_gap_stays_while_history_is_really_missing(tmp_path: Path) -> None:
    """A retained read failure clears only when no history is missing either."""
    q, missed = message('q', None, 'q'), message('missed', 'q', 'missed')
    first, path, archive = first_start(tmp_path, [q])
    retain_history_gap(archive, {'unparsedTranscriptTail': '{"type": "us'}, 'Expecting value')
    write(path, [q, missed])
    resume(path, archive).close()
    assert pending_locators(archive) == ['history-gap']
    with pytest.raises(ValueError, match='Unresolved observations'):
        store(archive).messages()


def test_a_tail_never_completed_keeps_messages_refusing(tmp_path: Path) -> None:
    """Content that never arrived stays reported, with what was read of it."""
    q, n = message('q', None, 'q'), message('n', 'q', 'n')
    c, path, archive = resume_with_full_archive(tmp_path, [q])
    tail = append_torn(path, n)
    c.close()
    result = store(archive)
    assert result.pending()[0]['event']['native']['record']['unparsedTranscriptTail'] == tail
    with pytest.raises(ValueError, match='Unresolved observations'):
        result.messages()


@pytest.mark.skipif(not os.environ.get('CLAUDE_SDK_MODULE'), reason='Explicit pinned official SDK comparison')
@pytest.mark.parametrize('case', ['chain', 'siblings', 'preserved-messages', 'preserved-segment', 'tools', 'replay',
                                'queued', 'queued-tail', 'queued-delivery', 'queued-forwarded', 'tools-indirect-replay',
                                'assistant-first'])
def test_order_matches_official_sdk_session_store(case: str) -> None:
    """Compare the official public SessionStore API, with no login or home scan."""
    records = [message('q', None, 'q'), message('a', 'q', 'a', role='assistant'),
               message('b', 'a', 'b', role='assistant')]
    if case == 'assistant-first':
        records = [message('q', None, 'old'),
                   message('new', None, 'new context', role='assistant')]
    if case == 'siblings':
        records[1]['message']['id'] = records[2]['message']['id'] = 'api'
        records[2]['parentUuid'] = 'q'
    if case.startswith('tools'):
        records[1]['message']['id'] = records[2]['message']['id'] = 'api'
        records[1]['message']['content'] = [{'type': 'tool_use', 'id': 'one', 'name': 'Read', 'input': {}}]
        records[2]['message']['content'] = [{'type': 'tool_use', 'id': 'two', 'name': 'Read', 'input': {}}]
        records[2]['parentUuid'] = 'q'
        second = message('result-two', 'b', 'same')
        second['message']['content'] = [{'type': 'tool_result', 'tool_use_id': 'two', 'content': 'same'}]
        first = message('result-one', 'a', 'same')
        first['message']['content'] = [{'type': 'tool_result', 'tool_use_id': 'one', 'content': 'same'}]
        records.extend([second, first, message('end', 'result-two', 'done', role='assistant')])
        if case == 'tools-indirect-replay':
            records.insert(-1, {**deepcopy(second), 'uuid': 'duplicate-two', 'parentUuid': 'q',
                                'sourceToolAssistantUUID': 'b'})
    if case == 'replay':
        records.append(deepcopy(records[1]))
    if case.startswith('queued'):
        attachment = {'type': 'attachment', 'uuid': 'queued', 'parentUuid': 'a', 'sessionId': 's',
                      'attachment': {'type': 'queued_command', 'prompt': 'next', 'source_uuid': 'source'}}
        if case == 'queued-forwarded':
            attachment['attachment']['forwardedIntent'] = {'lineage': 'native-lineage', 'source': 'relay'}
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


@pytest.mark.parametrize('retained_gap', [False, True])
def test_assistant_first_context_change_replaces_surface_preserving_history(
    tmp_path: Path, retained_gap: bool,
) -> None:
    """An independent assistant root replaces context without a synthetic user."""
    original = message('q', None, 'old')
    c, path, archive = collector(tmp_path, [original])
    before = store(archive).page()['events']
    replacement = message('new', None, 'new context', role='assistant',
                          completedAt='native-completion', unknown={'retain': True})
    write(path, [original, replacement])
    if retained_gap:
        # A prior collector checkpoint remains an observation, never rewritten
        # as a successful original collection after upgrading the validator.
        gap = {'type': 'claude/observation', 'seq': 0, 'time': 0,
               'data': {}, 'ignorable': True, 'native': {
                   'runtime': 'claude', 'sessionId': 's', 'locator': 'history-gap',
                   'record': {'nativeContext': [replacement]}},
               'missing': [{'path': 'history', 'reason':
                   'Archive protocol cannot replace context with an assistant-first chain.'}]}
        store(archive).checkpoint(gap, source='history-gap', position=0)
    c.collect()
    result = store(archive)
    events = result.page()['events']
    assert events[:len(before)] == before
    assert result.pending() == []
    assert [(m['id'], m['role'], m['content']) for m in result.messages()] == [
        ('new', 'assistant', replacement['message']['content'])]
    published = next(e for e in events if e['type'] == 'assistant/message')
    assert published['native']['record'] == replacement
    assert published['surfaceOp'] == {'op': 'replace', 'startSeq': 0, 'endSeq': 0}
    assert published['sourceEventSeqs'] == [0]
    if retained_gap:
        assert any(o['event'] == gap for o in result.observations())
    c.collect()
    assert store(archive).page()['events'] == events


def test_received_batch_preserves_fragments_boundaries_and_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A backlog reads the archive per batch while retaining content and later disablement."""
    c, _, archive = collector(tmp_path, [])
    opened = []
    initialize = JsonlSessionStore.__init__

    def observe(self, path: Path, **options: object) -> None:
        """Count full archive reads, the long-Session cost under investigation."""
        opened.append(path)
        initialize(self, path, **options)

    monkeypatch.setattr(JsonlSessionStore, '__init__', observe)
    records = [{'type': 'stream_event', 'session_id': 's', 'event': {
        'type': 'message_start', 'message': {'id': 'api'}}}]
    records.extend({'type': 'stream_event', 'session_id': 's', 'uuid': str(i), 'event': {
        'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': str(i) + ','}}}
        for i in range(100))
    boundary = {'type': 'control_request', 'session_id': 's', 'request': {'unknown': 'retained'}}
    records.append(boundary)
    c.accept_batch(list(zip(records, range(len(records)))))
    assert len(opened) < 10  # No whole-archive read for each of the 100 fragments.
    retained = store(archive)
    draft = next(p['event'] for p in retained.pending()
                 if p['event']['native']['locator'] == 'stream:api')
    assert draft['data']['stream'][1]['text'] == ''.join(str(i) + ',' for i in range(100))
    assert any(p['event']['native']['record'] == boundary for p in retained.pending())
    before = retained.path.read_bytes()
    archive.save_normalized_sessions = False
    c.accept_batch([(boundary, len(records))])
    assert retained.path.read_bytes() == before


def test_message_batch_reads_native_history_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve a message backlog once, preserving native order and observations."""
    c, path, archive = collector(tmp_path, [])
    records = [message('q', None, 'question'), message('a', 'q', 'answer', role='assistant')]
    write(path, records)
    reads = []
    original_open = Path.open

    def observe(self: Path, *args: object, **kwargs: object):
        """Measure actual transcript reads without replacing collection work."""
        if self == path:
            reads.append(self)
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', observe)
    # Notifications can arrive backwards; the native chain decides order.
    boundary = {'type': 'control_request', 'request': {'unknown': 'retained'}}
    c.accept_batch([(records[1], 0), (records[0], 1), (boundary, 2)])
    assert len(reads) == 1
    retained = store(archive)
    assert [m['id'] for m in retained.messages()] == ['q', 'a']
    observed = [o['event']['native']['record'] for o in retained.observations()]
    assert all(record in observed for record in [*records, boundary])
