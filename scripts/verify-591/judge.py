"""Task 591 verdicts from the hosts' own records (run with python3 -I; stdlib only).

usage:
  judge.py snap <data root>                                   record ids now under <root>/control/agents
  judge.py claude <stream.jsonl> <root> <snap> <tool> <host> <word> <child runtime>
      a real `claude -p --output-format stream-json --verbose` Main: the init tool list, the tool calls it made,
      their results, and the one new child record under <root>
  judge.py pi <session dir> <output> <root> <snap> <tool> <host> <word> <child runtime>
      a real Pi Main: the offered tool set replayed from the Session file's system messages (toolsAdded and
      toolsRemoved, Pi's documented session format), the tool calls, their results, and the one new child record
  judge.py cli <venv>                                         the installed console scripts of the candidate

Every verdict line starts PASS or FAIL; the exit status is 0 only when every line is PASS. An old tool name is any
name `agents` or `mcp__<anything>__agents`.
"""
import json, re, subprocess, sys
from pathlib import Path

OLD = re.compile(r'^(?:agents|mcp__.+__agents)$')
FAILED = []


def check(ok, message):
    print(('PASS: ' if ok else 'FAIL: ') + message)
    if not ok:
        FAILED.append(message)


def records(root):
    found = {}
    for path in sorted((Path(root) / 'control' / 'agents').glob('*.json')):
        try:
            found[path.stem] = json.loads(path.read_text())
        except (OSError, ValueError):
            found[path.stem] = {}
    return found


def child(root, snap, host, word, texts, runtime):
    """The one new record: created by ``host``, a ``runtime`` child, completed with ``word``; the tool results name it."""
    before = set(Path(snap).read_text().split()) if Path(snap).is_file() else set()
    new = {a: r for a, r in records(root).items() if a not in before}
    owners = {a: ((r.get('creator') or {}).get('host'), r.get('runtime')) for a, r in new.items()}
    check(len(new) == 1, f'exactly one new child record under {root}/control/agents: {owners}')
    for agent, record in new.items():
        check((record.get('creator') or {}).get('host') == host, f'{agent} was created by host {host}: {owners[agent]}')
        check(record.get('runtime') == runtime, f'{agent} is a {runtime} child: runtime {record.get("runtime")!r}')
        last = (record.get('executions') or [{}])[-1]
        message = last.get('last_message') or ''
        check(last.get('outcome') == 'completed' and word in message.lower(),
              f'{agent} completed with {word!r}: outcome {last.get("outcome")}, error '
              f'{(last.get("error") or {}).get("code")}, last_message {message[:80]!r}')
        check(any(agent in t for t in texts), f'a tool result of the Main names {agent}')
        print(f'follow-up (paste): python3 -m json.tool {Path(root) / "control" / "agents" / (agent + ".json")}')
    return list(new)


def calls_and_results(calls, results, tool):
    """``calls``: tool names the Main called; ``results``: (name, is_error, text) for the new tool's results."""
    print(f'tool calls made by the Main: {calls}')
    check(calls.count(tool) >= 2, f'the Main called {tool} at least twice (create, wait): {calls.count(tool)}')
    old = [c for c in calls if OLD.match(c)]
    check(not old, f'the Main called no old tool name: {old}')
    errors = [t[:200] for name, error, t in results if name == tool and error]
    check(not errors, f'no {tool} result is an error: {errors}')
    for name, error, text in results:
        print(f'  result of {name} (error {error}): {text[:240]!r}')


def tools_verdict(label, tools, tool):
    old = sorted(t for t in tools if OLD.match(t))
    print(f'{label} ({len(tools)}): {sorted(tools)}')
    check(tool in tools, f'{label} has {tool}')
    check(not old, f'{label} has no old name (agents or mcp__*__agents): {old}')


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ' '.join(text_of(c.get('text') if isinstance(c, dict) and 'text' in c else
                                c.get('content') if isinstance(c, dict) else c) for c in content)
    return '' if content is None else str(content)


