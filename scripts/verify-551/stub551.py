"""REHEARSAL ONLY: stand-in for claude, codex, pi and dsh (argv[1] = which). No model, no real host.

claude: a one-line prompt -> a stream-json init (graphtraj connected, mcp__graphtraj__agents) and a READY-551 result.
        the B parent prompt -> a parent stream-json with create/wait tool calls whose results are FABRICATED, and a
        fake child record (an init with tools and MCP servers, a tasks call, a Read of the manual) written under
        the project's .graphtraj/swarm, so steps.zsh's collect and sum551.py run on host-shaped files.
codex/pi/dsh: print one READY-551 line.
"""
import json
import os
import re
import sys
from pathlib import Path


def emit(value):
    print(json.dumps(value))


def trust() -> dict:
    """The init fields of folder trust: the shape Main's B run 1 recorded when untrusted (the rehearsal wrapper
    sets STUB551_UNTRUSTED while its marker file exists), else the GraphTraj host plugin loaded."""
    if os.environ.get('STUB551_UNTRUSTED'):
        return {'plugin_warnings': [{'type': 'project-scope-suppressed-untrusted', 'message':
                                     '1 project-scope directory under ./.claude/skills/ was skipped because this '
                                     'workspace was not trusted (STUB)'}], 'plugins': []}
    return {'plugin_warnings': [], 'plugins': [{'name': 'graphtraj-claude-host', 'path': './.claude/skills/graphtraj-claude-host'}]}


# Claude Code's variadic options: each takes every following argument up to the next option or `--`.
VARIADIC = {'--allowedTools', '--allowed-tools', '--disallowedTools', '--disallowed-tools', '--mcp-config',
            '--tools', '--add-dir', '--betas', '--plugin-dir'}


def variadic_swallow(argv: list[str]) -> str | None:
    """The warning Claude Code prints when a prompt-like argument lands in a variadic option's values, else None."""
    flag = None
    for item in argv:
        if item == '--':
            return None                      # options ended: what follows is the prompt
        if item.startswith('-'):
            flag = item.split('=', 1)[0] if item.split('=', 1)[0] in VARIADIC and '=' not in item else None
            continue
        if flag is not None and (any(c.isspace() for c in item) or len(item) > 200):
            return (f'⚠ "{item[:40]}…" was read as a value of {flag}, not as a prompt · put a prompt '
                    f'before {flag} or after -- (STUB551 rejects this argv)')
    return None


