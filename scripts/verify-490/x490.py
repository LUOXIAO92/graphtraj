"""Task 490 real-host helper, run by steps.zsh with the candidate venv's Python inside the isolated project.

    python -I x490.py prepare <project>            roles + Task 6 (30 minutes, A) and Task 7 (5 minutes, B), ready
    python -I x490.py instruction <project> <id>    the probe Task's instruction: its registered body text
    python -I x490.py last <project> <alias>        the Session's last execution, outcome, last_agent_message, directory
    python -I x490.py decide <project> <alias> <task id> <s>   the alias's latest submission (agent-runner reports):
                                                   check its commit has probe-<task id>.txt, then decide-result accepted
    python -I x490.py integrate <project> <task id>   graphtraj task integrate -- <check probe-<task id>.txt exists>
    python -I x490.py timers <project>              budget_idle_timer processes whose Session lies in <project>
    python -I x490.py ended <project> <alias> <s>   the Session's current execution has its terminal record
    python -I x490.py settle <project> <leader> <engineer> <s>   both ended and no new execution for 20 s
    python -I x490.py engineer-timer <project> <engineer> <task id>   its timer runs with the current token, threshold ahead
    python -I x490.py watch <project> <leader> <engineer> <s>   the Leader Worker a timer delivery starts: parent, collection
    python -I x490.py delivered <project> <engineer> <leader>   the Engineer's budget notice reached the Leader
    python -I x490.py notices <project>             execution-budget-exceeded records per Session (time, key, delivery)

Tasks 1-4 of earlier runs are left registered and unused: Task 1's thresholds pass while the Team runs (R1);
Task 2 was moved to awaiting-integration without an acceptance (R2); Tasks 3 and 4 carry a body that said
'Reply with one line DONE. Use no tool.', against the launch instruction (R3); Task 5's body branched on the role and its
Leader took the engineer branch (R4).

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

{instruction}
'''


def commit_and_submit(task_id: str) -> str:
    """One Bash commit of probe-<id>.txt that also prints the full hash, then submit_result with it (realhost-402 step 2).

    submit_result refuses a short hash, and no second Bash command or file read can recover the full one (R3).
    """
    return (f"In your Worktree run exactly one Bash command: echo {task_id} > probe-{task_id}.txt && "
            f"git add probe-{task_id}.txt && git commit -qm 'Add probe {task_id}' && git rev-parse HEAD. "
            f"It prints the full 40-character commit hash. Then submit the result with the GraphTraj tasks tool "
            f"feature submit_result: commit = that full 40-character hash exactly as printed (never a short hash), "
            f"result_refs = [probe-{task_id}.txt], completion = 'probe {task_id} committed'.")


# The registered Task body and the launch instruction are this same text (R3: a body saying otherwise won).
# No double quotes or backslashes: steps.zsh writes it into a YAML double-quoted launch instruction.
INSTRUCTIONS = {
    # A: one root member.
    '6': commit_and_submit('6') + ' Then reply with one line DONE.',
    # B: the Leader's steps, unconditional (R4: a role-branching body let the Leader take the engineer branch).
    # The Engineer reads this body too; the instruction the Leader passes tells it to ignore these steps.
    '7': ('Launch exactly one child with role engineer for this Task using your GraphTraj agents tool, with the '
          'instruction: You are the engineer launched by the leader. Ignore the leader steps in the Task body. '
          'Reply with one line DONE and do nothing else. Wait for its result. '
          + commit_and_submit('7') + ' Then reply with one line DONE. If a GraphTraj budget notice arrives later, '
          'reply with one line NOTED and do nothing else.'),
}
TASKS = {'6': ('timer-a6', 30), '7': ('timer-b7', 5)}


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
            'body': BODY.format(total=total, name=name, instruction=INSTRUCTIONS[task_id]), 'dependencies': [], 'schema_version': 2,
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


def runner() -> str:
    return str(Path(sys.executable).parent / 'agent-runner')


def last(project: Path, alias: str) -> int:
    """Print the Session's last execution, outcome, last_agent_message and directory."""
    directory = session_dir(project, alias)
    terminal = read(directory / 'execution.yml')
    print(f'  last execution {terminal.get("execution_id")}: outcome {terminal.get("outcome")}')
    print(f'  last_agent_message: {terminal.get("last_agent_message")!r}')
    print(f'  Session directory: {directory}')
    return 0


