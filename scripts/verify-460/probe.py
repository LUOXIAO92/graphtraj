"""460 probe helper: roles, the probe Task, the member's running Bash tool, the kill, one Runner read and the CHECKs.

Usage (the scratch venv's Python, from the isolated project):
  python -I probe.py prepare PROJECT MODEL   roles (team_leader claude, permission_mode auto) and probe Task 1, ready
  python -I probe.py plugins STREAM -        0 only when graphtraj-claude-host is loaded
  python -I probe.py member PROJECT SECONDS  poll (<=100 s) until the member's Bash tool runs 'sleep 460': MEMBER-SLEEPING
  python -I probe.py kill PROJECT FACTS      refuse unless the Runner's record of the member's execution lists a live
                                             'sleep 460'; SIGKILL the member's Worker and Runtime group, start three
                                             bystanders, one Runner status read (its abnormal answer), CHECK 1-4,
                                             stop the bystanders
  python -I probe.py idle OUT -              0 unless an earlier probe Main (pid file in OUT) or 'sleep 460' lives
Prints only facts read from the isolated project and process tables. It reads no credential and prints whether
the member's tool marker is recorded, never its value. It signals only the member's recorded Worker and Runtime
group (step 02, after checking pid, start time, ownership and marker) and processes it started itself.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import yaml

TASK_ID = '1'
NAME = 'killed-member-tools-probe'
MEMBER_SLEEP = 'sleep 460'
MARKER_ENV = 'GRAFTLING_MEMBER_RUN'
BODY = '''---
difficulty: low
difficulty_reason: Scratch probe for 460
execution_budget:
  estimated_minutes:
    total: 30
  planned_sessions:
    team_leader: 1
  correction_rounds: 0
  estimation_note: One member whose Worker is killed while its Bash tool runs
  on_exceed: Report only
---
Follow the dispatch instruction exactly.
'''


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def run(*argv: str) -> subprocess.CompletedProcess:
    done = subprocess.run(argv, capture_output=True, text=True, timeout=300)
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
    work = project / '.graphtraj/probe-460'
    work.mkdir(exist_ok=True)
    register = work / 'register.yml'
    register.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'task_name': NAME, 'source': 'local:scratch/460', 'title': NAME, 'body': BODY,
        'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
        'replaced_by': [], 'retirement_reason': None}))
    state = work / 'state.yml'
    state.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
        'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-460/evidence.md']}))
    rc = 0
    if not list(project.glob('.graphtraj/state/tasks/1-*/task.yml')):
        rc = run(str(bin_dir / 'graphtraj'), 'task', 'register', '--task-file', str(register)).returncode
    (work / 'evidence.md').write_text('460 probe: ready for one member whose Bash tool runs sleep 460.\n')
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


# -- Records (read only) ----------------------------------------------------------

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


def runner_record(directory: Path | None, mapping: dict) -> tuple[dict, str | None]:
    """The Runner's tool-processes record of the mapped execution (460): marker, sidecar, reclaims."""
    if directory is None or not mapping.get('execution_id'):
        return {}, 'no mapped execution'
    path = directory / f"tool-processes-{mapping['execution_id']}.yml"
    try:
        record = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as error:
        return {}, f'{type(error).__name__}: {error}'
    if not isinstance(record, dict) or record.get('execution_id') != mapping['execution_id']:
        return {}, 'record names another execution'
    return record, None


def recorded(sidecar: object) -> tuple[list[dict], str | None]:
    if not isinstance(sidecar, str) or not sidecar:
        return [], 'no tool_descendants path'
    try:
        from graftling.tool_descendants import read_sidecar

        return read_sidecar(sidecar), None
    except (ImportError, OSError, ValueError) as error:
        return [], f'{type(error).__name__}: {error}'


def alive(pid: object) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def live(entry: dict) -> bool:
    """Whether a recorded descendant is still the same process (same pid, uid and start time)."""
    from graftling.tool_descendants import identity

    found = identity(entry['pid'])
    return found is not None and found.start == entry['start'] and found.uid == entry['uid']


def is_member_sleep(argv: str) -> bool:
    words = argv.split()
    return words[:2] in (['sleep', '460'], ['/bin/sleep', '460'])


