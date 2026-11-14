"""444 probe helper: isolated project roles/Task, record reads and PASS/FAIL judgements.

Run with the production Python (.venv-runtime/bin/python -I). Reads only the isolated project, the step
outputs in OUT and (step F) the Harness continuity record. Prints no key or account value: any text it prints
passes through redact(), which removes the DEEPSEEK_API_KEY value when that variable is set.

  probe.py prepare PROJECT              roles.yml (asker: Claude permission_mode default; advisor; pi_member;
                                        codex_root gpt-6-luna), role_tree, Task 1 ready
  probe.py pisandbox -                  Pi sandbox paths exist and srt is on sandbox_path (prints what is missing)
  probe.py inbox PROJECT                continuity claims and every Main notice queue (ids, cursor, duplicates)
  probe.py queued PROJECT RUNTIME ALIAS SECONDS
                                        poll until the current RUNTIME Main's queue holds an undelivered end
                                        notice of ALIAS; prints QUEUED <id> or NOT-QUEUED
  probe.py count FILE TOKEN...          occurrences of each TOKEN in FILE (a Main stream or rollout)
  probe.py requests PROJECT OUT LABEL   373: native requests of the asker member dispatched in step LABEL
  probe.py session PROJECT ALIASPART    the newest member session directory whose name contains ALIASPART
  probe.py main PROJECT_OR_HARNESS EXPECT_RUNTIME EXPECT_SESSION
                                        F: the current Main claim (last continuity record) is unchanged
Exit 0 means every printed criterion passed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

TASK_ID = '1'
NAME = 'main-swap-probe'
CLAUDE_MODEL = 'claude-opus-5-5'
CODEX_MODEL = 'gpt-6-luna'
PI = {  # production roles.yml pi_dsh_trial.team_leader (Task 444 definition and dispatch)
    'sandbox_python': '/Users/luoxiao/agents-pi-sandbox/venv/bin/python',
    'sandbox_path': '/Users/luoxiao/agents-pi-sandbox/srt/node_modules/.bin:/opt/homebrew/bin:'
                    '/Users/luoxiao/agents-pi-sandbox/bin:/usr/bin:/bin:/usr/sbin:/sbin',
    'agent_dir': '/Users/luoxiao/.pi/agent',
}
BODY = '''---
difficulty: low
difficulty_reason: Scratch probe for 444
execution_budget:
  estimated_minutes:
    total: 60
  planned_sessions:
    team_leader: 1
  correction_rounds: 0
  estimation_note: Probe members of the 444 Main-swap checks
  on_exceed: Report only
---
Follow the dispatch instruction exactly.
'''


def redact(text: str) -> str:
    key = os.environ.get('DEEPSEEK_API_KEY')
    return text.replace(key, '[redacted]') if key else text


def say(*parts: object) -> None:
    print(redact(' '.join(str(p) for p in parts)), flush=True)


def verdict(name: str, ok: bool, observable: str) -> bool:
    say(f"{'PASS' if ok else 'FAIL'} {name}: {observable}")
    return ok


def run(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    done = subprocess.run(argv, capture_output=True, text=True, timeout=300, cwd=cwd)
    say(f'$ {" ".join(argv[-3:])} -> rc={done.returncode}')
    if done.returncode:
        say(done.stdout[-600:], done.stderr[-600:])
    return done


# -- preparation ---------------------------------------------------------------

def prepare(project: Path) -> int:
    graphtraj = str(Path(sys.executable).parent / 'graphtraj')
    roles = {
        # The 373 trigger: Claude with manual tool approval, so each shell call raises a native request
        # (393 risk: permission_mode auto may decide without asking).
        'asker': {'runtime': 'claude', 'model': CLAUDE_MODEL, 'worktree_access': 'read',
                  'claude': {'permission_mode': 'default'}},
        'advisor': {'runtime': 'claude', 'model': CLAUDE_MODEL, 'worktree_access': 'read',
                    'claude': {'permission_mode': 'auto'}},
        'pi_member': {'runtime': 'pi', 'connection': 'pi/deepseek/deepseek-flash', 'worktree_access': 'read',
                      'pi': dict(PI)},
        'codex_root': {'runtime': 'codex', 'model': CODEX_MODEL},
    }
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': roles, 'role_tree': {'asker': {}, 'advisor': {}, 'pi_member': {}, 'codex_root': {}}}))
    work = project / '.graphtraj/probe-444'
    work.mkdir(exist_ok=True)
    register = work / 'register.yml'
    register.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'task_name': NAME, 'source': 'local:scratch/444', 'title': NAME, 'body': BODY,
        'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
        'replaced_by': [], 'retirement_reason': None}))
    state = work / 'state.yml'
    state.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
        'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-444/evidence.md']}))
    (work / 'evidence.md').write_text('444 probe: ready.\n')
    rc = 0
    if not list(project.glob('.graphtraj/state/tasks/1-*/task.yml')):
        rc = run(graphtraj, 'task', 'register', '--task-file', str(register), cwd=project).returncode
    for argv in (('task', 'update', '--state-file', str(state)), ('doctor',)):
        done = run(graphtraj, *argv, cwd=project)
        rc = rc or done.returncode
        if argv == ('doctor',):
            say('roles OK' if 'roles: OK' in done.stdout else 'roles NOT OK: ' + done.stdout[-600:])
            rc = rc or ('roles: OK' not in done.stdout)
    graph = run(graphtraj, 'task', 'graph', cwd=project)
    tasks = (yaml.safe_load(graph.stdout) or {}).get('tasks', [])
    ready = any(t['task_id'] == TASK_ID and t['status'] == 'ready' for t in tasks)
    say('task 1 ready' if ready else 'task 1 NOT ready: ' + graph.stdout[-400:])
    return rc or (not ready)


def pisandbox(_unused: str) -> int:
    missing = [f'{k}={PI[k]}' for k in ('sandbox_python', 'agent_dir') if not Path(PI[k]).exists()]
    parts = PI['sandbox_path'].split(':')
    missing += [f'sandbox_path entry {p}' for p in parts if not Path(p).is_dir()]
    srt = next((str(Path(p) / 'srt') for p in parts if os.access(Path(p) / 'srt', os.X_OK)), None)
    rg = next((str(Path(p) / 'rg') for p in parts if os.access(Path(p) / 'rg', os.X_OK)), None)
    if srt is None:
        missing.append("srt on sandbox_path (pi_adapter: 'Pi requires srt on pi.sandbox_path; no fallback.')")
    say('pi sandbox: srt at', srt, '| rg at', rg)
    say('pi sandbox missing:', missing or 'nothing')
    return 1 if missing else 0


# -- records -------------------------------------------------------------------

def runner(project: Path) -> Path:
    return project / '.graphtraj/runner'


def claims(project: Path) -> list[dict]:
    path = runner(project) / 'main-sessions/continuity.jsonl'
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def inbox_path(project: Path, rt: str, session: str) -> Path:
    key = hashlib.sha256((rt + ':' + session).encode()).hexdigest()
    return runner(project) / 'main-sessions/inbox' / (key + '.jsonl')


def queue(path: Path) -> tuple[list[dict], int]:
    lines = [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.is_file() else []
    cursor = path.with_suffix('.cursor')
    return lines, (int(cursor.read_text()) if cursor.is_file() else 0)


def current(project: Path, rt: str | None = None) -> dict | None:
    found = [c for c in claims(project) if rt is None or c.get('runtime') == rt]
    return found[-1] if found else None


def inbox(project: Path) -> int:
    known = {}
    for c in claims(project):
        known[inbox_path(project, c['runtime'], c['session']).name] = f"{c['runtime']}:{c['session']}"
        say('claim:', c.get('runtime'), c.get('session'), 'entry', c.get('entry'), 'at', c.get('at'))
    say('current Main:', (current(project) or {}).get('runtime'), (current(project) or {}).get('session'))
    bad = 0
    for path in sorted((runner(project) / 'main-sessions/inbox').glob('*.jsonl')):
        lines, cursor = queue(path)
        ids = [n['id'] for n in lines]
        dup = len(ids) - len(set(ids))
        bad += dup
        say(f'queue {known.get(path.name, path.name)}: records {len(lines)} cursor {cursor} duplicate ids {dup}')
        for i, n in enumerate(lines):
            e = n['event']
            say(f"  [{i}] {'delivered' if i < cursor else 'PENDING'} id={n['id'][:16]} alias={e.get('alias')} "
                f"event={e.get('event')} execution={e.get('execution')} request={e.get('request_id')}")
    return 1 if bad else 0


def queued(project: Path, rt: str, alias: str, seconds: str) -> int:
    deadline = time.time() + float(seconds)
    while True:
        main = current(project, rt)
        if main:
            lines, cursor = queue(inbox_path(project, rt, main['session']))
            hits = [n for n in lines[cursor:] if alias in str(n['event'].get('alias', ''))
                    and n['event'].get('event') in {'completed', 'failed', 'interrupted'}]
            if hits:
                say('QUEUED', hits[0]['id'], 'for', rt, main['session'], 'event', hits[0]['event'].get('event'))
                return 0
        if time.time() >= deadline:
            say('NOT-QUEUED: no undelivered end notice of', alias, 'for the current', rt, 'Main',
                (main or {}).get('session'))
            return 1
        time.sleep(5)


def count(path: Path, *tokens: str) -> int:
    text = path.read_text(errors='replace') if path.is_file() else ''
    for t in tokens:
        say(f'count {t!r} in {path.name}: {text.count(t)}')
    return 0


def session(project: Path, part: str) -> int:
    found = sorted((runner(project) / 'sessions').glob(f'1-*{part}*'), key=lambda d: d.stat().st_mtime)
    say(found[-1] if found else 'NONE')
    return 0 if found else 1


def requests(project: Path, out: Path, label: str) -> int:
    """373: the asker of step LABEL raised >= 2 native requests and every one reached the Main.

    Observables: (1) request ids in the Main's notice queue for the asker's execution (pull-only Mains), or
    in the Main's own output stream (Codex host events; any Main's tool results); (2) the asker's native
    archive shows >= 2 permission outcomes for its two shell calls; (3) the Main stream shows a reply per id.
    """
    stream = out / f'{label}-main-stream.jsonl'
    text = stream.read_text(errors='replace') if stream.is_file() else ''
    aliases = sorted(set(re.findall(r'(1-[A-Za-z0-9_\-]*asker[A-Za-z0-9_\-]*@asker[_0-9]*)', text)))
    say('asker aliases in', stream.name, ':', aliases or 'none')
    ids: set[str] = set()
    for path in (runner(project) / 'main-sessions/inbox').glob('*.jsonl'):
        for n in queue(path)[0]:
            e = n['event']
            if e.get('request_id') and any(a == e.get('alias') for a in aliases):
                ids.add(str(e['request_id']))
    queued_ids = set(ids)
    ids |= set(re.findall(r'request_id\\*"\s*:\s*\\*"([^"\\]+)', text))
    say('request ids queued for a Main:', sorted(queued_ids) or 'none', '| in the Main stream:', sorted(ids - queued_ids) or 'none')
    replies = len(re.findall(r'deny', text, flags=re.I))
    member_text = ''
    for a in aliases:
        for f in (runner(project) / 'sessions' / a).rglob('*'):
            if f.is_file() and f.suffix in {'.jsonl', '.yml', '.json', '.md'}:
                member_text += f.read_text(errors='replace')
    denials = len(re.findall(r'denied|permission', member_text, flags=re.I))
    ok1 = verdict(f'373[{label}] raised', len(ids) >= 2, f'{len(ids)} distinct native request ids for the asker (>= 2)')
    ok2 = verdict(f'373[{label}] answered', replies >= len(ids) and len(ids) >= 2,
                  f"{replies} 'deny' mentions in the Main stream for {len(ids)} requests")
    ok3 = verdict(f'373[{label}] member saw answers', denials >= 2, f'{denials} denial/permission mentions in the asker records')
    return 0 if ok1 and ok2 and ok3 else 1


def main_unchanged(root: Path, rt: str, sess: str) -> int:
    last = current(root)
    ok = bool(last) and last.get('runtime') == rt and last.get('session') == sess
    verdict('F production Main', ok, f"last continuity claim {(last or {}).get('runtime')}:{(last or {}).get('session')} "
                                     f"== recorded at 00 {rt}:{sess}")
    return 0 if ok else 1


def main() -> int:
    cmd, *args = sys.argv[1:]
    if cmd == 'prepare':
        return prepare(Path(args[0]))
    if cmd == 'pisandbox':
        return pisandbox(args[0])
    if cmd == 'inbox':
        return inbox(Path(args[0]))
    if cmd == 'queued':
        return queued(Path(args[0]), args[1], args[2], args[3])
    if cmd == 'count':
        return count(Path(args[0]), *args[1:])
    if cmd == 'session':
        return session(Path(args[0]), args[1])
    if cmd == 'requests':
        return requests(Path(args[0]), Path(args[1]), args[2])
    if cmd == 'main':
        return main_unchanged(Path(args[0]), args[1], args[2])
    say('unknown command', cmd)
    return 2


if __name__ == '__main__':
    sys.exit(main())
