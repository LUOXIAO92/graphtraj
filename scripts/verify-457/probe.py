"""457 probe helper: roles, the probe Task, the member's Claude child, the kill, one reconciling read and the CHECKs.

Usage (the scratch venv's Python):
  python -I probe.py prepare PROJECT MODEL   roles (team_leader claude, permission_mode auto) and probe Task 1, ready
  python -I probe.py plugins STREAM -        0 only when graphtraj-claude-host is loaded
  python -I probe.py child PROJECT SECONDS   poll (<=100 s) until the member's turn ended and its child runs: CHILD-RUNNING
  python -I probe.py kill PROJECT FACTS      SIGKILL the child's owner and Runtime group, start two control processes,
                                             one reconciling read, CHECK 1-4, stop the control processes
  python -I probe.py idle OUT -              0 unless an earlier probe Main (pid file in OUT) or 'sleep 457' lives
  python -I probe.py stub PROJECT -          rehearsal only: a fake member, child record and processes, no model
Prints only facts read from the isolated project and process tables. It reads no credential and prints
whether the child's tool marker is recorded, never its value.
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
CHILD_SLEEP = 'sleep 457'
MARKER_ENV = 'GRAFTLING_MEMBER_RUN'
BODY = '''---
difficulty: low
difficulty_reason: Scratch probe for 457
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
    work = project / '.graphtraj/probe-457'
    work.mkdir(exist_ok=True)
    register = work / 'register.yml'
    register.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'task_name': NAME, 'source': 'local:scratch/457', 'title': NAME, 'body': BODY,
        'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
        'replaced_by': [], 'retirement_reason': None}))
    state = work / 'state.yml'
    state.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
        'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-457/evidence.md']}))
    rc = 0
    if not list(project.glob('.graphtraj/state/tasks/1-*/task.yml')):
        rc = run(str(bin_dir / 'graphtraj'), 'task', 'register', '--task-file', str(register)).returncode
    (work / 'evidence.md').write_text('457 probe: ready for one member with one agents-tool child.\n')
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

def member(project: Path) -> tuple[str | None, dict, Path | None]:
    """The member's alias, mapping and session directory (the probe has one team_leader)."""
    for directory in sorted(project.glob('.graphtraj/runner/sessions/1-*team_leader*')):
        mapping = directory / 'mapping.yml'
        return directory.name, (yaml.safe_load(mapping.read_text()) or {}) if mapping.is_file() else {}, directory
    return None, {}, None


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
                f'worker alive={alive(process.get("worker_pid"))} runtime alive={alive(process.get("runtime_pid"))} '
                f"'{CHILD_SLEEP}' alive={sorted(sleeping())}")

    code = poll(project, seconds, done, 'CHILD-RUNNING', state)
    print(state())
    return code


# -- Processes (read only unless named) -----------------------------------------

