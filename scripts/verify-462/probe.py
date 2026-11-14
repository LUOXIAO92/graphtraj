"""462 probe helper: roles, the probe Task, the member's Codex child, the kill, one reconciling read and the CHECKs.

Adapted from scripts/verify-459/probe.py. The member (Claude) creates a Codex child (gpt-6-luna) whose shell tool
runs 'sleep 462'. The child's owner is the member's Worker; its Runtime is the owned Codex app-server (the 'codex'
launcher, which leads its own process group with the native binary).

Usage (the scratch venv's Python):
  python -I probe.py prepare PROJECT MODEL   roles (team_leader claude, permission_mode auto; codex_child codex
                                             gpt-6-luna) and probe Task 1, ready
  python -I probe.py plugins STREAM -        0 only when graphtraj-claude-host is loaded
  python -I probe.py child PROJECT SECONDS   poll (<=100 s) until the member's turn ended and its child runs: CHILD-RUNNING
  python -I probe.py kill PROJECT FACTS      refuse unless the child's descendants record lists a live 'sleep 462';
                                             SIGKILL the child's owner and Runtime group, start three bystanders,
                                             one reconciling read, CHECK 1-4, stop the bystanders
  python -I probe.py idle OUT -              0 unless an earlier probe Main (pid file in OUT) or 'sleep 462' lives
  python -I probe.py stub PROJECT -          rehearsal only: a fake member, child record and processes, no model
Prints only facts read from the isolated project and process tables. It reads no credential and prints
whether the child's tool marker is recorded, never its value. It signals only the child's recorded owner Worker and
Runtime group (step 02, after checking them) and processes it started itself.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import yaml

TASK_ID = '1'
NAME = 'tool-processes-probe'
CHILD_SLEEP = 'sleep 462'
CODEX_MODEL = 'gpt-6-luna'
MARKER_ENV = 'GRAFTLING_MEMBER_RUN'
BODY = '''---
difficulty: low
difficulty_reason: Scratch probe for 462
execution_budget:
  estimated_minutes:
    total: 30
  planned_sessions:
    team_leader: 1
  correction_rounds: 0
  estimation_note: One agents-tool Codex child whose owner is killed while its shell tool runs
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
                                  'reports': ['report.md'], 'claude': {'permission_mode': 'auto'}},
                  # The agents tool's Codex child takes its settings from the one Codex role.
                  'codex_child': {'runtime': 'codex', 'model': CODEX_MODEL}},
        'role_tree': {'team_leader': {}},
    }))
    work = project / '.graphtraj/probe-462'
    work.mkdir(exist_ok=True)
    register = work / 'register.yml'
    register.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'task_name': NAME, 'source': 'local:scratch/462', 'title': NAME, 'body': BODY,
        'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
        'replaced_by': [], 'retirement_reason': None}))
    state = work / 'state.yml'
    state.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
        'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-462/evidence.md']}))
    rc = 0
    if not list(project.glob('.graphtraj/state/tasks/1-*/task.yml')):
        rc = run(str(bin_dir / 'graphtraj'), 'task', 'register', '--task-file', str(register)).returncode
    (work / 'evidence.md').write_text('462 probe: ready for one member with one agents-tool Codex child.\n')
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


# -- Records ------------------------------------------------------------------

_CHOSEN: dict = {}


def member(project: Path) -> tuple[str | None, dict, Path | None]:
    """The member 01 created: its alias, mapping and session directory.

    Candidates are every ``1-*team_leader*`` session. The one whose alias appears in 01's Main stream
    ($PROBE_OUT/01-main-stream.jsonl, the swarm result) is chosen when exactly one does; otherwise the one
    with the newest mapping.yml. Every candidate and the choice are printed once.
    """
    # A reserved second alias ('...@team_leader_2') is never the dispatched member.
    candidates = sorted(d for d in project.glob('.graphtraj/runner/sessions/1-*team_leader*')
                        if not d.name.endswith('@team_leader_2'))
    if not candidates:
        return None, {}, None
    key = tuple(candidates)
    if key not in _CHOSEN:
        stream = Path(os.environ.get('PROBE_OUT', '/nonexistent')) / '01-main-stream.jsonl'
        try:
            text = stream.read_text(encoding='utf-8', errors='replace')
        except OSError:
            text = ''
        named = [directory for directory in candidates if directory.name in text]
        mtime = lambda d: (d / 'mapping.yml').stat().st_mtime if (d / 'mapping.yml').is_file() else 0.0
        if len(named) == 1:
            chosen, why = named[0], f'its alias is in {stream.name}'
        else:
            chosen, why = max(candidates, key=mtime), (f'newest mapping.yml ({len(named)} aliases found in '
                                                       f'{stream.name if text else "no readable 01 stream"})')
        for directory in candidates:
            print(f'member candidate: {directory.name} mapping.yml mtime {mtime(directory):.0f} '
                  f'in 01 stream {directory in named}')
        print(f'member chosen: {chosen.name} ({why})')
        _CHOSEN[key] = chosen
    directory = _CHOSEN[key]
    mapping = directory / 'mapping.yml'
    return directory.name, (yaml.safe_load(mapping.read_text()) or {}) if mapping.is_file() else {}, directory


def core(project: Path, agent: str | None) -> dict:
    path = project / '.graphtraj/swarm/control/agents' / f'{agent}.json'
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        return {}


def child(project: Path, alias: str | None, reference: str | None) -> dict:
    """The member's one agents-tool child record (its parent is the alias or the core reference)."""
    found = []
    for path in sorted((project / '.graphtraj/swarm/control/agents').glob('agent-*.json')):
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if alias and record.get('parent') in {alias, reference} and record.get('host') != 'graphtraj-tasks':
            found.append(record)
    if len(found) > 1:
        print('NOTE: more than one child of the member:', [record['agent'] for record in found])
    return found[0] if found else {}


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


