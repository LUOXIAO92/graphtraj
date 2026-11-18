"""Task 514 real-host checks over Runtime records: model-visible MCP names and one successful agents call.

Usage: python -I check514.py <label> [--init STREAM] [--skip SUBSTRING]... [--observe] PATH...
  PATH       files or directories holding one Agent's Runtime records (scanned recursively)
  --init     a Claude stream-json file whose system init record lists the tools the model was given
  --skip     leave out files whose path contains SUBSTRING (another Agent's Session id, for example)
  --observe  Rs: print the facts only (no PASS/FAIL gate)
Criteria (Task 514 definition, acceptance): the records name mcp__graphtraj__agents and no mcp__agents__*
tool; at least one mcp__graphtraj__agents call has a result that is neither an error nor a review/permission
refusal. Exit 0 when every criterion passes. The step's own files (prompts, configuration) are never read.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

NEW = ('mcp__graphtraj__agents', 'mcp__graphtraj__tasks')
OLD = ('mcp__agents__agents', 'mcp__agents__tasks')
# Files steps.zsh writes itself (inputs, configuration, printouts): not Runtime records.
STEP_FILES = {'summary.txt', 'run.txt', 'mcp.json', 'config.json', 'settings.local.json', 'patch.yml',
              'member.txt', 'marker', 'main-session.txt'}
ID_KEYS = ('id', 'tool_use_id', 'toolUseId', 'toolCallId', 'callId', 'call_id')
NAME_KEYS = ('name', 'toolName', 'tool_name', 'tool')
REFUSALS = ('did not allow', "haven't granted", 'was denied', 'user denied', 'permission denied',
            'requires approval', 'no such tool', 'not available', 'unknown tool')


def files(paths: list[str], skips: list[str]):
    """Yield every readable Runtime record file under ``paths``."""
    for path in map(Path, paths):
        found = [path] if path.is_file() else sorted(path.rglob('*')) if path.is_dir() else []
        for item in found:
            if (item.name.endswith('.prompt.txt') or item.name in STEP_FILES
                    or any(skip and skip in str(item) for skip in skips)):
                continue
            try:
                if item.is_file():
                    item.read_bytes()[:0]
                    yield item
            except OSError as error:
                print(f'  unreadable, not scanned: {item} ({error.strerror})')


def objects(value):
    """Yield every dict inside one JSON value."""
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from objects(item)
    elif isinstance(value, list):
        for item in value:
            yield from objects(item)


def records(path: Path):
    """Yield each JSON value of a JSONL (or JSON) file; other lines are skipped."""
    text = path.read_text(errors='replace')
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(('{', '[')):
            try:
                yield json.loads(line)
            except ValueError:
                continue


def call_name(item: dict) -> str | None:
    """The model-visible tool name of one call object, or None.

    Codex rollouts record ``{type: McpToolCall, server, tool, status, result}`` (server and tool in separate
    fields); DSH ``--json`` records ``{type: tool_call, callId, tool, input}`` (517)."""
    if item.get('type') == 'McpToolCall' and isinstance(item.get('server'), str) and isinstance(item.get('tool'), str):
        return f"mcp__{item['server']}__{item['tool']}"
    for key in NAME_KEYS:
        if isinstance(item.get(key), str) and item[key].startswith('mcp__'):
            return item[key]
    invocation = item.get('invocation')
    if isinstance(invocation, dict) and isinstance(invocation.get('server'), str):
        return f"mcp__{invocation['server']}__{invocation.get('tool')}"
    return None


def refused(item: dict) -> str | None:
    """Why one result object is a failure, or None."""
    if item.get('is_error') is True or item.get('isError') is True:
        return 'error flag'
    result = item.get('result')
    if item.get('type') in ('McpToolCall', 'tool_result') and 'status' in item:
        # Codex McpToolCall and DSH --json tool_result state their outcome themselves (517): judged by
        # status, error field and result.isError only; text matching misread their successful content.
        if item.get('status') != 'completed':
            return f"status {item.get('status')!r}"
        if item.get('error'):
            return 'error field: ' + json.dumps(item['error'], ensure_ascii=False)[:200]
        if isinstance(result, dict) and result.get('isError') is True:
            return 'error result'
        return None
    if isinstance(result, dict) and ('Err' in result or result.get('isError') is True):
        return 'error result'
    text = json.dumps(item, ensure_ascii=False).lower()
    return next((f'refusal text {word!r}' for word in REFUSALS if word in text), None)


def main() -> int:
    arguments, label = sys.argv[2:], sys.argv[1]
    init, skips, observe, paths = None, [], False, []
    while arguments:
        head = arguments.pop(0)
        if head == '--init':
            init = arguments.pop(0)
        elif head == '--skip':
            skips.append(arguments.pop(0))
        elif head == '--observe':
            observe = True
        else:
            paths.append(head)
    verdicts = []

    def say(ok: bool, text: str) -> None:
        verdicts.append(ok)
        print(f"{'OBSERVED' if observe else 'PASS' if ok else 'FAIL'} [{label}] {text}")

    scanned = list(files(paths, skips))
    print(f'[{label}] scanning {len(scanned)} file(s)')
    totals = dict.fromkeys(NEW + OLD, 0)
    calls: dict[str, tuple[str, Path]] = {}
    results: dict[str, list[str | None]] = {}
    for path in scanned:
        text = path.read_text(errors='replace')
        counts = {name: text.count(name) for name in totals}
        if any(counts.values()):
            print(f'  names in {path}: ' + ' '.join(f'{k}={v}' for k, v in counts.items()))
        for name in totals:
            totals[name] += counts[name]
        for value in records(path):
            for item in objects(value):
                name = call_name(item)
                ident = next((str(item[k]) for k in ID_KEYS if isinstance(item.get(k), (str, int))), None)
                if name and ident and ('input' in item or 'arguments' in item or 'invocation' in item):
                    calls.setdefault(ident, (name, path))
                    started = item.get('status') in ('in_progress', 'inProgress', 'pending')  # not an outcome yet
                    if ('invocation' in item or item.get('type') == 'McpToolCall') and 'result' in item and not started:
                        results.setdefault(ident, []).append(refused(item))
                elif ident and any(k in item for k in ('content', 'output', 'result', 'is_error', 'isError')):
                    results.setdefault(ident, []).append(refused(item))

    if init:
        lines = [value for value in records(Path(init)) if isinstance(value, dict) and value.get('subtype') == 'init']
        first = lines[0] if lines else {}
        tools = [tool for tool in first.get('tools', []) if tool.startswith('mcp__')]
        servers = [(server.get('name'), server.get('status')) for server in first.get('mcp_servers', [])]
        print(f'  init mcp tools: {tools}\n  init mcp_servers: {servers}\n  init plugin_warnings: '
              f"{json.dumps(first.get('plugin_warnings', []))[:300]}")
        say(all(name in tools for name in NEW) and not any(name in tools for name in OLD),
            f'system init lists {list(NEW)}: {[n in tools for n in NEW]}; old {list(OLD)} listed: '
            f'{[n in tools for n in OLD]}')
    say(totals[NEW[0]] > 0 and not any(totals[name] for name in OLD),
        'records name ' + ', '.join(f'{name} {totals[name]}x' for name in NEW + OLD))

    by_name: dict[str, list[str]] = {}
    for ident, (name, path) in calls.items():
        outcome = results.get(ident)
        reason = ('no result' if not outcome else next((r for r in outcome if r), None) or 'ok')
        by_name.setdefault(name, []).append(reason)
    for name, outcomes in sorted(by_name.items()):
        print(f'  calls of {name}: {len(outcomes)}; outcomes: {outcomes[:8]}')
    good = by_name.get(NEW[0], []).count('ok')
    say(good > 0, f'{NEW[0]} calls with a result that is no error and no refusal: {good}')
    if observe:
        for name in NEW + OLD:
            print(f'OBSERVED [{label}] {name}: calls {len(by_name.get(name, []))}, ok {by_name.get(name, []).count("ok")}')
        return 0
    return 0 if all(verdicts) else 1


if __name__ == '__main__':
    sys.exit(main())
