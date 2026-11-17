"""501: CPU of graftling's Claude live collection per streamed fragment, as a message grows (sandbox)."""
import json, sys, time, uuid
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from graftling.sessions.archive import SessionArchive
from graftling.sessions.claude import ClaudeJsonlCollector

root = Path(sys.argv[2]); root.mkdir(parents=True, exist_ok=True)
kind = sys.argv[3]  # text | json
total = int(sys.argv[4])
session = str(uuid.uuid4())
transcript = root / f'{session}.jsonl'
size = int(sys.argv[5]) if len(sys.argv) > 5 else 1
lines, parent = [], None
for i in range(size):
    u = str(uuid.uuid4())
    role = 'user' if i % 2 == 0 else 'assistant'
    lines.append(json.dumps({'type': role, 'uuid': u, 'parentUuid': parent, 'sessionId': session,
        'timestamp': '2026-11-18T00:00:00Z', 'message': {'role': role, 'id': f'm{i}', 'model': 'claude-opus-5-5',
        'content': [{'type': 'text', 'text': 'x' * 5000}]}}))
    parent = u
transcript.write_text('\n'.join(lines) + '\n')
archive = SessionArchive(root / 'archive', save_normalized_sessions=True)
c = ClaudeJsonlCollector(archive, session, root, 'exec-1')
c.bind(transcript)
api = 'msg_1'
c.accept_batch([({'type': 'stream_event', 'session_id': session, 'parent_tool_use_id': None,
                  'event': {'type': 'message_start', 'message': {'id': api}}}, 1)])
delta = ({'type': 'text_delta', 'text': 'abcdefghij'} if kind == 'text'
         else {'type': 'input_json_delta', 'partial_json': 'abcdefghij'})
marks, began, pos = {}, time.process_time(), 2
for n in range(1, total + 1):
    c.accept_batch([({'type': 'stream_event', 'session_id': session, 'parent_tool_use_id': None,
                      'event': {'type': 'content_block_delta', 'index': 0, 'delta': delta}}, pos)])
    pos += 1
    if n in (100, 300, 600, 1000, 2000):
        marks[n] = time.process_time()
prev, prev_n = began, 0
for n, t in marks.items():
    print(f'{kind}: fragments {prev_n + 1}-{n}: {(t - prev) / (n - prev_n) * 1000:.2f} ms CPU per single-fragment batch')
    prev, prev_n = t, n
print(f'{kind}: total {time.process_time() - began:.2f} s CPU for {total} fragments')
