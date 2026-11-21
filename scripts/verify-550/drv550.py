"""Task 550 driver (shape A, Main decision ~16:55): three headless `claude -p` roles and a mechanical relay.

usage (steps.zsh calls these; python -I, standard library only):
  drv550.py ready  <role U|S|A> <effort list, comma separated>   one READY turn (S: + probes a, b, c)
  drv550.py run    <S#>          one scenario: files from design.md, relay S <-> U, U's sources answer
  drv550.py audit  <S#>          builds BASE/audit/<S#>, runs the auditor, saves logs/<S#>/audit.md
  drv550.py collect <S#> <dest>  copies everything to <dest>/<S#>/ and prints K0a, out-of-ws paths, audit line 1
Configuration comes from the environment steps.zsh sets: V550_BASE, V550_WT, V550_H, V550_CLAUDE, V550_MCP,
V550_TURN_S, V550_DENYROOT, V550_CONTEXT (S1's glossary source).

Every turn is `claude -p --output-format stream-json --verbose`, bounded by a perl alarm, its stdin the message,
its stdout kept as logs/<S#>/NN-<role>.jsonl. The relay copies S's final text to U and U's final text to S
unchanged: no model writes, summarises or filters any relayed message.
"""
import functools, json, os, re, shutil, subprocess, sys, time
from pathlib import Path

ENV = os.environ
BASE = Path(ENV.get('V550_BASE', '/private/tmp/cc-550'))
WT = Path(ENV['V550_WT']) if 'V550_WT' in ENV else Path(__file__).resolve().parents[2]
H = Path(ENV.get('V550_H', str(WT.parents[3])))
CLAUDE = ENV.get('V550_CLAUDE', 'claude')
MCP_BIN = ENV.get('V550_MCP', str(H / '.venv-runtime/bin/graphtraj-mcp'))
TURN_S = int(ENV.get('V550_TURN_S', '900'))
DENYROOT = Path(ENV.get('V550_DENYROOT', '/Users/luoxiao/workspace'))
DESIGN = WT / 'scripts/verify-550/design.md'
PROJECT = BASE / 'project'
MODELS = {'U': 'claude-fable-5-2', 'S': 'claude-haiku-5-5', 'A': 'claude-sonnet-5-5'}
MAX_EXCHANGES = 6
SCENARIOS = ('S1', 'S2', 'S3', 'S4')
EDIT_TOOLS = ('Edit', 'Write', 'MultiEdit', 'NotebookEdit')
# Every child (claude, graphtraj-mcp) gets only these variables: a caller's GRAPHTRAJ_CLI_CONNECTION / GRAFTLING_* /
# CLAUDECODE would bind S's MCP server to the caller's own Session (seen in the rehearsal: 'Agent Runner must be
# invoked from the Harness Project Root or this Session's Worktree.').
KEEP_ENV = ('HOME', 'USER', 'PATH', 'TERM', 'TMPDIR', 'LANG', 'STUB550_STATE')


def clean_env():
    return {k: ENV[k] for k in KEEP_ENV if k in ENV}


# ---------------------------------------------------------------- design.md (the single source of the texts)
def design():
    text = DESIGN.read_text(encoding='utf-8')
    lines = text.splitlines()

    def quote_after(marker):
        i = next(n for n, l in enumerate(lines) if l.startswith(marker))
        out, n = [], i + 1
        while n < len(lines) and not lines[n].startswith('> '):
            n += 1
        while n < len(lines) and lines[n].startswith('> '):
            out.append(lines[n][2:]); n += 1
        return '\n'.join(out)

    sources_q = re.search(r'After the loop U receives: "(.+)"', text).group(1)
    scenarios = {}
    for part in re.split(r'^## (?=S\d )', text, flags=re.M)[1:]:
        sid = part.split()[0]
        files, plines = {}, part.splitlines()
        n = 0
        while n < len(plines):
            if plines[n].startswith('```'):
                prev = next(l for l in reversed(plines[:n]) if l.strip())
                name = re.findall(r'([\w.-]+\.md):\s*$', prev)[-1]
                end = next(m for m in range(n + 1, len(plines)) if plines[m].startswith('```'))
                files[name] = '\n'.join(plines[n + 1:end]) + '\n'
                n = end
            n += 1
        opening = re.search(r'^OPENING: "(.+)"\s*$', part, re.M).group(1)
        hidden = re.search(r'^HIDDEN: (.+)$', part, re.M).group(1)
        scenarios[sid] = {'files': files, 'opening': opening, 'hidden': hidden,
                          'copy_context': 'CONTEXT.md (copy)' in part}
    return {'S': quote_after('S instruction'), 'U': quote_after('U instruction'),
            'A': quote_after('Auditor instruction'), 'sources': sources_q, 'scenarios': scenarios}


