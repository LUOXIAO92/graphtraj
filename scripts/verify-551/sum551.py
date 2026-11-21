"""Task 551: summarize one B/A probe run from its own files (standard library only).

  python -I sum551.py <step dir> <runtime> <manual heading or ->

<step dir> holds parent.jsonl (the Claude Main parent's stream-json) and records/ (the project's agents records
and every Runtime file copied since the step's marker). Prints, for the child of <runtime>:
  - the parent's create result (agent reference or the exact error) and the child's final message,
  - the child's self-report lines (TOOLS-551, MCP-551, TASKS-551, DESCRIBE-551, READ-551), marked as self-report,
  - from the child's own records (not the model's words): the tool and MCP server lists of every native init or
    launch record found, every tool call by name, every `tasks` call with its action/feature, every read of a
    manual guide.md, and whether a tool result holds the manual's heading,
  - approval or input requests the parent saw (agents requests/reply calls).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SELF = ('TOOLS-551', 'MCP-551', 'TASKS-551', 'DESCRIBE-551', 'READ-551', 'DENY-551', 'BEYOND-551')
TOOL_KEYS = ('name', 'tool_name', 'toolName', 'tool')


def records(path: Path):
    """Every JSON value of every line of every file under ``path`` (unparseable lines skipped)."""
    for file in sorted(p for p in path.rglob('*') if p.is_file()):
        try:
            text = file.read_text(errors='replace')
        except OSError:
            continue
        if file.suffix in ('.json', '.yml', '.yaml') and not text.lstrip().startswith(('{', '[')):
            continue
        for line in text.splitlines() if not text.lstrip().startswith('[') else [text]:
            try:
                yield file, json.loads(line)
            except ValueError:
                continue


def walk(value):
    """Every mapping nested in ``value``."""
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def call_name(node: dict) -> str | None:
    """The tool name of a tool-call shaped mapping (Claude tool_use, Codex function_call/mcp, Pi toolCall, DSH)."""
    kind = str(node.get('type', ''))
    if kind in ('tool_use', 'function_call', 'toolCall', 'tool_call', 'mcp_tool_call', 'custom_tool_call'):
        for key in TOOL_KEYS:
            if isinstance(node.get(key), str):
                server = node.get('server')
                return f"{server}.{node[key]}" if isinstance(server, str) else node[key]
    return None


def call_input(node: dict) -> object:
    for key in ('input', 'arguments', 'args', 'params'):
        if key in node:
            value = node[key]
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except ValueError:
                    return value
            return value
    return None


def parent_view(parent: Path, runtime: str) -> tuple[str, str, list[str]]:
    """(create result, child's final message, request lines) from the parent's stream-json."""
    created, final, requests = 'no create call seen', '', []
    pending: dict[str, str] = {}
    if not parent.is_file():
        return 'no parent.jsonl', '', []
    for _file, value in records_one(parent):
        for node in walk(value):
            name = call_name(node)
            if name and 'agents' in name:
                arguments = call_input(node) or {}
                feature = arguments.get('feature') if isinstance(arguments, dict) else None
                pending[str(node.get('id'))] = str(feature)
                if feature in ('requests', 'reply'):
                    requests.append(f"parent called agents {feature}: {json.dumps(arguments)[:300]}")
            if node.get('type') == 'tool_result' and str(node.get('tool_use_id')) in pending:
                feature = pending[str(node.get('tool_use_id'))]
                text = json.dumps(node.get('content'))[:1500]
                if feature == 'create':
                    created = text[:600]
                if feature == 'wait' and 'last_message' in text:
                    final = text
                if feature == 'requests' and 'request' in text:
                    requests.append(f"requests result: {text[:500]}")
            if node.get('type') == 'result' and isinstance(node.get('result'), str):
                match = re.search(r'BEGIN-CHILD\n(.*?)\nEND-CHILD', node['result'], re.S)
                if match:
                    final = match.group(1)
                elif not final:
                    final = node['result']
    return created, final, requests


def records_one(file: Path):
    for line in file.read_text(errors='replace').splitlines():
        try:
            yield file, json.loads(line)
        except ValueError:
            continue


def main() -> int:
    step, runtime, heading = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    created, final, requests = parent_view(step / 'parent.jsonl', runtime)
    print(f"[{runtime}] parent create result: {created}")
    final_text = final.encode().decode('unicode_escape', errors='replace') if '\\n' in final else final
    print(f"[{runtime}] child final message (via the parent's wait/result):")
    for line in final_text.splitlines()[-30:]:
        print(f"    {line[:400]}")
    for tag in SELF:
        found = [line for line in final_text.splitlines() if tag in line]
        print(f"[{runtime}] self-report {tag}: {found[-1].strip()[:600] if found else '(none)'}")
    for line in requests:
        print(f"[{runtime}] {line}")
    inits, calls, tasks_calls, manual_reads, heading_seen, launches = [], {}, [], [], [], []
    for file, value in records(step / 'records'):
        for node in walk(value):
            if node.get('subtype') == 'init' and ('tools' in node or 'mcp_servers' in node):
                inits.append((file.name, node.get('model'), node.get('tools'),
                              [(s.get('name'), s.get('status')) for s in node.get('mcp_servers', []) if isinstance(s, dict)]))
            for key in ('argv', 'command', 'args'):
                item = node.get(key)
                if isinstance(item, list) and any(isinstance(a, str) and a in ('--tools', '--mcp-config', '--disallowedTools', '--allowedTools') for a in item):
                    launches.append((file.name, item))
            name = call_name(node)
            if name:
                calls[name] = calls.get(name, 0) + 1
                arguments = call_input(node)
                if 'tasks' in name:
                    tasks_calls.append(f"{name} {json.dumps(arguments)[:200]}")
                if 'guide.md' in json.dumps(arguments):
                    manual_reads.append(f"{name} {json.dumps(arguments)[:300]}")
            if heading != '-' and node.get('type') in ('tool_result', 'function_call_output', 'toolResult') \
                    and heading in json.dumps(node, ensure_ascii=False):
                heading_seen.append(file.name)
    seen = set()
    for name, model, tools, servers in inits:
        key = (json.dumps(tools), json.dumps(servers))
        if key in seen:
            continue
        seen.add(key)
        print(f"[{runtime}] RECORD init ({name}, model {model}): tools={tools} mcp_servers={servers}")
    for name, argv in launches[:3]:
        flags = {argv[i]: argv[i + 1][:300] for i in range(len(argv) - 1)
                 if argv[i] in ('--tools', '--mcp-config', '--disallowedTools', '--allowedTools')}
        print(f"[{runtime}] RECORD launch flags ({name}): {flags}")
    print(f"[{runtime}] RECORD tool calls by name: {calls or 'none found'}")
    print(f"[{runtime}] RECORD tasks calls: {tasks_calls or 'none'}")
    print(f"[{runtime}] RECORD manual guide.md reads: {manual_reads or 'none'}")
    print(f"[{runtime}] RECORD a tool result holds the manual heading {heading!r}: "
          f"{'YES (' + ', '.join(sorted(set(heading_seen))) + ')' if heading_seen else 'NO'}")
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(2)
    sys.exit(main())
