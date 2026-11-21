"""Task 549: count how many times each describe/discover field reaches the model (and the host's display source).

  python -I count549.py server <server-probe.json>              # the raw CallToolResults (from probe549.py)
  python -I count549.py records <label> <file-or-dir>...        # host records: Codex rollout / exec --json, Pi
                                                                 # session JSONL, DSH JSONL; any JSON lines are read
For every tool result it prints the call (tool + arguments) and, for each marker of a field that the result holds,
the count in the MODEL text and the count in ONE copy of the same document. once = equal, twice = 2x.
Markers are short sentences of one field each; YAML does not wrap them and JSON does not escape them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MARKERS = {
    'agents.wait.description':        'Wait a finite positive number of seconds for an Agent.',
    'agents.wait.input_schema':       'Target Agent reference returned by create or status.',
    'agents.create.description':      'Create a child Agent on a Runtime',
    'tasks.task-delivery.description': 'Coordinate accepted tasks through dispatch',
    'tasks.task-delivery.manual_ref': 'manuals/task-delivery/guide.md',
    'tasks.parent_status.description': 'recorded owning host activity',
}


def counts(text: str) -> dict[str, int]:
    return {name: text.count(marker) for name, marker in MARKERS.items() if marker in text}


def one_copy(text: str) -> tuple[str, str | None]:
    """The text of ONE copy of the document the model text holds (JSON or YAML), or why it is not one document."""
    try:
        return json.dumps(json.loads(text), ensure_ascii=False), None
    except ValueError:
        pass
    try:
        import yaml
        doc = yaml.safe_load(text)
        if isinstance(doc, (dict, list)):
            return json.dumps(doc, ensure_ascii=False), None
        return '', 'not one JSON/YAML document'
    except Exception as error:  # noqa: BLE001 - any parse failure is reported, not raised
        return '', f'not one JSON/YAML document ({type(error).__name__})'


def verdict(model: str, label: str) -> str:
    single, why = one_copy(model)
    have, ref = counts(model), counts(single)
    if not have:
        repeated = why and not label.startswith('final')  # a reply is prose, not a document
        return f'    {label}: no marker (text starts {model[:80]!r})' + (f'  [{why}: REPEATED?]' if repeated else '')
    rows = []
    for name, n in have.items():
        r = ref.get(name, 0)
        if why:  # the text is not one document: each marker count is the number of copies
            word = 'once' if n == 1 else ('TWICE' if n == 2 else f'{n} times')
        else:
            word = 'once' if n == r else ('TWICE' if r and n == 2 * r else f'{n} vs {r} in one copy')
        rows.append(f'{name}={n} ({word})')
    return f'    {label}: ' + '; '.join(rows) + (f'  [{why}]' if why else '')


def text_of(value) -> str:
    """Model-visible text of a tool output in any of the hosts' shapes."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return '\n'.join(text_of(v) for v in value)
    if isinstance(value, dict):
        if isinstance(value.get('text'), str):
            return value['text']
        for key in ('content', 'output', 'body_items'):
            if key in value:
                return text_of(value[key])
    return ''


def walk(value):
    if isinstance(value, dict):
        yield value
        for v in value.values():
            yield from walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from walk(v)


def load(paths: list[str]):
    files = []
    for p in map(Path, paths):
        files += sorted(f for f in p.rglob('*') if f.is_file()) if p.is_dir() else [p]
    for f in files:
        for n, line in enumerate(f.read_text(errors='replace').splitlines(), 1):
            try:
                yield f, n, json.loads(line)
            except ValueError:
                continue


def records(label: str, paths: list[str]) -> int:
    calls, results = {}, []
    for f, n, record in load(paths):
        for d in walk(record):
            cid = d.get('call_id') or d.get('toolCallId') or d.get('callId') or d.get('id')
            args = d.get('arguments', d.get('input', d.get('args')))
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = None
            name = d.get('name') or d.get('toolName') or d.get('tool')
            if isinstance(args, dict) and 'action' in args and cid:
                calls[str(cid)] = f'{name} {json.dumps(args, ensure_ascii=False)}'
            # Model input: Codex function_call_output.output; Pi toolResult / DSH tool message .content.
            if d.get('type') in ('function_call_output', 'mcp_tool_call_output', 'custom_tool_call_output'):
                results.append((f, n, str(d.get('call_id')), 'model', text_of(d.get('output'))))
            elif d.get('role') in ('toolResult', 'tool') and 'content' in d:
                results.append((f, n, str(d.get('toolCallId') or d.get('callId') or d.get('tool_call_id')),
                                'model', text_of(d['content'])))
            # Codex exec --json mcp_tool_call item (exec_events.rs McpToolCallItemResult): result.content (the TUI
            # card's source) and result.structured_content (what the model is given) are both in the event.
            elif d.get('type') == 'mcp_tool_call' and isinstance(d.get('result'), dict):
                results.append((f, n, str(d.get('id')), 'exec item result.content', text_of(d['result'].get('content'))))
                sc = d['result'].get('structured_content', d['result'].get('structuredContent'))
                if sc is not None:
                    results.append((f, n, str(d.get('id')), 'structured_content', json.dumps(sc, ensure_ascii=False)))
                if d.get('arguments') is not None and d.get('id'):
                    calls.setdefault(str(d['id']), f"{d.get('tool')} {json.dumps(d.get('arguments'), ensure_ascii=False)}")
            elif d.get('type') == 'agent_message' and isinstance(d.get('text'), str):
                results.append((f, n, 'final', 'final message (model reply)', d['text']))
                calls['final'] = '(the model reply, not a tool result)'
    print(f'== {label}: {len(results)} tool results in {len(paths)} path(s)')
    seen = set()
    for f, n, cid, kind, text in results:
        key = (cid, kind, text)
        if key in seen:
            continue
        seen.add(key)
        if (not counts(text) and cid != 'final'
                and 'describe' not in calls.get(cid, '') and 'discover' not in calls.get(cid, '')):
            continue
        print(f'  {f.name}:{n} call {cid}: {calls.get(cid, "(call not found)")}')
        print(verdict(text, kind))
    return 0 if results else 1


def server(path: str) -> int:
    for item in json.loads(Path(path).read_text()):
        r = item['response'].get('result', {})
        content = [c.get('text', '') for c in r.get('content', []) if c.get('type') == 'text']
        sc = r.get('structuredContent')
        print(f"  {item['tool']} {json.dumps(item['arguments'])}: isError={r.get('isError')} "
              f"content text blocks={len(content)} structuredContent={'present' if sc is not None else 'absent'}")
        print(verdict('\n'.join(content), 'content text (Pi, DSH, Codex card)'))
        if sc is not None:
            print(verdict(json.dumps(sc, ensure_ascii=False), 'structuredContent (Codex model, Claude Code)'))
    return 0


def text(label: str, paths: list[str]) -> int:
    """Raw marker counts in printed (non-JSON) output, e.g. codex exec's human stdout/stderr."""
    for path in paths:
        body = Path(path).read_text(errors='replace')
        found = {name: body.count(marker) for name, marker in MARKERS.items()}
        print(f'== {label} {path}: mcp lines {body.count("mcp: ")}; DONE-549 lines {body.count("DONE-549")}; '
              + ('; '.join(f'{k}={v}' for k, v in found.items() if v) or 'no field marker printed'))
    return 0


if __name__ == '__main__':
    mode = sys.argv[1]
    if mode == 'server':
        sys.exit(server(sys.argv[2]))
    sys.exit(text(sys.argv[2], sys.argv[3:]) if mode == 'text' else records(sys.argv[2], sys.argv[3:]))
