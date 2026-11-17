"""499 S: is a test suite running? Decided from argv tokens, never from path substrings. Read only.

usage: busy499.py <ps listing: `ps -axww -o pid=,ppid=,etime=,command=`> <own root pid> <job pattern> <test venv pattern>

A process RUNS A SUITE when its argv (the command split on blanks) has:
  - an executable whose basename is `pytest` or `py.test`, or
  - `-m pytest` (or `-mpytest`), or
  - an argument whose basename is `run_test_shards.py`.
The own root pid and its descendants (S's own job, its ps and this script) are excluded.
`ours` (another S of ours is running; S refuses): a process (outside the own subtree) whose command holds the job
pattern (`<steps.zsh> _Srun`), or one that RUNS A SUITE and holds the test venv pattern (`<svenv>/bin/`).
497 defect (d), fixed here: 497 counted every process naming the test venv as ours, so leftover processes of S's own
test venv (an installed-environment budget_idle_timer or a Worker an earlier S left) refused a rerun. They are now
leftovers: listed as information, never counted as a running suite, never signalled.
Other processes whose command names a `pytest-of-*` directory are leftovers of earlier test runs too.
Prints `running suites: n`, `ours: n`, `leftover test processes (...): n` with pid, etime, command. Exit 0.
"""
import os, sys


def runs_suite(command: str) -> bool:
    tokens = command.split()
    if not tokens:
        return False
    if os.path.basename(tokens[0]) in ('pytest', 'py.test'):
        return True
    for i, token in enumerate(tokens):
        if token == '-mpytest' or (token == '-m' and i + 1 < len(tokens) and tokens[i + 1] == 'pytest'):
            return True
        if os.path.basename(token) == 'run_test_shards.py':
            return True
    return False


def main(argv: list[str]) -> int:
    rows = []
    for line in open(argv[0], errors='replace'):
        w = line.split(None, 3)
        if len(w) == 4 and w[0].isdigit():
            rows.append((w[0], w[1], w[2], w[3].rstrip('\n')))
    own = {argv[1]} if len(argv) > 1 else set()
    grew = True
    while grew:
        grew = False
        for pid, ppid, _, _ in rows:
            if ppid in own and pid not in own:
                own.add(pid); grew = True
    job = argv[2] if len(argv) > 2 and argv[2] else None
    venv = argv[3] if len(argv) > 3 and argv[3] else None
    others = [r for r in rows if r[0] not in own]
    running = [r for r in others if runs_suite(r[3])]
    ours = [r for r in others if (job and job in r[3]) or (venv and venv in r[3] and runs_suite(r[3]))]
    leftover = [r for r in others if ('/pytest-of-' in r[3] or (venv and venv in r[3]))
                and r not in running and r not in ours]
    print(f'running suites: {len(running)}')
    for pid, _, etime, command in running:
        print(f'  running: {pid} {etime} {command[:200]}')
    print(f'ours: {len(ours)}')
    for pid, _, etime, command in ours:
        print(f'  ours: {pid} {etime} {command[:200]}')
    print(f'leftover test processes (information; never signalled; not a running suite): {len(leftover)}')
    for pid, _, etime, command in leftover:
        print(f'  leftover: {pid} {etime} {command[:200]}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
