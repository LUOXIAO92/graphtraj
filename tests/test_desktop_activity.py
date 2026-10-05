"""Human activity projection through the same public operation the desktop uses."""
import json
from pathlib import Path

import pytest
import yaml

from graphtraj.execution.runner_status import runtime_caller
from graphtraj.execution.runner_models import RunnerError
from graphtraj.interfaces.gateway import handle_request
from graphtraj.interfaces.local_tool import bind
from test_result_submission import result_project
from conftest import InstalledCommands


def query(root: Path, **arguments: object) -> dict:
    """Exercise the native gateway, including argument and authority validation."""
    result = bind(root, desktop_observer=True)({'action': 'execute', 'feature': 'desktop_activity',
                             'arguments': {'ticket_id': '148', **arguments}})
    assert not result.failed, result.document
    return result.document


def prepare(root: Path, runtime: str, records: list[dict]) -> tuple[Path, Path, Path]:
    """Retain a controlled Runtime's records behind actual registered membership."""
    runner, team, _ = result_project(root)
    directory = runner / 'sessions/research@x1'
    trace = team.parent / 'traces/research@x1/events.jsonl'
    trace.parent.mkdir(parents=True)
    trace.write_text(''.join(json.dumps(record) + '\n' for record in records))
    mapping = yaml.safe_load((directory / 'mapping.yml').read_text())
    mapping.update(runtime=runtime, trace_file=str(trace))
    (directory / 'mapping.yml').write_text(yaml.safe_dump(mapping))
    (directory / 'launch.yml').write_text(yaml.safe_dump({'context_evidence': {'model': 'recorded-model'}}))
    for alias in ('research@x1', 'research@x2', 'research@x3'):
        (runner / 'sessions' / alias / 'execution.yml').write_text('outcome: completed\n')
    return runner, directory, trace


def message(text: str) -> dict:
    """Produce a Codex rollout message with observable untrusted Markdown."""
    return {'type': 'response_item', 'timestamp': '2026-10-06T00:00:00Z', 'payload': {
        'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': text}]}}


def test_incremental_replay_partial_record_and_members(tmp_path: Path) -> None:
    """Pages append once, replay identical IDs and retain offsets across partial writes."""
    _, _, trace = prepare(tmp_path, 'codex', [message(str(i)) for i in range(205)])
    first = query(tmp_path, alias='research@x1')
    assert len(first['events']) == 200 and first['has_more']
    assert first['agents'][0]['model'] == 'recorded-model'
    assert first['agents'][0]['state'] == 'idle' and not first['agents'][0]['historical']
    second = query(tmp_path, alias='research@x1', cursor=first['cursor'])
    replay = query(tmp_path, alias='research@x1', cursor=first['cursor'])
    assert all(x['replayed'] for x in replay['events'])
    assert [x['id'] for x in replay['events']] == [x['id'] for x in second['events']]
    assert [x['text'] for x in second['events']] == ['200', '201', '202', '203', '204']
    with trace.open('a') as stream:
        stream.write(json.dumps(message('live update')))
    incomplete = query(tmp_path, alias='research@x1', cursor=second['cursor'])
    assert incomplete['events'] == [] and incomplete['waiting_for_record']
    with trace.open('a') as stream:
        stream.write('\n')
    live = query(tmp_path, alias='research@x1', cursor=incomplete['cursor'])
    assert [x['text'] for x in live['events']] == ['live update']
    assert live['events'][0]['time'] == '2026-10-06T00:00:00Z'
    assert query(tmp_path, alias='research@x2', cursor=first['cursor'])['availability'] == 'cursor-expired'


def test_retired_binding_keeps_historical_trace(tmp_path: Path) -> None:
    """Removing live mappings leaves human Chat available from retained retirement evidence."""
    _, directory, trace = prepare(tmp_path, 'codex', [message('retained work')])
    mapping = yaml.safe_load((directory / 'mapping.yml').read_text())
    (directory / 'mapping.yml').unlink()
    (directory / 'session.yml').write_text(yaml.safe_dump({'retirement': {'mapping': mapping}}))
    directory.rename(trace.parent / 'runner')
    result = query(tmp_path, alias='research@x1')
    assert result['agents'][0]['historical'] and result['agents'][0]['state'] == 'retired'
    assert result['events'][0]['text'] == 'retained work'


