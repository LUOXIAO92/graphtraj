"""471 rehearsal: verify-462 probe.py member() picks this dispatch's member, else STOP; nothing is signalled.

usage: python -I rehearse_member.py <empty work dir> <probe.py> [<src dir for the kill check>]
Builds an isolated project in <work dir>: dispatch 1 creates '1-p-handover0-team_leader@team_leader', dispatch 2
(a fresh 01 stream) '...@team_leader_2'. Expects the second; then a third dispatch with two new candidates and no
swarm alias must print STOP. Only files under <work dir> are written; no process is started or signalled.
"""
import importlib.util, json, os, sys, time
from pathlib import Path

work, probe = Path(sys.argv[1]), Path(sys.argv[2])
project, out = work / 'project', work / 'out'
sessions = project / '.graphtraj/runner/sessions'
sessions.mkdir(parents=True); out.mkdir(parents=True)
os.environ['PROBE_OUT'] = str(out)
os.environ.pop('PROBE_ALIAS', None)
if len(sys.argv) > 3:
    sys.path.insert(0, sys.argv[3])
spec = importlib.util.spec_from_file_location('probe462', probe)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
LEAD = '1-p-handover0-team_leader@team_leader'
calls = []
for name in ('kill', 'killpg'):   # record any signal attempt instead of sending it
    setattr(mod.os, name, lambda *a, _n=name: calls.append((_n, a)) if a[-1] != 0 else None)


def dispatch(alias, *members):
    stream = out / '01-main-stream.jsonl'
    stream.unlink(missing_ok=True)
    time.sleep(1.1)
    # As in a real stream-json line: the swarm result is a JSON string inside a tool_result (escaped quotes).
    text = json.dumps({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': json.dumps(
        {'launch_status': 'started', 'tasks': [{'task_id': '1', 'alias': alias}]})}]}}) if alias else '{"type":"system"}'
    stream.write_text(text + '\n')
    time.sleep(1.1)
    for m in members:
        (sessions / m).mkdir()
        (sessions / m / 'mapping.yml').write_text(f'agent: agent-{m[-2:]}\n')
    mod._CHOSEN.clear()


def show(label, expect):
    alias, mapping, directory = mod.member(project)
    ok = alias == expect
    print(f'REHEARSAL {label}: chose {alias!r}, expected {expect!r}: {"PASS" if ok else "FAIL"}')
    return ok


results = []
dispatch(LEAD, LEAD)
results.append(show('dispatch 1 (swarm alias in the stream)', LEAD))
dispatch(None, LEAD + '_2')
results.append(show('dispatch 2, before the swarm result arrives (only member born after it)', LEAD + '_2'))
with (out / '01-main-stream.jsonl').open('a') as stream:   # the same 01 Main then prints the swarm result
    stream.write(json.dumps({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': json.dumps(
        {'tasks': [{'task_id': '1', 'alias': LEAD + '_2'}]})}]}}) + '\n')
mod._CHOSEN.clear()
results.append(show('dispatch 2, swarm result (alias ..._2) in the stream', LEAD + '_2'))
dispatch(None, LEAD + '_3', LEAD + '_4')
results.append(show('ambiguous: two members after the dispatch, no swarm alias', None))
os.environ['PROBE_OUT'] = str(work / 'missing')
mod._CHOSEN.clear()
results.append(show('no dispatch stream', None))
if len(sys.argv) > 3:
    facts = work / 'facts.json'; facts.write_text('{}')
    print('kill() on the ambiguous project:')
    os.environ['PROBE_OUT'] = str(out)
    mod._CHOSEN.clear()
    rc = mod.kill(project, str(facts))
    print(f'kill() returned {rc}')
    results.append(rc != 0)
print(f'signals attempted: {calls or "none"}')
print('REHEARSAL RESULT:', 'PASS' if all(results) and not calls else 'FAIL')
sys.exit(0 if all(results) and not calls else 1)
