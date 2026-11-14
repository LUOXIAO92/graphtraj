"""463 probe helper: the dsh role, an owner that creates a DSH child, the kill, one reconciling read and the CHECKs.

Usage (the scratch venv's Python, -I):
  probe.py prepare PROJECT SOURCE  copy the only dsh/ connection preset of SOURCE (a project root, read through the
                                   installed roles_file, or a roles file) as probe_463.dsh_child; prints the
                                   connections file path, model and the key variable's NAME only
  probe.py select PROJECT -        what create will launch (installed AdapterDriver.prepare, runtime dsh)
  probe.py owner PROJECT OUT       the owner: creates one DSH child through GraphTraj's agents control and stays
                                   alive (step 01 starts it in the background); answers only the child's exact Bash
                                   approval if DSH asks for one
  probe.py ready PROJECT SECONDS   wait (<= SECONDS, at most 480) until the child's descendants record lists a live
                                   setsid'd '/bin/sleep 4632'
  probe.py kill PROJECT FACTS      refuse unless ready; SIGKILL only the owner; print the recorded descendants still
                                   alive (the residue), start three bystanders, one reconciling read, CHECK 1-4
  probe.py idle OUT -              0 unless an earlier owner (pid file in OUT) or a probe sleep lives
  probe.py stub PROJECT -          rehearsal only: a stand-in owner, dsh web and child record, no model
It never reads or prints a credential value. It signals only the owner it started (after checking its pid and start
time), the child's recorded Runtime group if that is still alive 30 s after the owner's death, and its own bystanders.
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

ESCAPED, IN_GROUP = '4632', '4631'
COMMAND = (f"/usr/bin/perl -MPOSIX -e 'setsid(); exec \"/bin/sleep\",\"{ESCAPED}\"' & /bin/sleep {IN_GROUP}")
INSTRUCTION = (f'Use the Bash tool exactly once to run exactly this command, unchanged: {COMMAND}\n'
               'It runs for a long time; do not wait for it in any other way and run nothing else.')
MARKER_ENV = 'GRAFTLING_MEMBER_RUN'
CALLER = 'verify-463'


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def check(label: str, ok: bool, detail: str = '') -> bool:
    print(f'CHECK {"PASS" if ok else "FAIL"}: {label}' + (f' | {detail}' if detail else ''))
    return ok


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


# -- prepare ----------------------------------------------------------------------

GROUP, ROLE = 'probe_463', 'dsh_child'
REFERENCE = f'{GROUP}.{ROLE}'


def dsh_presets(document: dict) -> dict[str, dict]:
    """Presets whose connection is a DSH one, by reference, in the installed schema
    (project_roles._roles_from_document: a group maps role names to mappings; a flat entry is its own preset)."""
    found = {}
    for name, entry in ((document or {}).get('roles') or {}).items():
        if isinstance(entry, dict) and entry and all(isinstance(value, dict) for value in entry.values()):
            items = [(f'{name}.{role}', value) for role, value in entry.items()]
        else:
            items = [(name, entry)]
        for reference, value in items:
            if isinstance(value, dict) and str(value.get('connection', '')).startswith('dsh/'):
                found[reference] = value
    return found


def prepare(project: Path, source: str) -> int:
    """The isolated project's one preset: the source's only DSH connection (and effort), nothing else.

    SOURCE is a project root (its roles file via the installed roles_file) or a roles file (rehearsal fixture).
    instructions and reports are not copied: their files and paths do not exist in the isolated project."""
    from graphtraj.configuration.project_roles import roles_file
    from graphtraj.configuration.runtime_connections import connections_file, resolve_connection

    path = Path(source) if Path(source).is_file() else roles_file(Path(source))
    print(f'source roles file: {path}')
    try:
        found = dsh_presets(yaml.safe_load(path.read_text()))
    except (OSError, yaml.YAMLError) as error:
        print(f'STOP: cannot read {path}: {type(error).__name__}')
        return 1
    if len(found) != 1:
        print(f'STOP: need exactly one preset with a dsh/ connection in {path}; found {sorted(found) or "none"}.')
        return 1
    (source_ref, entry), = found.items()
    preset = {key: entry[key] for key in ('connection', 'reasoning_effort') if key in entry}
    target = roles_file(project)
    target.write_text(yaml.safe_dump({'roles': {GROUP: {ROLE: preset}}}))
    print(f'isolated roles file: {target} | preset {REFERENCE} <- {source_ref}: {preset}')
    catalog = connections_file()
    print(f'connections file: {catalog} | exists: {catalog.exists()}')
    try:
        resolved = resolve_connection(preset['connection'], preset.get('reasoning_effort'))
    except (OSError, ValueError) as error:
        print(f'STOP: connection {preset["connection"]} does not resolve from {catalog}: {error}')
        return 1
    key = resolved.get('api_key_env')
    print(f'connection resolves: runtime {resolved["runtime"]} | model {resolved["model"]} | base_url set '
          f'{bool(resolved.get("base_url"))} | key variable (name only): {key or "none (DSH login)"}')
    work = project / '.graphtraj/probe-463'
    work.mkdir(exist_ok=True)
    (work / 'keyvar').write_text(key or '')
    done = subprocess.run([str(Path(sys.executable).parent / 'graphtraj'), 'doctor'],
                          capture_output=True, text=True, timeout=300)
    ok = 'roles: OK' in done.stdout
    print('roles OK' if ok else 'roles NOT OK: ' + (done.stdout + done.stderr)[-600:])
    return 0 if ok else 1


def select(project: Path, _unused: str) -> int:
    """What the owner's create will launch: the installed AdapterDriver.prepare for runtime dsh and the preset."""
    from graftling import Caller
    from graphtraj.execution.agent_driver import AdapterDriver

    try:
        prepared = AdapterDriver(project, project).prepare('dsh', Caller(CALLER, None), configuration=REFERENCE)
    except Exception as error:
        print(f'STOP: create would refuse: {getattr(error, "code", type(error).__name__)}: {error}')
        return 1
    request = prepared['adapter_request']
    print(f'create selects: role {prepared["role"]} | runtime dsh | model {request.get("model")} | connection '
          f'{request.get("connection")} | DSH home set {bool(request.get("runtime_home"))} | base_url set '
          f'{bool(request.get("base_url"))} | key variable {request.get("api_key_env") or "none"} | sandbox '
          f'{request.get("sandbox")} | dsh {request.get("executable")}')
    return 0


