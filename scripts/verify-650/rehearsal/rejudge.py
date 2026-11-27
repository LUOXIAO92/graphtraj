"""Task 650 correction 3 (Engineer, offline): re-judge the REAL retained evidence of the first VM sitting with the
driver's fixed criteria (vm/drive650.py's own functions). Argument: the evidence-live directory (scrubbed evidence
fetched by the steps; nothing is copied from it). Prints one line per item: verdict and a short observable.
"""
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('drive650', HERE / 'vm' / 'drive650.py')
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)
E = Path(sys.argv[1])


def records(case: str, marker: str) -> list[dict]:
    found: dict = {}
    for record in d.read_jsonl(E / case / 'starts-648.jsonl'):
        if any(marker in str(part) for part in record.get('argv') or []):
            found.setdefault(record.get('pid'), record)
    return list(found.values())


def show(case: str, item: str, verdict: str, observable: str) -> None:
    print(f'{case} {item}: {verdict} {d.short(observable, 300)}')


stream = d.claude_stream((E / 'claude' / 'claude-stdout.txt').read_text(encoding='utf-8', errors='replace'))
show('claude', 'O3', *d.o3_judgement(stream))
print(f'claude init plugins: {[p.get("name") for p in stream["init"].get("plugins") or []]}')

hosts = records('pi', 'graftling.pi.host')
node, venv = hosts[0]['ppid'], hosts[0]['prefix']
ok, text, other = d.own_records(records('pi', 'graftling.mcp'), node, venv)
show('pi', 'H5', 'PASS' if ok else 'FAIL', f'{text}; others (OBSERVED): {other}')

for case in ('dsh', 'dsh-nonascii'):
    hosts = records(case, 'graftling.dsh.host')
    node, venv = hosts[0]['ppid'], hosts[0]['prefix']
    ok_h, text_h, _ = d.own_records(hosts, node, venv)
    ok_m, text_m, other = d.own_records(records(case, 'graftling.mcp'), node, venv)
    named = all(d.same_path(r.get('executable'), Path(venv) / 'Scripts' / 'python.exe') for r in hosts)
    show(case, 'D4 (records)', 'PASS' if ok_h and ok_m and named else 'FAIL',
         f'host {text_h}; MCP {text_m}; host record executable is the venv python {named}; others (OBSERVED): {other}')

events = d.json_events((E / 'pi-caller' / 'pi-stdout.txt').read_text(encoding='utf-8', errors='replace'))
first = d.first_bash(events)
ok = d.status_answered(events[:first]) and 'authority-denied' not in json.dumps(events[:first])
show('pi-caller', 'H6', 'PASS' if d.subagent_calls(events) and ok else 'FAIL',
     f'subagents calls {d.subagent_calls(events)}; status result before the bash call {ok} ({first} of {len(events)} events)')

text, code = d.outcome_file(E / 'claude-caller' / 'o4-context.txt')
show('claude-caller', 'O4', *d.o4_judgement(text, code))
