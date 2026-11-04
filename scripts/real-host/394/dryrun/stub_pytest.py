#!/usr/bin/env python3
"""Stand in for a step-30 tree's `python -m pytest ... -rA <test>` in the 394 dry run. Never used on a real run.

The tree is the directory three levels above this link (<tree>/venv/bin/python). <tree>/stub-fails.txt holds
lines `<variant> <n>`: that variant fails in the first n runs. <tree>/stub-runs counts the runs.
"""
from pathlib import Path
import sys

tree = Path(sys.argv[0]).absolute().parent.parent.parent
runs_file = tree / 'stub-runs'
run = int(runs_file.read_text()) + 1 if runs_file.exists() else 1
runs_file.write_text(str(run))
fails = dict(line.split() for line in (tree / 'stub-fails.txt').read_text().splitlines() if line.strip())
test = sys.argv[-1]
failed = 0
for variant in ('raised-RUNTIME_REQUEST_FAILED', 'cancelled'):
    bad = run <= int(fails.get(variant, 0))
    failed += bad
    print(f"{'FAILED' if bad else 'PASSED'} {test}[{variant}]" + (' - RuntimeError: Codex initialize request 1 timed out' if bad else ''))
print(f'{failed} failed, {2 - failed} passed in 0.01s' if failed else '2 passed in 0.01s')
sys.exit(1 if failed else 0)
