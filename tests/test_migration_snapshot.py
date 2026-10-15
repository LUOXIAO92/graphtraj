"""Public offline copies and recovery without original Runtime source files."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

import yaml

from conftest import InstalledCommands, run_process
from test_task_migration import _ticket_project, _snapshot, _migrate
from graphtraj.sessions.storage import SessionStore, session_path


def _source(root: Path, native: Path) -> tuple[Path, bytes]:
    """Create one associated external Codex source and one retained Trace link."""
    root.mkdir()
    _ticket_project(root)
    content = (json.dumps({'type': 'session_meta', 'payload': {'id': 'owned'}}) + '\n'
               + json.dumps({'type': 'response_item', 'payload': {
                   'encrypted_content': 'ciphertext', 'text': str(root) + '/ticket.md'}}) + '\n').encode()
    native.write_bytes(content)
    trace = root / '.graphtraj/state/tickets/2-child/teams/1/traces/member/events.jsonl'
    trace.parent.mkdir(parents=True)
    trace.symlink_to(native)
    record = root / '.graphtraj/runner/sessions/member/mapping.yml'
    record.parent.mkdir(parents=True)
    record.write_text(yaml.safe_dump({'runtime': 'codex', 'session': 'owned', 'alias': 'member',
                                     'ticket_id': '2', 'trace_file': str(trace)}))
    (record.parent / 'session.yml').write_text(yaml.safe_dump({'session': 'owned', 'rollout_path': str(native)}))
    return trace, content


def test_snapshot_migrates_without_original_project_or_sources(
    installed_commands: InstalledCommands, tmp_path: Path,
) -> None:
    """A different-directory rehearsal keeps provenance while using only copied bytes."""
    origin = tmp_path / 'origin'
    external = tmp_path / 'native.jsonl'
    trace, content = _source(origin, external)
    unrelated = tmp_path / 'unrelated.txt'
    unrelated.write_text('Do not copy this unrelated file.\n')
    foreign = trace.parent / 'unrelated-link'
    foreign.symlink_to(unrelated)
    definition_link = origin / '.graphtraj/state/tickets/2-child/definition-link'
    definition_link.symlink_to(origin / '.graphtraj/state/tickets/1-summary/ticket.md')
    before = _snapshot(origin)
    copy = tmp_path / 'rehearsal'
    result = run_process([str(installed_commands.product), 'migrate-tickets', '--snapshot', str(copy)], cwd=origin)
    assert result.returncode == 0, result.stderr
    assert _snapshot(origin) == before
    assert not (copy / '.graphtraj/runner').exists()
    assert (copy / '.graphtraj/migration-runner/sessions/member/mapping.yml').is_file()
    for path in copy.rglob('*'):
        if path.is_symlink():
            assert path.resolve().is_relative_to(copy), path
    assert yaml.safe_load(result.stdout)['missing_links']
    # Removing both originals makes any accidental fallback observable.
    shutil.rmtree(origin)
    external.unlink()
    unrelated.unlink()
    preview = run_process([str(installed_commands.product), 'migrate-tickets', '--preview'], cwd=copy)
    assert preview.returncode == 0, preview.stderr
    assert yaml.safe_load(preview.stdout)['project'] == str(origin)
    result = _migrate(installed_commands, copy)
    assert result.returncode == 0, result.stderr
    state = copy / '.graphtraj/state'
    with SessionStore(session_path(state, 'codex:owned'), readonly=True) as store:
        assert store.header['graphtraj']['projectId'] == str(origin)
        assert store.header['graphtraj']['agentId'] == 'member'
        assert store.header['graphtraj']['native']['sourcePath'] == str(external)
        assert store.page()['events'][1]['data']['record']['payload']['text'] == str(origin) + '/ticket.md'
        item = next(item for item in yaml.safe_load(result.stdout)['sessions'] if item.get('session') == 'owned')
        assert store.attachment(item['original_bytes']['sha256']) == content
    graph = run_process([str(installed_commands.product), 'task', 'graph', '--view', 'full'], cwd=copy)
    assert graph.returncode == 0, graph.stderr
    assert len(yaml.safe_load(graph.stdout)['tasks']) == 2
    assert (state / 'tasks/2-child/definition-link').read_bytes() == (state / 'tasks/1-summary/task.md').read_bytes()
    backup = yaml.safe_load(result.stdout)['backup']
    restored = run_process([str(installed_commands.product), 'migrate-tickets', '--restore', backup], cwd=copy)
    assert restored.returncode == 0, restored.stderr
    assert _migrate(installed_commands, copy).returncode == 0
    assert not origin.exists() and not external.exists()


def test_restore_has_native_bytes_after_original_source_is_removed(
    installed_commands: InstalledCommands, tmp_path: Path,
) -> None:
    """Recovery restores readable project-local Traces without recreating Runtime Home."""
    root = tmp_path / 'origin'
    native = tmp_path / 'native.jsonl'
    trace, content = _source(root, native)
    result = _migrate(installed_commands, root)
    assert result.returncode == 0, result.stderr
    backup = yaml.safe_load(result.stdout)['backup']
    native.unlink()
    restored = run_process([str(installed_commands.product), 'migrate-tickets', '--restore', backup], cwd=root)
    assert restored.returncode == 0, restored.stderr
    assert not native.exists()
    assert trace.read_bytes() == content
    assert trace.resolve().is_relative_to(root)
    record = yaml.safe_load((root / '.graphtraj/runner/sessions/member/session.yml').read_text())
    assert Path(record['rollout_path']).read_bytes() == content
    assert Path(record['rollout_path']).is_relative_to(root)
    assert _migrate(installed_commands, root).returncode == 0


def test_snapshot_refuses_existing_destination_without_changes(
    installed_commands: InstalledCommands, tmp_path: Path,
) -> None:
    """The copy operation never replaces a user directory or writes inside its source."""
    root = tmp_path / 'origin'
    _source(root, tmp_path / 'native.jsonl')
    destination = tmp_path / 'occupied'
    destination.mkdir()
    saved = destination / 'user.txt'
    saved.write_text('keep')
    before = _snapshot(root)
    alias = tmp_path / 'source-alias'
    alias.symlink_to(root, target_is_directory=True)
    for target in (destination, root / 'nested', alias / 'nested'):
        result = run_process([str(installed_commands.product), 'migrate-tickets', '--snapshot', str(target)], cwd=root)
        assert result.returncode != 0
    assert saved.read_text() == 'keep'
    assert _snapshot(root) == before


def test_snapshot_preserves_pi_parent_attachments_and_other_runtime_cursors(
    installed_commands: InstalledCommands, tmp_path: Path,
) -> None:
    """Copied parents/attachments and existing Claude cursors never consult original paths."""
    from graphtraj.runtimes.claude.collection import open_archive, collect_transcript, finish_transcript_collection

    origin = tmp_path / 'origin'
    origin.mkdir()
    _ticket_project(origin)
    image = origin / 'image.png'
    image.write_bytes(b'original-image-bytes')
    parent = tmp_path / 'parent.jsonl'
    child = tmp_path / 'child.jsonl'
    claude = tmp_path / 'claude.jsonl'
    dsh = tmp_path / 'dsh.jsonl'
    message = {'type': 'message', 'id': 'm1', 'message': {'role': 'user', 'content': 'inherited'}}
    records = {
        parent: [{'type': 'session', 'id': 'p1', 'version': 3, 'cwd': str(origin), 'timestamp': 1}, message],
        child: [{'type': 'session', 'id': 'p2', 'version': 3, 'cwd': str(origin), 'timestamp': 2,
                 'parentSession': str(parent)}, message,
                {'type': 'message', 'id': 'm2', 'message': {'role': 'user', 'content': [
                    {'type': 'image', 'path': 'image.png'}]}}],
        claude: [{'type': 'user', 'sessionId': 'c1', 'uuid': 'm1',
                  'message': {'role': 'user', 'content': 'original text'}}],
        dsh: [{'version': 4, 'id': 'd1', 'createdAt': 1, 'isSeeded': False},
              {'type': 'user/message', 'seq': 0, 'time': 1, 'surfaceOp': 'append',
               'data': {'id': 'm1', 'role': 'user', 'content': [{'type': 'text', 'text': 'dsh-original'}],
                        'source': {'kind': 'user'}}},
              {'type': 'llm/retry', 'seq': 1, 'time': 2, 'data': {
                  'turn': 0, 'step': 0, 'retryId': 'r1', 'retry': 1, 'provider': 'deepseek', 'mode': 'normal',
                  'policyKey': 'default', 'delayMs': 488.02348886860193, 'maxRetries': 2,
                  'failure': {'message': 'temporary failure', 'code': 'RATE_LIMIT'}}}],
    }
    for path, values in records.items():
        path.write_text(''.join(json.dumps(value) + '\n' for value in values))
    claude_alias = tmp_path / 'claude-alias.jsonl'
    claude_alias.symlink_to(claude)
    for runtime, session, path in [('pi', 'p1', parent), ('pi', 'p2', child),
                                   ('claude', 'c1', claude_alias), ('dsh', 'd1', dsh)]:
        mapping = origin / '.graphtraj/runner/sessions' / session / 'mapping.yml'
        mapping.parent.mkdir(parents=True)
        mapping.write_text(yaml.safe_dump({'runtime': runtime, 'session': session, 'alias': session,
                                          'ticket_id': '2', 'trace_file': str(path)}))
        (mapping.parent / 'session.yml').write_text(yaml.safe_dump({'session': session, 'rollout_path': str(path)}))
    with open_archive(origin / '.graphtraj/state', origin, 'c1', 'c1', source='member', task_ids=['2']) as store:
        collect_transcript(store, claude)
        finish_transcript_collection(store, 'c1', terminal=True)
        original_events = store.next_seq
    copy = tmp_path / 'rehearsal'
    result = run_process([str(installed_commands.product), 'migrate-tickets', '--snapshot', str(copy)], cwd=origin)
    assert result.returncode == 0, result.stderr
    shutil.rmtree(origin)
    for path in records:
        path.unlink()
    result = _migrate(installed_commands, copy)
    assert result.returncode == 0, result.stderr
    state = copy / '.graphtraj/state'
    with SessionStore(session_path(state, 'pi:p2'), readonly=True) as store:
        assert store.header['parentSession'] == 'pi:p1'
        assert store.header['graphtraj']['native']['record']['parentSession'] == str(parent)
        attachments = [attachment for event in store.page()['events']
                       for attachment in event.get('graphtraj', {}).get('attachments', [])]
        assert len(attachments) == 1
        assert store.attachment(attachments[0]['sha256']) == b'original-image-bytes'
    with SessionStore(session_path(state, 'claude:c1'), readonly=True) as store:
        assert store.next_seq == original_events
        assert store.header['graphtraj']['projectId'] == str(origin)
    with SessionStore(session_path(state, 'dsh:d1'), readonly=True) as store:
        events = store.page()['events']
        assert events[0]['data']['content'][0]['text'] == 'dsh-original'
        assert events[1]['data']['delayMs'] == 488.02348886860193
        assert events[1]['graphtraj']['native']['record'] == records[dsh][2]
        assert store.header['graphtraj']['projectId'] == str(origin)


def test_referenced_forks_are_ordered_and_missing_parent_history_is_retained(
    installed_commands: InstalledCommands, tmp_path: Path,
) -> None:
    """Import a known parent first; preserve child observations when its parent is unavailable."""
    for available in (False, True):
        origin = tmp_path / ('origin-' + str(available))
        origin.mkdir()
        _ticket_project(origin)
        parent = tmp_path / ('parent-' + str(available) + '.jsonl')
        child = tmp_path / ('child-' + str(available) + '.jsonl')
        parent_records = [
            {'type': 'session_meta', 'ordinal': 0, 'payload': {'id': 'p'}},
            {'type': 'response_item', 'ordinal': 1, 'payload': {'text': 'parent-original'}},
        ]
        parent_bytes = ''.join(json.dumps(record) + '\n' for record in parent_records).encode()
        parent.write_bytes(parent_bytes)
        child_records = [
            {'type': 'session_meta', 'ordinal': 2, 'payload': {'id': 'c', 'forked_from_id': 'p',
             'history_base': {'thread_id': 'p', 'end_ordinal_exclusive': 2, 'end_byte_offset': len(parent_bytes)}}},
            {'type': 'response_item', 'ordinal': 3, 'payload': {'encrypted_content': 'original-ciphertext'}},
        ]
        child.write_text(''.join(json.dumps(record) + '\n' for record in child_records))
        values = [('a-child', 'c', child)] + ([('z-parent', 'p', parent)] if available else [])
        for alias, session, path in values:
            mapping = origin / '.graphtraj/runner/sessions' / alias / 'mapping.yml'
            mapping.parent.mkdir(parents=True)
            mapping.write_text(yaml.safe_dump({'alias': alias, 'session': session, 'runtime': 'codex',
                                              'ticket_id': '2', 'trace_file': str(path)}))
        copy = tmp_path / ('copy-' + str(available))
        result = run_process([str(installed_commands.product), 'migrate-tickets', '--snapshot', str(copy)], cwd=origin)
        assert result.returncode == 0, result.stderr
        shutil.rmtree(origin)
        parent.unlink()
        child.unlink()
        result = _migrate(installed_commands, copy)
        assert result.returncode == 0, result.stderr
        with SessionStore(session_path(copy / '.graphtraj/state', 'codex:c'), readonly=True) as store:
            if available:
                store.validate()
                assert store.next_seq == 5 and store.pending() is None
                assert store.page()['events'][2]['type'] == 'session/end-seed'
            else:
                assert store.next_seq == 0
                pending = store.pending()['event']['data']['observations']
                assert [item['event']['data']['record'] for item in pending] == child_records
                assert any(gap['path'] == 'history_base' for gap in pending[0]['event']['graphtraj']['missing'])
