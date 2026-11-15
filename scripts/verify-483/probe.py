"""483 probe helper (trimmed from verify-444): Codex-Main checks 373 and 401 in an isolated project.

Run with the production Python (.venv-runtime/bin/python -I). Reads only the isolated project, the step outputs in
OUT, a Codex rollout (read only) and (step F) the Harness continuity record.

  probe.py prepare PROJECT              roles.yml (asker: Claude permission_mode default; advisor), role_tree,
                                        a fresh Task 1 (budget total 120, planned_sessions asker 3 / advisor 3) ready
  probe.py inbox PROJECT                continuity claims and every Main notice queue (ids, cursor, duplicates)
  probe.py claims PROJECT               continuity claims only (00: did the preflight probes claim Main here?)
  probe.py count FILE TOKEN...          occurrences of each TOKEN in FILE
  probe.py requests PROJECT OUT LABEL TAG  373 (a)-(d) for the asker dispatched in step LABEL (files 373-TAG-a/-b)
  probe.py agent PROJECT NAME           the agents-tool control record of NAME: agent id, each execution's outcome,
                                        notification (delivered/unconfirmed/held/unavailable/pending/queueing) and push
                                        fields; graftling/control.py:510-538 writes these after the push attempt
  probe.py ends PROJECT OUT ALIAS STREAM...  401: deliveries of ALIAS's end to the Codex Main (streams/records)
  probe.py rollout PROJECT ALIAS THREAD 401 (interactive): deliveries of ALIAS's end in THREAD's Codex rollout (read only)
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
BODY = '''---
difficulty: low
difficulty_reason: Scratch probe for 483
execution_budget:
  estimated_minutes:
    total: 120
  planned_sessions:
    asker: 3
    advisor: 3
  correction_rounds: 0
  estimation_note: Probe members of the 483 Codex-Main checks (fresh Task; 444's probe Task was budget-stopped)
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
    }
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': roles, 'role_tree': {'asker': {}, 'advisor': {}}}))
    work = project / '.graphtraj/probe-483'
    work.mkdir(exist_ok=True)
    register = work / 'register.yml'
    register.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'task_name': NAME, 'source': 'local:scratch/483', 'title': NAME, 'body': BODY,
        'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
        'replaced_by': [], 'retirement_reason': None}))
    state = work / 'state.yml'
    state.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
        'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-483/evidence.md']}))
    (work / 'evidence.md').write_text('483 probe: ready.\n')
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


def count(path: Path, *tokens: str) -> int:
    text = path.read_text(errors='replace') if path.is_file() else ''
    for t in tokens:
        say(f'count {t!r} in {path.name}: {text.count(t)}')
    return 0


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


def claims_only(project: Path) -> int:
    found = claims(project)
    for c in found:
        say('claim:', c.get('runtime'), c.get('session'), 'entry', c.get('entry'), 'at', c.get('at'))
    say('continuity claims in', project, ':', len(found), '| current Main:', (current(project) or {}).get('runtime'),
        (current(project) or {}).get('session'))
    return 0


def agent_records(project: Path, name: str) -> list[tuple[Path, dict]]:
    found = []
    for f in sorted((project / '.graphtraj/swarm/control/agents').glob('*.json')):
        try:
            record = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and (f.stem == name or name in {record.get('name'), (record.get('request') or {}).get('name')}):
            found.append((f, record))
    return found


def agent(project: Path, name: str) -> int:
    """The agents-tool control record: after a push attempt graftling/control.py:510-538 sets each execution's
    ``notification`` to delivered (Codex send_host_event returned), unconfirmed (it raised for a native parent),
    held/unavailable, or leaves pending/queueing with push_deferred while not yet taken."""
    found = agent_records(project, name)
    if not found:
        say('AGENT', name, 'NONE: no control record under .graphtraj/swarm/control/agents')
        return 1
    for f, record in found:
        say('AGENT', name, 'id', f.stem, '| parent', record.get('parent'), '| creator', json.dumps(record.get('creator'))[:200])
        for e in record.get('executions') or []:
            short = {k: (v if len(json.dumps(v)) < 160 else json.dumps(v)[:160] + '...') for k, v in e.items()}
            say('  execution', json.dumps(short, ensure_ascii=False))
            say('  NOTIFICATION', e.get('id'), e.get('notification'))
    return 0


def rollout(project: Path, name: str, thread: str) -> int:
    """401 (interactive Codex Main): count the end event of NAME in THREAD's rollout (~/.codex/sessions, read only),
    by event identity (agent id + execution id + end outcome). Model output, reasoning and tool-call arguments are
    excluded; a tool result (status/wait) is a pull and is listed but not counted as a push delivery."""
    found = agent_records(project, name)
    if not found:
        say('401 interactive: no control record for', name)
        return 1
    stem, record = found[-1][0].stem, found[-1][1]
    ends = [(e.get('id'), e.get('notification')) for e in record.get('executions') or []]
    say('agent', name, '=', stem, '| executions (id, notification):', ends)
    files = sorted((Path.home() / '.codex/sessions').rglob(f'rollout-*{thread}*.jsonl')) if thread else []
    say('rollout files for thread', thread, ':', [str(f) for f in files] or 'NONE')
    pushes: list[str] = []
    pulls: list[str] = []
    for f in files:
        for number, rec in jsonl(f):
            payload = rec.get('payload') if isinstance(rec, dict) else None
            kind = f"{rec.get('type')}/{(payload or {}).get('type')}/{(payload or {}).get('role', '')}" if isinstance(rec, dict) else '?'
            if isinstance(payload, dict) and (payload.get('type') in {'reasoning', 'function_call', 'custom_tool_call', 'agent_message', 'agent_reasoning'}
                                              or payload.get('role') == 'assistant'):
                continue
            text = flat(rec)
            for execution, _ in ends:
                if stem in text and execution and execution in text and re.search(r'completed|failed|interrupted', text):
                    where = f'{f.name}:{number} {kind}'
                    (pulls if 'output' in kind or 'tool_call_end' in kind or 'mcp' in kind else pushes).append(where)
                    say('  raw', where, text[:300])
    say('rollout push-shaped records (by identity):', pushes or 'none')
    say('rollout tool-result records (pulls, not counted):', pulls or 'none')
    inputs = [p for p in pushes if p.split(' ')[1].startswith('response_item/')]
    ok = verdict('401 interactive delivered once', len(inputs) == 1,
                 f'{len(inputs)} model-input records (response_item) carrying {stem} end; '
                 f'{len(pushes) - len(inputs)} other host records (event_msg echo of the same input) listed above')
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
    if cmd == 'inbox':
        return inbox(Path(args[0]))
    if cmd == 'count':
        return count(Path(args[0]), *args[1:])
    if cmd == 'requests':
        return requests(Path(args[0]), Path(args[1]), args[2], args[3])
    if cmd == 'ends':
        return ends(Path(args[0]), Path(args[1]), args[2], *args[3:])
    if cmd == 'claims':
        return claims_only(Path(args[0]))
    if cmd == 'agent':
        return agent(Path(args[0]), args[1])
    if cmd == 'rollout':
        return rollout(Path(args[0]), args[1], args[2])
    if cmd == 'current':
        return current_is(Path(args[0]), args[1], args[2])
    if cmd == 'main':
        return main_unchanged(Path(args[0]), args[1], args[2])
    say('unknown command', cmd)
    return 2


if __name__ == '__main__':
    sys.exit(main())
