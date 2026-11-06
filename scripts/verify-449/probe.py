"""449 probe helper: roles, the probe Task, and what the swarm result, notices and task_sessions showed.

Usage (the scratch venv's Python):
  python -I probe.py prepare PROJECT MODEL     roles and probe Task 1, ready
  python -I probe.py plugins STREAM -          0 only when graphtraj-claude-host is loaded
  python -I probe.py wait PROJECT SECONDS      poll (<120 s) until the member's final report exists
  python -I probe.py observe PROJECT STREAM    wait (<540 s) for Main to end, then check the three criteria
Prints only facts read from the isolated project and the Main stream; it reads no credential.
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
NAME = 'agent-identity-probe'
END = 'REPORT-449-END'
BODY = '''---
difficulty: low
difficulty_reason: Scratch probe for 449
execution_budget:
  estimated_minutes:
    total: 30
  planned_sessions:
    team_leader: 1
  correction_rounds: 0
  estimation_note: One agents-tool child run twice, then one report
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
                                  'reports': ['report.md']}},
        'role_tree': {'team_leader': {}},
    }))
    work = project / '.graphtraj/probe-449'
    work.mkdir(exist_ok=True)
    register = work / 'register.yml'
    register.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'task_name': NAME, 'source': 'local:scratch/449', 'title': NAME, 'body': BODY,
        'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
        'replaced_by': [], 'retirement_reason': None}))
    state = work / 'state.yml'
    state.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
        'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-449/evidence.md']}))
    rc = 0
    if not list(project.glob('.graphtraj/state/tasks/1-*/task.yml')):
        rc = run(str(bin_dir / 'graphtraj'), 'task', 'register', '--task-file', str(register)).returncode
    (work / 'evidence.md').write_text('449 probe: ready for one member with one agents-tool child.\n')
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
    return sorted(project.glob('.graphtraj/runner/sessions/1-*team_leader*'))


def final_report(project: Path) -> tuple[str | None, str | None]:
    """Return (alias, last_agent_message) of the member whose last execution ended with the report."""
    for directory in member_sessions(project):
        execution = directory / 'execution.yml'
        if execution.is_file():
            message = (yaml.safe_load(execution.read_text()) or {}).get('last_agent_message') or ''
            if END in message:
                return directory.name, message
    return None, None


def wait(project: Path, seconds: str) -> int:
    deadline = time.time() + min(float(seconds), 115)
    while True:
        alias, message = final_report(project)
        if message:
            print(f'{now()} MEMBER-DONE {alias}')
            return 0
        if time.time() >= deadline:
            ends = [(d.name, (yaml.safe_load((d / 'execution.yml').read_text()) or {}).get('outcome'))
                    for d in member_sessions(project) if (d / 'execution.yml').is_file()]
            print(f'{now()} member not done yet; member sessions: {[d.name for d in member_sessions(project)]} ends: {ends}')
            return 0
        time.sleep(3)


def stream_calls(stream: Path) -> list[dict]:
    """Each tool call of the Main stream with its input and the text of its result."""
    calls, by_id = [], {}
    for line in stream.read_text().splitlines() if stream.is_file() else ():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        for block in (record.get('message') or {}).get('content') or []:
            if not isinstance(block, dict):
                continue
            if block.get('type') == 'tool_use':
                call = {'name': block.get('name'), 'input': block.get('input'), 'result': None, 'is_error': None}
                by_id[block.get('id')] = call
                calls.append(call)
            elif block.get('type') == 'tool_result' and block.get('tool_use_id') in by_id:
                content = block.get('content')
                text = content if isinstance(content, str) else '\n'.join(
                    part.get('text', '') for part in content or [] if isinstance(part, dict))
                by_id[block['tool_use_id']].update(result=text, is_error=block.get('is_error'))
    return calls


def loads(text: str | None) -> object:
    try:
        return json.loads(text or '')
    except ValueError:
        return None


def embedded_notices(text: str) -> list[dict]:
    """Every JSON object in ``text`` that starts like a GraphTraj notice."""
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


def recorded_notices(project: Path, child: str) -> dict[str, list[tuple[str, dict]]]:
    """Notices naming ``child`` in any text record under the project's .graphtraj, by file."""
    found: dict[str, list[tuple[str, dict]]] = {}
    for path in (project / '.graphtraj').rglob('*'):
        if not path.is_file() or path.stat().st_size > 50_000_000 or path.suffix not in {'.jsonl', '.json', '.yml', '.yaml', '.txt'}:
            continue
        try:
            text = path.read_text(errors='replace')
        except OSError:
            continue
        if child not in text:
            continue
        values = []
        for line in text.splitlines():
            record = loads(line)
            for value in strings(record) if record is not None else [line]:
                values.extend(embedded_notices(value))
        for notice in values:
            if notice.get('alias') == child:
                found.setdefault(str(path.relative_to(project)), []).append(('', notice))
    return found


