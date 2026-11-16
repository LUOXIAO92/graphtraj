"""Nr, 492 part (taken from adopt-475/nr475.py with 471's fixes: 'claude:'-prefixed session ids, the member's own
archive found by its header): Bash really started (child and member), 465's member settings and session_read, and
492's checks of 466 (agents session_read), 477 (last_message, no push after wait) and 468 (Worker CPU) (read only).

usage: nr492.py <project> <raw dir> <child name> <member alias> <task directory name>

Acceptance rule (user, 475): an unobserved required check is NOT met. When a Bash tool did not start, this prints
``BLOCKED: <check> not observed - <error text> (emitted in <file>)`` and the CHECK is FAIL, never PASS.

Where the facts are:
  child record     <project>/.graphtraj/swarm/control/agents/<agent>.json (graftling/control.py): name, session,
                   executions[*].process.tool_descendants (459's record of the child's tool processes).
  Nw snapshots     <raw>/Nw-snapshots.jsonl (watch459.py): the record while the child ran.
  archives         <project>/.graphtraj/swarm/sessions/<sha256 of '<runtime>:<id>'>/session.jsonl, found by its first
                   line's header (471: exactly one, else NOT OBSERVED with the candidates); a Bash result is a
                   tool_result item answering a Bash tool-call. If readable, the native transcript
                   ~/.claude/projects/*/<session>.jsonl is searched for the error text only.
  member settings  <project>/.graphtraj/core/runner/sessions/<alias>/claude-settings.yml (graftling/claude/execution.py
                   writes it; 465 stops adding one grant per associated history file). After retirement the Session
                   directory may be under the Task's teams/*/traces/<alias>/runner/.
  member reply     <raw>/N-reply.txt: the line 'SESSION-READ-492 session=[<runtime>:]<id> events=<n>' and 'member-bash-ok'.
Only counts, sizes and booleans are printed for the settings; never a value.
"""
import json, re, sys
from pathlib import Path

import yaml

project, raw, name, alias, task = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]
TOOL_NAME = f'{name}-tool'
ERRORS = re.compile(r'E2BIG|Argument list too long|Could not start|spawn [^\s]* ?ENOENT|EACCES|Operation not permitted|'
                    r'failed to start|sandbox[^"]{0,40}(error|fail)', re.I)
HOME = Path.home()


def check(label, ok, detail=''):
    print(f"CHECK {label}: {ok if isinstance(ok, str) else ('PASS' if ok else 'FAIL')}{(' (' + detail + ')') if detail else ''}")


def events(path: Path) -> list[dict]:
    out = []
    try:
        for line in path.read_text(errors='replace').splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    except OSError as error:
        print(f'  cannot read {path}: {type(error).__name__}')
    return out


def error_text(files: list[Path], extra: list[tuple[str, str]] = ()) -> str:
    """The first error-like text and where it was emitted, for a BLOCKED line."""
    for path in files:
        try:
            text = path.read_text(errors='replace')
        except OSError:
            continue
        for line in text.splitlines():
            match = ERRORS.search(line)
            if match:
                start = max(0, match.start() - 80)
                return f"{line[start:match.end() + 120]!r} (emitted in {path})"
    for where, text in extra:
        match = ERRORS.search(text)
        if match:
            start = max(0, match.start() - 80)
            return f"{text[start:match.end() + 120]!r} (quoted in {where})"
    return 'no error text found in ' + ', '.join(str(f) for f in files) + (' or ' + ', '.join(w for w, _ in extra) if extra else '')


def _items(event: dict):
    """Content items of a message event: archive data.content / data.message.content, native message.content."""
    data = event.get('data') if isinstance(event.get('data'), dict) else {}
    for content in (data.get('content'), (data.get('message') or {}).get('content'), (event.get('message') or {}).get('content')):
        if isinstance(content, list):
            yield from (item for item in content if isinstance(item, dict))


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(i if isinstance(i, str) else str(i.get('text', '')) for i in content if isinstance(i, (str, dict)))
    return ''


