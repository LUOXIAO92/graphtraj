"""Task 551: summarize one B/A probe run from its own files (standard library only).

  python -I sum551.py <step dir> <runtime> <manual heading or -> [<AU beyond-host tool> <child permission mode>]
                      [--expect-refusal]   (A's refused-create cases: the CHECK line says so)

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

SELF = ('TOOLS-551', 'MCP-551', 'TASKS-551', 'DESCRIBE-551', 'READ-551', 'WEB-551')
try:  # the installation's python has PyYAML (session.yml native_init); without it YAML files are skipped
    import yaml

    class TaggedLoader(yaml.SafeLoader):
        """Reads DSH patches: a `!!js` expression (or any other tag) becomes its text."""

    TaggedLoader.add_multi_constructor('', lambda loader, tag, node: f'{tag} {loader.construct_scalar(node)}'
                                       if isinstance(node, yaml.ScalarNode) else None)
except ImportError:
    yaml = None
TOOL_KEYS = ('name', 'tool_name', 'toolName', 'tool')


def records(path: Path):
    """Every JSON value of every line of every file under ``path`` (unparseable lines skipped)."""
    for file in sorted(p for p in path.rglob('*') if p.is_file()):
        try:
            text = file.read_text(errors='replace')
        except OSError:
            continue
        if file.suffix in ('.yml', '.yaml'):
            if yaml is not None:
                try:
                    yield file, yaml.load(text, Loader=TaggedLoader)
                except yaml.YAMLError:
                    pass
            continue
        if file.suffix == '.json':
            try:  # a whole (possibly indented) JSON document, such as the agents control record
                yield file, json.loads(text)
                continue
            except ValueError:
                if not text.lstrip().startswith(('{', '[')):
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
    if kind == 'tool/call' and isinstance(node.get('data'), dict):  # DSH session.v4: {"type": "tool/call", "data": {...}}
        name = node['data'].get('name')
        return name if isinstance(name, str) else None
    if kind in ('tool_use', 'function_call', 'toolCall', 'tool_call', 'mcp_tool_call', 'custom_tool_call'):
        for key in TOOL_KEYS:
            if isinstance(node.get(key), str):
                server = node.get('server')
                return f"{server}.{node[key]}" if isinstance(server, str) else node[key]
    return None


def call_input(node: dict) -> object:
    if node.get('type') == 'tool/call' and isinstance(node.get('data'), dict):
        node = node['data']
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


def au_class(step: Path, tool: str, mode: str) -> None:
    """AU: did the child's beyond-host ask reach the user? Only a parent `agents reply` counts as yes."""
    pending: dict[str, str] = {}
    requests, replies = [], []
    parent = step / 'parent.jsonl'
    for _file, value in (records_one(parent) if parent.is_file() else ()):
        for node in walk(value):
            name = call_name(node)
            if name and 'agents' in name:
                arguments = call_input(node) or {}
                feature = arguments.get('feature') if isinstance(arguments, dict) else None
                pending[str(node.get('id'))] = str(feature)
                if feature == 'reply':
                    replies.append(json.dumps(arguments.get('arguments', arguments))[:300])
            if node.get('type') == 'tool_result' and pending.get(str(node.get('tool_use_id'))) == 'requests':
                requests.append(json.dumps(node.get('content'))[:4000])
    calls, outcomes = set(), []
    for _file, value in records(step / 'records'):
        for node in walk(value):
            name = call_name(node)
            if name == tool or (name or '').endswith('.' + tool):
                calls.add(str(node.get('id') or node.get('toolCallId') or node.get('call_id')))
    for _file, value in records(step / 'records'):
        for node in walk(value):
            claude = node.get('type') == 'tool_result' and str(node.get('tool_use_id')) in calls
            pi = node.get('role') == 'toolResult' and (node.get('toolName') == tool or str(node.get('toolCallId')) in calls)
            if claude or pi:
                outcomes.append(('refused' if node.get('is_error') or node.get('isError') else 'ran',
                                 json.dumps(node.get('content'))[:200]))
    # User decision (551): a child's tasks calls are allowed outright, so none of the requests may be for tasks.
    requested = re.findall(r'"tool"\s*:\s*"([^"]+)"', ' '.join(json.loads(r) if r.startswith('"') else r
                                                             for r in requests).replace('\\"', '"'))
    tasks_requests = [name for name in requested if name.endswith('tasks')]
    print(f"AU tasks calls raised requests: {len(tasks_requests)} (expected 0) "
          f"{'PASS' if not tasks_requests else 'FAIL ' + str(tasks_requests)} | requested tools: {requested or 'none'}")
    outcome = '; '.join(f'{state}: {text}' for state, text in outcomes) or f'the child did not call {tool}'
    if replies:
        print(f"AU CLASS: REQUEST reached the user: {requests[0] if requests else '(requests result not in the transcript)'}"
              f" -> answered {replies} -> outcome: {outcome}")
    else:
        state = ('was not called' if not outcomes else
                 'was refused' if all(state == 'refused' for state, _ in outcomes) else 'ran')
        print(f"AU CLASS: NO REQUEST: the child's {tool} {state} without a request (permission mode {mode}); "
              f"outcome: {outcome}")


