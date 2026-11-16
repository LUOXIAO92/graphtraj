"""Task 490 real-host helper, run by steps.zsh with the candidate venv's Python inside the isolated project.

    python -I x490.py prepare <project>            roles + Task 1 (1-minute budget, B) and Task 2 (30 minutes, A), ready
    python -I x490.py accept <project> <task id>    implementing -> reviewing -> awaiting-integration, then task integrate
    python -I x490.py timers <project>              budget_idle_timer processes whose Session lies in <project>
    python -I x490.py watch <project> <alias> <s>   follow the Leader's Worker a timer delivery started (B)
    python -I x490.py notices <project>             execution-budget-exceeded records per Session (time, key, delivery)

It never signals a process. Exit status: 0 = the observation passed, 1 = it failed, 2 = could not observe.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import yaml

MODEL = 'claude-opus-5-5'
BODY = '''---
difficulty: low
difficulty_reason: 490 real-host probe
execution_budget:
  estimated_minutes:
    total: {total}
  estimation_note: 490 probe
  planned_sessions:
    team_leader: 1
    engineer: 1
  correction_rounds: 0
  on_exceed: Notify the caller
---
# 490 probe {name}

Reply with one line DONE. Use no tool.
'''
TASKS = {'1': ('timer-b', 1), '2': ('timer-a', 30)}


def run(*argv: str, cwd: Path) -> subprocess.CompletedProcess:
    """Run one command in the project; echo a failure."""
    done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    if done.returncode:
        print('command failed:', ' '.join(argv), '\n', (done.stdout + done.stderr)[-800:])
    return done


def graphtraj() -> str:
    return str(Path(sys.executable).parent / 'graphtraj')


def task_record(project: Path, task_id: str) -> dict:
    """The Task's recorded state (task.yml)."""
    name = TASKS[task_id][0]
    return yaml.safe_load((project / '.graphtraj/state/tasks' / f'{task_id}-{name}' / 'task.yml').read_text())


def prepare(project: Path) -> int:
    roles = {
        'member': {'runtime': 'claude', 'model': MODEL, 'claude': {'permission_mode': 'auto'}},
        'leader': {'runtime': 'claude', 'model': MODEL, 'claude': {'permission_mode': 'auto'}},
        'engineer': {'runtime': 'claude', 'model': MODEL, 'claude': {'permission_mode': 'auto'}},
    }
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': roles, 'role_tree': {'member': {}, 'leader': {'engineer': {}}}}))
    work = project / '.graphtraj/probe-490'
    work.mkdir(exist_ok=True)
    (work / 'evidence.md').write_text('490 probe: ready.\n')
    graph = run(graphtraj(), 'task', 'graph', cwd=project)
    known = {t.get('task_id'): t for t in (yaml.safe_load(graph.stdout) or {}).get('tasks', [])} if graph.returncode == 0 else {}
    rc = 0
    for task_id, (name, total) in TASKS.items():
        if task_id in known:
            print(f'task {task_id} already registered ({known[task_id].get("status")}): register skipped')
            continue
        register = work / f'register-{task_id}.yml'
        register.write_text(yaml.safe_dump({
            'task_id': task_id, 'task_name': name, 'source': 'local:scratch/490', 'title': name,
            'body': BODY.format(total=total, name=name), 'dependencies': [], 'schema_version': 2,
            'parent_id': None, 'disposition': 'active', 'replaced_by': [], 'retirement_reason': None}))
        state = work / f'ready-{task_id}.yml'
        state.write_text(yaml.safe_dump({
            'task_id': task_id, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
            'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-490/evidence.md']}))
        rc |= run(graphtraj(), 'task', 'register', '--task-file', str(register), cwd=project).returncode
        rc |= run(graphtraj(), 'task', 'update', '--state-file', str(state), cwd=project).returncode
    doctor = run(graphtraj(), 'doctor', cwd=project)
    print('roles OK' if 'roles: OK' in doctor.stdout else 'roles NOT OK: ' + doctor.stdout[-600:])
    for task_id, (name, total) in TASKS.items():
        print(f'task {task_id} {name}: budget {total} min, status {task_record(project, task_id)["status"]}')
    return 1 if rc or 'roles: OK' not in doctor.stdout else 0


