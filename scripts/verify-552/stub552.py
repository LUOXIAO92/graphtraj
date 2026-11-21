"""REHEARSAL ONLY: stand-ins for `claude`, `codex`, `dsh` and `sandbox-exec` (rehearse.zsh puts wrappers first on PATH).

  python -I stub552.py <claude|codex|dsh|sandbox-exec> <the host's own argv...>

Replaced: every model, Claude Code's and Codex's permission enforcement, Codex's Seatbelt (`codex sandbox`) and the
outer `sandbox-exec` around dsh (the stub just runs the command: nested Seatbelt is refused inside the Engineer's
sandbox). Refusals of out-of-workspace reads, `ls`, `curl` and web search are the STUB's texts, not enforcement.
Real: S's `tasks describe concept-clarification` is a real tools/call to the MCP server the host was configured with
(claude: --mcp-config file; codex: -c mcp_servers.graphtraj.command; dsh: the patch's mcp-graphtraj row, i.e. the
tasks-only relay in front of the production graphtraj-mcp), the Reads of the guide and ws files, S's edits of its
ws file, the codex rollout file written under V552_CODEX_SESSIONS, the DSH session log (zstd) under DSH_HOME whose
request/header.tools is the tools/list answer of that same relay plus DSH's file tools.
"""
import json, os, re, subprocess, sys, uuid, time
from pathlib import Path

STATE = Path(os.environ.get('STUB552_STATE', '/tmp/stub552'))


def opt(args, name, default=None):
    return args[args.index(name) + 1] if name in args else default


def rpc(command, calls):
    msgs = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18',
             'capabilities': {}, 'clientInfo': {'name': 'stub552', 'version': '0'}}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'}]
    msgs += [dict(m, jsonrpc='2.0', id=10 + i) for i, m in enumerate(calls)]
    out = subprocess.run(command, capture_output=True, text=True, timeout=120,
                         input=''.join(json.dumps(m) + '\n' for m in msgs)).stdout
    by_id = {}
    for line in out.splitlines():
        try:
            d = json.loads(line)
            by_id[d.get('id')] = d
        except ValueError:
            pass
    return [by_id.get(10 + i, {}) for i in range(len(calls))]


DESCRIBE = {'method': 'tools/call', 'params': {'name': 'tasks', 'arguments': {
    'action': 'describe', 'feature': 'concept-clarification'}}}


def describe(command):
    res = rpc(command, [DESCRIBE])[0].get('result') or {}
    return res['content'][0]['text'], (res.get('structuredContent') or {}).get('manual_ref')


def session(sid):
    f = STATE / f'{sid}.json'
    n = json.loads(f.read_text())['turns'] if f.is_file() else 0
    STATE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({'turns': n + 1}))
    return n


def probe_targets(prompt):
    paths = re.findall(r'(?:Read the file|List the directory|on its own: cat|on its own: ls) (\S+?)\.?$', prompt, re.M)
    return paths


def s_behaviour(prompt, turn, command, call, model, shell=False):
    """Shared S script: returns the final text; `call(name, input, result, is_error)` records tool calls."""
    if 'scripted isolation probe' in prompt:
        text, ref = describe(command)
        call('describe', {'action': 'describe', 'feature': 'concept-clarification'}, text, False)
        guide = Path(ref).read_text()
        call('read', {'file_path': ref}, guide, False)
        for p in probe_targets(prompt):
            call('read', {'file_path': p}, f'Permission to read {p} denied. (stub)', True)
        call('agents', {'action': 'discover'}, 'Unknown tool: agents (stub)', True)
        if shell:
            call('curl', {'command': 'curl -sS -m 10 https://example.com'},
                 'curl: (6) Could not resolve host: example.com (stub)', True)
        heading = next((l for l in guide.splitlines() if l.startswith('#')), '')
        tag = re.search(r'(READY-552-S-\w+)', prompt).group(1)
        return (f'GUIDE: {heading}\nCANARY-U: REFUSED\nCANARY-SIBLING: REFUSED\nDESIGN: REFUSED\nLISTING: REFUSED\n'
                f'AGENTS: UNAVAILABLE\nWEB: UNAVAILABLE\n' + ('CURL: failed\n' if shell else '')
                + f'TOOLS: (stub)\n{tag} {model} logged in (stub)')
    ws = Path.cwd()
    if turn == 0:
        text, ref = describe(command)
        call('describe', {'action': 'describe', 'feature': 'concept-clarification'}, text, False)
        call('read', {'file_path': ref}, Path(ref).read_text(), False)
        files = sorted(p for p in ws.iterdir() if p.is_file())
        for f in files:
            call('read', {'file_path': str(f)}, f.read_text(), False)
        return f'I read {", ".join(f.name for f in files)}. Which meaning should the key term have here? (stub question)'
    target = sorted(p for p in ws.iterdir() if p.suffix == '.md' and p.name != 'CONTEXT.md')[0]
    target.write_text(target.read_text() + f'\n<!-- stub edit after the user said: {prompt[:60]!r} -->\n')
    call('edit', {'file_path': str(target)}, 'ok', False)
    return 'Updated the file with the agreed meaning. (stub)\nDONE'


