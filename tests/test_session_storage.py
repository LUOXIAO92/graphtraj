"""Runtime-facing Session archival behavior, recovery and public authorized reads."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter

import pytest

from graphtraj.sessions.storage import SessionStore, StreamWriter, session_path
from agent_swarm.sessions.protocol import retain_native


def header(session_id: str = 'canonical') -> dict:
    """Provide a canonical identity distinct from its native provenance."""
    return {'version': 4, 'id': session_id, 'createdAt': 1, 'isSeeded': False,
            'graphtraj': {'version': 1, 'projectId': 'project', 'agentId': 'agent',
                         'taskIds': ['148'], 'native': {'runtime': 'codex',
                         'sessionId': 'native-research@x1', 'locator': 'header'}}}


def assistant(seq: int = 0) -> dict:
    """Supply a valid unfinished message template with unknown source evidence."""
    return {'type': 'assistant/message', 'seq': seq, 'time': 1, 'surfaceOp': 'append',
            'data': {'turn': 0, 'step': 0, 'stream': [], 'message': {
                'id': 'message', 'role': 'assistant', 'source': {
                    'kind': 'model', 'provider': 'test', 'model': 'test', 'opaque': 'preserved'},
                'content': []}}}


def run(text: str, **extra: object) -> dict:
    """Represent a mapped text fragment, without transport timing or snapshots."""
    return {'type': 'graphtraj/text-run', 'requestId': 'request', 'attemptId': 'attempt',
            'messageId': 'message', 'index': 0, 'blockType': 'text', 'text': text, **extra}


def test_events_pages_native_replay_and_attachments(tmp_path: Path) -> None:
    """Portable archives retain opaque/ciphertext facts, dedup and actual bytes."""
    path = session_path(tmp_path, '../canonical')
    with SessionStore.create(path, header('../canonical')) as store:
        attachment = tmp_path / 'runtime-home.bin'
        attachment.write_bytes(b'\x00\xffimage')
        reference = store.copy_attachment(attachment)
        missing = store.copy_attachment(tmp_path / 'missing')
        assert missing['missing']['reason'] == 'FileNotFoundError'
        for seq in range(205):
            event = retain_native('codex', {'ciphertext': 'opaque==', 'unknown': [seq, None],
                                          'attachment': reference, 'missing': missing},
                                  session_id='native', locator=str(seq), seq=seq, time=1)
            assert store.append(event, source='file', position=seq * 10)
            assert not store.append(event, source='file', position=seq * 10)
        assert store.append({**event, 'seq': 205}, source='file', position=3000)
        assert store.next_seq == 205
        first = store.page(limit=200)
        assert len(first['events']) == 200 and first['has_more']
        assert [e['seq'] for e in store.page(first['after'])['events']] == list(range(200, 205))
        store.validate()
        archive = tmp_path / 'export.sqlite3'
        store.export(archive)
    attachment.unlink()
    path.unlink()
    with SessionStore(archive, readonly=True) as store:
        assert store.attachment(reference['sha256']) == b'\x00\xffimage'
        assert store.page()['events'][0]['data']['record']['ciphertext'] == 'opaque=='
        assert store.position('file') == 3000
        with pytest.raises(ValueError, match='unavailable'):
            store.attachment('missing')
        with pytest.raises(ValueError):
            store.page(limit=0)


def test_stream_checkpoints_replay_and_partial_finish(tmp_path: Path) -> None:
    """Restart retains committed text, resumes once and flushes cancelled output."""
    path = tmp_path / 'session.sqlite3'
    with SessionStore.create(path, header()) as store:
        writer = StreamWriter(store, 'rpc', assistant())
        writer.feed(run('received '), 1)
        writer.checkpoint()
        writer.feed(run('not committed'), 2)
        assert store.pending()['event']['data']['stream'][0]['text'] == 'received '
    with SessionStore(path) as store:
        writer = StreamWriter(store, 'rpc')
        assert not writer.feed(run('received '), 1)
        writer.feed(run('replayed'), 2)
        assert writer.finish(interrupted=True) == 0
        assert store.pending() is None
        event = store.page()['events'][0]
        assert event['data']['interrupted'] is True
        assert event['data']['message']['content'] == [{'type': 'text', 'text': 'received replayed'}]
        assert store.position('rpc') == 2
        store.validate()


@pytest.mark.parametrize('reason', ['error', 'aborted', 'stop'])
def test_semantic_boundaries_and_end_reasons(tmp_path: Path, reason: str) -> None:
    """Permission/unknown/usage/finish facts separate otherwise matching runs."""
    with SessionStore.create(tmp_path / 'session.sqlite3', header()) as store:
        writer = StreamWriter(store, 'rpc', assistant())
        facts = [run('a'), {'type': 'permission', 'ciphertext': '==', 'extra': [1, None]},
                 run('b'), run('c', unknown={'future': True}), run('d'),
                 {'type': 'chunk', 'time': 1, 'chunk': {'type': 'usage',
                  'usage': {'inputTokens': 5, 'outputTokens': 4}}}]
        finish = {'type': 'chunk', 'time': 2, 'chunk': {'type': 'finish', 'reason': {'kind': reason}}}
        if reason in {'error', 'aborted'}:
            finish['chunk']['reason']['failure'] = {'message': 'received failure', 'code': reason}
        facts.append(finish)
        for position, record in enumerate(facts):
            writer.feed(record, position)
        writer.finish(interrupted=reason != 'stop')
        stored = store.page()['events'][0]
        assert stored['data']['stream'] == facts
        assert stored['data']['message']['content'][0]['text'] == 'abcd'
        store.validate()


def test_snapshot_prefixes_and_stale_collectors(tmp_path: Path) -> None:
    """Cumulative snapshots keep only suffixes and stale concurrent writers fail."""
    with SessionStore.create(tmp_path / 'session.sqlite3', header()) as store:
        first = StreamWriter(store, 'rpc', assistant())
        stale = StreamWriter(store, 'rpc', assistant())
        for pos, text in enumerate(['a', 'ab', 'ab', 'abc']):
            first.feed(run(text), pos, cumulative=True)
        first.feed(run('abcd', unknown={'probability': -0.5}), 4, cumulative=True)
        first.checkpoint()
        stale.feed(run('wrong'), 8)
        with pytest.raises(ValueError, match='changed'):
            stale.checkpoint()
        with pytest.raises(ValueError, match='changed already'):
            first.feed(run('replacement'), 5, cumulative=True)
        first.finish()
        assert store.page()['events'][0]['data']['stream'] == [run('abc'), run('d', unknown={'probability': -0.5})]


def test_boundaries_cannot_be_appended_over_unfinished_output(tmp_path: Path) -> None:
    """A producer must explicitly retain partial output before its next log event."""
    with SessionStore.create(tmp_path / 'session.sqlite3', header()) as store:
        writer = StreamWriter(store, 'rpc', assistant())
        writer.feed(run('partial'), 0)
        writer.checkpoint()
        boundary = {'type': 'permission', 'seq': 1, 'time': 2, 'data': {'allowed': False}}
        with pytest.raises(ValueError, match='Finalize'):
            store.append(boundary, source='rpc', position=1)
        assert store.position('rpc') == 0
        writer.finish(interrupted=True)
        store.append(boundary, source='rpc', position=1)
        assert [e['type'] for e in store.page()['events']] == ['assistant/message', 'permission']


def test_fork_and_four_runtime_records(tmp_path: Path) -> None:
    """Archive actual 311 fixture values without promoting provenance to parentage."""
    for runtime in ('codex', 'pi', 'dsh', 'claude'):
        example = json.loads((Path(__file__).parents[1] / 'examples/sessions' / f'{runtime}.json').read_text())
        event = retain_native(runtime, example, session_id=runtime, locator='0', seq=0, time=1)
        fork = {**header(runtime), 'parentSession': 'source-fork', 'isSeeded': True}
        with SessionStore.create(tmp_path / f'{runtime}.sqlite3', fork) as store:
            store.append(event, source='history', position=0)
            marker = {'type': 'session/end-seed', 'seq': 1, 'time': 1, 'data': {'inherited': True}}
            store.append(marker, source='history', position=1)
            assert store.header['graphtraj']['agentId'] == 'agent'
            assert store.header['parentSession'] == 'source-fork'
            assert store.page()['events'][0]['data']['record'] == example
            store.validate()


def test_process_exit_after_commit_and_during_uncommitted_transaction(tmp_path: Path) -> None:
    """A real killed process leaves committed draft and rolls back its next write."""
    path = tmp_path / 'crash.sqlite3'
    script = '''
import os, sys
from pathlib import Path
from graphtraj.sessions.storage import SessionStore, StreamWriter
from test_session_storage import header, assistant, run
store = SessionStore.create(Path(sys.argv[1]), header())
writer = StreamWriter(store, 'rpc', assistant())
writer.feed(run('durable partial'), 0)
writer.checkpoint()
store.db.execute('BEGIN IMMEDIATE')
store.db.execute("UPDATE draft SET value='uncommitted invalid JSON'")
os._exit(7)
'''
    environment = {**os.environ, 'PYTHONPATH': os.pathsep.join([
        str(Path(__file__).parents[1] / 'src'), str(Path(__file__).parent)])}
    result = subprocess.run([sys.executable, '-c', script, str(path)], env=environment)
    assert result.returncode == 7
    with SessionStore(path) as store:
        writer = StreamWriter(store, 'rpc')
        assert writer.event['data']['stream'] == [run('durable partial')]
        writer.finish(interrupted=True)
    with SessionStore(path) as store:
        assert store.next_seq == 1 and store.position('rpc') == 0
        store.validate()


def test_public_query_authority_and_independent_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The common operation reads canonical data only for the verified native owner."""
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.execution.runner_status import runtime_caller
    from graphtraj.interfaces.gateway import handle_request
    from graphtraj.interfaces.local_tool import bind
    from test_result_submission import result_project

    runner, _, _ = result_project(tmp_path)
    path = session_path(tmp_path / 'state', 'canonical')
    with SessionStore.create(path, header()) as store:
        store.append({'type': 'unknown/encrypted', 'seq': 0, 'time': 1,
                      'data': {'ciphertext': 'opaque'}}, source='native', position=0)
        store.export(tmp_path / 'portable.sqlite3')
    path.unlink()
    (tmp_path / 'portable.sqlite3').replace(path)
    request = {'action': 'execute', 'feature': 'session_read', 'arguments': {'session_id': 'canonical'}}
    with runtime_caller(runner, 'research@x1'):
        from graphtraj.runtimes.codex.managed_session import native_operation_features
        result = handle_request(request, cwd=tmp_path, allowed_features=native_operation_features())
        assert result.document['events'][0]['data']['ciphertext'] == 'opaque'
        with pytest.raises(ValueError, match='unavailable'):
            handle_request({**request, 'arguments': {'session_id': 'not-collected'}}, cwd=tmp_path)
    with runtime_caller(runner, 'research@x2'), pytest.raises(RunnerError, match='own verified'):
        handle_request(request, cwd=tmp_path)
    monkeypatch.setattr('graphtraj.sessions.query.caller_runtime', lambda: None)
    with runtime_caller(runner, None):
        with pytest.raises(RunnerError):
            handle_request(request, cwd=tmp_path)
    result = bind(tmp_path, desktop_observer=True)(request)
    assert not result.failed and result.document['header']['id'] == 'canonical'
    forbidden = deepcopy(request)
    forbidden['arguments']['path'] = str(path)
    assert bind(tmp_path, desktop_observer=True)(forbidden).failed


