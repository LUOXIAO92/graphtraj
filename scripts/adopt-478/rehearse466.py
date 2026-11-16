"""Rehearsal of N466r (nr466.py) on the REAL result shape: a tool_use of mcp__agents__agents {action, feature:
session_read, arguments} and a tool_result whose content is a JSON string {action, agent, session, ..., result: {...}}.

usage: rehearse466.py <scripts dir> <scratch dir>     prints REHEARSAL PASS/FAIL lines; exit 1 on any FAIL
"""
import json, shutil, subprocess, sys
from pathlib import Path

sd, base = Path(sys.argv[1]), Path(sys.argv[2])
FAKE = 'sk-probe478fake' + 'value0000'
CHILD, MEMBER, ALIAS, TASK = '5585dafa', '7777aaaa', '478-x-handover0-advisor@advisor', '478-production-adoption-466-477'
bad = 0


def write(d: Path, sid: str, evs: list[dict]) -> None:
    d.mkdir(parents=True, exist_ok=True)
    head = {'header': {'id': f'claude:{sid}', 'native': {'sessionId': sid}}}
    (d / 'session.jsonl').write_text('\n'.join(json.dumps(x) for x in [head] + evs) + '\n')


def setup(masked: bool) -> Path:
    project = base / ('masked' if masked else 'leak')
    shutil.rmtree(project, ignore_errors=True)
    sess = project / '.graphtraj/swarm/sessions'
    child = [{'seq': 8, 'type': 'assistant/message', 'data': {'content': [{'type': 'text', 'text': 'Now step 02, marker KW478-ORCHID.'}]}},
             {'seq': 58, 'type': 'assistant/message', 'data': {'content': [{'type': 'text', 'text': 'KW478-ORCHID again'}]}},
             {'seq': 409, 'type': 'user/message', 'data': {'content': [{'type': 'tool_result', 'content': f'api_key={FAKE}\n'}]}}]
    write(sess / 'c', CHILD, child)
    def doc(**kw):
        return json.dumps({'action': 'session_read', 'agent': None, 'session': f'claude:{CHILD}', 'execution': None, 'message': None,
                           'result': {'session': f'claude:{CHILD}', 'content': 'text', **kw}})
    ev = lambda i, s, text='x': {'index': i, 'seq': s, 'type': 'assistant/message', 'text': text}
    secret = '[redacted]' if masked else f'api_key={FAKE}'
    calls = [({}, doc(total=45, start=40, stop=45, events=[ev(i, 300 + i) for i in range(40, 45)])),
             ({'start': -10, 'stop': -5}, doc(total=45, start=35, stop=40, events=[ev(i, 300 + i) for i in range(35, 40)])),
             ({'search': 'KW478-ORCHID'}, doc(total=45, start=0, stop=45, search='KW478-ORCHID', hits_total=2,
                                              hits=[{'index': 0, 'seq': 8}, {'index': 2, 'seq': 58}])),
             ({'content': 'tools', 'search': 'probe478'}, doc(total=130, start=0, stop=130, search='probe478', hits_total=1,
                                                             hits=[{'index': 120, 'seq': 409, 'snippet': secret}])),
             ({'content': 'all', 'start': -6}, doc(total=140, start=134, stop=140, events=[ev(134, 409, secret)] + [ev(i, 400 + i) for i in range(135, 140)]))]
    member = []
    for n, (args, result) in enumerate(calls):
        args = {'session': f'claude:{CHILD}', **args}
        member.append({'seq': 2 * n + 1, 'type': 'assistant/message', 'data': {'content': [{'type': 'tool_use', 'id': f'u{n}', 'name': 'mcp__agents__agents',
                       'input': {'action': 'execute', 'feature': 'session_read', 'arguments': args}}]}})
        member.append({'seq': 2 * n + 2, 'type': 'user/message', 'data': {'content': [{'tool_use_id': f'u{n}', 'type': 'tool_result', 'content': result}]}})
    write(sess / 'm', MEMBER, member)
    mdir = project / '.graphtraj/core/runner/sessions' / ALIAS
    mdir.mkdir(parents=True)
    (mdir / 'mapping.yml').write_text(f'session: claude:{MEMBER}\ntask_id: "478"\n')
    raw = project / 'raw'; raw.mkdir()
    (raw / 'N466.txt').write_text(json.dumps({'launch_status': 'launched', 'agent': 'a', 'alias': ALIAS}))
    return project


def run(project: Path) -> tuple[int, str]:
    done = subprocess.run([sys.executable, '-I', str(sd / 'nr466.py'), str(project), str(project / 'raw'), f'claude:{CHILD}', TASK],
                          capture_output=True, text=True)
    return done.returncode, done.stdout + done.stderr


