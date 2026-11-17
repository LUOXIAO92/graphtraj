"""Rehearsal only: write header-format swarm archives for the N child and the member (471/478 formats).

usage: rehearse_fixtures.py <swarm sessions dir> <case>
  case: positive | e2big | bad466 | bad477

Archives are found by their first line's header (directory names are arbitrary here, as sha256 names are in
production). A Bash result is a tool_result item answering a Bash tool-call; agents calls are tool-calls named
mcp__agents__agents with input {action, feature, arguments} and their results as tool_result text (JSON).
"""
import json, sys
from pathlib import Path

sessions, case = Path(sys.argv[1]), sys.argv[2]
FAKE = 'sk-probe478fake' + 'value0000'
TOTAL = 30


def write(directory: str, session: str, events: list[dict]) -> None:
    path = sessions / directory / 'session.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({'header': {'id': f'claude:{session}', 'native': {'sessionId': session}}})]
    lines += [json.dumps({'seq': n + 1, **e}) for n, e in enumerate(events)]
    path.write_text('\n'.join(lines) + '\n')


def call(tid: str, name: str, payload: dict, text: str = '') -> dict:
    return {'type': 'assistant/message', 'data': {'content': [{'type': 'text', 'text': text},
            {'type': 'tool-call', 'id': tid, 'name': name, 'input': payload}]}}


def result(tid: str, content, error: bool = False) -> dict:
    return {'type': 'user/message', 'data': {'content': [{'type': 'tool_result', 'tool_use_id': tid,
            'content': content if isinstance(content, str) else json.dumps(content), 'is_error': error}]}}


# --- child: step 01 (n478-tool), step 02 (keyword), steps 03-.., the fake key, DONE-478 -------------------------
child = [{'type': 'user/message', 'data': {'content': [{'type': 'text', 'text': "scripted probe ... echo api_key=sk-probe478fake''value0000"}]}}]
bash1 = result('t1', 'n478-tool\n') if case != 'e2big' else result('t1', 'Error: spawn /bin/zsh E2BIG', True)
child += [call('t1', 'Bash', {'command': 'echo n478-tool && sleep 3'}, 'Now step 01.'), bash1,
          call('t2', 'Bash', {'command': "seq -f '478-02-%g' 1 400"}, 'Now step 02, marker KW478-ORCHID.'), result('t2', '478-02-1\n')]
n = 3
while len(child) < TOTAL - 3:
    child += [call(f't{n}', 'Bash', {'command': f"seq -f '478-{n:02d}-%g' 1 400"}, f'Now step {n:02d}.'), result(f't{n}', f'478-{n:02d}-1\n')]
    n += 1
child += [call('tk', 'Bash', {'command': "echo api_key=sk-probe478fake''value0000"}, 'Now step 43.'), result('tk', f'api_key={FAKE}\n'),
          {'type': 'assistant/message', 'data': {'content': [{'type': 'text', 'text': 'DONE-478'}]}}]
assert len(child) == TOTAL, len(child)
write('cdir', 'sess-c', child)
keyword_seq = next(i + 1 for i, e in enumerate(child) if 'KW478-ORCHID' in json.dumps(e))

# --- member: create, wait, status, three session_read calls, its own Bash ---------------------------------------
def doc(start, stop, redacted=True):
    events = [{'index': i, 'event': {'seq': i + 1, 'type': 'x', 'text': '[redacted]' if redacted else f'api_key={FAKE}'}}
              for i in range(start, stop)]
    return {'session': 'claude:sess-c', 'content': 'text', 'total': TOTAL, 'start': start, 'stop': stop, 'events': events}


def agents(tid, feature, arguments, answer):
    return [call(tid, 'mcp__agents__agents', {'action': 'execute', 'feature': feature, 'arguments': arguments}), result(tid, answer)]


last = None if case == 'bad477' else 'DONE-478'
member = agents('a1', 'create', {'name': 'n478'}, {'agent': 'c1', 'execution': 'e1', 'session': 'claude:sess-c'})
member += agents('a2', 'wait', {'agent': 'c1', 'timeout': 300}, {'agent': 'c1', 'execution': 'e1', 'state': 'ended', 'last_message': last})
member += agents('a3', 'status', {'agent': 'c1'}, {'agent': 'c1', 'configuration': 'opus_coding_team.advisor', 'model': 'claude-opus-5-5', 'last_message': last})
if case == 'bad466':
    member += agents('a4', 'session_read', {'agent': 'c1'}, doc(TOTAL - 4, TOTAL, redacted=False))
    member += agents('a6', 'session_read', {'agent': 'c1', 'search': 'KW478-ORCHID'},
                     {'session': 'claude:sess-c', 'total': TOTAL, 'search': 'KW478-ORCHID', 'hits': [{'index': TOTAL - 2, 'seq': TOTAL - 1}]})
else:
    member += agents('a4', 'session_read', {'agent': 'c1'}, doc(TOTAL - 5, TOTAL))
    member += agents('a5', 'session_read', {'agent': 'c1', 'start': -10, 'stop': -5}, doc(TOTAL - 10, TOTAL - 5))
    member += agents('a6', 'session_read', {'agent': 'c1', 'search': 'KW478-ORCHID'},
                     {'session': 'claude:sess-c', 'total': TOTAL, 'search': 'KW478-ORCHID',
                      'hits': [{'index': keyword_seq - 1, 'seq': keyword_seq, 'type': 'assistant/message'}]})
if case == 'bad477':   # the child's end pushed to the member after wait delivered it
    member.append({'type': 'user/message', 'data': {'content': [{'type': 'text', 'text': json.dumps(
        {'source': 'graphtraj', 'agent': 'c1', 'execution': 'e1', 'outcome': 'completed'})}]}})
member += [call('m1', 'Bash', {'command': 'echo member-bash-ok'}),
           result('m1', 'member-bash-ok\n') if case != 'e2big' else result('m1', 'Error: spawn /bin/zsh E2BIG', True)]
write('mdir', 'sess-m', member)
print(f'fixtures {case}: child {len(child)} events (keyword seq {keyword_seq}), member {len(member)} events')
