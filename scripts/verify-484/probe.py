"""484 probe helper (trimmed from verify-483): 401 for an interactive Codex Main on the shared background server.

Run with the isolated candidate venv's Python (-I). Reads only the isolated project, a Codex rollout (read only),
the Codex shared background server through `codex app-server proxy` (one read-only `thread/loaded/list`) and
(step F) the Harness continuity record.

  probe.py prepare PROJECT              roles.yml (advisor: Claude) and role_tree, a fresh Task 1 ready
  probe.py claims PROJECT               continuity claims
  probe.py agent PROJECT NAME           NAME's control record: each execution's notification and notification_error
  probe.py daemon CODEX_HOME [THREAD]   one read-only thread/loaded/list through `codex app-server proxy`; with
                                        THREAD, whether that thread is loaded in the shared background server
  probe.py rollout PROJECT NAME THREAD CODEX_HOME   401: deliveries of NAME's end in THREAD's rollout, by identity
  probe.py main ROOT RUNTIME SESSION    F: the current Main claim (last continuity record) is unchanged
Exit 0 means every printed criterion passed.
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

TASK_ID      = '1'
NAME         = 'codex-main-end-probe'
CLAUDE_MODEL = 'claude-opus-5-5'
BODY = '''---
difficulty: low
difficulty_reason: Scratch probe for 484
execution_budget:
  estimated_minutes:
    total: 60
  planned_sessions:
    advisor: 2
  correction_rounds: 0
  estimation_note: Probe for the 484 interactive Codex Main end delivery
  on_exceed: Report only
---
Follow the instruction exactly.
'''


def say(*parts: object) -> None:
    """Print one line at once."""
    print(' '.join(str(p) for p in parts), flush=True)


def verdict(name: str, ok: bool, observable: str) -> bool:
    """Print one PASS/FAIL line and return ``ok``."""
    say(f"{'PASS' if ok else 'FAIL'} {name}: {observable}")
    return ok


def run(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run one command (limit 300 s), printing its tail on failure."""
    done = subprocess.run(argv, capture_output=True, text=True, timeout=300, cwd=cwd)
    say(f'$ {" ".join(argv[-3:])} -> rc={done.returncode}')
    if done.returncode:
        say(done.stdout[-600:], done.stderr[-600:])
    return done


def prepare(project: Path) -> int:
    """Write roles and register a ready Task 1; exit 2 register, 3 roles, 4 not ready."""
    graphtraj = str(Path(sys.executable).parent / 'graphtraj')
    roles = {'advisor': {'runtime': 'claude', 'model': CLAUDE_MODEL, 'worktree_access': 'read',
                         'claude': {'permission_mode': 'auto'}}}
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({'roles': roles, 'role_tree': {'advisor': {}}}))
    work = project / '.graphtraj/probe-484'
    work.mkdir(exist_ok=True)
    register = work / 'register.yml'
    register.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'task_name': NAME, 'source': 'local:scratch/484', 'title': NAME, 'body': BODY,
        'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
        'replaced_by': [], 'retirement_reason': None}))
    state = work / 'state.yml'
    state.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
        'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-484/evidence.md']}))
    (work / 'evidence.md').write_text('484 probe: ready.\n')

    def task1() -> dict | None:
        graph = run(graphtraj, 'task', 'graph', cwd=project)
        tasks = (yaml.safe_load(graph.stdout) or {}).get('tasks', []) if graph.returncode == 0 else []
        return next((t for t in tasks if t.get('task_id') == TASK_ID), None)

    rc = 0
    if task1() is None:
        rc = 2 if run(graphtraj, 'task', 'register', '--task-file', str(register), cwd=project).returncode else 0
    current = task1()
    if current is not None and current.get('status') != 'ready':
        rc = rc or (2 if run(graphtraj, 'task', 'update', '--state-file', str(state), cwd=project).returncode else 0)
    doctor   = run(graphtraj, 'doctor', cwd=project)
    roles_ok = doctor.returncode == 0 and 'roles: OK' in doctor.stdout
    say('roles OK' if roles_ok else 'roles NOT OK (doctor): ' + (doctor.stdout + doctor.stderr)[-600:])
    current = task1()
    ready   = current is not None and current.get('status') == 'ready'
    say('task 1 ready' if ready else f'task 1 NOT ready: {current}')
    return rc or (0 if roles_ok else 3) or (0 if ready else 4)


def claims(project: Path) -> list[dict]:
    """Every continuity claim of PROJECT, oldest first."""
    path = project / '.graphtraj/runner/main-sessions/continuity.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.is_file() else []


def claims_only(project: Path) -> int:
    """Print every claim and the current Main."""
    found = claims(project)
    for c in found:
        say('claim:', c.get('runtime'), c.get('session'), 'entry', c.get('entry'), 'at', c.get('at'),
            'codex_home', (c.get('connection') or {}).get('codex_home'))
    last = found[-1] if found else {}
    say('continuity claims in', project, ':', len(found), '| current Main:', last.get('runtime'), last.get('session'))
    return 0


def agent_records(project: Path, name: str) -> list[tuple[Path, dict]]:
    """Control records whose file stem or name is NAME."""
    found = []
    for f in sorted((project / '.graphtraj/swarm/control/agents').glob('*.json')):
        try:
            record = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and (f.stem == name or record.get('name') == name):
            found.append((f, record))
    return found