def test_agent_cannot_use_human_observation_or_forge_path(tmp_path: Path) -> None:
    """Verified Agents cannot read even their own Chat via the human-only surface."""
    runner, _, _ = prepare(tmp_path, 'codex', [message('private')])
    with pytest.raises(RunnerError, match='desktop host binding'):
        handle_request({'action': 'execute', 'feature': 'desktop_activity', 'arguments': {'ticket_id': '148'}}, cwd=tmp_path)
    with runtime_caller(runner, 'research@x1'):
        with pytest.raises(RunnerError, match='human observation'):
            query(tmp_path, alias='research@x1')
    refused = bind(tmp_path, desktop_observer=True)({'action': 'execute', 'feature': 'desktop_activity',
        'arguments': {'ticket_id': '148', 'path': '/private/elsewhere'}})
    assert refused.failed and 'unexpected parameter' in refused.document['error']
    with pytest.raises(ValueError, match='actual member'):
        query(tmp_path, alias='other@x1')


def test_missing_and_changed_traces_are_explicit(tmp_path: Path) -> None:
    """Missing content and replaced files never become a fabricated empty success."""
    _, _, trace = prepare(tmp_path, 'codex', [message('old')])
    page = query(tmp_path, alias='research@x1')
    trace.unlink()
    assert query(tmp_path, alias='research@x1', cursor=page['cursor'])['availability'] == 'unavailable'
    trace.write_text('')
    assert query(tmp_path, alias='research@x1', cursor=page['cursor'])['availability'] == 'trace-changed'


def test_codex_tools_usage_and_redaction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Native commands/results survive while credentials and unsupported metrics do not."""
    monkeypatch.setenv('EXAMPLE_API_KEY', 'secret-from-environment')
    usage = {'last_token_usage': {'input_tokens': 100, 'cached_input_tokens': 60, 'output_tokens': 5},
             'total_token_usage': {'input_tokens': 100, 'output_tokens': 5}}
    records = [
        {'type': 'turn_context', 'payload': {'model': 'actual-model', 'turn_id': 'turn-1'}},
        {'type': 'response_item', 'payload': {'type': 'function_call', 'call_id': 'c1', 'name': 'exec',
                                             'arguments': '{"cmd":"pwd", "api_key":"hidden-key"}'}},
        {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'c1',
                                             'output': 'failed: secret-from-environment Bearer raw-secret password="long private phrase"'}},
        {'type': 'event_msg', 'payload': {'type': 'token_count', 'info': usage}},
        {'type': 'event_msg', 'payload': {'type': 'token_count', 'info': usage}},
    ]
    prepare(tmp_path, 'codex', records)
    result = query(tmp_path, alias='research@x1')
    calls = [e for e in result['events'] if e['kind'] == 'tool']
    assert calls[0]['call_id'] == calls[1]['call_id'] == 'c1'
    assert 'pwd' in calls[0]['arguments'] and 'failed:' in calls[1]['result']
    serialized = json.dumps(result)
    assert all(secret not in serialized for secret in ('hidden-key', 'secret-from-environment', 'raw-secret', 'long private phrase'))
    facts = [e['usage'] for e in result['events'] if e['kind'] == 'usage']
    assert facts[0]['tokens'] == {'input': 100, 'cache_read': 60, 'output': 5}
    assert facts[0]['identity'] == facts[1]['identity']
    assert facts[0]['model'] == 'actual-model' and facts[0]['agent'] == 'research@x1'
    assert facts[0]['call_id'].startswith('counter:')
    assert facts[0]['identity_basis'] == 'native-cumulative-counter'
    assert facts[0]['attributable'] and 'provider_call_id' not in facts[0]


def test_pi_per_call_usage_and_errors(tmp_path: Path) -> None:
    """Pi's separate cache fields normalize without losing actual provider values."""
    prepare(tmp_path, 'pi', [
        {'type': 'message', 'id': 'msg-1', 'message': {'role': 'assistant', 'model': 'pi-model',
         'content': [{'type': 'text', 'text': 'Working'}, {'type': 'toolCall', 'id': 'c', 'name': 'bash', 'arguments': {'command': 'pwd'}}],
         'usage': {'input': 10, 'output': 2, 'cacheRead': 20, 'cacheWrite': 3}}},
        {'type': 'message', 'message': {'role': 'toolResult', 'toolCallId': 'c', 'isError': True, 'content': [{'type': 'text', 'text': 'denied'}]}},
    ])
    result = query(tmp_path, alias='research@x1')['events']
    usage = next(e['usage'] for e in result if e['kind'] == 'usage')
    assert usage['call_id'] == 'msg-1' and usage['tokens']['input'] == 33
    assert usage['provider_usage']['cacheRead'] == 20
    assert result[-1]['result'] == 'denied' and result[-1]['error'] is True


