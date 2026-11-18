"""468 production sample: CPU of the Worker that collects the agents-created Claude child's archive (read only).

usage: cpu468.py sample <project> <raw dir> <task id> <max seconds>   (Nw starts it in the background; ends itself)
       cpu468.py report <raw dir>                                      (Nr)

Which process: an agents child of a Task member is owned by a thread inside the member's own Runner Worker
(``-m graphtraj.execution.runner_worker``, argv names <runner>/sessions/<alias>/...; 452/459), and the Claude
archive collection of that child (graftling/sessions/archive.py, 468) runs in that owner. So the sampled process is
the Worker of the Task's member alias '<task id>-...'. While the member waits for the child, the member itself is
idle, so the Worker's CPU is the child's collection plus the wait. Raw ``ps -o pid,ppid,pcpu,time,etime,command``
lines every ~10 s; nothing is signalled. 475 production (468 R1, before 468): 0.84-0.97 CPU-s per wall-s; 468's
accepted AFTER < 0.25.
"""
import json, re, subprocess, sys, time
from pathlib import Path

BEFORE = (0.84, 0.97)
AFTER_LIMIT = 0.25


def now() -> str:
    return time.strftime('%H:%M:%S')


def seconds(text: str) -> float:
    """ps cumulative CPU time: [[dd-]hh:]mm:ss[.ss]."""
    days, _, rest = text.rpartition('-')
    parts = [float(p) for p in rest.split(':')]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    return (float(days) if days else 0.0) * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]


def workers(task_id: str) -> list[str]:
    out = subprocess.run(['ps', '-axww', '-o', 'pid=,command='], capture_output=True, text=True).stdout
    return [line.split(None, 1)[0] for line in out.splitlines()
            if '-m graphtraj.execution.runner_worker' in line and f'/sessions/{task_id}-' in line]


def child_running(project: Path, raw: Path) -> bool | None:
    """True while the N child's last execution is running (None: no record yet)."""
    name = (raw / 'N-child-name').read_text().strip() if (raw / 'N-child-name').is_file() else None
    for path in (project / '.graphtraj/swarm/control/agents').glob('*.json'):
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if name and record.get('name') == name:
            executions = record.get('executions') or []
            return bool(executions) and executions[-1].get('outcome') is None   # no outcome yet: still running
    return None


def sample(project: Path, raw: Path, task_id: str, limit: float) -> int:
    log = raw / 'Nw468-ps.txt'
    start = time.time()
    print(f'{now()} 468 sampler: waiting for the Worker of Task {task_id} (max {limit:.0f} s)', flush=True)
    pid = None
    while time.time() - start < limit:
        found = workers(task_id)
        if pid is None and found:
            pid = found[-1]
            print(f'{now()} Worker pid {pid}', flush=True)
        if pid is not None:
            line = subprocess.run(['ps', '-o', 'pid=,ppid=,pcpu=,time=,etime=,command=', '-p', pid],
                                  capture_output=True, text=True).stdout.strip()
            if not line:
                print(f'{now()} Worker {pid} gone', flush=True)
                break
            running = child_running(project, raw)
            with log.open('a') as stream:
                stream.write(json.dumps({'at': time.time(), 'child_running': running, 'ps': line[:300]}) + '\n')
            print(f'{now()} child_running={running} ps: {line[:200]}', flush=True)
        time.sleep(10 if pid else 2)
    print(f'{now()} == END 468 sampler', flush=True)
    return 0


def report(raw: Path) -> int:
    log = raw / 'Nw468-ps.txt'
    rows = []
    for line in log.read_text().splitlines() if log.is_file() else []:
        try:
            row = json.loads(line)
            fields = row['ps'].split(None, 5)
            rows.append((row['at'], bool(row['child_running']), fields[0], seconds(fields[3])))
        except (ValueError, KeyError, IndexError):
            continue
    busy = [r for r in rows if r[1]]
    pids = {r[2] for r in busy}
    print(f'468: {len(rows)} samples, {len(busy)} while the child ran, Worker pids {sorted(pids)} (raw: {log})')
    if len(busy) < 2 or len(pids) != 1 or busy[-1][0] - busy[0][0] < 60:
        print(f'CHECK 468 Worker CPU while the child worked: BLOCKED (fewer than 2 samples over >= 60 s of one Worker '
              f'while the child ran; see {log} and Nw468.txt)')
        return 1
    wall = busy[-1][0] - busy[0][0]
    rate = (busy[-1][3] - busy[0][3]) / wall
    print(f'468: Worker CPU {busy[-1][3] - busy[0][3]:.1f} s over {wall:.0f} s wall = {rate:.3f} CPU-s per wall-s; '
          f'475 production (468 R1): {BEFORE[0]}-{BEFORE[1]}; 468 accepted AFTER < {AFTER_LIMIT}')
    ok = rate < AFTER_LIMIT and rate < BEFORE[0]
    print(f"CHECK 468 Worker CPU below 475's 0.84-0.97 and < {AFTER_LIMIT}: {'PASS' if ok else 'FAIL'} ({rate:.3f})")
    return 0 if ok else 1


def window(raw: Path, span: float = 30.0) -> int:
    """515 (501 Leader's advice): Worker CPU over ``span`` s before and after the child's record first appears.

    The creation time is the first sample whose child record exists (child_running not None); samples are ~10 s
    apart, so each window rate uses the first and last sample inside it. Reported, never judged.
    """
    log = raw / 'Nw468-ps.txt'
    rows = []
    for line in log.read_text().splitlines() if log.is_file() else []:
        try:
            row = json.loads(line)
            rows.append((row['at'], row['child_running'], row['ps'].split(None, 5)[0], seconds(row['ps'].split(None, 5)[3])))
        except (ValueError, KeyError, IndexError):
            continue
    created = next((r[0] for r in rows if r[1] is not None), None)
    if created is None:
        print(f'REPORT 515 468 window: NOT OBSERVED (no sample with the child record; {len(rows)} samples in {log})'); return 0
    for label, low, high in (('before', created - span, created), ('after', created, created + span)):
        inside = [r for r in rows if low <= r[0] <= high and r[2] == rows[-1][2]]
        if len(inside) < 2 or inside[-1][0] - inside[0][0] <= 0:
            print(f'REPORT 515 468 Worker CPU {span:.0f} s {label} child creation: NOT OBSERVED ({len(inside)} samples)'); continue
        wall = inside[-1][0] - inside[0][0]
        print(f'REPORT 515 468 Worker CPU {span:.0f} s {label} child creation: {(inside[-1][3] - inside[0][3]) / wall:.3f} '
              f'CPU-s per wall-s ({inside[-1][3] - inside[0][3]:.1f} s over {wall:.0f} s, {len(inside)} samples; not blocking)')
    return 0


if __name__ == '__main__':
    if sys.argv[1] == 'window':
        sys.exit(window(Path(sys.argv[2])))
    if sys.argv[1] == 'sample':
        sys.exit(sample(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], float(sys.argv[5])))
    sys.exit(report(Path(sys.argv[2])))