def sleeping() -> dict[int, str]:
    """Live same-user processes whose command holds ``sleep 457`` (read only): ps, plus argv read
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
    except (OSError, ValueError):
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


def check(label: str, ok: bool, detail: str = '') -> bool:
    print(f'CHECK {"PASS" if ok else "FAIL"}: {label}' + (f' | {detail}' if detail else ''))
    return ok


def kill(project: Path, facts_file: str) -> int:
    """Kill the child's owner and Runtime group, then one reconciling read and the four CHECKs."""
    alias, mapping, record, execution = facts_of(project)
    process = execution.get('process') or {}
    worker, runtime, marker = process.get('worker_pid'), process.get('runtime_pid'), process.get('tool_marker')
    print(f'member {alias} agent {mapping.get("agent")} worker_pid {mapping.get("worker_pid")} '
          f'turn ended {member_terminal(project)}')
    print(f'child {record.get("agent")} execution {execution.get("id")} state {execution.get("state")} '
          f'worker_pid {worker} runtime_pid {runtime} tool_marker recorded {bool(marker)}')
    if not member_terminal(project):
        print("STOP: the member's turn has not ended; its Worker is never killed while it runs. Nothing was done.")
        return 1
    if not record or execution.get('state') != 'running' or worker != mapping.get('worker_pid'):
        print("STOP: no running child, or its owner is not the member's last Worker. Nothing was done.")
        return 1
    if not marker:
        print('STOP: the child record has no tool_marker (the venv lacks the 457 fix?). Nothing was done.')
        return 1
    before = marked(marker)
    sleep_before = sleeping()
    print(f'before the kill: {len(before)} processes carry the child marker: '
          f'{[command[:100] for command in before.values()]}')
    print(f"before the kill: '{CHILD_SLEEP}' alive {sorted(sleep_before)}")
    blind = sorted(pid for pid, count in env_entries(sleep_before).items() if count == 0)
    print(f"before the kill: env entries the scan reads per '{CHILD_SLEEP}' process: {env_entries(sleep_before)}")
    if blind:
        print(f'NOTE: the marker scan saw 0 env entries for {blind} (macOS platform binaries hide their environment); '
              'the marker cannot match them, so CHECK 2 and 3 are expected to FAIL.')
    if alive(runtime) and runtime not in before:
        print("STOP: the recorded runtime_pid does not carry the child's marker; it is not this child's Runtime. "
              'Nothing was done.')
        return 1
    if not sleep_before:
        print(f"STOP: the child's '{CHILD_SLEEP}' is not running (ended, or never started); the check would prove "
              'nothing. Nothing was done. Rerun 01 once the guard passes.')
        return 1

    killed: list = []
    if alive(worker):
        os.kill(worker, signal.SIGKILL)
        killed.append({'label': 'worker', 'pid': worker, 'at': time.time()})
        print(f'worker {worker}: SIGKILL')
        time.sleep(2)
    else:
        print(f'worker {worker}: already exited')
    kill_group(runtime, 'child runtime', killed)
    time.sleep(1)
    print('alive after kill:', {item['label']: alive(item['pid']) for item in killed} or 'nothing was killed')
    after_kill = marked(marker)
    print(f'after the kill, before any read: {len(after_kill)} marked processes alive (escaped tools): '
          f'{[command[:100] for command in after_kill.values()]}')

    other = control_process(uuid.uuid4().hex)
    plain = control_process(None)
    time.sleep(0.5)
    print(f'control processes: other-marker pid {other.pid} alive {other.poll() is None}, '
          f'no-marker pid {plain.pid} alive {plain.poll() is None}')
    try:
        from graphtraj.interfaces.agents import GraphTrajAgents

        read_at = time.time()
        GraphTrajAgents(project).reconcile_children({alias, mapping.get('agent')})
        read_done = time.time()
        state = (core(project, record['agent']).get('executions') or [{}])[-1]
        escaped = state.get('escaped_processes')
        print(f'read: {read_done - read_at:.1f} s; child {state.get("state")} {state.get("outcome")} '
              f'{(state.get("error") or {}).get("code")} ended_at {state.get("ended_at")} '
              f'(read started {read_at:.0f})')
        print('escaped_processes:', json.dumps(escaped, ensure_ascii=False))
        results = [check('1 child execution failed / owner-exited',
                         state.get('outcome') == 'failed' and (state.get('error') or {}).get('code') == 'owner-exited')]
        stopped = [item.get('command', '') for item in (escaped or {}).get('stopped', [])]
        has_sleep = any(command.split()[:2] == ['sleep', '457'] for command in stopped)
        has_shell = any(CHILD_SLEEP in command and command.split()[:1] != ['sleep'] for command in stopped)
        results.append(check("2 escaped_processes lists the tool shell and 'sleep 457' stopped, remaining empty",
                             bool(escaped) and has_sleep and has_shell and escaped.get('remaining') == [],
                             f'stopped={len(stopped)} sleep={has_sleep} shell={has_shell} '
                             f'remaining={(escaped or {}).get("remaining")} error={(escaped or {}).get("error")} '
                             f"'{CHILD_SLEEP}' pids before the kill={sorted(sleep_before)} 0-env={blind}"))
        left_marked, left_sleep = marked(marker), sleeping()
        results.append(check("3 no process carries the child's marker and no 'sleep 457' is alive",
                             not left_marked and not left_sleep,
                             f'marked={[command[:100] for command in left_marked.values()]} sleep457={left_sleep} '
                             f'env entries of those left={env_entries(left_sleep)} 0-env before the kill={blind}'))
        results.append(check('4 both control processes alive', other.poll() is None and plain.poll() is None,
                             f'other-marker={other.poll() is None} no-marker={plain.poll() is None}'))
    finally:
        for process in (other, plain):
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(5)
        print(f'control processes stopped: other {other.poll() is not None}, no-marker {plain.poll() is not None}')
    Path(facts_file).write_text(json.dumps({
        'alias': alias, 'member_agent': mapping.get('agent'), 'child': record.get('agent'),
        'execution': execution.get('id'), 'worker_pid': worker, 'child_runtime_pid': runtime,
        'tool_marker_recorded': True, 'marked_before_kill': len(before), 'marked_after_kill': len(after_kill),
        'sleep_pids_before_kill': sorted(sleep_before), 'zero_env_pids': blind,
        'killed': killed, 'read_at': read_at, 'escaped_processes': escaped,
        'checks': results}, indent=2))
    print('== summary:', 'ALL PASS' if all(results) else f'{results.count(False)} FAIL of {len(results)}',
          f'| facts in {facts_file}')
    return 0 if all(results) else 1


