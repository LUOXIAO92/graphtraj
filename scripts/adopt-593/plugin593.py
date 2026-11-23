"""593 V/I: is the difference between production's and the candidate's graphtraj-claude-host plugin exactly 591/592's?

usage: plugin593.py <production plugin directory> <candidate plugin directory>

Production's copy was written by `configuration --write` from graftling 0.8.0 + graphtraj eb009725 (579). The candidate
is written the same way from graftling 0.9.0 + graphtraj 3eb21101. Predicted from the diffs (and seen when the 0.9.0
wheel regenerates a copy 0.8.0 wrote, in the rehearsal):
  - hooks/hooks.json: SAME ({"modules": ["./host_context.mjs"]}; no matcher lives there).
  - .claude-plugin/plugin.json: only the description, 592's runtimes/claude/host.py: "... for the agents and tasks MCP
    entries." -> "... for the subagents and tasks MCP entries.".
  - hooks/host_context.mjs: exactly 591's lines (const TOOL = "subagents", TOOLS = [TOOL, "tasks"] written by
    claude/plugin.py, the plugin PREFIX, the display and log labels, the request test `name === TOOL`).
Read only. Exit 0 = exactly that; 1 = anything else (V STOPs); 2 = the copies are identical (the prediction is wrong).
"""
import difflib
import json
import sys
from pathlib import Path

DESCRIPTION = ('GraphTraj Main host context for the agents and tasks MCP entries.',
               'GraphTraj Main host context for the subagents and tasks MCP entries.')
REMOVED = [
    '/** Native context and human-only observation for the external agents entry.',
    '// the written copy with the tools a package declares beside agents.',
    'const TOOLS = ["agents", "tasks"];',
    '// .mcp.json (configuration --write). The marketplace copy names its plugin,',
    '// whose tools Claude Code calls mcp__plugin_<plugin>_agents__<tool>.',
    'const PREFIX = PLUGIN ? `mcp__plugin_${PLUGIN}_agents__` : `mcp__${SERVER}__`;',
    "  return [`┌ agents · ${frame.from} → ${frame.to}`, ...frame.body.split(/\\r?\\n/).map((line) => '│ ' + line),",
    "        ? Text({children: [Text({dimColor: true, children: ['agents → ']}), Text({bold: true, children: [frame.to]})]})",
    "    if (!python || !config) throw new Error('Native agents host configuration is missing.');",
    "        try { await $.ui.log('agents context cleanup failed: ' + String(error)); } catch {}",
    '    await $.ui.log(`agents · current Session ${session}`);',
    "        const request = name === 'agents' && event.action === 'execute'",
    "      : {deny: 'The native agents context hook failed; no call was authorized.'});",
    "    catch (error) { $.ui.log('agents context cleanup failed: ' + String(error)); }",
]
ADDED = [
    '/** Native context and human-only observation for the external subagents entry.',
    "// graftling's own MCP tool, the only one whose exchange this module renders. It",
    '// is graftling.tool.TOOL_NAME; graftling.claude.plugin refuses a copy whose',
    '// line differs, so the two cannot drift.',
    'const TOOL = "subagents";',
    '// the written copy with the tools a package declares beside TOOL.',
    'const TOOLS = [TOOL, "tasks"];',
    '// .mcp.json (configuration --write). The marketplace copy names its plugin. Its',
    '// server key is TOOL (claude-plugin/.claude-plugin/plugin.json), so Claude Code',
    '// calls its tools mcp__plugin_<plugin>_subagents__<tool>.',
    'const PREFIX = PLUGIN ? `mcp__plugin_${PLUGIN}_${TOOL}__` : `mcp__${SERVER}__`;',
    "  return [`┌ subagents · ${frame.from} → ${frame.to}`, ...frame.body.split(/\\r?\\n/).map((line) => '│ ' + line),",
    "        ? Text({children: [Text({dimColor: true, children: ['subagents → ']}), Text({bold: true, children: [frame.to]})]})",
    "    if (!python || !config) throw new Error('Native subagents host configuration is missing.');",
    "        try { await $.ui.log('subagents context cleanup failed: ' + String(error)); } catch {}",
    '    await $.ui.log(`subagents · current Session ${session}`);',
    "        const request = name === TOOL && event.action === 'execute'",
    "      : {deny: 'The native subagents context hook failed; no call was authorized.'});",
    "    catch (error) { $.ui.log('subagents context cleanup failed: ' + String(error)); }",
]


def lines_changed(old: Path, new: Path) -> tuple[list[str], list[str]]:
    removed, added = [], []
    for line in difflib.unified_diff(old.read_text(encoding='utf-8').splitlines(),
                                     new.read_text(encoding='utf-8').splitlines(), lineterm='', n=0):
        if not line.startswith(('---', '+++', '@@')):
            (removed if line.startswith('-') else added).append(line[1:])
    return removed, added


def main() -> int:
    old, new = Path(sys.argv[1]), Path(sys.argv[2])
    names = sorted({str(p.relative_to(d)) for d in (old, new) for p in d.rglob('*') if p.is_file()})
    changed = [n for n in names if not ((old / n).is_file() and (new / n).is_file()
                                        and (old / n).read_bytes() == (new / n).read_bytes())]
    print(f'plugin files: {names} | changed: {changed}')
    if not changed:
        print('CHECK 593 plugin differs by exactly 591/592 (hook module lines, plugin.json description): FAIL '
              '(no difference; the prediction expected one)')
        return 2
    ok = changed == ['.claude-plugin/plugin.json', 'hooks/host_context.mjs']
    if '.claude-plugin/plugin.json' in changed and (old / '.claude-plugin/plugin.json').is_file() \
            and (new / '.claude-plugin/plugin.json').is_file():
        a = json.loads((old / '.claude-plugin/plugin.json').read_text())
        b = json.loads((new / '.claude-plugin/plugin.json').read_text())
        keys = sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))
        print(f"plugin.json keys changed: {keys} | description: {a.get('description')!r} -> {b.get('description')!r}")
        ok = ok and keys == ['description'] and (a.get('description'), b.get('description')) == DESCRIPTION
    if 'hooks/host_context.mjs' in changed and (old / 'hooks/host_context.mjs').is_file() \
            and (new / 'hooks/host_context.mjs').is_file():
        removed, added = lines_changed(old / 'hooks/host_context.mjs', new / 'hooks/host_context.mjs')
        print(f'host_context.mjs differences: removed {len(removed)} line(s), added {len(added)} line(s)')
        for line in removed: print(f'  - {line.strip()[:140]}')
        for line in added: print(f'  + {line.strip()[:140]}')
        ok = ok and removed == REMOVED and added == ADDED
    print(f"CHECK 593 plugin differs by exactly 591/592 (hook module lines, plugin.json description): "
          f"{'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