def test_public_query_reads_jsonl_with_existing_native_authority(tmp_path: Path) -> None:
    """The same gateway reads the new archive without granting sibling access."""
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.execution.runner_status import runtime_caller
    from graphtraj.interfaces.gateway import handle_request
    from graphtraj.interfaces.agents import swarm_root
    from agent_swarm.sessions.archive import SessionArchive
    from test_result_submission import result_project

    runner, _, _ = result_project(tmp_path)
    identity = 'codex:native-research@x1'
    archive = SessionArchive(swarm_root(tmp_path), save_normalized_sessions=True)
    archive.map_session(header(identity))
    archive.collect(identity, [retain_native('codex', {'ciphertext': 'opaque'},
        session_id='native-research@x1', locator='byte:0', seq=0, time=1)], source='rollout', position=1)
    request = {'action': 'execute', 'feature': 'session_read', 'arguments': {'session_id': identity}}
    with runtime_caller(runner, 'research@x1'):
        result = handle_request(request, cwd=tmp_path)
        assert result.document['header']['id'] == identity
        assert result.document['events'][0]['data']['record']['ciphertext'] == 'opaque'
    with runtime_caller(runner, 'research@x2'), pytest.raises(RunnerError, match='own verified'):
        handle_request(request, cwd=tmp_path)


