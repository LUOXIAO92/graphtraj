"""579 V/I: is the difference between production's and the candidate's plugin hooks/host_context.mjs exactly 577's?

usage: plugin579.py <production host_context.mjs> <candidate host_context.mjs>

graftling 0.7.0..0.8.0 changes claude/host_context.mjs in one place (577): the plugin host's `context` command gains
`--data-root <GRAFTLING_DATA_ROOT>` when that variable is set. production's graphtraj-claude-host copy is written from
that module, so the regenerated copy must differ by exactly these lines and nothing else. Read only. Exit 0 = exactly
577's change, 1 = anything else (V STOPs), 2 = the files are identical (the prediction is wrong the other way).
"""
import difflib
import sys
from pathlib import Path

REMOVED = ["      '--project-from', await $.session.cwd()];"]
ADDED = ["    // GRAFTLING_DATA_ROOT holds the plugin host's configuration when set (577).",
         "    const dataRoot = await $.env.get('GRAFTLING_DATA_ROOT');",
         "      '--project-from', await $.session.cwd(), ...(dataRoot ? ['--data-root', dataRoot] : [])];"]

old = Path(sys.argv[1]).read_text(encoding='utf-8').splitlines()
new = Path(sys.argv[2]).read_text(encoding='utf-8').splitlines()
removed, added = [], []
for line in difflib.unified_diff(old, new, lineterm='', n=0):
    if line.startswith(('---', '+++', '@@')):
        continue
    (removed if line.startswith('-') else added).append(line[1:])
print(f'host_context.mjs differences: removed {len(removed)} line(s), added {len(added)} line(s)')
for line in removed: print(f'  - {line.strip()[:140]}')
for line in added: print(f'  + {line.strip()[:140]}')
if not removed and not added:
    print('CHECK 579 plugin hooks/host_context.mjs differs by exactly 577\'s --data-root change: FAIL (no difference; '
          'the prediction expected one)')
    sys.exit(2)
ok = removed == REMOVED and added == ADDED
print(f"CHECK 579 plugin hooks/host_context.mjs differs by exactly 577's --data-root change: {'PASS' if ok else 'FAIL'}")
sys.exit(0 if ok else 1)
