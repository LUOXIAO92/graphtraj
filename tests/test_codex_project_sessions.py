"""Native Codex boundaries retain linked project Sessions and current reads."""

import json
from pathlib import Path

import pytest

from agent_swarm import write_config
from agent_swarm.sessions.archive import JsonlSessionStore, SessionArchive, archive_path
from agent_swarm.sessions.codex import CodexJsonlArchive
from graphtraj.interfaces.agents import ConfiguredSessionArchive, swarm_root
from graphtraj.interfaces.gateway import handle_request
from graphtraj.execution.runner_status import runtime_caller
from test_result_submission import result_project


def message(text: str) -> dict:
    """Supply an ordinary native user message with observable content."""
    return {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': text}]}


def write(path: Path, records: list[dict]) -> None:
    """Write a controlled native input, preserving its supplied order."""
    path.write_text(''.join(json.dumps(record) + '\n' for record in records))


@pytest.mark.parametrize('agent', ['main', 'research@x1'])
def test_boundaries_keep_identity_history_and_current_public_reads(tmp_path: Path, agent: str) -> None:
    """Each compaction/rollback creates one record; notifications and turns do not."""
    runner, _, _ = result_project(tmp_path)
    root = swarm_root(tmp_path)
    write_config(root, save_normalized_sessions=True, backfill_history=True)
    source = tmp_path / 'first.jsonl'
    records = [
        {'type': 'session_meta', 'payload': {'id': 'native-research@x1', 'source': 'cli'}},
        {'type': 'response_item', 'payload': message('before')},
    ]
    ids = []
    snapshots = {}

    def collect(path: Path) -> JsonlSessionStore:
        """Restart the hook collector, as separate native invocations would."""
        CodexJsonlArchive(ConfiguredSessionArchive(root), agent, 'native-research@x1', path).collect(path)
        identity = SessionArchive(root).native_id('codex', 'native-research@x1')
        return JsonlSessionStore(archive_path(root, identity))

    write(source, records)
    store = collect(source)
    ids.append(store.header['id'])
    for index in range(2):
        snapshots[store.path] = store.path.read_bytes()
        records.append({'type': 'compacted', 'payload': {
            'replacement_history': [message(f'summary-{index}')],
            'window_number': index, 'resume_metadata': {},
        }})
        write(source, records)
        store = collect(source)
        assert store.header['graphtraj']['previousSession'] == ids[-1]
        assert store.header['graphtraj']['native']['sessionId'] == 'native-research@x1'
        assert store.header['graphtraj']['agentId'] == agent
        assert 'parentSession' not in store.header  # Continuation is not a native fork.
        assert store.messages()[0]['content'][0]['text'] == f'summary-{index}'
        ids.append(store.header['id'])
        assert collect(source).header == store.header

    records.append({'type': 'response_item', 'payload': message('follow-up')})
    write(source, records)
    assert collect(source).header['id'] == ids[-1]
    records.append({'type': 'event_msg', 'payload': {'type': 'thread_rolled_back', 'num_turns': 1}})
    write(source, records)
    store = collect(source)
    assert store.header['graphtraj']['previousSession'] == ids[-1]
    assert store.messages()[0]['content'][0]['text'] == 'summary-1'
    ids.append(store.header['id'])
    assert len(set(ids)) == 4

    moved = tmp_path / 'second.jsonl'
    write(moved, [records[0], {'type': 'response_item', 'payload': message('continued')}])
    store = collect(moved)
    assert store.header['graphtraj']['previousSession'] == ids[-1]
    ids.append(store.header['id'])
    assert store.messages()[0]['content'][0]['text'] == 'continued'
    assert collect(moved).header == store.header
    assert collect(source).header == store.header  # A late old-file callback does not replace current.
    assert len(list((root / 'sessions').glob('*/session.jsonl'))) == 5
    for path, before in snapshots.items():
        assert path.read_bytes() == before

    # Native reads select current; explicit project IDs retain their historical meaning.
    request = {'action': 'execute', 'feature': 'session_read', 'arguments': {'session_id': 'native-research@x1'}}
    with runtime_caller(runner, 'research@x1'):
        current = handle_request(request, cwd=tmp_path).document
        previous = handle_request({**request, 'arguments': {'session_id': ids[0]}}, cwd=tmp_path).document
    assert current['header']['id'] == ids[-1]
    assert previous['header']['id'] == ids[0]
    assert previous['events'][-1]['data']['content'][0]['text'] == 'before'
    assert source.read_text() == ''.join(json.dumps(record) + '\n' for record in records)


def test_a_genuinely_new_native_session_has_its_own_project_record(tmp_path: Path) -> None:
    """A new native identity is neither a duplicate nor a continuation of another."""
    archive = SessionArchive(tmp_path / 'swarm', save_normalized_sessions=True, backfill_history=True)
    for native in ('one', 'two'):
        source = tmp_path / f'{native}.jsonl'
        write(source, [{'type': 'session_meta', 'payload': {'id': native, 'source': 'cli'}}])
        CodexJsonlArchive(archive, 'main', native, source).collect(source)
    first, second = [archive.native_header('codex', native) for native in ('one', 'two')]
    assert first['id'] != second['id']
    assert 'previousSession' not in second['graphtraj']


def test_backfill_resolves_excluded_history_across_retained_boundaries(tmp_path: Path) -> None:
    """Saving policy remains effective when compaction follows an excluded prefix."""
    root = tmp_path / 'swarm'
    write_config(root, save_normalized_sessions=True, backfill_history=False)
    source = tmp_path / 'native.jsonl'
    records = [
        {'type': 'session_meta', 'payload': {'id': 'native', 'source': 'cli'}},
        {'type': 'response_item', 'payload': message('old')},
    ]
    write(source, records)
    collector = CodexJsonlArchive(ConfiguredSessionArchive(root), 'main', 'native', source)
    records.append({'type': 'compacted', 'payload': {'replacement_history': [message('summary')]}})
    write(source, records)
    collector.collect(source)
    current = archive_path(root, collector.id)
    original = archive_path(root, 'codex:native')
    for path in (current, original):
        with pytest.raises(ValueError, match='incomplete'):
            JsonlSessionStore(path).messages()
    ids = {path.parent.name for path in (root / 'sessions').glob('*/session.jsonl')}
    write_config(root, backfill_history=True)
    collector.collect(source)
    assert not JsonlSessionStore(current).pending()
    assert JsonlSessionStore(current).messages()[0]['content'][0]['text'] == 'summary'
    assert JsonlSessionStore(original).messages()[0]['content'][0]['text'] == 'old'
    assert {path.parent.name for path in (root / 'sessions').glob('*/session.jsonl')} == ids


def test_compaction_preserves_fork_ancestry_and_agent_ownership(tmp_path: Path) -> None:
    """Project continuation keeps native fork provenance separate from its predecessor."""
    root = tmp_path / 'swarm'
    archive = SessionArchive(root, save_normalized_sessions=True, backfill_history=True)
    source = tmp_path / 'fork.jsonl'
    records = [
        {'type': 'session_meta', 'payload': {'id': 'child', 'forked_from_id': 'parent'}},
        {'type': 'response_item', 'payload': message('inherited')},
        {'type': 'event_msg', 'payload': {'type': 'thread_settings_applied', 'thread_id': 'child'}},
        {'type': 'response_item', 'payload': message('local')},
        {'type': 'compacted', 'payload': {'replacement_history': [message('summary')]}},
    ]
    write(source, records)
    collector = CodexJsonlArchive(archive, 'actual-child', 'child', source)
    collector.collect(source)
    store = JsonlSessionStore(archive_path(root, collector.id))
    assert store.header['parentSession'] == 'codex:parent'
    assert store.header['graphtraj']['previousSession'] == 'codex:child'
    assert store.header['graphtraj']['agentId'] == 'actual-child'
    assert store.header['graphtraj']['native']['sessionId'] == 'child'
    assert store.messages()[0]['content'][0]['text'] == 'summary'
    assert any(event['type'] == 'session/end-seed' for event in store.page()['events'])
