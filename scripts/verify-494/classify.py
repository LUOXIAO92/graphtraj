"""Task 494: sort one repeat run's failures into double deliveries, unstarted-thread joins and others.

    python -I classify.py <repeat out-dir>

Reads ``counts.txt`` and ``failures/*.txt`` written by scripts/verify-487/repeat.py. A
double delivery is a test_dsh_standalone_child failure where one child end reached the
Main again: answered()'s ``(last, carried, [body...])`` assertion (module helper and the
embedded copy alike) or the 494 test's ``assert again == []``. A ``cannot join thread``
failure is any text with ``cannot join thread before it is started``. Prints the three
counts and the other failures' files; exits 0 only when all three are 0 and counts.txt
reports a TOTAL of 0.
"""
import re
import sys
from pathlib import Path

out      = Path(sys.argv[1])
DOUBLE   = re.compile(r"AssertionError: \(\{.*\}, \[.*\], \[['\"].+\]\)\s*$|>\s+assert again == \[\]", re.M)
JOIN     = 'cannot join thread before it is started'
doubles, joins, others = [], [], []
for path in sorted((out / 'failures').glob('*.txt')):
    text = path.read_text(encoding='utf-8', errors='replace')
    if JOIN in text:
        joins.append(path.name)
    elif 'test_dsh_standalone_child' in path.name and DOUBLE.search(text):
        doubles.append(path.name)
    else:
        others.append(path.name)

total = re.search(r'^TOTAL failed\+error (\d+)', (out / 'counts.txt').read_text(encoding='utf-8'), re.M)
print(f'double deliveries: {len(doubles)}')
print(f'cannot join thread: {len(joins)}')
print(f'other failures: {len(others)}')
for name in doubles + joins + others:
    print(f'  {name}')
print(f'counts.txt TOTAL failed+error: {total.group(1) if total else "missing"}')
sys.exit(0 if total and total.group(1) == '0' and not (doubles or joins or others) else 1)
