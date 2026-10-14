"""Observable lossless collection and recovery at the Codex archive seam."""

import json
from pathlib import Path
import shutil

import pytest

from graphtraj.runtimes.codex.session_archive import CodexSessionArchive
from graphtraj.sessions.protocol import native_record
from graphtraj.sessions.storage import SessionStore, session_path


def records(session: str = 'native') -> list[dict]:
    """Supply distinct semantic records, including fields no mapper understands."""
    return [
        {'type': 'session_meta', 'timestamp': '2026-10-15T00:00:00Z',
         'payload': {'id': session, 'source': 'cli'}},
        {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
         'content': [{'type': 'input_text', 'text': 'hello'}]}},
        {'type': 'response_item', 'payload': {'type': 'reasoning',
         'summary': [{'text': 'visible reasoning'}], 'encrypted_content': 'opaque+/='}},
        {'type': 'response_item', 'payload': {'type': 'function_call',
         'call_id': 'call', 'name': 'tool', 'arguments': '{  "a": 1 }'}},
        {'type': 'response_item', 'payload': {'type': 'function_call_output',
         'call_id': 'call', 'output': 'result'}},
        {'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {
         'total_token_usage': {'input_tokens': 15, 'cached_input_tokens': 5, 'output_tokens': 2}}}},
        {'type': 'compacted', 'payload': {'message': 'summary', 'replacement_history': None}},
        {'type': 'future_event', 'payload': {'unknown': [None, {'opaque': 'unchanged'}]}},
    ]


def write_records(path: Path, values: list[dict]) -> None:
    """Write a native producer's complete lines without normalizing their data."""
    path.write_text(''.join(json.dumps(record) + '\n' for record in values))


def test_resume_partial_line_and_cleanup_preserve_native_content(tmp_path: Path) -> None:
    """Only committed complete records appear once, independent of native lifetime."""
    worktree = tmp_path / 'worktree'
    worktree.mkdir()
    rollout = worktree / 'rollout.jsonl'
    values = records()
    write_records(rollout, values[:-1])
    tail = json.dumps(values[-1]).encode()
    with rollout.open('ab') as output:
        output.write(tail[:10])
    state = tmp_path / 'state'
    archive = CodexSessionArchive(state, 'project', 'agent', 'native', ('313',))
    archive.collect(rollout)
    with SessionStore(session_path(state, 'codex:native'), readonly=True) as store:
        assert [native_record(item) for item in store.page()['events']] == values[:-1]
        assert store.position('rollout') == rollout.stat().st_size - 10
    with rollout.open('ab') as output:
        output.write(tail[10:] + b'\n')
    # Task switching cannot change the owning Agent or duplicate imported usage.
    resumed = CodexSessionArchive(state, 'project', 'agent', 'native', ('next-task',))
    resumed.collect(rollout)
    resumed.collect(rollout)
    shutil.rmtree(worktree)
    with SessionStore(session_path(state, 'codex:native')) as store:
        store.validate()
        events = store.page()['events']
        assert [native_record(item) for item in events] == values
        assert len([item for item in events if native_record(item)['type'] == 'event_msg']) == 1
        assert store.header['graphtraj']['agentId'] == 'agent'
        assert events[2]['graphtraj']['missing']
        exported = tmp_path / 'standalone.sqlite3'
        store.export(exported)
    shutil.rmtree(state)
    with SessionStore(exported, readonly=True) as store:
        assert [native_record(item) for item in store.page()['events']] == values


def test_invalid_complete_input_does_not_advance_cursor(tmp_path: Path) -> None:
    """A visible acquisition failure leaves the failed source record replayable."""
    rollout = tmp_path / 'rollout.jsonl'
    write_records(rollout, records()[:1])
    committed = rollout.stat().st_size
    with rollout.open('ab') as output:
        output.write(b'{broken}\n')
    archive = CodexSessionArchive(tmp_path, 'project', 'agent', 'native')
    with pytest.raises(ValueError):
        archive.collect(rollout)
    with SessionStore(archive.path, readonly=True) as store:
        assert store.next_seq == 1
        assert store.position('rollout') == committed
    write_records(rollout, records()[:2])
    archive.collect(rollout)
    with SessionStore(archive.path, readonly=True) as store:
        assert store.next_seq == 2


def test_native_identity_and_agent_identity_are_independent(tmp_path: Path) -> None:
    """One owner can archive multiple Sessions; another cannot claim an archive."""
    rollout = tmp_path / 'rollout.jsonl'
    for session in ('first', 'second'):
        write_records(rollout, records(session))
        archive = CodexSessionArchive(tmp_path, 'project', 'agent', session)
        archive.collect(rollout)
        with SessionStore(archive.path, readonly=True) as store:
            assert store.header['graphtraj']['agentId'] == 'agent'
            assert store.header['id'] == 'codex:' + session
    with pytest.raises(ValueError, match='another project or Agent'):
        CodexSessionArchive(tmp_path, 'project', 'other', 'second').collect(rollout)
    with pytest.raises(ValueError, match='owned Session'):
        CodexSessionArchive(tmp_path, 'project', 'agent', 'first').collect(rollout)


