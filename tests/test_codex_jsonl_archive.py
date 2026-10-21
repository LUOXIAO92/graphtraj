"""Owned rollout records, rather than notification order, drive JSONL messages."""

import asyncio
import json
from pathlib import Path

import pytest

from agent_swarm import write_config
from graphtraj.interfaces.agents import ConfiguredSessionArchive
from graphtraj.runtimes.codex.jsonl_archive import CodexJsonlArchive
from graphtraj.sessions.archive import JsonlSessionStore, SessionArchive, archive_path
from graphtraj.sessions.protocol import native_record
from graphtraj.runtimes.codex.app_server import CodexAppServer
from test_codex_app_server import context, peer  # noqa: F401


def write(path: Path, records: list[dict]) -> None:
    """Write complete native records in their supplied source order."""
    path.write_text(''.join(json.dumps(record) + '\n' for record in records))


def current(root: Path) -> JsonlSessionStore:
    """Read the current project Session for the test's native conversation."""
    return JsonlSessionStore(archive_path(root, SessionArchive(root).native_id('codex', 'native')))


def history() -> list[dict]:
    """Return native results in reverse call order and with backward timestamps."""
    items = [
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'both'}]},
        {'type': 'function_call', 'call_id': 'a', 'name': 'first', 'arguments': '{}'},
        {'type': 'function_call', 'call_id': 'b', 'name': 'second', 'arguments': '{  "x": 1 }'},
        {'type': 'function_call_output', 'call_id': 'b', 'output': 'same'},
        {'type': 'function_call_output', 'call_id': 'a', 'output': 'same'},
        {'type': 'reasoning', 'summary': [], 'encrypted_content': 'opaque+/=', 'future': [None, 7]},
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'done'}]},
    ]
    return [{'type': 'session_meta', 'timestamp': '2026-10-18T00:00:00Z',
             'payload': {'id': 'native', 'source': 'appServer'}}] + [
        {'type': 'response_item', 'timestamp': f'2026-10-18T00:00:0{7 - index}Z', 'payload': item}
        for index, item in enumerate(items)
    ]


def test_jsonl_native_order_content_ciphertext_and_partial_tail(tmp_path: Path) -> None:
    """Collect ordered native messages and preserve incomplete lines for retry."""
    root = tmp_path / 'swarm'
    write_config(root, save_normalized_sessions=True, backfill_history=True)
    source = tmp_path / 'rollout.jsonl'
    archive = ConfiguredSessionArchive(root)
    collector = CodexJsonlArchive(archive, 'agent', 'native', source)
    records = history()
    write(source, records[:-1])
    tail = json.dumps(records[-1])
    with source.open('a') as stream:
        stream.write(tail[:20])
    collector.collect(source)
    store = current(root)
    assert [native_record(event) for event in store.page()['events']] == records[:-1]
    assert [message['toolCallId'] for message in store.messages() if message['role'] == 'tool'] == ['b', 'a']
    with source.open('a') as stream:
        stream.write(tail[20:] + '\n')
    collector.collect(source)
    collector.collect(source)
    store = JsonlSessionStore(store.path)
    assert [native_record(event) for event in store.page()['events']] == records
    assert store.messages()[-1]['content'] == [{'type': 'text', 'text': 'done'}]
    assert store.messages()[-2]['content'][0]['value'] == 'opaque+/='
    assert store.page()['events'][1]['time'] > store.page()['events'][-1]['time']