# ---------------------------------------------------------------- per-role command lines
def abs_rule(tool, path, tree=True):
    """Claude permission rule(s) for an absolute path; /private/tmp also as /tmp."""
    forms = {str(path)}
    if str(path).startswith('/private/tmp/'):
        forms.add(str(path)[len('/private'):])
    suffix = '/**' if tree else ''
    return [f'{tool}(/{p}{suffix})' for p in sorted(forms)] + ([f'{tool}(/{p})' for p in sorted(forms)] if tree else [])


def deny_except(root, keep, notes):
    """Deny rules for everything under root except the directory chain down to keep."""
    rules = []
    try:
        rel = keep.relative_to(root)
    except ValueError:
        return abs_rule('Read', root)
    cur = root
    for part in rel.parts:
        try:
            entries = sorted(os.listdir(cur))
        except OSError as error:
            notes.append(f'could not list {cur} ({error.strerror}); its siblings of {part} are not enumerated')
            entries = []
        for entry in entries:
            if entry != part:
                rules += abs_rule('Read', cur / entry)
        cur = cur / part
    return rules


@functools.lru_cache(maxsize=None)
def manual_dir():
    """Ask the product's stdio MCP server (in a ws-like cwd) for the guide's manual_ref; no model."""
    probe = PROJECT / 'runs/probe/ws'
    probe.mkdir(parents=True, exist_ok=True)
    msgs = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
        'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'v550', 'version': '0'}}},
        {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'tasks', 'arguments': {
            'action': 'describe', 'feature': 'concept-clarification'}}}]
    out = subprocess.run([MCP_BIN], input=''.join(json.dumps(m) + '\n' for m in msgs), cwd=probe, env=clean_env(),
                         capture_output=True, text=True, timeout=120).stdout
    for line in out.splitlines():
        d = json.loads(line)
        if d.get('id') == 2:
            ref = (d.get('result', {}).get('structuredContent') or {}).get('manual_ref')
            if ref:
                return Path(ref).parent, d
    raise SystemExit(f'STOP: tasks describe concept-clarification gave no manual_ref: {out[:400]}')


def s_files(sid):
    """S's MCP config and settings, both outside its ws (BASE/logs/<sid>)."""
    logs = BASE / 'logs' / sid
    logs.mkdir(parents=True, exist_ok=True)
    mdir, _ = manual_dir()
    notes = []
    deny = []
    for p in (BASE / 'u', BASE / 'audit', BASE / 'logs', Path.home() / '.claude'):
        deny += abs_rule('Read', p)
    deny += deny_except(DENYROOT, mdir, notes)
    deny += abs_rule('Edit', mdir) + abs_rule('Write', mdir)
    deny += ['Bash', 'WebSearch', 'WebFetch', 'mcp__graphtraj__agents']
    settings = {'permissions': {'deny': deny, 'allow': ['mcp__graphtraj__tasks'] + abs_rule('Read', mdir),
                                'additionalDirectories': [str(mdir)],
                                'blockReadsOutsideWorkingDirectories': True}}
    (logs / 's-settings.json').write_text(json.dumps(settings, indent=2) + '\n')
    (logs / 's-mcp.json').write_text(json.dumps({'mcpServers': {'graphtraj': {'command': MCP_BIN, 'args': []}}},
                                                indent=2) + '\n')
    (logs / 's-settings-notes.txt').write_text('\n'.join(notes) + '\n')
    return logs / 's-settings.json', logs / 's-mcp.json', mdir, notes


EMPTY_MCP = '{"mcpServers": {}}'


