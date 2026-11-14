"""471 rehearsal for verify-445 / verify-450: their criterion and wait read only this dispatch's member's records.

usage: python -I rehearse_records.py <empty work dir> <445|450> <probe.py>
Builds an isolated project in <work dir>. Dispatch 1 created '...@team_leader' and left records (445: execution.yml and a
delivered elapsed_minutes:1 notice observed by it; 450: a claude-termination record). Dispatch 2 (a fresh 01 stream)
created '...@team_leader_2', which has no records yet: wait must not report the stale records and observe must not PASS.
Then _2's own records arrive: observe PASS. Then two members after a third dispatch, no swarm alias: STOP and not PASS;
no stream: STOP and not PASS. Writes only under <work dir>; starts and signals nothing (os.kill/killpg are recorders,
and 450's process listing tagged_alive is replaced by 'none alive', since no tagged process exists here).
"""
import contextlib, importlib.util, io, json, os, sys, time
from datetime import datetime
from pathlib import Path

work, which, probe = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
project, out = work / 'project', work / 'out'
sessions = project / '.graphtraj/runner/sessions'
sessions.mkdir(parents=True); out.mkdir(parents=True)
os.environ['PROBE_OUT'] = str(out)
spec = importlib.util.spec_from_file_location('probe' + which, probe)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
calls = []
for name in ('kill', 'killpg'):
    setattr(os, name, lambda *a, _n=name: calls.append((_n, a)))
if which == '450':
    mod.tagged_alive = lambda tag: {}
LEAD = '1-p-handover0-team_leader@team_leader'
TAG = 'probe450-second'
results = []


def clear():
    getattr(mod, '_CHOSEN', {}).clear()


def run(fn, *args):
    clear()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rc = fn(*args)
    text = buffer.getvalue()
    for line in text.splitlines():
        if line.startswith(('CRITERION', 'STOP', 'member chosen')) or 'termination record' in line or 'delivered' in line:
            print('    | ' + line[:230])
    return rc, text


def expect(label, ok):
    results.append(ok)
    print(f'REHEARSAL {label}: {"PASS" if ok else "FAIL"}')


def dispatch(alias, *members):
    stream = out / '01-main-stream.jsonl'
    stream.unlink(missing_ok=True)
    time.sleep(1.1)
    text = json.dumps({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': json.dumps(
        {'tasks': [{'task_id': '1', 'alias': alias}]})}]}}) if alias else '{"type":"system"}'
    stream.write_text(text + '\n')
    time.sleep(1.1)
    for m in members:
        (sessions / m).mkdir()
        (sessions / m / 'mapping.yml').write_text(f'agent: agent-{m[-2:]}\nexecution_id: ex{len(m)}\n')


def records(member, tag=None):
    """445: the member's execution ends, then its notice is delivered. 450: its termination record (tag stopped)."""
    d = sessions / member
    if which == '445':
        (d / 'execution.yml').write_text('outcome: completed\n')
        time.sleep(1.1)
        budget = project / '.graphtraj/state/tasks/1-idle-leader-probe/execution-budget.yml'
        budget.parent.mkdir(parents=True, exist_ok=True)
        import yaml
        state = yaml.safe_load(budget.read_text()) if budget.is_file() else {
            'started_at': time.time() - 90, 'notifications': [], 'stopped': False, 'parent_notices': []}
        state['parent_notices'].append({'key': 'elapsed_minutes:1', 'delivered': True, 'observer': member,
                                        'event': {'occurred_at': datetime.now().astimezone().isoformat()}})
        budget.write_text(yaml.safe_dump(state))
    else:
        item = {'pid': 4242, 'command': f"python -c 'import time; time.sleep(600)' {tag}"}
        (d / f'claude-termination-ex{len(member)}.yml').write_text(json.dumps(
            {'runtime_pid': 1, 'process_group_closed': True, 'escaped_processes': {'found': [item], 'stopped': [item]}}))


arg = 'model' if which == '445' else TAG
passed = lambda text: 'CRITERION PASS' in text
waited = (lambda text: 'delivered=True' in text) if which == '445' else (lambda text: 'termination record present' in text)

dispatch(LEAD, LEAD)
records(LEAD, TAG)            # dispatch 1's records (an earlier run; 450: same tag, the worst case for a stale read)
dispatch(LEAD + '_2', LEAD + '_2')
print('dispatch 2 created ..._2; only dispatch 1 has records:')
rc, text = run(mod.wait, project, '3')
expect('wait does not report dispatch 1 records as this dispatch\'s', not waited(text))
rc, text = run(mod.observe, project, arg)
expect('observe is not PASS on dispatch 1 records', not passed(text))
records(LEAD + '_2', TAG)
print("..._2's own records arrive:")
rc, text = run(mod.wait, project, '3')
expect("wait reports ..._2's record", waited(text))
rc, text = run(mod.observe, project, arg)
expect("observe PASS on ..._2's records", passed(text))
dispatch(None, LEAD + '_3', LEAD + '_4')
records(LEAD + '_3', TAG); records(LEAD + '_4', TAG)
print('ambiguous: dispatch 3 created ..._3 and ..._4 (both with records), no swarm alias:')
rc, text = run(mod.observe, project, arg)
expect('observe prints STOP and is not PASS', 'STOP' in text and not passed(text))
os.environ['PROBE_OUT'] = str(work / 'missing')
print('no dispatch stream:')
rc, text = run(mod.observe, project, arg)
expect('observe prints STOP and is not PASS', 'STOP' in text and not passed(text))
print(f'signals attempted: {calls or "none"}')
print(f'REHEARSAL RESULT {which}:', 'PASS' if all(results) and not calls else 'FAIL')
sys.exit(0 if all(results) and not calls else 1)
