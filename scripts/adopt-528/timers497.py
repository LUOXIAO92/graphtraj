"""497: list every budget_idle_timer process (490 and the known interference), read only, never signals.

usage:
  timers497.py list <ps file> <runtime venv> [<install-start epoch> <install-end epoch>]
  timers497.py nt   <ps file> <runtime venv> <install-start> <install-end> <runner sessions dir> <task id> <out.json>
  timers497.py t    <ps file> <runtime venv> <install-start> <install-end> <runner sessions dir> <task id>
                    <nt.json> <task state dir> <end epoch>

<ps file> holds `ps -axww -o pid=,ppid=,stat=,lstart=,command=` (lstart is five words, local time).
A timer's argv (budget_idle_timer.start_idle_budget_timer): <python> -I -m graphtraj.execution.budget_idle_timer
<session directory> <token> <ended Worker pid>. Its budget-timer.yml holds {token, pid: null}: the pid is never
written, so a timer is matched to its Session by the session directory and token in its argv.
Classes (by process start time against I's install window): old (started before pip), new (after the install's
checks passed), during (inside the window; information). Timers stay NON-BLOCKING: exit 0 unless a CHECK is FAIL.
"""
import json, sys, time
from datetime import datetime
from pathlib import Path

import yaml

MODULE = '-m graphtraj.execution.budget_idle_timer'


