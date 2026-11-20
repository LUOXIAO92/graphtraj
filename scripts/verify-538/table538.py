"""Task 538: print each case's phases and (a)/(b) observables from ui538.mjs's summary.json and observed.json.

    python table538.py <phase>/runs
Run 1 and run 2 sit side by side, so 'same result' is a line-by-line comparison.
"""
import json
import pathlib
import sys

out = pathlib.Path(sys.argv[1])
for run in ('run1', 'run2'):
    for case in ('G', 'S'):
        d = out / run / case
        if not (d / 'summary.json').exists():
            continue
        s = json.loads((d / 'summary.json').read_text())
        o = (json.loads((d / 'observed.json').read_text()) if (d / 'observed.json').exists()
             else {'tools': [], 'notices': []})
        phases = ' '.join(f"{x['phase']}={x['seconds']}{'' if x['ok'] else '(MISSED)'}" for x in s['timings'])
        send = [x for x in o['tools'] if x['send']]
        print(f"{run} {case}: reached {','.join(s['reached'])}")
        print(f"   phases {phases} | total {s['totalSeconds']} s | retries {s['retries']}")
        print(f"   (a) agents rows {len(o['tools'])}, IN shown in {sum(bool(x['inShown']) for x in o['tools'])}; "
              f"send card IN shown: {bool(send and send[0]['inShown'])}; "
              f"its Markdown message in IN: {bool(send and send[0]['markdownInIn'])}")
        print(f"   (b) notice blocks {len(o['notices'])}" + ''.join(
            f"\n       {n['file']}: graftling-section={n['graftlingSection']} sender-graphtraj={n['showsGraphtrajAsSender']}"
            f" repeated-lines={n['adjacentRepeatedLines']} markdown-source={n['markdownSource']}"
            for n in o['notices']))
