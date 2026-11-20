"""Check the markers of Task 531's two fixes in a site-packages tree (532).

usage: markers.py <site-packages | directory holding graphtraj/> <expect: present|absent>

Each marker is a line of GraphTraj a7b20447 that production (528: graphtraj 8267f9e5 + graftling 0.6.2) does not
have, or a line production has that a7b20447 removed. Kind 'add': the line is in the new tree. Kind 'remove': the line
is in the old tree only. Files are read as text; nothing is imported. Exit 0 only when every marker is as expected:
``present`` for the candidate or the installed venv, ``absent`` for production now. graftling is not changed by 532,
so every marker is a graphtraj file.

  496cec58: a Claude child's preflight reads the project history only when a grant overlaps a protected path
            (runtimes/claude/adapter.py).
  805ec01b: the caller lookup skips Sessions whose owner lock is not held (execution/runner_heartbeat.py
            any_ownership_held; execution/runner_status.py uses it).
"""
import sys
from pathlib import Path

ADD, REMOVE = 'add', 'remove'
MARKERS = [
    ('531 805ec01b any_ownership_held in runner_heartbeat', 'graphtraj/execution/runner_heartbeat.py',
     'def any_ownership_held(directory: Path) -> bool:', ADD),
    ('531 805ec01b runner_status imports any_ownership_held', 'graphtraj/execution/runner_status.py',
     'from graphtraj.execution.runner_heartbeat import any_ownership_held, ownership_is_held, read_heartbeat', ADD),
    ('531 805ec01b caller lookup skips Sessions without a held owner lock', 'graphtraj/execution/runner_status.py',
     'or not any_ownership_held(session_record_directory(runner_directory, alias))):', ADD),
    ('531 496cec58 preflight reads history lazily', 'graphtraj/runtimes/claude/adapter.py',
     '\n    history = None\n', ADD),
    ('531 496cec58 history no longer read for every grant', 'graphtraj/runtimes/claude/adapter.py',
     '\n    history = project_history_files(root)\n', REMOVE),
]


def main() -> int:
    site, expect = Path(sys.argv[1]), sys.argv[2]
    if expect not in ('present', 'absent'):
        print('expect must be present or absent'); return 2
    bad = 0
    for label, relative, text, kind in MARKERS:
        path = site / relative
        found = path.is_file() and text in path.read_text(encoding='utf-8', errors='replace')
        new_state = found if kind == ADD else (path.is_file() and not found)
        ok = new_state if expect == 'present' else not new_state
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {label} [{kind}]: line {'found' if found else 'not found'} in {path}"
              f"{'' if path.is_file() else ' (FILE MISSING)'}")
    print(f"markers expected {expect}: {'PASS' if bad == 0 else 'FAIL'} ({len(MARKERS) - bad}/{len(MARKERS)})")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
