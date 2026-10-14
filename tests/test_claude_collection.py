"""Claude collection through native entry and the canonical public archive query."""
import json
from pathlib import Path

from click.testing import CliRunner
import pytest

from graphtraj.interfaces.local_tool import bind
from graphtraj.runtimes.native_entry import main
from graphtraj.runtimes.claude.collection import open_archive, StreamCollector
from graphtraj.sessions.storage import SessionStore, session_path
from test_result_submission import result_project


def hook(root: Path, event: dict, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Deliver an official hook shape through the public native entry command."""
    monkeypatch.chdir(root)
    result = CliRunner().invoke(main, ['claude'], input=json.dumps(event))
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def query(root: Path, identity: str) -> dict:
    """Use the public project observer query, not a display projection."""
    result = bind(root, desktop_observer=True)({
        'action': 'execute', 'feature': 'session_read', 'arguments': {'session_id': identity}})
    assert not result.failed, result.document
    return result.document


def test_native_hook_resume_child_and_portable_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Parent and child sources stay separate; replay and missing source preserve history."""
    result_project(tmp_path)
    monkeypatch.setattr('graphtraj.sessions.query.caller_runtime', lambda: None)
    parent = tmp_path / 'parent.jsonl'
    child = tmp_path / 'child.jsonl'
    message = {'type': 'assistant', 'sessionId': 'parent', 'uuid': 'm',
               'message': {'content': [{'type': 'thinking', 'thinking': 'visible', 'signature': 'sig'},
                                       {'type': 'redacted_thinking', 'data': 'ciphertext'}],
                           'usage': {'input_tokens': 3, 'output_tokens': 2}}, 'future': {'keep': None}}
    parent.write_text(json.dumps(message) + '\n')
    child_message = {**message, 'agentId': 'child', 'isSidechain': True, 'uuid': 'child-m'}
    child.write_text(json.dumps(child_message) + '\n')
    event = {'hook_event_name': 'SessionStart', 'source': 'startup', 'session_id': 'parent',
             'cwd': str(tmp_path), 'transcript_path': str(parent)}
    first = hook(tmp_path, event, monkeypatch)
    assert first['records'] == 1
    assert hook(tmp_path, {**event, 'source': 'resume'}, monkeypatch)['records'] == 0
    child_event = {**event, 'hook_event_name': 'SubagentStop', 'agent_id': 'child',
                   'agent_type': 'plugin:checker', 'agent_transcript_path': str(child)}
    collected = hook(tmp_path, child_event, monkeypatch)
    assert collected['source'] == 'child' and collected['session_id'] != first['session_id']
    assert 'error' in hook(tmp_path, {**child_event, 'agent_transcript_path': str(parent)}, monkeypatch)
    data = query(tmp_path, collected['session_id'])
    assert 'parentSession' not in data['header']
    assert data['header']['origin'] == 'subagent'
    assert data['events'][0]['data']['record'] == child_message
    parent.unlink()
    child.unlink()
    archived = query(tmp_path, first['session_id'])
    assert archived['events'][0]['data']['record'] == message
    assert len([e for e in archived['events'] if e['data']['record'].get('uuid') == 'm']) == 1
    assert hook(tmp_path, event, monkeypatch)['missing']['reason']


def test_transcript_incomplete_tail_and_wrong_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Partial source records replay; a child transcript cannot become a root source."""
    result_project(tmp_path)
    monkeypatch.setattr('graphtraj.sessions.query.caller_runtime', lambda: None)
    path = tmp_path / 'native.jsonl'
    line = json.dumps({'type': 'user', 'sessionId': 's', 'message': {'content': 'hello'}})
    path.write_text(line)
    event = {'hook_event_name': 'Stop', 'session_id': 's', 'transcript_path': str(path), 'cwd': str(tmp_path)}
    assert hook(tmp_path, event, monkeypatch)['records'] == 0
    path.write_text(line + '\n')
    assert hook(tmp_path, event, monkeypatch)['records'] == 1
    with path.open('a') as stream:
        stream.write(json.dumps({'sessionId': 's', 'agentId': 'child', 'isSidechain': True}) + '\n')
    assert 'error' in hook(tmp_path, event, monkeypatch)


def test_stream_fragment_compaction_unknown_boundaries_and_interrupt(tmp_path: Path) -> None:
    """Character fragmentation preserves content with bounded permanent records."""
    text = 'hello界' * 1500
    sizes = []
    for chunk_size in (1, 1000):
        state = tmp_path / str(chunk_size)
        with open_archive(state, tmp_path, 's', 'managed', source='managed') as store:
            collector = StreamCollector(store, 'execution', 'model', 'anthropic')
            position = 0
            for offset in range(0, len(text), chunk_size):
                position += 1
                collector.accept({'type': 'stream_event', 'session_id': 's', 'event': {
                    'type': 'content_block_delta', 'index': 0,
                    'delta': {'type': 'text_delta', 'text': text[offset:offset + chunk_size]}}}, position)
            position += 1
            unknown = {'type': 'stream_event', 'event': {'type': 'future', 'signature': 'untouched'}}
            collector.accept(unknown, position)
            position += 1
            collector.accept({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': text}],
                              'usage': {'input_tokens': 2, 'output_tokens': 4}}}, position)
            collector.close()
            store.validate()
            events = store.page()['events']
            assert len(events) == 1
            assert events[0]['data']['message']['content'][0]['text'] == text
            assert events[0]['data']['stream'][0]['text'] == text
            assert events[0]['data']['stream'][1]['record'] == unknown
            sizes.append(len(json.dumps(events)))
        with SessionStore(session_path(state, 'claude:s')) as store:
            collector = StreamCollector(store, 'next-execution', 'model', 'anthropic')
            collector.accept({'type': 'stream_event', 'event': {'type': 'content_block_delta', 'index': 1,
                              'delta': {'type': 'thinking_delta', 'thinking': 'partial'}}}, 1)
            collector.close()
            assert store.page()['events'][-1]['data']['interrupted']
            store.validate()
    assert abs(sizes[0] - sizes[1]) < 100


def test_true_fork_retains_prefix_without_agent_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only explicit native fork provenance creates parentSession and seed cut."""
    result_project(tmp_path)
    monkeypatch.setattr('graphtraj.sessions.query.caller_runtime', lambda: None)
    path = tmp_path / 'fork.jsonl'
    inherited = {'type': 'user', 'sessionId': 'fork', 'uuid': 'new-message',
                 'forkedFrom': {'sessionId': 'original', 'messageUuid': 'old-message'},
                 'message': {'content': 'inherited'}}
    path.write_text(json.dumps(inherited) + '\n')
    event = {'hook_event_name': 'SessionStart', 'source': 'fork', 'session_id': 'fork',
             'transcript_path': str(path), 'cwd': str(tmp_path)}
    result = hook(tmp_path, event, monkeypatch)
    data = query(tmp_path, result['session_id'])
    assert data['header']['parentSession'] == 'claude:original'
    assert data['header']['isSeeded']
    assert data['events'][1]['type'] == 'session/end-seed'
    assert data['events'][1]['data']['inherited'] is True
    assert hook(tmp_path, {**event, 'source': 'resume'}, monkeypatch)['records'] == 0
    data = query(tmp_path, result['session_id'])
    assert len([e for e in data['events'] if e['type'] == 'session/end-seed']) == 1


def test_received_stream_checkpoint_replay_and_atomic_boundary(tmp_path: Path) -> None:
    """A restarted collector skips the committed prefix and preserves later failure."""
    delta = {'type': 'stream_event', 'event': {'type': 'content_block_delta', 'index': 0,
             'delta': {'type': 'text_delta', 'text': 'first'}}}
    with open_archive(tmp_path / 'state', tmp_path, 'stream', 'managed', source='managed') as store:
        collector = StreamCollector(store, 'execution', 'model', 'anthropic')
        collector.accept(delta, 1)
        assert store.position('execution') == 1
        assert store.pending()['event']['data']['stream'][0]['text'] == 'first'
    with SessionStore(session_path(tmp_path / 'state', 'claude:stream')) as store:
        collector = StreamCollector(store, 'execution', 'model', 'anthropic')
        collector.accept(delta, 1)
        collector.accept({**delta, 'event': {**delta['event'], 'delta': {'type': 'text_delta', 'text': ' second'}}}, 2)
        failure = {'type': 'result', 'is_error': True, 'errors': ['controlled failure'],
                   'usage': {'input_tokens': 2, 'cache_read_input_tokens': 4, 'output_tokens': 3}}
        collector.accept(failure, 3)
        page = store.page()['events']
        assert len(page) == 2 and store.pending() is None and store.position('execution') == 3
        assert page[0]['data']['stream'][0]['text'] == 'first second'
        assert page[0]['data']['interrupted']
        assert page[1]['data']['record'] == failure
        store.validate()


def test_attachment_bytes_and_child_query_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A parent native ID is provenance, not authorization to read a native child."""
    import yaml
    from graphtraj.execution.runner_status import runtime_caller
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.interfaces.gateway import handle_request

    runner, _, _ = result_project(tmp_path)
    path = tmp_path / 'child.jsonl'
    record = {'sessionId': 'native', 'agentId': 'child', 'type': 'user', 'message': {'content': [
        {'type': 'image', 'source': {'type': 'base64', 'data': 'AP8='}},
        {'type': 'document', 'source': {'type': 'url', 'url': 'https://example.invalid/file'}},
    ]}}
    path.write_text(json.dumps(record) + '\n')
    event = {'hook_event_name': 'SubagentStop', 'session_id': 'native', 'agent_id': 'child',
             'agent_transcript_path': str(path), 'transcript_path': str(tmp_path / 'parent.jsonl'),
             'cwd': str(tmp_path)}
    result = hook(tmp_path, event, monkeypatch)
    with SessionStore(session_path(tmp_path / 'state', result['session_id'])) as store:
        item = store.page()['events'][0]
        reference = item['graphtraj']['attachments'][0]
        assert store.attachment(reference['sha256']) == b'\x00\xff'
        assert any(m['path'] == '/message/content/1/source' for m in item['graphtraj']['missing'])
        assert store.header['graphtraj']['native']['sessionId'] == 'native'
    mapping_path = runner / 'sessions/research@x1/mapping.yml'
    mapping = yaml.safe_load(mapping_path.read_text())
    mapping.update(runtime='claude', session='native')
    mapping_path.write_text(yaml.safe_dump(mapping))
    with runtime_caller(runner, 'research@x1'), pytest.raises(RunnerError, match='own verified'):
        handle_request({'action': 'execute', 'feature': 'session_read',
                        'arguments': {'session_id': result['session_id']}}, cwd=tmp_path)
