"""Native Claude usage keeps provider identities through paging and UI replay."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from test_desktop_activity import prepare, query


def test_native_usage_fragments_and_replay_replace_one_api_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real usage aggregation counts two API IDs once, including across page replay."""
    monkeypatch.setattr('graphtraj.execution.runner_status.caller_runtime', lambda: None)

    def response(identity: str | None, output: int, uuid: str) -> dict:
        """Keep the native record UUID distinct from the provider response ID."""
        return {'type': 'assistant', 'sessionId': 'native', 'uuid': uuid,
                'message': {'id': identity, 'model': 'retained-model',
                            'content': [{'type': 'text', 'text': 'same text'}],
                            'usage': {'input_tokens': 11, 'cache_read_input_tokens': 7,
                                      'cache_creation_input_tokens': 2, 'output_tokens': output}}}

    records = [response('api-1', 1, 'first')]
    records += [{'type': 'user', 'message': {'content': 'native user text'}}] * 199
    records += [response('api-1', 5, 'fragment'), response('api-1', 5, 'replay'),
                response('api-2', 5, 'different-call'), response(None, 7, 'unknown-call')]
    prepare(tmp_path, 'claude', records)
    first = query(tmp_path, alias='research@x1')
    second = query(tmp_path, alias='research@x1', cursor=first['cursor'])
    replay = query(tmp_path, alias='research@x1')
    facts = [event['usage'] for event in first['events'] + second['events'] if event['kind'] == 'usage']
    assert len({fact['identity'] for fact in facts[:3]}) == 1
    assert facts[3]['identity'] != facts[0]['identity']
    assert not facts[4]['attributable']
    assert any(event.get('text') == 'native user text' for event in first['events'])
    assert all(event['model'] == 'retained-model' for event in second['events'] if event['kind'] == 'usage')

    # Exercise the unchanged desktop reducer without Node discovering the
    # protected Harness ancestors of the linked source Worktree.
    reducer = tmp_path / 'usage.ts'
    shutil.copy2(Path(__file__).parents[1] / 'desktop/electron/usage.ts', reducer)
    result = subprocess.run(['node', '--input-type=module', '-e',
        'import fs from "node:fs"; '
        f'import {{collect,records}} from {json.dumps(reducer.as_uri())}; '
        'const calls=new Map(); for(const page of JSON.parse(fs.readFileSync(0,"utf8"))) '
        'collect(calls,"fixture",page); console.log(JSON.stringify(records(calls)));'],
        input=json.dumps([first['events'], second['events'], replay['events']]),
        text=True, capture_output=True, timeout=15, check=True)
    calls = json.loads(result.stdout)
    owned = [call for call in calls if call['attributable']]
    assert len(owned) == 2
    assert sum(call['tokens']['input'] for call in owned) == 40
    assert sum(call['tokens']['output'] for call in owned) == 10


def test_retained_transport_trace_does_not_add_message_usage_to_result(tmp_path: Path) -> None:
    """Older SDK transport traces retain one aggregate result usage observation."""
    from graphtraj.runtimes.activity import TraceReader

    path = tmp_path / 'transport.jsonl'
    usage = {'input_tokens': 11, 'output_tokens': 5}
    records = [{'type': 'assistant', 'session_id': 'native',
                'message': {'id': 'api-1', 'content': [], 'usage': usage}},
               {'type': 'result', 'session_id': 'native', 'uuid': 'turn-1', 'usage': usage}]
    path.write_text(''.join(json.dumps(record) + '\n' for record in records))
    facts = [event['usage'] for event in TraceReader(path, 'claude', 'native').page()['events']
             if event['kind'] == 'usage']
    assert len(facts) == 1 and facts[0]['call_id'] == 'turn-1'
