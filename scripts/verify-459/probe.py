"""459 probe helper: roles, the probe Task, the member's Claude child, the kill, one reconciling read and the CHECKs.

Usage (the scratch venv's Python):
  python -I probe.py prepare PROJECT MODEL   roles (team_leader claude, permission_mode auto) and probe Task 1, ready
  python -I probe.py plugins STREAM -        0 only when graphtraj-claude-host is loaded
  python -I probe.py child PROJECT SECONDS   poll (<=100 s) until the member's turn ended and its child runs: CHILD-RUNNING
  python -I probe.py kill PROJECT FACTS      refuse unless the child's descendants record lists a live 'sleep 459';
                                             SIGKILL the child's owner and Runtime group, start three bystanders,
                                             one reconciling read, CHECK 1-4, stop the bystanders
  python -I probe.py idle OUT -              0 unless an earlier probe Main (pid file in OUT) or 'sleep 459' lives
  python -I probe.py stub PROJECT -          rehearsal only: a fake member, child record and processes, no model
Prints only facts read from the isolated project and process tables. It reads no credential and prints
whether the child's tool marker is recorded, never its value. It signals only the child's recorded owner Worker and
Runtime group (step 02, after checking them) and processes it started itself.
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
NAME = 'tool-processes-probe'
CHILD_SLEEP = 'sleep 459'
MARKER_ENV = 'GRAFTLING_MEMBER_RUN'
BODY = '''---
difficulty: low
difficulty_reason: Scratch probe for 459
execution_budget:
  estimated_minutes:
    total: 30
  planned_sessions:
    team_leader: 1
  correction_rounds: 0
  estimation_note: One agents-tool child whose owner is killed while its Bash tool runs
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
    work = project / '.graphtraj/probe-459'
    work.mkdir(exist_ok=True)
    register = work / 'register.yml'
    register.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'task_name': NAME, 'source': 'local:scratch/459', 'title': NAME, 'body': BODY,
        'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
        'replaced_by': [], 'retirement_reason': None}))
    state = work / 'state.yml'
    state.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
        'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-459/evidence.md']}))
    rc = 0
    if not list(project.glob('.graphtraj/state/tasks/1-*/task.yml')):
        rc = run(str(bin_dir / 'graphtraj'), 'task', 'register', '--task-file', str(register)).returncode
    (work / 'evidence.md').write_text('459 probe: ready for one member with one agents-tool child.\n')
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
    """Live same-user processes whose command holds ``sleep 459`` (read only): ps, plus argv read
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