def argv(role, effort, sid, resume=None, system=None):
    """The exact command line of one turn (printed into the logs)."""
    a = [CLAUDE, '-p', '--output-format', 'stream-json', '--verbose', '--model', MODELS[role],
         '--setting-sources', 'project']
    if effort:
        a += ['--effort', effort]
    if role == 'S':
        st, mcp, mdir, _ = s_files(sid)
        a += ['--tools', 'Read,Edit,Write,Glob,Grep', '--allowedTools', 'mcp__graphtraj__tasks',
              '--disallowedTools', 'Bash,WebSearch,WebFetch,mcp__graphtraj__agents',
              '--permission-mode', 'acceptEdits', '--strict-mcp-config', '--mcp-config', str(mcp),
              '--settings', str(st), '--add-dir', str(mdir)]
    elif role == 'U':
        a += ['--tools', 'WebSearch,WebFetch', '--allowedTools', 'WebSearch,WebFetch',
              '--strict-mcp-config', '--mcp-config', EMPTY_MCP]
    else:
        a += ['--tools', 'Read,Glob,Grep', '--allowedTools', 'Read,Glob,Grep',
              '--disallowedTools', 'Bash,Edit,Write,WebSearch,WebFetch',
              '--strict-mcp-config', '--mcp-config', EMPTY_MCP,
              '--settings', json.dumps({'permissions': {'blockReadsOutsideWorkingDirectories': True}})]
    if system:
        a += ['--append-system-prompt', system]
    if resume:
        a += ['--resume', resume]
    return a


def parse(path):
    """init model/tools/auth, session id, final text, is_error, and the ordered tool calls of one stream."""
    info = {'model': None, 'tools': None, 'auth': None, 'session': None, 'text': None, 'is_error': None,
            'calls': [], 'results': {}}
    for line in Path(path).read_text(errors='replace').splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        if d.get('type') == 'system' and d.get('subtype') == 'init':
            info.update(model=d.get('model'), tools=d.get('tools'), auth=d.get('apiKeySource'),
                        session=d.get('session_id'))
        elif d.get('type') == 'assistant':
            for c in (d.get('message') or {}).get('content') or []:
                if c.get('type') == 'tool_use':
                    info['calls'].append({'id': c.get('id'), 'name': c.get('name'), 'input': c.get('input')})
        elif d.get('type') == 'user':
            content = (d.get('message') or {}).get('content')
            for c in content if isinstance(content, list) else []:
                if c.get('type') == 'tool_result':
                    body = c.get('content')
                    if isinstance(body, list):
                        body = '\n'.join(str(x.get('text', '')) for x in body if isinstance(x, dict))
                    info['results'][c.get('tool_use_id')] = {'is_error': c.get('is_error'), 'text': str(body)}
        elif d.get('type') == 'result':
            info.update(text=d.get('result'), is_error=d.get('is_error'), session=d.get('session_id') or info['session'])
    return info


def turn(role, effort, sid, n, message, cwd, resume=None, system=None):
    logs = BASE / 'logs' / sid
    logs.mkdir(parents=True, exist_ok=True)
    out = logs / f'{n:02d}-{role}.jsonl'
    a = argv(role, effort, sid, resume, system)
    shown = [('<U instruction with HIDDEN, see design.md>' if x == system else x) for x in a]
    (logs / f'{n:02d}-{role}.argv.json').write_text(json.dumps(shown, indent=1) + '\n')
    (logs / f'{n:02d}-{role}.in.txt').write_text(message)
    t0 = time.time()
    with open(out, 'w') as o, open(logs / f'{n:02d}-{role}.err', 'w') as e:
        rc = subprocess.run(['/usr/bin/perl', '-e', 'alarm shift; exec @ARGV or die "exec: $!\\n"', str(TURN_S), *a],
                            input=message, stdout=o, stderr=e, cwd=cwd, text=True, env=clean_env()).returncode
    info = parse(out)
    log(sid, f'turn {n:02d} {role} rc={rc} {time.time() - t0:.0f}s model={info["model"]} session={info["session"]} '
             f'is_error={info["is_error"]} tools={len(info["calls"])} text_chars={len(info["text"] or "")}')
    if info['text'] is None or info['is_error']:
        raise RuntimeError(f'{role} turn {n:02d} gave no usable result (rc {rc}; see {out} and .err)')
    return info


def log(sid, text):
    line = f'{time.strftime("%H:%M:%S")} {text}'
    print(line, flush=True)
    with open(BASE / 'logs' / sid / 'driver.log', 'a') as f:
        f.write(line + '\n')


def done(text):
    rows = [l.strip() for l in (text or '').splitlines() if l.strip()]
    return bool(rows) and rows[-1] == 'DONE'


def effort_of(role):
    f = BASE / f'effort-{role}.txt'
    return f.read_text().strip() if f.is_file() else None


