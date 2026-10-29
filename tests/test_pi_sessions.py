"""Pi unified archives through real controlled RPC and native extension pipes."""
from contextlib import ExitStack, nullcontext
import json
from pathlib import Path
import time

import pytest

from graphtraj.runtimes.pi.collector import PiCollector
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError
from graphtraj.sessions.storage import SessionStore, session_path
from agent_swarm.sessions.archive import JsonlSessionStore, archive_path
from agent_swarm.sessions.protocol import native_record
from test_pi_runtime import pi_environment, execution
from test_result_submission import result_project


def test_rpc_fragmentation_and_partial_failures(tmp_path: Path, pi_environment: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Real transport chunk size changes neither semantic content nor durable growth."""
    result_project(tmp_path)
    metrics = []
    for size, prompt in [(1, 'stream-ok'), (512, 'stream-ok'), (512, 'stream-error'),
                         (512, 'stream-abort'), (512, 'stream-crash')]:
        monkeypatch.setenv('PI_FIXTURE_CHUNK', str(size))
        with ExitStack() as stack:
            turn, _, trace = execution(tmp_path, pi_environment, 'research@x1', prompt, stack)
            if prompt in {'stream-error', 'stream-crash'}:
                with pytest.raises(RuntimeAdapterError):
                    turn.run()
            else:
                result = turn.run()
                assert result['outcome'] == ('interrupted' if prompt == 'stream-abort' else 'completed')
        assert not (trace.with_suffix('.pi') / 'rpc.jsonl').exists()
        path = archive_path(tmp_path / '.graphtraj/swarm', 'pi:' + turn.session)
        with nullcontext(JsonlSessionStore(path)) as store:
            start = time.perf_counter()
            events = store.page(limit=1000)['events']
            read_ms = (time.perf_counter() - start) * 1000
            observations = [item['event'] for item in store.observations() + store.pending()]
            attempt = [event for event in observations if event['type'] == 'assistant/attempt'][-1]
            stream = attempt['data']['stream']
            runs = [record for record in stream if record['type'] == 'text-run']
            assert ''.join(record['text'] for record in runs if record['index'] == 1) == 'hello世界 ' * 1024
            assert ''.join(record['text'] for record in runs if record['index'] == 2) == '{"path":"/tmp/result"}'
            assert len(runs) == 3
            encoded = json.dumps(stream)
            for expected in ('cipher:sig', 'cipher:payload', 'fixture-tokenizer', '-0.25', 'call-1'):
                assert expected in encoded
            if prompt in {'stream-abort', 'stream-error', 'stream-crash'}:
                assert attempt['data']['interrupted'] is True
            if prompt != 'stream-crash':
                native = [native_record(event) for event in events if event['type'] == 'native']
                message = [record['message'] for record in native if record.get('message', {}).get('role') == 'assistant'][-1]
                assert message['usage'] == {'input': 17, 'output': 4096, 'cacheRead': 3, 'cacheWrite': 0}
            if prompt == 'stream-ok':
                tool = next(record['message'] for record in native if record.get('message', {}).get('role') == 'toolResult')
                assert tool['toolCallId'] == 'call-1'
                assert tool['content'] == [{'type': 'text', 'text': 'tool result'}]
            metrics.append({'chunk': size, 'case': prompt, 'bytes': path.stat().st_size,
                            'events': len(events), 'stream_records': len(stream), 'page_ms': read_ms,
                            'native_bytes': (trace.with_suffix('.pi') / 'session.jsonl').stat().st_size,
                            'native_records': len((trace.with_suffix('.pi') / 'session.jsonl').read_text().splitlines()),
                            'wire': json.loads((trace.with_suffix('.pi') / 'traffic.json').read_text())})
        # Each comparison uses a fresh native Session and archive.
        trace.unlink(missing_ok=True)
        (trace.with_suffix('.pi') / 'session.jsonl').unlink()
    assert metrics[0]['events'] == metrics[1]['events']
    assert metrics[0]['stream_records'] == metrics[1]['stream_records']
    assert metrics[0]['bytes'] <= metrics[1]['bytes'] * 1.5
    print('PI_TRANSPORT_METRICS=' + json.dumps(metrics))


def test_native_resume_fork_partial_line_and_independent_export(tmp_path: Path) -> None:
    """Native byte cursors survive reopen, partial writes, branches and source removal."""
    native = tmp_path / 'native.jsonl'
    header = {'type': 'session', 'id': 'native-parent', 'version': 3,
              'timestamp': '2026-10-14T00:00:00Z', 'cwd': str(tmp_path)}
    entries = [header, {'type': 'message', 'id': 'm1', 'parentId': None,
                       'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'retained'}]}},
               {'type': 'branch_summary', 'id': 'b1', 'parentId': 'm1', 'fromId': 'other', 'summary': 'branch'}]
    native.write_text(''.join(json.dumps(record) + '\n' for record in entries))
    arguments = {'project': str(tmp_path), 'agent': 'agent', 'source': 'main'}
    collector = PiCollector(tmp_path / 'state', native, 'native-parent', **arguments)
    assert collector.store.next_seq == 2
    collector.close()
    collector = PiCollector(tmp_path / 'state', native, 'native-parent', **arguments)
    assert collector.store.next_seq == 2
    with native.open('a') as stream:
        stream.write('{"type":"opaque","value":')
    collector.sync_native()
    assert collector.store.next_seq == 2
    with native.open('a') as stream:
        stream.write('"secret"}\n')
    collector.sync_native()
    assert collector.store.next_seq == 3
    fork = tmp_path / 'fork.jsonl'
    fork.write_text(json.dumps({**header, 'id': 'fork', 'parentSession': str(native)}) + '\n'
                    + ''.join(json.dumps(record) + '\n' for record in entries[1:]))
    child = PiCollector(tmp_path / 'state', fork, 'fork', **{**arguments, 'source': 'child'})
    assert child.store.header['parentSession'] == 'pi:native-parent'
    assert child.store.header['origin'] == 'subagent'
    child.close()
    export = tmp_path / 'archive.sqlite3'
    collector.store.export(export)
    collector.close()
    native.unlink()
    fork.unlink()
    with SessionStore(export, readonly=True) as store:
        first = store.page(limit=2)
        second = store.page(after=first['after'], limit=2)
        assert [event['seq'] for event in first['events'] + second['events']] == [0, 1, 2]
        assert first['events'][1]['data']['record'] == entries[2]
        assert second['events'][0]['data']['record']['value'] == 'secret'


def test_native_attachments_and_durable_interrupted_draft(tmp_path: Path) -> None:
    """Copy attachment bytes and recover checkpointed output without a source symlink."""
    attachment = tmp_path / 'attachment.bin'
    attachment.write_bytes(b'original bytes\x00')
    native = tmp_path / 'native.jsonl'
    records = [{'type': 'session', 'id': 's', 'version': 3, 'timestamp': 0},
               {'type': 'message', 'message': {'role': 'user', 'content': [
                   {'type': 'file', 'path': str(attachment)},
                   {'type': 'image', 'path': str(tmp_path / 'missing.png')}]}}]
    native.write_text(''.join(json.dumps(record) + '\n' for record in records))
    arguments = {'project': str(tmp_path), 'agent': 'agent', 'source': 'main'}
    collector = PiCollector(tmp_path / 'state', native, 's', **arguments)
    collector.receive({'type': 'message_update', 'message': {}, 'assistantMessageEvent': {
        'type': 'text_delta', 'contentIndex': 0, 'delta': 'durable partial', 'partial': {}}})
    collector.receive({'type': 'permission', 'request': 'confirm'})
    assert collector.store.pending() is not None
    collector.store.close()  # Simulate loss after a returned durable boundary.
    attachment.unlink()
    resumed = PiCollector(tmp_path / 'state', native, 's', **arguments)
    events = resumed.store.page()['events']
    references = events[0]['attachments']
    assert resumed.store.attachment(references[0]['sha256']) == b'original bytes\x00'
    assert references[1]['missing']['reason'] == 'FileNotFoundError'
    assert events[-1]['data']['interrupted'] is True
    assert events[-1]['data']['stream'][0]['text'] == 'durable partial'
    assert any(item['path'] == 'transportTail' for item in events[-1]['missing'])
    assert resumed.store.pending() is None
    resumed.close()


def test_main_and_plugin_extension_pipe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The shipped extension starts one real collector pipe for Main and plugin children."""
    from click.testing import CliRunner
    import os
    import shutil
    import subprocess
    import sys

    from graphtraj.configuration.project_configuration import default_configuration_content, load_project_configuration
    from graphtraj.execution.main_finalize import session_binding
    from graphtraj.runtimes.native_entry import main

    if shutil.which('node') is None:
        pytest.skip('Node is required for the actual extension carrier')
    configuration = tmp_path / '.graphtraj/config.yml'
    configuration.parent.mkdir()
    configuration.write_text(default_configuration_content(tmp_path, tmp_path))
    monkeypatch.chdir(tmp_path)
    native = tmp_path / 'native.jsonl'
    header = {'type': 'session', 'id': 'main-pipe', 'version': 3, 'timestamp': 0, 'cwd': str(tmp_path)}
    native.write_text(json.dumps(header) + '\n')
    monkeypatch.setenv('GRAPHTRAJ_NATIVE_RUNTIME', 'pi')
    monkeypatch.setenv('GRAPHTRAJ_NATIVE_SESSION', header['id'])
    monkeypatch.setenv('GRAPHTRAJ_NATIVE_SESSION_FILE', str(native))
    result = CliRunner().invoke(main, ['pi'], input=json.dumps({
        'event': 'session_start', 'reason': 'startup', 'header': header, 'entries': []}))
    assert json.loads(result.output) == {'source': 'main'}
    binding = session_binding(tmp_path, 'pi', header['id'])
    original = binding.read_bytes()
    native.unlink()  # Real Pi defers creating a fresh file until its first message.
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    command = bin_dir / 'graphtraj-session'
    command.write_text(f'#!{sys.executable}\nfrom graphtraj.runtimes.native_entry import main\nmain()\n')
    command.chmod(0o755)
    monkeypatch.setenv('PATH', str(bin_dir) + os.pathsep + os.environ['PATH'])
    source = Path(__file__).resolve().parents[1] / 'src'
    monkeypatch.setenv('PYTHONPATH', str(source))
    script = '''
import { pathToFileURL } from 'node:url';
const { startCollection } = await import(pathToFileURL(process.argv[1]).href);
const collector = await startCollection({cwd: process.cwd(), sessionManager: {
  getHeader: () => ({type: 'session', version: 3, id: process.env.GRAPHTRAJ_NATIVE_SESSION,
    cwd: process.cwd(), timestamp: 0}), getEntries: () => [],
}}, {});
await collector.write({type: 'message_update', message: {}, assistantMessageEvent:
  {type: 'text_delta', contentIndex: 0, delta: 'from extension', partial: {}}});
await collector.write({type: 'permission', request: 'retained boundary'});
await collector.close();
'''
    for session, child in [('main-pipe', False), ('plugin-child', True)]:
        if child:
            native.write_text(json.dumps({**header, 'id': session}) + '\n')
            monkeypatch.setenv('GRAPHTRAJ_NATIVE_SESSION', session)
            monkeypatch.setenv('PI_SUBAGENT_CHILD', '1')
        subprocess.run(['node', '--input-type=module', '-e', script,
                        str(source / 'graphtraj/runtimes/pi/extension.mjs')],
                       check=True, timeout=20, capture_output=True, text=True)
        path = archive_path(tmp_path / '.graphtraj/swarm', 'pi:' + session)
        with nullcontext(JsonlSessionStore(path)) as store:
            assert store.header['source'] == ('child' if child else 'main')
            attempt = next(item['event'] for item in store.pending()
                           if item['event']['type'] == 'assistant/attempt')
            assert ''.join(item.get('text', '') for item in attempt['data']['stream']) == 'from extension'
            assert attempt['data']['interrupted'] is True
        assert binding.read_bytes() == original


def test_retry_and_unknown_boundaries_do_not_join_attempts(tmp_path: Path) -> None:
    """A retry ends partial output, and a permission or unknown field splits a run."""
    collector = PiCollector(tmp_path / 'state', tmp_path / 'not-yet-persisted.jsonl', 'fresh',
                            project=str(tmp_path), agent='agent', source='member')
    start = {'type': 'message_start', 'message': {'role': 'assistant', 'content': []}}
    collector.receive(start)
    for text in ('one', 'two'):
        collector.receive({'type': 'message_update', 'message': {}, 'assistantMessageEvent': {
            'type': 'text_delta', 'contentIndex': 0, 'delta': text, 'partial': {}, 'unknown': 'ciphertext'}})
    collector.receive({'type': 'auto_retry_start', 'attempt': 2, 'errorMessage': 'retry reason'})
    collector.receive(start)
    collector.receive({'type': 'message_update', 'message': {}, 'assistantMessageEvent': {
        'type': 'text_delta', 'contentIndex': 0, 'delta': 'new attempt', 'partial': {}}})
    collector.receive({'type': 'permission', 'question': 'continue'})
    collector.close()
    with SessionStore(session_path(tmp_path / 'state', 'pi:fresh'), readonly=True) as store:
        attempts = store.page()['events']
        assert len(attempts) == 2
        assert all(event['data']['interrupted'] for event in attempts)
        runs = [[record['text'] for record in event['data']['stream']
                 if record['type'] == 'text-run'] for event in attempts]
        assert runs == [['one', 'two'], ['new attempt']]
        assert any(item['path'] == 'logprobs' for item in attempts[1]['missing'])
        assert 'retry reason' in json.dumps(attempts[0])
        assert 'ciphertext' in json.dumps(attempts[0])


def test_installed_pi_native_branch_and_fork_archive(tmp_path: Path) -> None:
    """Use the installed Pi SessionManager, without launching a model or reading Home history."""
    import shutil
    import subprocess

    node, pi = shutil.which('node'), shutil.which('pi')
    if not node or not pi:
        pytest.skip('Installed Pi SDK and Node are required')
    module = Path(__file__).resolve().parents[1] / 'src/graphtraj/runtimes/pi/extension.mjs'
    script = '''
import { pathToFileURL } from 'node:url';
const { loadHostSdk } = await import(pathToFileURL(process.argv[1]).href);
const { SessionManager } = await loadHostSdk(process.argv[2]);
const manager = SessionManager.create(process.cwd(), process.cwd() + '/native');
const user = manager.appendMessage({role: 'user', content: 'SDK fixture', timestamp: 1});
manager.appendMessage({role: 'assistant', content: [{type: 'text', text: 'first branch', textSignature: 'sdk-signature'}],
  model: 'fixture-model', provider: 'fixture-provider', api: 'fixture', timestamp: 2, stopReason: 'stop',
  usage: {input: 7, output: 3, cacheRead: 2, cacheWrite: 0, totalTokens: 12}});
manager.branchWithSummary(user, 'branch summary', {opaque: 'keep'});
manager.appendMessage({role: 'user', content: 'second branch', timestamp: 3});
const fork = SessionManager.forkFrom(manager.getSessionFile(), process.cwd(), process.cwd() + '/fork');
console.log(JSON.stringify({parent: manager.getSessionFile(), child: fork.getSessionFile(),
  parentId: manager.getSessionId(), childId: fork.getSessionId()}));
'''
    result = subprocess.run([node, '--input-type=module', '-e', script, str(module), pi],
                            cwd=tmp_path, capture_output=True, text=True, check=True, timeout=20)
    facts = json.loads(result.stdout)
    for key, identity in [('parent', 'parentId'), ('child', 'childId')]:
        path = Path(facts[key])
        original = [json.loads(line) for line in path.read_text().splitlines()]
        collector = PiCollector(tmp_path / 'state', path, facts[identity], project=str(tmp_path),
                                agent='native-sdk-fixture', source='main')
        events = collector.store.page()['events']
        assert [store_record for event in events if event['type'] != 'session/end-seed'
                for store_record in [native_record(event)]] == original[1:]
        assert collector.store.header['native']['record'] == original[0]
        assert any(event['type'] == 'assistant/message' for event in events)
        assert any(native_record(event).get('type') == 'branch_summary' for event in events
                   if event['type'] != 'session/end-seed')
        message = next(event for event in events if event['type'] == 'assistant/message')
        assert message['data']['usage']['inputTokens'] == 7
        assert message['data']['usage']['cacheReadTokens'] == 2
        if key == 'child':
            assert collector.store.header['parentSession'] == 'pi:' + facts['parentId']
        collector.sync_native()
        expected_events = len(original) - 1
        if key == 'child':
            expected_events += 1
        assert collector.store.next_seq == expected_events
        collector.store.validate()
        collector.close()
