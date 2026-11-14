"""461 probe helper: roles, the probe Task, the member's Pi child, the kill, one reconciling read and the CHECKs.

Usage (the scratch venv's Python):
  python -I probe.py prepare PROJECT MODEL   roles (team_leader claude; a 'pi' role on the user's Pi connection)
                                             and probe Task 1, ready; prints the Pi values used (never a key value)
  python -I probe.py isolation PROJECT -     the project is its own graphtraj root and git top level, no CLAUDE.md
                                             at or above it; the context files a Pi child there would load
  python -I probe.py plugins STREAM -        0 only when graphtraj-claude-host is loaded
  python -I probe.py dispatch PROJECT STREAM record 01's dispatch (time, stream) before the probe Main starts
  python -I probe.py child PROJECT SECONDS   poll (<=100 s) until the member created by 01's dispatch ended its
                                             turn, its Pi child runs and the child's background 'sleep 1461' lives:
                                             CHILD-RUNNING
  python -I probe.py kill PROJECT FACTS      refuse unless the child's descendants record lists a live 'sleep 1461';
                                             print the recorded chain; SIGKILL the child's owner and Runtime group,
                                             CHECK 0 (the orphan is alive), three bystanders, one reconciling read,
                                             CHECK 1-4, stop the bystanders
  python -I probe.py idle OUT -              0 unless an earlier probe Main (pid file in OUT) or 'sleep 1461' lives
  python -I probe.py stub PROJECT CASE       rehearsal only, no model: CASE '-' an older member, the dispatch, the
                                             current member with a child record and processes; CASE 'ambiguous'
                                             two members after the dispatch, no alias, no processes
The member is the one created by 01's dispatch: its session directory was created at or after the dispatch time
and, when 01's stream already holds the swarm result, its name is the alias that result returned. Zero or more
than one such member: STOP, nothing signalled.
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
# The child's background job (orphan) and its second, still-running bash call. Timeline (t0 = 01's dispatch):
# the orphan starts about t0+2 min and lives 1461 s (24 min); the running call starts about t0+3 min and lasts
# 1200 s (20 min); 01's Main ends by about t0+10 min; 02 kills the owner when 01's Main ended (<= t0+9 min, or
# <= t0+18 min when 02 is rerun once after a STOP). Both are still alive then.
CHILD_SLEEP = 'sleep 1461'
RUNNING_SLEEP = 'sleep 1200'
DISPATCH = '.graphtraj/probe-461/dispatch.json'
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


CONTEXT_NAMES = ('AGENTS.override.md', 'AGENTS.md', 'AGENTS.MD', 'CLAUDE.md', 'CLAUDE.MD')


def context_files(project: Path) -> list[str]:
    """Context files Pi 1.4.0 would consider for cwd at or below ``project``: every candidate name in the project
    and each parent up to '/' (resource-loader.js loadProjectContextFiles walks cwd -> '/'; loadContextFileFromDir
    takes the first readable of these names, so all are listed)."""
    found = []
    for directory in (project.resolve(), *project.resolve().parents):
        found += [str(directory / name) for name in CONTEXT_NAMES if (directory / name).is_file()]
    return found


def pi_role(project: Path) -> dict:
    """The child's role: the user's connection (rehearsal: the same model inline) and Pi settings.

    Probe-only difference from the user's production role: ``deny_read`` lists every context file at or above the
    project (computed now, never hard-coded), so the Pi child does not load the Harness's AGENTS.md. Pi skips a
    file it cannot read (resource-loader.js:115-134, a warning). It does not touch the reclaim path."""
    pi = {**PI, 'deny_read': context_files(project)}
    if os.environ.get('VERIFY461_NO_MODEL'):
        return {'runtime': 'pi', 'model': 'deepseek/deepseek-flash', 'worktree_access': 'read', 'pi': pi}
    return {'connection': CONNECTION, 'worktree_access': 'read', 'pi': pi}


def show_pi_values(project: Path) -> int:
    """Print, read only, the Pi values the child uses. Key values are never read into the output."""
    role = pi_role(project)
    print('pi role:', json.dumps({key: value for key, value in role.items() if key != 'pi'}))
    for key, value in role['pi'].items():
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
                  'pi': pi_role(project)},
        'role_tree': {'team_leader': {}},
    }))
    rc = show_pi_values(project)
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


def isolation(project: Path, _unused: str) -> int:
    """Print how discovery stops at the isolated project and what a Pi child there would read (read only)."""
    from graphtraj.workspace.runner_project import discover_project_root

    project = project.resolve()
    root = discover_project_root(project)
    top = subprocess.run(['git', '-C', str(project), 'rev-parse', '--show-toplevel'],
                         capture_output=True, text=True).stdout.strip()
    upward = [str(p / name) for p in (project, *project.parents) for name in ('CLAUDE.md', 'CLAUDE.local.md')
              if (p / name).exists()]
    print(f'graphtraj project root: {root} | isolated: {root == project}')
    print(f'git top level: {top} | isolated: {Path(top).resolve() == project if top else False}')
    print(f'CLAUDE.md/CLAUDE.local.md at or above the project: {upward or "none"}')
    ok = root == project and bool(top) and Path(top).resolve() == project and not upward
    print('isolation:', 'OK' if ok else 'NOT OK')
    # Pi 1.4.0 dist/core/resource-loader.js:160-196 loads the agent dir's file, then one file per directory from
    # cwd up to '/'; graftling passes no --no-context-files and its srt denyRead is the role's deny_read plus the
    # source agent dir (src/graftling/pi/execution.py:321-328), so a file is kept out only by the role's deny_read.
    seen = context_files(project)
    roles = yaml.safe_load((project / '.graphtraj/roles.yml').read_text()) or {}
    denied = set(((roles.get('roles') or {}).get('pi') or {}).get('pi', {}).get('deny_read') or [])
    print(f'Pi child context files at or above cwd=project (Pi 1.4.0 walks cwd -> /): {seen or "none"}')
    print(f"denied by the probe's 'pi' role deny_read (probe-only; production roles untouched): "
          f'{sorted(denied & set(seen)) or "none"}')
    agent_file = [str(Path(PI['agent_dir']) / name) for name in CONTEXT_NAMES
                  if (Path(PI['agent_dir']) / name).is_file()] if os.access(PI['agent_dir'], os.R_OK) else ['unreadable here']
    print(f"Pi agent dir context file (the user's own global Pi context, linked by graftling; not the Harness): "
          f'{agent_file or "none"}')
    isolated = set(seen) <= denied
    print('Pi child context isolated:', 'YES' if isolated else f'NO (not denied: {sorted(set(seen) - denied)})')
    return 0 if ok and isolated else 1


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

def dispatch_cmd(project: Path, stream: str) -> int:
    """Record 01's dispatch (time, stream path) in the project, before the probe Main starts."""
    record = {'at': time.time(), 'iso': now(), 'stream': stream}
    path = project / DISPATCH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))
    print(f'dispatch recorded at {record["iso"]} ({record["at"]:.3f}) in {path}')
    return 0