# -- owner --------------------------------------------------------------------------

def owner(project: Path, out: str) -> int:
    """Create one DSH child as a host caller and keep owning it; never returns on its own before 9 minutes."""
    from graftling import Caller, bind
    from graphtraj.interfaces.agents import GraphTrajAgents

    agents = GraphTrajAgents(project)
    call = bind(agents.control, Caller(CALLER, None))
    print(now(), 'owner pid', os.getpid(), 'creating the DSH child', flush=True)
    created = call({'action': 'create', 'runtime': 'dsh', 'configuration': REFERENCE,
                    'instruction': INSTRUCTION}).document
    agent = created.get('agent')
    Path(out).write_text(json.dumps({'agent': agent, 'owner_pid': os.getpid(), 'created': created.get('execution')}))
    print(now(), 'CREATED', agent, created.get('execution'), flush=True)
    answered: set[str] = set()
    deadline = time.time() + 540
    while time.time() < deadline:
        try:
            pending = call({'action': 'requests', 'agent': agent}).document.get('requests', [])
        except Exception as error:
            print(now(), 'requests failed:', type(error).__name__, error, flush=True)
            pending = []
        for request in pending:
            token = request.get('request_token')
            text = json.dumps(request.get('action') or request.get('params') or {})
            if token in answered:
                continue
            answered.add(token)
            if ESCAPED in text and IN_GROUP in text and request.get('method') == 'dsh/approval-request':
                reply = call({'action': 'reply', 'agent': agent, 'request': request, 'response': {'decision': 'allow'}})
                print(now(), 'APPROVAL answered allow by the owner probe for the exact command:',
                      reply.document.get('reply_status', reply.document.get('state')), flush=True)
            else:
                print(now(), 'APPROVAL left unanswered (not the exact command):', request.get('method'),
                      text[:200], flush=True)
        time.sleep(3)
    print(now(), 'owner: 9 minutes passed without being killed; exiting (the child ends with it)', flush=True)
    return 0


# -- reading the record --------------------------------------------------------------