def member_terminal(project: Path) -> bool:
    """Whether the member's last execution has its terminal record (its turn ended)."""
    _, _, directory = member(project)
    return bool(directory) and (directory / 'execution.yml').is_file()


def poll(project: Path, seconds: str, done, label: str, state) -> int:
    deadline = time.time() + min(float(seconds), 100)
    while True:
        if done():
            print(f'{now()} {label}')
            return 0
        if time.time() >= deadline:
            print(f'{now()} not yet: {state()}')
            return 0
        time.sleep(3)


def facts_of(project: Path) -> tuple[str | None, dict, dict, dict]:
    alias, mapping, _ = member(project)
    record = child(project, alias, mapping.get('agent'))
    execution = (record.get('executions') or [{}])[-1]
    return alias, mapping, record, execution


def child_cmd(project: Path, seconds: str) -> int:
    def done():
        _, _, record, execution = facts_of(project)
        return (bool(record) and execution.get('state') == 'running'
                and bool((execution.get('process') or {}).get('runtime_pid')) and member_terminal(project)
                and bool(sleeping()))

    def state():
        alias, mapping, record, execution = facts_of(project)
        process = execution.get('process') or {}
        return (f'member={alias} turn ended={member_terminal(project)} worker_pid={mapping.get("worker_pid")} '
                f'child={record.get("agent")} execution={execution.get("id")} state={execution.get("state")} '
                f'worker_pid={process.get("worker_pid")} runtime_pid={process.get("runtime_pid")} '
                f'tool_marker recorded={bool(process.get("tool_marker"))} '
                f'tool_descendants recorded={bool(process.get("tool_descendants"))} '
                f'worker alive={alive(process.get("worker_pid"))} runtime alive={alive(process.get("runtime_pid"))} '
                f"'{CHILD_SLEEP}' alive={sorted(sleeping())}")

    code = poll(project, seconds, done, 'CHILD-RUNNING', state)
    print(state())
    return code