def accept(project: Path, task_id: str) -> int:
    """Stand in for an accepted result: the public state updates, then Main's task integrate."""
    record = task_record(project, task_id)
    if record['status'] == 'integrated':
        print(f'task {task_id} already integrated')
        return 0
    worktree = project / record['worktree']
    candidate = run('git', 'rev-parse', 'HEAD', cwd=worktree).stdout.strip()
    work = project / '.graphtraj/probe-490'
    for status in ('reviewing', 'awaiting-integration'):
        record = task_record(project, task_id)
        if record['status'] in ('awaiting-integration',) and status == 'reviewing':
            continue
        if record['status'] == status:
            continue
        change = work / f'{status}-{task_id}.yml'
        change.write_text(yaml.safe_dump({
            'task_id': task_id, 'status': status, 'active_team_ordinal': record['active_team_ordinal'],
            'worktree': record['worktree'], 'branch': record['branch'], 'current_candidate': candidate,
            'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-490/evidence.md']}))
        if run(graphtraj(), 'task', 'update', '--state-file', str(change), cwd=project).returncode:
            return 2
        print(f'task {task_id}: {status} (candidate {candidate[:12]})')
    if run(graphtraj(), 'task', 'integrate', '--task-id', task_id, '--', sys.executable, '-c', 'pass',
           cwd=project).returncode:
        return 2
    print(f'task {task_id}: {task_record(project, task_id)["status"]}')
    return 0


def processes() -> list[tuple[int, int, str, str]]:
    """(pid, ppid, state, command) of this user's processes."""
    shown = subprocess.run(['ps', '-xww', '-o', 'pid=,ppid=,stat=,command='], capture_output=True, text=True)
    rows = []
    for line in shown.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[0].isdigit():
            rows.append((int(parts[0]), int(parts[1]), parts[2], parts[3]))
    return rows


def timer_rows(project: Path) -> list[tuple[int, int, str, str]]:
    sessions = str(project / '.graphtraj/runner/sessions') + '/'
    return [row for row in processes()
            if 'graphtraj.execution.budget_idle_timer' in row[3] and sessions in row[3]]


def timers(project: Path) -> int:
    rows = timer_rows(project)
    print(f'budget timers of {project}: {len(rows)}')
    for pid, ppid, state, command in rows:
        print(f'  pid {pid} state {state} session {command.split()[-3].rsplit("/", 1)[-1]}')
    return 0


def heartbeat_pid(project: Path, alias: str) -> int | None:
    try:
        return yaml.safe_load((project / '.graphtraj/runner/sessions' / alias / 'heartbeat.yml').read_text())['worker_pid']
    except (OSError, TypeError, KeyError, yaml.YAMLError):
        return None


def watch(project: Path, alias: str, seconds: float) -> int:
    """Follow the Worker that a timer's delivery starts for ``alias``: who its parent is, and how it ends."""
    first = heartbeat_pid(project, alias)
    print(f'{alias}: worker before the delivery {first}; waiting up to {seconds:.0f} s for a new Worker')
    deadline = time.time() + seconds
    worker = None
    while time.time() < deadline:
        pid = heartbeat_pid(project, alias)
        if pid is not None and pid != first:
            worker = pid
            break
        time.sleep(0.5)
    if worker is None:
        print('no new Worker of the Leader appeared (no delivery resumed it)')
        return 2
    table = {pid: (ppid, state, command) for pid, ppid, state, command in processes()}
    parent = table.get(worker, (None, '', ''))[0]
    parent_command = table.get(parent, (None, '', ''))[2] if parent else ''
    print(f'new Leader Worker {worker}: parent {parent} '
          f'({"a budget_idle_timer" if "budget_idle_timer" in parent_command else parent_command[:100] or "gone"})')
    ended_at = None
    zombie_seconds = 0.0
    while time.time() < deadline + 240:
        row = {pid: state for pid, _, state, _ in processes()}.get(worker)
        now = time.time()
        if row is None:
            print(f'Worker {worker}: gone (collected) {0 if ended_at is None else now - ended_at:.1f} s after it ended')
            return 0
        if row.startswith('Z'):
            ended_at = ended_at or now
            zombie_seconds = now - ended_at
            if zombie_seconds > 15:
                print(f'Worker {worker}: ZOMBIE for {zombie_seconds:.0f} s (parent {parent})')
                return 1
        time.sleep(1)
    print(f'Worker {worker}: still running after the watch window')
    return 2


def notices(project: Path) -> int:
    for path in sorted((project / '.graphtraj/runner/sessions').glob('*/parent-notices.jsonl')):
        for line in path.read_text().splitlines():
            record = json.loads(line)
            identity = record.get('identity') or {}
            if identity.get('type') == 'execution-budget-exceeded':
                print(f'{time.strftime("%H:%M:%S", time.localtime(record["at"]))} {path.parent.name} '
                      f'{identity.get("key")} {record.get("delivery")}')
    return 0


def main() -> int:
    command, project = sys.argv[1], Path(sys.argv[2])
    if command == 'prepare':
        return prepare(project)
    if command == 'accept':
        return accept(project, sys.argv[3])
    if command == 'timers':
        return timers(project)
    if command == 'watch':
        return watch(project, sys.argv[3], float(sys.argv[4]))
    if command == 'notices':
        return notices(project)
    print(__doc__)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