def test_public_query_pages_migrated_evidence_without_claiming_native_order(tmp_path: Path) -> None:
    """Old evidence respects the selected page size and keeps its own cursor."""
    from agent_swarm.sessions.migration import import_sqlite
    from graphtraj.execution.runner_status import runtime_caller
    from graphtraj.interfaces.gateway import handle_request
    from graphtraj.interfaces.agents import swarm_root
    from test_result_submission import result_project

    runner, _, _ = result_project(tmp_path)
    source = session_path(tmp_path / 'state', 'canonical')
    with SessionStore.create(source, header()) as store:
        for seq in range(3):
            store.append({'type': 'unknown/encrypted', 'seq': seq, 'time': 1,
                          'data': {'ciphertext': str(seq)}}, source='old-notification', position=seq)
    import_sqlite(source, swarm_root(tmp_path))
    request = {'action': 'execute', 'feature': 'session_read',
               'arguments': {'session_id': 'canonical', 'limit': 1}}
    with runtime_caller(runner, 'research@x1'):
        first = handle_request(request, cwd=tmp_path).document
        assert first['events'] == []
        assert [event['seq'] for event in first['legacy']['events']] == [0]
        assert first['legacy']['has_more'] and not first['legacy']['native_order_verified']
        request['arguments']['after'] = first['legacy']['after']
        second = handle_request(request, cwd=tmp_path).document
        assert [event['seq'] for event in second['legacy']['events']] == [1]