def facts(project: Path) -> tuple[dict, dict, dict]:
    """(owner.json, child record, its last execution); empty dicts when missing."""
    try:
        made = json.loads((project / '.graphtraj/probe-463/owner.json').read_text())
    except (OSError, ValueError):
        return {}, {}, {}
    from graphtraj.interfaces.agents import swarm_root

    path = swarm_root(project) / 'control/agents' / f'{made.get("agent")}.json'
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        return made, {}, {}
    return made, record, (record.get('executions') or [{}])[-1]


def recorded(sidecar: object) -> tuple[list[dict], str | None]:
    if not isinstance(sidecar, str) or not sidecar:
        return [], 'no tool_descendants fact'
    try:
        from graftling.tool_descendants import read_sidecar

        return read_sidecar(sidecar), None
    except (OSError, ValueError) as error:
        return [], f'{type(error).__name__}: {error}'


def live(entry: dict) -> bool:
    from graftling.tool_descendants import identity

    found = identity(entry['pid'])
    return found is not None and found.start == entry['start'] and found.uid == entry['uid']


def escaped_sleeps(entries: list[dict]) -> list[dict]:
    """Recorded live '/bin/sleep 4632' that leads its own group (it left the tool's group by setsid)."""
    return [entry for entry in entries if entry.get('argv', '').split()[:2] == ['/bin/sleep', ESCAPED]
            and entry.get('pgid') == entry['pid'] and live(entry)]


def state_line(made: dict, record: dict, execution: dict) -> str:
    process = execution.get('process') or {}
    entries, error = recorded(process.get('tool_descendants'))
    return (f'child {record.get("agent")} execution {execution.get("id")} state {execution.get("state")} '
            f'worker_pid {process.get("worker_pid")} (owner {made.get("owner_pid")}) runtime_pid '
            f'{process.get("runtime_pid")} tool_marker recorded {bool(process.get("tool_marker"))} '
            f'tool_descendants {process.get("tool_descendants")} entries {len(entries)} '
            f'escaped sleep {[entry["pid"] for entry in escaped_sleeps(entries)]}' + (f' ({error})' if error else ''))


def ready(project: Path, seconds: str) -> int:
    deadline = time.time() + min(float(seconds), 480)
    while True:
        made, record, execution = facts(project)
        process = execution.get('process') or {}
        entries, _ = recorded(process.get('tool_descendants'))
        if execution.get('state') == 'running' and escaped_sleeps(entries):
            print(now(), 'CHILD-READY |', state_line(made, record, execution))
            return 0
        if made and not alive(made.get('owner_pid')):
            print(now(), 'STOP: the owner already ended |', state_line(made, record, execution))
            return 1
        if time.time() >= deadline:
            print(now(), 'NOT READY |', state_line(made, record, execution))
            return 1
        time.sleep(3)


# -- kill, read, checks ------------------------------------------------------------------

