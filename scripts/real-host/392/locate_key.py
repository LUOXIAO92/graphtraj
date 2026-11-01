"""Say where the DeepSeek value sits in the saved Pi sessions, without printing or copying it.

Usage: python -I locate_key.py <runs directory> <evidence directory>

Reads only. The value comes from this process's environment and is compared, never written: each
reported text has every occurrence replaced before it is cut, so no piece of the value can survive
at the edge of a window. Any other run of 20 or more token characters is masked too. The last act is
to look for the value in what was written; if it is there, that file is emptied and the answer says so.
"""
import json
import os
from pathlib import Path
import re
import sys

WINDOW = 60
LONG = re.compile(r'[A-Za-z0-9_-]{20,}')


def masked(text: str, value: str) -> str:
    """Return ``text`` with the value and every other long token-like run hidden."""
    return LONG.sub('<LONG>', text.replace(value, '<KEY>'))


def leaves(item: object, path: str = '$'):
    """Yield (path, string) for each string in a JSON value; a key counts as a string at its own path."""
    if isinstance(item, str):
        yield path, item
    elif isinstance(item, dict):
        for key, child in item.items():
            yield f'{path}.<key>', key
            yield from leaves(child, f'{path}.{key}')
    elif isinstance(item, list):
        for index, child in enumerate(item):
            yield from leaves(child, f'{path}[{index}]')


def windows(leaf: str, value: str) -> list[str]:
    """Return 60 characters each side of each occurrence, masked, the value replaced before cutting."""
    hidden = leaf.replace(value, '<KEY>')
    found = []
    start = hidden.find('<KEY>')
    while start >= 0:
        piece = hidden[max(0, start - WINDOW):start + len('<KEY>') + WINDOW]
        found.append(LONG.sub('<LONG>', piece))
        start = hidden.find('<KEY>', start + 1)
    return found


def tool_calls(records: list[tuple[int, dict]]) -> dict:
    """Map a tool call's id to (name, arguments), from assistant messages and start events."""
    calls = {}
    for _, record in records:
        message = record.get('message') if isinstance(record.get('message'), dict) else {}
        content = message.get('content')
        for item in content if isinstance(content, list) else []:
            if isinstance(item, dict) and item.get('type') == 'toolCall':
                calls[item.get('id')] = (item.get('name'), item.get('arguments'))
        if record.get('type') == 'tool_execution_start':
            calls.setdefault(record.get('toolCallId'), (record.get('toolName'), record.get('args')))
    return calls


def describe(number: int, record: dict, path: str, leaf: str, context: str, calls: dict, later: int, value: str) -> str:
    """Return one location line."""
    message = record.get('message') if isinstance(record.get('message'), dict) else {}
    call_id = message.get('toolCallId') or record.get('toolCallId')
    role = message.get('role')
    fields = {
        'line': number, 'type': record.get('type'), 'customType': record.get('customType'), 'role': role,
        'toolName': message.get('toolName') or record.get('toolName'), 'stopReason': message.get('stopReason'),
        'provider': 'provider' in record or 'provider' in message, 'model': 'model' in record or 'model' in message,
        'path': path, 'leaf_length': len(leaf), 'context': context, 'assistant_entries_after': later,
    }
    if call_id in calls:
        name, arguments = calls[call_id]
        fields['tool_call'] = {'name': name, 'arguments': masked(json.dumps(arguments, ensure_ascii=False), value)}
    return json.dumps(fields, ensure_ascii=False)


def scan_file(path: Path, value: str) -> tuple[list[str], int]:
    """Return location lines for one JSONL file, and how many lines hold the value outside a parsed string."""
    records, raw_only = [], 0
    with path.open(encoding='utf-8', errors='replace') as stream:
        lines = list(enumerate(stream, 1))
    for number, line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            raw_only += value in line
            continue
        if isinstance(record, dict):
            records.append((number, record))
        else:
            raw_only += value in line
    assistants = [number for number, record in records
                  if isinstance(record.get('message'), dict) and record['message'].get('role') == 'assistant']
    calls = tool_calls(records)
    found = []
    for number, record in records:
        for where, leaf in leaves(record):
            if value in leaf:
                later = sum(item > number for item in assistants)
                found += [describe(number, record, where, leaf, piece, calls, later, value)
                          for piece in windows(leaf, value)]
    return found, raw_only


def latest(runs: Path, step: str) -> Path | None:
    """Return the latest run directory of a step; its name ends with its start time."""
    found = sorted(path for path in runs.glob(f'{step}-*') if path.is_dir())
    return found[-1] if found else None


def targets(runs: Path) -> list[Path]:
    """Return the three named kinds of file, from the latest runs of steps 64 and 89."""
    found = []
    walk = latest(runs, '64-walk-pi')
    if walk:
        found += [path for name in ('pi-session.jsonl', 'pi-session-stdout.jsonl') for path in [walk / 'out' / name] if path.is_file()]
    residual = latest(runs, '89-residual-416')
    if residual:
        found += sorted(path for path in residual.rglob('session.jsonl')
                        if 'events.pi' in path.parts and '4-probe-pi' in path.parts)
    return found


def main() -> int:
    """Write locations.txt and answer.txt; print counts only."""
    runs, evidence = Path(sys.argv[1]), Path(sys.argv[2])
    value = os.environ.get('DEEPSEEK_API_KEY', '')
    if not value:
        print('CANNOT no DeepSeek value in this process')
        return 0
    named = targets(runs)
    output, summary = [], []
    for path in named:
        found, raw_only = scan_file(path, value)
        name = str(path.relative_to(runs))
        output += [f'{name}\t{line}' for line in found]
        summary.append(f'{name}: {len(found)} occurrences in string values; {raw_only} other lines holding it')
    others = []
    for path in sorted(runs.glob('*/**/*.jsonl')):
        if path in named or not path.is_file():
            continue
        if value.encode() in path.read_bytes():
            others.append(str(path.relative_to(runs)))
    locations = evidence / 'locations.txt'
    locations.write_text('\n'.join(output) + ('\n' if output else ''))
    (evidence / 'other-files.txt').write_text('\n'.join(others) + ('\n' if others else ''))
    written = locations.read_bytes() + (evidence / 'other-files.txt').read_bytes()
    if value.encode() in written:
        locations.write_text('')
        (evidence / 'other-files.txt').write_text('')
        print('FAIL the output held the value, so it was emptied')
        return 0
    print(f'PASS scanned {len(named)} named files: ' + ('; '.join(summary) or 'none found'))
    print(f'PASS other *.jsonl files under the runs holding the value: {len(others)}; names in other-files.txt')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
