"""Codex hook input failures name their source and do not stop a user's turn."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_swarm import write_config
from graphtraj.interfaces.agents import ConfiguredSessionArchive
from agent_swarm.sessions.codex import CodexJsonlArchive
from graphtraj.runtimes.codex.session_entry import session_record
from graphtraj.runtimes.codex.stop_hook import main as stop_hook
from agent_swarm.sessions.archive import JsonlSessionStore, archive_path


def test_empty_stdin_names_hook_stdin_and_keeps_stop_error() -> None:
    """An empty native event is a visible Stop error naming stdin, never a bare decode error."""
    reply = CliRunner().invoke(stop_hook, [], input='')
    assert reply.exit_code == 0, reply.output
    result = json.loads(reply.output)
    assert result['continue'] is False
    assert 'Codex hook stdin (0 characters)' in result['stopReason']
    assert 'Completion Check · error' in result['stopReason']


def test_rollout_parse_failure_names_file_and_offset(tmp_path: Path) -> None:
    """An invalid native record identifies the rollout and byte offset; a growing tail is ignored."""
    rollout = tmp_path / 'rollout.jsonl'
    meta = json.dumps({'type': 'session_meta', 'payload': {'id': 'n', 'source': 'cli'}}) + '\n'
    rollout.write_text(meta + '{"type":"turn_con')
    assert session_record(rollout)[0]['id'] == 'n'
    rollout.write_text(meta + 'not json\n')
    with pytest.raises(ValueError, match=f'Codex rollout {rollout} has no valid JSON record at byte {len(meta)}'):
        session_record(rollout)


def test_fork_activation_inside_a_record_starts_at_next_line(tmp_path: Path) -> None:
    """A size observed mid-append is aligned to the next native record, not parsed mid-line."""
    root = tmp_path / 'swarm'
    write_config(root, save_normalized_sessions=True, backfill_history=False)
    rollout = tmp_path / 'fork.jsonl'
    records = [
        {'type': 'session_meta', 'payload': {'id': 'fork', 'forked_from_id': 'parent', 'source': 'cli'}},
        {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                                              'content': [{'type': 'input_text', 'text': 'old'}]}},
        {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                                              'content': [{'type': 'input_text', 'text': 'new'}]}},
    ]
    lines = [json.dumps(record) + '\n' for record in records]
    rollout.write_text(''.join(lines))
    collector = CodexJsonlArchive(ConfiguredSessionArchive(root), 'main', 'fork', rollout)
    collector.activation = len(lines[0]) + 5
    collector.collect(rollout)
    store = JsonlSessionStore(archive_path(root, 'codex:fork'))
    assert store.position('fork-records') == rollout.stat().st_size


def test_cursor_from_one_physical_rollout_is_not_read_in_another(tmp_path: Path) -> None:
    """A second physical rollout of the same Session is never read from the first file's byte cursor."""
    root = tmp_path / 'swarm'
    write_config(root, save_normalized_sessions=True, backfill_history=False)
    meta = {'type': 'session_meta', 'payload': {'id': 's', 'source': 'cli'}}

    def user(text: str) -> dict:
        return {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                                                     'content': [{'type': 'input_text', 'text': text}]}}

    first, second = tmp_path / 'A.jsonl', tmp_path / 'B.jsonl'
    first.write_text(''.join(json.dumps(record) + '\n' for record in [meta, user('first')]))
    second.write_text(''.join(json.dumps(record) + '\n' for record in [
        meta, {'type': 'compacted', 'payload': {'message': 'summary ' * 30}}, user('after'),
        # Codex 0.163 host-delivered output: no originating call_id.
        {'type': 'response_item', 'payload': {'type': 'function_call_output', 'id': 'fco', 'name': 'graphtraj',
                                              'output': 'notice'}}]))
    for rollout in (first, second):
        collector = CodexJsonlArchive(ConfiguredSessionArchive(root), 'main', 's', rollout)
        collector.activation = 0
        collector.collect(rollout)

    # Each physical file keeps its own cursor; both files' records stay distinct.
    from agent_swarm.sessions.protocol import native_record

    store = JsonlSessionStore(archive_path(root, 'codex:s'))
    assert store.position('rollout') == first.stat().st_size
    assert store.position('B.jsonl:rollout') == second.stat().st_size
    records = [native_record(event) for event in store.page()['events']]
    assert [record['payload'].get('content', [{}])[0].get('text') for record in records
            if record['type'] == 'response_item'] == ['first', 'after', None]
    assert records[-1]['payload']['output'] == 'notice'