# ---------------------------------------------------------------- claude
def claude(args):
    if '--version' in args:
        print('2.1.999 (stub claude for verify-552 rehearsal)')
        return 0
    model = opt(args, '--model', 'unknown')
    sid = opt(args, '--resume') or str(uuid.uuid4())
    turn = session(sid)
    prompt = sys.stdin.read()
    tools = [t for t in (opt(args, '--tools', '') or '').split(',') if t]
    mcpf = opt(args, '--mcp-config', '')
    server = (json.loads(Path(mcpf).read_text()).get('mcpServers') or {}).get('graphtraj') if mcpf.endswith('.json') else None
    if server:
        tools += ['mcp__graphtraj__agents', 'mcp__graphtraj__tasks']
    tools = [t for t in tools if t not in (opt(args, '--disallowedTools', '') or '').split(',')]
    out = [{'type': 'system', 'subtype': 'init', 'session_id': sid, 'model': model, 'tools': tools,
            'apiKeySource': 'stub', 'cwd': os.getcwd()}]
    n = [0]
    names = {'describe': 'mcp__graphtraj__tasks', 'read': 'Read', 'edit': 'Edit', 'agents': 'mcp__graphtraj__agents'}

    def call(name, inp, result, is_error):
        n[0] += 1
        tid = f'toolu_stub_{n[0]}'
        out.append({'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': tid,
                    'name': names.get(name, name), 'input': inp}]}})
        out.append({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': tid,
                    'is_error': is_error, 'content': result}]}})

    usage = {}
    if server:
        text = s_behaviour(prompt, turn, [server['command'], *server.get('args', [])], call, model)
    elif 'READY-552-' in prompt:
        text = f'{re.search(r"(READY-552-[UA])", prompt).group(1)} {model} logged in (stub)'
    elif 'You will play the expert user' in prompt:
        text = 'Notes (stub research): terms used as in the hidden facts.\nSources: none (stub)'
        usage = {'server_tool_use': {'web_search_requests': 0}}
    elif 'You audit a test run' in prompt:
        for f in sorted(Path.cwd().glob('S-turn-*'))[:1]:
            call('read', {'file_path': str(f)}, f.read_text()[:200], False)
        text = 'AUDIT: CLEAN\n' + '\n'.join(f'({k}) none found (stub)' for k in range(1, 6))
    elif 'The conversation has ended' in prompt:
        text = 'none (stub)'
    else:
        sysp = opt(args, '--append-system-prompt', '') or ''
        text = (f'Stub user reply (HIDDEN FACTS present: {"HIDDEN FACTS:" in sysp}; RESEARCH NOTES present: '
                f'{"RESEARCH NOTES:" in sysp}).')
    out.append({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': text}]}})
    out.append({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': text, 'session_id': sid,
                'usage': usage})
    for d in out:
        print(json.dumps(d), flush=True)
    return 0


# ---------------------------------------------------------------- codex
def codex(args):
    if '--version' in args:
        print('codex-cli 0.171.0 (stub for verify-552 rehearsal)')
        return 0
    if args[:2] == ['login', 'status']:
        print('Logged in (stub)')
        return 0
    if args[:1] == ['sandbox']:
        # Stub model of Codex 0.171's lowering of the s552 profile (not the real Seatbelt): readable = entries with
        # read/write, platform dirs, and, because of `:minimal`, the scratch roots /private/tmp and /private/var/tmp
        # (seatbelt_scratch.rs) minus every `deny` entry (and its subtree).
        cmd = args[args.index('--') + 1:]
        perms = ' '.join(args[i + 1] for i, a in enumerate(args) if a == '-c' and args[i + 1].startswith('permissions='))
        entries = re.findall(r'"([^"]+)"="(read|write|deny)"', perms)
        under = lambda p, root: p == root or p.startswith(root.rstrip('/') + '/')
        denied = lambda p: any(under(p, e) for e, m in entries if m == 'deny')
        explicit = lambda p, modes: any(under(p, e) for e, m in entries if m in modes)
        scratch = lambda p: ('":minimal"' in perms) and any(under(p, s) for s in ('/private/tmp', '/private/var/tmp'))
        readable = lambda p: explicit(p, ('read', 'write')) or (scratch(p) and not denied(p)) or \
            any(under(p, s) for s in ('/bin', '/usr', '/etc', '/private/etc'))
        writable = lambda p: explicit(p, ('write',)) or (scratch(p) and not denied(p))
        if 'curl' in cmd[0]:
            print('curl: (6) Could not resolve host: example.com (stub)', file=sys.stderr)
            return 6
        text = ' '.join(cmd[1:])
        paths = [os.path.realpath(t.strip(';&')) for t in re.findall(r'(/[^\s;&>]+)', text)]
        target = re.search(r'>\s*(/\S+)', text)
        if target and not writable(os.path.realpath(target.group(1))):
            print(f'sh: {target.group(1)}: Operation not permitted (stub)', file=sys.stderr)
            return 1
        bad = [p for p in paths if not readable(p) and not (target and p == os.path.realpath(target.group(1)))]
        if bad:
            print(f'{cmd[0]}: {bad[0]}: Operation not permitted (stub)', file=sys.stderr)
            return 1
        return subprocess.run(cmd).returncode
    resume = args[1] == 'resume'
    flags = args[2:] if resume else args[1:]
    tid = flags[-2] if resume else str(uuid.uuid4())
    turn = session(tid)
    prompt = sys.stdin.read()
    cfg = ' '.join(flags[i + 1] for i, a in enumerate(flags) if a == '-c')
    command = re.search(r'graphtraj=\{command=("[^"]+")', cfg)
    command = [json.loads(command.group(1))] if command else None
    events = [{'type': 'thread.started', 'thread_id': tid}, {'type': 'turn.started'}]
    k = [0]

    def call(name, inp, result, is_error):
        k[0] += 1
        if name == 'describe':
            item = {'id': f'item_{k[0]}', 'type': 'mcp_tool_call', 'server': 'graphtraj', 'tool': 'tasks',
                    'arguments': inp, 'result': {'content': [{'type': 'text', 'text': result}]}, 'status': 'completed'}
        elif name == 'agents':
            item = {'id': f'item_{k[0]}', 'type': 'mcp_tool_call', 'server': 'graphtraj', 'tool': 'agents',
                    'arguments': inp, 'error': {'message': result}, 'status': 'failed'}
        elif name == 'edit':
            item = {'id': f'item_{k[0]}', 'type': 'file_change', 'changes': [{'path': inp['file_path'], 'kind': 'update'}],
                    'status': 'completed'}
        else:
            cmd = inp.get('command') or f"cat {inp['file_path']}"
            item = {'id': f'item_{k[0]}', 'type': 'command_execution', 'command': f"/bin/zsh -c '{cmd}'",
                    'aggregated_output': result, 'exit_code': 1 if is_error else 0,
                    'status': 'failed' if is_error else 'completed'}
        events.append({'type': 'item.completed', 'item': item})

    text = s_behaviour(prompt, turn, command, call, 'gpt-6-luna', shell=True)
    events.append({'type': 'item.completed', 'item': {'id': 'msg', 'type': 'agent_message', 'text': text}})
    events.append({'type': 'turn.completed', 'usage': {}})
    Path(opt(flags, '-o')).write_text(text)
    sessions = STATE.parent / 'codex-sessions' / time.strftime('%Y/%m/%d')   # rehearse.zsh's fake ~/.codex/sessions
    sessions.mkdir(parents=True, exist_ok=True)
    with open(sessions / f'rollout-{time.strftime("%Y-%m-%dT%H-%M-%S")}-{tid}.jsonl', 'a') as f:
        f.write(json.dumps({'type': 'turn_context', 'payload': {'model': 'gpt-6-luna', 'effort': 'high',
                                                                 'cwd': os.getcwd(), 'permission_profile': {
                                                                     'network': 'restricted (stub)'}}}) + '\n')
    for e in events:
        print(json.dumps(e), flush=True)
    return 0


# ---------------------------------------------------------------- dsh
def dsh(args):
    if '--version' in args:
        print('0.2.2-alpha.2 (stub for verify-552 rehearsal)')
        return 0
    if '--dump-config' in args:
        print('# stub dsh --dump-config')
        return 0
    patch = Path(opt(args, '--patch')).read_text()
    command = [json.loads(re.search(r'command: (".*")', patch).group(1)), *json.loads(re.search(r'args: (\[.*\])', patch).group(1))]
    sid = opt(args, '--session-id') or f'session-{uuid.uuid4()}'
    turn = session(sid)
    prompt = sys.stdin.read()
    events = [{'type': 'session', 'sessionId': sid, 'cwd': os.getcwd()}]
    k = [0]
    names = {'describe': 'mcp__graphtraj__tasks', 'agents': 'mcp__graphtraj__agents'}

    def call(name, inp, result, is_error):
        k[0] += 1
        events.append({'type': 'tool_call', 'callId': f'c{k[0]}', 'tool': names.get(name, name), 'input': inp})
        events.append({'type': 'tool_result', 'callId': f'c{k[0]}', 'status': 'error' if is_error else 'completed',
                       'result': result})

    text = s_behaviour(prompt, turn, command, call, 'deepseek-flash')
    listed = rpc(command, [{'method': 'tools/list', 'params': {}}])[0].get('result', {}).get('tools', [])
    tools = sorted(['edit', 'glob', 'grep', 'read', 'write', 'todo_write'] + [f'mcp__graphtraj__{t["name"]}' for t in listed])
    store = Path(os.environ['DSH_HOME']) / 'sessions' / 'stub' / sid
    store.mkdir(parents=True, exist_ok=True)
    header = {'type': 'request/header', 'seq': turn, 'data': {'header': {'tools': tools, 'config': {
        'provider': 'deepseek-official', 'model': 'deepseek-flash', 'reasoningEffort': 'high'}}}}
    raw = store / 'session.v4.jsonl'
    with open(raw, 'a') as f:
        f.write(json.dumps(header) + '\n')
    subprocess.run(['zstd', '-q', '-f', str(raw), '-o', str(store / 'session.v4.jsonl.zstd')], check=True)
    events.append({'type': 'final', 'sessionId': sid, 'reason': {'kind': 'completed'}, 'text': text})
    for e in events:
        print(json.dumps(e), flush=True)
    return 0


def sandbox_exec(args):
    """`sandbox-exec -f <profile> cmd...`: NOT Seatbelt. For /bin/cat and /bin/ls only, the stub evaluates the
    profile's (deny|allow file-read*/file-read-data ... (subpath ...)) rules in order, the last match deciding
    (the SBPL rule this design assumes; Main's 00 dsh-sandbox check proves it for real). Every other command
    (dsh, node, pwd) runs unconfined."""
    # Precedence modelled on Main's real run of 3356b581 (Leader correction 2): a rule that names the operation
    # (file-read-data) decides before any `file-read*` wildcard rule; within each kind the last match wins.
    prof, cmd = Path(args[1]).read_text(), args[2:]
    trap = STATE / 'abort-if-denied'   # bisection self-test only: abort dsh when this path is denied by file-read*
    if Path(cmd[0]).name == 'dsh' and trap.is_file() and \
            f'(subpath "{trap.read_text().strip()}")' in ''.join(l for l in prof.splitlines() if l.startswith('(deny file-read*')):
        os.abort()
    if Path(cmd[0]).name in ('cat', 'ls', 'pwd') or (Path(cmd[0]).name == 'dsh' and '--patch' in cmd):
        rules =[(m.group(1), m.group(2).split(), re.findall(r'\(subpath "([^"]+)"\)', m.group(3)))
                 for m in re.finditer(r'^\((deny|allow) ((?:file-read[\w*-]*\s*)+)(.*)\)$', prof, re.M)]
        name = Path(cmd[0]).name
        targets = [os.getcwd()] if name == 'pwd' else ([cmd[cmd.index('--patch') + 1]] if name == 'dsh' else cmd[1:])
        for p in targets:
            rp = os.path.realpath(p)
            hit = lambda r: any(rp == s or rp.startswith(s.rstrip('/') + '/') for s in r[2])
            specific = [r[0] for r in rules if 'file-read-data' in r[1] and hit(r)]
            wildcard = [r[0] for r in rules if 'file-read*' in r[1] and hit(r)]
            verdict = specific[-1] if specific else (wildcard[-1] if wildcard else 'allow')
            if verdict == 'deny':
                print(f'{Path(cmd[0]).name}: {p}: Operation not permitted (stub)', file=sys.stderr)
                return 1
    return subprocess.run(cmd).returncode


if __name__ == '__main__':
    host, rest = sys.argv[1], sys.argv[2:]
    sys.exit({'claude': claude, 'codex': codex, 'dsh': dsh, 'sandbox-exec': sandbox_exec}[host](rest))
