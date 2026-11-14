"""445 probe helper: roles, the probe Task, and what the idle Leader's planned end produced.

Usage (the scratch venv's Python): python -I probe.py <prepare|observe> PROJECT MODEL | plugins STREAM - | wait PROJECT SECONDS
Prints only facts read from the isolated project; it reads no credential.
"""
from __future__ import annotations

import json
import os
import re
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


# -- This dispatch's member (471) ---------------------------------------------

_CHOSEN: dict = {}


def born(path: Path) -> float:
    """Creation time (macOS st_birthtime; elsewhere st_ctime)."""
    status = path.stat()
    return getattr(status, 'st_birthtime', status.st_ctime)


def member(project: Path) -> tuple[str | None, dict, Path | None]:
    """The member this run's 01 dispatched: its alias, mapping and session directory, or (None, {}, None).

    471: the same isolated project can hold earlier dispatches' members ('...@team_leader', then
    '...@team_leader_2'), so neither the first nor a fixed alias is taken. The dispatch is 01's Main stream
    ($PROBE_OUT/01-main-stream.jsonl; its creation time is the dispatch time). Candidates are task 1's
    team_leader sessions created at/after it; when the stream holds the swarm result, only its exact alias
    (PROBE_ALIAS, if set, overrides). Exactly one must remain; otherwise a STOP line names the candidates and
    the caller does nothing.
    """
    directories = sorted(project.glob('.graphtraj/runner/sessions/1-*team_leader*'))
    stream = Path(os.environ.get('PROBE_OUT', '/nonexistent')) / '01-main-stream.jsonl'
    try:
        text, at = stream.read_text(encoding='utf-8', errors='replace'), born(stream)
    except OSError:
        text, at = None, None
    aliases = ([os.environ['PROBE_ALIAS']] if os.environ.get('PROBE_ALIAS') else
               sorted(set(re.findall(r'\\*"alias\\*"\s*:\s*\\*"(1-[^"\\]*team_leader[^"\\]*)', text or ''))))
    after = [d for d in directories if at is not None and born(d) >= at]
    chosen = [d for d in after if not aliases or d.name in aliases]
    reason = (f"dispatch {stream if text is not None else f'NOT READABLE ({stream})'}; task 1 team_leader sessions "
              f"{[d.name for d in directories]}; created at/after the dispatch {[d.name for d in after]}; "
              f"swarm result alias {aliases or 'not in the stream'}")
    line = (f'member chosen: {chosen[0].name} ({reason})' if len(chosen) == 1 else
            f'STOP: no single member of this dispatch, {len(chosen)} match ({reason}). Nothing is signalled.')
    if _CHOSEN.get('line') != line:
        print(line)
        _CHOSEN['line'] = line
    if len(chosen) != 1:
        return None, {}, None
    directory = chosen[0]
    mapping = directory / 'mapping.yml'
    return directory.name, (yaml.safe_load(mapping.read_text()) or {}) if mapping.is_file() else {}, directory


def dispatch_time() -> float | None:
    """Creation time of this run's 01 Main stream ($PROBE_OUT/01-main-stream.jsonl), or None."""
    try:
        return born(Path(os.environ.get('PROBE_OUT', '/nonexistent')) / '01-main-stream.jsonl')
    except OSError:
        return None


def budget_state(project: Path) -> tuple[dict | None, str]:
    """The probe Task's one execution-budget.yml, or (None, why)."""
    files = sorted(project.glob('.graphtraj/state/tasks/1-*/execution-budget.yml'))
    if len(files) != 1:
        return None, f'{len(files)} execution-budget.yml files {[str(f) for f in files]}'
    return (yaml.safe_load(files[0].read_text()) or {}), str(files[0])


