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
    if host != 'claude':
        print(f'READY-551 stub-{host} (REHEARSAL STUB, no model)')
        return 0
    text = sys.stdin.read() if not sys.stdin.isatty() else ''
    prompt = text or ' '.join(argv)
    model = argv[argv.index('--model') + 1] if '--model' in argv else 'stub'
    if 'probe-551-' not in prompt:
        if '--output-format' not in argv:
            print(f'READY-551 {model} (REHEARSAL STUB)')
            return 0
        emit({'type': 'system', 'subtype': 'init', 'model': model, 'apiKeySource': 'none (stub)',
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
             'TASKS-551: absent\nDESCRIBE-551: skipped\nREAD-551: skipped')
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
