"""532 GR: judge the reused full suite of Task 531 (G at 83e84fba with the graftling wheel of 4a002129). Read only.

usage: greuse532.py <531 G directory> <expected candidate commit> <expected graftling commit>

532 runs no suite of its own (Leader decision): `git diff 83e84fba a7b20447 -- src tests plugins pyproject.toml` is
empty, so 531's G tested the same product and tests, with graftling from git archive 4a002129 = production's 0.6.2.
steps.zsh checks the diff; this script reads 531's G record: run.txt names the candidate and the graftling commit;
suite.txt carries the totals and 'exit='; every FAILED/ERROR line in suite.txt, shards/*.log and shards/failures.txt
is listed. Prints 'CHECK 532 reused G (531 83e84fba) no failure: PASS' only when the candidate and graftling commits
are the expected ones, the totals name passed tests and no failed/error, the run ended with exit=0 and no FAILED or
ERROR line exists. Anything else is FAIL (a known 516 failure would be reported here and judged by the Leader).
"""
import re
import sys
from pathlib import Path


def main() -> int:
    g, candidate, graftling = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    problems = []
    run = (g / 'run.txt').read_text(errors='replace') if (g / 'run.txt').is_file() else ''
    suite = (g / 'suite.txt').read_text(errors='replace') if (g / 'suite.txt').is_file() else ''
    if not run or not suite:
        problems.append(f'run.txt or suite.txt missing in {g}')
    m = re.search(r'^candidate: ([0-9a-f]{40}) \| graftling ([0-9a-f]{40})', run, re.M)
    got_candidate, got_graftling = (m.group(1), m.group(2)) if m else ('not found', 'not found')
    print(f'reused G: {g}')
    print(f'candidate: {got_candidate} (expected {candidate}): {"yes" if got_candidate == candidate else "NO"}')
    print(f'graftling commit of the wheel: {got_graftling} (expected {graftling} = production 0.6.2): '
          f'{"yes" if got_graftling == graftling else "NO"}')
    if got_candidate != candidate:
        problems.append('candidate is not the expected commit')
    if got_graftling != graftling:
        problems.append('graftling commit is not the expected one')
    totals = [line for line in suite.splitlines() if re.search(r'\d+ (passed|failed|error)', line)]
    total = totals[-1].strip() if totals else 'none'
    exits = re.findall(r'^exit=(\d+)$', suite, re.M)
    print(f'totals: {total} | exit: {exits[-1] if exits else "none (run not ended)"}')
    if not re.search(r'\d+ passed', total) or re.search(r'\d+ (failed|errors?)\b', total):
        problems.append(f'totals {total!r}')
    if exits[-1:] != ['0']:
        problems.append(f'exit {exits[-1] if exits else "missing"}')
    failing = []
    sources = [g / 'suite.txt', *sorted((g / 'shards').glob('*.log')), g / 'shards' / 'failures.txt']
    for source in sources:
        if source.is_file():
            for line in source.read_text(errors='replace').splitlines():
                if re.match(r'(FAILED|ERROR) ', line):
                    failing.append(f'{source.name}: {line[:200]}')
    print(f'FAILED/ERROR lines (suite.txt, shards/*.log, failures.txt): {len(failing)}')
    for line in failing:
        print(f'  {line}')
    if failing:
        problems.append(f'{len(failing)} FAILED/ERROR lines')
    for problem in problems:
        print(f'  problem: {problem}')
    print(f"CHECK 532 reused G (531 {candidate[:8]}) no failure: {'PASS' if not problems else 'FAIL'}")
    return 0 if not problems else 1


if __name__ == '__main__':
    sys.exit(main())