def decide(project: Path, alias: str, task_id: str, seconds: float) -> int:
    """Accept the alias's latest submission through Main's public decision, as realhost-402 step 2 does.

    The decision sets the Task to awaiting-integration: the timer's exit condition this step observes.
    """
    deadline = time.time() + seconds
    while True:
        shown = run(runner(), 'reports', alias, cwd=project)
        submissions = ((yaml.safe_load(shown.stdout) or {}) if shown.returncode == 0 else {}).get('submissions') or []
        if submissions or time.time() >= deadline:
            break
        time.sleep(5)
    if not submissions:
        print(f'{alias} submitted nothing within {seconds:.0f} s')
        last(project, alias)
        return 2
    latest = submissions[-1]
    probe = f'probe-{task_id}.txt'
    worktree = project / task_record(project, task_id)['worktree']
    present = run('git', '-C', str(worktree), 'cat-file', '-e', f'{latest["candidate"]}:{probe}', cwd=project).returncode == 0
    evidence = f'decision-{task_id}.md'
    (project / evidence).write_text(f'Submission {latest["event_id"]} candidate {latest["candidate"]}: '
                                    f'{probe} present in the commit: {"yes" if present else "no"}\n')
    print(f'submission {latest["event_id"]} candidate {latest["candidate"]} result_refs {latest.get("result_refs")}; '
          f'{probe} in the commit: {"yes" if present else "no"}')
    if not present:
        return 2
    arguments = ['decide-result', '--submission-id', latest['event_id'], '--commit', latest['candidate'],
                 '--decision', 'accepted', '--reason', f'490 probe {probe} committed', '--evidence-ref', evidence]
    for ref in latest.get('evidence_refs') or []:
        arguments += ['--evidence-ref', ref]
    decided = run(runner(), *arguments, cwd=project)
    print(decided.stdout.strip()[-600:])
    status = task_record(project, task_id)['status']
    print(f'decision: {"OK" if decided.returncode == 0 else "NO"} (task {task_id} status {status})')
    return 0 if decided.returncode == 0 and status == 'awaiting-integration' else 2


def integrate(project: Path, task_id: str) -> int:
    """Main's task integrate with a validation that the accepted probe file is in the integrated tree."""
    check = f"from pathlib import Path; assert Path('probe-{task_id}.txt').is_file()"
    done = run(graphtraj(), 'task', 'integrate', '--task-id', task_id, '--', sys.executable, '-c', check, cwd=project)
    print(done.stdout.strip()[-600:])
    status = task_record(project, task_id)['status']
    print(f'integration: {"OK" if done.returncode == 0 and status == "integrated" else "NO"} (task {task_id} status {status})')
    return 0 if done.returncode == 0 and status == 'integrated' else 2


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


def session_dir(project: Path, alias: str) -> Path:
    return project / '.graphtraj/runner/sessions' / alias


def read(path: Path) -> dict:
    try:
        record = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        return {}
    return record if isinstance(record, dict) else {}


def execution_state(project: Path, alias: str) -> tuple[str | None, bool]:
    """(current execution id from mapping.yml, whether execution.yml is that execution's terminal record).

    execution.yml keeps the previous execution's outcome after a resume, so only a
    matching execution_id says the current execution ended.
    """
    directory = session_dir(project, alias)
    current = read(directory / 'mapping.yml').get('execution_id')
    terminal = read(directory / 'execution.yml')
    return current, current is not None and terminal.get('execution_id') == current and 'outcome' in terminal


def ended(project: Path, alias: str, seconds: float) -> int:
    deadline = time.time() + seconds
    while time.time() < deadline:
        current, done = execution_state(project, alias)
        if done:
            print(f'{alias}: execution {current} ended ({read(session_dir(project, alias) / "execution.yml").get("outcome")})')
            return 0
        time.sleep(1)
    print(f'{alias}: current execution {execution_state(project, alias)[0]} did not end within {seconds:.0f} s')
    return 2


def settle(project: Path, leader: str, engineer: str, seconds: float) -> int:
    """Both Sessions ended and no new execution started for 20 s (the Engineer's completion resumes the Leader)."""
    deadline = time.time() + seconds
    stable_since, last = None, None
    while time.time() < deadline:
        states = (execution_state(project, leader), execution_state(project, engineer))
        if all(done for _, done in states):
            if states != last:
                stable_since, last = time.time(), states
            elif time.time() - stable_since >= 20:
                print(f'settled: Leader execution {states[0][0]} and Engineer execution {states[1][0]} ended, '
                      f'no new execution for 20 s')
                return 0
        else:
            stable_since, last = None, None
        time.sleep(1)
    print(f'not settled within {seconds:.0f} s: Leader {execution_state(project, leader)}, '
          f'Engineer {execution_state(project, engineer)}')
    return 2


