"""Check the markers of Task 560's pair (graftling 0.6.3 + GraphTraj candidate) in a site-packages tree.

usage: markers.py <site-packages | directory holding graphtraj/ and graftling/> <expect: present|absent>

Each marker is a line the 560 pair has and production (532: graphtraj a7b20447 + graftling 0.6.2) does not. Files are
read as text; nothing is imported. Exit 0 only when every marker is as expected: ``present`` for the candidate or the
installed venv, ``absent`` for production now.

  graftling 0.6.3: the version line; 555 ValidationErrors (schema.py); 546 input_closed_wait_seconds (control.py);
                   545 next-turn relay (dsh/communication.mjs).
  graphtraj:       556 the MCP gateway imports ValidationErrors and read_envelope_arguments from graftling;
                   563 migrate-task-definitions (workspace/definition_migration.py).
"""
import sys
from pathlib import Path

MARKERS = [
    ('560 graftling version 0.6.3', 'graftling/__init__.py', '__version__ = "0.6.3"'),
    ('555 graftling ValidationErrors', 'graftling/schema.py', 'class ValidationErrors(ValueError):'),
    ('546 graftling waits for a closing execution', 'graftling/control.py',
     'self.input_closed_wait_seconds = INPUT_CLOSED_WAIT_SECONDS'),
    ('545 graftling DSH relay to the next-turn inbox', 'graftling/dsh/communication.mjs',
     "agent.send(message, 'next-turn', true);"),
    ('556 graphtraj gateway uses 555 names', 'graphtraj/interfaces/gateway.py',
     'from graftling import (ENVELOPE_SCHEMA as INPUT_SCHEMA, ValidationErrors, read_envelope_arguments, schema_errors,'),
    ('563 graphtraj migrate-task-definitions', 'graphtraj/workspace/definition_migration.py',
     'def migrate_task_definitions(cwd: Path, *, preview: bool = False) -> dict[str, Any]:'),
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