# -- Processes (read only unless named) -----------------------------------------

def sleeping() -> dict[int, str]:
    """Live same-user processes whose command holds ``sleep 462`` (read only): ps, plus argv read
    through libproc, which also works where ps is not allowed (the sandbox rehearsal)."""
    found = {}
    try:
        listing = subprocess.run(['ps', '-axo', 'pid=,command='], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        listing = ''
    for line in listing.splitlines():
        pid, _, command = line.strip().partition(' ')
        if CHILD_SLEEP in command and 'probe.py' not in command and pid.isdigit():
            found[int(pid)] = command[:160]
    try:
        from graftling.member_processes import _process_view, _user_pids

        for pid in _user_pids():
            view = _process_view(pid) if pid not in found and pid != os.getpid() else None
            command = ' '.join(view[0]) if view else ''
            if CHILD_SLEEP in command and 'probe.py' not in command:
                found[pid] = command[:160]
    except (ImportError, OSError, ValueError):
        # Optional: the guard runs before the venv exists; ps alone covers the real host.
        pass
    return found


def marked(marker: str) -> dict[int, str]:
    """Same-user processes carrying exactly this marker (a read-only scan)."""
    from graftling.member_processes import find_marked_processes

    return find_marked_processes(marker)


def env_entries(pids) -> dict[int, int | None]:
    """How many environment entries the marker scan can read per pid (None: unreadable or gone)."""
    from graftling.member_processes import _process_view

    views = {pid: _process_view(pid) for pid in sorted(pids)}
    return {pid: (len(view[1]) if view else None) for pid, view in views.items()}


def kill_group(pid: int, label: str, killed: list) -> None:
    if not alive(pid):
        print(f'{label} {pid}: already gone')
        return
    try:
        group = os.getpgid(pid)
    except ProcessLookupError:
        group = None
    if group is not None and group == pid and group != os.getpgid(0):
        os.killpg(group, signal.SIGKILL)
        print(f'{label} {pid}: SIGKILL process group {group}')
    else:
        os.kill(pid, signal.SIGKILL)
        print(f'{label} {pid}: SIGKILL (process group {group} not its own; left)')
    killed.append({'label': label, 'pid': pid, 'group': group, 'at': time.time()})


def control_process(marker: str | None) -> subprocess.Popen:
    """A detached bystander: own session, as a tool shell; never the child's marker."""
    environment = {key: value for key, value in os.environ.items() if key != MARKER_ENV}
    if marker is not None:
        environment[MARKER_ENV] = marker
    return subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(900)'],
                            env=environment, start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def user_sleep() -> subprocess.Popen:
    """A third bystander: a platform binary of the user's own, in its own session, not a descendant of the child."""
    return subprocess.Popen(['/bin/sleep', '901'], start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def check(label: str, ok: bool, detail: str = '') -> bool:
    print(f'CHECK {"PASS" if ok else "FAIL"}: {label}' + (f' | {detail}' if detail else ''))
    return ok


def recorded(sidecar: object) -> tuple[list[dict], str | None]:
    """The child's descendants record (entries, error); read only."""
    if not isinstance(sidecar, str) or not sidecar:
        return [], 'no tool_descendants fact'
    try:
        from graftling.tool_descendants import read_sidecar

        return read_sidecar(sidecar), None
    except (ImportError, OSError, ValueError) as error:
        return [], f'{type(error).__name__}: {error}'


def live(entry: dict) -> bool:
    """Whether a recorded descendant is still the same process (same pid, uid and start time)."""
    from graftling.tool_descendants import identity

    now = identity(entry['pid'])
    return now is not None and now.start == entry['start'] and now.uid == entry['uid']


def is_child_sleep(argv: str) -> bool:
    return argv.split()[:2] in (['sleep', CHILD_SLEEP.split()[1]], ['/bin/sleep', CHILD_SLEEP.split()[1]])


def ancestry(sleeps: list[dict], marker: str) -> None:
    """Print each live recorded sleep's ancestors up to pid 1, read only.

    pid, ppid, pgid, argv[:60], whether the environment is readable and whether it holds exactly the
    child's marker: booleans only, never a value.
    """
    from graftling.member_processes import _process_view
    from graftling.tool_descendants import identity

    for entry in sleeps:
        print(f"ancestry of recorded '{CHILD_SLEEP}' {entry['pid']} (read only):")
        pid, seen = entry['pid'], set()
        while pid > 1 and pid not in seen:
            seen.add(pid)
            now = identity(pid)
            if now is None:
                print(f'  pid {pid}: gone or unreadable')
                break
            view = _process_view(pid)
            argv = ' '.join(view[0])[:60] if view else ''
            readable = bool(view and view[1])
            carries = readable and f'{MARKER_ENV}={marker}' in view[1]
            print(f'  pid {pid} ppid {now.ppid} pgid {now.pgid} argv {argv!r} env readable {readable} '
                  f'carries child marker {carries}')
            pid = now.ppid


def termination_records(directory: Path, since: float) -> list[Path]:
    """The owner's codex-termination-*.yml written at or after ``since`` (read only)."""
    return sorted(path for path in directory.glob('codex-termination-*.yml') if path.stat().st_mtime >= since - 1)


def kill(project: Path, facts_file: str) -> int:
    """Kill only the child's app-server group; the owner stays alive and must reclaim. CHECK A-D.

    CHECK A: a recorded 'sleep 462' is alive right after the app-server is gone (the residue was observed).
    CHECK B: the owner's codex-termination record (or, after 30 s without one, one reconciling read) lists that
             sleep, same pid, in ``stopped``; ``remaining`` is empty; no error. Nothing to act on fails.
    CHECK C: no recorded descendant and no 'sleep 462' alive afterwards.
    CHECK D: the three bystanders (started here, stopped here) are alive.
    Signals only the child's app-server process group (pid and start time checked, it leads its own group and
    carries the child's marker) and the probe's own bystanders.
    """
    from graftling.tool_descendants import identity

    alias, mapping, record, execution = facts_of(project)
    process = execution.get('process') or {}
    worker, runtime, marker = process.get('worker_pid'), process.get('runtime_pid'), process.get('tool_marker')
    sidecar = process.get('tool_descendants')
    print(f'member {alias} agent {mapping.get("agent")} worker_pid {mapping.get("worker_pid")} '
          f'turn ended {member_terminal(project)}')
    print(f'child {record.get("agent")} execution {execution.get("id")} state {execution.get("state")} '
          f'worker_pid {worker} runtime_pid {runtime} tool_marker recorded {bool(marker)} '
          f'tool_descendants {sidecar}')
    if not record or execution.get('state') != 'running':
        print('STOP: no running child. Nothing was done.')
        return 1
    if not marker or not sidecar:
        print('STOP: the child record has no tool_marker or tool_descendants. Nothing was done.')
        return 1
    entries, error = recorded(sidecar)
    print('before the kill: the descendants record lists', len(entries), 'entries:',
          [(entry['pid'], entry.get('argv', '')[:100]) for entry in entries], f'(error: {error})' if error else '')
    recorded_sleeps = [entry for entry in entries if is_child_sleep(entry.get('argv', ''))]
    if error or not recorded_sleeps:
        print(f"STOP: the child's descendants record lists no '{CHILD_SLEEP}' (the venv lacks the fix, the tool has not "
              'started, or the sampler missed it). Nothing was done.')
        return 1
    ancestry([entry for entry in recorded_sleeps if live(entry)], marker)
    service = identity(runtime) if isinstance(runtime, int) else None
    if service is None:
        print(f'STOP: the recorded app-server {runtime} is not alive. Nothing was done.')
        return 1
    if service.pgid != service.pid:
        print(f'STOP: the app-server {runtime} does not lead its own process group ({service.pgid}). Nothing was done.')
        return 1
    if runtime not in marked(marker):
        print("STOP: the recorded runtime_pid does not carry the child's marker; it is not this child's app-server. "
              'Nothing was done.')
        return 1
    owner = identity(worker) if isinstance(worker, int) else None
    print(f'owner Worker {worker} alive {owner is not None} (it is kept alive)')

    other = control_process(uuid.uuid4().hex)
    plain = control_process(None)
    mine = user_sleep()
    results: list = []
    report, path, termination = None, None, None
    try:
        time.sleep(0.5)
        print(f'bystanders: other-marker pid {other.pid}, no-marker pid {plain.pid}, own /bin/sleep 901 pid {mine.pid}')
        # Re-check pid and start time right before the signal: never a bare pid after the fact.
        now = identity(runtime)
        if now is None or now.start != service.start:
            print(f'STOP: the app-server {runtime} changed or ended before the kill. Nothing was signalled.')
            return 1
        killed_at = time.time()
        os.killpg(service.pgid, signal.SIGKILL)
        print(f'app-server {runtime}: SIGKILL process group {service.pgid} at {killed_at:.1f}; owner {worker} not signalled')
        deadline = time.time() + 10
        while time.time() < deadline and (identity(runtime) or None) is not None \
                and identity(runtime).start == service.start:
            time.sleep(0.05)
        gone = identity(runtime) is None or identity(runtime).start != service.start
        residue = [entry for entry in entries if live(entry)]
        residue_sleeps = [entry for entry in residue if is_child_sleep(entry.get('argv', ''))]
        print(f'app-server gone: {gone} ({time.time() - killed_at:.2f} s after the kill)')
        print('right after the app-server is gone, recorded descendants alive (the residue):',
              [(entry['pid'], entry.get('argv', '')[:60]) for entry in residue])
        results.append(check(f"A a recorded '{CHILD_SLEEP}' is alive after the app-server is gone",
                             gone and bool(residue_sleeps),
                             f'app-server gone={gone} live recorded sleeps={[e["pid"] for e in residue_sleeps]}'))

        directory = Path(sidecar).parent
        deadline = time.time() + 30
        while time.time() < deadline and not termination_records(directory, killed_at):
            time.sleep(0.25)
        found = termination_records(directory, killed_at)
        if found:
            termination = found[-1]
            path = 'owner-side reclaim'
            report = (yaml.safe_load(termination.read_text()) or {}).get('escaped_processes')
            print(f'owner termination record {termination.name} after {time.time() - killed_at:.1f} s')
        else:
            path = 'reconcile'
            print('no owner termination record within 30 s; one reconciling read')
            from graphtraj.interfaces.agents import GraphTrajAgents

            GraphTrajAgents(project).reconcile_children({alias, mapping.get('agent')})
            report = ((core(project, record['agent']).get('executions') or [{}])[-1]).get('escaped_processes')
        print(f'escaped_processes ({path}):', json.dumps(report, ensure_ascii=False))
        stopped = {item.get('pid') for item in (report or {}).get('stopped', [])}
        ok_b = (bool(report) and bool(residue_sleeps) and all(e['pid'] in stopped for e in residue_sleeps)
                and all(e['pid'] in stopped for e in residue) and report.get('remaining') == []
                and not report.get('error'))
        results.append(check(f"B {path}: the residue (incl. '{CHILD_SLEEP}', same pid) is stopped, remaining [], no error",
                             ok_b, f'stopped={sorted(p for p in stopped if p is not None)} '
                                   f'residue={[e["pid"] for e in residue]} remaining={(report or {}).get("remaining")} '
                                   f'error={(report or {}).get("error")}'))
        left = [(entry['pid'], entry.get('argv', '')[:60]) for entry in entries if live(entry)]
        left_sleep = sleeping()
        results.append(check(f"C no recorded descendant and no '{CHILD_SLEEP}' alive",
                             not left and not left_sleep, f'recorded alive={left} {CHILD_SLEEP}={left_sleep}'))
        results.append(check('D the three bystanders alive',
                             other.poll() is None and plain.poll() is None and mine.poll() is None,
                             f'other-marker={other.poll() is None} no-marker={plain.poll() is None} '
                             f'own /bin/sleep={mine.poll() is None}'))
        state = (core(project, record['agent']).get('executions') or [{}])[-1]
        print(f'child execution {state.get("id")}: state {state.get("state")} outcome {state.get("outcome")} '
              f'error {(state.get("error") or {}).get("code")}; owner Worker {worker} alive '
              f'{owner is not None and identity(worker) is not None and identity(worker).start == owner.start}')
    finally:
        for bystander in (other, plain, mine):
            if bystander.poll() is None:
                bystander.terminate()
            try:
                bystander.wait(5)
            except subprocess.TimeoutExpired:
                bystander.kill()
                bystander.wait(5)
        print(f'bystanders stopped: other {other.poll() is not None}, no-marker {plain.poll() is not None}, '
              f'own sleep {mine.poll() is not None}')
    Path(facts_file).write_text(json.dumps({
        'alias': alias, 'member_agent': mapping.get('agent'), 'child': record.get('agent'),
        'execution': execution.get('id'), 'worker_pid': worker, 'app_server_pid': runtime,
        'tool_descendants': sidecar, 'recorded_before_kill': entries, 'path': path,
        'termination_record': str(termination) if termination else None,
        'escaped_processes': report, 'checks': results}, indent=2))
    print('== summary:', 'ALL PASS' if results and all(results) else f'{results.count(False)} FAIL of {len(results)}',
          f'| facts in {facts_file}')
    return 0 if results and all(results) else 1


PID_FILES = ('01-main.pid',)


def idle(out: Path, _unused: str) -> int:
    """0 when no earlier probe Main (pid file in ``out``) and no 'sleep 462' runs; signals nothing."""
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
                                              **{f'{CHILD_SLEEP} pid {k}': v for k, v in found.items()}})
    print(f"STOP: changed nothing. Wait for it to end, then rerun (a '{CHILD_SLEEP}' ends 462 s after it started).")
    return 1


