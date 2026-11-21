"""Task 545: print each case's phases and notice observables from ui545.mjs's summary.json / observed.json and
sessions545.mjs's session-record.txt.

    python table545.py <phase>/runs
notice form: block (the notice has its own trigger block) or in-turn (claimed inside a running turn, no block).
page order: SENT / BLOCK / GOT in document order (AFTER busy expects SENT BLOCK GOT). session record: each relay's
turn and step; 'opened its turn' = step 1 of a turn (no user input), 'inside a running turn' = a later step.
"""
import json
import pathlib
import sys

out = pathlib.Path(sys.argv[1])
for run in ('run1', 'run2'):
    for case in ('G', 'S', 'GI'):
        d = out / run / case
        if not (d / 'summary.json').exists():
            continue
        s = json.loads((d / 'summary.json').read_text())
        o = (json.loads((d / 'observed.json').read_text()) if (d / 'observed.json').exists()
             else {'tools': [], 'notices': []})
        phases = ' '.join(f"{x['phase']}={x['seconds']}{'' if x['ok'] else '(MISSED)'}" for x in s['timings'])
        dom = o.get('dom', {})
        print(f"{run} {case}: notice form {o.get('noticeForm', '?')} | reached {','.join(s['reached'])}")
        print(f"   phases {phases} | total {s['totalSeconds']} s")
        print(f"   page order {' '.join(o.get('order', [])) or '-'} | GOT lines {o.get('gotLines', '?')} | "
              f"user inputs {o.get('userInputs', '?')} | turnTrigger {dom.get('turnTrigger', '?')} "
              f"agentIncoming {dom.get('agentIncoming', '?')} relaySender {dom.get('relaySender', '?')} "
              f"contextText {dom.get('contextText', '?')}")
        for n in o['notices']:
            print(f"   {n['file']}: graftling-section={n['graftlingSection']} sender-graphtraj={n['showsGraphtrajAsSender']}"
                  f" repeated-lines={n['adjacentRepeatedLines']} markdown-source={n['markdownSource']}")
        rec = d / 'session-record.txt'
        if rec.exists():
            for line in rec.read_text().splitlines():
                if line.startswith(('session ', '  relay', 'no Main session')):
                    print(f"   record: {line.strip()}")