def main() -> int:
    host, argv = sys.argv[1], sys.argv[2:]
    if '--version' in argv:  # Claude's in the real format, so the driver's version check runs as on the host
        print('2.1.326 (Claude Code) STUB-551' if host == 'claude' else f'{host} STUB-551')
        return 0
    if host == 'codex':  # the human header codex exec prints, then the reply
        print('--------\nworkdir: /stub\nmodel: ' + argv[argv.index('-m') + 1] + '\nprovider: openai\n--------')
        print('READY-551 stub-codex (REHEARSAL STUB, no model)')
        return 0
    if host == 'pi':  # one --mode json assistant message with Pi's provider/model fields
        model = argv[argv.index('--model') + 1]
        emit({'type': 'message_end', 'message': {'role': 'assistant', 'provider': argv[argv.index('--provider') + 1],
                                                 'model': model, 'content': [{'type': 'text', 'text': 'READY-551 stub-pi'}]}})
        return 0
    if host == 'dsh':
        if '--dump-config' in argv:  # the shape of the real resolved profile entry (Engineer's dsh 0.2.2-alpha.2 dump)
            print("- id: agent-default-model\n  name: '@deepseek-ai/dsh-agent-default-model'\n  config:\n"
                  "    provider: deepseek-official\n    model: deepseek-flash\n- id: jobs")
            return 0
        # The real --json stream (Main's 00 run 2): no model key anywhere.
        sid = 'session-00000000-0000-4000-8000-000000000551'
        for value in ({'type': 'session', 'sessionId': sid, 'cwd': '/stub'}, {'type': 'status', 'status': 'running'},
                      {'type': 'thinking', 'text': '...'}, {'type': 'text', 'text': 'READY-551 stub-dsh (REHEARSAL STUB)'},
                      {'type': 'final', 'sessionId': sid, 'reason': 'completed', 'text': 'READY-551 stub-dsh (REHEARSAL STUB)'}):
            emit(value)
        return 0
    refused = variadic_swallow(argv)
    if refused:  # as Claude Code 2.1.326 does (Main's 00 run 1 and AU run 1): the prompt became an option value
        print(refused, file=sys.stderr)
        return 2
    # Interactive AU passes the prompt as an argument and leaves stdin open: never wait on it then.
    text = '' if sys.stdin.isatty() or 'probe-551-' in ' '.join(argv) else sys.stdin.read()
    prompt = text or ' '.join(argv)
    model = argv[argv.index('--model') + 1] if '--model' in argv else 'stub'
    if 'probe-551-' not in prompt:
        if '--output-format' not in argv:
            print(f'READY-551 {model} (REHEARSAL STUB)')
            return 0
        emit({'type': 'system', 'subtype': 'init', 'model': model, 'apiKeySource': 'none',
              'tools': ['Read', 'mcp__graphtraj__agents', 'mcp__graphtraj__tasks'],
              'mcp_servers': [{'name': 'graphtraj', 'status': 'connected'}], **trust()})
        emit({'type': 'result', 'result': f'READY-551 {model} (REHEARSAL STUB)'})
        return 0
    runtime = re.search(r'"runtime": "([a-z]+)"', prompt).group(1)
    # A's refusal cases, FABRICATED here in the shape agents create returns them (rehearses the verdicts only).
    named = next((marker for marker in ('nosuchtool551', 'mcp__nosuchserver551__x', 'tool-nosuch551') if marker in prompt), '')
    refusal = next((code for marker, code in (('nosuchtool551', 'unavailable'), ('mcp__nosuchserver551__x', 'unavailable'),
                                              ('tool-nosuch551', 'unavailable'), ('mcp__undefined551__x', 'unavailable'),
                                              ('"tool-plugin-market"', 'authorization-required'),
                                              ('"tools": ["web_search"]', 'authorization-required'))
                    if marker in prompt), None)
    if refusal is not None:
        emit({'type': 'system', 'subtype': 'init', 'model': model, 'tools': ['mcp__graphtraj__agents'],
              'mcp_servers': [{'name': 'graphtraj', 'status': 'connected'}], **trust()})
        error = {'action': 'create', 'error': {'code': refusal, 'message': f'STUB refusal {[named] if named else ""}'}}
        emit({'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': 'c1', 'name': 'mcp__graphtraj__agents',
                                                            'input': {'action': 'execute', 'feature': 'create'}}]}})
        emit({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'c1', 'is_error': True,
                                                       'content': [{'type': 'text', 'text': json.dumps(error)}]}]}})
        emit({'type': 'result', 'result': f'CREATE-ERROR {refusal}: STUB refusal'})
        return 0
    agent = f'agent-stub-{runtime}'
    session = '00000000-0000-4000-8000-0000000005{0:02d}'.format(len(runtime))
    manual = '/stub/share/graphtraj/manuals/concept-clarification/guide.md'
    record = Path.cwd() / '.graphtraj/swarm/stub-run' / agent / 'trace.jsonl'
    record.parent.mkdir(parents=True, exist_ok=True)
    (record.parent / 'session.yml').write_text(  # the shape E1 names: native_init.tools (YAML, flow style is valid)
        'native_init: {model: stub-child, tools: [Bash, Read, Write, Edit, Glob, Grep, mcp__graphtraj__agents]}\n'
        'argv: [claude, --print, --restricted, --tools, "Bash,Read,Write,Edit,Glob,Grep", --model, stub-child]\n')
    with record.open('w') as handle:
        for value in (
            {'type': 'system', 'subtype': 'init', 'model': 'stub-child', 'session_id': session,
             'tools': ['Bash', 'Read', 'Write', 'Edit', 'Glob', 'Grep', 'mcp__graphtraj__agents'],
             'mcp_servers': [{'name': 'graphtraj', 'status': 'connected'}]},
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': 't1', 'name': 'Read',
                                                           'input': {'file_path': manual}}]}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 't1',
                                                      'content': 'File is outside the allowed directories (STUB)'}]}},
        ):
            handle.write(json.dumps(value) + '\n')
        # AU (the parent asks the user): the child's WebSearch, refused after a request (STUB551_AU_REQUEST, set by
        # the rehearsal wrapper while its marker exists) or run without any request (auto-mode-like).
        user_mode = 'allow or deny?' in prompt
        asked = bool(os.environ.get('STUB551_AU_REQUEST'))
        if user_mode:
            handle.write(json.dumps({'type': 'assistant', 'message': {'content': [
                {'type': 'tool_use', 'id': 't2', 'name': 'WebSearch', 'input': {'query': 'example.com'}}]}}) + '\n')
            handle.write(json.dumps({'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 't2', 'is_error': asked,
                 'content': 'The parent denied this tool use (STUB)' if asked else 'Example Domain (STUB)'}]}}) + '\n')
    # Per-Runtime record shapes A's verdicts read (FABRICATED, shaped like Main's real A records).
    denied = (re.findall(r'"disallowed_tools": \[([^\]]*)\]', prompt) or [''])[0]
    folder = record.parent
    if runtime == 'codex':  # rollout: additional_tools declares code-mode tools; a tasks call through exec
        declared = ['exec_command(args: {})', 'view_image(args: {})'] + ([] if 'web_search' in denied else ['web__run(args: {})'])
        (folder / 'rollout-stub.jsonl').write_text(''.join(json.dumps(value) + '\n' for value in (
            {'type': 'response_item', 'payload': {'type': 'additional_tools', 'tools': [
                {'type': 'namespace', 'name': 'functions', 'tools': [{'name': 'exec', 'description': '\n'.join(declared)}]}]}},
            {'type': 'response_item', 'payload': {'type': 'custom_tool_call', 'name': 'exec', 'call_id': 'x1',
                                                  'input': 'const r = await tools.mcp__graphtraj__tasks({action:"discover"});'}})))
    chosen = (re.findall(r'"tools": \[([^\]]*)\]', prompt) or [None])[0]
    drops = bool(os.environ.get('STUB551_PI_DROPS_MCP'))  # the defect Main saw on f8c39a95, for the FAIL path
    if runtime == 'pi':  # pi-process.json: the launch argv (the fixed one keeps the owner's MCP entries)
        names = re.findall(r'"([^"]+)"', chosen) if chosen is not None else []
        if chosen is not None and not drops:
            names += ['mcp__graphtraj__agents', 'mcp__graphtraj__tasks']
        (folder / 'pi-process.json').write_text(json.dumps({'argv': ['pi', '--mode', 'rpc', '--model', 'stub'] + (
            ['--tools', ','.join(names)] if chosen is not None else []) + (
            ['--exclude-tools', 'bash'] if 'bash' in denied else [])}))
        if not drops:  # the Pi child's session: its tasks call as Pi records it
            (folder / 'session.jsonl').write_text(json.dumps({'type': 'message', 'message': {'role': 'assistant', 'content': [
                {'type': 'toolCall', 'id': 'p1', 'name': 'mcp__graphtraj__tasks', 'arguments': {'action': 'discover'}}]}}) + '\n')
    if runtime == 'dsh':  # the launch patch's agent-preset rows
        (folder / 'cordis.patch.yml').write_text(
            "- id: preset-standard\n  config:\n    plugins:\n      - {id: tool-fs, name: x}\n"
            f"      - {{id: tool-web, name: x{', disabled: true' if 'tool-web' in denied else ''}}}\n"
            "      - {id: tool-bash, name: x, disabled: !!js \"process.platform === 'win32'\"}\n")
    # The agents control record: the first plain DSH child fails as in Main's A run, later ones complete.
    flag = Path.cwd() / '.graphtraj/stub-dsh-plain-failed'
    failed = runtime == 'dsh' and not denied and not flag.exists()
    if failed:
        flag.write_text('1')
    control = Path.cwd() / '.graphtraj/swarm/control/agents' / f'{agent}.json'
    control.parent.mkdir(parents=True, exist_ok=True)
    control.write_text(json.dumps({'agent': agent, 'executions': [
        {'outcome': 'failed', 'error': {'code': 'RUNTIME_CONNECTION_CLOSED', 'message': 'DSH Session connection failed. (STUB)'}}
        if failed else {'outcome': 'completed', **({'process': {'tool_check': {'tools_not_offered': ['NoSuchTool551']}}}
                                                   if 'NoSuchTool551' in prompt else {})}]}, indent=1))
    final = ('TOOLS-551: Bash, Read, Write, Edit, Glob, Grep, mcp__graphtraj__agents (STUB)\nMCP-551: graphtraj: agents\n'
             'TASKS-551: absent\nDESCRIBE-551: skipped\nREAD-551: skipped\nWEB-551: absent')
    if runtime == 'pi':
        final = (('TOOLS-551: read, grep (STUB)\nMCP-551: NONE\nTASKS-551: absent\n' if drops else
                  'TOOLS-551: read, grep, mcp__graphtraj__agents, mcp__graphtraj__tasks (STUB)\nMCP-551: graphtraj: agents, tasks\n'
                  'TASKS-551: ok\n') + 'DESCRIBE-551: skipped\nREAD-551: skipped\nWEB-551: absent')
    lines = [{'type': 'system', 'subtype': 'init', 'model': model, 'tools': ['mcp__graphtraj__agents'],
              'mcp_servers': [{'name': 'graphtraj', 'status': 'connected'}], **trust()}]
    steps = [('c1', 'create', {}, {'agent': agent, 'state': 'running'})]
    if user_mode and asked:
        pending = [{'request_token': 'r1', 'tool': 'WebSearch', 'text': 'can_use_tool WebSearch (STUB)'}]
        if os.environ.get('STUB551_TASKS_REQUEST'):  # the old behaviour 551 removes: a tasks call asked too
            pending.append({'request_token': 'r0', 'tool': 'mcp__graphtraj__tasks', 'text': 'review of tasks (STUB)'})
        steps += [('c3', 'requests', {'agent': agent}, {'requests': pending}),
                  ('c4', 'reply', {'agent': agent, 'request_token': 'r1', 'response': {'decision': 'deny'}},
                   {'reply_status': 'submitted'})]
    steps += [('c2', 'wait', {}, {'agent': agent, 'state': 'ended', 'last_message': final})]
    for call_id, feature, arguments, result in steps:
        lines.append({'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': call_id, 'name': 'mcp__graphtraj__agents',
                                                                    'input': {'action': 'execute', 'feature': feature,
                                                                              'arguments': arguments}}]}})
        lines.append({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': call_id,
                                                               'content': [{'type': 'text', 'text': json.dumps(result)}]}]}})
    lines.append({'type': 'result', 'result': f'BEGIN-CHILD\n{final}\nEND-CHILD'})
    for value in lines:
        emit(value)
    # The interactive parent's transcript where AC looks for it (rehearsal: STUB551_PROJECTS), by --session-id.
    if os.environ.get('STUB551_PROJECTS') and '--session-id' in argv:
        folder = Path(os.environ['STUB551_PROJECTS']) / 'stub-project'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{argv[argv.index('--session-id') + 1]}.jsonl").write_text(''.join(json.dumps(v) + '\n' for v in lines))
    return 0


if __name__ == '__main__':
    sys.exit(main())
