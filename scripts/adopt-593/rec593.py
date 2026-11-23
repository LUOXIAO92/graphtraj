"""515: MCP tool names in real Claude records (read only; never prints tool contents beyond a short error).

  rec515.py init <stream.jsonl>
      The first system/init record of a `claude -p --output-format stream-json --verbose` run. Only GraphTraj's and
      graftling's own server entries are judged (517): `graphtraj` is present and connected, and there is no `agents`
      or `graftling` entry beside it (also in plugin form `plugin:<p>:<name>`). Other servers (the user's own
      connectors, e.g. 'claude.ai Claude Docs') are listed, not judged. Tools must hold mcp__graphtraj__agents and
      mcp__graphtraj__tasks and no mcp__agents__*; plugin_warnings empty and no record naming an untrusted plugin.
      Exit 0 only when all hold.
  rec515.py calls <label> [--after <epoch seconds or ISO time>] [--need agents,tasks] <path>...
      Every MCP tool call (name mcp__<server>__<tool>) in the JSONL records under the paths, counted by its full
      name. A call is a dict with type tool_use (Claude stream/transcript) or tool-call (graftling archive) and an
      id; its result is the dict with type tool_result and the same tool_use_id. A result is a refusal or error only
      when it says so itself (is_error true); its first text line is shown (200 characters). Text matching on
      successful content is not used (514's check514.py misjudged real success records that way).
      --after keeps only calls whose own record time is after the split (517; it replaced 515's byte offsets, which
      counted pre-install turns as resumed ones). A call's time is the nearest enclosing record time: Claude's
      `timestamp` (ISO) or graftling's archive `time` (epoch ms; 0 is graftling's "missing" placeholder). The same
      id is joined across files (transcript + archive) and its earliest time is used. A call with no time anywhere
      is reported as undated: it is outside the window, except that an undated old-name call FAILs (conservative).
      Old names: server `agents` (mcp__agents__*) or the plugin form mcp__plugin_<p>_agents__*.
      PASS when: each needed mcp__graphtraj__<x> has at least one ok call in the window, no needed call in the
      window was refused, and there is no old-name call in the window and no undated old-name call.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import sys
from pathlib import Path

NEW = ('mcp__graphtraj__agents', 'mcp__graphtraj__tasks')
OLD_PREFIX = 'mcp__agents__'
OWN_SERVERS = ('graphtraj', 'agents', 'graftling')   # GraphTraj's and graftling's own entries; others are not judged


def server_of(tool: str) -> str:
    """'mcp__claude_ai_Docs__read' -> 'claude_ai_Docs'."""
    return tool[len('mcp__'):].rsplit('__', 1)[0] if tool.startswith('mcp__') else ''


def is_old(tool: str) -> bool:
    server = server_of(tool)
    return server == 'agents' or (server.startswith('plugin_') and server.endswith('_agents'))


def epoch(value: float) -> float | None:
    """Seconds since the epoch from a number (milliseconds when large); None for graftling's 0 placeholder."""
    return None if value <= 0 else value / 1000 if value > 1e11 else float(value)


def parse_time(text: str) -> float | None:
    """Epoch seconds from digits (seconds or ms) or an ISO time (UTC when no zone); None when unreadable."""
    text = text.strip()
    if text.replace('.', '', 1).isdigit():
        return epoch(float(text))
    try:
        stamp = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return None
    return (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)).timestamp()


def own_time(item: dict) -> float | None:
    """A record's own time: Claude `timestamp` (ISO) or graftling archive `time` (ms; 0 = missing)."""
    if isinstance(item.get('timestamp'), str):
        return parse_time(item['timestamp'])
    if isinstance(item.get('time'), (int, float)) and not isinstance(item.get('time'), bool):
        return epoch(item['time'])
    return None


def objects(value, when=None):
    """Every dict inside one JSON value with the nearest enclosing record time."""
    if isinstance(value, dict):
        when = own_time(value) or when
        yield value, when
        for item in value.values():
            yield from objects(item, when)
    elif isinstance(value, list):
        for item in value:
            yield from objects(item, when)


def jsonl(path: Path):
    with path.open('rb') as handle:
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
        else:
            print(f'  not readable or missing, not scanned: {path}')


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
    entries = [(s.get('name'), s.get('status')) if isinstance(s, dict) else (s, None) for s in first.get('mcp_servers') or []]
    own = [(n, st) for n, st in entries if str(n).split(':')[-1] in OWN_SERVERS]
    others = [n for n, st in entries if (n, st) not in own]
    tools = [t for t in first.get('tools') or [] if isinstance(t, str) and t.startswith('mcp__')]
    warnings = first.get('plugin_warnings') or []
    untrusted = [r.get('type') for r in records if 'untrusted' in json.dumps(r).lower()]
    print(f'init mcp_servers: {entries}')
    print(f'init GraphTraj/graftling entries (judged): {own}; other servers (listed, not judged): {others}')
    print(f'init mcp tools: {tools}')
    print(f'init plugin_warnings: {json.dumps(warnings)[:300]} | records naming "untrusted": {len(untrusted)}')
    checks = [
        ('mcp server graphtraj connected, no agents/graftling entry beside it',
         len(own) == 1 and own[0][0] == 'graphtraj' and own[0][1] in ('connected', None), f'{own}'),
        ('tools mcp__graphtraj__agents and mcp__graphtraj__tasks', all(n in tools for n in NEW), ''),
        ('no mcp__agents__* tool', not any(t.startswith(OLD_PREFIX) for t in tools), ''),
        ('no untrusted-plugin warning', not warnings and not untrusted, ''),
    ]
    for name, ok, detail in checks:
        print(f"CHECK 515 init {name}: {'PASS' if ok else 'FAIL'}{' (' + detail + ')' if detail and not ok else ''}")
    return 0 if all(ok for _, ok, _ in checks) else 1