# ---------------------------------------------------------------- steps
def cmd_ready(role, efforts):
    sid = 'ready'
    cwd = {'U': BASE / 'u/ready', 'S': PROJECT / 'runs/probe/ws', 'A': BASE / 'audit/ready'}[role]
    cwd.mkdir(parents=True, exist_ok=True)
    canary = BASE / 'u/ready/canary.txt'
    token = f'CANARY-{os.getpid()}-{int(time.time())}'
    if role == 'S':
        canary.parent.mkdir(parents=True, exist_ok=True)
        canary.write_text(token + '\n')
    tag = f'READY-550-{role}'
    ask = (f'Reply with exactly one line: {tag} followed by the model id you are running as, and say whether you '
           'are logged in. Use no tool.')
    if role == 'S':
        ask = ('Do these steps. 1. Call the `tasks` tool with action `describe` and feature `concept-clarification`. '
               '2. Read the file named by manual_ref in its answer. '
               f'3. Try to Read the file {canary}. '
               'Then reply with exactly three lines: line 1 GUIDE: followed by the first heading line of that guide; '
               'line 2 CANARY: followed by the file content, or REFUSED if the Read was refused; '
               f'line 3 {tag} followed by the model id you are running as and whether you are logged in.')
    info, chosen = None, None
    for n, effort in enumerate([e for e in efforts.split(',') if e] or [None], 1):
        try:
            info = turn(role, effort, sid, n + {'U': 10, 'S': 20, 'A': 30}[role], ask, cwd)
            chosen = effort
            break
        except RuntimeError as error:
            print(f'{role} effort {effort}: {error}')
    if info is None:
        print(f'{tag}: STOP (no effort in {efforts} gave a result)')
        return 1
    if chosen:
        (BASE / f'effort-{role}.txt').write_text(chosen + '\n')
    line = next((l for l in (info['text'] or '').splitlines() if tag in l), '(no tag line)')
    print(f'{tag} | init model: {info["model"]} | auth source (init apiKeySource): {info["auth"]} | effort: {chosen} '
          f'| answer: {line.strip()[:160]}')
    ok = info['model'] == MODELS[role] and tag in (info['text'] or '')
    if role == 'S':
        ok &= probes(info, canary, token)
    print(f'CHECK 550 {tag}: {"PASS" if ok else "FAIL"} (expect model {MODELS[role]})')
    return 0 if ok else 1


def probes(info, canary, token):
    mdir, _ = manual_dir()
    guide = mdir / 'guide.md'
    heading = next((l.strip() for l in guide.read_text(errors='replace').splitlines() if l.startswith('#')), '')
    describe = [c for c in info['calls'] if c['name'] == 'mcp__graphtraj__tasks'
                and (c['input'] or {}).get('feature') == 'concept-clarification']
    reads = [c for c in info['calls'] if c['name'] == 'Read']
    guide_read = [c for c in reads if heading and heading in info['results'].get(c['id'], {}).get('text', '')]
    canary_calls = [c for c in reads if str((c['input'] or {}).get('file_path', '')).endswith('canary.txt')]
    stream = ''.join(json.dumps(r) for r in info['results'].values())
    leaked = token in stream or token in (info['text'] or '')
    tools = info['tools'] or []
    banned = [t for t in tools if t in ('WebSearch', 'WebFetch', 'Bash') or t == 'mcp__graphtraj__agents']
    a = bool(describe) and bool(guide_read)
    b = bool(canary_calls) and all(info['results'].get(c['id'], {}).get('is_error') for c in canary_calls) and not leaked
    c = info['tools'] is not None and not banned
    print(f'probe (a) tasks describe concept-clarification: {len(describe)} call(s); a Read result holds the guide '
          f'heading {heading!r}: {"yes" if guide_read else "NO"} -> {"PASS" if a else "FAIL"}')
    print(f'probe (b) Read of the canary {canary}: {len(canary_calls)} attempt(s), results '
          f'{[info["results"].get(x["id"], {}).get("text", "(none)")[:120] for x in canary_calls]}; canary token in '
          f'S output: {"YES" if leaked else "no"} -> {"PASS" if b else ("NOT PROBED (S made no Read)" if not canary_calls else "FAIL")}')
    print(f'probe (c) init tools: {tools}; WebSearch/WebFetch/Bash/agents present: {banned or "none"} -> '
          f'{"PASS" if c else "FAIL"}')
    return a and b and c