def bash_results_with(evs: list[dict], needle: str) -> list[str]:
    """Bash tool results (not errors) containing needle, as 'seq <n>' labels.

    The archive has no 'tool/result' events: a result is a tool_result content item of a user/message (native: 'user')
    whose tool_use_id answers a Bash tool-call (native: tool_use) of an assistant/message. Text that merely quotes
    the needle (instructions, replies) is not a tool_result and does not count."""
    calls = {i.get('id') for e in evs if e.get('type') in ('assistant/message', 'assistant') for i in _items(e)
             if i.get('type') in ('tool-call', 'tool_use') and i.get('name') == 'Bash'}
    found = []
    for e in evs:
        if e.get('type') in ('user/message', 'user') and any(
                i.get('type') == 'tool_result' and i.get('tool_use_id') in calls and i.get('is_error') is not True
                and needle in _text(i.get('content')) for i in _items(e)):
            found.append(f"seq {e.get('seq', '?')}")
    return found


def own_archives(session) -> list[Path]:
    """Swarm archives whose header is this Session's: directories are sha256 of the canonical id ('<runtime>:<id>'),
    so match the first line's header (native.sessionId without a sub-agent, or id '<runtime>:<id>'), not the name."""
    out = []
    for path in sorted((project / '.graphtraj/swarm/sessions').glob('*/session.jsonl')):
        try:
            with path.open(encoding='utf-8', errors='replace') as stream:
                meta = json.loads(stream.readline())
        except (OSError, ValueError):
            continue
        header = meta.get('header', meta) if isinstance(meta, dict) else {}
        native = header.get('native') or {} if isinstance(header, dict) else {}
        hid = str(header.get('id', '')) if isinstance(header, dict) else ''
        if (native.get('sessionId') == session and not native.get('agentId')) or \
                (':' in hid and hid.split(':', 1)[1] == session):
            out.append(path)
    return out


def archive_for(session, who: str) -> Path | None:
    """Exactly one own archive, else print the candidates and return None (the check stays NOT OBSERVED)."""
    matches = own_archives(str(session)) if session else []
    if len(matches) != 1:
        print(f'  {who} archive: {len(matches)} swarm archives with header session {session}: {[str(m) for m in matches]}')
        return None
    return matches[0]


def bare(session_id: str) -> str:
    """'claude:<id>' -> '<id>'; a bare id stays as it is."""
    return session_id.split(':', 1)[1] if ':' in session_id else session_id


# --- the child record and its Session ---------------------------------------------------------------------------
agents = project / '.graphtraj/swarm/control/agents'
found = []
for path in agents.glob('*.json') if agents.is_dir() else ():
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        continue
    if record.get('name') == name:
        found.append((path.stat().st_mtime, path, record))
if not found:
    print(f'475: NO {name} child record under {agents}')
    sys.exit(1)
_, child_path, child = max(found, key=lambda item: item[0])
exs = child.get('executions') or []
child_session = child.get('session') or next((e.get('session') for e in exs if e.get('session')), None)
print(f'475: child {name} agent={child.get("agent")} session={child_session}')
reply_file = raw / 'N-reply.txt'
reply = reply_file.read_text(errors='replace') if reply_file.is_file() else ''
child_archive = archive_for(bare(str(child_session)), 'child') if child_session else None
child_files = [child_archive] if child_archive else []
if child_session:
    try:
        child_files += sorted((HOME / '.claude/projects').glob(f'*/{child_session}.jsonl'))
    except OSError:
        pass
child_files = [f for f in child_files if f.is_file()]
print(f'  child archives searched: {[str(f) for f in child_files] or "none found"}')

# --- 459: the child's Bash started (the descendants record listed the command) ------------------------------------
tool = re.compile(re.escape(TOOL_NAME) + r'|(^|[^0-9A-Za-z])sleep 3([^0-9]|$)')
listed = 0
snapshots = raw / 'Nw-snapshots.jsonl'
create_id = exs[0].get('id') if exs else None
for item in events(snapshots) if snapshots.is_file() else []:
    if item.get('agent') == child.get('agent') and item.get('execution') == create_id:
        listed += sum(1 for entry in (item.get('record') or {}).get('entries') or [] if tool.search(str(entry.get('argv', ''))))