def swarm_aliases(stream: object) -> list[str]:
    """Task 1's aliases from the swarm tool result in 01's stream (read only; [] before it arrives)."""
    found: list[str] = []
    try:
        lines = Path(str(stream)).read_text().splitlines()
    except (OSError, TypeError):
        return found
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        for content in ((record.get('message') or {}).get('content') or []) if record.get('type') == 'user' else []:
            text = content.get('content') if isinstance(content, dict) and content.get('type') == 'tool_result' else None
            if not isinstance(text, str) or '"launch_status"' not in text:
                continue
            try:
                result = json.loads(text)
            except ValueError:
                continue
            found += [task['alias'] for task in result.get('tasks', [])
                      if str(task.get('task_id')) == TASK_ID and task.get('alias')]
    return found


def born(path: Path) -> float:
    """Creation time of a directory (macOS st_birthtime; elsewhere st_ctime)."""
    status = path.stat()
    return getattr(status, 'st_birthtime', status.st_ctime)


_SELECTED: dict = {}


def member(project: Path) -> tuple[str | None, dict, Path | None]:
    """The member created by 01's dispatch: alias, mapping and session directory, or (None, {}, None).

    Candidates are task 1's team_leader session directories created at or after the recorded dispatch time; when
    01's stream already holds the swarm result, only its alias. Exactly one must match. Prints which and why."""
    try:
        dispatch = json.loads((project / DISPATCH).read_text())
    except (OSError, ValueError):
        reason = f'no dispatch record {project / DISPATCH} (run 01 first)'
        dispatch = None
    directories = sorted(project.glob('.graphtraj/runner/sessions/1-*team_leader*'))
    chosen: list[Path] = []
    if dispatch is not None:
        aliases = dispatch.get('alias') and [dispatch['alias']] or swarm_aliases(dispatch.get('stream'))
        after = [d for d in directories if born(d) >= dispatch['at']]
        chosen = [d for d in after if not aliases or d.name in aliases]
        reason = (f"dispatch at {dispatch.get('iso')}; task 1 team_leader sessions {[d.name for d in directories]}; "
                  f"created at/after the dispatch {[d.name for d in after]}; swarm result alias "
                  f"{aliases or 'not yet in the stream'}")
    line = (f'member: {chosen[0].name} ({reason})' if len(chosen) == 1 else
            f'member: NONE: {len(chosen)} match ({reason})')
    if _SELECTED.get('line') != line:
        print(line)
        _SELECTED['line'] = line
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
                f'child={record.get("agent")} runtime={record.get("runtime")} execution={execution.get("id")} '
                f'state={execution.get("state")} worker_pid={process.get("worker_pid")} '
                f'runtime_pid={process.get("runtime_pid")} tool_marker recorded={bool(process.get("tool_marker"))} '
                f'tool_descendants recorded={bool(process.get("tool_descendants"))} '
                f'worker alive={alive(process.get("worker_pid"))} runtime alive={alive(process.get("runtime_pid"))} '
                f"'{CHILD_SLEEP}' alive={sorted(sleeping())} '{RUNNING_SLEEP}' alive={sorted(sleeping(RUNNING_SLEEP))}")

    code = poll(project, seconds, done, 'CHILD-RUNNING', state)
    print(state())
    return code