def bystander(marker: str | None) -> subprocess.Popen:
    environment = {key: value for key, value in os.environ.items() if key != MARKER_ENV}
    if marker is not None:
        environment[MARKER_ENV] = marker
    return subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(900)'], env=environment,
                            start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def kill(project: Path, facts_file: str) -> int:
    from graftling.tool_descendants import identity
    from graphtraj.interfaces.agents import GraphTrajAgents

    made, record, execution = facts(project)
    process = execution.get('process') or {}
    owner_pid, runtime = made.get('owner_pid'), process.get('runtime_pid')
    print('before the kill:', state_line(made, record, execution))
    entries, error = recorded(process.get('tool_descendants'))
    print('before the kill: recorded descendants:', [(e['pid'], e.get('pgid'), e.get('argv', '')[:90]) for e in entries])
    sleeps = escaped_sleeps(entries)
    if (not record or execution.get('state') != 'running' or process.get('worker_pid') != owner_pid
            or not process.get('tool_marker') or error or not sleeps):
        print("STOP: no running child owned by this probe's owner, no tool_marker/tool_descendants, or no live "
              f"setsid'd '/bin/sleep {ESCAPED}' recorded (the venv lacks the 463 fix, or the tool did not run). "
              'Nothing was signalled.')
        return 1
    owner_identity, runtime_identity = identity(owner_pid), identity(runtime)
    killed: list = []
    if owner_identity is not None and identity(owner_pid) == owner_identity:
        os.kill(owner_pid, signal.SIGKILL)
        killed.append({'label': 'owner', 'pid': owner_pid, 'at': time.time()})
        print(f'owner {owner_pid}: SIGKILL')
    else:
        print(f'STOP: owner {owner_pid} is gone or changed. Nothing was signalled.')
        return 1
    # The watcher stops dsh web (SIGINT, SIGTERM, SIGKILL at 5 s each); DSH disposes its tool groups on SIGINT.
    deadline = time.time() + 30
    while runtime_identity is not None and time.time() < deadline:
        found = identity(runtime)
        if found is None or found.start != runtime_identity.start:
            break
        time.sleep(0.2)
    found = identity(runtime) if runtime_identity is not None else None
    if found is not None and found.start == runtime_identity.start:
        os.killpg(runtime, signal.SIGKILL) if os.getpgid(runtime) == runtime else os.kill(runtime, signal.SIGKILL)
        killed.append({'label': 'dsh web (still alive 30 s after the owner)', 'pid': runtime, 'at': time.time()})
        print(f'dsh web {runtime}: still alive after 30 s, SIGKILL')
        time.sleep(1)
    else:
        print(f'dsh web {runtime}: gone (its watcher stopped it)')
    residue = [(entry['pid'], entry.get('pgid'), entry.get('argv', '')[:90]) for entry in entries if live(entry)]
    print('RESIDUE after the kill, before reconciliation: recorded descendants still alive:', residue)

    others = [bystander(uuid.uuid4().hex), bystander(None),
              subprocess.Popen(['/bin/sleep', '901'], start_new_session=True)]
    time.sleep(0.5)
    print('bystanders:', [(item.pid, item.poll() is None) for item in others])
    results: list = []
    escaped = None
    try:
        started = time.time()
        GraphTrajAgents(project).control.unconfirmed_ends(record['agent'])
        from graphtraj.interfaces.agents import swarm_root

        state = (json.loads((swarm_root(project) / 'control/agents' / f'{record["agent"]}.json').read_text())
                 .get('executions') or [{}])[-1]
        escaped = state.get('escaped_processes')
        print(f'read: {time.time() - started:.1f} s; child {state.get("state")} {state.get("outcome")} '
              f'{(state.get("error") or {}).get("code")}')
        print('escaped_processes:', json.dumps(escaped, ensure_ascii=False))
        results.append(check('1 child execution failed / owner-exited', state.get('outcome') == 'failed'
                             and (state.get('error') or {}).get('code') == 'owner-exited'))
        stopped = {item.get('pid') for item in (escaped or {}).get('stopped', [])}
        survivors = {pid for pid, _, _ in residue}
        results.append(check('2 escaped_processes stopped the survivors, remaining [], no error',
                             bool(escaped) and bool(survivors) and survivors <= stopped
                             and escaped.get('remaining') == [] and not escaped.get('error'),
                             f'survivors={sorted(survivors)} stopped={sorted(stopped)} '
                             f'remaining={(escaped or {}).get("remaining")} error={(escaped or {}).get("error")}'))
        left = [(entry['pid'], entry.get('argv', '')[:60]) for entry in entries if live(entry)]
        results.append(check('3 none of the recorded identities alive', not left, f'alive={left}'))
        results.append(check('4 the three bystanders alive', all(item.poll() is None for item in others),
                             str([(item.pid, item.poll() is None) for item in others])))
    finally:
        for item in others:
            if item.poll() is None:
                item.terminate()
            try:
                item.wait(5)
            except subprocess.TimeoutExpired:
                item.kill()
                item.wait(5)
    Path(facts_file).write_text(json.dumps({
        'owner': made, 'child': record.get('agent'), 'execution': execution.get('id'), 'runtime_pid': runtime,
        'recorded_before_kill': entries, 'residue': residue, 'killed': killed, 'escaped_processes': escaped,
        'checks': results}, indent=2))
    print('== summary:', 'ALL PASS' if results and all(results) else f'{results.count(False)} FAIL of {len(results)}',
          f'| facts in {facts_file}')
    return 0 if results and all(results) else 1


