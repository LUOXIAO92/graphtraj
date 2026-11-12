"""451 probe helper: roles, the probe Task, the member's child, the kill, and whether the lost end reached the member once.

Usage (the scratch venv's Python):
  python -I probe.py prepare PROJECT MODEL     roles (team_leader claude, permission_mode auto) and probe Task 1, ready
  python -I probe.py plugins STREAM -          0 only when graphtraj-claude-host is loaded
  python -I probe.py child PROJECT SECONDS     poll (<=100 s) until the member's child runs with a runtime_pid: CHILD-RUNNING
  python -I probe.py kill PROJECT FACTS        SIGKILL the Worker owning the child, then the child's (and member's) Runtime
  python -I probe.py wait PROJECT SECONDS      poll (<=100 s) until the member's records show REPORT-451-END: MEMBER-DONE
  python -I probe.py observe PROJECT FACTS     read only: the four CHECK lines and a summary
  python -I probe.py idle OUT -                0 unless an earlier probe Main (pid files in OUT) or 'sleep 400' lives
Prints only facts read from the isolated project and process tables; it reads no credential.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

TASK_ID = '1'
NAME = 'owner-exited-probe'
END = 'REPORT-451-END'
CHILD_SLEEP = 'sleep 400'
SWEEP_BOUND = 60
BODY = '''---
difficulty: low
difficulty_reason: Scratch probe for 451
execution_budget:
  estimated_minutes:
    total: 30
  planned_sessions:
    team_leader: 1
  correction_rounds: 0
  estimation_note: One agents-tool child whose owner is killed, then one report
  on_exceed: Report only
---
Follow the dispatch instruction exactly.
'''


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def stamp(value: float | None) -> str:
    return datetime.fromtimestamp(value).astimezone().isoformat(timespec='seconds') if value else 'none'


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
    work = project / '.graphtraj/probe-451'
    work.mkdir(exist_ok=True)
    register = work / 'register.yml'
    register.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'task_name': NAME, 'source': 'local:scratch/451', 'title': NAME, 'body': BODY,
        'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
        'replaced_by': [], 'retirement_reason': None}))
    state = work / 'state.yml'
    state.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
        'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-451/evidence.md']}))
    rc = 0
    if not list(project.glob('.graphtraj/state/tasks/1-*/task.yml')):
        rc = run(str(bin_dir / 'graphtraj'), 'task', 'register', '--task-file', str(register)).returncode
    (work / 'evidence.md').write_text('451 probe: ready for one member with one agents-tool child.\n')
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


def report_text(project: Path) -> str | None:
    """The member's last execution message holding REPORT-451-END, if any."""
    _, _, directory = member(project)
    execution = directory / 'execution.yml' if directory else None
    if execution and execution.is_file():
        message = (yaml.safe_load(execution.read_text()) or {}).get('last_agent_message') or ''
        if END in message:
            return message
    return None


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


def child_cmd(project: Path, seconds: str) -> int:
    def facts():
        alias, mapping, _ = member(project)
        record = child(project, alias, mapping.get('agent'))
        execution = (record.get('executions') or [{}])[-1]
        return alias, mapping, record, execution

    def done():
        _, _, record, execution = facts()
        return bool(record) and execution.get('state') == 'running' and alive((execution.get('process') or {}).get('runtime_pid'))

    def state():
        alias, mapping, record, execution = facts()
        return (f'member={alias} worker_pid={mapping.get("worker_pid")} child={record.get("agent")} '
                f'execution={execution.get("id")} state={execution.get("state")} process={execution.get("process")}')

    code = poll(project, seconds, done, 'CHILD-RUNNING', state)
    print(state())
    return code


def wait(project: Path, seconds: str) -> int:
    def state():
        alias, mapping, _ = member(project)
        record = core(project, mapping.get('agent'))
        last = (record.get('executions') or [{}])[-1]
        return f'member={alias} core execution={last.get("id")} state={last.get("state")} outcome={last.get("outcome")}'

    return poll(project, seconds, lambda: report_text(project) is not None, 'MEMBER-DONE', state)


# -- Kill ---------------------------------------------------------------------

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