def test_save_and_backfill_choices_control_actual_collection(tmp_path: Path) -> None:
    """Excluded history stays explicitly unresolved until mapped backfill is enabled."""
    root = tmp_path / 'swarm'
    source = tmp_path / 'rollout.jsonl'
    records = history()
    write(source, records[:-1])
    write_config(root, save_normalized_sessions=True, backfill_history=False)
    archive = ConfiguredSessionArchive(root)
    collector = CodexJsonlArchive(archive, 'agent', 'native', source)
    write(source, records)
    collector.collect(source)
    path = archive_path(root, 'codex:native')
    store = JsonlSessionStore(path)
    assert [native_record(event) for event in store.page()['events']] == records[-1:]
    assert store.pending()
    with pytest.raises(ValueError, match='incomplete'):
        store.messages()
    write_config(root, backfill_history=True)
    collector.collect(source)
    store = JsonlSessionStore(path)
    assert [native_record(event) for event in store.page()['events']] == records
    assert not store.pending()
    assert len(store.messages()) == 7
    before = path.read_bytes()
    write_config(root, save_normalized_sessions=False)
    write(source, records + [{'type': 'future_history', 'payload': {'opaque': True}}])
    collector.collect(source)
    assert path.read_bytes() == before
    write_config(root, save_normalized_sessions=True)
    collector.collect(source)
    with pytest.raises(ValueError, match='opaque-native'):
        JsonlSessionStore(path).messages()


def test_empty_compaction_replaces_messages_without_losing_evidence(tmp_path: Path) -> None:
    """An empty native replacement clears the surface, retaining the original log."""
    root = tmp_path / 'swarm'
    write_config(root, save_normalized_sessions=True, backfill_history=True)
    source = tmp_path / 'rollout.jsonl'
    records = history() + [{'type': 'compacted', 'payload': {'replacement_history': []}}]
    write(source, records)
    collector = CodexJsonlArchive(ConfiguredSessionArchive(root), 'agent', 'native', source)
    collector.collect(source)
    store = current(root)
    assert native_record(store.page()['events'][-2]) == records[-1]
    assert store.messages() == []


def test_compaction_retained_context_and_rollback(tmp_path: Path) -> None:
    """Replacement order survives retained authorization state and a dropped turn."""
    root = tmp_path / 'swarm'
    write_config(root, save_normalized_sessions=True, backfill_history=True)
    source = tmp_path / 'rollout.jsonl'
    first = {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'keep'}]}
    second = {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'drop'}]}
    records = history() + [
        {'type': 'compacted', 'payload': {'replacement_history': [first],
                                        'window_number': 1, 'resume_metadata': {},
                                        'replacement_history_metadata': [{'user_input_order': 1}]}},
        {'type': 'retained_context', 'payload': {'opaque': 'authorization', 'future': [1, None]}},
        {'type': 'response_item', 'payload': second, 'metadata': {'user_input_order': 2}},
        {'type': 'event_msg', 'payload': {'type': 'thread_rolled_back', 'num_turns': 1}},
    ]
    write(source, records)
    collector = CodexJsonlArchive(ConfiguredSessionArchive(root), 'agent', 'native', source)
    collector.collect(source)
    collector.collect(source)
    store = current(root)
    assert [message['content'][0]['text'] for message in store.messages()] == ['keep']
    assert any(native_record(event) == records[-3] for event in store.page()['events']
               if event['type'] != 'graphtraj/history')


def test_rollback_restores_history_before_removed_legacy_compaction(tmp_path: Path) -> None:
    """A compaction belonging to the removed turn cannot delete surviving input."""
    root = tmp_path / 'swarm'
    write_config(root, save_normalized_sessions=True, backfill_history=True)
    source = tmp_path / 'rollout.jsonl'
    records = history()[:1]
    for turn, text in [('a', 'keep'), ('b', 'drop')]:
        records.extend([
            {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': turn}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                                                'content': [{'type': 'input_text', 'text': text}]}},
        ])
    records.extend([
        {'type': 'compacted', 'payload': {'replacement_history': []}},
        {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 'b'}},
        {'type': 'event_msg', 'payload': {'type': 'thread_rolled_back', 'num_turns': 1}},
    ])
    write(source, records)
    CodexJsonlArchive(ConfiguredSessionArchive(root), 'agent', 'native', source).collect(source)
    store = current(root)
    assert [message['content'][0]['text'] for message in store.messages()] == ['keep']


