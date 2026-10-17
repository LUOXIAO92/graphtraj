"""Owned rollout records, rather than notification order, drive JSONL messages."""

import asyncio
import json
from pathlib import Path

import pytest

from agent_swarm import write_config
from graphtraj.interfaces.agents import ConfiguredSessionArchive
from graphtraj.runtimes.codex.jsonl_archive import CodexJsonlArchive
from graphtraj.sessions.archive import JsonlSessionStore, archive_path
from graphtraj.sessions.protocol import native_record
from graphtraj.runtimes.codex.app_server import CodexAppServer
from test_codex_app_server import context, peer  # noqa: F401


def write(path: Path, records: list[dict]) -> None:
    """Write complete native records in their supplied source order."""
    path.write_text(''.join(json.dumps(record) + '\n' for record in records))


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
    store = JsonlSessionStore(archive_path(root, 'codex:native'))
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


def test_compaction_is_retained_without_claiming_complete_messages(tmp_path: Path) -> None:
    """An unimplemented history replacement cannot silently yield an old prompt."""
    root = tmp_path / 'swarm'
    write_config(root, save_normalized_sessions=True, backfill_history=True)
    source = tmp_path / 'rollout.jsonl'
    records = history() + [{'type': 'compacted', 'payload': {'replacement_history': []}}]
    write(source, records)
    collector = CodexJsonlArchive(ConfiguredSessionArchive(root), 'agent', 'native', source)
    collector.collect(source)
    store = JsonlSessionStore(archive_path(root, 'codex:native'))
    assert native_record(store.page()['events'][-1]) == records[-1]
    with pytest.raises(ValueError, match='opaque-native'):
        store.messages()


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
