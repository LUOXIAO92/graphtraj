"""Check the markers of Tasks 518 (graftling 0.6.1), 521 and 523 in a site-packages tree (525).

usage: markers.py <site-packages> <expect: present|absent> [<directory holding graftling/>]

Each marker is a line of dev 8267f9e5 (graphtraj) or of graftling v0.6.1 that production (515: 4ad22e90 + graftling
0.6.0) does not have, or a line production has that 8267f9e5/v0.6.1 removed. Kind 'add': the line is in the new tree.
Kind 'remove': the line is in the old tree only. Files are read as text; nothing is imported. Exit 0 only when every
marker is as expected: ``present`` for the candidate or the installed venv, ``absent`` for production now. For
git-archive trees, graftling lies in another directory: give it as the third argument (default: the site-packages).
"""
import sys
from pathlib import Path

ADD, REMOVE = 'add', 'remove'
MARKERS = [
    ('518 header-only archive lookup (graftling)', 'graftling/sessions/archive.py',
     'def _archived_header(path: Path) -> dict:', ADD),
    ('518 native_header uses it', 'graftling/sessions/archive.py',
     'header = upgrade_header(_archived_header(path))', ADD),
    ('graftling 0.6.1', 'graftling/__init__.py',
     '__version__ = "0.6.1"', ADD),
    ('graftling 0.6.0 gone', 'graftling/__init__.py',
     '__version__ = "0.6.0"', REMOVE),
    ('521 read-only role result: Worktree access from the Session records', 'graphtraj/execution/runner_results.py',
     'def session_worktree_access(session_directory: Path, mapping: Mapping[str, Any], harness_root: Path) -> str:', ADD),
    ('521 submit_result description names the own report', 'graphtraj/interfaces/tools.py',
     "'a Session with read-only Worktree access may instead name its own report already written by '", ADD),
    ('523 cleanup skips names no alias can take', 'graphtraj/execution/runner_status.py',
     'if name == alias or not ALIAS.fullmatch(name):', ADD),
    ('523 old alias-only skip gone', 'graphtraj/execution/runner_status.py',
     'if name == alias:\n', REMOVE),
]


def main() -> int:
    site, expect = Path(sys.argv[1]), sys.argv[2]
    gparent = Path(sys.argv[3]) if len(sys.argv) > 3 else site
    if expect not in ('present', 'absent'):
        print('expect must be present or absent'); return 2
    bad = 0
    for label, relative, text, kind in MARKERS:
        path = (gparent if relative.startswith('graftling/') else site) / relative
        found = path.is_file() and text in path.read_text(encoding='utf-8', errors='replace')
        new_state = found if kind == ADD else not found
        ok = new_state if expect == 'present' else not new_state
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {label} [{kind}]: line {'found' if found else 'not found'} in {path}")
    print(f"markers expected {expect}: {'PASS' if bad == 0 else 'FAIL'} ({len(MARKERS) - bad}/{len(MARKERS)})")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