def test_rollback_keeps_persistent_developer_prefix_and_original_annotations(tmp_path: Path) -> None:
    """Dropping the first turn strips its model/mode fragments without losing evidence."""
    root = tmp_path / 'swarm'
    write_config(root, save_normalized_sessions=True, backfill_history=True)
    source = tmp_path / 'rollout.jsonl'
    developer = {'type': 'message', 'role': 'developer', 'content': [
        {'type': 'input_text', 'text': 'persistent'},
        {'type': 'input_text', 'text': '<model_switch>current</model_switch>'},
    ], 'internal_chat_message_metadata_passthrough': {
        'turn_id': 'a', 'content_item_kinds': ['developer.text', 'model_switch'], 'unknown': 9,
    }}
    user = {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'drop'}],
            'internal_chat_message_metadata_passthrough': {'turn_id': 'a'}}
    records = history()[:1] + [
        {'type': 'response_item', 'payload': developer},
        {'type': 'response_item', 'payload': user},
        {'type': 'event_msg', 'payload': {'type': 'thread_rolled_back', 'num_turns': 1}},
    ]
    write(source, records)
    collector = CodexJsonlArchive(ConfiguredSessionArchive(root), 'agent', 'native', source)
    collector.collect(source)
    store = current(root)
    assert store.messages()[0]['content'] == [{'type': 'text', 'text': 'persistent'}]
    assert native_record(store.page()['events'][1])['payload'] == developer
    # Replaying a later no-op rollback must not duplicate the derived prefix.
    write(source, records + [{'type': 'event_msg', 'payload': {'type': 'thread_rolled_back', 'num_turns': 0}}])
    collector.collect(source)
    assert JsonlSessionStore(store.path).messages() == store.messages()


def test_native_agent_communication_keeps_author_ciphertext_and_rollback_boundary(tmp_path: Path) -> None:
    """Native peer messages retain their author rather than becoming Main output."""
    root = tmp_path / 'swarm'
    write_config(root, save_normalized_sessions=True, backfill_history=True)
    source = tmp_path / 'rollout.jsonl'
    communication = {'type': 'inter_agent_communication', 'payload': {
        'author': 'main/worker', 'recipient': 'main', 'other_recipients': [],
        'content': '', 'encrypted_content': 'opaque+/=', 'trigger_turn': False, 'unknown': ['kept'],
    }}
    records = history()[:2] + [communication]
    write(source, records)
    collector = CodexJsonlArchive(ConfiguredSessionArchive(root), 'agent', 'native', source)
    collector.collect(source)
    store = current(root)
    message = store.messages()[-1]
    assert message['source']['author'] == 'main/worker'
    assert message['content'][0]['item']['content'][-1]['encrypted_content'] == 'opaque+/='
    assert native_record(store.page()['events'][-1]) == communication
    write(source, records + [{'type': 'event_msg', 'payload': {'type': 'thread_rolled_back', 'num_turns': 1}}])
    collector.collect(source)
    assert len(current(root).messages()) == 1


def test_copied_fork_seeds_before_child_messages(tmp_path: Path) -> None:
    """A copied native prefix remains inherited and precedes the child prompt."""
    root = tmp_path / 'swarm'
    write_config(root, save_normalized_sessions=True, backfill_history=True)
    source = tmp_path / 'rollout.jsonl'
    records = history()
    records[0]['payload']['forked_from_id'] = 'parent'
    records += [
        {'type': 'event_msg', 'payload': {'type': 'thread_settings_applied', 'thread_id': 'native'}},
        {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                                            'content': [{'type': 'input_text', 'text': 'child'}]}},
    ]
    write(source, records)
    collector = CodexJsonlArchive(ConfiguredSessionArchive(root), 'agent', 'native', source)
    collector.collect(source)
    store = current(root)
    assert store.header['parentSession'] == 'codex:parent'
    assert len(store.messages()) == 8
    assert store.messages()[-1]['content'][0]['text'] == 'child'


