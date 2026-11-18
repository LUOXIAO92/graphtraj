"""Check the markers of Task 514 (MCP server name graphtraj) and graftling 0.6.0 in a site-packages tree (515).

usage: markers.py <site-packages> <expect: present|absent> [<directory holding graftling/>]

Each marker is a line of dev 4ad22e90 (graphtraj) or of graftling v0.6.0 that production (503: 6115c724 + graftling
0.5.2) does not have, or a line production has that 4ad22e90/v0.6.0 removed. Kind 'add': the line is in the new tree.
Kind 'remove': the line is in the old tree only. Files are read as text; nothing is imported. Exit 0 only when every
marker is as expected: ``present`` for the candidate or the installed venv, ``absent`` for production now. For
git-archive trees, graftling lies in another directory: give it as the third argument (default: the site-packages).
"""
import sys
from pathlib import Path

ADD, REMOVE = 'add', 'remove'
MARKERS = [
    ('514 Main host server name graphtraj', 'graphtraj/runtimes/claude/mcp.py',
     "SERVER = {'name': 'graphtraj', 'version': '1'}", ADD),
    ('514 old server name agents gone', 'graphtraj/runtimes/claude/mcp.py',
     "SERVER = {'name': 'agents', 'version': '1'}", REMOVE),
    ('514 configuration --write drops its own old agents entry', 'graphtraj/runtimes/claude/host.py',
     "OLD_SERVER = 'agents'", ADD),
    ('514 Claude member names mcpServer graphtraj', 'graphtraj/runtimes/claude/execution.py',
     "return super().mcp_server if self.independent else 'graphtraj'", ADD),
    ('0.6.0 host_context names its server', 'graftling/claude/host_context.mjs',
     'const SERVER = "graftling";', ADD),
    ('0.6.0 host_context no longer hard-codes mcp__agents__', 'graftling/claude/host_context.mjs',
     "const PREFIX = PLUGIN ? `mcp__plugin_${PLUGIN}_agents__` : 'mcp__agents__';", REMOVE),
    ('graftling 0.6.0', 'graftling/__init__.py',
     '__version__ = "0.6.0"', ADD),
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
