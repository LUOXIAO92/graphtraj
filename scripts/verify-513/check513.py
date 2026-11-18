"""Task 513 real-host checks: read one step's retained records and print PASS/FAIL/CANNOT lines.

Usage: python -I check513.py <runtime> <step dir> <reviewer log> <path>...
Every <path> (file or directory) is scanned for the model-visible tool names.
Child criterion (513 task.md): one agents call created a child and was not stopped by review. PONG-513 (the
child's answer) is printed as information, not judged (517).
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

NEW, OLD = 'mcp__graftling__agents', 'mcp__agents__agents'
TOKEN = 'PONG-513'
# Files steps.zsh writes itself: its inputs, configuration and diagnostic printouts. They are not Runtime
# records (client-view-keys.txt lists the old key on purpose, the prompts name the tool and the token),
# so no check reads them. client-view-keys.txt stays in the step directory as display evidence.
STEP_FILES = {'summary.txt', 'run.txt', 'client-view-keys.txt', 'reviewer.log', 'config.yml', 'mcp.json',
              'claude-host.json', 'codex-settings.json', 'pi-host.json', 'dsh-host.json', 'dsh-main.patch.yml'}


def files(paths: list[str]):
    """Yield every Runtime record file under ``paths``, leaving out the step's own files (STEP_FILES, prompts)."""
    for path in map(Path, paths):
        found = [path] if path.is_file() else sorted(path.rglob('*')) if path.is_dir() else []
        for item in found:
            if item.name.endswith('.prompt.txt') or item.name in STEP_FILES:
                continue
            try:
                if item.is_file():
                    item.read_bytes()[:0]
                    yield item
            except OSError as error:
                # A retained symlink into a directory this process may not read (named, never silent).
                print(f'  unreadable, not scanned: {item} ({error.strerror})')


def display_entries(path: Path) -> int:
    """Count the Pi display's Session entries: type ``custom``, customType graftling:agent-communication."""
    count = 0
    for line in path.read_text(errors='replace').splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        count += isinstance(entry, dict) and entry.get('type') == 'custom' \
            and entry.get('customType') == 'graftling:agent-communication'
    return count


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

    # 2. The child (Task 513 criterion: one agents call created a child; review is check 3). graftling writes
    # <data>/control/agents/<agent>.json when create succeeds, and the parent's own Runtime records (outside
    # data/) must hold that agent id, i.e. the create result reached the parent. The child's reply token is
    # informational only: a Claude child under native permission mode `default` may wait for a native
    # permission answer that the host prompt never gives (513 Leader report), which is not a review stop.
    raw = '\n'.join(path.read_text(errors='replace') for path in files([str(step)]))
    control = step / 'data' / 'control' / 'agents'
    children = sorted(p.stem for p in control.glob('agent-*.json')) if control.is_dir() else []
    parent_text = '\n'.join(path.read_text(errors='replace') for path in files([str(step)])
                            if 'data' not in path.relative_to(step).parts)
    created = [child for child in children if child in parent_text]
    say('PASS' if created else 'FAIL',
        f'an agents create call made a child and returned it to the parent: control records {children or "none"}; '
        f'named in the parent records: {created or "none"}')
    answered = [line for line in raw.splitlines() if 'last_message' in line and TOKEN in line]
    print(f'  info (not a criterion): the child answered {TOKEN} in an agents result (last_message): '
          f'{len(answered)} record line(s)')

    # 3. Review: the reviewer was asked about other tools, never about the agents tool.
    asked = Path(reviewer_log).read_text().split() if Path(reviewer_log).is_file() else []
    print(f'  reviewer was asked about: {asked or "nothing"}')
    agents_asked = [tool for tool in asked if tool.endswith('__agents')]
    say('FAIL' if agents_asked else 'PASS', f'the reviewer was never asked about an agents tool: asked {agents_asked or "none"}')

    # 4. Display of the call.
    frames = [line for line in raw.splitlines() if '┌ ' in line or 'agents · ' in line]
    # Pi notices share the customType as custom_message entries; only `custom` entries are the display.
    custom = sum(display_entries(path) for path in files([str(step)]) if path.suffix == '.jsonl')
    print(f'  display lines: {len(frames)}; graftling:agent-communication entries: {custom}')
    for line in frames[:4]:
        print(f'    {line[:200]}')
    if frames or custom:
        say('PASS', f'display of the agents call: {len(frames)} frame line(s), {custom} Pi display entr(y/ies)')
    else:
        say('CANNOT', 'no display frame in the retained records (see the step header for where this Runtime shows it)')


if __name__ == '__main__':
    main()