def observe(project: Path, _model: str) -> int:
    """Print the budget record, this dispatch's Leader's execution end and Main's received budget events.

    471: only the member this run's 01 dispatched counts (member()); its elapsed_minutes:1 notice must name it as
    observer and occur at/after the dispatch. Anything that cannot be tied to it is reported and is never PASS."""
    alias, _mapping, directory = member(project)
    at = dispatch_time()
    if alias is None:
        print('CRITERION NOT SHOWN (no single member of this dispatch; see the STOP line above)')
        return 1
    state, where = budget_state(project)
    if state is None:
        print(f'STOP: cannot tie an execution-budget.yml to this dispatch: {where}. Nothing was picked.')
        print('CRITERION NOT SHOWN (no single execution-budget.yml)')
        return 1
    print('execution-budget.yml:', where)
    print('  started_at:', _instant(state['started_at']), ' planned end:', _instant(state['started_at'] + 60))
    print('  notifications:', state['notifications'], ' stopped:', state['stopped'])
    for notice in state['parent_notices']:
        print('  parent_notice:', notice['key'], 'delivered=', notice['delivered'], 'observer=', notice.get('observer'),
              'occurred_at=', notice.get('event', {}).get('occurred_at'))
    ended = None
    execution = directory / 'execution.yml'
    if execution.is_file():
        ended = execution.stat().st_mtime
        print('Leader', alias, 'last execution ended at', _instant(ended),
              'outcome', yaml.safe_load(execution.read_text()).get('outcome'))
    else:
        print('Leader', alias, 'has no execution.yml (its execution has not ended)')
    print('  budget-timer.yml present:', (directory / 'budget-timer.yml').is_file())
    events = []
    for inbox in project.glob('.graphtraj/runner/main-sessions/inbox/*.jsonl'):
        for line in inbox.read_text().splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if 'execution-budget-exceeded' in line:
                events.append((inbox, record))
    print('Main inbox execution-budget-exceeded records (every run; they name no member alias, so they are not tied to '
          'this dispatch and are not part of the criterion):', len(events))
    for inbox, record in events:
        print('  ', inbox.name, json.dumps(record, ensure_ascii=False)[:400])
    notices = [n for n in state['parent_notices'] if n['key'] == 'elapsed_minutes:1']
    other = [n.get('observer') for n in notices if n.get('observer') != alias]
    if other:
        print(f'  elapsed_minutes:1 notices of other members ignored: {other}')
    mine = [n for n in notices if n.get('observer') == alias]
    occurred = mine[0].get('event', {}).get('occurred_at') if mine else None
    when = datetime.fromisoformat(occurred).timestamp() if occurred else None
    ok = bool(mine and mine[0]['delivered'] and ended is not None and when is not None and when > ended
              and at is not None and when >= at)
    print('CRITERION', 'PASS' if ok else 'NOT SHOWN',
          f'(elapsed_minutes:1 delivered, observer = this dispatch\'s Leader {alias}, at/after the dispatch, '
          'observed after its execution ended)')
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
    """Poll for up to ``seconds`` (< 120) until this dispatch's Leader's elapsed_minutes:1 notice is delivered.

    Read only; touches no Agent. 471: a notice naming another member (an earlier dispatch) does not count."""
    deadline = time.time() + min(float(seconds), 115)
    while True:
        alias, _, _ = member(project)
        state, where = budget_state(project)
        notice = next((n for n in (state or {}).get('parent_notices', [])
                       if n['key'] == 'elapsed_minutes:1' and alias and n.get('observer') == alias), None)
        if notice and notice.get('delivered'):
            print(f'{datetime.now().astimezone().isoformat(timespec="seconds")} elapsed_minutes:1 delivered=True '
                  f'observer={notice.get("observer")} occurred_at={notice.get("event", {}).get("occurred_at")}')
            return 0
        if time.time() >= deadline:
            print(f'{datetime.now().astimezone().isoformat(timespec="seconds")} not delivered to this dispatch\'s '
                  f'member ({alias}) yet; notifications={state.get("notifications") if state else where}')
            return 0
        time.sleep(2)


if __name__ == '__main__':
    command, project, model = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    commands = {'prepare': prepare, 'observe': observe, 'plugins': plugins, 'wait': wait}
    raise SystemExit(commands[command](project, model))