PID_FILES = ('01-main.pid',)


def idle(out: Path, _unused: str) -> int:
    """0 when no earlier probe Main (pid file in ``out``) and no 'sleep 457' runs; signals nothing."""
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
    print(f"STOP: changed nothing. Wait for it to end, then rerun (a '{CHILD_SLEEP}' ends 457 s after it started).")
    return 1


# -- Rehearsal only -------------------------------------------------------------

def stub(project: Path, _unused: str) -> int:
    """Without a model: a member session, its child's record and stand-in processes, as 01 leaves them.

    The stand-ins: a 'worker' (own session), a 'Runtime' (own group, child marker) and a 'tool shell'
    (own session, child marker) whose child's argv is ``sleep 457``. All are Python: macOS hides the
    environment of Apple platform binaries (/bin/sh, /bin/sleep) from the marker scan, at least in the sandbox.
    """
    from graftling import AgentControl, Caller, bind

    marker = uuid.uuid4().hex
    environment = {key: value for key, value in os.environ.items() if key != MARKER_ENV}
    detached = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    worker = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(900)'], env=environment, **detached)
    marked_env = {**environment, MARKER_ENV: marker}
    runtime = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(900)'], env=marked_env, **detached)
    work = project / '.graphtraj/probe-457/stub'
    work.mkdir(parents=True, exist_ok=True)
    (work / '457').write_text('import time; time.sleep(457)')
    shell = ('import subprocess, sys; subprocess.run(["sleep", "457"], executable=sys.executable, cwd=sys.argv[1])')
    subprocess.Popen([sys.executable, '-c', shell, str(work), 'tool-shell-standin', CHILD_SLEEP],
                     env=marked_env, **detached)

    class Driver:
        def prepare(self, runtime_name, caller):
            return {}

        def start(self, run):
            run.events.session('stub-' + run.agent[-6:])
            run.events.process(runtime_pid=runtime.pid, tool_marker=marker)

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
          f'runtime {runtime.pid}; the tool shell runs {CHILD_SLEEP!r}')
    return 0


if __name__ == '__main__':
    command, target, extra = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    commands = {'prepare': prepare, 'plugins': plugins, 'child': child_cmd, 'kill': kill, 'idle': idle, 'stub': stub}
    raise SystemExit(commands[command](target, extra))