def write_ws(sid, scen):
    ws = PROJECT / 'runs' / sid / 'ws'
    if ws.exists():
        shutil.move(str(ws.parent), str(ws.parent) + time.strftime('.%H%M%S'))
    ws.mkdir(parents=True)
    if scen['copy_context']:
        shutil.copyfile(ENV.get('V550_CONTEXT', str(H / 'CONTEXT.md')), ws / 'CONTEXT.md')
    for name, body in scen['files'].items():
        (ws / name).write_text(body, encoding='utf-8')
    return ws


def cmd_run(sid):
    d = design()
    scen = d['scenarios'][sid]
    logs = BASE / 'logs' / sid
    if logs.exists():
        shutil.move(str(logs), str(logs) + time.strftime('.%H%M%S'))
    logs.mkdir(parents=True)
    ws = write_ws(sid, scen)
    ucwd = BASE / 'u' / sid
    ucwd.mkdir(parents=True, exist_ok=True)
    log(sid, f'ws {ws}: {sorted(os.listdir(ws))} | U cwd {ucwd} | S effort {effort_of("S")} | U effort high')
    status = {'scenario': sid, 'exchanges': 0, 'done': False, 'error': None}
    u_system = d['U'].replace('<HIDDEN>', scen['hidden'])
    n = 1
    try:
        s = turn('S', effort_of('S'), sid, n, d['S'].replace('<OPENING>', scen['opening']), ws)
        s_session, u_session = s['session'], None
        while not done(s['text']) and status['exchanges'] < MAX_EXCHANGES:
            n += 1
            u = turn('U', 'high', sid, n, s['text'], ucwd, resume=u_session, system=u_system)
            u_session = u['session']
            n += 1
            s = turn('S', effort_of('S'), sid, n, u['text'], ws, resume=s_session)
            status['exchanges'] += 1
        status['done'] = done(s['text'])
        if u_session:
            n += 1
            src = turn('U', 'high', sid, n, d['sources'], ucwd, resume=u_session, system=u_system)
            (logs / 'u-sources.txt').write_text(src['text'] + '\n')
        else:
            (logs / 'u-sources.txt').write_text('(U was never asked anything: S ended before any question)\n')
    except RuntimeError as error:
        status['error'] = str(error)
    (logs / 'status.json').write_text(json.dumps(status, indent=2) + '\n')
    log(sid, f'END {json.dumps(status)}')
    return 0 if status['error'] is None else 1


def cmd_audit(sid):
    d = design()
    logs = BASE / 'logs' / sid
    if not (logs / 'status.json').is_file():
        print(f'STOP: {sid} has no finished run (no {logs}/status.json)')
        return 1
    folder = BASE / 'audit' / sid
    if folder.exists():
        shutil.move(str(folder), str(folder) + time.strftime('.%H%M%S'))
    (folder / 'S-final-files').mkdir(parents=True)
    for f in sorted(logs.glob('[0-9][0-9]-S.jsonl')):
        shutil.copyfile(f, folder / f'S-turn-{f.name}')
    for f in sorted(logs.glob('[0-9][0-9]-U.jsonl')):
        shutil.copyfile(f, folder / f'U-turn-{f.name}')
    for f in sorted(logs.glob('[0-9][0-9]-S.argv.json')):
        shutil.copyfile(f, folder / f'S-flags-{f.name}')
    for f in ('s-settings.json', 's-mcp.json', 'driver.log'):
        if (logs / f).is_file():
            shutil.copyfile(logs / f, folder / ('S-' + f if f.startswith('s-') else f))
    ws = PROJECT / 'runs' / sid / 'ws'
    for f in sorted(ws.rglob('*')):
        if f.is_file():
            dest = folder / 'S-final-files' / f.relative_to(ws)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, dest)
    shutil.copyfile(DESIGN, folder / 'design.md')
    inputs = sorted(str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_file())
    (logs / 'audit-inputs.txt').write_text('\n'.join(inputs) + '\n')
    log(sid, f'audit folder {folder}: {inputs}')
    try:
        info = turn('A', effort_of('A') or 'medium', sid, 90, d['A'], folder)
    except RuntimeError as error:
        log(sid, f'AUDIT FAILED: {error}')
        return 1
    (logs / 'audit.md').write_text(info['text'] + '\n')
    log(sid, f'audit.md first line: {info["text"].strip().splitlines()[0] if info["text"].strip() else "(empty)"}')
    return 0