def claude(stream, root, snap, tool, host, word, runtime):
    init, calls, ids, results, final = None, [], {}, [], None
    for raw in open(stream, errors='replace'):
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        if e.get('type') == 'system' and e.get('subtype') == 'init' and init is None:
            init = e
        message = e.get('message') if isinstance(e.get('message'), dict) else {}
        for block in message.get('content') or [] if isinstance(message.get('content'), list) else []:
            if not isinstance(block, dict):
                continue
            if block.get('type') == 'tool_use':
                calls.append(block.get('name'))
                ids[block.get('id')] = block.get('name')
            if block.get('type') == 'tool_result':
                results.append((ids.get(block.get('tool_use_id')), bool(block.get('is_error')),
                                text_of(block.get('content'))))
        if e.get('type') == 'result':
            final = e
    check(init is not None, f'{stream} has the init record')
    init = init or {}
    servers = [(s.get('name'), s.get('status')) for s in init.get('mcp_servers') or []]
    print(f'Main init: model {init.get("model")} | session {init.get("session_id")} | mcp servers {servers}')
    print(f'plugins: {[p.get("name") if isinstance(p, dict) else p for p in init.get("plugins") or []]}')
    tools = set(init.get('tools') or [])
    tools_verdict('the init tool list', tools, tool)
    server = tool.split('__')[1] if tool.count('__') >= 2 else ''
    listed = dict(servers)
    names = [n for n in listed if n.replace(':', '_') == server or n == server]
    check(any(listed[n] == 'connected' for n in names), f'the MCP server of {tool} is connected: {servers}')
    others = [(n, st) for n, st in servers if n not in names]
    print(f'every other MCP server in the init record (name: status): '
          f'{", ".join(f"{n}: {st}" for n, st in others) or "none"}')
    for n, _ in others:
        prefix = 'mcp__' + ''.join(c if c.isalnum() or c in '_-' else '_' for c in n) + '__'
        print(f'  {n}: tools {sorted(t for t in tools if t.startswith(prefix))}')
    calls_and_results(calls, results, tool)
    print(f'Main result: {str((final or {}).get("result"))[:400]!r}')
    check(final is not None and not final.get('is_error'), 'the Main ended with a result that is not an error')
    child(root, snap, host, word, [t for _, _, t in results], runtime)


def pi(sessions, output, root, snap, tool, host, word, runtime):
    files = sorted(Path(sessions).rglob('*.jsonl'))
    check(len(files) == 1, f'one Pi Session file in {sessions}: {[f.name for f in files]}')
    requests, active, calls, ids, results, providers = [], set(), [], {}, [], set()
    for f in files:
        for raw in f.read_text(errors='replace').splitlines():
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            m = e.get('message') if isinstance(e, dict) else None
            if not isinstance(m, dict):
                continue
            if m.get('role') == 'system':
                active |= {t.get('name') for t in m.get('toolsAdded') or [] if isinstance(t, dict)}
                active -= {t.get('name') for t in m.get('toolsRemoved') or [] if isinstance(t, dict)}
                requests.append(set(active))
            if m.get('role') == 'assistant':
                providers.add(m.get('provider'))
                for block in m.get('content') or []:
                    if isinstance(block, dict) and block.get('type') == 'toolCall':
                        calls.append(block.get('name'))
            if m.get('role') == 'toolResult':
                results.append((m.get('toolName'), bool(m.get('isError')), text_of(m.get('content'))))
    check(bool(requests), f'the Session file has system messages declaring the tools ({len(requests)})')
    tools_verdict('the tools Pi offered at the first request', requests[0] if requests else set(), tool)
    every = set().union(*requests) if requests else set()
    check(not [t for t in every if OLD.match(t)], 'no system message of the Session ever offered an old name')
    print(f'assistant providers: {sorted(map(str, providers))}')
    check(providers == {'deepseek'}, 'deepseek is the only provider of the Main\'s answers')
    calls_and_results(calls, results, tool)
    text = Path(output).read_text(errors='replace')
    check('Extension error' not in text, 'no Extension error in the Main\'s output')
    raw = ''.join(f.read_text(errors='replace') for f in files)
    print(f'notice labels in the Session file: [subagents notice from: {raw.count("[subagents notice from")} '
          '(informational; a notice need not arrive in -p mode)')
    check('[agents notice from' not in raw, 'no old label [agents notice from in the Session file')
    child(root, snap, host, word, [t for _, _, t in results], runtime)


