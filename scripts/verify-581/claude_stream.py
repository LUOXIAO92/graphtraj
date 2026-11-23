"""Task 581: read one `claude -p --output-format stream-json --verbose` run of a Claude Code Main.

usage: claude_stream.py <stream.jsonl> <text out>
Prints the init record's model, apiKeySource, MCP servers, plugins and whether the tools hold
mcp__graftling__agents; writes the final answer followed by every tool result's text to <text out>, which
scripts/verify-570/judge.py then reads (its 'authority-denied' and error checks need the tool results too).
Exit 0 when an init and a result record were found, else 1.
"""
import json, sys


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(text_of(c.get('text') if isinstance(c, dict) and 'text' in c else
                                 c.get('content') if isinstance(c, dict) else c) for c in content)
    return '' if content is None else json.dumps(content)


def main(stream, out):
    init, result, tools = None, None, []
    for line in open(stream, errors='replace'):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        if d.get('type') == 'system' and d.get('subtype') == 'init':
            init = d
        elif d.get('type') == 'result':
            result = d
        elif d.get('type') == 'user':
            for c in (d.get('message') or {}).get('content') or []:
                if isinstance(c, dict) and c.get('type') == 'tool_result':
                    tools.append(text_of(c.get('content')))
    if init:
        servers = {s.get('name'): s.get('status') for s in init.get('mcp_servers') or [] if isinstance(s, dict)}
        plugins = [p.get('name') if isinstance(p, dict) else p for p in init.get('plugins') or []]
        print(f'claude init: model {init.get("model")} | apiKeySource {init.get("apiKeySource")} | mcp_servers {servers}'
              f' | plugins {plugins} | mcp__graftling__agents in tools: {"mcp__graftling__agents" in (init.get("tools") or [])}')
    else:
        print('claude init: NONE')
    answer = str((result or {}).get('result') or '')
    print(f'claude result: is_error {(result or {}).get("is_error")} | {len(tools)} tool result(s)')
    with open(out, 'w') as sink:
        sink.write(answer + '\n\n-- tool results --\n' + '\n'.join(tools) + '\n')
    return 0 if init and result else 1


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(*sys.argv[1:]))