# -- Processes (read only unless named) -----------------------------------------

def sleeping(text: str = CHILD_SLEEP) -> dict[int, str]:
    """Live same-user processes whose command holds ``text`` (read only): ps, plus argv read
    through libproc, which also works where ps is not allowed (the sandbox rehearsal)."""
    found = {}
    try:
        listing = subprocess.run(['ps', '-axo', 'pid=,command='], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        listing = ''
    for line in listing.splitlines():
        pid, _, command = line.strip().partition(' ')
        if text in command and 'probe.py' not in command and pid.isdigit():
            found[int(pid)] = command[:160]
    try:
        from graftling.member_processes import _process_view, _user_pids

        for pid in _user_pids():
            view = _process_view(pid) if pid not in found and pid != os.getpid() else None
            command = ' '.join(view[0]) if view else ''
            if text in command and 'probe.py' not in command:
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
    """The orphan ``sleep 1461`` itself (or via ``nohup``), as Pi's bash tool left it in the background."""
    seconds = CHILD_SLEEP.split()[1]
    words = argv.split()
    if words[:1] == ['nohup']:
        words = words[1:]
    return words[:2] in (['sleep', seconds], ['/bin/sleep', seconds])


def kill(project: Path, facts_file: str) -> int:
    """Kill the child's owner and Runtime group, then one reconciling read and the four CHECKs."""
    from graftling.tool_descendants import identity

    alias, mapping, record, execution = facts_of(project)
    if alias is None:
        print('STOP: no single member created by 01\'s dispatch (line above). Nothing was done.')
        return 1
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
    try:
        runtime_group = os.getpgid(runtime) if isinstance(runtime, int) else None
    except ProcessLookupError:
        runtime_group = None
    running = sleeping(RUNNING_SLEEP)
    print(f"before the kill: the child's running bash call '{RUNNING_SLEEP}' alive (read only) {sorted(running)}; "
          f'Runtime process group {runtime_group}')

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
    # The required observation: the orphan outlived the owner kill, outside the Runtime's group (so neither the
    # group kill nor Pi's own abort of the running call stopped it). Fail-closed.
    orphans = [entry for entry in sleeps if live(entry) and entry.get('pgid') != runtime_group]
    observed = check(f"0 after the owner kill and before the reconciling read, the child's recorded '{CHILD_SLEEP}' "
                     'is alive (outside the Runtime group)', bool(orphans),
                     f"alive={[(entry['pid'], entry.get('pgid')) for entry in orphans]} runtime group {runtime_group}")
    if not observed:
        print(f"NOT OBSERVED: no recorded '{CHILD_SLEEP}' outlived the owner kill outside the Runtime group; the "
              'reclaim path was not exercised. The summary cannot be ALL PASS.')

    other = control_process(uuid.uuid4().hex)
    plain = control_process(None)
    mine = user_sleep()
    time.sleep(0.5)
    print(f'bystanders: other-marker pid {other.pid} alive {other.poll() is None}, '
          f'no-marker pid {plain.pid} alive {plain.poll() is None}, own /bin/sleep 901 pid {mine.pid} '
          f'alive {mine.poll() is None}')
    results: list = [observed]
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
        'orphan_alive_after_kill': [entry['pid'] for entry in orphans], 'runtime_group': runtime_group,
        'running_call_before_kill': sorted(running), 'checks': results}, indent=2))
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
    print(f"STOP: changed nothing. Wait for it to end, then rerun (a '{CHILD_SLEEP}' ends 1461 s after it started).")
    return 1


# -- Rehearsal only -------------------------------------------------------------

