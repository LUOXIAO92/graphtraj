"""Task 513 real-host checks: read one step's retained records and print PASS/FAIL/CANNOT lines.

Usage: python -I check513.py <runtime> <step dir> <reviewer log> <path>...
Every <path> (file or directory) is scanned for the model-visible tool names.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

NEW, OLD = 'mcp__graftling__agents', 'mcp__agents__agents'
TOKEN = 'PONG-513'


def files(paths: list[str]):
    """Yield every record file under ``paths``: not the prompts (they name the tool and the token) nor this summary."""
    for path in map(Path, paths):
        found = [path] if path.is_file() else sorted(path.rglob('*')) if path.is_dir() else []
        yield from (item for item in found if item.is_file()
                    and not item.name.endswith('.prompt.txt') and item.name != 'summary.txt')


def say(state: str, text: str) -> None:
    """Print one criterion line."""
    print(f'{state} {text}')


def main() -> None:
    """Judge the names, the child, the review and the display of one step."""
    runtime, step, reviewer_log, *paths = sys.argv[1:]
    step = Path(step)

    # 1. Names the model saw, by file.
    totals = {NEW: 0, OLD: 0}
    for path in files(paths):
        text = path.read_text(errors='replace')
        counts = {name: text.count(name) for name in totals}
        if any(counts.values()):
            print(f'  names in {path}: {NEW}={counts[NEW]} {OLD}={counts[OLD]}')
        for name in totals:
            totals[name] += counts[name]
    if runtime == 'claude':
        # The init record lists exactly the tools the model was given.
        inits = [json.loads(line) for line in (step / 'stream.jsonl').read_text(errors='replace').splitlines()
                 if '"subtype":"init"' in line.replace(' ', '')]
        tools = inits[0].get('tools', []) if inits else []
        servers = [server.get('name') for server in inits[0].get('mcp_servers', [])] if inits else []
        print(f'  init mcp tools: {[tool for tool in tools if tool.startswith("mcp__")]} servers: {servers}')
        state = 'PASS' if NEW in tools and OLD not in tools else 'FAIL'
        say(state, f'model-visible tools (system init record): {NEW} listed={NEW in tools}, {OLD} listed={OLD in tools}')
    state = 'PASS' if totals[NEW] > 0 and totals[OLD] == 0 else 'FAIL'
    say(state, f'retained records name {NEW} {totals[NEW]} times and {OLD} {totals[OLD]} times')

    # 2. The child: its result reached the parent through agents (last_message carries the token).
    raw = '\n'.join(path.read_text(errors='replace') for path in files([str(step)]))
    answered = [line for line in raw.splitlines() if 'last_message' in line and TOKEN in line]
    say('PASS' if answered else 'FAIL',
        f'the created child answered {TOKEN} in an agents result (last_message): {len(answered)} record line(s)')

    # 3. Review: the reviewer was asked about other tools, never about the agents tool.
    asked = Path(reviewer_log).read_text().split() if Path(reviewer_log).is_file() else []
    print(f'  reviewer was asked about: {asked or "nothing"}')
    agents_asked = [tool for tool in asked if tool.endswith('__agents')]
    say('FAIL' if agents_asked else 'PASS', f'the reviewer was never asked about an agents tool: asked {agents_asked or "none"}')

    # 4. Display of the call.
    frames = [line for line in raw.splitlines() if '┌ ' in line or 'agents · ' in line]
    custom = raw.count('graftling:agent-communication')
    print(f'  display lines: {len(frames)}; graftling:agent-communication entries: {custom}')
    for line in frames[:4]:
        print(f'    {line[:200]}')
    if frames or custom:
        say('PASS', f'display of the agents call: {len(frames)} frame line(s), {custom} Pi display entr(y/ies)')
    else:
        say('CANNOT', 'no display frame in the retained records (see the step header for where this Runtime shows it)')


if __name__ == '__main__':
    main()