def test_referenced_fork_waits_for_exact_parent_cut(tmp_path: Path) -> None:
    """A late parent archive resolves the prefix without importing its later turn."""
    root = tmp_path / 'swarm'
    write_config(root, save_normalized_sessions=True, backfill_history=True)
    archive = ConfiguredSessionArchive(root)
    parent_path = tmp_path / 'parent.jsonl'
    parent_records = history()
    for ordinal, record in enumerate(parent_records):
        record['ordinal'] = ordinal
    write(parent_path, parent_records[:2])
    cut = parent_path.stat().st_size
    child_path = tmp_path / 'child.jsonl'
    child_records = [
        {'type': 'session_meta', 'ordinal': 0, 'payload': {'id': 'child', 'forked_from_id': 'native',
            'history_base': {'thread_id': 'native', 'end_byte_offset': cut, 'end_ordinal_exclusive': 2}}},
        {'type': 'response_item', 'ordinal': 1, 'payload': {'type': 'message', 'role': 'user',
                                                         'content': [{'type': 'input_text', 'text': 'child'}]}},
    ]
    write(child_path, child_records)
    child = CodexJsonlArchive(archive, 'child-agent', 'child', child_path)
    child.collect(child_path)
    path = archive_path(root, 'codex:child')
    assert JsonlSessionStore(path).pending()
    with pytest.raises(ValueError, match='incomplete'):
        JsonlSessionStore(path).messages()
    before = child.collection_key()
    write(parent_path, parent_records)
    CodexJsonlArchive(archive, 'parent-agent', 'native', parent_path).collect(parent_path)
    assert child.collection_key() != before
    child.collect(child_path)
    store = JsonlSessionStore(path)
    assert not store.pending()
    assert [message['content'][0]['text'] for message in store.messages()] == ['both', 'child']
    grandchild_path = tmp_path / 'grandchild.jsonl'
    first_child_line = child_path.read_bytes().splitlines(keepends=True)[0]
    write(grandchild_path, [
        {'type': 'session_meta', 'ordinal': 0, 'payload': {
            'id': 'grandchild', 'forked_from_id': 'child', 'history_base': {
                'thread_id': 'child', 'end_byte_offset': len(first_child_line), 'end_ordinal_exclusive': 1,
            },
        }},
    ])
    CodexJsonlArchive(archive, 'grandchild-agent', 'grandchild', grandchild_path).collect(grandchild_path)
    grandchild = JsonlSessionStore(archive_path(root, 'codex:grandchild'))
    assert [message['content'][0]['text'] for message in grandchild.messages()] == ['both']


def test_runtime_observes_archive_policy_without_new_native_output(tmp_path: Path, peer: Path) -> None:
    """A backfill choice wakes collection of the same unchanged native file."""
    async def exercise() -> None:
        """Use the Runtime's production trace owner instead of calling the mapper."""
        root = tmp_path / 'swarm'
        write_config(root, save_normalized_sessions=True, backfill_history=False)
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path, environment={
            'PEER_NATIVE_ROLLOUT': str(tmp_path / 'native'),
        }) as adapter:
            session = await adapter.create_session(context(tmp_path / 'worktree', peer))
            source = session.rollout_path
            source.parent.mkdir()
            records = history()
            records[0]['payload']['id'] = session.thread_id
            write(source, records)
            archive = ConfiguredSessionArchive(root)
            collector = CodexJsonlArchive(archive, 'agent', session.thread_id, source)
            adapter.retain_native_trace(session, tmp_path / 'trace.jsonl', archive=collector)
            path = archive_path(root, 'codex:' + session.thread_id)
            assert JsonlSessionStore(path).pending()
            write_config(root, backfill_history=True)
            await asyncio.sleep(0.3)
            store = JsonlSessionStore(path)
            assert not store.pending()
            assert len(store.messages()) == 7
            before = path.read_bytes()
            write_config(root, save_normalized_sessions=False)
            write(source, records + [{'type': 'future_history', 'payload': {'opaque': True}}])
            await asyncio.sleep(0.3)
            assert path.read_bytes() == before

    asyncio.run(exercise())
