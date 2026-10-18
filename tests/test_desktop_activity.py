"""Human activity projection through the same public operation the desktop uses."""
import json
from pathlib import Path
from time import monotonic

import pytest
import yaml

from graphtraj.execution.runner_status import runtime_caller
from graphtraj.execution.runner_models import RunnerError
from graphtraj.interfaces.gateway import handle_request
from graphtraj.interfaces.local_tool import bind
from test_result_submission import result_project
from conftest import InstalledCommands


@pytest.fixture(autouse=True)
def human_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Model an unbound human OS host only for in-process controlled-data checks."""
    monkeypatch.setattr('graphtraj.execution.desktop_activity.caller_runtime', lambda: None)


def query(root: Path, **arguments: object) -> dict:
    """Exercise the native gateway, including argument and authority validation."""
    result = bind(root, desktop_observer=True)({'action': 'execute', 'feature': 'desktop_activity',
                             'arguments': {'task_id': '148', **arguments}})
    assert not result.failed, result.document
    return result.document


def prepare(
    root: Path, runtime: str, records: list[dict], parent: str | None = None,
) -> tuple[Path, Path, Path]:
    """Retain a controlled Runtime's records behind actual registered membership."""
    runner, team, _ = result_project(root)
    directory = runner / 'sessions/research@x1'
    trace = team.parent / 'traces/research@x1/events.jsonl'
    trace.parent.mkdir(parents=True)
    trace.write_text(''.join(json.dumps(record) + '\n' for record in records))
    mapping = yaml.safe_load((directory / 'mapping.yml').read_text())
    mapping.update(runtime=runtime, trace_file=str(trace), parent=parent)
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
    _, _, trace = prepare(tmp_path, 'codex', [message(str(i)) for i in range(205)], parent='research@x2')
    first = query(tmp_path, alias='research@x1')
    assert len(first['events']) == 200 and first['has_more']
    assert first['agents'][0]['model'] == 'recorded-model'
    assert first['agents'][0]['parent'] == 'research@x2'
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
    """Registered Agents see only their own Session through the authenticated gateway."""
    runner, _, _ = prepare(tmp_path, 'codex', [message('private')])
    with pytest.raises(RunnerError, match='desktop host binding'):
        handle_request({'action': 'execute', 'feature': 'desktop_activity', 'arguments': {'task_id': '148'}}, cwd=tmp_path)
    with runtime_caller(runner, 'research@x1'):
        allowed = handle_request({'action': 'execute', 'feature': 'desktop_activity',
            'arguments': {'task_id': '148', 'alias': 'research@x1'}}, cwd=tmp_path)
        assert not allowed.failed
        assert allowed.document['scope'] == 'self'
        assert [member['alias'] for member in allowed.document['agents']] == ['research@x1']
        assert allowed.document['events'][0]['text'] == 'private'
        for target in ('research@x2', 'research@x3', 'other@x1'):
            with pytest.raises(RunnerError, match='own Session'):
                query(tmp_path, alias=target)
        with pytest.raises(RunnerError, match='own Session'):
            query(tmp_path, task_id='other')
    refused = bind(tmp_path, desktop_observer=True)({'action': 'execute', 'feature': 'desktop_activity',
        'arguments': {'task_id': '148', 'path': '/private/elsewhere'}})
    assert refused.failed and 'unexpected parameter' in refused.document['error']
    with pytest.raises(ValueError, match='actual member'):
        query(tmp_path, alias='other@x1')


@pytest.mark.parametrize('runtime', ['codex', 'pi', 'dsh'])
def test_external_main_runtime_cannot_select_grandchild_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runtime: str,
) -> None:
    """A desktop flag cannot elevate an external Main detected by native ancestry."""
    prepare(tmp_path, 'codex', [message('private grandchild')], parent='research@x2')
    monkeypatch.setattr('graphtraj.execution.desktop_activity.caller_runtime', lambda: runtime)
    with pytest.raises(RunnerError, match='human observation'):
        query(tmp_path, alias='research@x1')


