"""450 probe helper: roles, the probe Task, and whether the member's escaped process was stopped and recorded.

Usage (the scratch venv's Python): python -I probe.py prepare PROJECT MODEL | plugins STREAM - |
    wait PROJECT SECONDS | observe PROJECT TAG
Prints only facts read from the isolated project and process argv; it reads no credential and signals nothing.
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
NAME = 'escaped-process-probe'
BODY = '''---
difficulty: low
difficulty_reason: Scratch probe for 450
execution_budget:
  estimated_minutes:
    total: 10
  planned_sessions:
    team_leader: 1
  correction_rounds: 0
  estimation_note: One Bash command that leaves a detached process, then one reply
  on_exceed: Report only
---
Run the one Bash command your instruction names, reply STARTED and end your turn.
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
                                  'reports': ['report.md'], 'claude': {'permission_mode': 'auto'}}},
        'role_tree': {'team_leader': {}},
    }))
    work = project / '.graphtraj/probe-450'
    work.mkdir(exist_ok=True)
    register = work / 'register.yml'
    register.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'task_name': NAME, 'source': 'local:scratch/450', 'title': NAME, 'body': BODY,
        'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
        'replaced_by': [], 'retirement_reason': None}))
    state = work / 'state.yml'
    state.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
        'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-450/evidence.md']}))
    rc = 0
    if not list(project.glob('.graphtraj/state/tasks/1-*/task.yml')):
        rc = run(str(bin_dir / 'graphtraj'), 'task', 'register', '--task-file', str(register)).returncode
    (work / 'evidence.md').write_text('450 probe: ready for one Leader that leaves a background process.\n')
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


def _records(project: Path) -> list[Path] | None:
    """Termination records of this dispatch's member only (471), or None when that member is uncertain (STOP printed).

    Its Runner session directory holds claude-termination-<execution_id>.yml; with a mapped execution, only that one."""
    _alias, mapping, directory = member(project)
    if directory is None:
        return None
    execution = mapping.get('execution_id')
    return sorted(directory.glob(f'claude-termination-{execution}.yml' if execution else 'claude-termination-*.yml'))


def wait(project: Path, seconds: str) -> int:
    """Poll for this dispatch's Leader's termination record for up to ``seconds`` (< 120); touches no Agent."""
    deadline = time.time() + min(float(seconds), 115)
    while True:
        found = _records(project) or []
        now = datetime.now().astimezone().isoformat(timespec='seconds')
        if found:
            print(f'{now} termination record present: {found[-1]}')
            return 0
        if time.time() >= deadline:
            print(f"{now} no termination record of this dispatch's member yet")
            return 0
        time.sleep(2)


def tagged_alive(tag: str) -> dict[int, str]:
    """Same-user probe processes: ``tag`` is a whole argv element after the probe's sleep code (read only).

    This excludes the observer itself and any shell whose command line merely mentions the tag.
    """
    import os

    from graftling.member_processes import _process_view, _user_pids

    alive = {}
    for pid in _user_pids():
        view = _process_view(pid)
        if (pid != os.getpid() and view and tag in view[0]
                and any('time.sleep(600)' in item for item in view[0])):
            alive[pid] = ' '.join(view[0])[:200]
    return alive


def observe(project: Path, tag: str) -> int:
    """Print escaped_processes per termination record; PASS when the tagged pid was found and stopped."""
    records = _records(project)
    if records is None:
        print("CRITERION NOT SHOWN (no single member of this dispatch; see the STOP line above)")
        return 1
    if not records:
        print("NO termination record of this dispatch's member under", project / '.graphtraj/runner/sessions')
        return 1
    stopped_tagged = set()
    for path in records:
        record = yaml.safe_load(path.read_text()) or {}
        escaped = record.get('escaped_processes')
        print(path.relative_to(project), 'runtime_pid', record.get('runtime_pid'),
              'process_group_closed', record.get('process_group_closed'))
        print('  escaped_processes:', json.dumps(escaped, ensure_ascii=False))
        if escaped:
            found = {item['pid'] for item in escaped.get('found', []) if tag in item.get('command', '')}
            stopped = {item['pid'] for item in escaped.get('stopped', []) if tag in item.get('command', '')}
            stopped_tagged |= found & stopped
    alive = tagged_alive(tag)
    print('tagged pids stopped per record:', sorted(stopped_tagged))
    print('tagged processes alive now:', alive or 'none')
    if alive:
        print('A live tagged process is left alone; it exits by itself 600 s after it started.')
    ok = bool(stopped_tagged) and not alive
    print('CRITERION', 'PASS' if ok else 'NOT SHOWN',
          '(the tagged pid is in escaped_processes.found and .stopped; no tagged process alive)')
    return 0 if ok else 1


if __name__ == '__main__':
    command, project, extra = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    commands = {'prepare': prepare, 'observe': observe, 'plugins': plugins, 'wait': wait}
    raise SystemExit(commands[command](project, extra))
