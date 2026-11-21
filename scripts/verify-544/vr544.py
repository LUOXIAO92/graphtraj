"""Task 544 Vr: read the interactive Codex Main's rollout of the isolated project (read only).

usage: python -I vr544.py <codex sessions dir> <project> <child name> <V start epoch>
       python -I vr544.py --selftest <rollout.jsonl>      (parser self-test: sizes of every McpToolCall, no verdict)

The Main = the session of the last codex:SessionStart claim in <project>/.graphtraj/runner/main-sessions/
continuity.jsonl written at or after the V stamp; its rollout = the newest one whose session_meta id is that session.
Codex 0.171.0 calls MCP tools in code mode: response_item custom_tool_call 'exec' whose input calls
tools.mcp__graphtraj__agents(...), event_msg item_completed item.type McpToolCall (the full CallToolResult), then
response_item custom_tool_call_output (what the model got from the script). Direct function_call(_output) is also read.
Per agents create/send/resume McpToolCall:
  (only action 'execute' calls: describe/discover of create are ignored)
  CHECK content lacks the message body (instruction/message argument);
  CHECK content is exactly one text block of one line `→ <child> [agent-…]` (no reply, no '← replied');
  CHECK structuredContent is present and complete (a dict with 'agent' and 'result').
  SIZE (bytes, UTF-8, compact JSON as JSON.stringify writes it): (a) the actual CallToolResult; (b) the same object
  with content text = yaml.safe_dump(structuredContent, sort_keys=False, allow_unicode=True), i.e. what the baseline
  f754d3a9 returns — DERIVED, not observed; (c) the custom_tool_call_output the model actually got; delta (b)-(a).
Also CHECK no 535 hook copy anywhere (`agents → <child>` / `<child> · replied`). Exit 0 = every CHECK PASS.
"""
import json
import re
import sys
from pathlib import Path

import yaml

SENDS = {'create', 'send', 'resume'}


def size(value) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode())


def baseline(result: dict) -> dict:
    """The same CallToolResult with today's YAML content (derived)."""
    text = yaml.safe_dump(result.get('structuredContent'), sort_keys=False, allow_unicode=True)
    return {**result, 'content': [{'type': 'text', 'text': text}]}


def output_bytes(output) -> int:
    if isinstance(output, str):
        return len(output.encode())
    if isinstance(output, list):
        return sum(len(str(part.get('text', '')).encode()) for part in output if isinstance(part, dict))
    return size(output)


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def calls(path: Path) -> tuple[list[dict], list[tuple[int, str]]]:
    """Every McpToolCall with its exec call and the model's output size, and every record line's strings."""
    found, pending, by_call, texts = [], None, {}, []
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        try:
            payload = json.loads(line).get('payload') or {}
        except ValueError:
            continue
        kind = payload.get('type')
        texts.append((number, line))
        if kind in ('custom_tool_call', 'function_call'):
            pending = payload.get('call_id')
            by_call[pending] = {'line': number, 'name': payload.get('name'),
                                'input': str(payload.get('input') or payload.get('arguments') or '')}
        elif kind == 'item_completed' and (payload.get('item') or {}).get('type') == 'McpToolCall':
            item = payload['item']
            found.append({'line': number, 'call_id': pending, 'server': item.get('server'), 'tool': item.get('tool'),
                          'arguments': item.get('arguments') or {}, 'result': item.get('result') or {}})
        elif kind in ('custom_tool_call_output', 'function_call_output') and payload.get('call_id') in by_call:
            for entry in found:
                if entry['call_id'] == payload.get('call_id') and 'model_bytes' not in entry:
                    entry['model_bytes'], entry['output_line'] = output_bytes(payload.get('output')), number
            by_call[payload.get('call_id')]['output'] = number
    for entry in found:
        entry['exec'] = by_call.get(entry['call_id'], {})
    return found, texts


def print_size(entry: dict) -> None:
    result = entry['result']
    a, b = size(result), size(baseline(result))
    c = entry.get('model_bytes')
    print(f"  SIZE (a) actual CallToolResult {a} B | (b) same with today's YAML content {b} B (DERIVED, not observed) "
          f"| (c) custom_tool_call_output the model got {c if c is not None else 'none'} B "
          f"(line {entry.get('output_line')}) | delta (b)-(a) {b - a} B")