def sleeping() -> dict[int, str]:
    """Live same-user processes whose command holds 'sleep 460' (read only): ps, plus argv through libproc."""
    found = {}
    try:
        listing = subprocess.run(['ps', '-axo', 'pid=,command='], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        listing = ''
    for line in listing.splitlines():
        pid, _, command = line.strip().partition(' ')
        if MEMBER_SLEEP in command and 'probe.py' not in command and pid.isdigit():
            found[int(pid)] = command[:160]
    try:
        from graftling.member_processes import _process_view, _user_pids

        for pid in _user_pids():
            view = _process_view(pid) if pid not in found and pid != os.getpid() else None
            command = ' '.join(view[0]) if view else ''
            if MEMBER_SLEEP in command and 'probe.py' not in command:
                found[pid] = command[:160]
    except (ImportError, OSError, ValueError):
        pass
    return found


def member_state(project: Path) -> str:
    alias, mapping, directory = member(project)
    record, error = runner_record(directory, mapping)
    entries, sidecar_error = recorded(record.get('tool_descendants'))
    running = bool(directory) and not (directory / 'execution.yml').exists()
    return (f'member={alias} execution={mapping.get("execution_id")} running={running} '
            f'worker_pid={mapping.get("worker_pid")} alive={alive(mapping.get("worker_pid"))} '
            f'runtime_pid={mapping.get("runtime_pid")} alive={alive(mapping.get("runtime_pid"))} '
            f'runner record={not error} tool_marker recorded={bool(record.get("tool_marker"))} '
            f'sidecar entries={len(entries)}{" (" + sidecar_error + ")" if sidecar_error else ""} '
            f"recorded live '{MEMBER_SLEEP}'={[e['pid'] for e in entries if is_member_sleep(e.get('argv', '')) and live(e)]}")


def member_cmd(project: Path, seconds: str) -> int:
    def done() -> bool:
        _, mapping, directory = member(project)
        record, error = runner_record(directory, mapping)
        entries, _ = recorded(record.get('tool_descendants'))
        return (not error and not (directory / 'execution.yml').exists()
                and any(is_member_sleep(entry.get('argv', '')) and live(entry) for entry in entries))

    deadline = time.time() + min(float(seconds), 100)
    while not done():
        if time.time() >= deadline:
            print(f'{now()} not yet: {member_state(project)}')
            return 0
        time.sleep(3)
    print(f'{now()} MEMBER-SLEEPING')
    print(member_state(project))
    return 0


# -- Signals: only after identity checks, or processes this probe started ----------

def kill_group(pid: int, label: str, killed: list) -> None:
    try:
        group = os.getpgid(pid)
    except ProcessLookupError:
        print(f'{label} {pid}: already gone')
        return
    if group == pid and group != os.getpgid(0):
        os.killpg(group, signal.SIGKILL)
        print(f'{label} {pid}: SIGKILL process group {group}')
    else:
        os.kill(pid, signal.SIGKILL)
        print(f'{label} {pid}: SIGKILL (process group {group} not its own; left)')
    killed.append({'label': label, 'pid': pid, 'group': group, 'at': time.time()})


def bystander(argv: list[str], marker: str | None) -> subprocess.Popen:
    """A detached bystander in its own session, as a tool shell; never the member's marker."""
    environment = {key: value for key, value in os.environ.items() if key != MARKER_ENV}
    if marker is not None:
        environment[MARKER_ENV] = marker
    return subprocess.Popen(argv, env=environment, start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def check(label: str, ok: bool, detail: str = '') -> bool:
    print(f'CHECK {"PASS" if ok else "FAIL"}: {label}' + (f' | {detail}' if detail else ''))
    return ok


def kill(project: Path, facts_file: str) -> int:
    """Kill the member's Worker and Runtime group, then one Runner status read and the four CHECKs."""
    from graftling.member_processes import find_marked_processes
    from graftling.tool_descendants import identity
    from graphtraj.execution.runner_heartbeat import ownership_is_held

    alias, mapping, directory = member(project)
    print(member_state(project))
    record, error = runner_record(directory, mapping)
    worker, runtime, marker = mapping.get('worker_pid'), mapping.get('runtime_pid'), record.get('tool_marker')
    if directory is None or (directory / 'execution.yml').exists():
        print("STOP: no member, or its execution already ended (execution.yml exists). Nothing was done.")
        return 1
    if error or not marker:
        print(f"STOP: no Runner tool-processes record for the mapped execution ({error}); the venv lacks the 460 fix "
              'or the Worker started before it. Nothing was done.')
        return 1
    if not ownership_is_held(directory, worker):
        print("STOP: the mapped Worker does not hold the Session's ownership lock. Nothing was done.")
        return 1
    entries, sidecar_error = recorded(record.get('tool_descendants'))
    print('before the kill: the descendants record lists', len(entries), 'entries:',
          [(entry['pid'], entry.get('argv', '')[:100]) for entry in entries],
          f'(error: {sidecar_error})' if sidecar_error else '')
    sleeps = [entry for entry in entries if is_member_sleep(entry.get('argv', '')) and live(entry)]
    shells = [entry for entry in entries if entry['pid'] in {item.get('ppid') for item in sleeps}]
    print(f"before the kill: recorded live '{MEMBER_SLEEP}': {[entry['pid'] for entry in sleeps]}; its recorded "
          f"parent (the Bash tool shell): {[(entry['pid'], entry.get('argv', '')[:60]) for entry in shells]}")
    if sidecar_error or not sleeps:
        print(f"STOP: the record lists no live '{MEMBER_SLEEP}' (the sleep ended, or the sampler missed it). "
              'Nothing was done.')
        return 1
    marked = find_marked_processes(marker)
    print(f'before the kill: {len(marked)} processes carry the member marker: '
          f'{[command[:100] for command in marked.values()]}')
    if not alive(runtime) or runtime not in marked:
        print("STOP: the recorded runtime_pid is gone or does not carry the member's marker. Nothing was done.")
        return 1
    worker_identity, runtime_identity = identity(worker), identity(runtime)
    if worker_identity is None or runtime_identity is None:
        print('STOP: the Worker or Runtime identity is unreadable. Nothing was done.')
        return 1

    killed: list = []
    # Pid and start time are checked again right before each signal.
    if (current := identity(worker)) is not None and current.start == worker_identity.start:
        os.kill(worker, signal.SIGKILL)
        killed.append({'label': 'worker', 'pid': worker, 'at': time.time()})
        print(f'worker {worker}: SIGKILL')
    deadline = time.time() + 15
    while ownership_is_held(directory, worker) and time.time() < deadline:
        time.sleep(0.1)
    if (current := identity(runtime)) is not None and current.start == runtime_identity.start:
        kill_group(runtime, 'member runtime', killed)
    deadline = time.time() + 15
    while alive(runtime) and time.time() < deadline:
        time.sleep(0.1)
    print('alive after kill:', {item['label']: alive(item['pid']) for item in killed},
          '| ownership held:', ownership_is_held(directory, worker))
    print('after the kill, before any read: recorded descendants alive:',
          [(entry['pid'], entry.get('argv', '')[:60]) for entry in entries if live(entry)])

    hold = [sys.executable, '-I', '-c', 'import time; time.sleep(900)']
    other, plain, mine = bystander(hold, uuid.uuid4().hex), bystander(hold, None), bystander(['/bin/sleep', '901'], None)
    time.sleep(0.5)
    print(f'bystanders: other-marker {other.pid} alive {other.poll() is None}, no-marker {plain.pid} alive '
          f'{plain.poll() is None}, own /bin/sleep 901 {mine.pid} alive {mine.poll() is None}')
    results: list = []
    reclaimed = status = None
    read_at = time.time()
    try:
        from graphtraj.execution.runner_status import status_aliases

        # The project's root caller reads the member's status: the Runner judges it abnormal and answers
        # (owner-exit record, Runtime termination confirmation, tool reclaim, one parent notice).
        status = status_aliases([alias], project).document
        print(f'status read: {time.time() - read_at:.1f} s:', json.dumps(status, ensure_ascii=False)[:600])
        execution = yaml.safe_load((directory / 'execution.yml').read_text()) if (directory / 'execution.yml').is_file() else {}
        receipt_file = directory / f"terminal-confirmation-{mapping['execution_id']}.yml"
        receipt = yaml.safe_load(receipt_file.read_text()) if receipt_file.is_file() else {}
        reclaimed = receipt.get('tool_processes')
        after, _ = runner_record(directory, mapping)
        print('terminal confirmation:', receipt_file.is_file(), '| tool_processes:', json.dumps(reclaimed, ensure_ascii=False))
        print('runner record reclaims:', len(after.get('reclaims') or []))
        results.append(check('1 member execution owner-exited and its Runtime end confirmed',
                             (execution.get('error') or {}).get('code') == 'owner-exited'
                             and receipt.get('terminal_confirmed') is True,
                             f"execution={execution.get('outcome')} receipt={receipt_file.name if receipt else None}"))
        stopped = {item.get('pid') for item in (reclaimed or {}).get('stopped', [])}
        want = {entry['pid'] for entry in sleeps + shells}
        results.append(check(f"2 the Runner record lists the tool shell and '{MEMBER_SLEEP}' stopped, remaining empty",
                             bool(reclaimed) and bool(shells) and want <= stopped and reclaimed.get('remaining') == []
                             and not reclaimed.get('error') and (after.get('reclaims') or [None])[-1] == reclaimed,
                             f'stopped={sorted(stopped)} expected={sorted(want)} '
                             f'remaining={(reclaimed or {}).get("remaining")} error={(reclaimed or {}).get("error")}'))
        left = [(entry['pid'], entry.get('argv', '')[:60]) for entry in entries if live(entry)]
        left_sleep = sleeping()
        results.append(check(f"3 none of the recorded tool processes and no '{MEMBER_SLEEP}' alive",
                             not left and not left_sleep, f'recorded alive={left} {MEMBER_SLEEP}={left_sleep}'))
        results.append(check('4 the three bystanders alive',
                             other.poll() is None and plain.poll() is None and mine.poll() is None,
                             f'other-marker={other.poll() is None} no-marker={plain.poll() is None} '
                             f'own /bin/sleep={mine.poll() is None}'))
    finally:
        for item in (other, plain, mine):
            if item.poll() is None:
                item.terminate()
            try:
                item.wait(5)
            except subprocess.TimeoutExpired:
                item.kill()
                item.wait(5)
        print(f'bystanders stopped: other {other.poll() is not None}, no-marker {plain.poll() is not None}, '
              f'own sleep {mine.poll() is not None}')
    Path(facts_file).write_text(json.dumps({
        'alias': alias, 'execution_id': mapping.get('execution_id'), 'worker_pid': worker, 'runtime_pid': runtime,
        'tool_descendants': record.get('tool_descendants'), 'recorded_before_kill': entries,
        'marked_before_kill': len(marked), 'killed': killed, 'read_at': read_at, 'status': status,
        'tool_processes': reclaimed, 'checks': results}, indent=2, default=str))
    print('== summary:', 'ALL PASS' if results and all(results) else f'{results.count(False)} FAIL of {len(results)}',
          f'| facts in {facts_file}')
    return 0 if results and all(results) else 1


PID_FILES = ('01-main.pid',)


def idle(out: Path, _unused: str) -> int:
    """0 when no earlier probe Main (pid file in ``out``) and no 'sleep 460' runs; signals nothing."""
    busy = {}
    for name in PID_FILES:
        try:
            pid = int((out / name).read_text().strip())
        except (OSError, ValueError):
            continue
        if alive(pid):
            busy[name] = pid
    found = sleeping()
    if not busy and not found:
        print('no earlier probe process alive')
        return 0
    print('STILL ALIVE from an earlier run:', {**{f'pid file {k}': v for k, v in busy.items()},
                                              **{f'{MEMBER_SLEEP} pid {k}': v for k, v in found.items()}})
    print(f"STOP: changed nothing. Wait for it to end, then rerun (a '{MEMBER_SLEEP}' ends 460 s after it started).")
    return 1


if __name__ == '__main__':
    command, target, extra = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    commands = {'prepare': prepare, 'plugins': plugins, 'member': member_cmd, 'kill': kill, 'idle': idle}
    raise SystemExit(commands[command](target, extra))
