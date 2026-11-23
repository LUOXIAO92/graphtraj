"""Task 592 verdicts from the hosts' own records (run with python3 -I; stdlib only).

usage:
  judge.py pi <session dir> <output>          a real GraphTraj Pi Main: the offered tool set replayed from the Session
                                              file's system messages (toolsAdded/toolsRemoved), the providers, and the
                                              five probe calls with their results (matched by toolCallId)
  judge.py claude <stream.jsonl>              a real GraphTraj Claude Code Main (`claude -p --output-format stream-json
                                              --verbose`): the init tool list and servers, and the same five calls
  judge.py mcp <venv> <project>               the installed graphtraj-mcp over stdio in <project> (no model, no network):
                                              tools/list, an old-name call and the same five calls
  judge.py hook <written plugin dir>          the TOOL/TOOLS lines of the hook that configuration --write wrote
  judge.py probes                             print the five probe calls (the prompt and the mcp step use these)

Every verdict line starts PASS or FAIL (NOTE lines are information); the exit status is 0 only when every verdict is
PASS. An old tool name is `agents` or `mcp__<anything>__agents`; the old gateway feature is `agents`.
"""
import json, os, re, subprocess, sys
from pathlib import Path

NEW, TASKS = 'mcp__graphtraj__subagents', 'mcp__graphtraj__tasks'
OLD = re.compile(r'^(?:agents|mcp__.+__agents)$')
# The five probe calls, in order: (label, tool, input).
PROBES = [
    ('subagents-discover', NEW, {'action': 'discover'}),
    ('subagents-status', NEW, {'action': 'execute', 'feature': 'status', 'arguments': {}}),
    ('tasks-discover', TASKS, {'action': 'discover'}),
    ('tasks-refuses-subagents', TASKS, {'action': 'execute', 'feature': 'subagents', 'arguments': {}}),
    ('tasks-no-agents-feature', TASKS, {'action': 'execute', 'feature': 'agents', 'arguments': {}}),
]
REFUSAL = 'Feature does not belong to this MCP entry.'
ROUTING = re.compile(r'unknown (?:feature|tool)|does not belong to this MCP entry', re.I)
# Two exact old forms GraphTraj itself returned at e3dc5257 (interfaces/agents.py): a FAIL (Leader decision). Any other
# old label naming the tool in a result text is printed as a NOTE.
OLD_FORMS = ('agents needs a verified caller', 'read-only agents access')
OLD_LABEL = re.compile(r'(?<![\w/.-])agents (?:needs a verified caller|needs|access|tool|host|review|notice|context)\b'
                       r'|read-only agents access')
FEATURE_LINE =re.compile(r'^\s*-?\s*feature:\s*["\']?([A-Za-z0-9_\-]+)', re.M)
FAILED = []


def check(ok, message):
    print(('PASS: ' if ok else 'FAIL: ') + message)
    if not ok:
        FAILED.append(message)


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ' '.join(text_of(c.get('text') if isinstance(c, dict) and 'text' in c else
                                c.get('content') if isinstance(c, dict) else c) for c in content)
    return '' if content is None else str(content)


def features(text):
    """Feature names a discover result lists (YAML `- feature: <name>` lines, or a JSON document)."""
    try:
        document = json.loads(text)
        return [f.get('feature') for f in document.get('features') or [] if isinstance(f, dict)]
    except (ValueError, AttributeError):
        return FEATURE_LINE.findall(text)


def tools_verdict(label, tools):
    old = sorted(t for t in tools if OLD.match(t))
    print(f'{label} ({len(tools)}): {sorted(tools)}')
    check(NEW in tools and TASKS in tools, f'{label} has {NEW} and {TASKS}')
    check(not old, f'{label} has no old name (agents or mcp__*__agents): {old}')


def same(a, b):
    """Whether a call's input is the probe's input (the model may add arguments: {} or omit it on discover)."""
    norm = lambda d: {k: v for k, v in (d or {}).items() if not (k == 'arguments' and v in ({}, None))}
    return isinstance(a, dict) and norm(a) == norm(b)