def kill(project: Path, facts_file: str) -> int:
    """Kill the child's owner and Runtime group, then one reconciling read and the four CHECKs."""
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
    if not member_terminal(project):
        print("STOP: the member's turn has not ended; its Worker is never killed while it runs. Nothing was done.")
        return 1
    if not record or execution.get('state') != 'running' or worker != mapping.get('worker_pid'):
        print("STOP: no running child, or its owner is not the member's last Worker. Nothing was done.")
        return 1
    if not marker:
        print('STOP: the child record has no tool_marker. Nothing was done.')
        return 1
    entries, error = recorded(sidecar)
    print('before the kill: the descendants record lists', len(entries), 'entries:',
          [(entry['pid'], entry.get('argv', '')[:100]) for entry in entries], f'(error: {error})' if error else '')
    sleeps = [entry for entry in entries if is_child_sleep(entry.get('argv', '')) and live(entry)]
    shells = [entry for entry in entries if sleeps and entry['pid'] in {item.get('ppid') for item in sleeps}]
    print(f"before the kill: recorded live '{CHILD_SLEEP}': {[entry['pid'] for entry in sleeps]}; "
          f"its recorded parent (the tool shell): {[(entry['pid'], entry.get('argv', '')[:60]) for entry in shells]}")
    if error or not sleeps:
        print(f"STOP: the child's descendants record is missing or lists no live '{CHILD_SLEEP}' "
              '(the venv lacks the 459 fix, the sleep ended, or the sampler missed it). Nothing was done.')
        return 1
    before = marked(marker)
    sleep_before = sleeping()
    print(f'before the kill: {len(before)} processes carry the child marker: '
          f'{[command[:100] for command in before.values()]}')
    print(f"before the kill: '{CHILD_SLEEP}' alive (ps/argv, read only) {sorted(sleep_before)}")
    print(f"before the kill: env entries readable per '{CHILD_SLEEP}' process: {env_entries(sleep_before)}")
    if alive(runtime) and runtime not in before:
        print("STOP: the recorded runtime_pid does not carry the child's marker; it is not this child's Runtime. "
              'Nothing was done.')
        return 1
    worker_identity, runtime_identity = identity(worker), identity(runtime)

    killed: list = []
    # Re-check pid and start time right before each signal: never a bare pid after the fact.
    if worker_identity is not None and identity(worker) == worker_identity:
        os.kill(worker, signal.SIGKILL)
        killed.append({'label': 'worker', 'pid': worker, 'at': time.time()})
        print(f'worker {worker}: SIGKILL')
        time.sleep(2)
    else:
        print(f'worker {worker}: already exited')
    if runtime_identity is not None and (now := identity(runtime)) is not None and now.start == runtime_identity.start:
        kill_group(runtime, 'child runtime', killed)
    else:
        print(f'child runtime {runtime}: already gone')
    time.sleep(1)
    print('alive after kill:', {item['label']: alive(item['pid']) for item in killed} or 'nothing was killed')
    print('after the kill, before any read: recorded descendants alive:',
          [(entry['pid'], entry.get('argv', '')[:60]) for entry in entries if live(entry)])

    other = control_process(uuid.uuid4().hex)
    plain = control_process(None)
    mine = user_sleep()
    time.sleep(0.5)
    print(f'bystanders: other-marker pid {other.pid} alive {other.poll() is None}, '
          f'no-marker pid {plain.pid} alive {plain.poll() is None}, own /bin/sleep 901 pid {mine.pid} '
          f'alive {mine.poll() is None}')
    results: list = []
    escaped = None
    read_at = time.time()
    try:
        from graphtraj.interfaces.agents import GraphTrajAgents

        GraphTrajAgents(project).reconcile_children({alias, mapping.get('agent')})
        read_done = time.time()
        state = (core(project, record['agent']).get('executions') or [{}])[-1]
        escaped = state.get('escaped_processes')
        print(f'read: {read_done - read_at:.1f} s; child {state.get("state")} {state.get("outcome")} '
              f'{(state.get("error") or {}).get("code")} ended_at {state.get("ended_at")} '
              f'(read started {read_at:.0f})')
        print('escaped_processes:', json.dumps(escaped, ensure_ascii=False))
        results.append(check('1 child execution failed / owner-exited',
                             state.get('outcome') == 'failed'
                             and (state.get('error') or {}).get('code') == 'owner-exited'))
        stopped = {item.get('pid'): item.get('command', '') for item in (escaped or {}).get('stopped', [])}
        has_sleep = all(entry['pid'] in stopped for entry in sleeps)
        has_shell = bool(shells) and all(entry['pid'] in stopped for entry in shells)
        zsh = [entry['pid'] for entry in shells if entry.get('argv', '').split()[:1] in (['/bin/zsh'], ['zsh'])]
        results.append(check(f"2 escaped_processes lists the /bin/zsh tool shell and '{CHILD_SLEEP}' stopped, "
                             'remaining empty',
                             bool(escaped) and has_sleep and has_shell and escaped.get('remaining') == []
                             and not escaped.get('error'),
                             f'stopped={sorted(stopped)} sleep={has_sleep} shell={has_shell} zsh shell={zsh} '
                             f'remaining={(escaped or {}).get("remaining")} error={(escaped or {}).get("error")}'))
        left = [(entry['pid'], entry.get('argv', '')[:60]) for entry in entries if live(entry)]
        left_sleep = sleeping()
        results.append(check(f"3 none of the recorded descendants and no '{CHILD_SLEEP}' alive",
                             not left and not left_sleep, f'recorded alive={left} {CHILD_SLEEP}={left_sleep}'))
        results.append(check('4 the three bystanders alive',
                             other.poll() is None and plain.poll() is None and mine.poll() is None,
                             f'other-marker={other.poll() is None} no-marker={plain.poll() is None} '
                             f'own /bin/sleep={mine.poll() is None}'))
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
        'execution': execution.get('id'), 'worker_pid': worker, 'child_runtime_pid': runtime,
        'tool_descendants': sidecar, 'recorded_before_kill': entries,
        'marked_before_kill': len(before), 'sleep_pids_before_kill': sorted(sleep_before),
        'killed': killed, 'read_at': read_at, 'escaped_processes': escaped,
        'checks': results}, indent=2))
    print('== summary:', 'ALL PASS' if results and all(results) else f'{results.count(False)} FAIL of {len(results)}',
          f'| facts in {facts_file}')
    return 0 if results and all(results) else 1


PID_FILES = ('01-main.pid',)


def idle(out: Path, _unused: str) -> int:
    """0 when no earlier probe Main (pid file in ``out``) and no 'sleep 459' runs; signals nothing."""
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
    print(f"STOP: changed nothing. Wait for it to end, then rerun (a '{CHILD_SLEEP}' ends 459 s after it started).")
    return 1


# -- Rehearsal only -------------------------------------------------------------

STUB_OWNER = r"""
import os, subprocess, sys
from graftling.tool_descendants import DescendantSampler
path, marker, runtime_code = sys.argv[1], sys.argv[2], sys.argv[3]
sampler = DescendantSampler(path, marker)
sampler.prepare()
runtime = subprocess.Popen([sys.executable, "-I", "-c", runtime_code], start_new_session=True,
                           env={**os.environ, "GRAFTLING_MEMBER_RUN": marker},
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
sampler.start(runtime.pid)
runtime.wait()
sampler.finish()
"""
STUB_RUNTIME = r"""
import subprocess, time
subprocess.Popen(["/bin/zsh", "-c", "sleep 459; :"], start_new_session=True,
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(900)
"""


def stub(project: Path, _unused: str) -> int:
    """Without a model: a member session, its child's record and stand-in processes, as 01 leaves them.

    A stand-in owner Worker (Python, own session) runs the real descendant sampler on a stand-in Runtime (Python,
    own group, the child's marker). The Runtime starts a real ``/bin/zsh -c 'sleep 459; :'`` in its own session,
    so the tool shell and its ``sleep 459`` are Apple platform binaries, as on the real host.
    """
    from graftling import AgentControl, Caller, bind
    from graftling.tool_descendants import read_sidecar

    marker = uuid.uuid4().hex
    environment = {key: value for key, value in os.environ.items() if key != MARKER_ENV}
    work = project / '.graphtraj/probe-459/stub'
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
    if os.environ.get('PROBE_OUT'):
        # 471: member() needs this run's dispatch: a fresh 01 stream (born now) naming the stub alias, as 01's would.
        stream = Path(os.environ['PROBE_OUT']) / '01-main-stream.jsonl'
        stream.unlink(missing_ok=True)
        stream.write_text('SWARM-RESULT {"tasks": [{"task_id": "1", "alias": "1-stub-team_leader"}]}\n')
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