def test_native_main_binding_is_not_a_human(tmp_path: Path) -> None:
    """Main's explicitly bound None alias and host receiver both retain Agent limits."""
    from graphtraj.execution.runner_connection import parent_connection

    runner, _, _ = prepare(tmp_path, 'codex', [message('private grandchild')], parent='research@x2')
    with runtime_caller(runner, None), pytest.raises(RunnerError, match='human observation'):
        query(tmp_path, alias='research@x1')
    with parent_connection('native-main-receiver'), pytest.raises(RunnerError, match='human observation'):
        query(tmp_path, alias='research@x1')


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
                                             'output': 'failed: secret-from-environment Bearer raw-secret password="long private phrase" '
                                                       'service_cookie=private-cookie service_authorization=private-auth '
                                                       '"部署_api_key":"private-unicode"'}},
        {'type': 'event_msg', 'payload': {'type': 'token_count', 'info': usage}},
        {'type': 'event_msg', 'payload': {'type': 'token_count', 'info': usage}},
    ]
    prepare(tmp_path, 'codex', records)
    result = query(tmp_path, alias='research@x1')
    calls = [e for e in result['events'] if e['kind'] == 'tool']
    assert calls[0]['call_id'] == calls[1]['call_id'] == 'c1'
    assert 'pwd' in calls[0]['arguments'] and 'failed:' in calls[1]['result']
    serialized = json.dumps(result)
    assert all(secret not in serialized for secret in (
        'hidden-key', 'secret-from-environment', 'raw-secret', 'long private phrase',
        'private-cookie', 'private-auth', 'private-unicode',
    ))
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
    assert result[-1]['error'] is True
    assert result[-1]['content'] == [{'type': 'text', 'text': 'denied'}]
    assert result[-1]['result'] == [{'type': 'text', 'text': 'denied'}]


