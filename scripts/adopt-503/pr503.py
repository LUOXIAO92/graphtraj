"""503 Pr: a Pi or DSH child of Main loaded GraphTraj's extension/tool with the installed graftling. Read only.

usage: pr503.py <project> <raw dir> <kind: pi|dsh> <child name> <runtime venv> <ps listing file> <since epoch>

Inputs (Main saves them as P prints):
  <raw>/P-<kind>-create.txt   Main's raw agents create result (or the exact error when the host could not start)
  <raw>/P-<kind>-reply.txt    the child's final reply (DONE-503-PI / DONE-503-DSH plus one result field)
  control record              <project>/.graphtraj/**/control/agents/*.json with name == <child name>
  archive                     <project>/.graphtraj/swarm/sessions/*/session.jsonl naming the child's execution id
CHECK lines: PASS, FAIL, PENDING (not yet saved / still running) or NOT OBSERVED (with the reason; reportable, not a
failure of the product). The text 'cannot find the installed graftling distribution' anywhere it looks is FAIL (the
395 failure mode). Processes: every GraphTraj process of a Pi/DSH host in the ps listing must run from <runtime venv>.
"""
import json
import re
import sys
from pathlib import Path

h, raw, kind, name, rt, psfile, since = (Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4],
                                         sys.argv[5].rstrip('/'), Path(sys.argv[6]), float(sys.argv[7]))
TOKEN = f'DONE-503-{kind.upper()}'
MISSING = 'cannot find the installed graftling distribution'
results = []


def check(label, verdict, detail=''):
    results.append(verdict)
    print(f"CHECK 503 {kind} {label}: {verdict}{' (' + detail + ')' if detail else ''}")


def read(p):
    try:
        return p.read_text(errors='replace')
    except OSError:
        return None


create, reply = read(raw / f'P-{kind}-create.txt'), read(raw / f'P-{kind}-reply.txt')
child, child_path = None, None
for g in ('.graphtraj/swarm/control/agents/*.json', '.graphtraj/*/control/agents/*.json', '.graphtraj/core/runner/control/agents/*.json'):
    for p in h.glob(g):
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        if d.get('name') == name and (child_path is None or p.stat().st_mtime > child_path.stat().st_mtime):
            child, child_path = d, p
if child is None:
    if create is None:
        check('child created', 'PENDING', f'no {name} record and no {raw}/P-{kind}-create.txt yet')
    elif MISSING in create:
        check('child created', 'FAIL', f'create result names: {MISSING}')
    else:
        first = next((l for l in create.splitlines() if l.strip()), '(empty)')[:200]
        check('child created', 'NOT OBSERVED', f'no {name} record; the host did not start; create result: {first}')
    print(f"503 {kind}: {'FAIL' if 'FAIL' in results else 'NOT OBSERVED' if 'NOT OBSERVED' in results else 'PENDING'}")
    sys.exit(1 if 'FAIL' in results else 0)

sel = child.get('selection') or {}
exs = child.get('executions') or []
print(f"child {name}: agent={child.get('agent')} runtime={child.get('runtime') or sel.get('runtime')} "
      f"configuration={sel.get('configuration')!r} model={sel.get('model')!r} executions={len(exs)} record={child_path}")
for ex in exs:
    print(f"  execution {ex.get('id')}: state={ex.get('state')} outcome={ex.get('outcome')} "
          f"error={(ex.get('error') or {}).get('code')} notification={ex.get('notification')}")
check('child created', 'PASS', f"agent {child.get('agent')}")
ended = [e for e in exs if e.get('state') == 'ended']
if not ended:
    check('execution ended completed', 'PENDING', 'still running: rerun Pr after the reply')
else:
    ok = all(e.get('outcome') == 'completed' for e in ended)
    check('execution ended completed', 'PASS' if ok else 'FAIL', ', '.join(f"{e.get('id')}={e.get('outcome')}" for e in ended))

