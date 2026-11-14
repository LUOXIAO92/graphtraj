"""461 probe helper: roles, the probe Task, the member's Pi child, the kill, one reconciling read and the CHECKs.

Usage (the scratch venv's Python):
  python -I probe.py prepare PROJECT MODEL   roles (team_leader claude; a 'pi' role on the user's Pi connection)
                                             and probe Task 1, ready; prints the Pi values used (never a key value)
  python -I probe.py plugins STREAM -        0 only when graphtraj-claude-host is loaded
  python -I probe.py child PROJECT SECONDS   poll (<=100 s) until the member's turn ended and its Pi child runs:
                                             CHILD-RUNNING
  python -I probe.py kill PROJECT FACTS      refuse unless the child's descendants record lists a live 'sleep 461';
                                             print the recorded chain; SIGKILL the child's owner and Runtime group,
                                             start three bystanders, one reconciling read, CHECK 1-4, stop them
  python -I probe.py idle OUT -              0 unless an earlier probe Main (pid file in OUT) or 'sleep 461' lives
  python -I probe.py stub PROJECT -          rehearsal only: a fake member, child record and processes, no model
Prints only facts read from the isolated project, the user's connection catalog (names, never values) and
process tables. It prints whether the child's tool marker is present, never its value. It signals only the
child's recorded owner Worker and Runtime group (step 02, after checking their start times) and processes it
started itself.
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
NAME = 'pi-tool-processes-probe'
CHILD_SLEEP = 'sleep 461'
MARKER_ENV = 'GRAFTLING_MEMBER_RUN'
# The user's Pi configuration (production roles.yml, preset pi_dsh_trial.team_leader).
CONNECTION = 'pi/deepseek/deepseek-flash'
PI = {'sandbox_python': os.environ.get('VERIFY461_SANDBOX_PYTHON', '/Users/luoxiao/agents-pi-sandbox/venv/bin/python'),
      'sandbox_path': os.environ.get('VERIFY461_SANDBOX_PATH',
                                     '/Users/luoxiao/agents-pi-sandbox/srt/node_modules/.bin:/opt/homebrew/bin:'
                                     '/Users/luoxiao/agents-pi-sandbox/bin:/usr/bin:/bin:/usr/sbin:/sbin'),
      'agent_dir': os.environ.get('VERIFY461_AGENT_DIR', '/Users/luoxiao/.pi/agent')}
BODY = '''---
difficulty: low
difficulty_reason: Scratch probe for 461
execution_budget:
  estimated_minutes:
    total: 30
  planned_sessions:
    team_leader: 1
  correction_rounds: 0
  estimation_note: One agents-tool Pi child whose owner is killed while its bash tool runs
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


def pi_role() -> dict:
    """The child's role: the user's connection (rehearsal: the same model inline) and Pi settings."""
    if os.environ.get('VERIFY461_NO_MODEL'):
        return {'runtime': 'pi', 'model': 'deepseek/deepseek-flash', 'worktree_access': 'read', 'pi': PI}
    return {'connection': CONNECTION, 'worktree_access': 'read', 'pi': PI}


def show_pi_values() -> int:
    """Print, read only, the Pi values the child uses. Key values are never read into the output."""
    print('pi role:', json.dumps({key: value for key, value in pi_role().items() if key != 'pi'}))
    for key, value in PI.items():
        print(f'pi.{key}: {value}')
    rc = 0
    if not os.environ.get('VERIFY461_NO_MODEL'):
        try:
            from graphtraj.configuration.runtime_connections import resolve_connection

            resolved = resolve_connection(CONNECTION, None)
            names = [resolved.get('api_key_env'), *resolved.get('pass_env', ())]
            print('connection', CONNECTION, '->', json.dumps({
                key: resolved.get(key) for key in ('runtime', 'model', 'runtime_home', 'runtime_provider',
                                                   'provider_api', 'model_source')}),
                  '| base_url set:', bool(resolved.get('base_url')),
                  '| key variables named (set in this shell?):',
                  {name: bool(os.environ.get(name)) for name in names if name} or 'none (Pi login)')
        except Exception as error:  # noqa: BLE001 - reported, never fatal to the listing
            print(f'connection {CONNECTION}: NOT resolvable: {type(error).__name__}: {error}')
            rc = 1
    print('srt on sandbox_path:', [str(Path(p) / 'srt') for p in PI['sandbox_path'].split(':')
                                   if os.path.exists(Path(p) / 'srt')] or 'NONE')
    try:
        done = subprocess.run([PI['sandbox_python'], '-I', '-c',
                               'from agent_sandbox import is_sandbox_available; print(is_sandbox_available())'],
                              env={'PATH': PI['sandbox_path'], 'HOME': os.environ.get('HOME', '')},
                              capture_output=True, text=True, timeout=60)
        available = done.stdout.strip() == 'True'
        print('sandbox available (agent_sandbox.is_sandbox_available):', 'YES' if available else
              f'NO ({(done.stdout + done.stderr).strip()[-200:]})')
    except (OSError, subprocess.SubprocessError) as error:
        available = False
        print(f'sandbox available: NO ({type(error).__name__}: {error})')
    if not available and not os.environ.get('VERIFY461_NO_MODEL'):
        rc = 1
    return rc


def prepare(project: Path, model: str) -> int:
    bin_dir = Path(sys.executable).parent
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'team_leader': {'runtime': 'claude', 'model': model, 'worktree_access': 'write',
                                  'reports': ['report.md'], 'claude': {'permission_mode': 'auto'}},
                  # The one role using Pi: an agents-tool create with runtime 'pi' selects it.
                  'pi': pi_role()},
        'role_tree': {'team_leader': {}},
    }))
    rc = show_pi_values()
    work = project / '.graphtraj/probe-461'
    work.mkdir(exist_ok=True)
    register = work / 'register.yml'
    register.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'task_name': NAME, 'source': 'local:scratch/461', 'title': NAME, 'body': BODY,
        'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
        'replaced_by': [], 'retirement_reason': None}))
    state = work / 'state.yml'
    state.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
        'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-461/evidence.md']}))
    if not list(project.glob('.graphtraj/state/tasks/1-*/task.yml')):
        rc = rc or run(str(bin_dir / 'graphtraj'), 'task', 'register', '--task-file', str(register)).returncode
    (work / 'evidence.md').write_text('461 probe: ready for one member with one agents-tool Pi child.\n')
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
                f'child={record.get("agent")} runtime={record.get("runtime")} execution={execution.get("id")} '
                f'state={execution.get("state")} worker_pid={process.get("worker_pid")} '
                f'runtime_pid={process.get("runtime_pid")} tool_marker recorded={bool(process.get("tool_marker"))} '
                f'tool_descendants recorded={bool(process.get("tool_descendants"))} '
                f'worker alive={alive(process.get("worker_pid"))} runtime alive={alive(process.get("runtime_pid"))} '
                f"'{CHILD_SLEEP}' alive={sorted(sleeping())}")

    code = poll(project, seconds, done, 'CHILD-RUNNING', state)
    print(state())
    return code


# -- Processes (read only unless named) -----------------------------------------

def sleeping() -> dict[int, str]:
    """Live same-user processes whose command holds ``sleep 461`` (read only): ps, plus argv read
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