def idle(out: Path, _unused: str) -> int:
    """0 when no earlier owner (pid file) and no probe sleep lives; signals nothing."""
    busy = []
    try:
        pid = int((out / '01-owner.pid').read_text().strip())
        if alive(pid):
            busy.append(f'owner {pid}')
    except (OSError, ValueError):
        pass
    try:
        listing = subprocess.run(['ps', '-axo', 'pid=,command='], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        listing = ''  # ps is not allowed in the sandbox rehearsal; the real host has it
    busy += [line.strip()[:80] for line in listing.splitlines()
             if f'sleep {ESCAPED}' in line or f'sleep {IN_GROUP}' in line]
    busy = [item for item in busy if 'probe.py' not in item and 'ps -axo' not in item]
    if busy:
        print('STOP: an earlier run still lives; changed nothing:', busy)
        return 1
    print('no earlier probe process alive')
    return 0


# -- rehearsal only ---------------------------------------------------------------------

STUB_WEB = r'''
import os, signal, subprocess, sys
tool = subprocess.Popen(["/bin/zsh", "-c", sys.argv[1]], start_new_session=True)
def stop(*_):
    try:
        os.killpg(tool.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    os._exit(0)
signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)
sys.stdin.read()
stop()
'''
STUB_OWNER = r'''
import os, subprocess, sys, time
from graftling.tool_descendants import DescendantSampler
path, marker, web, command = sys.argv[1:5]
sampler = DescendantSampler(path, marker)
sampler.prepare()
service = subprocess.Popen([sys.executable, "-I", "-c", web, command], stdin=subprocess.PIPE, start_new_session=True,
                           env={**os.environ, "GRAFTLING_MEMBER_RUN": marker})
sampler.start(service.pid)
time.sleep(900)
'''


def stub(project: Path, _unused: str) -> int:
    """Without a model: a stand-in owner runs the real sampler on a stand-in dsh web that starts the exact tool
    command in a real /bin/zsh in its own session and disposes that group when its owner dies, as DSH does."""
    from graftling import AgentControl, Caller, bind

    marker = uuid.uuid4().hex
    work = project / '.graphtraj/probe-463'
    work.mkdir(parents=True, exist_ok=True)
    sidecar = work / 'stub-tool-descendants.json'
    environment = {key: value for key, value in os.environ.items() if key != MARKER_ENV}
    owner_process = subprocess.Popen([sys.executable, '-I', '-c', STUB_OWNER, str(sidecar), marker, STUB_WEB, COMMAND],
                                     env=environment, start_new_session=True)
    deadline = time.time() + 20
    while time.time() < deadline and not (sidecar.exists() and json.loads(sidecar.read_text()).get('runtime_pid')):
        time.sleep(0.2)
    runtime = json.loads(sidecar.read_text()).get('runtime_pid') if sidecar.exists() else None
    if runtime is None:
        print('STOP: the stand-in owner did not start its dsh web')
        return 1

    class Driver:
        def prepare(self, runtime_name, caller):
            return {}

        def start(self, run):
            run.events.session('stub-' + run.agent[-6:])
            run.events.process(runtime_pid=runtime, tool_marker=marker, tool_descendants=str(sidecar.resolve()))

        def deliver(self, run, message):
            pass

        def interrupt(self, run):
            return True

    from graphtraj.interfaces.agents import swarm_root

    root = swarm_root(project)
    control = AgentControl(root, {'stub': Driver()})
    agent = bind(control, Caller('stub-host', None))({'action': 'create', 'runtime': 'stub',
                                                      'instruction': 'w'}).document['agent']
    path = root / 'control/agents' / f'{agent}.json'
    data = json.loads(path.read_text())
    data['executions'][-1]['process']['worker_pid'] = owner_process.pid
    path.write_text(json.dumps(data, indent=2, sort_keys=True))
    (work / 'owner.json').write_text(json.dumps({'agent': agent, 'owner_pid': owner_process.pid}))
    print(f'stub: child {agent}, owner {owner_process.pid}, dsh web {runtime}')
    return 0


if __name__ == '__main__':
    command, target, extra = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    commands = {'prepare': prepare, 'select': select, 'owner': owner, 'ready': ready, 'kill': kill, 'idle': idle, 'stub': stub}
    raise SystemExit(commands[command](target, extra))
