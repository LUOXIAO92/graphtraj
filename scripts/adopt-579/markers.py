"""Check the markers of Task 579's pair (graftling 0.8.0 + GraphTraj candidate) in a site-packages tree.

usage: markers.py <site-packages | directory holding graphtraj/ and graftling/> <expect: present|absent>

Each marker is a line the 579 pair has and production (571: graphtraj 98125982 + graftling 0.7.0) does not. Files are
read as text; nothing is imported. Exit 0 only when every marker is as expected: ``present`` for the candidate or the
installed venv, ``absent`` for production now.

  graftling 0.8.0: the version line; 576 the probed default tool set (claude/execution.py); 578 the narrower
                   permission-mode warning (claude/execution.py); 577 the plugin host's data root
                   (claude/host_context.mjs); 585 a Pi subagent child starts no host (pi/extension.mjs).
  graphtraj:       575 the Claude host reads arguments_file for the call it runs; 583 GraphTraj's Pi entry hands the
                   Session to graftling only with a connection or --agents-config.
"""
import sys
from pathlib import Path

MARKERS = [
    ('579 graftling version 0.8.0', 'graftling/__init__.py', '__version__ = "0.8.0"'),
    ('576 graftling Claude default_tool_set', 'graftling/claude/execution.py', 'def default_tool_set(self) -> list[str]:'),
    ('578 graftling permission_mode_narrower', 'graftling/claude/execution.py',
     "warning = {'source': 'system_init', 'category': 'permission_mode_narrower'}"),
    ('577 graftling plugin host --data-root', 'graftling/claude/host_context.mjs',
     "...(dataRoot ? ['--data-root', dataRoot] : [])];"),
    ('585 graftling Pi subagent child starts no host', 'graftling/pi/extension.mjs',
     "if (process.env.PI_SUBAGENT_CHILD === '1' || Number(process.env.PI_SUBAGENT_DEPTH) > 0"),
    ('575 graphtraj Claude host reads arguments_file', 'graphtraj/runtimes/claude/host.py',
     'request = read_arguments_file(request, current)'),
    ('583 graphtraj Pi entry keeps its own Session', 'graphtraj/runtimes/pi/extension.mjs',
     "if (Object.hasOwn(process.env, 'GRAFTLING_CONNECTION') || pi.getFlag?.('agents-config')) {"),
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
