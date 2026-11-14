"""451 probe helper: roles, the probe Task, the member's child, the kill, and whether the lost end reached the member once.

Usage (the scratch venv's Python):
  python -I probe.py prepare PROJECT MODEL     roles (team_leader claude, permission_mode auto) and probe Task 1, ready
  python -I probe.py plugins STREAM -          0 only when graphtraj-claude-host is loaded
  python -I probe.py child PROJECT SECONDS     poll (<=100 s) until the member's turn ended and its child runs: CHILD-RUNNING
  python -I probe.py kill PROJECT FACTS        member idle: SIGKILL the child's owner and Runtime if alive, then two reads
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


def _stream_at() -> float | None:
    """Creation time of this run's 01 Main stream ($PROBE_OUT/01-main-stream.jsonl), or None (471)."""
    try:
        return born(Path(os.environ.get('PROBE_OUT', '/nonexistent')) / '01-main-stream.jsonl')
    except OSError:
        return None


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
    # 471: a child created before this dispatch (e.g. an earlier member under a reused alias) is not this member's.
    at = _stream_at()
    stale = [r.get('agent') for r in found
             if at is None or not isinstance(r.get('created_at'), (int, float)) or r['created_at'] < at]
    if stale:
        print('  children created before this dispatch, ignored:', stale)
    found = [r for r in found if r.get('agent') not in stale]
    if len(found) > 1:
        print('STOP: more than one child of the member created after this dispatch:', [r['agent'] for r in found],
              '- none is used; nothing is signalled.')
        return {}
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
        # The record still says running (nothing reconciled it yet); its Runtime may or may not live.
        _, _, record, execution = facts()
        return (bool(record) and execution.get('state') == 'running'
                and bool((execution.get('process') or {}).get('runtime_pid')) and member_terminal(project))

    def state():
        alias, mapping, record, execution = facts()
        process = execution.get('process') or {}
        return (f'member={alias} turn ended={member_terminal(project)} worker_pid={mapping.get("worker_pid")} '
                f'child={record.get("agent")} execution={execution.get("id")} state={execution.get("state")} '
                f'process={process} worker alive={alive(process.get("worker_pid"))} '
                f'runtime alive={alive(process.get("runtime_pid"))}')

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
    """With the member idle: stop the child's owner and Runtime if alive, then read twice with a receiver."""
    alias, mapping, _ = member(project)
    record = child(project, alias, mapping.get('agent'))
    execution = (record.get('executions') or [{}])[-1]
    process = execution.get('process') or {}
    worker = process.get('worker_pid')
    print(f'member {alias} agent {mapping.get("agent")} worker_pid {mapping.get("worker_pid")} turn ended {member_terminal(project)}')
    print(f'child {record.get("agent")} execution {execution.get("id")} state {execution.get("state")} process {process}')
    if not member_terminal(project):
        print('STOP: the member\'s turn has not ended; its Worker is never killed while it runs. Nothing was done.')
        return 1
    if not record or worker != mapping.get('worker_pid'):
        print('STOP: no child, or the child\'s owner is not the member\'s last Worker. Nothing was done.')
        return 1
    killed: list = []
    if alive(worker):
        os.kill(worker, signal.SIGKILL)
        killed.append({'label': 'worker', 'pid': worker, 'at': time.time()})
        print(f'worker {worker}: alive after the turn ended (452 behaviour): SIGKILL')
        time.sleep(2)
    else:
        print(f'worker {worker}: already exited at the turn end (base behaviour)')
    kill_group(process.get('runtime_pid'), 'child runtime', killed)
    time.sleep(1)
    print('alive after kill:', {item['label']: alive(item['pid']) for item in killed} or 'nothing was killed')

    from graphtraj.interfaces.agents import GraphTrajAgents

    held = []
    for read in (1, 2):
        GraphTrajAgents(project).reconcile_children({alias, mapping.get('agent')})
        state = (core(project, record['agent']).get('executions') or [{}])[-1]
        held.append({'read': read, 'at': time.time(), 'state': state.get('state'), 'outcome': state.get('outcome'),
                     'error': (state.get('error') or {}).get('code'), 'notification': state.get('notification')})
        print(f'read {read}: child {state.get("state")} {state.get("outcome")} '
              f'{(state.get("error") or {}).get("code")} notification={state.get("notification")} '
              f'member turn ended={member_terminal(project)}')
    facts = {'alias': alias, 'member_agent': mapping.get('agent'), 'child': record.get('agent'),
             'execution': execution.get('id'), 'worker_pid': worker, 'child_runtime_pid': process.get('runtime_pid'),
             'killed': killed, 'killed_at': time.time(), 'held': held}
    Path(facts_file).write_text(json.dumps(facts, indent=2))
    ok = [item['notification'] for item in held] == ['held', 'held']
    print(('HELD-TWICE' if ok else 'NOT HELD TWICE') + f' child {facts["child"]} execution {facts["execution"]}; facts in {facts_file}')
    return 0 if ok else 1


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
    held = facts.get('held') or []
    held_at = max((item['at'] for item in held), default=None)
    resumed = [item for item in member_record.get('executions', []) if (item.get('started_at') or 0) > (held_at or 0)]
    started = resumed[0].get('started_at') if resumed else None
    print(f'   held by the idle-member reads: {[item["notification"] for item in held]} (last at {stamp(held_at)}); '
          f'member resumed execution started {stamp(started)}; notification now {execution.get("notification")}')
    results.append(check('3 held while the member was idle, delivered after its resumed execution started',
                         [item['notification'] for item in held] == ['held', 'held'] and bool(started)
                         and execution.get('notification') in {'delivered', 'queued'} and len(reported) == 1,
                         f'held={[item["notification"] for item in held]} resumed={bool(started)}'))

    pids = {item['label']: item['pid'] for item in facts.get('killed', [])}
    left = {label: pid for label, pid in pids.items() if alive(pid)}
    sleeping = probe_processes()
    results.append(check('4 no probe process alive (the killed owner and child Runtime, the child\'s sleep 400)',
                         not left and not sleeping, f'alive={left} sleep400={sleeping}'))
    print('== summary:', 'ALL PASS' if all(results) else f'{results.count(False)} FAIL of {len(results)}')
    return 0 if all(results) else 1


if __name__ == '__main__':
    command, target, extra = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    commands = {'prepare': prepare, 'plugins': plugins, 'child': child_cmd, 'kill': kill,
                'wait': wait, 'observe': observe, 'idle': idle}
    raise SystemExit(commands[command](target, extra))
