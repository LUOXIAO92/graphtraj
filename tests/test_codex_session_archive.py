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
        assert malformed['missing']['reason']
        assert malformed['missing']['path'] == '/payload/content/1/file_data'
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
        assert len(events) == 4
        assert native_record(events[0]) == thread['turns'][0]
        assert events[1]['data'] == {'inherited': True}
        assert native_record(events[2]) == thread
        assert native_record(events[3]) == notice
        assert store.header['parentSession'] == 'codex:parent'


def test_native_time_meanings_survive_fork_and_notifications(tmp_path: Path) -> None:
    """History uses its own timestamps; server emission never becomes receipt time."""
    archive = CodexSessionArchive(tmp_path, 'project', 'checker', 'child')
    thread = {'id': 'child', 'forkedFromId': 'parent', 'createdAt': 200,
              'turns': [{'id': 'old', 'startedAt': 10, 'items': []},
                        {'id': 'unknown', 'items': []}]}
    archive.seed_fork(thread)
    notice = {'method': 'item/completed', 'emittedAtMs': 42,
              'params': {'threadId': 'child', 'turnId': 'new',
                         'item': {'type': 'agentMessage', 'text': 'late'}}}
    archive.notice(notice)
    archive.notice({'method': 'unknown', 'params': {'threadId': 'child'}})
    with SessionStore(archive.path) as store:
        events = store.page()['events']
        assert store.header['createdAt'] == 200000
        assert [event['time'] for event in events] == [10000, 0, 0, 0, 42, 0]
        assert native_record(events[0]) == thread['turns'][0]
        assert events[1]['graphtraj']['missing']
        assert native_record(events[-2]) == notice
        assert events[-2]['graphtraj']['receivedAtMs'] > 42
        assert events[-1]['graphtraj']['missing']


@pytest.mark.parametrize('interrupt_promotion', [False, True])
def test_persistent_copied_fork_uses_child_settings_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupt_promotion: bool,
) -> None:
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
    rollout.unlink()
    with SessionStore(archive.path, readonly=True) as store:
        assert store.page()['events'] == []
        assert 'parentSession' not in store.header
        assert store.header['isSeeded'] is False
        observations = store.pending()['event']['data']['observations']
        assert [native_record(item['event']) for item in observations] == [header, *inherited]
    # Restore the owned source and resume with a new collector after restart.
    archive = CodexSessionArchive(tmp_path, 'project', 'main', 'child')
    owned_settings = {'type': 'event_msg', 'payload': {
        'type': 'thread_settings_applied', 'thread_id': 'child', 'thread_settings': {},
    }}
    child_content = records('child')[1:]
    values = [header, *inherited, owned_settings, *child_content, owned_settings]
    write_records(rollout, values)
    if interrupt_promotion:
        def interrupted(
            self: SessionStore, *, parent_session: str | None, inherited: list[tuple[str, int]],
        ) -> None:
            """Simulate interruption after the source boundary is durably staged."""
            raise OSError('controlled interruption')

        with monkeypatch.context() as fault:
            fault.setattr(SessionStore, 'finish_initial_collection', interrupted)
            with pytest.raises(OSError):
                archive.collect(rollout)
        archive = CodexSessionArchive(tmp_path, 'project', 'main', 'child')
    archive.collect(rollout)
    archive.collect(rollout)
    with SessionStore(archive.path) as store:
        store.validate()
        events = store.page()['events']
        assert store.pending() is None
        cut = len(inherited)
        assert events[cut]['type'] == 'session/end-seed'
        assert [native_record(event) for event in events[:cut]] == inherited
        assert native_record(events[cut + 1]) == header
        native_events = [event for event in events if event['type'] != 'session/end-seed']
        native_events.sort(key=lambda event: int(event['graphtraj']['native']['locator'].split(':')[1]))
        assert [native_record(event) for event in native_events] == values
        assert len(events) == len(values) + 1
        assert store.header['parentSession'] == 'codex:parent'


@pytest.mark.parametrize('copied_parent', [False, True])
def test_referenced_fork_copies_only_native_ordinal_prefix(tmp_path: Path, copied_parent: bool) -> None:
    """Parent growth and source cleanup cannot change a referenced child's prefix."""
    parent_values = records('parent')
    if copied_parent:
        parent_values[0]['payload']['forked_from_id'] = 'ancestor'
        parent_values.insert(4, {'type': 'event_msg', 'payload': {
            'type': 'thread_settings_applied', 'thread_id': 'parent', 'thread_settings': {},
        }})
    for ordinal, record in enumerate(parent_values):
        record['ordinal'] = ordinal
    parent_source = tmp_path / 'parent.jsonl'
    write_records(parent_source, parent_values[:5 if copied_parent else 2])
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