# -- Rehearsal only -------------------------------------------------------------

STUB_OWNER = r"""
import json, os, subprocess, sys, time
from pathlib import Path
from graftling.tool_descendants import DescendantSampler, stop_tool_processes
path, marker, runtime_code = sys.argv[1], sys.argv[2], sys.argv[3]
sampler = DescendantSampler(path, marker)
sampler.prepare()
runtime = subprocess.Popen([sys.executable, "-I", "-c", runtime_code], start_new_session=True,
                           env={**os.environ, "GRAFTLING_MEMBER_RUN": marker},
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
sampler.start(runtime.pid)
code = runtime.wait()
# As the Codex owner: once its service has exited, stop what is left and write the record; stay alive.
report = stop_tool_processes(sampler.finish(), marker, {runtime.pid}, error=sampler.error)
target = Path(path).parent / "codex-termination-stub.yml"
target.write_text(json.dumps({"runtime_pid": runtime.pid, "runtime_exit_code": code, "escaped_processes": report}))
time.sleep(900)
"""
STUB_RUNTIME = r"""
import subprocess, sys, time
native = 'import subprocess, time; subprocess.Popen(["/bin/zsh", "-c", "sleep 462; :"], start_new_session=True, ' \
         'stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(900)'
subprocess.Popen([sys.executable, "-I", "-c", native], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(900)
"""