sidecar = ((exs[0].get('process') or {}).get('tool_descendants') if exs else None)
if isinstance(sidecar, str) and Path(sidecar).is_file():
    try:
        listed += sum(1 for entry in json.loads(Path(sidecar).read_text()).get('entries') or [] if tool.search(str(entry.get('argv', ''))))
    except (OSError, ValueError):
        pass
child_output = len(bash_results_with(events(child_archive), TOOL_NAME)) if child_archive else 0
print(f'  record entries naming {TOOL_NAME} or sleep 3: {listed}; child tool results containing {TOOL_NAME}: {child_output}')
if listed:
    check('459 child Bash started (record lists the command)', True, f'{listed} record entries')
else:
    where = error_text(child_files, [(str(reply_file), reply)] if reply else [])
    print(f'BLOCKED: 459 child Bash started not observed - {where}')
    check('459 child Bash started (record lists the command)', False,
          'NOT OBSERVED' + (f'; the child archive shows {TOOL_NAME} output, but no record listed it' if child_output else ''))

# --- 465: the member's claude-settings has no per-session-file grant ---------------------------------------------
candidates = [project / '.graphtraj/core/runner/sessions' / alias / 'claude-settings.yml',
              project / '.graphtraj/runner/sessions' / alias / 'claude-settings.yml']
candidates += sorted(project.glob(f'.graphtraj/core/state/tasks/{task}/teams/*/traces/{alias}/runner/claude-settings.yml'))
settings_file = next((c for c in candidates if c.is_file()), None)
history_roots = [str(HOME / '.claude/projects') + '/', str(HOME / '.codex/sessions') + '/']


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


if settings_file is None:
    print(f'  member settings: not found ({[str(c) for c in candidates[:2]]})')
    check('465 member claude-settings has no per-session-file grants', False, 'NOT OBSERVED: settings file not found')
else:
    data = yaml.safe_load(settings_file.read_text()) or {}
    settings = data.get('settings', data) if isinstance(data, dict) else {}
    permissions = settings.get('permissions', {}) if isinstance(settings, dict) else {}
    filesystem = (settings.get('sandbox', {}) or {}).get('filesystem', {}) if isinstance(settings, dict) else {}
    counts = {'bytes': settings_file.stat().st_size,
              **{k: len(permissions.get(k, []) or []) for k in ('allow', 'deny', 'additionalDirectories')},
              **{k: len(filesystem.get(k, []) or []) for k in ('allowRead', 'denyRead', 'allowWrite', 'denyWrite')}}
    history = [s for s in strings(data) if '.jsonl' in s and any(root in s for root in history_roots)]
    print(f'  member settings {settings_file}: {json.dumps(counts)}; entries naming a *.jsonl under ~/.claude/projects or ~/.codex/sessions: {len(history)}')
    check('465 member claude-settings has no per-session-file grants', not history, f'{len(history)} such entries; values not printed')

# --- 465: the member's session_read returned the child's Session --------------------------------------------------
# The member quotes the canonical id, optionally with a Runtime prefix ('claude:<id>'); the record holds the bare id.
quoted = re.findall(r'SESSION-READ-492\s+session=((?:[A-Za-z][\w.-]*:)?[0-9A-Za-z-]+)\s+events=(\d+)', reply)
if quoted:
    sid, count = quoted[-1]
    print(f'  member quoted: session={sid} (bare {bare(sid)}) events={count}; child record session={child_session} '
          f'(bare {bare(str(child_session)) if child_session else None})')
    check('465 member session_read returned the child\'s Session (id match)',
          bool(child_session) and bare(sid) == bare(str(child_session)), f'events={count}')
else:
    where = error_text([], [(str(reply_file), reply)] if reply else [])
    print(f"BLOCKED: 465 member session_read not observed - no 'SESSION-READ-492 session=<id> events=<n>' line in "
          f"{reply_file if reply else str(reply_file) + ' (missing)'}; {where}")
    check('465 member session_read returned the child\'s Session (id match)', False, 'NOT OBSERVED')