def probes_verdict(calls):
    """``calls``: (tool name, input, is_error, text) in call order. One verdict per probe."""
    print(f'tool calls made ({len(calls)}): {[(n, json.dumps(a, sort_keys=True)) for n, a, _, _ in calls]}')
    check(not [n for n, *_ in calls if OLD.match(str(n))], 'no call used an old tool name')
    texts = [t for _, _, _, t in calls]
    for form in OLD_FORMS:  # a whole word: 'subagents needs a verified caller' is the new form, not the old one
        old = re.compile(r'(?<![\w-])' + re.escape(form))
        check(not any(old.search(t) for t in texts), f'no result text says the old form {form!r} (Leader decision)')
    labels = sorted({m.group(0) for t in texts for m in OLD_LABEL.finditer(t)} - set(OLD_FORMS))
    if labels:
        print(f'NOTE: result texts still carry other old human-facing labels (information, not a verdict): {labels}')
    for label, tool, wanted in PROBES:
        got = [(e, t) for n, a, e, t in calls if n == tool and same(a, wanted)]
        if not got:
            check(False, f'{label}: no call of {tool} with {json.dumps(wanted)}')
            continue
        error, text = got[0]
        print(f'  {label}: {tool} {json.dumps(wanted)} -> error {error}: {text[:300]!r}')
        if label == 'subagents-discover':
            names = features(text)
            check(not error and {'create', 'status'} <= set(names),
                  f'{label}: a real call of {tool} answered with its features (create, status among {names})')
        elif label == 'subagents-status':
            if not error:
                check(True, f'{label}: execute status through {tool} succeeded (GraphTraj routed the subagents feature)')
            else:
                check(not ROUTING.search(text), f'{label}: the refusal is not a routing error (unknown feature or tool / '
                                                f'does not belong): {text[:200]!r}')
                print(f'NOTE: {label} was refused for another reason (shown above); the acceptance call is '
                      'subagents-discover; report this refusal.')
        elif label == 'tasks-discover':
            names = features(text)
            check(not error and 'task_graph' in names, f'{label}: tasks discover answered ({len(names)} features)')
            check('subagents' not in names and 'agents' not in names,
                  f'{label}: lists neither the feature subagents nor agents: {sorted(n for n in names if "agent" in n)}')
        elif label == 'tasks-refuses-subagents':
            check(error and REFUSAL in text, f'{label}: tasks refuses feature subagents with {REFUSAL!r}')
        elif label == 'tasks-no-agents-feature':
            check(error and 'Unknown feature: agents' in text, f'{label}: the old feature agents is unknown to tasks')


def pi(sessions, output):
    files = sorted(Path(sessions).rglob('*.jsonl'))
    check(len(files) == 1, f'one Pi Session file in {sessions}: {[f.name for f in files]}')
    requests, active, calls, results, providers = [], set(), [], {}, set()
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
                        calls.append((block.get('id'), block.get('name'), block.get('arguments')))
            if m.get('role') == 'toolResult':
                results[m.get('toolCallId')] = (bool(m.get('isError')), text_of(m.get('content')))
    check(bool(requests), f'the Session file has system messages declaring the tools ({len(requests)})')
    tools_verdict('the tools Pi offered at the first request', requests[0] if requests else set())
    every = set().union(*requests) if requests else set()
    check(not [t for t in every if OLD.match(t)], 'no system message of the Session ever offered an old name')
    print(f'assistant providers: {sorted(map(str, providers))}')
    check(providers == {'deepseek'}, "deepseek is the only provider of the Main's answers")
    probes_verdict([(n, a, *results.get(i, (True, '<no result>'))) for i, n, a in calls])
    text = Path(output).read_text(errors='replace')
    check('Extension error' not in text, "no Extension error in the Main's output")