def kill(project: Path, facts_file: str) -> int:
    alias, mapping, _ = member(project)
    record = child(project, alias, mapping.get('agent'))
    execution = (record.get('executions') or [{}])[-1]
    process = execution.get('process') or {}
    worker = mapping.get('worker_pid')
    print(f'member {alias} worker_pid {worker} runtime_pid {mapping.get("runtime_pid")} agent {mapping.get("agent")}')
    print(f'child {record.get("agent")} execution {execution.get("id")} state {execution.get("state")} process {process}')
    if execution.get('state') != 'running':
        print('STOP: the child execution is not running; nothing was killed.')
        return 1
    if not isinstance(worker, int) or worker != process.get('worker_pid'):
        print('STOP: the member mapping worker_pid is not the child execution worker_pid; nothing was killed.')
        return 1
    killed: list = []
    os.kill(worker, signal.SIGKILL)
    killed.append({'label': 'worker', 'pid': worker, 'at': time.time()})
    print(f'worker {worker}: SIGKILL')
    time.sleep(2)
    kill_group(process.get('runtime_pid'), 'child runtime', killed)
    # The member's own Runtime loses its Worker too; it is stopped so the Runner can resume the member.
    kill_group(mapping.get('runtime_pid'), 'member runtime', killed)
    time.sleep(1)
    facts = {'alias': alias, 'member_agent': mapping.get('agent'), 'child': record.get('agent'),
             'execution': execution.get('id'), 'worker_pid': worker, 'child_runtime_pid': process.get('runtime_pid'),
             'member_runtime_pid': mapping.get('runtime_pid'), 'killed': killed, 'killed_at': time.time()}
    Path(facts_file).write_text(json.dumps(facts, indent=2))
    print('alive after kill:', {item['label']: alive(item['pid']) for item in killed})
    print(f'KILLED child {facts["child"]} execution {facts["execution"]}; facts in {facts_file}')
    return 0


# -- Observe ------------------------------------------------------------------