def test_inline_attachments_survive_and_unfetched_references_are_explicit(tmp_path: Path) -> None:
    """Actual bytes are portable; an external URI never silently means empty data."""
    rollout = tmp_path / 'rollout.jsonl'
    values = records()[:1] + [{'type': 'response_item', 'payload': {
        'type': 'message', 'role': 'user', 'content': [
            {'type': 'input_image', 'image_url': 'data:image/png;base64,aW1hZ2U='},
            {'type': 'input_file', 'file_data': 'data:application/pdf;base64,?invalid'},
            {'type': 'local_image', 'path': '/private/not-authorized.png'},
        ],
    }}]
    write_records(rollout, values)
    archive = CodexSessionArchive(tmp_path, 'project', 'agent', 'native')
    archive.collect(rollout)
    rollout.unlink()
    with SessionStore(archive.path, readonly=True) as store:
        event = store.page()['events'][1]
        assert native_record(event) == values[1]
        inline, malformed, external = event['graphtraj']['attachments']
        assert store.attachment(inline['sha256']) == b'image'
        assert malformed['missing']['reason'] == 'Invalid inline base64 bytes.'
        assert external['missing']['reason']


def test_fork_retains_exact_returned_prefix_without_reading_parent(tmp_path: Path) -> None:
    """Later parent history cannot shift a child's recorded native inheritance cut."""
    archive = CodexSessionArchive(tmp_path, 'project', 'checker', 'child')
    thread = {'id': 'child', 'forkedFromId': 'parent', 'turns': [
        {'id': 'turn-at-fork', 'items': [{'type': 'reasoning', 'encrypted_content': 'cipher'}]},
    ]}
    archive.seed_fork(thread)
    notice = {'method': 'item/completed', 'params': {'threadId': 'child',
              'turnId': 'new-turn', 'item': {'type': 'agentMessage', 'text': 'new'}}}
    archive.notice(notice)
    archive.notice({'method': 'item/completed', 'params': {'threadId': 'parent'}})
    with SessionStore(archive.path) as store:
        store.validate()
        events = store.page()['events']
        assert len(events) == 3
        assert native_record(events[0]) == thread
        assert events[1]['data'] == {'inherited': True}
        assert native_record(events[2]) == notice
        assert store.header['parentSession'] == 'codex:parent'


def test_persistent_copied_fork_uses_child_settings_boundary(tmp_path: Path) -> None:
    """A late first collection distinguishes inherited settings from child updates."""
    rollout = tmp_path / 'fork.jsonl'
    header = records('child')[0]
    header['payload']['forked_from_id'] = 'parent'
    inherited = records('parent') + [{'type': 'event_msg', 'payload': {
        'type': 'thread_settings_applied', 'thread_id': 'parent', 'thread_settings': {},
    }}]
    write_records(rollout, [header, *inherited])
    archive = CodexSessionArchive(tmp_path, 'project', 'main', 'child')
    archive.collect(rollout)
    assert not archive.path.exists()  # The unfinished native prefix remains replayable.
    owned_settings = {'type': 'event_msg', 'payload': {
        'type': 'thread_settings_applied', 'thread_id': 'child', 'thread_settings': {},
    }}
    child_content = records('child')[1:]
    values = [header, *inherited, owned_settings, *child_content, owned_settings]
    write_records(rollout, values)
    archive.collect(rollout)
    archive.collect(rollout)
    with SessionStore(archive.path) as store:
        store.validate()
        events = store.page()['events']
        cut = len(inherited) + 1
        assert events[cut]['type'] == 'session/end-seed'
        assert [native_record(event) for event in events if event['type'] != 'session/end-seed'] == values
        assert len(events) == len(values) + 1
        assert store.header['parentSession'] == 'codex:parent'


def test_referenced_fork_copies_only_native_ordinal_prefix(tmp_path: Path) -> None:
    """Parent growth and source cleanup cannot change a referenced child's prefix."""
    parent_values = records('parent')
    for ordinal, record in enumerate(parent_values):
        record['ordinal'] = ordinal
    parent_source = tmp_path / 'parent.jsonl'
    write_records(parent_source, parent_values[:2])
    parent = CodexSessionArchive(tmp_path, 'project', 'parent-agent', 'parent')
    parent.collect(parent_source)
    # The parent's native log has advanced after its last hook collection.
    write_records(parent_source, parent_values)
    child_values = records('child')[:2]
    for ordinal, record in enumerate(child_values, start=3):
        record['ordinal'] = ordinal
    child_values[0]['payload'].update(forked_from_id='parent', history_mode='paginated', history_base={
        'thread_id': 'parent', 'end_ordinal_exclusive': 3,
        'end_byte_offset': len(''.join(json.dumps(item) + '\n' for item in parent_values[:3]).encode()),
    }, forked_from_ordinal_exclusive=3)
    child_source = tmp_path / 'child.jsonl'
    write_records(child_source, child_values)
    child = CodexSessionArchive(tmp_path, 'project', 'child-agent', 'child')
    child.collect(child_source)
    child.collect(child_source)
    parent.path.unlink()
    parent_source.unlink()
    child_source.unlink()
    with SessionStore(child.path) as store:
        store.validate()
        events = store.page()['events']
        assert events[3]['type'] == 'session/end-seed'
        assert [native_record(event) for event in events[:3]] == parent_values[:3]
        assert [native_record(event) for event in events[4:]] == child_values
