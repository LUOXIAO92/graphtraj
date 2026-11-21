"""REHEARSAL ONLY: a stand-in for `claude -p --output-format stream-json` (rehearse.zsh puts it first on PATH).

What it replaces: the model and Claude Code's permission enforcement. It writes an init record (model from --model,
tools from --tools plus the MCP server's tools minus --disallowedTools, apiKeySource 'stub'), scripted tool calls, and
a result record; --resume continues the same session id (state in STUB550_STATE).
What stays real: S's `tasks describe concept-clarification` is a real tools/call to the MCP server named in
--mcp-config (production graphtraj-mcp), S's Read of manual_ref and of its ws files read the real files, S's Edit
writes its ws file, the auditor's Read reads its audit folder. The canary Read is NOT attempted: the stub reports the
refusal real Claude Code should give, so probe (b) here proves only the parsing, not the deny rule.
"""
import json, os, sys, uuid, subprocess
from pathlib import Path


def opt(args, name, default=None):
    return args[args.index(name) + 1] if name in args else default


def main(args):
    if '--version' in args:
        print('2.1.999 (stub claude for verify-550 rehearsal)')
        return 0
    model, resume = opt(args, '--model', 'unknown'), opt(args, '--resume')
    sid = resume or str(uuid.uuid4())
    state = Path(os.environ.get('STUB550_STATE', '/tmp')) / f'{sid}.json'
    turns = json.loads(state.read_text())['turns'] if state.is_file() else 0
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({'turns': turns + 1, 'model': model}))
    prompt = sys.stdin.read()
    tools = [t for t in (opt(args, '--tools', '') or '').split(',') if t]
    mcp = json.loads(Path(opt(args, '--mcp-config')).read_text()) if opt(args, '--mcp-config', '').endswith('.json') else {}
    server = (mcp.get('mcpServers') or {}).get('graphtraj')
    if server:
        tools += ['mcp__graphtraj__agents', 'mcp__graphtraj__tasks']
    disallowed = (opt(args, '--disallowedTools', '') or '').split(',')
    tools = [t for t in tools if t not in disallowed]
    out = []
    emit = lambda d: out.append(d)
    emit({'type': 'system', 'subtype': 'init', 'session_id': sid, 'model': model, 'tools': tools,
          'apiKeySource': 'stub', 'cwd': os.getcwd()})
    n = [0]

    def call(name, inp, result, is_error=False):
        n[0] += 1
        tid = f'toolu_stub_{n[0]}'
        emit({'type': 'assistant', 'session_id': sid, 'message': {'content': [
            {'type': 'tool_use', 'id': tid, 'name': name, 'input': inp}]}})
        emit({'type': 'user', 'session_id': sid, 'message': {'content': [
            {'type': 'tool_result', 'tool_use_id': tid, 'is_error': is_error, 'content': result}]}})
        return result

    def describe():
        msgs = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18',
                 'capabilities': {}, 'clientInfo': {'name': 'stub', 'version': '0'}}},
                {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'tasks', 'arguments': {
                    'action': 'describe', 'feature': 'concept-clarification'}}}]
        res = subprocess.run([server['command'], *server.get('args', [])], capture_output=True, text=True,
                             input=''.join(json.dumps(m) + '\n' for m in msgs), timeout=120).stdout
        doc = next(json.loads(l) for l in res.splitlines() if json.loads(l).get('id') == 2)['result']
        text = doc['content'][0]['text']
        call('mcp__graphtraj__tasks', {'action': 'describe', 'feature': 'concept-clarification'}, text)
        return (doc.get('structuredContent') or {}).get('manual_ref')

    def read(path):
        p = Path(path)
        return call('Read', {'file_path': str(p)}, p.read_text(errors='replace'))

    if 'haiku' in model:
        if 'READY-550-S' in prompt:
            ref = describe()
            guide = read(ref)
            heading = next((l for l in guide.splitlines() if l.startswith('#')), '')
            canary = next(w for w in prompt.split() if w.endswith('canary.txt.') or w.endswith('canary.txt')).rstrip('.')
            call('Read', {'file_path': canary}, f'Permission to read {canary} has been denied. (stub)', True)
            text = f'GUIDE: {heading}\nCANARY: REFUSED\nREADY-550-S {model} logged in (stub)'
        elif turns == 0:
            ref = describe()
            read(ref)
            files = sorted(p for p in Path.cwd().iterdir() if p.is_file())
            for f in files:
                read(f)
            text = f'I read {", ".join(f.name for f in files)}. Which meaning should the key term have here? (stub question)'
        else:
            target = sorted(p for p in Path.cwd().iterdir() if p.suffix == '.md' and p.name != 'CONTEXT.md')[0]
            new = target.read_text() + f'\n<!-- stub edit after the user said: {prompt[:60]!r} -->\n'
            call('Edit', {'file_path': str(target), 'old_string': '', 'new_string': '(stub)'}, 'ok')
            target.write_text(new)
            text = 'Updated the file with the agreed meaning. (stub)\nDONE'
    elif 'fable' in model:
        if 'READY-550-U' in prompt:
            text = f'READY-550-U {model} logged in (stub)'
        elif 'List the sources' in prompt:
            text = 'none (stub)'
        else:
            has_hidden = 'HIDDEN FACTS:' in (opt(args, '--append-system-prompt', '') or '')
            text = f'Stub user reply (U instruction with hidden block present: {has_hidden}).'
    else:
        if 'READY-550-A' in prompt:
            text = f'READY-550-A {model} logged in (stub)'
        else:
            for f in sorted(Path.cwd().glob('S-turn-*.jsonl'))[:1]:
                read(f)
            text = ('AUDIT: CLEAN\n(1) none found (stub)\n(2) none found (stub)\n(3) none found (stub)\n'
                    '(4) none found (stub)\n(5) none found (stub)')
    emit({'type': 'assistant', 'session_id': sid, 'message': {'content': [{'type': 'text', 'text': text}]}})
    emit({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': text, 'session_id': sid})
    for d in out:
        print(json.dumps(d), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
