"""REHEARSAL ONLY: stand-in for claude, codex, pi and dsh (argv[1] = which). No model, no real host.

claude: a one-line prompt -> a stream-json init (graphtraj connected, mcp__graphtraj__agents) and a READY-551 result.
        the B parent prompt -> a parent stream-json with create/wait tool calls whose results are FABRICATED, and a
        fake child record (an init with tools and MCP servers, a tasks call, a Read of the manual) written under
        the project's .graphtraj/swarm, so steps.zsh's collect and sum551.py run on host-shaped files.
codex/pi/dsh: print one READY-551 line.
"""
import json
import re
import sys
from pathlib import Path


def emit(value):
    print(json.dumps(value))


def main() -> int:
    host, argv = sys.argv[1], sys.argv[2:]
    if '--version' in argv:
        print(f'{host} STUB-551')
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
    text = sys.stdin.read() if not sys.stdin.isatty() else ''
    prompt = text or ' '.join(argv)
    model = argv[argv.index('--model') + 1] if '--model' in argv else 'stub'
    if 'probe-551-' not in prompt:
        if '--output-format' not in argv:
            print(f'READY-551 {model} (REHEARSAL STUB)')
            return 0
        emit({'type': 'system', 'subtype': 'init', 'model': model, 'apiKeySource': 'none',
              'tools': ['Read', 'mcp__graphtraj__agents', 'mcp__graphtraj__tasks'],
              'mcp_servers': [{'name': 'graphtraj', 'status': 'connected'}]})
        emit({'type': 'result', 'result': f'READY-551 {model} (REHEARSAL STUB)'})
        return 0
    runtime = re.search(r'"runtime": "([a-z]+)"', prompt).group(1)
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
    final = ('TOOLS-551: Bash, Read, Write, Edit, Glob, Grep, mcp__graphtraj__agents (STUB)\nMCP-551: graphtraj: agents\n'
             'TASKS-551: absent\nDESCRIBE-551: skipped\nREAD-551: skipped\nWEB-551: absent')
    emit({'type': 'system', 'subtype': 'init', 'model': model, 'tools': ['mcp__graphtraj__agents'],
          'mcp_servers': [{'name': 'graphtraj', 'status': 'connected'}]})
    for call_id, feature, result in (('c1', 'create', {'agent': agent, 'state': 'running'}),
                                     ('c2', 'wait', {'agent': agent, 'state': 'ended', 'last_message': final})):
        emit({'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': call_id, 'name': 'mcp__graphtraj__agents',
                                                            'input': {'action': 'execute', 'feature': feature}}]}})
        emit({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': call_id,
                                                       'content': [{'type': 'text', 'text': json.dumps(result)}]}]}})
    emit({'type': 'result', 'result': f'BEGIN-CHILD\n{final}\nEND-CHILD'})
    return 0


if __name__ == '__main__':
    sys.exit(main())