# --- the member's own Bash started -------------------------------------------------------------------------------
member_session = None
for c in (project / '.graphtraj/core/runner/sessions' / alias / 'mapping.yml',
          *project.glob(f'.graphtraj/core/state/tasks/{task}/teams/*/traces/{alias}/runner/session.yml')):
    if c.is_file():
        d = yaml.safe_load(c.read_text()) or {}
        m = d if c.name == 'mapping.yml' else ((d.get('retirement') or {}).get('mapping') or {})
        member_session = m.get('session')
        member_session = member_session.get('id') if isinstance(member_session, dict) else member_session
        break
archive = archive_for(bare(str(member_session)), 'member') if member_session else None
member_files = [archive] if archive else []
if member_session:
    try:
        member_files += sorted((HOME / '.claude/projects').glob(f'*/{member_session}.jsonl'))
    except OSError:
        pass
member_files = [f for f in member_files if f.is_file()]
ok_results = bash_results_with(events(archive), 'member-bash-ok') if archive else []
print(f'  member session={member_session}; archive={archive}; Bash tool results containing member-bash-ok: {len(ok_results)} '
      f'{ok_results}; '
      f'reply quotes it: {"member-bash-ok" in reply}')
if ok_results:
    check('member Bash started', True, f'a Bash tool_result in the member archive contains member-bash-ok ({ok_results[0]})')
else:
    where = error_text(member_files, [(str(reply_file), reply)] if reply else [])
    print(f'BLOCKED: member Bash started not observed - {where}')
    check('member Bash started', False, 'NOT OBSERVED' + ('; the reply quotes it but the archive has no such tool result'
                                                           if 'member-bash-ok' in reply else ''))


# --- 492: 466 (agents session_read), 477 (last_message; no push after wait) -------------------------------------
KEYWORD, DONE = 'KW492-ORCHID', 'DONE-492'
FAKE = 'sk-probe492fake' + 'value0000'   # never printed; counts only


def agent_calls(evs: list[dict]) -> list[tuple[dict, str]]:
    """(arguments, result text) of each mcp__agents__agents call in an archive, in order."""
    calls, out = {}, []
    for e in evs:
        for i in _items(e):
            if i.get('type') in ('tool-call', 'tool_use') and str(i.get('name', '')).endswith('agents__agents'):
                args = i.get('input', i.get('arguments', {}))
                if isinstance(args, str):
                    try: args = json.loads(args)
                    except ValueError: args = {}
                calls[i.get('id')] = args if isinstance(args, dict) else {}
            elif i.get('type') == 'tool_result' and i.get('tool_use_id') in calls:
                out.append((calls[i['tool_use_id']], _text(i.get('content'))))
    return out


