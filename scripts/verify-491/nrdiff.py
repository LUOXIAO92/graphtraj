"""Task 491 NR: compare a replayed nr492.py output with the CHECK lines 492 recorded in raw-9faa0274/Nr.txt.

    python -I nrdiff.py <recorded Nr.txt> <replay output>

Each replayed CHECK line is matched to the recorded line with the same label (text before ': <status>').
PASS NR when the 487 first-wait check is now PASS and every other replayed CHECK line equals its recorded line.
"""
import re
import sys
from pathlib import Path

LINE = re.compile(r'^CHECK (.*?): (PASS|FAIL|BLOCKED|PENDING|NOT OBSERVED|CHECK BY HAND|BY THE)')
FIRST = '487 first wait timed out while the child ran'


def checks(path: str) -> dict[str, str]:
    out = {}
    for line in Path(path).read_text(errors='replace').splitlines():
        match = LINE.match(line)
        if match:
            out.setdefault(match.group(1), line)
    return out


recorded, replay = checks(sys.argv[1]), checks(sys.argv[2])
same, changed, first = 0, [], None
for label, line in replay.items():
    old = recorded.get(label)
    if label.startswith(FIRST):
        first = (old, line)
    elif old == line:
        same += 1
    else:
        changed.append((label, old, line))
print(f'replayed CHECK lines {len(replay)}: identical to 492 recorded {same}; other changes {len(changed)}')
for label, old, new in changed:
    print(f'  CHANGED {label}\n    492: {old}\n    now: {new}')
if first:
    print(f'  487 first wait\n    492: {first[0]}\n    now: {first[1]}')
ok = bool(first) and ': PASS' in first[1] and not changed and bool(replay)
print('PASS NR: the 487 first-wait check is PASS and the other checks are unchanged' if ok
      else 'FAIL NR: see the lines above')
sys.exit(0 if ok else 1)