def claude(stream):
    init, calls, results, final = None, [], {}, None
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
        for block in message.get('content') if isinstance(message.get('content'), list) else []:
            if not isinstance(block, dict):
                continue
            if block.get('type') == 'tool_use':
                calls.append((block.get('id'), block.get('name'), block.get('input')))
            if block.get('type') == 'tool_result':
                results[block.get('tool_use_id')] = (bool(block.get('is_error')), text_of(block.get('content')))
        if e.get('type') == 'result':
            final = e
    check(init is not None, f'{stream} has the init record')
    init = init or {}
    servers = [(s.get('name'), s.get('status')) for s in init.get('mcp_servers') or []]
    print(f'Main init: model {init.get("model")} | session {init.get("session_id")} | mcp servers {servers}')
    print(f'plugins: {[p.get("name") if isinstance(p, dict) else p for p in init.get("plugins") or []]}')
    tools_verdict('the init tool list (every server)', set(init.get('tools') or []))
    check(('graphtraj', 'connected') in servers, f'the graphtraj MCP server is connected: {servers}')
    check(any('graphtraj-claude-host' in str(p) for p in init.get('plugins') or []),
          'the written graphtraj-claude-host plugin is loaded')
    probes_verdict([(n, a, *results.get(i, (True, '<no result>'))) for i, n, a in calls])
    print(f'Main result: {str((final or {}).get("result"))[:400]!r}')
    check(final is not None and not final.get('is_error'), 'the Main ended with a result that is not an error')


def mcp(venv, project):
    """The installed graphtraj-mcp in the project: the same five calls, plus tools/list and an old-name call."""
    lines = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
              'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'v592', 'version': '0'}}},
             {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
             {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
             {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'agents', 'arguments': {'action': 'discover'}}}]
    lines += [{'jsonrpc': '2.0', 'id': 10 + i, 'method': 'tools/call',
               'params': {'name': tool.split('__')[-1], 'arguments': wanted}} for i, (_, tool, wanted) in enumerate(PROBES)]
    env = {k: v for k, v in os.environ.items() if not k.startswith(('GRAFTLING_', 'GRAPHTRAJ_'))}
    run = subprocess.run([str(Path(venv) / 'bin' / 'graphtraj-mcp')], input=''.join(json.dumps(x) + '\n' for x in lines),
                         capture_output=True, text=True, timeout=120, cwd=project, env=env)
    replies = {}
    for raw in run.stdout.splitlines():
        try:
            r = json.loads(raw)
            replies[r.get('id')] = r
        except ValueError:
            pass
    print(f'graphtraj-mcp in {project}: exit {run.returncode}; stderr {run.stderr.strip()[-300:]!r}')
    names = [t.get('name') for t in ((replies.get(2) or {}).get('result') or {}).get('tools') or []]
    print(f'tools/list: {names}')
    check(sorted(names) == ['subagents', 'tasks'], 'graphtraj-mcp lists exactly the tools subagents and tasks')
    old = (replies.get(3) or {}).get('error') or ((replies.get(3) or {}).get('result') or {})
    print(f'tools/call agents -> {str(old)[:200]}')
    check('Unknown tool: agents' in str(old), 'graphtraj-mcp refuses a call of the old tool name agents as unknown')
    calls = []
    for i, (_, tool, wanted) in enumerate(PROBES):
        r = (replies.get(10 + i) or {}).get('result') or {}
        text = text_of(r.get('content')) if r else str((replies.get(10 + i) or {}).get('error'))
        calls.append((tool, wanted, bool(r.get('isError', not r)), text))
    probes_verdict(calls)


def hook(plugin):
    lines = []
    for f in sorted(Path(plugin).rglob('*.mjs')):
        lines += [l.strip() for l in f.read_text(errors='replace').splitlines() if re.match(r'\s*const TOOLS? = ', l)]
    print(f'written hook TOOL/TOOLS lines under {plugin}: {lines}')
    check('const TOOL = "subagents";' in lines, 'the written hook says const TOOL = "subagents";')
    check('const TOOLS = [TOOL, "tasks"];' in lines, 'the written hook says const TOOLS = [TOOL, "tasks"];')
    check(not any('"agents"' in l for l in lines), 'no TOOL/TOOLS line names "agents"')


def main(argv):
    if argv == ['probes']:
        for label, tool, wanted in PROBES:
            print(f'{tool} {json.dumps(wanted)}')
        return 0
    if argv[:1] == ['pi'] and len(argv) == 3:
        pi(*argv[1:])
    elif argv[:1] == ['claude'] and len(argv) == 2:
        claude(argv[1])
    elif argv[:1] == ['mcp'] and len(argv) == 3:
        mcp(*argv[1:])
    elif argv[:1] == ['hook'] and len(argv) == 2:
        hook(argv[1])
    else:
        print(__doc__)
        return 2
    print(f'judge: {"ALL PASS" if not FAILED else f"{len(FAILED)} FAIL"}')
    return 1 if FAILED else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