def stub(project: Path, _unused: str) -> int:
    """Without a model: a member session, its child's record and stand-in processes, as 01 leaves them.

    A stand-in owner Worker (Python, own session) runs the real descendant sampler on a stand-in Runtime (Python,
    own group, the child's marker: the 'codex' launcher). Its readable child in the same group (the native
    app-server, with the marker) starts a real ``/bin/zsh -c 'sleep 462; :'`` in its own session, so the tool
    shell and its ``sleep 462`` are Apple platform binaries, as on the real host.
    """
    from graftling import AgentControl, Caller, bind
    from graftling.tool_descendants import read_sidecar

    marker = uuid.uuid4().hex
    environment = {key: value for key, value in os.environ.items() if key != MARKER_ENV}
    work = project / '.graphtraj/probe-462/stub'
    work.mkdir(parents=True, exist_ok=True)
    sidecar = work / 'tool-descendants.json'
    worker = subprocess.Popen([sys.executable, '-I', '-c', STUB_OWNER, str(sidecar), marker, STUB_RUNTIME],
                              env=environment, start_new_session=True,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 20
    entries: list = []
    while time.time() < deadline:
        try:
            entries = read_sidecar(sidecar)
        except (OSError, ValueError):
            entries = []
        if any(is_child_sleep(entry.get('argv', '')) for entry in entries):
            break
        time.sleep(0.2)
    runtime = json.loads(sidecar.read_text()).get('runtime_pid') if sidecar.exists() else None
    if runtime is None:
        print('STOP: the stand-in owner did not start its Runtime')
        return 1
    if os.environ.get('VERIFY462_STUB_TOOL_GONE'):
        # Negative rehearsal: the tool ends before the kill, so there is nothing to act on.
        from graftling.tool_descendants import identity

        for entry in entries:
            if (entry.get('argv', '').startswith('/bin/zsh') or is_child_sleep(entry.get('argv', ''))) \
                    and (now := identity(entry['pid'])) is not None \
                    and now.start == entry['start']:
                os.kill(entry['pid'], signal.SIGKILL)
        time.sleep(1.5)
        print('stub: VERIFY462_STUB_TOOL_GONE set; the tool shell and its sleep were stopped before the kill')

    class Driver:
        def prepare(self, runtime_name, caller):
            return {}

        def start(self, run):
            run.events.session('stub-' + run.agent[-6:])
            run.events.process(runtime_pid=runtime, tool_marker=marker, tool_descendants=str(sidecar))

        def deliver(self, run, message):
            pass

        def interrupt(self, run):
            return True

    root = project / '.graphtraj/swarm'
    control = AgentControl(root, {'stub': Driver()})
    lead = bind(control, Caller('stub-host', None))({'action': 'create', 'runtime': 'stub', 'instruction': 'lead'})
    lead_agent = lead.document['agent']
    created = bind(control, Caller('stub-host', lead_agent))({'action': 'create', 'runtime': 'stub', 'instruction': 'w'})
    agent = created.document['agent']
    path = root / 'control/agents' / f'{agent}.json'
    data = json.loads(path.read_text())
    data['executions'][-1]['process']['worker_pid'] = worker.pid
    path.write_text(json.dumps(data, indent=2, sort_keys=True))
    session = project / '.graphtraj/runner/sessions/1-stub-team_leader'
    session.mkdir(parents=True, exist_ok=True)
    (session / 'mapping.yml').write_text(yaml.safe_dump({'agent': lead_agent, 'worker_pid': worker.pid}))
    (session / 'execution.yml').write_text(yaml.safe_dump({'last_agent_message': 'stub'}))
    print(f'stub: member 1-stub-team_leader agent {lead_agent}, child {agent}, worker {worker.pid}, '
          f'runtime {runtime}; recorded {[(entry["pid"], entry.get("argv")) for entry in entries]}')
    return 0


if __name__ == '__main__':
    command, target, extra = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    commands = {'prepare': prepare, 'plugins': plugins, 'child': child_cmd, 'kill': kill, 'idle': idle, 'stub': stub}
    raise SystemExit(commands[command](target, extra))