STUB_OWNER = r"""
import os, subprocess, sys
from graftling.tool_descendants import DescendantSampler
path, marker, runtime_code, case = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
sampler = DescendantSampler(path, marker)
sampler.prepare()
runtime = subprocess.Popen([sys.executable, "-I", "-c", runtime_code, case], start_new_session=True,
                           env={**os.environ, "GRAFTLING_MEMBER_RUN": marker},
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
sampler.start(runtime.pid)
runtime.wait()
sampler.finish()
"""
# As Pi 1.4.0's bash tool (/bin/bash -c <command>, detached, own session) running 01's two calls: the first leaves
# the orphan in the background and ends; the second is still running.
STUB_RUNTIME = r"""
import subprocess, sys, time
first = subprocess.Popen(["/bin/bash", "-c", "sleep 1461 >/dev/null 2>&1 & sleep 3"],
                         start_new_session=sys.argv[1] != "ingroup",
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
first.wait()
subprocess.Popen(["/bin/bash", "-c", "sleep 1200"], start_new_session=True,
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(900)
"""


def stub_session(project: Path, name: str, mapping: dict) -> None:
    session = project / '.graphtraj/runner/sessions' / name
    session.mkdir(parents=True, exist_ok=True)
    (session / 'mapping.yml').write_text(yaml.safe_dump(mapping))
    (session / 'execution.yml').write_text(yaml.safe_dump({'last_agent_message': 'stub'}))


def stub(project: Path, case: str) -> int:
    """Without a model: member sessions, the current member's Pi child record and stand-in processes.

    CASE '-': an older task-1 member (as round 1's run left), then the dispatch record, then the current member.
    A stand-in owner Worker (Python, own session) runs the real descendant sampler on a stand-in Runtime (Python,
    own group, the child's marker). The Runtime runs 01's two bash calls as Pi's bash tool does (``/bin/bash -c``,
    own session): the first leaves ``sleep 1461`` in the background and ends, the second (``sleep 1200``) runs.
    CASE 'ingroup': as '-', but the first call runs in the Runtime's group, so the group kill also stops the
    orphan: 02 must print NOT OBSERVED and no ALL PASS (fail-closed check of CHECK 0).
    CASE 'ambiguous': a new dispatch record and two members after it, no alias; no process is started.
    """
    from graftling import AgentControl, Caller, bind
    from graftling.tool_descendants import read_sidecar

    if case == 'ambiguous':
        dispatch_cmd(project, '')
        time.sleep(0.05)
        for name in ('1-stub_ambiguous-team_leader@team_leader_3', '1-stub_ambiguous-team_leader@team_leader_4'):
            stub_session(project, name, {'agent': 'agent-stub-' + name[-1], 'worker_pid': None})
        print('stub ambiguous: two task-1 members created after the dispatch, no alias recorded')
        return 0
    stub_session(project, '1-stub-team_leader@team_leader', {'agent': 'agent-older-member', 'worker_pid': None})
    print('stub: older member 1-stub-team_leader@team_leader (before the dispatch)')
    time.sleep(1.1)
    dispatch_cmd(project, '')
    time.sleep(0.05)
    marker = uuid.uuid4().hex
    environment = {key: value for key, value in os.environ.items() if key != MARKER_ENV}
    work = project / '.graphtraj/probe-461/stub'
    work.mkdir(parents=True, exist_ok=True)
    sidecar = work / f'tool-descendants-{marker[:8]}.json'
    worker = subprocess.Popen([sys.executable, '-I', '-c', STUB_OWNER, str(sidecar), marker, STUB_RUNTIME, case],
                              env=environment, start_new_session=True,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 20
    entries: list = []
    while time.time() < deadline:
        try:
            entries = read_sidecar(sidecar)
        except (OSError, ValueError):
            entries = []
        # As at the real kill: the first call ended (the orphan reparented) and the second call runs.
        if any(is_child_sleep(entry.get('argv', '')) for entry in entries) and \
                any(entry.get('argv') == RUNNING_SLEEP for entry in entries):
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
    current = f'1-stub-team_leader@team_leader_{marker[:4]}'
    stub_session(project, current, {'agent': lead_agent, 'worker_pid': worker.pid})
    print(f'stub: current member {current} agent {lead_agent}, child {agent}, worker '
          f'{worker.pid}, runtime {runtime}; recorded {[(entry["pid"], entry.get("argv")) for entry in entries]}')
    return 0


if __name__ == '__main__':
    command, target, extra = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    commands = {'prepare': prepare, 'isolation': isolation, 'plugins': plugins, 'dispatch': dispatch_cmd,
                'child': child_cmd, 'kill': kill, 'idle': idle, 'stub': stub}
    raise SystemExit(commands[command](target, extra))