def deep(value, depth=0):
    """Decode nested JSON strings (478 Round 2: the real tool_result content is a JSON string
    {action, agent, ..., result: {...}}, possibly inside [{type: text, text: ...}])."""
    if depth > 8:
        return value
    if isinstance(value, str):
        s = value.strip()
        if s[:1] in '{[':
            try:
                return deep(json.loads(s), depth + 1)
            except ValueError:
                i = s.find('{')
                try:
                    return deep(json.loads(s[i:]), depth + 1) if i > 0 else value
                except ValueError:
                    return value
        return value
    if isinstance(value, dict):
        return {k: deep(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [deep(v, depth + 1) for v in value]
    return value


def doc(text: str):
    """The session_read result: the first dict holding 'total' (nr466.py's walker), else None."""
    todo = [deep(text)]
    while todo:
        v = todo.pop(0)
        if isinstance(v, dict):
            if 'total' in v:
                return v
            todo.extend(v.values())
        elif isinstance(v, list):
            todo.extend(v)
    return None


def shape(value, depth=0):
    if depth > 3: return '…'
    if isinstance(value, dict): return {k: shape(v, depth + 1) for k, v in list(value.items())[:12]}
    if isinstance(value, list): return [f'list[{len(value)}]'] + ([shape(value[0], depth + 1)] if value else [])
    if isinstance(value, str): return f'str[{len(value)}]'
    return type(value).__name__


def seq_of(e):
    return e.get('seq') if 'seq' in e else ((e.get('event') or {}).get('seq') if isinstance(e.get('event'), dict) else None)


def values(value, key):
    if isinstance(value, dict):
        for k, v in value.items():
            if k == key: yield v
            yield from values(v, key)
    elif isinstance(value, list):
        for v in value: yield from values(v, key)


member_events = events(archive) if archive else []
child_events = events(child_archive) if child_archive else []
calls = agent_calls(member_events)
where = f'member archive {archive}' if archive else 'member archive NOT FOUND (see the member archive line above)'
print(f'492: agents calls in the member archive: {[(c.get("feature") or c.get("action")) for c, _ in calls]}')
reads = [(c.get('arguments') or {}, doc(t), t) for c, t in calls if c.get('feature') == 'session_read']
for a, d, t in reads:
    if d is None:
        print(f'  session_read {sorted(a.items())}: no dict with total; structure: {json.dumps(shape(deep(t)))[:600]}')
default = next((d for a, d, _ in reads if d and 'start' not in a and 'stop' not in a and 'search' not in a), None)
page = next((d for a, d, _ in reads if d and a.get('start') == -10 and a.get('stop') == -5), None)
found = next((d for a, d, _ in reads if d and a.get('search') == KEYWORD), None)
if default:
    idx, total = [e.get('index') for e in default.get('events', [])], default.get('total')
    check('466 default read = last 5', isinstance(total, int) and idx == list(range(total))[-5:], f'total={total} indices={idx}')
else:
    check('466 default read = last 5', 'BLOCKED', f'no default session_read result in {where}')
if page:
    idx, total = [e.get('index') for e in page.get('events', [])], page.get('total')
    check('466 page back [-10:-5]', isinstance(total, int) and idx == list(range(total))[-10:-5], f'total={total} indices={idx}')
else:
    check('466 page back [-10:-5]', 'BLOCKED', f'no session_read result with start -10 stop -5 in {where}')
if found:
    hits = [(h.get('index'), h.get('seq')) for h in found.get('hits', [])]
    seqs = {e.get('seq') for e in child_events if KEYWORD in json.dumps(e)}
    total = found.get('total')
    ok = bool(hits) and all(s in seqs for _, s in hits) and all(isinstance(i, int) and i < (total or 0) - 10 for i, _ in hits)
    check('466 keyword search hits the child events holding the keyword (before the last 10)', ok,
          f'hits (index, seq)={hits} child archive seqs with it={sorted(s for s in seqs if s is not None)} total={total}')
else:
    check('466 keyword search', 'BLOCKED', f'no session_read result with search {KEYWORD} in {where}')
# 466 masking, 478 Round 3: search runs on redacted text (api_key=sk-… becomes api_key="[redacted]"), so the member
# searches content tools for api_key and for [redacted]. PASS: a result shows an event at a child seq holding the
# value with '[redacted]', the value 0 times in all results, the member archive and its native transcript. Counts only.
results_text = ''.join(t for _, _, t in reads)
in_child = sum(json.dumps(e).count(FAKE) for e in child_events)
fake_seqs = sorted({e.get('seq') for e in child_events if e.get('seq') is not None and FAKE in json.dumps(e)})
in_member = sum(json.dumps(e).count(FAKE) for e in member_events)
transcripts = sorted((HOME / '.claude/projects').glob(f'*/{bare(str(member_session))}.jsonl')) if member_session else []
in_native = sum(p.read_text(errors='replace').count(FAKE) for p in transcripts)
masked = []
for a, d, t in reads:
    if d is None or a.get('content') != 'tools' or a.get('search') not in ('api_key', '[redacted]'):
        continue
    evs = [e for e in (d.get('events') or []) + (d.get('hits') or []) if isinstance(e, dict)]
    at = [seq_of(e) for e in evs if seq_of(e) in fake_seqs]
    red = t.count('[redacted]')
    print(f"  466 masking read search={a.get('search')!r}: total={d.get('total')} seqs={[seq_of(e) for e in evs]} "
          f"at fake-value seqs={at} '[redacted]'={red} value present={'yes' if FAKE in t else 'no'}")
    if at and red:
        masked.append((a.get('search'), at))
print(f'466: fake key occurrences: child archive {in_child} at seqs {fake_seqs}, session_read results {results_text.count(FAKE)}, '
      f'[redacted] marks in results {results_text.count("[redacted]")}, member archive {in_member}, '
      f'member native transcript {in_native} ({len(transcripts)} file(s)); masked results {masked}')
check('466 credential masked (a content-tools search shows a fake-value event redacted; value 0 in results, member archive and transcript)',
      'BLOCKED (no child event with a seq holds the fake key)' if not fake_seqs else
      (bool(masked) and results_text.count(FAKE) == 0 and in_member == 0 and in_native == 0 and bool(archive)),
      'counts above')
# 477
wait_msgs = [m for c, t in calls if c.get('feature') == 'wait' for m in values(deep(t), 'last_message')]
status_msgs = [m for c, t in calls if c.get('feature') == 'status' and (c.get('arguments') or {}).get('agent')
               for m in values(deep(t), 'last_message')]
check('477 wait last_message == the child reply DONE-492', any(isinstance(m, str) and m.strip() == DONE for m in wait_msgs),
      f'wait last_message values {[str(m)[:40] for m in wait_msgs]} ({where})')
check('477 status last_message == DONE-492', any(isinstance(m, str) and m.strip() == DONE for m in status_msgs),
      f'status last_message values {[str(m)[:40] for m in status_msgs]} ({where})')
pushed = []
for ex in exs:
    eid = ex.get('id')
    for e in member_events:
        if eid and e.get('type') == 'user/message' and eid in json.dumps(e) and 'graphtraj' in json.dumps(e) \
                and not any(i.get('type') == 'tool_result' for i in _items(e)):
            pushed.append((eid, e.get('seq')))
check('477 child end not pushed to the member after wait delivered it (graphtraj notification inputs = 0)',
      (len(pushed) == 0) if archive and exs else 'BLOCKED', f'inputs (execution, seq)={pushed} ({where})')

# --- 492: 487 (wait timeout and push race: the reply reaches the member once) -----------------------------------
# Only executed waits (491): the member's earlier {action: describe, feature: wait} call is not a wait.
waits = [(c.get('arguments') or {}, deep(t)) for c, t in calls if c.get('feature') == 'wait' and c.get('action') == 'execute']
if waits:
    a0, r0 = waits[0]
    timed = list(values(r0, 'timed_out'))
    state0 = [s for s in values(r0, 'state') if isinstance(s, str)]
    print(f"487: wait calls {len(waits)}; first wait arguments {sorted(a0.items())} timed_out={timed} states={state0}")
    check('487 first wait timed out while the child ran (short finite timeout returned timed_out true)',
          True in timed and 'ended' not in state0, f'timed_out={timed} states={state0}')
else:
    check('487 first wait timed out while the child ran', 'BLOCKED', f'no agents wait call in {where}')
delivered = sum(1 for m in wait_msgs + status_msgs if isinstance(m, str) and m.strip() == DONE)
check(f'487 reply delivered once ({DONE} through wait/status; graphtraj inputs pushed for that execution = 0)',
      (any(isinstance(m, str) and m.strip() == DONE for m in wait_msgs) and len(pushed) == 0) if archive and exs else 'BLOCKED',
      f'wait/status results with {DONE}: {delivered}; pushed inputs {len(pushed)}')

# --- 492: 486 (the child and the member end normally; nothing interrupted) ----------------------------------------
for ex in exs:
    check(f"486 child {name} execution {ex.get('id')} ended completed, not interrupted",
          ex.get('outcome') == 'completed', f"state={ex.get('state')} outcome={ex.get('outcome')} error={(ex.get('error') or {}).get('code')}")
end = {}
for c in (project / '.graphtraj/core/runner/sessions' / alias / 'execution.yml',
          *project.glob(f'.graphtraj/core/state/tasks/{task}/teams/*/traces/{alias}/runner/execution.yml')):
    if c.is_file():
        end = yaml.safe_load(c.read_text()) or {}
        break
check('486 member end normal (execution.yml outcome completed)', end.get('outcome') == 'completed' if end else 'PENDING',
      f"outcome={end.get('outcome')} terminal_confirmed={end.get('terminal_confirmed')}")
