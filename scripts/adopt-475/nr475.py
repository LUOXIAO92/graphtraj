"""Nr, 475 part: Bash really started (child and member), 465's member settings and session_read (read only).

usage: nr475.py <project> <raw dir> <child name> <member alias> <task directory name>

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
  member reply     <raw>/N-reply.txt: the line 'SESSION-READ-475 session=[<runtime>:]<id> events=<n>' and 'member-bash-ok'.
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
quoted = re.findall(r'SESSION-READ-475\s+session=((?:[A-Za-z][\w.-]*:)?[0-9A-Za-z-]+)\s+events=(\d+)', reply)
if quoted:
    sid, count = quoted[-1]
    print(f'  member quoted: session={sid} (bare {bare(sid)}) events={count}; child record session={child_session} '
          f'(bare {bare(str(child_session)) if child_session else None})')
    check('465 member session_read returned the child\'s Session (id match)',
          bool(child_session) and bare(sid) == bare(str(child_session)), f'events={count}')
else:
    where = error_text([], [(str(reply_file), reply)] if reply else [])
    print(f"BLOCKED: 465 member session_read not observed - no 'SESSION-READ-475 session=<id> events=<n>' line in "
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
