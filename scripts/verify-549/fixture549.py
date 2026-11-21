"""Task 549 rehearsal fixture: host-shaped records built from step S's real server results.

  python -I fixture549.py <server.json> <out directory>
Writes codex-rollout.jsonl (function_call + function_call_output = JSON of structuredContent), pi-session.jsonl
(toolCall + toolResult content = the YAML text) and doubled.jsonl (a Codex output carrying the YAML text AND the JSON,
the defect shape). count549.py must report once for the first two and TWICE for the third.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

items = json.loads(Path(sys.argv[1]).read_text())
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
codex, pi, doubled, exec_events = [], [], [], []
for n, item in enumerate(items):
    result = item['response']['result']
    name = f"mcp__graphtraj__{item['tool']}"
    text = result['content'][0]['text']
    sc = json.dumps(result['structuredContent'], ensure_ascii=False)
    call = {'type': 'function_call', 'name': name, 'arguments': json.dumps(item['arguments']), 'call_id': f'c{n}'}
    codex += [{'type': 'response_item', 'payload': call},
              {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': f'c{n}', 'output': sc}}]
    doubled += [{'type': 'response_item', 'payload': call},
                {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': f'c{n}',
                                                      'output': text + '\n' + sc}}]
    pi += [{'type': 'message', 'message': {'role': 'assistant', 'content': [
               {'type': 'toolCall', 'id': f't{n}', 'name': name, 'arguments': item['arguments']}]}},
           {'type': 'message', 'message': {'role': 'toolResult', 'toolCallId': f't{n}', 'toolName': name,
                                           'content': [{'type': 'text', 'text': text}],
                                           'details': {'server': 'graphtraj'}}}]
    # codex exec --json (0.171.0 exec_events.rs:262-276): item.completed mcp_tool_call with result.content and
    # result.structured_content, as event_processor_with_jsonl_output.rs:213-235 copies them.
    exec_events.append({'type': 'item.completed', 'item': {
        'id': f'item_{n}', 'type': 'mcp_tool_call', 'server': 'graphtraj', 'tool': item['tool'],
        'arguments': item['arguments'], 'result': {'content': result['content'],
                                                   'structured_content': result['structuredContent']},
        'error': None, 'status': 'completed'}})
exec_events.append({'type': 'item.completed', 'item': {'id': 'item_final', 'type': 'agent_message',
                                                       'text': 'DONE-549 ok ok ok ok ok ok'}})
human = ''.join(f'mcp: graphtraj/{i["tool"]} started\nmcp: graphtraj/{i["tool"]} (completed)\n' for i in items)
(out / 'human.stderr.txt').write_text(human + 'codex\nDONE-549 ok ok ok ok ok ok\n')
for file, rows in (('codex-rollout.jsonl', codex), ('pi-session.jsonl', pi), ('doubled.jsonl', doubled),
                   ('exec.jsonl', exec_events)):
    (out / file).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
print(f'fixtures: {out}')