def check(label: str, ok: bool, detail: str = '') -> bool:
    print(f'CHECK {"PASS" if ok else "FAIL"}: {label}' + (f' | {detail}' if detail else ''))
    return ok


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
    results = []
    calls = stream_calls(stream)
    swarm = next((call for call in calls if call['name'] == 'mcp__agents__tasks'), None)
    print('== swarm result (raw):', swarm and swarm['result'])
    document = loads(swarm and swarm['result']) or {}
    document = document.get('result', document) if isinstance(document, dict) else {}
    task = (document.get('tasks') or [{}])[0] if isinstance(document, dict) else {}
    agent, alias = task.get('agent'), task.get('alias')
    results.append(check('1 swarm result has agent', isinstance(agent, str) and agent.startswith('agent-'),
                         f'agent={agent} alias={alias} execution_id={task.get("execution_id")} launch_status={task.get("launch_status")}'))
    mapping_file = project / '.graphtraj/runner/sessions' / str(alias) / 'mapping.yml'
    mapping = yaml.safe_load(mapping_file.read_text()) if mapping_file.is_file() else {}
    results.append(check('1 swarm agent equals the member mapping agent', bool(agent) and mapping.get('agent') == agent,
                         f'mapping.agent={mapping.get("agent")}'))
    for feature in ('status', 'retire'):
        call = next((c for c in calls if c['name'] == 'mcp__agents__agents'
                     and (c['input'] or {}).get('feature') == feature
                     and ((c['input'] or {}).get('arguments') or {}).get('agent') == agent), None)
        print(f'== Main agents {feature} by swarm agent (raw):', call and call['result'])
        body = loads(call and call['result'])
        failed = call is None or call['is_error'] or (isinstance(body, dict) and 'error' in body)
        results.append(check(f'3 Main agents {feature} accepts the swarm agent id', bool(agent) and not failed))
    retired = (yaml.safe_load(mapping_file.read_text()) or {}).get('retire_status') if mapping_file.is_file() else None
    print('   member retire_status now:', retired)

    records = [loads(path.read_text()) for path in sorted((project / '.graphtraj/swarm/control/agents').glob('*.json'))]
    children = [r for r in records if isinstance(r, dict) and r.get('parent') in {alias, agent} and alias]
    print('== member children in core records:', [(r['agent'], r.get('name')) for r in children])
    results.append(check('2 the member has exactly one agents-tool child', len(children) == 1))
    child = children[0] if children else {}
    ended = [e for e in child.get('executions', []) if e.get('state') == 'ended']
    for execution in ended:
        print('   child execution', execution.get('id'), 'outcome', execution.get('outcome'),
              'notification', execution.get('notification'), 'last_message', repr(execution.get('last_message')))
    results.append(check('2 the child ran twice (create, then send)', len(ended) >= 2, f'ended={len(ended)}'))
    found = recorded_notices(project, child.get('agent', '?')) if child else {}
    distinct: dict[str, set[str]] = {}
    for path, notices in sorted(found.items()):
        print('   notices in', path, ':', len(notices))
        for _, notice in notices:
            distinct.setdefault(str(notice.get('execution')), set()).add(json.dumps(notice, sort_keys=True, ensure_ascii=False))
    for execution, texts in sorted(distinct.items()):
        for text in sorted(texts):
            print('   NOTICE', text)
    for execution in ended[:2]:
        texts = distinct.get(execution.get('id'), set())
        results.append(check(f'2 one distinct end notice names execution {execution.get("id")}', len(texts) == 1,
                             f'distinct={len(texts)} notification={execution.get("notification")}'))
        results.append(check(f'2 execution {execution.get("id")} delivered once (core notification)',
                             execution.get('notification') == 'delivered'))
    results.append(check('2 no notice of the child lacks execution or names another one',
                         bool(ended) and set(distinct) <= {e.get('id') for e in ended}, f'named={sorted(distinct)}'))

    member, report = final_report(project)
    print('== member final report (raw):')
    print(report)
    reported = embedded_notices(report or '')
    print('   reported inputs:', len(reported), [(n.get('event'), n.get('execution')) for n in reported])
    results.append(check('2 member-reported inputs name the two executions in order', len(ended) >= 2 and
                         [n.get('execution') for n in reported if n.get('alias') == child.get('agent')]
                         == [e.get('id') for e in ended[:2]]))
    block = re.search(r'STATUS-BEGIN\s*(.*?)\s*STATUS-END', report or '', re.S)
    status = loads(block.group(1)) if block else None
    status = status.get('result', status) if isinstance(status, dict) else None
    nodes = (status or {}).get('task_sessions', {}).get('agents', []) if isinstance(status, dict) else []
    node = next((n for n in nodes if n.get('alias') == alias), None)
    print('   member task_sessions node:', node and {k: node.get(k) for k in ('alias', 'parent', 'children')})
    listed = [n.get('agent') for n in (status or {}).get('agents', [])] if isinstance(status, dict) else []
    results.append(check('1 member task_sessions node lists the agents-tool child (member-reported status)',
                         bool(node) and child.get('agent') in (node.get('children') or []),
                         f'agents list={listed}'))
    print('== summary:', 'ALL PASS' if all(results) else f'{results.count(False)} FAIL of {len(results)}')
    return 0 if all(results) else 1


if __name__ == '__main__':
    command, target, extra = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    commands = {'prepare': prepare, 'plugins': plugins, 'wait': wait, 'observe': observe}
    raise SystemExit(commands[command](target, extra))