def engineer_timer(project: Path, engineer: str, task_id: str) -> int:
    """The Engineer's timer process runs with the token its budget-timer.yml names, and a threshold is ahead."""
    from graphtraj.execution.execution_budget import ExecutionBudgetMonitor

    directory = session_dir(project, engineer)
    token = read(directory / 'budget-timer.yml').get('token')
    rows = [row for row in timer_rows(project) if f' {directory} ' in f' {row[3]} ']
    current = [row for row in rows if token is not None and f' {token} ' in f' {row[3]} ']
    name = TASKS[task_id][0]
    monitor = ExecutionBudgetMonitor(project / '.graphtraj/state/tasks' / f'{task_id}-{name}', task_id, name)
    due = monitor.next_elapsed_threshold_at()
    print(f'Engineer timer record token: {token or "none"}; timer processes for its Session: '
          f'{[row[0] for row in rows]}; with the current token: {[row[0] for row in current]}')
    print('next threshold: ' + (time.strftime('%H:%M:%S', time.localtime(due)) + f' (in {due - time.time():.0f} s)'
                                if due is not None else 'none'))
    if due is None:
        print('STOP reason: thresholds passed while running (no threshold ahead)')
        return 2
    if not current:
        print('STOP reason: no Engineer timer with the current token (none started, or it already exited)')
        return 2
    return 0


def delivered(project: Path, engineer: str, leader: str) -> int:
    path = session_dir(project, engineer) / 'parent-notices.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []
    hits = [row for row in rows if (row.get('identity') or {}).get('type') == 'execution-budget-exceeded'
            and row.get('parent') == leader and row.get('delivery') == 'received']
    for row in hits:
        print(f'  {time.strftime("%H:%M:%S", time.localtime(row["at"]))} {row["identity"].get("key")} '
              f'-> {row["parent"]} ({row.get("input")})')
    return 0 if hits else 1


def heartbeat_pid(project: Path, alias: str) -> int | None:
    try:
        return yaml.safe_load((project / '.graphtraj/runner/sessions' / alias / 'heartbeat.yml').read_text())['worker_pid']
    except (OSError, TypeError, KeyError, yaml.YAMLError):
        return None


def watch(project: Path, leader: str, engineer: str, seconds: float) -> int:
    """Follow the Leader Worker that the Engineer's timer delivery starts: its parent, then its collection."""
    first = heartbeat_pid(project, leader)
    engineer_directory = str(session_dir(project, engineer))
    print(f'{leader}: Worker before the delivery {first}; waiting up to {seconds:.0f} s for a new Worker')
    deadline = time.time() + seconds
    worker = None
    while time.time() < deadline:
        pid = heartbeat_pid(project, leader)
        if pid is not None and pid != first:
            worker = pid
            break
        time.sleep(0.5)
    if worker is None:
        print('parent: NO (no new Leader Worker appeared; no delivery resumed it)')
        print('collected: NO (nothing to observe)')
        return 1
    table = {pid: (ppid, state, command) for pid, ppid, state, command in processes()}
    parent = table.get(worker, (None, '', ''))[0]
    command = table.get(parent, (None, '', ''))[2] if parent else ''
    timer_parent = 'graphtraj.execution.budget_idle_timer' in command and f' {engineer_directory} ' in f' {command} '
    print(f'parent: {"OK" if timer_parent else "NO"} (new Leader Worker {worker}, parent {parent}: '
          f'{command[:200] or "not found"})')
    ended_at = None
    while time.time() < deadline + 300:
        state = {pid: row for pid, _, row, _ in processes()}.get(worker)
        now = time.time()
        if state is None:
            print(f'collected: OK (Worker {worker} gone {0 if ended_at is None else now - ended_at:.1f} s after it ended)')
            return 0 if timer_parent else 1
        if state.startswith('Z'):
            ended_at = ended_at or now
            if now - ended_at > 15:
                print(f'collected: NO (Worker {worker} ZOMBIE for {now - ended_at:.0f} s under {parent})')
                return 1
        time.sleep(1)
    print(f'collected: NO (Worker {worker} still running after the watch window)')
    return 1


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
    if command == 'instruction':
        print(INSTRUCTIONS[sys.argv[3]])
        return 0
    if command == 'last':
        return last(project, sys.argv[3])
    if command == 'decide':
        return decide(project, sys.argv[3], sys.argv[4], float(sys.argv[5]))
    if command == 'integrate':
        return integrate(project, sys.argv[3])
    if command == 'timers':
        return timers(project)
    if command == 'ended':
        return ended(project, sys.argv[3], float(sys.argv[4]))
    if command == 'settle':
        return settle(project, sys.argv[3], sys.argv[4], float(sys.argv[5]))
    if command == 'engineer-timer':
        return engineer_timer(project, sys.argv[3], sys.argv[4])
    if command == 'delivered':
        return delivered(project, sys.argv[3], sys.argv[4])
    if command == 'watch':
        return watch(project, sys.argv[3], sys.argv[4], float(sys.argv[5]))
    if command == 'notices':
        return notices(project)
    print(__doc__)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
