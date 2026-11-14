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
  probe.py requests PROJECT OUT LABEL TAG  373 (a)-(d) for the asker dispatched in step LABEL (files 373-TAG-a/-b)
  probe.py ends PROJECT OUT ALIAS STREAM...  401: deliveries of ALIAS's end to the Codex Main
  probe.py delivered PROJECT ALIAS      397: ALIAS's end notice id delivered exactly once (records)
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
        # A connection reference carries the Runtime; it may not be mixed with runtime/model/base_url/api_key_env
        # (project_roles.py _role_preset). Same form as verify-461.
        'pi_member': {'connection': 'pi/deepseek/deepseek-flash', 'worktree_access': 'read',
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
    # Exit codes name what failed: 2 register/update, 3 roles (doctor), 4 Task 1 not ready.
    # A rerun on an existing project registers nothing: Task 1 is looked up in the graph first.
    def task1() -> dict | None:
        graph = run(graphtraj, 'task', 'graph', cwd=project)
        tasks = (yaml.safe_load(graph.stdout) or {}).get('tasks', []) if graph.returncode == 0 else []
        return next((t for t in tasks if t.get('task_id') == TASK_ID), None)
    rc = 0
    if task1() is None:
        rc = 2 if run(graphtraj, 'task', 'register', '--task-file', str(register), cwd=project).returncode else 0
    else:
        say('task 1 already registered: register skipped')
    current = task1()
    if current is not None and current.get('status') != 'ready':
        rc = rc or (2 if run(graphtraj, 'task', 'update', '--state-file', str(state), cwd=project).returncode else 0)
    elif current is not None:
        say('task 1 already ready: update skipped')
    doctor = run(graphtraj, 'doctor', cwd=project)
    roles_ok = doctor.returncode == 0 and 'roles: OK' in doctor.stdout
    say('roles OK' if roles_ok else 'roles NOT OK (doctor): ' + (doctor.stdout + doctor.stderr)[-600:])
    current = task1()
    ready = current is not None and current.get('status') == 'ready'
    say('task 1 ready' if ready else f"task 1 NOT ready: {current}")
    return rc or (0 if roles_ok else 3) or (0 if ready else 4)


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


def keys_for(project: Path, name: str) -> set[str]:
    """An agents-tool Agent is created with a readable ``name``; notices carry its agent id as ``alias``.
    Match the name and every agent id whose control record names it."""
    keys = {name}
    for f in (project / '.graphtraj/swarm/control/agents').glob('*.json'):
        try:
            record = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and any(v == name for v in (record.get('name'), (record.get('request') or {}).get('name'))):
            keys.add(f.stem)
            keys |= {str(record[k]) for k in ('agent', 'id', 'alias') if isinstance(record.get(k), str)}
    return keys


def hit(value: object, keys: set[str]) -> bool:
    return any(k in str(value or '') for k in keys)


def current_is(project: Path, rt: str, session: str) -> int:
    for c in claims(project):
        say('claim:', c.get('runtime'), c.get('session'), 'entry', c.get('entry'), 'at', c.get('at'))
    last = current(project)
    ok = bool(last) and last.get('runtime') == rt and last.get('session') == session
    say('current Main:', (last or {}).get('runtime'), (last or {}).get('session'), '| expected', rt, session,
        '->', 'YES' if ok else 'NO')
    return 0 if ok else 1


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
    keys = keys_for(project, alias)
    say('matching', alias, 'as', sorted(keys))
    while True:
        main = current(project, rt)
        if main:
            lines, cursor = queue(inbox_path(project, rt, main['session']))
            hits = [n for n in lines[cursor:] if hit(n['event'].get('alias'), keys)
                    and n['event'].get('event') in {'completed', 'failed', 'interrupted'}]
            if hits:
                say('QUEUED', hits[0]['id'], 'for', rt, main['session'], 'event', hits[0]['event'].get('event'))
                return 0
        keys = keys_for(project, alias)
        if time.time() >= deadline:
            say('NOT-QUEUED: no undelivered end notice of', alias, 'for the current', rt, 'Main',
                (main or {}).get('session'))
            say('matched as', sorted(keys), '; every queued end notice, raw, for judgement:')
            for path in (runner(project) / 'main-sessions/inbox').glob('*.jsonl'):
                for n in queue(path)[0]:
                    if n['event'].get('event') in END_EVENTS:
                        say('  raw:', json.dumps(n)[:300])
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


END_EVENTS = {'completed', 'failed', 'interrupted'}
SKIP_ITEMS = {'agent_message', 'reasoning', 'user_message', 'todo_list'}


def jsonl(path: Path) -> list[tuple[int, object]]:
    rows = []
    if path.is_file():
        for number, line in enumerate(path.read_text(errors='replace').splitlines(), 1):
            try:
                rows.append((number, json.loads(line)))
            except ValueError:
                continue
    return rows


def walk(value: object):
    yield value
    if isinstance(value, dict):
        for v in value.values():
            yield from walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from walk(v)


def flat(value: object) -> str:
    """One string with JSON string escapes removed at any depth, so nested tool results read like plain JSON."""
    return re.sub(r'\\+"', '"', json.dumps(value, ensure_ascii=False))


def delivery_view(record: object) -> object:
    """A stream record without what the Main or the prompt wrote: model text, reasoning, the user's prompt and
    tool-call arguments are dropped; tool results, host events and injected notices stay."""
    if isinstance(record, dict) and isinstance(record.get('item'), dict):
        item = record['item']
        if item.get('type') in SKIP_ITEMS:
            return None
        return {k: v for k, v in item.items() if k not in {'arguments', 'text', 'command'}}
    if isinstance(record, dict) and record.get('type') in {'assistant', 'user_prompt'}:
        return None
    return record


def raw(label: str, lines: list[str]) -> None:
    for line in lines[:8]:
        say(f'  raw {label}: {line[:400]}')


def asker_aliases(text: str) -> list[str]:
    return sorted(set(re.findall(r'(1-[A-Za-z0-9_\-]*asker[A-Za-z0-9_\-]*@asker[_0-9]*)', text)))


def requests(project: Path, out: Path, label: str, tag: str) -> int:
    """373: the asker of step LABEL raised >= 2 native requests, each reached the Main, the Main's reply to each
    was submitted, the asker's two touch calls were refused, and neither file exists.

    (a) request ids for the asker in any Main notice queue, or in tool results/host events of the Main stream
        (prompt text, model text and tool-call arguments excluded);
    (b) per id, a Main-stream tool result naming that id with reply_status submitted (reply's result shape:
        graftling/*/execution.py ``{'request_id': ..., 'reply_status': 'submitted'}``);
    (c) the asker's native records: each Bash tool_use naming 373-TAG-a/-b has an error/denied tool_result;
    (d) BASE/373-TAG-a and -b are absent (BASE is the isolated project's parent).
    """
    stream = out / f'{label}-main-stream.jsonl'
    rows = jsonl(stream)
    aliases = asker_aliases(stream.read_text(errors='replace') if stream.is_file() else '')
    say('asker aliases in', stream.name, ':', aliases or 'none')
    queued: set[str] = set()
    for path in (runner(project) / 'main-sessions/inbox').glob('*.jsonl'):
        for n in queue(path)[0]:
            e = n['event']
            if e.get('request_id') and e.get('alias') in aliases:
                queued.add(str(e['request_id']))
    seen: set[str] = set()
    submitted: set[str] = set()
    for _, record in rows:
        view = delivery_view(record)
        if view is None:
            continue
        text = flat(view)
        seen |= set(re.findall(r'"request_id"\s*:\s*"([^"]+)"', text))
        for m in re.finditer(r'\{[^{}]*"reply_status"\s*:\s*"submitted"[^{}]*\}', text):
            submitted |= set(re.findall(r'"request_id"\s*:\s*"([^"]+)"', m.group(0)))
    ids = queued | seen
    say('request ids queued for a Main:', sorted(queued) or 'none', '| seen in Main-stream tool results/events:', sorted(seen) or 'none')
    say('reply results with reply_status submitted, by request id:', sorted(submitted) or 'none')
    missing = sorted(ids - submitted)
    say('request ids without a submitted reply result:', missing or 'none')
    if not rows and stream.is_file():
        say(stream.name, 'is not a JSON stream; (b) cannot be read from records. Raw lines naming a request id:')
        raw(stream.name, [x for x in stream.read_text(errors='replace').splitlines()
                          if any(i in x for i in queued) or 'request' in x.lower()])
    elif not ids:
        raw(stream.name, [flat(r) for _, r in rows if 'request' in flat(r)])
    ok_a = verdict(f'373[{label}] (a) raised and reached Main', len(ids) >= 2, f'{len(ids)} distinct request ids for the asker (>= 2)')
    ok_b = verdict(f'373[{label}] (b) replies submitted', bool(ids) and not missing,
                   f'{len(ids) - len(missing)}/{len(ids)} ids have a reply result with reply_status submitted')
    # (c) the asker's native records
    targets = {f'373-{tag}-a': None, f'373-{tag}-b': None}
    uses: dict[str, str] = {}
    results: dict[str, str] = {}
    lines: list[str] = []
    for alias in aliases:
        for f in sorted((runner(project) / 'sessions' / alias).rglob('*.jsonl')):
            for _, record in jsonl(f):
                for node in walk(record):
                    if not isinstance(node, dict):
                        continue
                    if node.get('type') == 'tool_use' and isinstance(node.get('input'), dict):
                        command = str(node['input'].get('command', ''))
                        for t in targets:
                            if t in command:
                                uses[node.get('id')] = t
                    if node.get('type') == 'tool_result':
                        content = flat(node.get('content'))
                        results[node.get('tool_use_id')] = ('error' if node.get('is_error') else 'ok') + ': ' + content[:160]
                text = flat(record)
                if f'373-{tag}' in text:
                    lines.append(f'{f.name}: {text}')
    refused = {}
    for use, t in uses.items():
        result = results.get(use, 'no tool_result')
        say(f'asker tool_use {use} for {t}: {redact(result)}')
        refused[t] = refused.get(t) or (result.startswith('error') and bool(re.search(r'den(y|ied)|reject|not allowed|permission', result, re.I)))
    if len(uses) == 0:
        say('asker record shape unknown (no tool_use naming the files); raw lines for judgement:')
        raw('asker', lines)
    ok_c = verdict(f'373[{label}] (c) asker refused', all(refused.get(t) for t in targets),
                   f'denied/rejected tool_result per touch call: {[(t, bool(refused.get(t))) for t in targets]}')
    base = project.parent
    states = {t: ('exists' if (base / t).exists() else 'absent') for t in targets}
    ok_d = verdict(f'373[{label}] (d) files absent', all(v == 'absent' for v in states.values()),
                   ' '.join(f'{base / t}: {v}' for t, v in states.items()))
    return 0 if ok_a and ok_b and ok_c and ok_d else 1


def ends(project: Path, out: Path, alias: str, *streams: str) -> int:
    """401: deliveries of ALIAS's end to the Codex Main, by event identity.

    Stream channel: tool results, host events and injected notices in the given Main streams (model text,
    reasoning, the prompt and tool-call arguments excluded) that carry ALIAS with an end event: either a host-event
    object {alias, event[, execution]} or the rendered header '[GraphTraj notice from ALIAS · EVENT'.
    Record channel: Codex Main notice-queue entries for ALIAS's end, before the cursor (delivered).
    """
    occurrences: list[tuple[str, str]] = []
    keys = keys_for(project, alias)
    say('matching', alias, 'as', sorted(keys))
    for name in streams:
        for number, record in jsonl(out / name):
            view = delivery_view(record)
            if view is None:
                continue
            text = flat(view)
            for node in walk(view):
                if (isinstance(node, dict) and hit(node.get('alias'), keys) and node.get('event') in END_EVENTS):
                    occurrences.append((f"{node.get('alias')}|{node.get('event')}|{node.get('execution')}", f'{name}:{number} host-event'))
            for m in re.finditer(r'\[GraphTraj notice from ([^ \]]*) · (\w+)(?: · execution ([^\s\]\\]+))?', text):
                if m.group(2) in END_EVENTS and hit(m.group(1), keys):
                    occurrences.append((f'{m.group(1)}|{m.group(2)}|{m.group(3)}', f'{name}:{number} notice-text'))
    occurrences = sorted(set(occurrences), key=lambda x: x[1])
    recorded: list[tuple[str, str]] = []
    for c in claims(project):
        if c.get('runtime') != 'codex':
            continue
        lines, cursor = queue(inbox_path(project, 'codex', c['session']))
        for i, n in enumerate(lines):
            e = n['event']
            if hit(e.get('alias'), keys) and e.get('event') in END_EVENTS:
                recorded.append((n['id'], f"codex queue {c['session']} [{i}] {'delivered' if i < cursor else 'PENDING'}"))
    for key, where in occurrences:
        say(f'401 stream delivery: {key} at {where}')
    for key, where in recorded:
        say(f'401 record: id {key[:16]} {where}')
    stream_count = len(occurrences)
    record_count = len([r for r in recorded if 'delivered' in r[1]])
    total = stream_count if stream_count else record_count
    if not occurrences and not recorded:
        lines = []
        for name in streams:
            lines += [f'{name}:{n} {flat(r)}' for n, r in jsonl(out / name) if hit(flat(r), keys)]
        say('no delivery shape recognised; raw lines naming', alias, 'for judgement:')
        raw('401', lines)
    ok = verdict('401 delivered once', total == 1,
                 f'{stream_count} stream deliveries (tool results/host events/notices), {record_count} delivered '
                 f'Codex-queue entries; judged on {"stream" if stream_count else "records"}: {total} (== 1)')
    return 0 if ok else 1


def delivered(project: Path, alias: str) -> int:
    """397: ALIAS's end notice id is delivered exactly once: one entry per queue, never PENDING, no duplicates,
    and the last queue holding it (the continuing Main's) has its cursor past it."""
    found: dict[str, list[str]] = {}
    keys = keys_for(project, alias)
    say('matching', alias, 'as', sorted(keys))
    for c in claims(project):
        path = inbox_path(project, c['runtime'], c['session'])
        lines, cursor = queue(path)
        for i, n in enumerate(lines):
            if hit(n['event'].get('alias'), keys) and n['event'].get('event') in END_EVENTS:
                place = f"{c['runtime']}:{c['session']}[{i}] {'delivered' if i < cursor else 'PENDING'}"
                if place not in found.setdefault(n['id'], []):
                    found[n['id']].append(place)
    for key, places in found.items():
        say(f'397 record: id {key[:16]} in {places}')
    queues = [p.split('[')[0] for places in found.values() for p in places]
    ok = (len(found) == 1 and len(queues) == len(set(queues))
          and all('delivered' in p for places in found.values() for p in places))
    verdict('397 record delivered once', ok, f'{len(found)} end-notice id(s) for {alias} (== 1), each queue holds it once, none PENDING')
    return 0 if ok else 1


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
        return requests(Path(args[0]), Path(args[1]), args[2], args[3])
    if cmd == 'ends':
        return ends(Path(args[0]), Path(args[1]), args[2], *args[3:])
    if cmd == 'delivered':
        return delivered(Path(args[0]), args[1])
    if cmd == 'current':
        return current_is(Path(args[0]), args[1], args[2])
    if cmd == 'main':
        return main_unchanged(Path(args[0]), args[1], args[2])
    say('unknown command', cmd)
    return 2


if __name__ == '__main__':
    sys.exit(main())