def embedded_notices(text: str) -> list[dict]:
    found, decoder = [], json.JSONDecoder()
    for match in re.finditer(r'\{"source": ?"graphtraj"', text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
        except ValueError:
            continue
        if isinstance(value, dict):
            found.append(value)
    return found


def strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def recorded_notices(project: Path, agent: str) -> dict[str, list[dict]]:
    """Notices naming ``agent`` in any text record under the project's .graphtraj, by file."""
    found: dict[str, list[dict]] = {}
    for path in (project / '.graphtraj').rglob('*'):
        if (not path.is_file() or path.stat().st_size > 50_000_000
                or path.suffix not in {'.jsonl', '.json', '.yml', '.yaml', '.txt'}):
            continue
        try:
            text = path.read_text(errors='replace')
        except OSError:
            continue
        if agent not in text:
            continue
        values = []
        for line in text.splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                record = None
            for value in strings(record) if record is not None else [line]:
                values.extend(embedded_notices(value))
        notices = [notice for notice in values if notice.get('alias') == agent]
        if notices:
            found[str(path.relative_to(project))] = notices
    return found


def probe_processes() -> dict[int, str]:
    """Live same-user processes running the child's ``sleep 400`` (read only)."""
    try:
        listing = subprocess.run(['ps', '-axo', 'pid=,command='], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    found = {}
    for line in listing.splitlines():
        pid, _, command = line.strip().partition(' ')
        if CHILD_SLEEP in command and 'probe.py' not in command and pid.isdigit():
            found[int(pid)] = command[:160]
    return found


PID_FILES = ('01-main.pid', '01-main-stream.pid', '03-main.pid', '03-main-stream.pid')


def idle(out: Path, _unused: str) -> int:
    """0 when no earlier probe Main (pid files in ``out``) and no 'sleep 400' runs; signals nothing."""
    busy = {}
    for name in PID_FILES:
        try:
            pid = int((out / name).read_text().strip())
        except (OSError, ValueError):
            continue
        if alive(pid):
            busy[name] = pid
    sleeping = probe_processes()
    if not busy and not sleeping:
        print('no earlier probe process alive')
        return 0
    print('STILL ALIVE from an earlier run:', {**{f'pid file {k}': v for k, v in busy.items()},
                                              **{f'sleep 400 pid {k}': v for k, v in sleeping.items()}})
    print('STOP: changed nothing. Wait for it to end, then rerun (the child\'s sleep 400 ends 400 s after it started).')
    return 1


def check(label: str, ok: bool, detail: str = '') -> bool:
    print(f'CHECK {"PASS" if ok else "FAIL"}: {label}' + (f' | {detail}' if detail else ''))
    return ok


def observe(project: Path, facts_file: str) -> int:
    facts = json.loads(Path(facts_file).read_text())
    agent, execution_id = facts['child'], facts['execution']
    record = core(project, agent)
    execution = next((item for item in record.get('executions', []) if item.get('id') == execution_id), {})
    print('== child', agent, 'execution', execution_id)
    print('   ', json.dumps({key: execution.get(key) for key in (
        'state', 'outcome', 'error', 'terminal_confirmed', 'notification', 'ended_at', 'process')}, ensure_ascii=False))
    results = [check('1 child execution failed / owner-exited / delivered (or queued)',
                     execution.get('outcome') == 'failed'
                     and (execution.get('error') or {}).get('code') == 'owner-exited'
                     and execution.get('notification') in {'delivered', 'queued'},
                     f'notification={execution.get("notification")}')]

    found = recorded_notices(project, agent)
    distinct: dict[str, set[str]] = {}
    for path, notices in sorted(found.items()):
        print('   notices in', path, ':', len(notices))
        for notice in notices:
            distinct.setdefault(str(notice.get('execution')), set()).add(json.dumps(notice, sort_keys=True, ensure_ascii=False))
    for texts in distinct.values():
        for text in sorted(texts):
            print('   NOTICE', text)
    mine = distinct.get(execution_id, set())
    report = report_text(project) or ''
    print('== member final report (raw):')
    print(report or '(none)')
    reported = [notice for notice in embedded_notices(report)
                if notice.get('alias') == agent and notice.get('execution') == execution_id and notice.get('event') == 'failed']
    results.append(check('2 one distinct notice for the execution in the records, and one failed input in the member report',
                         len(mine) == 1 and len(reported) == 1,
                         f'distinct in records={len(mine)} reported={len(reported)} other executions={sorted(set(distinct) - {execution_id})}'))

    member_record = core(project, facts.get('member_agent'))
    resumed = [item for item in member_record.get('executions', [])
               if (item.get('started_at') or 0) > facts['killed_at']]
    started = resumed[0].get('started_at') if resumed else None
    ended = execution.get('ended_at')
    print(f'   killed at {stamp(facts["killed_at"])}; member resumed execution started {stamp(started)}; '
          f'child end recorded (reconciled) {stamp(ended)}')
    if started and ended and ended >= started:
        delay = ended - started
        results.append(check(f'3 found and sent within {SWEEP_BOUND} s after the resumed execution started (sweep)',
                             delay <= SWEEP_BOUND, f'{delay:.1f} s'))
    else:
        detail = ('a read before the resumed execution reconciled it' if started and ended
                  else 'no resumed member execution after the kill' if not started else 'the child has no end')
        results.append(check('3 found by the resumed member\'s sweep', False, detail +
                             ' (the reconciling control delivered it; see notification above)'))

    pids = {item['label']: item['pid'] for item in facts.get('killed', [])}
    left = {label: pid for label, pid in pids.items() if alive(pid)}
    sleeping = probe_processes()
    results.append(check('4 no probe process alive (worker, runtimes, the child\'s sleep 400)',
                         not left and not sleeping, f'alive={left} sleep400={sleeping}'))
    print('== summary:', 'ALL PASS' if all(results) else f'{results.count(False)} FAIL of {len(results)}')
    return 0 if all(results) else 1


if __name__ == '__main__':
    command, target, extra = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    commands = {'prepare': prepare, 'plugins': plugins, 'child': child_cmd, 'kill': kill,
                'wait': wait, 'observe': observe, 'idle': idle}
    raise SystemExit(commands[command](target, extra))