def cli(venv):
    bin_ = Path(venv) / 'bin'
    have = {n: (bin_ / n).exists() for n in ('subagents', 'subagents-mcp', 'agents', 'agents-mcp')}
    print(f'console scripts in {bin_}: {have}')
    check(have['subagents'] and have['subagents-mcp'], 'subagents and subagents-mcp are installed')
    check(not have['agents'] and not have['agents-mcp'], 'agents and agents-mcp are not installed')
    meta = subprocess.run([str(bin_ / 'python'), '-I', '-c', 'import importlib.metadata as m; print(" ".join(sorted('
                           'f"{e.name}={e.value}" for e in m.distribution("graftling").entry_points '
                           'if e.group == "console_scripts")))'], capture_output=True, text=True)
    print(f'graftling console_scripts metadata: {meta.stdout.strip()}')
    check(meta.stdout.split() == ['subagents-mcp=graftling.mcp:main', 'subagents=graftling.cli:main'],
          'the metadata declares exactly subagents=graftling.cli:main and subagents-mcp=graftling.mcp:main')
    if not have['subagents'] or not have['subagents-mcp']:
        return
    run = subprocess.run([str(bin_ / 'subagents'), '--help'], capture_output=True, text=True, timeout=60)
    print(f'subagents --help: exit {run.returncode}; {run.stdout.splitlines()[:1]}')
    check(run.returncode == 0 and run.stdout.startswith('usage: subagents '), 'subagents --help runs as subagents')
    run = subprocess.run([str(bin_ / 'subagents'), '{"action":"discover"}'], capture_output=True, text=True, timeout=60)
    print(f'subagents \'{{"action":"discover"}}\' with no host: exit {run.returncode}; {run.stdout.strip()[:200]}')
    try:
        code = (json.loads(run.stdout).get('error') or {}).get('code')
    except ValueError:
        code = None
    check(run.returncode == 1 and code == 'authority-denied',
          'without an owner connection subagents refuses with a JSON authority-denied (the documented behaviour)')
    lines = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
              'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'v591', 'version': '0'}}},
             {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
             {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'agents', 'arguments': {}}}]
    run = subprocess.run([str(bin_ / 'subagents-mcp')], input=''.join(json.dumps(x) + '\n' for x in lines),
                         capture_output=True, text=True, timeout=60)
    replies = {}
    for raw in run.stdout.splitlines():
        try:
            r = json.loads(raw)
            replies[r.get('id')] = r
        except ValueError:
            pass
    info = ((replies.get(1) or {}).get('result') or {}).get('serverInfo') or {}
    names = [t.get('name') for t in ((replies.get(2) or {}).get('result') or {}).get('tools') or []]
    old = (replies.get(3) or {}).get('error') or ((replies.get(3) or {}).get('result') or {})
    print(f'subagents-mcp: exit {run.returncode}; serverInfo {info}; tools/list {names}; tools/call agents -> {str(old)[:160]}')
    check(info.get('name') == 'subagents', 'subagents-mcp names itself subagents')
    check(names == ['subagents'], 'subagents-mcp lists exactly the tool subagents')
    check('Unknown tool' in str(old), 'subagents-mcp refuses a call of the old name agents as an unknown tool')


def main(argv):
    if argv[:1] == ['snap'] and len(argv) == 2:
        print('\n'.join(records(argv[1])))
        return 0
    if argv[:1] == ['claude'] and len(argv) == 8:
        claude(*argv[1:])
    elif argv[:1] == ['pi'] and len(argv) == 9:
        pi(*argv[1:])
    elif argv[:1] == ['cli'] and len(argv) == 2:
        cli(argv[1])
    else:
        print(__doc__)
        return 2
    print(f'judge: {"ALL PASS" if not FAILED else f"{len(FAILED)} FAIL"}')
    return 1 if FAILED else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
