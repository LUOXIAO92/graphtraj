"""515: MCP tool names in real Claude records (read only; never prints tool contents beyond a short error).

  rec515.py init <stream.jsonl>
      The first system/init record of a `claude -p --output-format stream-json --verbose` run: mcp_servers must be
      exactly ['graphtraj'], tools must hold mcp__graphtraj__agents and mcp__graphtraj__tasks and no mcp__agents__*,
      plugin_warnings empty and no record naming an untrusted plugin. Exit 0 only when all hold.
  rec515.py sizes <out file> <path>...
      Record each JSONL file's current byte size under the paths (Rs: before the resume message).
  rec515.py calls <label> [--since <sizes file>] [--need agents,tasks] <path>...
      Every Claude tool call by name in the JSONL records under the paths (only the bytes after --since's sizes).
      A call is a dict with type tool_use (Claude stream/transcript, graftling archive content) and a name starting
      mcp__; its result is the dict with type tool_result and the same tool_use_id. A result is a refusal or error
      only when it says so itself (is_error true); its first text line is shown (200 characters). Text matching on
      successful content is not used (514's check514.py misjudged real success records that way).
      PASS when: each needed mcp__graphtraj__<x> has at least one ok call, no needed call was refused, and there is
      no mcp__agents__* call at all.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

NEW = ('mcp__graphtraj__agents', 'mcp__graphtraj__tasks')
OLD_PREFIX = 'mcp__agents__'


def objects(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from objects(item)
    elif isinstance(value, list):
        for item in value:
            yield from objects(item)


def jsonl(path: Path, start: int = 0):
    with path.open('rb') as handle:
        handle.seek(start)
        for raw in handle:
            line = raw.decode('utf-8', 'replace').strip()
            if line.startswith('{'):
                try:
                    yield json.loads(line)
                except ValueError:
                    continue


def files(paths):
    for path in map(Path, paths):
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from sorted(p for p in path.rglob('*.jsonl') if p.is_file())


def text_of(item: dict) -> str:
    content = item.get('content')
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ' '.join(str(c.get('text', '')) for c in content if isinstance(c, dict))
    return ''


def init(stream: str) -> int:
    records = list(jsonl(Path(stream)))
    first = next((r for r in records if r.get('type') == 'system' and r.get('subtype') == 'init'), None)
    if first is None:
        print('CHECK 515 init record: FAIL (no system/init record)'); return 1
    servers = [s.get('name') if isinstance(s, dict) else s for s in first.get('mcp_servers') or []]
    status = [(s.get('name'), s.get('status')) for s in first.get('mcp_servers') or [] if isinstance(s, dict)]
    tools = [t for t in first.get('tools') or [] if isinstance(t, str) and t.startswith('mcp__')]
    warnings = first.get('plugin_warnings') or []
    untrusted = [r.get('type') for r in records if 'untrusted' in json.dumps(r).lower()]
    print(f'init mcp_servers: {status}')
    print(f'init mcp tools: {tools}')
    print(f'init plugin_warnings: {json.dumps(warnings)[:300]} | records naming "untrusted": {len(untrusted)}')
    checks = [
        ('mcp server graphtraj only', servers == ['graphtraj'], f'{servers}'),
        ('tools mcp__graphtraj__agents and mcp__graphtraj__tasks', all(n in tools for n in NEW), ''),
        ('no mcp__agents__* tool', not any(t.startswith(OLD_PREFIX) for t in tools), ''),
        ('no untrusted-plugin warning', not warnings and not untrusted, ''),
    ]
    for name, ok, detail in checks:
        print(f"CHECK 515 init {name}: {'PASS' if ok else 'FAIL'}{' (' + detail + ')' if detail and not ok else ''}")
    return 0 if all(ok for _, ok, _ in checks) else 1


def sizes(out: str, paths) -> int:
    lines = [f'{p.stat().st_size}\t{p}' for p in files(paths)]
    Path(out).write_text('\n'.join(lines) + ('\n' if lines else ''))
    print(f'recorded sizes of {len(lines)} record file(s) in {out}')
    return 0


def calls(label: str, args: list[str]) -> int:
    since, need, paths = {}, list(NEW), []
    while args:
        head = args.pop(0)
        if head == '--since':
            for line in Path(args.pop(0)).read_text().splitlines():
                size, _, name = line.partition('\t')
                since[name] = int(size)
        elif head == '--need':
            need = [f'mcp__graphtraj__{n}' for n in args.pop(0).split(',') if n]
        else:
            paths.append(head)
    found, results = {}, {}
    scanned = list(files(paths))
    for path in scanned:
        for record in jsonl(path, since.get(str(path), 0)):
            for item in objects(record):
                kind = item.get('type')
                if kind == 'tool_use' and str(item.get('name', '')).startswith('mcp__') and item.get('id'):
                    found.setdefault(str(item['id']), (item['name'], path))
                elif kind == 'tool_result' and item.get('tool_use_id'):
                    results.setdefault(str(item['tool_use_id']), item)
    print(f'[{label}] scanned {len(scanned)} file(s){" after the recorded sizes" if since else ""}')
    by_name: dict[str, list[str]] = {}
    for ident, (name, path) in found.items():
        result = results.get(ident)
        if result is None:
            outcome = 'no result'
        elif result.get('is_error') is True:
            outcome = 'error: ' + (text_of(result).strip().splitlines() or [''])[0][:200]
        else:
            outcome = 'ok'
        by_name.setdefault(name, []).append(outcome)
    for name, outcomes in sorted(by_name.items()):
        print(f'[{label}] calls of {name}: {len(outcomes)}; ok {outcomes.count("ok")}; others: {[o for o in outcomes if o != "ok"][:4]}')
    old = sum(len(v) for k, v in by_name.items() if k.startswith(OLD_PREFIX))
    verdicts = []
    for name in need:
        ok = by_name.get(name, []).count('ok')
        bad = [o for o in by_name.get(name, []) if o.startswith('error')]
        verdicts.append(ok > 0 and not bad)
        print(f"CHECK 515 [{label}] {name} called and answered without error or refusal: "
              f"{'PASS' if ok and not bad else 'FAIL' if found else 'NOT OBSERVED'} (ok {ok}, errors/refusals {len(bad)})")
    verdicts.append(old == 0)
    print(f"CHECK 515 [{label}] no mcp__agents__* call: {'PASS' if old == 0 else 'FAIL'} ({old})")
    return 0 if all(verdicts) else 1


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode == 'init':
        return init(sys.argv[2])
    if mode == 'sizes':
        return sizes(sys.argv[2], sys.argv[3:])
    if mode == 'calls':
        return calls(sys.argv[2], sys.argv[3:])
    print(__doc__); return 2


if __name__ == '__main__':
    sys.exit(main())