def marker_state(pid: int, marker: str) -> str:
    """'yes', 'no' or 'unreadable' (macOS platform binary): whether ``pid`` carries exactly this marker."""
    from graftling.member_processes import _process_view

    view = _process_view(pid)
    if view is None or not view[1]:
        return 'unreadable'
    return 'yes' if f'{MARKER_ENV}={marker}' in view[1] else 'no'


def live_chain(runtime: object, marker: str) -> list[str]:
    """The live process tree below the Runtime, read only, with each process's marker state.

    Unlike the record, this ignores the boundary rule, so it shows where the marker was lost if the
    record stops early (for example srt or sandbox-exec dropping the environment)."""
    from graftling.member_processes import _process_view
    from graftling.tool_descendants import _table, shown_command

    if not isinstance(runtime, int):
        return []
    table = _table()
    lines, pending = [], [(runtime, 0)]
    while pending:
        pid, depth = pending.pop()
        item = table.get(pid)
        if item is None:
            lines.append(f'{"  " * depth}{pid}: gone')
            continue
        view = _process_view(pid)
        lines.append(f'{"  " * depth}pid {pid} ppid {item.ppid} pgid {item.pgid} uid {item.uid} '
                     f'marker {marker_state(pid, marker)} argv {shown_command(view[0] if view else [])[:120]}')
        pending.extend((other.pid, depth + 1) for other in sorted(table.values(), key=lambda x: -x.pid)
                       if other.ppid == pid)
    return lines


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
    """``sleep 461`` itself, or Pi's ``/bin/bash -c sleep 461`` before bash replaced itself with it."""
    words = argv.split()
    return words[:2] in (['sleep', '461'], ['/bin/sleep', '461']) or words[-2:] == ['sleep', '461'] and (
        words[:2] in (['/bin/bash', '-c'], ['bash', '-c'], ['/bin/sh', '-c'], ['/bin/zsh', '-c']))