# Codex code mode: the `exec` tool's description declares each nested tool as `name(args: ...)`, and a call is
# `tools.<name>({...})` inside the exec script (Task 544's probe rollout; Main's A-plain codex rollout).
CODEX_DECLARED = re.compile(r'(?<![A-Za-z0-9_.])([A-Za-z_][A-Za-z0-9_]*)\(args')
CODEX_CALL = re.compile(r'tools\.([A-Za-z_][A-Za-z0-9_]*)\(\s*(\{.*?\})?\s*\)', re.S)


def main() -> int:
    args = [item for item in sys.argv[1:] if item != '--expect-refusal']
    expect_refusal = '--expect-refusal' in sys.argv
    step, runtime, heading = Path(args[0]), args[1], args[2]
    if len(args) == 5:
        au_class(step, args[3], args[4])
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
    tool_fields: dict[str, set] = {}     # Runtime-written 'tools' lists/settings, by value -> files
    dsh_rows: dict[str, set] = {}        # DSH agent-preset tool rows (id -> disabled) in a launch patch
    web: dict[str, set] = {}             # Codex web_search settings
    codex_declared: set = set()          # Codex code-mode tools declared in additional_tools
    outcomes: list = []                  # the agents control record's execution outcome(s)
    for file, value in records(step / 'records'):
        if isinstance(value, list) and file.suffix in ('.yml', '.yaml'):
            value = {'patch': value}
        if 'control/agents' in str(file) and isinstance(value, dict) and isinstance(value.get('executions'), list):
            for execution in value['executions']:
                error = execution.get('error') or {}
                outcomes.append(f"{execution.get('outcome')}{' ' + str(error.get('code')) + ': ' + str(error.get('message')) if error else ''}")
        for node in walk(value):
            if node.get('type') == 'additional_tools':
                codex_declared |= set(CODEX_DECLARED.findall(json.dumps(node.get('tools')).replace('\\n', '\n')))
            if node.get('type') == 'custom_tool_call' and node.get('name') == 'exec' and isinstance(node.get('input'), str):
                for nested, raw in CODEX_CALL.findall(node['input']):
                    label = f'exec->{nested}'
                    calls[label] = calls.get(label, 0) + 1
                    if 'tasks' in nested:
                        tasks_calls.append(f'{label} {raw[:200]}')
                    # (an exec script naming guide.md is counted once below, as a call of `exec`)
            tools = node.get('tools')
            if isinstance(tools, list) and tools and all(isinstance(t, (str, dict)) for t in tools):
                names = [t if isinstance(t, str) else str(t.get('name') or t.get('type') or sorted(t)) for t in tools]
                tool_fields.setdefault(', '.join(names)[:700], set()).add(file.name)
            elif isinstance(tools, dict) and tools:
                tool_fields.setdefault(json.dumps(tools, default=str)[:400], set()).add(file.name)
            if isinstance(node.get('plugins'), list):
                for row in walk(node['plugins']):
                    if isinstance(row.get('id'), str) and row['id'].startswith('tool-'):
                        flag = row.get('disabled', False)
                        state = 'disabled' if flag is True else 'enabled' if flag is False else 'per-platform'
                        dsh_rows.setdefault(f"{row['id']}={state}", set()).add(file.name)
            for key in ('web_search', 'web_search_request', 'tools.web_search'):
                if key in node and not isinstance(node[key], (dict, list)):
                    web.setdefault(f'{key}={node[key]}', set()).add(file.name)
            for init in ([node] if node.get('subtype') == 'init' else []) + \
                    ([node['native_init']] if isinstance(node.get('native_init'), dict) else []):
                if 'tools' in init or 'mcp_servers' in init:
                    inits.append((file.name, init.get('model'), init.get('tools'),
                                  [(s.get('name'), s.get('status')) if isinstance(s, dict) else s
                                   for s in init.get('mcp_servers', []) or []]))
            for key in ('argv', 'command', 'args'):
                item = node.get(key)
                if isinstance(item, list) and any(isinstance(a, str) and a in ('--model', '--mode', '--tools') for a in item):
                    launches.append((file.name, item))
            name = call_name(node)
            if name:
                calls[name] = calls.get(name, 0) + 1
                arguments = call_input(node)
                if 'tasks' in name:
                    tasks_calls.append(f"{name} {json.dumps(arguments)[:200]}")
                if 'guide.md' in json.dumps(arguments):
                    manual_reads.append(f"{name} {json.dumps(arguments)[:300]}")
            if heading != '-' and (node.get('type') in ('tool_result', 'function_call_output', 'custom_tool_call_output',
                                                        'toolResult', 'tool/result') or node.get('role') == 'toolResult') \
                    and heading in json.dumps(node, ensure_ascii=False):
                heading_seen.append(file.name)
    seen = set()
    for name, model, tools, servers in inits:
        key = (json.dumps(tools), json.dumps(servers))
        if key in seen:
            continue
        seen.add(key)
        print(f"[{runtime}] RECORD init ({name}, model {model}): tools={tools} mcp_servers={servers}")
    shown = set()
    for name, argv in launches:
        flags = {argv[i]: str(argv[i + 1])[:300] for i in range(len(argv) - 1)
                 if argv[i] in ('--tools', '--mcp-config', '--disallowedTools', '--allowedTools', '--exclude-tools',
                                '--no-tools', '--no-builtin-tools', '--extension', '--restricted')}
        flags.update({flag: True for flag in ('--restricted', '--no-tools', '--no-builtin-tools', '--no-mcp') if flag in argv})
        key = json.dumps(flags, sort_keys=True)
        if key in shown:
            continue
        shown.add(key)
        print(f"[{runtime}] RECORD launch flags ({name}): {flags or 'no tool/MCP flag (Runtime defaults)'}")
    for value, files in list(tool_fields.items())[:6]:
        print(f"[{runtime}] RECORD tools field ({', '.join(sorted(files))[:120]}): {value}")
    if not tool_fields:
        print(f"[{runtime}] RECORD tools field: none in the child's records")
    if dsh_rows:
        print(f"[{runtime}] RECORD DSH agent-preset tool rows (launch patch): {', '.join(sorted(dsh_rows))}")
    if web:
        print(f"[{runtime}] RECORD web search settings: {', '.join(f'{k} ({sorted(v)[0]})' for k, v in sorted(web.items()))}")
    print(f"[{runtime}] RECORD tool calls by name: {calls or 'none found'}")
    print(f"[{runtime}] RECORD tasks calls: {tasks_calls or 'none'}")
    print(f"[{runtime}] RECORD manual guide.md reads: {manual_reads or 'none'}")
    print(f"[{runtime}] RECORD a tool result holds the manual heading {heading!r}: "
          f"{'YES (' + ', '.join(sorted(set(heading_seen))) + ')' if heading_seen else 'NO'}")
    # One tool list per Runtime from a record that Runtime writes (A's deny verdicts read this line).
    if runtime == 'claude':
        first = next((tools for _n, _m, tools, _s in inits if tools), None)
        toolset = ('Claude init tools', first)
    elif runtime == 'codex':
        toolset = ('Codex rollout additional_tools, code-mode declarations', sorted(codex_declared) or None)
    elif runtime == 'pi':
        argv = next((argv for _n, argv in launches if '--mode' in argv), None)
        chosen = [f'{argv[i]} {argv[i + 1]}' for i in range(len(argv) - 1)
                  if argv[i] in ('--tools', '--exclude-tools')] if argv else None
        toolset = ('Pi launch argv (pi-process.json); none = the host defaultTools', chosen if argv else None)
    else:
        toolset = ('DSH launch-patch agent-preset tool rows', sorted(dsh_rows) or None)
    print(f"[{runtime}] RECORD TOOLSET ({toolset[0]}): "
          f"{', '.join(toolset[1]) if toolset[1] else ('none' if toolset[1] == [] else 'NOT IN RECORDS')}")
    # Which MCP server name the child's own tool lists and tool calls show for agents/tasks (E1 renamed
    # graftling -> graphtraj). Prose is not counted: the probe text itself names mcp__graphtraj__tasks as an example.
    listed = ' '.join([*tool_fields, *(json.dumps(tools) for _n, _m, tools, _s in inits), *calls])
    names = sorted(set(re.findall(r'mcp__(graphtraj|graftling)__(agents|tasks)\b', listed)))
    print(f"[{runtime}] RECORD child MCP server name for agents/tasks (tool lists and calls): "
          f"{', '.join(f'mcp__{server}__{tool}' for server, tool in names) or 'none found'}")
    outcome = outcomes[-1] if outcomes else None
    print(f"[{runtime}] RECORD execution outcome (agents control record): {outcome or 'none'}")
    failed = outcome is not None and not outcome.startswith('completed')
    missing = [what for what, ok in (('a created child (agent-... in the create result)',
                                      re.search(r'agent-[0-9A-Za-z]', created) is not None),
                                     ('a child final message', bool(final_text.strip()) and not failed)) if not ok]
    tail = ' (expected: create refused)' if expect_refusal and missing else ''
    print(f"CHECK 551 {runtime} child run: {'COMPLETE' if not missing else 'NOT COMPLETE (no ' + ', no '.join(missing) + ')'}{tail}")
    return 1 if missing else 0


if __name__ == '__main__':
    if len([a for a in sys.argv if a != '--expect-refusal']) not in (4, 6):
        print(__doc__)
        sys.exit(2)
    sys.exit(main())
