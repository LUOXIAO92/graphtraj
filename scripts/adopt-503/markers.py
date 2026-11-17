"""Check the markers of Task 395 (graftling split) in a site-packages tree (503).

usage: markers.py <site-packages> <expect: present|absent> [<directory holding graftling/>]

Each marker is a line of dev 6115c724 (graphtraj) or of graftling v0.5.2 that production (871aaaa9, installed by 499)
does not have, or a line production has that 6115c724 removed. Kind 'add': the line is in the new tree. Kind
'remove': the line is in the old tree only. The files are read as text; nothing is imported. Exit 0 only when every
marker is as expected: ``present`` for the candidate or the installed venv (6115c724 + graftling 0.5.2), ``absent``
for production now (871aaaa9 + graftling 0.5.0). For git-archive trees, graftling lies in another directory: give it
as the third argument (default: the site-packages itself).
"""
import sys
from pathlib import Path

ADD, REMOVE = 'add', 'remove'
MARKERS = [
    ('395 graftling.mjs finds the installed graftling', 'graphtraj/runtimes/graftling.mjs',
     'export function graftlingDirectory(', ADD),
    ('395 graftling.mjs names every place looked when absent', 'graphtraj/runtimes/graftling.mjs',
     'GraphTraj cannot find the installed graftling distribution', ADD),
    ('395 Pi extension loads graftling through graftling.mjs', 'graphtraj/runtimes/pi/extension.mjs',
     "  graftlingModule('pi/extension.mjs');", ADD),
    ('395 Pi extension no longer imports the sibling path', 'graphtraj/runtimes/pi/extension.mjs',
     "from '../../../graftling/pi/extension.mjs';", REMOVE),
    ('395 DSH tool imports graftling through graftling.mjs', 'graphtraj/runtimes/dsh/tool.mjs',
     "await graftlingImport('dsh/plugin.mjs');", ADD),
    ('395 DSH tool no longer imports the sibling path', 'graphtraj/runtimes/dsh/tool.mjs',
     "from '../../../graftling/dsh/plugin.mjs';", REMOVE),
    ('395 graftling 0.5.2', 'graftling/__init__.py',
     '__version__ = "0.5.2"', ADD),
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
