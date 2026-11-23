"""593: read-only search for graftling's old tool and command names (591 renamed agents to subagents, no alias).

usage: scan593.py live <harness> <label>
       scan593.py home <file>...

live: searches the Harness's live configuration and its real launch scripts and wrappers, prints file:line for each
  hit and keeps live configuration apart from history (scripts/verify-*, scripts/adopt-*, archives, evidence, backups).
  Files searched, when they exist (each is listed with 'searched' or 'absent'):
    .graphtraj/core/roles.yml and every other .graphtraj/core/*.yml, .graphtraj/swarm/config.yml,
    docs/agents/roles/* (text), .mcp.json, .claude/settings*.json, .codex/config.toml, .codex/hooks.json,
    .graphtraj/claude-host/config.json, the hook copy .claude/skills/graphtraj-claude-host/** (written by
    configuration --write), and launch scripts or wrappers: *.sh, *.zsh, *.command files directly in the Harness and
    in its bin/, scripts/ and tools/ directories (non-recursive), plus the text console scripts in .venv-runtime/bin.
  It also lists the console script NAMES in .venv-runtime/bin (agents, agents-mcp, subagents, subagents-mcp).
  The last line is a REPORT with the live configuration hits and the docs hits counted apart (the Harness docs are
  Main's to update after the adoption; this Task does not edit them). Exit 0 always: the step judges.
home: the USER's own files (~/.claude/settings.json, ~/.claude.json). Prints ONLY the matching strings with the JSON
  key path that holds them (never any other value). Exit 0 always.

Old names (graftling <= 0.8.0): mcp__graphtraj__agents, mcp__graftling__agents, mcp__plugin_<p>_agents__agents (and any
mcp__<server>__agents), allowedTools/tools/disallowed_tools values naming agents, and the commands agents-mcp and
bin/agents. 'subagents', 'agents-context', '.agents-control', 'control/agents' and DSH's 'agents' plugin id are not old
names (PUBLIC_API section 7: unchanged).
"""
import json
import re
import sys
from pathlib import Path

WORD = r'(?<![\w.-])agents(?![\w-])'
PATTERNS = [
    ('old MCP tool name', re.compile(r'mcp__[A-Za-z0-9_-]+?__agents(?![\w-])')),
    ('old plugin server form', re.compile(r'mcp__plugin_[A-Za-z0-9_-]+_agents__')),
    ('tool list naming agents', re.compile(r'(?i)(allowed_?tools|disallowed_?tools|"tools"|\btools)\s*[:=].*' + WORD)),
    ('old command agents-mcp', re.compile(r'(?<![\w.-])agents-mcp(?![\w-])')),
    ('old command bin/agents', re.compile(r'bin/agents(?![\w-])')),
]
HISTORY = ('/scripts/verify-', '/scripts/adopt-', '/scripts/realhost-', '/scripts/real-host', '/archive', '/evidence',
           '/backup', '/state/', '/sessions/', '/tmp/')


def hits(text: str) -> list[tuple[int, str, str]]:
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        for label, pattern in PATTERNS:
            if pattern.search(line):
                found.append((number, label, line.strip()[:200]))
                break
    return found


def text_of(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b'\0' in data[:4096]:
        return None
    return data.decode('utf-8', errors='replace')


def live(harness: Path, label: str) -> int:
    named = [harness / '.graphtraj/core/roles.yml', *sorted((harness / '.graphtraj/core').glob('*.yml')),
             harness / '.graphtraj/swarm/config.yml', harness / '.mcp.json',
             *sorted((harness / '.claude').glob('settings*.json')), harness / '.codex/config.toml',
             harness / '.codex/hooks.json', harness / '.graphtraj/claude-host/config.json']
    named += sorted(p for p in (harness / 'docs/agents/roles').rglob('*') if p.is_file())
    named += sorted(p for p in (harness / '.claude/skills/graphtraj-claude-host').rglob('*') if p.is_file())
    launch = []
    for directory in (harness, harness / 'bin', harness / 'scripts', harness / 'tools'):
        if directory.is_dir():
            launch += sorted(p for p in directory.iterdir() if p.is_file() and p.suffix in ('.sh', '.zsh', '.command'))
    runtime_bin = harness / '.venv-runtime/bin'
    if runtime_bin.is_dir():
        launch += sorted(p for p in runtime_bin.iterdir() if p.is_file() and not p.name.startswith(('python', 'activate')))
    seen, counts = set(), {'live': 0, 'docs': 0, 'history': 0}
    print(f'[{label}] launch scripts and wrappers found: '
          f'{[str(p.relative_to(harness)) for p in launch if not str(p).startswith(str(runtime_bin))] or "none"}'
          f' (+ {sum(1 for p in launch if str(p).startswith(str(runtime_bin)))} files in .venv-runtime/bin)')
    names = sorted(p.name for p in runtime_bin.iterdir()) if runtime_bin.is_dir() else []
    print(f"[{label}] .venv-runtime/bin console scripts: "
          f"{[n for n in names if n in ('agents', 'agents-mcp', 'subagents', 'subagents-mcp')]}")
    for path in [*named, *launch]:
        if path in seen:
            continue
        seen.add(path)
        text = text_of(path) if path.is_file() else None
        relative = str(path.relative_to(harness)) if path.is_relative_to(harness) else str(path)
        if text is None:
            if not path.is_relative_to(runtime_bin):
                print(f'[{label}] {"absent" if not path.exists() else "not text"}: {relative}')
            continue
        kind = ('history' if any(h in '/' + relative for h in HISTORY)
                else 'docs' if relative.startswith('docs/') else 'live')
        found = hits(text)
        if not path.is_relative_to(runtime_bin):
            print(f'[{label}] searched: {relative} ({kind}; hits {len(found)})')
        for number, why, line in found:
            counts[kind] += 1
            print(f'  {kind.upper()} {relative}:{number}: [{why}] {line}')
    print(f"REPORT 593 old-name scan [{label}]: live configuration hits {counts['live']} | docs hits {counts['docs']} "
          f"(Main updates the Harness docs after the adoption) | history hits {counts['history']}")
    return 0


def walk(value: object, path: str):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from walk(item, f'{path}.{key}' if path else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk(item, f'{path}[{index}]')
    elif isinstance(value, str):
        yield path, value


def home(files: list[str]) -> int:
    total = 0
    for name in files:
        path = Path(name)
        try:
            document = json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            print(f'absent: {path}'); continue
        except (OSError, ValueError) as error:
            print(f'unreadable: {path} ({type(error).__name__})'); continue
        matched = [(key, text) for key, text in walk(document, '')
                   if any(pattern.search(text) for _, pattern in PATTERNS) or re.fullmatch(WORD, text)
                   and re.search(r'(?i)tools', key)]
        total += len(matched)
        print(f'{path}: matching strings {len(matched)}')
        for key, text in matched:
            print(f'  {key}: {text[:200]}')
    print(f'REPORT 593 USER allow rules naming the old tool or commands: {total}')
    return 0


if __name__ == '__main__':
    if len(sys.argv) >= 4 and sys.argv[1] == 'live':
        sys.exit(live(Path(sys.argv[2]), sys.argv[3]))
    if len(sys.argv) >= 3 and sys.argv[1] == 'home':
        sys.exit(home(sys.argv[2:]))
    print(__doc__)
    sys.exit(2)