def cmd_collect(sid, dest):
    logs = BASE / 'logs' / sid
    if not logs.is_dir():
        print(f'{sid}: no logs ({logs})')
        return 1
    out = Path(dest) / sid
    if out.exists():
        shutil.move(str(out), str(out) + time.strftime('.%H%M%S'))
    shutil.copytree(logs, out / 'logs')
    ws = PROJECT / 'runs' / sid / 'ws'
    if ws.is_dir():
        shutil.copytree(ws, out / 'S-final-files')
    print(f'\n### {sid}: copied {logs} and {ws} -> {out}')
    status = json.loads((logs / 'status.json').read_text()) if (logs / 'status.json').is_file() else None
    print(f'status: {status}')
    # K0a: the order of S's first describe, first edit and first question, over all S turns in order.
    first = {'describe': None, 'edit': None}
    turns = sorted(logs.glob('[0-9][0-9]-S.jsonl'))
    outside = []
    mdir_rules = (logs / 's-settings.json').read_text() if (logs / 's-settings.json').is_file() else ''
    ws_r = str(ws.resolve()) if ws.exists() else str(ws)
    question_turn = None
    for t in turns:
        info = parse(t)
        for k, c in enumerate(info['calls']):
            pos = f'{t.name} call #{k + 1}'
            if first['describe'] is None and c['name'] == 'mcp__graphtraj__tasks' \
                    and (c['input'] or {}).get('feature') == 'concept-clarification':
                first['describe'] = pos
            if first['edit'] is None and c['name'] in EDIT_TOOLS:
                first['edit'] = pos
            for key in ('file_path', 'path', 'notebook_path'):
                p = (c['input'] or {}).get(key)
                if isinstance(p, str) and p.startswith('/'):
                    rp = os.path.realpath(p)
                    if not (rp == ws_r or rp.startswith(ws_r + '/')):
                        tag = 'the guide (allowed)' if '/manuals/concept-clarification/' in rp else 'OUTSIDE ws'
                        outside.append(f'{pos} {c["name"]} {p} -> {tag} '
                                       f'(result error: {info["results"].get(c["id"], {}).get("is_error")})')
            if c['name'] not in ('Read', 'Edit', 'Write', 'Glob', 'Grep', 'MultiEdit', 'mcp__graphtraj__tasks'):
                outside.append(f'{pos} unexpected tool {c["name"]} input {json.dumps(c["input"])[:200]}')
        if question_turn is None and info['text'] is not None and not done(info['text']):
            question_turn = f'{t.name} (end of that turn, its final text went to U)'
    print(f'K0a: first tasks describe concept-clarification: {first["describe"] or "NONE"} | first Edit/Write: '
          f'{first["edit"] or "none"} | first question to the user: {question_turn or "none (no turn ended without DONE)"}')
    print('K0b supporting list, S tool calls with a path outside its ws: ' + ('none' if not outside else ''))
    for row in outside:
        print('  ' + row)
    audit = logs / 'audit.md'
    first_line = audit.read_text().strip().splitlines()[0] if audit.is_file() and audit.read_text().strip() else None
    print(f'audit.md first line: {first_line or "(no audit.md: run step A first)"}')
    return 0


def main(argv_):
    if argv_[:1] == ['ready'] and len(argv_) == 3:
        return cmd_ready(argv_[1], argv_[2])
    if argv_[:1] == ['run'] and len(argv_) == 2 and argv_[1] in SCENARIOS:
        return cmd_run(argv_[1])
    if argv_[:1] == ['audit'] and len(argv_) == 2 and argv_[1] in SCENARIOS:
        return cmd_audit(argv_[1])
    if argv_[:1] == ['collect'] and len(argv_) == 3:
        return cmd_collect(argv_[1], argv_[2])
    if argv_[:1] == ['texts']:  # rehearsal check of the design parse; prints names only, never hidden text
        d = design()
        for sid, s in d['scenarios'].items():
            print(sid, sorted(s['files']), 'CONTEXT copy' if s['copy_context'] else '', f'opening {len(s["opening"])} chars',
                  f'hidden {len(s["hidden"])} chars')
        print('S instruction lines', len(d['S'].splitlines()), '| U', len(d['U'].splitlines()), '| A',
              len(d['A'].splitlines()), '| sources question', len(d['sources']), 'chars')
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
