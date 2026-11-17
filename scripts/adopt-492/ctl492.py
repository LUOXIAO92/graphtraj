"""492: production agents control records, read only (484 notification_error, 486 restart effect).

usage:
  ctl492.py snap <project> <out.json>            per execution: state, outcome, error code, notification,
                                                 notification_error, owner pids (process.*pid*, host)
  ctl492.py n484 <before.json> <after.json>       484 check after N (before = I's snapshot right before pip, else 00's)
  ctl492.py restart <before.json> <after.json>    486: every execution whose state changed across the Main restart
  ctl492.py mcp <claude pid> <ps listing file>    486: graphtraj-mcp / graphtraj.interfaces.mcp descendants of Main

Records: <project>/.graphtraj/swarm/control/agents/<agent>.json (graftling/control.py). Nothing is written to them.
484 (graftling/control.py): a push that raised records notification_error {code, message} only with notification
'unavailable' or 'unconfirmed'; a delivered end has none. Exit 1 when a CHECK is FAIL.
"""
import json, sys
from pathlib import Path

FINAL = ('unavailable', 'unconfirmed')
SETTLING = (None, 'pending', 'queueing', 'held', 'queued')


def owner(process) -> dict:
    process = process if isinstance(process, dict) else {}
    return {k: v for k, v in process.items() if 'pid' in k or k in ('host', 'owner')}


def snap(project: Path, out: Path) -> int:
    agents = {}
    for p in sorted((project / '.graphtraj/swarm/control/agents').glob('*.json')):
        try:
            d = json.loads(p.read_text(encoding='utf-8'))
        except (OSError, ValueError) as e:
            print(f'unreadable record {p.name}: {type(e).__name__}')
            continue
        agents[d.get('agent') or p.stem] = {
            'name': d.get('name'), 'parent': d.get('parent'), 'retired': d.get('retired_at') is not None,
            'executions': {str(x.get('id')): {
                'state': x.get('state'), 'outcome': x.get('outcome'), 'error': (x.get('error') or {}).get('code'),
                'notification': x.get('notification'), 'notification_error': x.get('notification_error'),
                'owner': owner(x.get('process'))} for x in d.get('executions') or [] if isinstance(x, dict)}}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(agents, indent=1, sort_keys=True))
    n = sum(len(a['executions']) for a in agents.values())
    errs = sum(1 for a in agents.values() for x in a['executions'].values() if x['notification_error'])
    print(f'control records snapshot {out.name}: agents={len(agents)} executions={n} with notification_error={errs}')
    return 0


def flat(path: Path) -> dict:
    d = json.loads(path.read_text())
    return {(a, e): {**x, 'name': v.get('name'), 'parent': v.get('parent')} for a, v in d.items() for e, x in v['executions'].items()}


failed = False


def check(label, ok, detail=''):
    global failed
    verdict = ok if isinstance(ok, str) else ('PASS' if ok else 'FAIL')
    failed |= verdict != 'PASS'
    print(f"CHECK {label}: {verdict}{(' (' + detail + ')') if detail else ''}")


def n484(before: Path, after: Path) -> int:
    b, a = flat(before), flat(after)
    changed, settled, new_ok, new_bad, bad_err = [], [], [], [], []
    for k, x in a.items():
        err, note = x.get('notification_error'), x.get('notification')
        if err and note not in FINAL:
            bad_err.append((k, note))
        if k in b:
            was = b[k].get('notification')
            if was != note:
                (settled if was in SETTLING else changed).append((k, was, note))
        else:
            (new_bad if note == 'delivered' and err else new_ok).append((k, note, bool(err)))
    print(f'484: before {before.name} {len(b)} executions, after {after.name} {len(a)}; new {len(new_ok) + len(new_bad)}')
    for k, was, now in settled:
        print(f'  settled since the snapshot (information): {k[0]}/{k[1]} {was} -> {now}')
    for k, was, now in changed:
        print(f'  CHANGED final notification: {k[0]}/{k[1]} {was} -> {now}')
    for k, note, err in new_ok + new_bad:
        print(f'  new execution {k[0]}/{k[1]} ({a[k].get("name")}): notification={note} notification_error={"present" if err else "none"}')
    for k, note in bad_err:
        print(f'  notification_error with notification={note}: {k[0]}/{k[1]} code={(a[k]["notification_error"] or {}).get("code")}')
    check('484 pre-existing executions keep their final notification', not changed, f'{len(changed)} changed, {len(settled)} settled from pending/held')
    check('484 new delivered executions have no notification_error', not new_bad and bool(new_ok),
          f'{len(new_ok)} new, {len(new_bad)} delivered with an error' + ('' if new_ok or new_bad else '; no new execution: did N run?'))
    check('484 notification_error only with notification unavailable|unconfirmed', not bad_err, f'{len(bad_err)} other')
    return 1 if failed else 0


def restart(before: Path, after: Path) -> int:
    b, a = flat(before), flat(after)
    moved = [(k, b[k], a.get(k)) for k in b if a.get(k) is None or a[k].get('state') != b[k].get('state')
             or a[k].get('outcome') != b[k].get('outcome')]
    print(f'486: executions before the restart {len(b)}, after {len(a)}; state changed across the restart: {len(moved)}')
    interrupted = []
    for k, was, now in moved:
        now = now or {}
        print(f"  {k[0]}/{k[1]} name={was.get('name')} parent={was.get('parent')} owner={was.get('owner')}: "
              f"{was.get('state')}/{was.get('outcome')} -> {now.get('state')}/{now.get('outcome')} error={now.get('error')}")
        if now.get('outcome') == 'interrupted':
            interrupted.append(k)
    check('486 no execution ended interrupted across the Main restart', not interrupted,
          f'{len(interrupted)} interrupted; {len(moved)} changed (listed above; other Tasks\' members may end normally meanwhile)')
    return 1 if failed else 0


def mcp(pid: str, listing: Path) -> int:
    rows = []
    for line in listing.read_text(errors='replace').splitlines():
        w = line.split(None, 2)
        if len(w) >= 2 and w[0].isdigit() and w[1].isdigit():
            rows.append((w[0], w[1], w[2] if len(w) > 2 else ''))
    kids, seen, todo = {}, set(), [pid]
    for p, pp, c in rows:
        kids.setdefault(pp, []).append((p, c))
    found = []
    while todo:
        cur = todo.pop()
        for p, c in kids.get(cur, []):
            if p in seen:
                continue
            seen.add(p); todo.append(p)
            if 'graphtraj.interfaces.mcp' in c or 'graphtraj-mcp' in c:
                found.append(f'{p} {c[:160]}')
    print(f'486: descendants of Main claude pid {pid}: {len(seen)}; graphtraj-mcp among them: {len(found)}')
    for f in found:
        print('  ' + f)
    check('486 no graphtraj-mcp server under the Claude Main (486 changes only graphtraj-mcp)',
          (not found) if rows and pid.isdigit() else 'BLOCKED', f'{len(found)} found' if rows else 'no ps listing')
    return 1 if failed else 0


if __name__ == '__main__':
    op = sys.argv[1]
    if op == 'snap':
        sys.exit(snap(Path(sys.argv[2]), Path(sys.argv[3])))
    if op == 'n484':
        sys.exit(n484(Path(sys.argv[2]), Path(sys.argv[3])))
    if op == 'restart':
        sys.exit(restart(Path(sys.argv[2]), Path(sys.argv[3])))
    if op == 'mcp':
        sys.exit(mcp(sys.argv[2], Path(sys.argv[3])))
    sys.exit(f'unknown operation {op}')