# Archive: the child's session.jsonl (naming one of its execution ids, or its session id in the header).
ids = [e.get('id') for e in exs if e.get('id')]
sid = str(child.get('session') or '').split(':', 1)[-1]
archives = []
for f in (h / '.graphtraj/swarm/sessions').glob('*/session.jsonl'):
    text = read(f) or ''
    if (sid and sid in text.split('\n', 1)[0]) or any(i in text for i in ids):
        archives.append((f, text))
tool_calls, tool_results = [], []
for f, text in archives:
    for line in text.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        s = json.dumps(e)
        call_shape = re.search(r'"type": "(tool_use|tool_call|toolCall|function_call)"', s) or 'tool/call' in str(e.get('type'))
        result_shape = re.search(r'"type": "(tool_result|toolResult|function_call_output)"', s) or 'tool/result' in str(e.get('type'))
        names_tool = re.search(r'(tasks|agents)', s)
        if call_shape and names_tool:
            tool_calls.append(e.get('type'))
        if result_shape and names_tool:
            tool_results.append(e.get('type'))
print(f"archives: {[str(f) for f, _ in archives] or 'NOT FOUND'}; tool calls naming tasks/agents: {len(tool_calls)}; results: {len(tool_results)}")
if not archives:
    check('GraphTraj tool call made and answered (archive)', 'NOT OBSERVED', 'no archived Session of the child found; see the reply check')
else:
    check('GraphTraj tool call made and answered (archive)', 'PASS' if tool_calls and tool_results else 'FAIL',
          f'calls {len(tool_calls)} results {len(tool_results)}')
if reply is None:
    check(f'reply {TOKEN} with a result field', 'PENDING', f'save the child reply to {raw}/P-{kind}-reply.txt')
else:
    has = TOKEN in reply
    field = re.search(r'(task_id|status|state|agent|feature|503)', reply.replace(TOKEN, ''))
    check(f'reply {TOKEN} with a result field', 'PASS' if has and field else 'FAIL', f'token {has}; field {bool(field)}')

# The 395 failure text, anywhere this child could have written it since P.
hits = []
for label, text in (('create result', create), ('reply', reply), ('child record', json.dumps(child))):
    if text and MISSING in text:
        hits.append(label)
for f, text in archives:
    if MISSING in text:
        hits.append(str(f))
for base in (h / '.graphtraj/swarm', h / '.graphtraj/core/runner'):
    for p in base.rglob('*') if base.is_dir() else ():
        try:
            st = p.stat()
            if p.is_file() and st.st_mtime >= since and st.st_size < 20_000_000 and MISSING.encode() in p.read_bytes():
                hits.append(str(p))
        except OSError:
            continue
check(f"no '{MISSING}' text", 'FAIL' if hits else 'PASS', f'found in {sorted(set(hits))}' if hits else 'records, archive, logs since P')

# Processes of the host's GraphTraj part (Pi: graphtraj-session pi / the extension; DSH: graphtraj.interfaces.mcp,
# native_entry dsh, the tool): each must run from the runtime venv.
pats = {'pi': ('graphtraj-session pi', 'graphtraj/runtimes/pi/', 'graphtraj.interfaces.mcp', 'graphtraj-mcp'),
        'dsh': ('graphtraj.interfaces.mcp', 'graphtraj-mcp', 'graphtraj.runtimes.native_entry dsh', 'graphtraj/runtimes/dsh/')}[kind]
lines = [l for l in (read(psfile) or '').splitlines() if any(p in l for p in pats)]
foreign = [l for l in lines if f'{rt}/' not in l]
for l in lines:
    print(f"  process: {l[:220]}")
if not lines:
    check('GraphTraj processes run from .venv-runtime', 'NOT OBSERVED', 'none alive when Pr ran (the host may have ended them); run Pr before retire')
else:
    check('GraphTraj processes run from .venv-runtime', 'FAIL' if foreign else 'PASS',
          f'{len(lines)} listed, {len(foreign)} not under {rt}')
verdict = 'FAIL' if 'FAIL' in results else 'PENDING' if 'PENDING' in results else 'NOT OBSERVED' if 'NOT OBSERVED' in results else 'PASS'
print(f'503 {kind}: {verdict}')
print('AGENT', child.get('agent') or '')
sys.exit(1 if verdict == 'FAIL' else 0)