def test_fragment_size_equivalence_and_measurements(tmp_path: Path) -> None:
    """Long output retains equal text, semantic boundaries, usage and probabilities."""
    output = 'abcdefghij界🙂' * 2000
    measurements = []
    histories = []
    for chunk_size, cumulative in ((1, False), (1024, False), (1, True)):
        path = tmp_path / f'{chunk_size}-{cumulative}.sqlite3'
        started = perf_counter()
        with SessionStore.create(path, header()) as store:
            writer = StreamWriter(store, 'rpc', assistant())
            position = 0
            for index in range(0, len(output), chunk_size):
                text = output[:index + chunk_size] if cumulative else output[index:index + chunk_size]
                writer.feed(run(text), position, cumulative=cumulative)
                position += 1
            usage = {'type': 'chunk', 'time': 2, 'chunk': {'type': 'usage',
                     'usage': {'inputTokens': 30, 'outputTokens': 4000, 'cacheReadTokens': 10}}}
            writer.feed(usage, position)
            probability = {'type': 'graphtraj/logprobs', 'seq': 1, 'time': 3, 'data': {
                'target': {'eventSeq': 0, 'requestId': 'request', 'attemptId': 'attempt',
                           'model': 'test', 'tokenizer': 'test'},
                'source': {'kind': 'native', 'producer': 'fixture', 'evidence': 'measured provider value'},
                'distribution': 'raw', 'semantics': 'natural log before sampling',
                'tokens': [{'position': 0, 'text': 'a', 'logprob': -0.5,
                            'span': {'blockIndex': 0, 'start': 0, 'end': 1}}]}}
            writer.finish(following=[probability])
            store.validate()
            write_time = perf_counter() - started
            started = perf_counter()
            events = store.page()['events']
            read_time = perf_counter() - started
            assert events[0]['data']['message']['content'][0]['text'] == output
            histories.append(events)
            measurements.append({'chunk_characters': chunk_size, 'cumulative': cumulative, 'input_fragments': position,
                                 'events': len(events), 'stream_records': len(events[0]['data']['stream']),
                                 'archive_bytes': path.stat().st_size,
                                 'json_bytes': len(json.dumps(events, ensure_ascii=False).encode()),
                                 'write_seconds': round(write_time, 6), 'read_seconds': round(read_time, 6)})
    assert histories[0] == histories[1] == histories[2]
    assert measurements[0]['stream_records'] == 2
    assert measurements[0]['archive_bytes'] <= measurements[1]['archive_bytes'] * 2
    print('\nSESSION_STORAGE_MEASUREMENTS=' + json.dumps(measurements))


def test_graph_query_does_not_open_session_archives(tmp_path: Path) -> None:
    """An unavailable Session body cannot prevent the lightweight graph query."""
    from graphtraj.interfaces.gateway import handle_request
    from test_result_submission import result_project

    result_project(tmp_path)
    path = session_path(tmp_path / 'state', 'canonical')
    path.parent.mkdir(parents=True)
    path.write_bytes(b'not a readable Session database')
    result = handle_request({'action': 'execute', 'feature': 'task_graph', 'arguments': {}}, cwd=tmp_path)
    assert not result.failed and result.document['tasks']