def test_dsh_stream_final_coordinates_and_model_source(tmp_path: Path) -> None:
    """Stream/final usage shares a native call identity; raw replay state stays private."""
    prepare(tmp_path, 'dsh', [
        {'type': 'model/selection', 'data': {'model': 'old', 'provider': 'deepseek'}},
        {'type': 'assistant/chunk', 'seq': 1, 'time': 123, 'data': {'turn': 1, 'step': 2, 'chunk': {'type': 'usage', 'usage': {'inputTokens': 100, 'outputTokens': 1}}}},
        {'type': 'assistant/message', 'seq': 2, 'time': 124, 'data': {'turn': 1, 'step': 2,
         'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'Done'}],
                     'source': {'kind': 'model', 'provider': 'deepseek', 'model': 'actual', 'replayState': 'opaque'}},
         'usage': {'inputTokens': 100, 'outputTokens': 3, 'cacheReadTokens': 80, 'cacheWriteTokens': 5}}},
        {'type': 'tool/result', 'data': {'turn': 1, 'step': 2, 'message': {'source': {'callId': 'tool-1'}, 'content': [{'type': 'tool-result', 'toolCallId': 'tool-1', 'content': 'result'}]}}},
    ])
    events = query(tmp_path, alias='research@x1')['events']
    facts = [e['usage'] for e in events if e['kind'] == 'usage']
    assert [f['phase'] for f in facts] == ['stream', 'final']
    assert facts[0]['identity'] == facts[1]['identity']
    assert facts[1]['model'] == 'actual' and facts[1]['tokens']['cache_read'] == 80
    assert facts[1]['tokens']['input'] == 185
    assert 'opaque' not in json.dumps(events)
    assert events[-1]['call_id'] == 'tool-1'


def test_installed_observer_streams_updates_and_reconnects(
    tmp_path: Path, installed_commands: InstalledCommands,
) -> None:
    """The actual desktop reader sees append/replay through installed public stdio."""
    import os
    import shutil
    import subprocess

    if not shutil.which('node'):
        pytest.skip('Optional desktop requires Node')
    _, _, trace = prepare(tmp_path, 'codex', [message('first native record')])
    environment = {**os.environ, 'GRAPHTRAJ_TOOL': str(installed_commands.product.with_name('graphtraj-tool'))}
    reader = Path(__file__).parents[1] / 'desktop/electron/activity.ts'
    script = r'''
      import assert from 'node:assert/strict';
      import { appendFile } from 'node:fs/promises';
      import { pathToFileURL } from 'node:url';
      const { ActivityReader } = await import(pathToFileURL(process.argv[1]));
      const reader = new ActivityReader();
      const root = process.argv[2];
      const request = { ticket_id: '148', alias: 'research@x1' };
      try {
        const first = await reader.read(root, request);
        assert.equal(first.events[0].text, 'first native record');
        await appendFile(process.argv[3], process.argv[4] + '\n');
        const next = await reader.read(root, { ...request, cursor: first.cursor });
        assert.equal(next.events.length, 1);
        assert.equal(next.events[0].text, 'native update');
        reader.close(root);
        const expired = await reader.read(root, { ...request, cursor: next.cursor });
        assert.equal(expired.availability, 'cursor-expired');
        const replay = await reader.read(root, request);
        assert.deepEqual(replay.events.map(event => event.id), [first.events[0].id, next.events[0].id]);
      } finally { reader.close(); }
    '''
    result = subprocess.run(
        ['node', '--preserve-symlinks', '--preserve-symlinks-main', '--input-type=module', '-e',
         script, str(reader), str(tmp_path), str(trace), json.dumps(message('native update'))],
        env=environment, capture_output=True, text=True, timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr
