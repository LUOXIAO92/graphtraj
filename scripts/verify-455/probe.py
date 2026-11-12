"""455 probe helper: roles, the probe Task, and the configuration/model an agents child records and ran with.

Usage (the scratch venv's Python):
  python -I probe.py prepare PROJECT MODEL     roles (team_leader, advisor) and probe Task 1, ready
  python -I probe.py plugins STREAM -          0 only when graphtraj-claude-host is loaded
  python -I probe.py wait PROJECT SECONDS      poll (<120 s) until the member's final report exists
  python -I probe.py observe PROJECT STREAM    wait (<540 s) for Main to end, then print one CHECK per criterion
  python -I probe.py check REPORT RECORD SESSION   the same checks on given files (rehearsal on synthetic records)
Prints only facts read from the isolated project, the Main stream and the child's native Session; it reads no credential.
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
NAME = 'configuration-recorded-probe'
END = 'REPORT-455-END'
ADVISOR_EFFORT = 'high'
BODY = '''---
difficulty: low
difficulty_reason: Scratch probe for 455
execution_budget:
  estimated_minutes:
    total: 30
  planned_sessions:
    team_leader: 1
  correction_rounds: 0
  estimation_note: One agents-tool child with configuration advisor, then one report
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
                                  'reports': ['report.md']},
                  'advisor': {'runtime': 'claude', 'model': model, 'reasoning_effort': ADVISOR_EFFORT}},
        'role_tree': {'team_leader': {}},
    }))
    work = project / '.graphtraj/probe-455'
    work.mkdir(exist_ok=True)
    register = work / 'register.yml'
    register.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'task_name': NAME, 'source': 'local:scratch/455', 'title': NAME, 'body': BODY,
        'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
        'replaced_by': [], 'retirement_reason': None}))
    state = work / 'state.yml'
    state.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
        'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-455/evidence.md']}))
    rc = 0
    if not list(project.glob('.graphtraj/state/tasks/1-*/task.yml')):
        rc = run(str(bin_dir / 'graphtraj'), 'task', 'register', '--task-file', str(register)).returncode
    (work / 'evidence.md').write_text('455 probe: ready for one member with one configured agents-tool child.\n')
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


def member_sessions(project: Path) -> list[Path]:
    """Active member records, then those retirement moved into the Task Traces."""
    return (sorted(project.glob('.graphtraj/runner/sessions/1-*team_leader*'))
            + sorted(project.glob('.graphtraj/state/tasks/1-*/teams/*/traces/1-*team_leader*/runner')))


def alias_of(directory: Path) -> str:
    return directory.parent.name if directory.name == 'runner' else directory.name


def member_mapping(project: Path, alias: str) -> tuple[dict, Path | None]:
    """The member's mapping: mapping.yml, else a retired record's session.yml retirement.mapping."""
    for directory in member_sessions(project):
        if alias_of(directory) != alias:
            continue
        if (directory / 'mapping.yml').is_file():
            return yaml.safe_load((directory / 'mapping.yml').read_text()) or {}, directory
        if (directory / 'session.yml').is_file():
            record = yaml.safe_load((directory / 'session.yml').read_text()) or {}
            return ((record.get('retirement') or {}).get('mapping') or {}), directory
    return {}, None


def final_report(project: Path) -> tuple[str | None, str | None]:
    """Return (alias, last_agent_message) of the member whose last execution ended with the report."""
    for directory in member_sessions(project):
        execution = directory / 'execution.yml'
        if execution.is_file():
            message = (yaml.safe_load(execution.read_text()) or {}).get('last_agent_message') or ''
            if END in message:
                return alias_of(directory), message
    return None, None


def wait(project: Path, seconds: str) -> int:
    deadline = time.time() + min(float(seconds), 115)
    while True:
        alias, message = final_report(project)
        if message:
            print(f'{now()} MEMBER-DONE {alias}')
            return 0
        if time.time() >= deadline:
            ends = [(alias_of(d), (yaml.safe_load((d / 'execution.yml').read_text()) or {}).get('outcome'))
                    for d in member_sessions(project) if (d / 'execution.yml').is_file()]
            print(f'{now()} member not done yet; member sessions: {[str(d.relative_to(project)) for d in member_sessions(project)]} ends: {ends}')
            return 0
        time.sleep(3)


def stream_result(stream: Path) -> dict | None:
    for line in stream.read_text().splitlines() if stream.is_file() else ():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get('type') == 'result':
            return record
    return None


def labelled(report: str, label: str) -> dict | None:
    """The JSON object after ``label`` in the member's report; its ``result`` if it is a tool envelope."""
    decoder = json.JSONDecoder()
    at = report.find(label)
    if at < 0:
        return None
    start = report.find('{', at)
    try:
        value, _ = decoder.raw_decode(report[start:])
    except ValueError:
        return None
    return value.get('result', value) if isinstance(value, dict) and isinstance(value.get('result'), dict) else value


def check(label: str, ok: bool, detail: str = '') -> bool:
    print(f'CHECK {"PASS" if ok else "FAIL"}: {label}' + (f' | {detail}' if detail else ''))
    return ok


def native_settings(session: Path) -> tuple[set, set]:
    """Models the API requests named and the efforts the Session recorded."""
    models, efforts = set(), set()

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'model' and isinstance(item, str):
                    models.add(item)
                elif key in ('effort', 'perTurnEffort') and isinstance(item, str):
                    efforts.add(item)
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    for line in session.read_text(errors='replace').splitlines():
        try:
            walk(json.loads(line))
        except ValueError:
            continue
    return models, efforts


def criteria(report: str, record: dict | None, session: Path | None, model: str, effort: str) -> int:
    want = {'configuration': 'advisor', 'model': model, 'reasoning_effort': effort}
    results = []
    for label in ('CREATE-RESULT', 'STATUS-RESULT', 'RETIRE-RESULT'):
        document = labelled(report, label)
        got = {key: (document or {}).get(key) for key in want} if isinstance(document, dict) else None
        results.append(check(f'{label} shows configuration=advisor, model={model}, reasoning_effort={effort}',
                             got == want, f'got {got}'))
    selection = (record or {}).get('selection') or {}
    got = {key: selection.get(key) for key in want}
    results.append(check('child record selection shows the same', got == want, f'got {got}'))
    results.append(check('child record keeps no applied in settings', record is not None
                         and 'applied' not in (record.get('settings') or {})))
    if session is None or not session.is_file():
        results.append(check('child native Session found', False, f'{session}'))
    else:
        models, efforts = native_settings(session)
        results.append(check(f'child native Session model is {model}', models == {model}, f'models {sorted(models)}'))
        results.append(check(f'child native Session effort is {effort}', efforts == {effort}, f'efforts {sorted(efforts)}'))
    print('summary:', 'ALL PASS' if all(results) else f'{results.count(False)} FAIL')
    return 0 if all(results) else 1


def child_record(project: Path, agent: str) -> tuple[dict | None, Path | None]:
    for path in (project / '.graphtraj').rglob(f'{agent}.json'):
        try:
            return json.loads(path.read_text()), path
        except ValueError:
            continue
    return None, None


def observe(project: Path, stream_path: str) -> int:
    stream = Path(stream_path)
    pid_file = stream.with_suffix('.pid')
    deadline = time.time() + 540
    while pid_file.is_file() and time.time() < deadline:
        try:
            os.kill(int(pid_file.read_text().strip()), 0)
        except (ProcessLookupError, ValueError):
            break
        time.sleep(5)
    else:
        if pid_file.is_file() and time.time() >= deadline:
            print(f'{now()} Main claude -p still running after 9 min; checking what exists now (rerun 02 later).')
    result = stream_result(stream)
    print('== Main final result:', (result or {}).get('result', '(none yet)')[-600:] if result else '(none yet)')
    alias, report = final_report(project)
    print('== member report (alias', alias, '):')
    print(report or '(no report with ' + END + ')')
    created = labelled(report or '', 'CREATE-RESULT') or {}
    agent = created.get('agent') if isinstance(created, dict) else None
    record, path = child_record(project, agent) if isinstance(agent, str) else (None, None)
    print('== child agent', agent, '| record', path)
    session = None
    if record and record.get('session'):
        found = sorted(Path.home().glob(f'.claude/projects/*/{record["session"]}.jsonl'))
        session = found[0] if found else None
    print('== child native Session', session)
    roles = yaml.safe_load((project / '.graphtraj/roles.yml').read_text())['roles']
    return criteria(report or '', record, session, roles['advisor']['model'], roles['advisor']['reasoning_effort'])


if __name__ == '__main__':
    command, *rest = sys.argv[1:]
    if command == 'prepare':
        sys.exit(prepare(Path(rest[0]), rest[1]))
    if command == 'plugins':
        sys.exit(plugins(Path(rest[0]), rest[1]))
    if command == 'wait':
        sys.exit(wait(Path(rest[0]), rest[1]))
    if command == 'observe':
        sys.exit(observe(Path(rest[0]), rest[1]))
    if command == 'check':
        report, record, session = (Path(value) for value in rest[:3])
        sys.exit(criteria(report.read_text(), json.loads(record.read_text()), session,
                          rest[3] if len(rest) > 3 else 'claude-opus-5-5', rest[4] if len(rest) > 4 else ADVISOR_EFFORT))
    sys.exit(f'unknown command {command!r}')