def selftest(path: Path) -> int:
    found, _ = calls(path)
    print(f'self-test on {path}: {len(found)} McpToolCall item(s)')
    for entry in found:
        print(f"---- line {entry['line']} {entry['server']}.{entry['tool']} (exec {entry['exec'].get('name')} line "
              f"{entry['exec'].get('line')}); content last line: {_text(entry['result']).split(chr(10))[-1]!r}")
        print_size(entry)
    return 0 if found else 1


def _text(result: dict) -> str:
    return '\n'.join(part.get('text', '') for part in result.get('content') or [] if isinstance(part, dict))


def main_session(project: Path, since: float) -> str | None:
    path = project / '.graphtraj/runner/main-sessions/continuity.jsonl'
    try:
        claims = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    except (OSError, ValueError) as error:
        print(f'continuity unreadable: {path}: {error}')
        return None
    print(f'continuity {path}: {[(c.get("entry"), c.get("session")) for c in claims]}')
    main = [c for c in claims if float(c.get('at', 0)) >= since and str(c.get('entry') or '').startswith('codex:SessionStart')]
    return main[-1]['session'] if main else None


def main(sessions: Path, project: Path, child: str, since: float) -> int:
    session = main_session(project, since)
    if session is None:
        print(f'FAIL: no codex:SessionStart Main claim at or after {since}; the USER part of V comes first')
        return 1
    paths = []
    for path in sessions.rglob('rollout-*.jsonl'):
        try:
            with path.open(encoding='utf-8') as handle:
                if (json.loads(handle.readline()).get('payload') or {}).get('id') == session:
                    paths.append(path)
        except (OSError, ValueError):
            continue
    if not paths:
        print(f'FAIL: no rollout under {sessions} whose session_meta id is the Main session {session}')
        return 1
    path = max(paths, key=lambda item: item.stat().st_mtime)
    print(f'Main session {session}: rollout {path}')
    found, texts = calls(path)
    recipient = re.compile(rf'→ {re.escape(child)} \[[^\]\n]+\]')
    ok, sends = True, 0
    for entry in found:
        given, result = entry['arguments'], entry['result']
        feature = given.get('feature') if isinstance(given, dict) else None
        if entry['server'] != 'graphtraj' or entry['tool'] != 'agents':
            continue
        print(f"---- line {entry['line']} graphtraj.agents {given.get('action')} {feature} (exec {entry['exec'].get('name')} "
              f"line {entry['exec'].get('line')}, calls mcp__graphtraj__agents: {'mcp__graphtraj__agents' in entry['exec'].get('input', '')})")
        text = _text(result)
        print('  content: ' + json.dumps(text[:400], ensure_ascii=False))
        if given.get('action') != 'execute' or feature not in SENDS:
            continue  # discover/describe (e.g. describe create) and other features are not sends
        sends += 1
        inner = given.get('arguments') if isinstance(given.get('arguments'), dict) else {}
        body = str(inner.get('instruction', inner.get('message')) or '')
        lines = [line for line in body.split('\n') if len(line.strip()) >= 6]
        checks = [
            ('content lacks the message body', bool(body.strip()) and body.strip() not in text
             and not any(line.strip() in text for line in lines)),
            (f'content is exactly one line "→ {child} [agent-…]"', bool(recipient.fullmatch(text))
             and len(result.get('content') or []) == 1),
            ('structuredContent present and complete (agent, result)', isinstance(result.get('structuredContent'), dict)
             and {'agent', 'result'} <= set(result['structuredContent'])),
        ]
        for name, passed in checks:
            ok &= passed
            print(f'  CHECK {name}: {"PASS" if passed else "FAIL"}')
        print_size(entry)
    hook = [number for number, line in texts
            if any(f'agents → {child}' in text or f'{child} · replied' in text
                   for text in strings(json.loads(line).get('payload') or {}))]
    checks = [(f'agents create/send/resume calls found: {sends}', sends > 0),
              (f'no 535 hook copy ("agents → {child}" / "{child} · replied"): {hook[:6] or "none"}', not hook)]
    for name, passed in checks:
        ok &= passed
        print(f'CHECK {name}: {"PASS" if passed else "FAIL"}')
    print('CHECK 544 rollout:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--selftest':
        sys.exit(selftest(Path(sys.argv[2])))
    if len(sys.argv) != 5:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2]).resolve(), sys.argv[3], float(sys.argv[4])))
