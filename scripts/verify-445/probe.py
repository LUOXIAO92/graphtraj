"""445 probe helper: roles, the probe Task, and what the idle Leader's planned end produced.

Usage (the scratch venv's Python): python -I probe.py <prepare|observe> PROJECT MODEL | plugins STREAM - | wait PROJECT SECONDS
Prints only facts read from the isolated project; it reads no credential.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

TASK_ID = '1'
NAME = 'idle-leader-probe'
BODY = '''---
difficulty: low
difficulty_reason: Scratch probe for 445
execution_budget:
  estimated_minutes:
    total: 1
  planned_sessions:
    team_leader: 1
  correction_rounds: 0
  estimation_note: One reply, then idle past the planned end
  on_exceed: Report only
---
Reply with exactly one line, PROBE DONE, and end your turn. Do not call any tool.
'''


def run(*argv: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    done = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=300)
    print(f'$ {" ".join(argv[-3:])} -> rc={done.returncode}')
    if done.returncode:
        print(done.stdout[-600:], done.stderr[-600:])
    return done


def prepare(project: Path, model: str) -> int:
    bin_dir = Path(sys.executable).parent
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'team_leader': {'runtime': 'claude', 'model': model, 'worktree_access': 'write',
                                  'reports': ['report.md']}},
        'role_tree': {'team_leader': {}},
    }))
    work = project / '.graphtraj/probe-445'
    work.mkdir(exist_ok=True)
    register = work / 'register.yml'
    register.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'task_name': NAME, 'source': 'local:scratch/445', 'title': NAME, 'body': BODY,
        'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
        'replaced_by': [], 'retirement_reason': None}))
    state = work / 'state.yml'
    state.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
        'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-445/evidence.md']}))
    rc = 0
    if not list(project.glob('.graphtraj/state/tasks/1-*/task.yml')):
        rc = run(str(bin_dir / 'graphtraj'), 'task', 'register', '--task-file', str(register)).returncode
    (work / 'evidence.md').write_text('445 probe: ready for one idle Leader.\n')
    for argv in (('task', 'update', '--state-file', str(state)), ('doctor',)):
        done = run(str(bin_dir / 'graphtraj'), *argv)
        rc = rc or done.returncode
        if argv == ('doctor',):
            print('roles OK' if 'roles: OK' in done.stdout else 'roles NOT OK: ' + done.stdout[-400:])
            rc = rc or ('roles: OK' not in done.stdout)
    graph = run(str(bin_dir / 'graphtraj'), 'task', 'graph')
    tasks = (yaml.safe_load(graph.stdout) or {}).get('tasks', [])
    ready = any(task['task_id'] == TASK_ID and task['status'] == 'ready' for task in tasks)
    print('task 1 ready' if ready else 'task 1 NOT ready: ' + graph.stdout[-400:])
    return rc or (not ready)


def _instant(value: float) -> str:
    return datetime.fromtimestamp(value).astimezone().isoformat(timespec='seconds')


def observe(project: Path, _model: str) -> int:
    """Print the budget record, the Leader's last execution end and Main's received budget events."""
    budget_files = sorted(project.glob('.graphtraj/state/tasks/1-*/execution-budget.yml'))
    if not budget_files:
        print('NO execution-budget.yml: the probe Task never started (see the dispatch output)')
        return 1
    state = yaml.safe_load(budget_files[0].read_text())
    print('execution-budget.yml:', budget_files[0])
    print('  started_at:', _instant(state['started_at']), ' planned end:', _instant(state['started_at'] + 60))
    print('  notifications:', state['notifications'], ' stopped:', state['stopped'])
    for notice in state['parent_notices']:
        print('  parent_notice:', notice['key'], 'delivered=', notice['delivered'], 'observer=', notice.get('observer'),
              'occurred_at=', notice.get('event', {}).get('occurred_at'))
    sessions = sorted(project.glob('.graphtraj/runner/sessions/*team_leader*'))
    ended = None
    for directory in sessions:
        execution = directory / 'execution.yml'
        if execution.is_file():
            ended = execution.stat().st_mtime
            print('Leader', directory.name, 'last execution ended at', _instant(ended),
                  'outcome', yaml.safe_load(execution.read_text()).get('outcome'))
        timer = directory / 'budget-timer.yml'
        print('  budget-timer.yml present:', timer.is_file())
    events = []
    for inbox in project.glob('.graphtraj/runner/main-sessions/inbox/*.jsonl'):
        for line in inbox.read_text().splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if 'execution-budget-exceeded' in line:
                events.append((inbox, record))
    print('Main inbox execution-budget-exceeded records:', len(events))
    for inbox, record in events:
        print('  ', inbox.name, json.dumps(record, ensure_ascii=False)[:400])
    delivered = [n for n in state['parent_notices'] if n['key'] == 'elapsed_minutes:1']
    occurred = delivered[0].get('event', {}).get('occurred_at') if delivered else None
    ok = bool(delivered and delivered[0]['delivered'] and delivered[0].get('observer', '').endswith('team_leader')
              and ended is not None and occurred is not None
              and datetime.fromisoformat(occurred).timestamp() > ended)
    print('CRITERION', 'PASS' if ok else 'NOT SHOWN',
          '(elapsed_minutes:1 delivered, observer = the Leader, observed after its execution ended)')
    return 0 if ok else 1


def plugins(stream: Path, _unused: str) -> int:
    """Print the init record's plugins; 0 only when graphtraj-claude-host is loaded."""
    for line in stream.read_text().splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get('type') == 'system' and record.get('subtype') == 'init':
            names = [plugin.get('name') for plugin in record.get('plugins', [])]
            print('init plugins:', names)
            print('mcp servers:', [(server.get('name'), server.get('status')) for server in record.get('mcp_servers', [])])
            loaded = 'graphtraj-claude-host' in names
            print('graphtraj-claude-host loaded:', 'YES' if loaded else 'NO')
            return 0 if loaded else 1
    print('graphtraj-claude-host loaded: NO (no init record in the stream)')
    return 1


def wait(project: Path, seconds: str) -> int:
    """Poll the probe's execution-budget.yml for up to ``seconds`` (< 120) without touching any Agent."""
    deadline = time.time() + min(float(seconds), 115)
    while True:
        files = sorted(project.glob('.graphtraj/state/tasks/1-*/execution-budget.yml'))
        state = yaml.safe_load(files[0].read_text()) if files else None
        if state:
            notice = next((n for n in state.get('parent_notices', []) if n['key'] == 'elapsed_minutes:1'), None)
            if notice and notice.get('delivered'):
                print(f'{datetime.now().astimezone().isoformat(timespec="seconds")} elapsed_minutes:1 delivered=True '
                      f'observer={notice.get("observer")} occurred_at={notice.get("event", {}).get("occurred_at")}')
                return 0
        if time.time() >= deadline:
            print(f'{datetime.now().astimezone().isoformat(timespec="seconds")} not delivered yet; '
                  f'notifications={state.get("notifications") if state else None}')
            return 0
        time.sleep(2)


if __name__ == '__main__':
    command, project, model = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    commands = {'prepare': prepare, 'observe': observe, 'plugins': plugins, 'wait': wait}
    raise SystemExit(commands[command](project, model))