@pytest.mark.parametrize('method, index', [
    ('item/agentMessage/delta', {}),
    ('item/plan/delta', {}),
    ('item/reasoning/textDelta', {'contentIndex': 0}),
    ('item/reasoning/summaryTextDelta', {'summaryIndex': 0}),
])
def test_checker_deltas_are_compact_and_survive_reopening(
    tmp_path: Path, method: str, index: dict,
) -> None:
    """Many chunks produce one retained run and one exact final native snapshot."""
    archive = CodexSessionArchive(tmp_path, 'project', 'checker', 'child')
    archive.seed_fork({'id': 'child', 'forkedFromId': 'parent', 'turns': []})
    for _ in range(300):
        archive.notice({'method': method, 'params': {'threadId': 'child',
                        'turnId': 'turn', 'itemId': 'item', 'delta': 'x', **index}})
    # Reopen as a new collector without any native transport/file replay.
    archive = CodexSessionArchive(tmp_path, 'project', 'checker', 'child')
    with SessionStore(archive.path, readonly=True) as store:
        assert len(store.page()['events']) == 2
        assert store.pending()['event']['data']['stream'][0]['text'] == 'x' * 300
        assert len(store.pending()['event']['data']['stream']) == 1
    final = {'method': 'item/completed', 'params': {'threadId': 'child',
             'turnId': 'turn', 'item': {'id': 'item', 'text': 'final snapshot can differ',
                                      'encrypted_content': 'opaque-retained'}}}
    archive.notice(final)
    archive.close()
    with SessionStore(archive.path) as store:
        store.validate()
        events = store.page()['events']
        assert len(events) == 4
        assert events[2]['data']['stream'][0]['text'] == 'x' * 300
        assert native_record(events[3]) == final
        assert store.pending() is None


def test_checker_unknown_delta_fields_and_interrupt_preserve_received_content(tmp_path: Path) -> None:
    """An unknown semantic field breaks compaction; close retains partial output."""
    archive = CodexSessionArchive(tmp_path, 'project', 'checker', 'child')
    archive.seed_fork({'id': 'child', 'forkedFromId': 'parent', 'turns': []})
    delta = {'method': 'item/agentMessage/delta', 'params': {'threadId': 'child',
             'turnId': 'turn', 'itemId': 'item', 'delta': 'a'}}
    archive.notice(delta)
    unknown = {**delta, 'params': {**delta['params'], 'signature': 'ciphertext'}}
    archive.notice(unknown)
    archive.notice(delta)
    archive.close()
    with SessionStore(archive.path) as store:
        store.validate()
        events = store.page()['events']
        assert len(events) == 5
        assert native_record(events[3]) == unknown
        assert events[4]['data']['stream'][0]['text'] == 'a'
        assert events[4]['data']['interrupted'] is True


def test_missing_reference_promotes_once_when_owned_parent_arrives(tmp_path: Path) -> None:
    """Late authorized parent history resolves the gap without replacing child records."""
    state = tmp_path / 'state'
    parent = tmp_path / 'parent.jsonl'
    child = tmp_path / 'child.jsonl'
    parent_records = [
        {'type': 'session_meta', 'ordinal': 0, 'payload': {'id': 'parent'}},
        {'type': 'response_item', 'ordinal': 1, 'payload': {'text': 'original parent'}},
    ]
    write_records(parent, parent_records)
    child_records = [
        {'type': 'session_meta', 'ordinal': 2, 'payload': {
            'id': 'child', 'forked_from_id': 'parent', 'history_base': {
                'thread_id': 'parent', 'end_ordinal_exclusive': 2,
                'end_byte_offset': parent.stat().st_size}}},
        {'type': 'response_item', 'ordinal': 3, 'payload': {'encrypted_content': 'opaque'}},
    ]
    write_records(child, child_records)
    sources = {str(parent):parent, str(child):child}
    archive = CodexSessionArchive(state, 'project', 'child-agent', 'child', source_paths=sources)
    archive.collect(child)
    archive.collect(child)
    with SessionStore(archive.path, readonly=True) as store:
        assert store.next_seq == 0
        assert len(store.pending()['event']['data']['observations']) == 2
    CodexSessionArchive(state, 'project', 'parent-agent', 'parent', source_paths=sources).collect(parent)
    archive.collect(child)
    archive.collect(child)
    with SessionStore(archive.path, readonly=True) as store:
        store.validate()
        events = store.page()['events']
        assert store.header['parentSession'] == 'codex:parent'
        assert store.header['graphtraj']['agentId'] == 'child-agent'
        assert store.pending() is None and store.next_seq == 5
        assert [native_record(item) for item in events if item['type'] != 'session/end-seed'] == parent_records + child_records