def test_one_native_record_commits_all_its_semantic_events(tmp_path: Path) -> None:
    """Failed batch mapping cannot advance the native cursor past missing evidence."""
    with SessionStore.create(tmp_path / 'session.sqlite3', header()) as store:
        events = [{'type': 'unknown', 'seq': seq, 'time': 1, 'data': {'value': seq}}
                  for seq in range(2)]
        with pytest.raises(ValueError):
            store.append_many([events[0], {**events[1], 'seq': 3}], source='native', position=100)
        assert store.next_seq == 0 and store.position('native') == -1
        assert store.append_many(events, source='native', position=100)
        assert not store.append_many(events, source='native', position=100)
        assert store.page()['events'] == events
        writer = StreamWriter(store, 'rpc', assistant(2))
        writer.feed(run('partial with boundary'), 0)
        writer.checkpoint()
        boundary = {'type': 'permission', 'seq': 3, 'time': 2, 'data': {'denied': True}}
        with pytest.raises(ValueError):
            writer.finish(interrupted=True, following=[{**boundary, 'seq': 4}])
        assert store.next_seq == 2 and store.pending() is not None
        writer.finish(interrupted=True, following=[boundary])
        assert store.next_seq == 4 and store.pending() is None


def test_pending_initial_ancestry_is_portable_atomic_and_one_way(tmp_path: Path) -> None:
    """Early hooks stay outside parent history; failed confirmation changes nothing."""
    path = tmp_path / 'initial.sqlite3'
    original = header()
    hook = retain_native('codex', {'hook': 'start'}, session_id='native', locator='hook', seq=0, time=1)
    parent = retain_native('codex', {'inherited': 'actual'}, session_id='native', locator='parent', seq=0, time=2)
    with SessionStore.create(path, original) as store:
        assert store.stage_initial_observation(hook, source='hooks', position=0)
        assert not store.stage_initial_observation(hook, source='hooks', position=0)
        assert store.stage_initial_observation(parent, source='file', position=12)
        assert store.page()['events'] == []
        store.export(tmp_path / 'export.sqlite3')
    path.unlink()
    with SessionStore(tmp_path / 'export.sqlite3') as store:
        before = store.pending()
        with pytest.raises(ValueError):
            store.finish_initial_collection(parent_session='parent', inherited=[('file', 99)])
        assert store.header == original and store.pending() == before
        assert store.position('file') == 12 and store.next_seq == 0
        store.finish_initial_collection(parent_session='parent', inherited=[('file', 12)])
        events = store.page()['events']
        assert events[0]['data']['record'] == {'inherited': 'actual'}
        assert events[1]['type'] == 'session/end-seed'
        assert events[2]['data']['record'] == {'hook': 'start'}
        assert events[2]['graphtraj']['initialHeader'] == original
        assert store.header['graphtraj'] == original['graphtraj']
        assert store.header['parentSession'] == 'parent' and store.pending() is None
        store.validate()
        with pytest.raises(ValueError, match='already started'):
            store.stage_initial_observation(hook, source='hooks', position=1)
        with pytest.raises(ValueError, match='Only pending'):
            store.finish_initial_collection(parent_session='other', inherited=[('file', 12)])
        assert store.page()['events'] == events


def test_initial_pending_cannot_be_validated_as_canonical_history() -> None:
    """Ordinary protocol consumers must not treat undecided observations as history."""
    from agent_swarm.sessions.protocol import INITIAL_COLLECTION_TYPE, validate_session

    event = {'type': INITIAL_COLLECTION_TYPE, 'seq': 0, 'time': 1, 'data': {}}
    with pytest.raises(ValueError, match='pending-collection'):
        validate_session(header(), [event])


def test_initial_batch_cursors_are_atomic_and_idempotent(tmp_path: Path) -> None:
    """Interrupted bulk ingestion replays without losing or duplicating raw records."""
    event = retain_native('codex', {'encrypted_content': 'opaque'}, session_id='native',
                          locator='byte:0', seq=0, time=1)
    observations = [{'event': event, 'source': 'rollout', 'position': i} for i in range(300)]
    path = tmp_path / 'bulk.sqlite3'
    with SessionStore.create(path, header()) as store:
        assert store.stage_initial_observations(observations[:256]) == 256
        before = store.pending()
        with pytest.raises((ValueError, KeyError)):
            store.stage_initial_observations(observations[256:] + [
                {'event': {}, 'source': 'rollout', 'position': 300}])
        assert store.position('rollout') == 255 and store.pending() == before
    with SessionStore(path) as store:
        assert store.stage_initial_observations(observations) == 44
        assert store.stage_initial_observations(observations) == 0
        assert len(store.pending()['event']['data']['observations']) == 300
        assert store.position('rollout') == 299 and store.next_seq == 0
