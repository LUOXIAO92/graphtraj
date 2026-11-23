"""Check the markers of Task 593's pair (graftling 0.9.0 + GraphTraj 3eb21101) in a site-packages tree.

usage: markers.py <site-packages | directory holding graphtraj/ and graftling/> <expect: present|absent>

Each marker is a line the 593 pair has and production (579: graphtraj eb009725 + graftling 0.8.0) does not. Files are
read as text; nothing is imported. Exit 0 only when every marker is as expected: ``present`` for the candidate or the
installed venv, ``absent`` for production now.

  graftling 0.9.0: the version line; 591 the one tool name (tool.py TOOL_NAME), the plugin template's TOOL line
                   (claude/host_context.mjs), Pi's and DSH's TOOL constants, and the console script subagents-mcp
                   (entry_points.txt of the dist-info beside the package).
  graphtraj:       592 the Claude host's tool comment (runtimes/claude/mcp.py); 588 submit_report names an assigned
                   path (interfaces/tools.py).
"""
import sys
from pathlib import Path

MARKERS = [
    ('593 graftling version 0.9.0', 'graftling/__init__.py', '__version__ = "0.9.0"'),
    ('591 graftling TOOL_NAME subagents', 'graftling/tool.py', 'TOOL_NAME = "subagents"'),
    ('591 graftling Claude hook TOOL line', 'graftling/claude/host_context.mjs', 'const TOOL = "subagents";'),
    ('591 graftling Pi TOOL', 'graftling/pi/extension.mjs', "export const TOOL = 'subagents';"),
    ('591 graftling DSH TOOL', 'graftling/dsh/review.mjs', "export const TOOL = 'subagents';"),
    ('591 graftling console script subagents-mcp', 'graftling-0.9.0.dist-info/entry_points.txt',
     'subagents-mcp = graftling.mcp:main'),
    ('592 graphtraj Claude host serves subagents', 'graphtraj/runtimes/claude/mcp.py',
     "raise AgentsError('invalid-input', 'Use the subagents entry for Agent controls.')"),
    ('588 graphtraj submit_report by assigned path', 'graphtraj/interfaces/tools.py',
     "'or by its assigned path (for example .state/teams/1/rounds/1/report.md). '"),
]


def main() -> int:
    site, expect = Path(sys.argv[1]), sys.argv[2]
    if expect not in ('present', 'absent'):
        print('expect must be present or absent'); return 2
    bad = 0
    for label, relative, text in MARKERS:
        path = site / relative
        found = path.is_file() and text in path.read_text(encoding='utf-8', errors='replace')
        ok = found if expect == 'present' else not found
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {label}: line {'found' if found else 'not found'} in {path}"
              f"{'' if path.is_file() else ' (FILE MISSING)'}")
    print(f"markers expected {expect}: {'PASS' if bad == 0 else 'FAIL'} ({len(MARKERS) - bad}/{len(MARKERS)})")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