def expect(label: str, ok: bool) -> None:
    global bad
    bad += not ok
    print(f"REHEARSAL {'PASS' if ok else 'FAIL'}: {label}")


rc, out = run(setup(True)); print(out)
expect('N466r positive exits 0 with four CHECK PASS', rc == 0 and out.count(': PASS') == 4 and 'FAIL' not in out and 'BLOCKED' not in out)
expect('N466r never prints the fake value', FAKE not in out)
rc, out = run(setup(False)); print(out)
expect('N466r masking negative: credential masked FAIL, exit 1, value not printed',
       rc == 1 and 'CHECK 466 credential masked' in out and 'counts above' in out and ': FAIL (counts above)' in out and FAKE not in out)
expect('N466r masking negative: the other three still PASS', out.count(': PASS') == 3)
print(f"REHEARSAL 466 RESULT: {'ALL PASS' if bad == 0 else 'SOME FAILED'}")


def setup_b(masked: bool) -> Path:
    project = base / ('b-masked' if masked else 'b-leak')
    shutil.rmtree(project, ignore_errors=True)
    sess = project / '.graphtraj/swarm/sessions'
    child = [{'type': 'claude/observation', 'data': {'note': f'api_key={FAKE}'}},   # no seq: must be ignored, no crash
             {'seq': 408, 'type': 'assistant/message', 'data': {'content': [{'type': 'text', 'text': 'Now step 43.'}]}},
             {'seq': 409, 'type': 'user/message', 'data': {'content': [{'type': 'tool_result', 'content': f'api_key={FAKE}\n'}]}}]
    write(sess / 'c', CHILD, child)
    secret = 'api_key=\"[redacted]\"' if masked else f'api_key={FAKE}'
    wrap = lambda **kw: json.dumps({'action': 'session_read', 'session': f'claude:{CHILD}', 'execution': None, 'message': None,
                                    'result': {'session': f'claude:{CHILD}', 'content': 'tools', **kw}})
    calls = [({'content': 'tools', 'search': 'api_key'}, wrap(total=131, search='api_key', hits_total=1, hits=[{'index': 125, 'seq': 409, 'snippet': secret}])),
             ({'content': 'tools', 'search': '[redacted]'}, wrap(total=131, search='[redacted]', hits_total=0, hits=[])),
             ({'content': 'tools'}, wrap(total=131, start=126, stop=131, events=[{'index': 126, 'seq': 409, 'text': secret}] + [{'index': i, 'seq': 410 + i} for i in range(127, 131)]))]
    member = []
    for n, (args, result) in enumerate(calls):
        member.append({'seq': 2 * n + 1, 'type': 'assistant/message', 'data': {'content': [{'type': 'tool_use', 'id': f'u{n}', 'name': 'mcp__agents__agents',
                       'input': {'action': 'execute', 'feature': 'session_read', 'arguments': {'session': f'claude:{CHILD}', **args}}}]}})
        member.append({'seq': 2 * n + 2, 'type': 'user/message', 'data': {'content': [{'tool_use_id': f'u{n}', 'type': 'tool_result', 'content': result}]}})
    write(sess / 'm', MEMBER, member)
    mdir = project / '.graphtraj/core/runner/sessions' / ALIAS; mdir.mkdir(parents=True)
    (mdir / 'mapping.yml').write_text(f'session: claude:{MEMBER}\ntask_id: "478"\n')
    raw = project / 'raw'; raw.mkdir()
    (raw / 'N466b.txt').write_text(json.dumps({'launch_status': 'launched', 'alias': ALIAS}))
    return project


def run_b(project: Path) -> tuple[int, str]:
    done = subprocess.run([sys.executable, '-I', str(sd / 'nr466.py'), str(project), str(project / 'raw'), f'claude:{CHILD}', TASK, 'N466b'],
                          capture_output=True, text=True)
    return done.returncode, done.stdout + done.stderr


rc, out = run_b(setup_b(True)); print(out)
expect('N466br positive (child event without seq ignored): credential masked PASS, exit 0, no Traceback',
       rc == 0 and 'CHECK 466 credential masked' in out and ': PASS' in out and 'Traceback' not in out and FAKE not in out)
rc, out = run_b(setup_b(False)); print(out)
expect('N466br leak negative: credential masked FAIL, exit 1, value not printed',
       rc == 1 and ': FAIL (counts above)' in out and 'Traceback' not in out and FAKE not in out)
print(f"REHEARSAL 466 RESULT (with N466b): {'ALL PASS' if bad == 0 else 'SOME FAILED'}")
sys.exit(1 if bad else 0)