def rows(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(errors='replace').splitlines():
        w = line.split()
        if len(w) < 9 or not w[0].isdigit():
            continue
        try:
            start = time.mktime(time.strptime(' '.join(w[3:8]), '%a %b %d %H:%M:%S %Y'))
        except ValueError:
            start = None
        out.append({'pid': int(w[0]), 'ppid': int(w[1]) if w[1].isdigit() else None, 'stat': w[2], 'start': start,
                    'command': ' '.join(w[8:])})
    return out


def timers(listing: list[dict], rt: str, window=None) -> list[dict]:
    found = []
    for r in listing:
        c = r['command']
        if MODULE not in c:
            continue
        argv = c.split()
        tail = c.split(MODULE, 1)[1].split()
        exe = argv[0]
        cls = 'unknown start'
        if window and r['start'] is not None:
            cls = 'old' if r['start'] < window[0] else ('new' if r['start'] > window[1] else 'during the install')
        kids = [f"{k['pid']}({k['stat']})" for k in listing if k['ppid'] == r['pid']]
        found.append({**r, 'executable': exe, 'production': exe.startswith(rt.rstrip('/') + '/'),
                      'session': tail[0] if tail else None, 'token': tail[1] if len(tail) > 1 else None,
                      'class': cls, 'children': kids})
    return found


def show(t: dict) -> str:
    start = time.strftime('%F %T', time.localtime(t['start'])) if t['start'] is not None else '?'
    exe = 'production .venv-runtime' if t['production'] else f"other: {t['executable']}"
    tok = (t['token'] or '?')[:8]
    return (f"timer pid {t['pid']} ppid {t['ppid']} stat {t['stat']} start {start} [{t['class']}] exe {exe} | "
            f"session {t['session']} token {tok}… | children {len(t['children'])}: {' '.join(t['children']) or 'none'}")


def window(args):
    """I's install window (start, end) as epochs; None when I has not recorded it (passed as 'x x')."""
    try:
        return (float(args[0]), float(args[1]))
    except (IndexError, ValueError):
        return None


def do_list(ps: Path, rt: str, args) -> int:
    found = timers(rows(ps), rt, window(args))
    zombies = sum(1 for t in found for k in t['children'] if '(Z' in k)
    print(f"budget_idle_timer processes: {len(found)} (production .venv-runtime {sum(t['production'] for t in found)}, "
          f"old {sum(t['class'] == 'old' for t in found)}, new {sum(t['class'] == 'new' for t in found)}; "
          f"children {sum(len(t['children']) for t in found)}, zombie children {zombies}) - NON-BLOCKING, never signalled")
    for t in found:
        print('  ' + show(t))
    return 0


failed = False


def check(label, ok, detail=''):
    global failed
    verdict = ok if isinstance(ok, str) else ('PASS' if ok else 'FAIL')
    failed |= verdict != 'PASS'
    print(f"CHECK {label}: {verdict}{(' (' + detail + ')') if detail else ''}")


def task_sessions(sessions: Path, task_id: str) -> dict:
    out = {}
    for d in sorted(sessions.glob(f'{task_id}-*')):
        try:
            rec = yaml.safe_load((d / 'budget-timer.yml').read_text()) or {}
        except (OSError, yaml.YAMLError):
            rec = {}
        out[str(d)] = rec.get('token') if isinstance(rec, dict) else None
    return out


def ours(t: dict, sessions: dict) -> bool:
    return t['session'] is not None and str(Path(t['session'])) in sessions


def do_nt(ps: Path, rt: str, args) -> int:
    win = window(args[:2]); sessions_dir, task_id, out = Path(args[2]), args[3], Path(args[4])
    sess = task_sessions(sessions_dir, task_id)
    print(f'Task {task_id} Sessions under {sessions_dir}: {len(sess)}')
    for d, tok in sess.items():
        print(f"  {Path(d).name}: budget-timer.yml token {(tok or 'none')[:8]}")
    found = [t for t in timers(rows(ps), rt, win) if ours(t, sess)]
    before = json.loads(out.read_text()) if out.is_file() else {}
    now = {str(t['pid']): {'start': t['start'], 'session': t['session'], 'class': t['class'], 'production': t['production'],
                           'current_token': sess.get(str(Path(t['session']))) == t['token']} for t in found}
    seen = {**before, **{k: v for k, v in now.items() if k not in before}}
    for pid, v in sorted(seen.items()):
        state = 'present' if pid in now else 'absent'
        start = time.strftime('%F %T', time.localtime(v['start'])) if v.get('start') else '?'
        print(f"  Task {task_id} timer pid {pid}: {state} | start {start} [{v['class']}] | "
              f"{'production .venv-runtime' if v['production'] else 'other executable'} | {Path(v['session']).name} | "
              f"token is the Session's current one: {v['current_token']}")
    out.write_text(json.dumps(seen, indent=1, sort_keys=True))
    new = [v for v in seen.values() if v['class'] == 'new' and v['production']]
    check(f'490 a timer started by the new version for a Task {task_id} Session is listed (start after the install, '
          f'production .venv-runtime)', bool(new) if win else 'BLOCKED (no install window: I-install-*.epoch missing)',
          f'{len(new)} new of {len(seen)} recorded; {len(now)} present now')
    return 1 if failed else 0


def do_t(ps: Path, rt: str, args) -> int:
    win = window(args[:2]); sessions_dir, task_id, nt, state, end = Path(args[2]), args[3], Path(args[4]), Path(args[5]), float(args[6])
    sess = task_sessions(sessions_dir, task_id)
    task = yaml.safe_load((state / 'task.yml').read_text()) or {}
    print(f"Task {task_id} status: {task.get('status')} | end time {time.strftime('%F %T', time.localtime(end))}")
    listing = rows(ps)
    present = {t['pid']: t for t in timers(listing, rt, win) if ours(t, sess)}
    recorded = json.loads(nt.read_text()) if nt.is_file() else {}
    judged = {int(p): v for p, v in recorded.items() if v['class'] == 'new'}
    for t in present.values():
        if t['class'] == 'new':
            judged.setdefault(t['pid'], {'start': t['start'], 'session': t['session'], 'class': 'new', 'production': t['production']})
    for pid, t in sorted(present.items()):
        if t['class'] != 'new':
            print(f"  old/not judged: {show(t)}")
    still = []
    for pid, v in sorted(judged.items()):
        alive = pid in present
        still += [pid] * alive
        print(f"  Task {task_id} new-version timer pid {pid} ({Path(v['session']).name}): {'PRESENT' if alive else 'gone'}")
    ended = task.get('status') in ('awaiting-integration', 'integrating', 'integrated')
    if not ended:
        check(f'490 every new-version timer of a Task {task_id} Session is gone after the Task end', 'PENDING',
              f"status {task.get('status')}: the Task has not ended; Main reruns T after acceptance")
    elif not judged:
        check(f'490 every new-version timer of a Task {task_id} Session is gone after the Task end', 'BLOCKED',
              'no new-version timer of a Task Session was observed (Nt recorded none)')
    else:
        recent = time.time() - end < 30
        check(f'490 every new-version timer of a Task {task_id} Session is gone after the Task end',
              (not still) if not (still and recent) else 'PENDING',
              f"{len(still)} of {len(judged)} still present" + ('; the end was < 30 s ago: rerun T in 30 s' if still and recent else ''))
    budget = yaml.safe_load((state / 'execution-budget.yml').read_text()) if (state / 'execution-budget.yml').is_file() else {}
    notices = (budget or {}).get('parent_notices') or []
    late = []
    for n in notices:
        at = ((n.get('event') or {}).get('occurred_at')) if isinstance(n, dict) else None
        try:
            epoch = datetime.fromisoformat(str(at)).timestamp() if at else None
        except ValueError:
            epoch = None
        if epoch is not None and epoch > end:
            late.append((n.get('key'), n.get('observer'), n.get('delivered'), at))
    print(f'Task {task_id} budget parent_notices: {len(notices)}; after the end: {len(late)}')
    for k in late:
        print(f'  after the end: key={k[0]} observer={k[1]} delivered={k[2]} occurred_at={k[3]}')
    check(f'490 no budget notice for Task {task_id} Sessions after the end', not [k for k in late if k[2]],
          f'{len(late)} after the end, {sum(1 for k in late if k[2])} delivered')
    return 1 if failed else 0


if __name__ == '__main__':
    op, ps, rt, rest = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4:]
    sys.exit({'list': do_list, 'nt': do_nt, 't': do_t}[op](ps, rt, rest))