def agent(project: Path, name: str) -> int:
    """Print NAME's executions: outcome, notification and the retained push failure (484)."""
    found = agent_records(project, name)
    if not found:
        say('AGENT', name, 'NONE: no control record under .graphtraj/swarm/control/agents')
        return 1
    for f, record in found:
        say('AGENT', name, 'id', f.stem, '| parent', record.get('parent'), '| creator', json.dumps(record.get('creator')))
        for e in record.get('executions') or []:
            say('  EXECUTION', e.get('id'), '| state', e.get('state'), '| outcome', e.get('outcome'),
                '| last_message', json.dumps(e.get('last_message'))[:120])
            say('  NOTIFICATION', e.get('id'), e.get('notification'),
                '| notification_error', json.dumps(e.get('notification_error')))
    return 0


def daemon(codex_home: str, thread: str | None) -> int:
    """One read-only ``thread/loaded/list`` through ``codex app-server proxy`` (send_event's own channel)."""
    from graphtraj.runtimes.codex.app_server import CodexAppServer

    async def loaded() -> dict:
        async with CodexAppServer(cwd=Path.cwd(), command=('codex', 'app-server', 'proxy'),
                                  environment={'CODEX_HOME': codex_home}, experimental_api=True) as client:
            return await client.call('thread/loaded/list', {})

    try:
        result = asyncio.run(asyncio.wait_for(loaded(), 60))
    except Exception as error:  # the probe prints any failure as evidence
        say('app-server proxy thread/loaded/list: NO |', type(error).__name__, str(error)[:600])
        return 1
    text = json.dumps(result)
    say('app-server proxy thread/loaded/list: YES | CODEX_HOME', codex_home, '| result', text[:600])
    if thread:
        return 0 if verdict('Main thread loaded in the shared background server', thread in text,
                            f'{thread} {"is" if thread in text else "is NOT"} in thread/loaded/list') else 1
    return 0


def jsonl(path: Path) -> list[tuple[int, object]]:
    """Parsed records of a JSONL file with their line numbers."""
    out = []
    for number, line in enumerate(path.read_text(errors='replace').splitlines(), 1):
        try:
            out.append((number, json.loads(line)))
        except ValueError:
            pass
    return out


def rollout(project: Path, name: str, thread: str, codex_home: str) -> int:
    """401: NAME's end in THREAD's rollout, counted by identity (agent id + execution id + outcome).

    Only model-input records (``response_item`` not written by the model) carrying the pushed event's
    ``"source": "graphtraj"`` count; tool results are pulls. PASS needs exactly one such record and the
    control record's notification ``delivered``.
    """
    found = agent_records(project, name)
    if not found:
        say('401 interactive: no control record for', name)
        return 1
    stem, record = found[-1][0].stem, found[-1][1]
    ends  = [(e.get('id'), e.get('outcome'), e.get('notification')) for e in record.get('executions') or []]
    say('agent', name, '=', stem, '| executions (id, outcome, notification):', ends)
    files = sorted((Path(codex_home) / 'sessions').rglob(f'rollout-*{thread}*.jsonl'))
    say('rollout files for thread', thread, ':', [str(f) for f in files] or 'NONE')
    inputs, others, pulls = [], [], []
    for f in files:
        for number, rec in jsonl(f):
            payload = rec.get('payload') if isinstance(rec, dict) else None
            if not isinstance(payload, dict):
                continue
            kind = f"{rec.get('type')}/{payload.get('type')}/{payload.get('role', '')}"
            if (payload.get('type') in {'reasoning', 'function_call', 'custom_tool_call', 'agent_message',
                                        'agent_reasoning', 'mcp_tool_call'} or payload.get('role') == 'assistant'):
                continue
            text = json.dumps(rec, ensure_ascii=False)
            for execution, outcome, _ in ends:
                if stem in text and execution and execution in text and outcome and outcome in text:
                    where = f'{f.name}:{number} {kind}'
                    say('  raw', where, text[:300])
                    # The pushed host event carries its own field "source": "graphtraj"
                    # (send_event); an agents tool result (status/wait/create) does not.
                    if not re.search(r'source\W+graphtraj', text):
                        pulls.append(where)
                    elif rec.get('type') == 'response_item':
                        inputs.append(where)
                    else:
                        others.append(where)
    say('model-input records carrying the end (counted):', inputs or 'none')
    say('host echo records (not counted):', others or 'none')
    say('tool-result records (pulls, not counted):', pulls or 'none')
    delivered = any(n == 'delivered' for _, _, n in ends)
    ok = verdict('401 interactive delivered once', len(inputs) == 1 and delivered,
                 f'{len(inputs)} model-input records carrying {stem} end; control notification '
                 f'{[n for _, _, n in ends]}')
    return 0 if ok else 1


def main_unchanged(root: Path, rt: str, sess: str) -> int:
    """F: the last continuity claim is the one recorded at 00."""
    found = claims(root)
    last  = found[-1] if found else {}
    ok    = bool(last) and last.get('runtime') == rt and last.get('session') == sess
    verdict('F production Main', ok, f"last continuity claim {last.get('runtime')}:{last.get('session')} "
                                     f'== recorded at 00 {rt}:{sess}')
    return 0 if ok else 1


def main() -> int:
    """Dispatch one probe command."""
    cmd, *args = sys.argv[1:]
    if cmd == 'prepare':
        return prepare(Path(args[0]))
    if cmd == 'claims':
        return claims_only(Path(args[0]))
    if cmd == 'agent':
        return agent(Path(args[0]), args[1])
    if cmd == 'daemon':
        return daemon(args[0], args[1] if len(args) > 1 else None)
    if cmd == 'rollout':
        return rollout(Path(args[0]), args[1], args[2], args[3])
    if cmd == 'main':
        return main_unchanged(Path(args[0]), args[1], args[2])
    say('unknown command', cmd)
    return 2


if __name__ == '__main__':
    sys.exit(main())