def kill(project: Path, facts_file: str) -> int:
    """Kill the child's owner and Runtime group, then one reconciling read and the four CHECKs."""
    from graftling.tool_descendants import identity

    alias, mapping, record, execution = facts_of(project)
    process = execution.get('process') or {}
    worker, runtime, marker = process.get('worker_pid'), process.get('runtime_pid'), process.get('tool_marker')
    sidecar = process.get('tool_descendants')
    print(f'member {alias} agent {mapping.get("agent")} worker_pid {mapping.get("worker_pid")} '
          f'turn ended {member_terminal(project)}')
    print(f'child {record.get("agent")} runtime {record.get("runtime")} execution {execution.get("id")} '
          f'state {execution.get("state")} worker_pid {worker} runtime_pid {runtime} '
          f'tool_marker recorded {bool(marker)} tool_descendants {sidecar}')
    if not member_terminal(project):
        print("STOP: the member's turn has not ended; its Worker is never killed while it runs. Nothing was done.")
        return 1
    if not record or record.get('runtime') != 'pi' or execution.get('state') != 'running' \
            or worker != mapping.get('worker_pid'):
        print("STOP: no running Pi child, or its owner is not the member's last Worker. Nothing was done.")
        return 1
    if not marker:
        print('STOP: the child record has no tool_marker (the venv lacks the 461 fix?). Nothing was done.')
        return 1
    entries, error = recorded(sidecar)
    print('before the kill: the live process tree below the Runtime (read only; marker yes/no/unreadable):')
    print('\n'.join('  ' + line for line in live_chain(runtime, marker)) or '  (Runtime not alive)')
    print(f'before the kill: the recorded chain ({len(entries)} entries; pid ppid pgid uid argv)'
          + (f' (error: {error})' if error else '') + ':')
    for entry in sorted(entries, key=lambda item: item['pid']):
        print(f"  pid {entry['pid']} ppid {entry.get('ppid')} pgid {entry.get('pgid')} uid {entry['uid']} "
              f"live {live(entry)} argv {entry.get('argv', '')[:120]}")
    sleeps = [entry for entry in entries if is_child_sleep(entry.get('argv', '')) and live(entry)]
    shells = [entry for entry in entries if sleeps and entry['pid'] in {item.get('ppid') for item in sleeps}]
    print(f"before the kill: recorded live '{CHILD_SLEEP}': {[entry['pid'] for entry in sleeps]}; "
          f"its recorded parent: {[(entry['pid'], entry.get('argv', '')[:60]) for entry in shells] or 'not recorded'}")
    if error or not sleeps:
        print(f"STOP: the child's descendants record is missing or lists no live '{CHILD_SLEEP}' "
              '(the venv lacks the fix, the sleep ended, or the marker was lost on the way: see the tree above). '
              'Nothing was done.')
        return 1
    before = marked(marker)
    sleep_before = sleeping()
    print(f'before the kill: {len(before)} processes carry the child marker: '
          f'{[command[:100] for command in before.values()]}')
    print(f"before the kill: '{CHILD_SLEEP}' alive (ps/argv, read only) {sorted(sleep_before)}")
    if alive(runtime) and marker_state(runtime, marker) == 'no':
        print("STOP: the recorded runtime_pid is readable without the child's marker; it is not this child's "
              'Runtime. Nothing was done.')
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
    escaped_before = [entry for entry in entries if live(entry)]
    print('after the kill, before any read: recorded descendants alive (the escaped tools):',
          [(entry['pid'], entry.get('argv', '')[:60]) for entry in escaped_before])

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
        has_escaped = all(entry['pid'] in stopped for entry in escaped_before)
        results.append(check(f"2 escaped_processes lists '{CHILD_SLEEP}' and every recorded process alive after "
                             'the kill as stopped, remaining empty',
                             bool(escaped) and has_sleep and has_escaped and escaped.get('remaining') == []
                             and not escaped.get('error'),
                             f'stopped={sorted(stopped)} sleep={has_sleep} all escaped={has_escaped} '
                             f'tool shell={[entry["pid"] for entry in shells]} '
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
    """0 when no earlier probe Main (pid file in ``out``) and no 'sleep 461' runs; signals nothing."""
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
    print(f"STOP: changed nothing. Wait for it to end, then rerun (a '{CHILD_SLEEP}' ends 461 s after it started).")
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
# As Pi 1.4.0's bash tool: /bin/bash -c <command>, detached (own session).
STUB_RUNTIME = r"""
import subprocess, time
subprocess.Popen(["/bin/bash", "-c", "sleep 461"], start_new_session=True,
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(900)
"""


def stub(project: Path, _unused: str) -> int:
    """Without a model: a member session, its Pi child's record and stand-in processes, as 01 leaves them.

    A stand-in owner Worker (Python, own session) runs the real descendant sampler on a stand-in Runtime (Python,
    own group, the child's marker). The Runtime starts a real ``/bin/bash -c 'sleep 461'`` in its own session,
    as Pi's bash tool does, so the tool process is an Apple platform binary, as on the real host.
    """
    from graftling import AgentControl, Caller, bind
    from graftling.tool_descendants import read_sidecar

    marker = uuid.uuid4().hex
    environment = {key: value for key, value in os.environ.items() if key != MARKER_ENV}
    work = project / '.graphtraj/probe-461/stub'
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
    control = AgentControl(root, {'pi': Driver()})
    lead = bind(control, Caller('stub-host', None))({'action': 'create', 'runtime': 'pi', 'instruction': 'lead'})
    lead_agent = lead.document['agent']
    created = bind(control, Caller('stub-host', lead_agent))({'action': 'create', 'runtime': 'pi', 'instruction': 'w'})
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
