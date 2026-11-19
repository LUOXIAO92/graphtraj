"""Check the markers of Tasks 526 and 527 and of graftling 0.6.2 in a site-packages tree (528).

usage: markers.py <site-packages> <expect: present|absent> [<directory holding graftling/>]

Each marker is a line of graftling v0.6.2 that production (525: graftling 0.6.1 + graphtraj 8267f9e5) does not have,
or a line production has that v0.6.2 removed. Kind 'add': the line is in the new tree. Kind 'remove': the line is in
the old tree only. Files are read as text; nothing is imported. Exit 0 only when every marker is as expected:
``present`` for the candidate or the installed venv, ``absent`` for production now. For git-archive trees, graftling
lies in another directory: give it as the third argument (default: the site-packages). GraphTraj is not reinstalled
by 528, so every marker is a graftling file.
"""
import sys
from pathlib import Path

ADD, REMOVE = 'add', 'remove'
MARKERS = [
    ('526 ignore_in_git writes .gitignore into runtime directories', 'graftling/locks.py',
     'def ignore_in_git(*directories: Path) -> None:', ADD),
    ('526 control keeps control/, live/, native/ out of git', 'graftling/control.py',
     'from graftling.locks import exclusive, ignore_in_git', ADD),
    ('526 archive keeps sessions/ out of git', 'graftling/sessions/archive.py',
     'ignore_in_git(path.parent.parent)', ADD),
    ('527 DSH client registers no AgentsRow', 'graftling/dsh/client.mjs',
     'function AgentsRow(', REMOVE),
    ('527 DSH client registers no tool.call.toolview view', 'graftling/dsh/client.mjs',
     "ctx.slots.register({ name: 'tool.call.toolview', key }, AgentsRow)", REMOVE),
    ('527 DSH package no longer injects dsh-client-ui-tool', 'graftling/dsh/package.json',
     '"@deepseek-ai/dsh-client-ui-tool"', REMOVE),
    ('graftling 0.6.2', 'graftling/__init__.py',
     '__version__ = "0.6.2"', ADD),
    ('graftling 0.6.1 gone', 'graftling/__init__.py',
     '__version__ = "0.6.1"', REMOVE),
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
        new_state = found if kind == ADD else (path.is_file() and not found)
        ok = new_state if expect == 'present' else not new_state
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {label} [{kind}]: line {'found' if found else 'not found'} in {path}"
              f"{'' if path.is_file() else ' (FILE MISSING)'}")
    print(f"markers expected {expect}: {'PASS' if bad == 0 else 'FAIL'} ({len(MARKERS) - bad}/{len(MARKERS)})")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