def stamp(when: float | None) -> str:
    return datetime.fromtimestamp(when, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ') if when else 'undated'


def calls(label: str, args: list[str]) -> int:
    after, need, paths = None, list(NEW), []
    while args:
        head = args.pop(0)
        if head == '--after':
            value = args.pop(0)
            after = parse_time(value)
            if after is None:
                print(f'[{label}] --after {value!r} is not an epoch or ISO time'); return 2
        elif head == '--need':
            need = [f'mcp__graphtraj__{n}' for n in args.pop(0).split(',') if n]
        else:
            paths.append(head)
    found: dict[str, list] = {}     # id -> [name, earliest time]
    results: dict[str, dict] = {}
    scanned = list(files(paths))
    for path in scanned:
        for record in jsonl(path):
            for item, when in objects(record):
                kind = item.get('type')
                if kind in ('tool_use', 'tool-call') and str(item.get('name', '')).startswith('mcp__') and item.get('id'):
                    entry = found.setdefault(str(item['id']), [item['name'], None])
                    if when and (entry[1] is None or when < entry[1]):
                        entry[1] = when
                elif kind == 'tool_result' and item.get('tool_use_id'):
                    ident = str(item['tool_use_id'])
                    if ident not in results or item.get('is_error') is True:
                        results[ident] = item
    print(f'[{label}] scanned {len(scanned)} file(s); split: '
          f'{"after " + stamp(after) + f" ({after:.0f})" if after else "none (every call)"}')
    window: dict[str, list[str]] = {}
    before: dict[str, int] = {}
    undated: dict[str, int] = {}
    for ident, (name, when) in found.items():
        if after is not None and when is None:
            undated[name] = undated.get(name, 0) + 1
            continue
        if after is not None and when <= after:
            before[name] = before.get(name, 0) + 1
            continue
        result = results.get(ident)
        if result is None:
            outcome = 'no result'
        elif result.get('is_error') is True:
            first = (text_of(result).strip().splitlines() or [''])[0][:200]
            # 579 (571 F2): graftling's `not-running` answers a supported call on an Agent with nothing pending
            # ("no native request is pending"); it informs, it is no refusal, so it is reported and not counted.
            outcome = ('info: ' if 'not-running' in text_of(result) else 'error: ') + first
        else:
            outcome = 'ok'
        window.setdefault(name, []).append(outcome)
    if after is not None:
        print(f'[{label}] calls at or before the split (not judged): {dict(sorted(before.items())) or "none"}')
        print(f'[{label}] undated calls (no record time in any file): {dict(sorted(undated.items())) or "none"}')
    for name, outcomes in sorted(window.items()):
        print(f'[{label}] calls of {name}{" after the split" if after else ""}: {len(outcomes)}; ok {outcomes.count("ok")}; '
              f'others: {[o for o in outcomes if o != "ok"][:4]}')
    old_times = sorted(stamp(w) for i, (n, w) in found.items() if is_old(n) and (after is None or w is None or w > after))
    old = sum(len(v) for k, v in window.items() if is_old(k))
    old_undated = sum(v for k, v in undated.items() if is_old(k))
    verdicts = []
    for name in need:
        ok = window.get(name, []).count('ok')
        bad = [o for o in window.get(name, []) if o.startswith('error')]
        verdicts.append(ok > 0 and not bad)
        print(f"CHECK 515 [{label}] {name} called and answered without error or refusal: "
              f"{'PASS' if ok and not bad else 'FAIL' if found else 'NOT OBSERVED'} (ok {ok}, errors/refusals {len(bad)})")
    verdicts.append(old == 0 and old_undated == 0)
    print(f"CHECK 515 [{label}] no mcp__agents__* call{' after the split' if after else ''}: "
          f"{'PASS' if old == 0 and old_undated == 0 else 'FAIL'} ({old} in the window, {old_undated} undated"
          f"{'; times ' + str(old_times[:6]) if old_times else ''})")
    return 0 if all(verdicts) else 1


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode == 'init':
        return init(sys.argv[2])
    if mode == 'calls':
        return calls(sys.argv[2], sys.argv[3:])
    print(__doc__); return 2


if __name__ == '__main__':
    sys.exit(main())