def test_tool_results_project_readable_parts_without_dumping_encodings(tmp_path: Path) -> None:
    """Long text, structured objects, images and unknown blocks stay readable."""
    long_text   = 'A long recorded explanation of the tool output. ' * 20
    image_bytes = 'iVBORw0KGgoAAAANSUhEUg' * 800  # Self-made stand-in, never a copied image.
    plain_log   = '\n'.join(f'build {index:03d}: compiled module ok' for index in range(1, 41))
    blocks = [
        {'type': 'input_text', 'text': long_text},
        {'type': 'input_image', 'image_url': 'data:image/png;base64,' + image_bytes},
        {'type': 'input_text', 'text': 'Rendered after the image.'},
    ]
    records = [
        {'type': 'response_item', 'payload': {'type': 'custom_tool_call', 'call_id': 'img-1',
                                             'name': 'view_image', 'input': '{}'}},
        {'type': 'response_item', 'payload': {'type': 'custom_tool_call_output', 'call_id': 'img-1',
                                             'output': json.dumps(blocks)}},
        {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'obj-1',
                                             'output': json.dumps({'status': 'ok', 'items': [1, 2],
                                                                   'summary': 'All recorded checks passed'})}},
        {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'unknown-1',
                                             'output': '[{"type":"future_block","payload":"x"}]'}},
        {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'plain-1',
                                             'output': plain_log}},
    ]
    prepare(tmp_path, 'codex', records)
    started = monotonic()
    events = query(tmp_path, alias='research@x1')['events']
    # A modest image must not consume the desktop's 15-second active timeout.
    assert monotonic() - started < 5
    results = [event for event in events if event['kind'] == 'tool' and event['phase'] == 'result']

    mixed = results[0]
    assert [part['type'] for part in mixed['content']] == ['text', 'image', 'text']
    assert mixed['content'][0]['text'] == long_text
    assert mixed['content'][1] == {'type': 'image', 'mime': 'image/png', 'data': image_bytes}
    assert mixed['content'][2]['text'] == 'Rendered after the image.'
    # Image bytes never leak into a text part; the raw record is still retained.
    assert all(image_bytes not in part.get('text', '') for part in mixed['content'])
    assert mixed['result'] == json.dumps(blocks)

    structured = results[1]
    # A structured payload reads as meaningful fields, not an inline JSON blob.
    assert structured['content'] == [{'type': 'text', 'text':
        'status: ok\nitems: 1, 2\nsummary: All recorded checks passed'}]
    assert '{' not in structured['content'][0]['text']
    assert structured['result'] == json.dumps({'status': 'ok', 'items': [1, 2],
                                               'summary': 'All recorded checks passed'})

    assert results[2]['content'] == [{'type': 'unknown', 'label': 'future_block'}]
    # Plain text keeps its recorded newlines instead of collapsing into one paragraph.
    assert results[3]['content'] == [{'type': 'text', 'text': plain_log}]


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
    from graphtraj.runtimes.replacement import caller_runtime
    if caller_runtime() is not None:
        pytest.skip('Positive human subprocess observation requires a genuine non-Agent host')
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
      const request = { task_id: '148', alias: 'research@x1' };
      try {
        const first = await reader.read(root, request);
        assert.equal(first.events[0].text, 'first native record');
        await appendFile(process.argv[3], process.argv[4] + '\n');
        const next = await reader.read(root, { ...request, cursor: first.cursor });
        assert.equal(next.events.length, 1);
        assert.equal(next.events[0].text, 'native update');
        reader.close(root);
        const resumed = await reader.read(root, { ...request, cursor: next.cursor });
        assert.equal(resumed.availability, 'available');
        assert.deepEqual(resumed.events, []);
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


def test_installed_desktop_flag_preserves_actual_agent_identity(
    tmp_path: Path, installed_commands: InstalledCommands,
) -> None:
    """A real Agent-launched observer cannot elevate itself through its CLI flag."""
    import subprocess
    from graphtraj.runtimes.replacement import caller_runtime

    if caller_runtime() is None:
        pytest.skip('This negative integration case requires an actual Agent host')
    prepare(tmp_path, 'codex', [message('private grandchild')], parent='research@x2')
    result = subprocess.run(
        [str(installed_commands.product.with_name('graphtraj-tool')), '--desktop-observer'],
        cwd=tmp_path, input=json.dumps({'action': 'execute', 'feature': 'desktop_activity',
            'arguments': {'task_id': '148', 'alias': 'research@x1'}}) + '\n',
        text=True, capture_output=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    reply = json.loads(result.stdout)
    assert reply['failed'] and 'human observation' in reply.get('error', ''), reply
    assert 'private grandchild' not in result.stdout


def test_desktop_option_keeps_authenticated_cli_forwarding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The desktop selector cannot bypass the calling Agent's existing channel."""
    from graphtraj.interfaces.local_tool import answer
    from graphtraj.interfaces.tools import ToolResult

    calls = []

    def forwarded(request: dict, cwd: Path) -> ToolResult:
        """Represent the authenticated host refusing an Agent conversation query."""
        calls.append((request, cwd))
        return ToolResult({'error': 'Agent query refused'}, failed=True)

    monkeypatch.setattr('graphtraj.interfaces.hosted_cli.forward_request', forwarded)
    request = {'action': 'execute', 'feature': 'desktop_activity', 'arguments': {'task_id': '148'}}
    reply = answer(request, cwd=tmp_path, desktop_observer=True)
    assert reply['failed'] and calls == [(request, tmp_path)]


def test_dsh_external_main_uses_native_node_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """DSH's actual executable ancestry is recognized without trusting environment claims."""
    from graphtraj.runtimes import replacement

    monkeypatch.setattr(replacement, 'process_ancestors', lambda pid: [pid, 700])
    monkeypatch.setattr(replacement, 'process_executable', lambda pid: Path('/usr/bin/node'))
    monkeypatch.setattr(replacement.sys, 'platform', 'darwin')
    monkeypatch.setattr(replacement.subprocess, 'check_output',
                        lambda *args, **kwargs: '/usr/bin/node /installed/@deepseek-ai/dsh/lib/bin.js')
    assert replacement.caller_runtime() == 'dsh'


def test_self_query_is_registered_for_authenticated_runtime_hosts(tmp_path: Path) -> None:
    """Managed Runtime/CLI callers share the self feature; native helpers do not gain it."""
    from graphtraj.runtimes.codex.managed_session import native_operation_features
    from graphtraj.execution.runner_status import NativeCaller

    runner, _, _ = prepare(tmp_path, 'codex', [message('own retained content')])
    request = {'action': 'execute', 'feature': 'desktop_activity', 'arguments': {'task_id': '148'}}
    with runtime_caller(runner, 'research@x1'):
        result = handle_request(request, cwd=tmp_path, allowed_features=native_operation_features())
        assert not result.failed and result.document['scope'] == 'self'
        assert [row['alias'] for row in result.document['agents']] == ['research@x1']
    for identity in ('unknown-native-thread', NativeCaller('research@x1', {'runtime': 'codex'})):
        with runtime_caller(runner, identity), pytest.raises(RunnerError):
            query(tmp_path, alias='research@x1')


def test_codex_cache_writes_and_counter_replay_across_turns(tmp_path: Path) -> None:
    """Actual cache-write telemetry survives; a repeated lifetime counter is one fact."""
    raw = {'input_tokens': 1000, 'cached_input_tokens': 600,
           'cache_write_input_tokens': 100, 'output_tokens': 200,
           'reasoning_output_tokens': 150}
    count = {'type': 'event_msg', 'payload': {'type': 'token_count',
             'info': {'last_token_usage': raw, 'total_token_usage': raw}}}
    prepare(tmp_path, 'codex', [
        {'type': 'turn_context', 'payload': {'model': 'gpt-6-astra', 'turn_id': 'one'}},
        count,
        {'type': 'turn_context', 'payload': {'model': 'gpt-6-astra', 'turn_id': 'two'}},
        count,
    ])
    facts = [event['usage'] for event in query(tmp_path, alias='research@x1')['events']
             if event['kind'] == 'usage']
    assert facts[0]['tokens'] == {
        'input': 1000, 'cache_read': 600, 'cache_write': 100,
        'output': 200, 'reasoning': 150,
    }
    assert facts[0]['identity'] == facts[1]['identity']


def test_usage_pages_progress_across_65_readable_agents(tmp_path: Path) -> None:
    """Round-robin public reads reach later usage and preserve idle totals at scale."""
    from graphtraj.graph.delivery_state import apply_delivery_state_request
    from graphtraj.graph.delivery_worldline import read_worldline

    runner, directory, trace = prepare(tmp_path, 'codex', [])
    template = yaml.safe_load((directory / 'mapping.yml').read_text())
    aliases = [f'research@x{index}' for index in range(1, 66)]
    for index, alias in enumerate(aliases, 1):
        if index > 3:
            request = {'phase': 'member', 'task_id': '148', 'member': f'member{index}',
                       'role': 'researcher', 'session_ref': alias,
                       'caused_by_event_ids': [read_worldline(tmp_path / 'state', tmp_path)[-1]['event_id']],
                       'evidence_refs': ['evidence.md']}
            apply_delivery_state_request(tmp_path / 'state', tmp_path, request, request)
        member = runner / 'sessions' / alias
        member.mkdir(exist_ok=True)
        native_trace = trace.parent.parent / alias / 'events.jsonl'
        native_trace.parent.mkdir(exist_ok=True)
        raw = {'input_tokens': 100, 'cached_input_tokens': 60, 'output_tokens': 5}
        records = [message('earlier activity')] * 200 + [
            {'type': 'turn_context', 'payload': {'model': 'gpt-5.3-codex'}},
            {'type': 'event_msg', 'payload': {'type': 'token_count',
             'info': {'last_token_usage': raw, 'total_token_usage': raw}}},
        ]
        native_trace.write_text(''.join(json.dumps(record) + '\n' for record in records))
        (member / 'mapping.yml').write_text(yaml.safe_dump({
            **template, 'alias': alias, 'session': 'native-' + alias,
            'trace_file': str(native_trace),
        }))
        (member / 'execution.yml').write_text('outcome: completed\n')

    cursors = {}
    for alias in aliases:
        page = query(tmp_path, alias=alias)
        assert page['has_more'] and not any(event['kind'] == 'usage' for event in page['events'])
        cursors[alias] = page['cursor']
    usage = {}
    for alias in aliases:
        page = query(tmp_path, alias=alias, cursor=cursors[alias])
        assert page['availability'] == 'available' and not page['has_more']
        fact = next(event['usage'] for event in page['events'] if event['kind'] == 'usage')
        usage[fact['identity']] = fact['tokens']
        cursors[alias] = page['cursor']
    assert len(usage) == 65
    assert sum(tokens['input'] for tokens in usage.values()) == 6500
    assert sum(tokens['cache_read'] for tokens in usage.values()) == 3900
    for alias in aliases:
        page = query(tmp_path, alias=alias, cursor=cursors[alias])
        assert page['availability'] == 'available' and page['events'] == []
    assert len(usage) == 65


@pytest.mark.parametrize('parallel', [False, True])
def test_windows_adoption_fixture_projects_retired_content_and_usage(
    temporary_git_repository: Path, parallel: bool,
) -> None:
    """The exact desktop fixture must survive native validation and Dashboard arithmetic."""
    import subprocess

    from conftest import PROJECT_ROOT
    from test_windows_desktop import operation

    root = temporary_git_repository
    operation(root, 'project_setup', {'source_repository': str(root), 'apply': True, 'create_dev': True})
    registered = operation(root, 'task_register', {
        'task_id': '1', 'task_name': 'controlled', 'title': 'Controlled',
        'source': 'https://github.com/example/controlled/issues/1', 'schema_version': 2, 'parent_id': None, 'disposition': 'active', 'replaced_by': [], 'retirement_reason': None,
        'body': 'Controlled fixture, no Runtime execution.', 'dependencies': [],
    })
    # Match Node's adoption seed bytes on Windows as well as POSIX.
    (root / 'seed.txt').write_text(
        'Controlled Windows adoption project; no model execution.\n', encoding='utf-8', newline='\n',
    )
    fixture = (PROJECT_ROOT / 'desktop/tests/retained-records.mjs').as_uri()
    generated = subprocess.run(
        ['node', '--preserve-symlinks', '--preserve-symlinks-main', '--input-type=module', '-e',
         f'import {{retainedRecords}} from {json.dumps(fixture)}; '
         f'console.log(await retainedRecords(process.argv[1], process.argv[2], {json.dumps(parallel)}));',
         str(root), registered['task_directory']],
        text=True, capture_output=True, timeout=15, check=False,
    )
    assert generated.returncode == 0, generated.stderr
    if parallel:
        for status, ordinal in [('ready', None), ('implementing', 1)]:
            operation(root, 'task_update', {
                'task_id': '1', 'status': status, 'active_team_ordinal': ordinal,
                'worktree': None, 'branch': None, 'current_candidate': None,
                'caused_by_event_ids': [], 'evidence_refs': ['seed.txt'],
            })
    alias = generated.stdout.strip()
    observer = bind(root, desktop_observer=True)
    arguments = {'task_id': '1', 'alias': alias}
    response = observer({'action': 'execute', 'feature': 'desktop_activity', 'arguments': arguments})
    assert not response.failed, response.document
    observed = response.document
    assert len(observed['agents']) == (2 if parallel else 1)
    if parallel:
        current = next(agent for agent in observed['agents'] if agent['alias'] == 'current@x2')
        assert not current['historical'] and current['state'] == 'idle', current
    agent = observed['agents'][0]
    assert agent['alias'] == alias and agent['historical'] and agent['state'] == 'retired', agent
    assert agent['model'] == 'gpt-5.3-codex'
    assert observed['availability'] == 'available'
    events = observed['events']
    assert any(event.get('text') == 'GraphTraj GUI controlled message' for event in events)
    assert any(event.get('name') == 'echo' and event['phase'] == 'call' for event in events)
    assert any(event.get('result') == 'controlled tool output' for event in events)
    usage = next(event['usage'] for event in events if event['kind'] == 'usage')
    assert usage['tokens'] == {'input': 1000, 'cache_read': 600, 'output': 80, 'reasoning': 20}
    assert usage['session'] == agent['session'] and usage['agent'] == alias and usage['task_id'] == '1'
    assert usage['attributable'] and usage['identity']
    replay = observer({'action': 'execute', 'feature': 'desktop_activity', 'arguments': arguments})
    assert not replay.failed, replay.document

    arithmetic = (PROJECT_ROOT / 'desktop/src/usage.ts').as_uri()
    checked = subprocess.run(
        ['node', '--preserve-symlinks', '--preserve-symlinks-main', '--input-type=module', '-e',
         'import fs from "node:fs"; '
         f'import {{collect,records,summarize}} from {json.dumps(arithmetic)}; '
         'const pages=JSON.parse(fs.readFileSync(0,"utf8")); const calls=new Map(); '
         'for(const events of pages) collect(calls,"controlled",events); '
         'console.log(JSON.stringify(summarize(records(calls))));'],
        input=json.dumps([events, replay.document['events']]), text=True,
        capture_output=True, timeout=15, check=True,
    )
    total = json.loads(checked.stdout)
    assert total['count'] == 1 and total['unpriced'] == 0
    assert total['tokens']['input']['value'] == 1000 and total['tokens']['output']['value'] == 80
    assert total['tokens']['cache_read']['value'] == 600
    assert total['tokens']['cache_write']['known'] == 0
    assert total['cacheRate'] == 0.6 and total['amount'] == pytest.approx(0.001925)


def test_codex_readable_reasoning_and_execution_events(tmp_path: Path) -> None:
    """Empty summaries do not hide plaintext; absent and encrypted text stay distinct."""
    records = [
        {'type': 'response_item', 'payload': {'type': 'reasoning', 'summary': [],
         'content': [{'type': 'reasoning_text', 'text': 'Check the recorded result.'}]}},
        {'type': 'response_item', 'payload': {'type': 'reasoning',
         'summary': [{'type': 'summary_text', 'text': 'Recorded summary'}],
         'content': [{'type': 'reasoning_text', 'text': 'Recorded detail'}]}},
        {'type': 'response_item', 'payload': {'type': 'reasoning', 'summary': []}},
        {'type': 'response_item', 'payload': {'type': 'reasoning', 'summary': [],
                                             'encrypted_content': 'opaque-private-content'}},
        *({'type': 'event_msg', 'payload': {'type': kind, 'turn_id': 'turn-1'}}
          for kind in ('task_started', 'task_complete', 'turn_aborted', 'error')),
    ]
    prepare(tmp_path, 'codex', records)
    events = query(tmp_path, alias='research@x1')['events']
    assert events[0]['text'] == 'Check the recorded result.'
    assert events[1]['text'] == 'Recorded summary\n\nRecorded detail'
    assert [event['availability'] for event in events[:4]] == ['available', 'available', 'missing', 'unavailable']
    assert all(event['role'] == 'reasoning' for event in events[:4])
    assert all(event['kind'] == 'work' and event.get('role') != 'reasoning' for event in events[4:])
    assert 'opaque-private-content' not in json.dumps(events)


def test_codex_cross_page_tool_names_and_usage_observations(tmp_path: Path) -> None:
    """Real IDs retain names across pages; counter replay preserves accounting identity."""
    def item(kind: str, **payload: object) -> dict:
        """Create a minimal sanitized native response item."""
        return {'type': 'response_item', 'payload': {'type': kind, **payload}}

    def usage(total: int) -> dict:
        """Record equal latest response usage with distinct native cumulative counters."""
        return {'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {
            'last_token_usage': {'input_tokens': 10, 'output_tokens': 2},
            'total_token_usage': {'input_tokens': total, 'output_tokens': total // 5},
        }}}

    records = [
        {'type': 'turn_context', 'payload': {'turn_id': 'one-turn'}},
        item('function_call', call_id='call-1', name='exec_command', arguments='{"cmd":"pwd"}'),
        *[item('function_call', call_id=f'other-{i}', name='other_tool', arguments='{}') for i in range(70)],
        *[message('padding') for _ in range(128)],
        item('function_call_output', call_id='call-1', output='Formatted test: hook decision allow'),
        item('function_call_output', call_id='result-first', output='early result'),
        item('function_call', call_id='result-first', name='read_file', arguments='{}'),
        item('function_call_output', call_id='missing-name', output='name unavailable'),
        item('function_call', call_id='missing-name', arguments='{}'),
        usage(10), usage(20), usage(20),
    ]
    prepare(tmp_path, 'codex', records)
    first = query(tmp_path, alias='research@x1')
    from graphtraj.execution.desktop_activity import _READERS

    _READERS.clear()  # Reconstruct names from the persisted cursor and native source.
    second = query(tmp_path, alias='research@x1', cursor=first['cursor'])
    replay = query(tmp_path, alias='research@x1', cursor=first['cursor'])
    assert second['read_records'] < 20  # Unrelated call history is not replayed.
    events = second['events']
    assert events[0]['name'] == 'exec_command'
    assert events[0]['result'] == 'Formatted test: hook decision allow'
    assert events[1]['name'] is None and events[2]['name'] == 'read_file'
    assert events[3]['name'] is None and events[4]['name'] is None
    assert replay['events'][1]['name'] is None  # A later page must not mutate its checkpoint.
    assert [event['id'] for event in events] == [event['id'] for event in replay['events']]
    facts = [event['usage'] for event in events if event['kind'] == 'usage']
    assert facts[0]['identity'] != facts[1]['identity'] == facts[2]['identity']
    assert all(fact['scope'] == 'latest-response' for fact in facts)
    assert [fact['cumulative']['input_tokens'] for fact in facts] == [10, 20, 20]
    assert all(fact['tokens'] == {'input': 10, 'output': 2} for fact in facts)
    assert all(event['turn_id'] == 'one-turn' for event in events)


@pytest.mark.parametrize(('alias', 'available'), [
    ('sanitized-292@engineer', False),
    ('sanitized-other@engineer', False),
    ('sanitized292-handover0-engineer@engineer', True),
    ('sanitizedother-handover0-engineer@engineer', True),
])
def test_activity_adoption_member_aliases(tmp_path: Path, alias: str, available: bool) -> None:
    """The CI fixture must use supported aliases before any native Trace is readable."""
    _, directory, trace = prepare(tmp_path, 'codex', [message('Sanitized adoption response')])
    mapping_path = directory / 'mapping.yml'
    mapping = yaml.safe_load(mapping_path.read_text())
    mapping['alias'] = alias
    historical = alias in {'sanitized-292@engineer', 'sanitized292-handover0-engineer@engineer'}
    if historical:
        mapping_path.unlink()
        (directory / 'session.yml').write_text(yaml.safe_dump({'retirement': {'mapping': mapping}}))
    else:
        mapping_path.write_text(yaml.safe_dump(mapping))
    directory.rename(directory.with_name(alias))
    team_path = trace.parents[2] / 'team.yml'
    team = yaml.safe_load(team_path.read_text())
    for member in team['members'].values():
        if member['session_ref'] == 'research@x1':
            member['session_ref'] = alias
    team_path.write_text(yaml.safe_dump(team))

    result = query(tmp_path, alias=alias)
    member = next(agent for agent in result['agents'] if agent['alias'] == alias)
    if available:
        assert member['runtime'] == 'codex'
        assert member['state'] == ('retired' if historical else 'idle')
        assert member['historical'] == historical
        assert result['availability'] == 'available'
        assert result['events'][0]['text'] == 'Sanitized adoption response'
    else:
        assert member['state'] == 'unavailable'
        assert result['availability'] == 'unavailable' and result['events'] == []


def members(root: Path, **arguments: object) -> dict:
    """Read Task members through the shared public gateway."""
    result = handle_request({'action': 'execute', 'feature': 'task_members',
                             'arguments': arguments}, cwd=root)
    assert not result.failed, result.document
    return result.document


def test_task_members_default_to_current_summaries_and_keep_history_explicit(tmp_path: Path) -> None:
    """Completed or retired members leave the default view; explicit history keeps them."""
    _, directory, trace = prepare(tmp_path, 'codex', [message('work')], parent='research@x2')

    current = members(tmp_path)
    assert current['scope'] == ['148'] and not current['explicit']
    assert {member['alias']: (member['state'], member['parent'], member['historical'])
            for member in current['members']} == {
        'research@x1': ('standby', 'research@x2', False),
        'research@x2': ('standby', None, False),
        'research@x3': ('standby', None, False),
    }

    # Retirement removes the member from the default list, never from history.
    mapping = yaml.safe_load((directory / 'mapping.yml').read_text())
    (directory / 'mapping.yml').unlink()
    (directory / 'session.yml').write_text(yaml.safe_dump({'retirement': {'mapping': mapping}}))
    directory.rename(trace.parent / 'runner')
    assert [member['alias'] for member in members(tmp_path)['members']] == ['research@x2', 'research@x3']
    history = members(tmp_path, summary_task_id='148')
    retired = next(member for member in history['members'] if member['alias'] == 'research@x1')
    assert retired['retired'] and retired['historical'] and retired['state'] is None



def test_task_members_hide_completed_summaries_until_selected(tmp_path: Path) -> None:
    """A completed Task's standby members are history, readable by explicit selection."""
    prepare(tmp_path, 'codex', [message('work')])
    task_file = tmp_path / 'state/tasks/148-research/task.yml'
    task = yaml.safe_load(task_file.read_text())
    task_file.write_text(yaml.safe_dump({**task, 'status': 'integrated'}))

    assert members(tmp_path) == {'scope': [], 'explicit': False, 'members': []}
    history = members(tmp_path, summary_task_id='148')
    assert history['scope'] == ['148'] and history['explicit']
    assert [(member['alias'], member['state']) for member in history['members']] == [
        ('research@x1', 'standby'), ('research@x2', 'standby'), ('research@x3', 'standby'),
    ]
    assert yaml.safe_load(task_file.read_text())['status'] == 'integrated'


def _summary_chain(root: Path, *, completed: bool) -> None:
    """Register summary 200 -> child 201 -> grandchild 202 with one member on 202."""
    from graphtraj.execution.runner_results import assign_session_reports
    from graphtraj.graph.delivery_state import apply_delivery_state_request
    from graphtraj.graph.delivery_worldline import read_worldline
    from graphtraj.graph.task_graph import register_task, update_task_state
    from test_result_submission import result_project
    from test_task_graph import _task

    runner, _, _ = result_project(root)
    state = root / 'state'
    for task_id, name, parent in (('200', 'summary', None), ('201', 'child', '200'),
                                  ('202', 'grandchild', '201')):
        register_task(state, root, {**_task(task_id, name), 'parent_id': parent})
    event = update_task_state(state, root, {
        'task_id': '202', 'status': 'ready', 'active_team_ordinal': None, 'worktree': None,
        'branch': None, 'current_candidate': None, 'caused_by_event_ids': [],
        'evidence_refs': ['evidence.md'],
    })
    request = {'phase': 'start', 'task_id': '202', 'caused_by_event_ids': [event['event_id']],
               'evidence_refs': ['evidence.md'], 'worktree': 'worktrees/research',
               'branch': 'agent/202-grandchild',
               'members': {'first': {'role': 'researcher', 'session_ref': 'research@x4'}}}
    apply_delivery_state_request(state, root, request, request)
    directory = runner / 'sessions/research@x4'
    directory.mkdir()
    (directory / 'mapping.yml').write_text(yaml.safe_dump({
        'alias': 'research@x4', 'runtime': 'codex', 'session': 'native-x4', 'task_id': '202',
        'team_generation': 1, 'role': 'researcher', 'parent': 'research@x1',
        'retained_batch_file': 'batch.yml', 'worktree_path': str(root / 'worktrees/research'),
        'trace_file': 'events.jsonl', 'worker_pid': 1, 'runtime_pid': 1,
        'report_files': [str(path) for path in assign_session_reports('researcher', 'research@x4', 1, 1)],
    }))
    for alias in ('research@x1', 'research@x2', 'research@x3', 'research@x4'):
        (runner / 'sessions' / alias / 'execution.yml').write_text('outcome: completed\n')
    assert read_worldline(state, root)
    if completed:
        for task_file in (state / 'tasks').glob('*/task.yml'):
            task = yaml.safe_load(task_file.read_text())
            task_file.write_text(yaml.safe_dump({**task, 'status': 'integrated'}))


def test_task_members_cover_recursive_children_of_current_summaries(tmp_path: Path) -> None:
    """Grandchild members of an unfinished summary are current; a finished one is history."""
    _summary_chain(tmp_path / 'open', completed=False)
    current = members(tmp_path / 'open')
    assert '200' in current['scope']
    grandchild = next(member for member in current['members'] if member['alias'] == 'research@x4')
    assert grandchild == {**grandchild, 'task_id': '202', 'parent': 'research@x1',
                          'state': 'standby', 'retired': False}

    _summary_chain(tmp_path / 'done', completed=True)
    assert members(tmp_path / 'done')['members'] == []
    history = members(tmp_path / 'done', summary_task_id='200')
    assert history['scope'] == ['200']
    assert [member['alias'] for member in history['members']] == ['research@x4']
