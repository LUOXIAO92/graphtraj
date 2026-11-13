"""Check the markers of the adopted Tasks 457 and 459 in a site-packages tree.

usage: markers.py <site-packages> <expect: present|absent>

Each marker is a line that 4e3aafce..b3d522ad adds (read from the diff). The
files are read as text; nothing is imported. Exit 0 only when every marker is
as expected: ``present`` for the candidate or the installed venv, ``absent``
for production (4e3aafce) before the install.
"""
import sys
from pathlib import Path

MARKERS = [
    ('457 claude driver records the tool marker', 'graftling/claude/driver.py', "facts = {'tool_marker': turn.member_marker}"),
    ('457 agents driver records the tool marker', 'graphtraj/execution/agent_driver.py', "marker = getattr(turn, 'member_marker', None) if run.runtime == 'claude' else None"),
    ('457 reconcile stops the escaped tools', 'graftling/control.py', 'def _stop_escaped(execution: dict) -> None:'),
    ('457 owner-exited reconcile calls it', 'graftling/control.py', '_stop_escaped(current)'),
    ('459 sampling period', 'graftling/tool_descendants.py', 'SAMPLE_SECONDS = 1.0'),
    ('459 descendant sampler', 'graftling/tool_descendants.py', 'class DescendantSampler:'),
    ('459 owner samples the Runtime', 'graftling/claude/execution.py', 'self.descendants.start(self.proc.pid)'),
    ('459 agents driver records the descendants file', 'graphtraj/execution/agent_driver.py', "facts['tool_descendants'] = str(Path(turn.tool_descendants).resolve())"),
    ('459 tool_descendants process fact allowed', 'graftling/control.py', '"tool_descendants"}'),
    ('459 pid list retried when the buffer fills', 'graftling/member_processes.py', "raise OSError(0, 'proc_listallpids kept filling its buffer')"),
    ('459 correction (b3d522ad): recorded argv redacted', 'graftling/tool_descendants.py', "'argv': shown_command(_argv(item.pid))"),
]


def main() -> int:
    site, expect = Path(sys.argv[1]), sys.argv[2]
    bad = 0
    for label, relative, text in MARKERS:
        path = site / relative
        found = path.is_file() and text in path.read_text(encoding='utf-8', errors='replace')
        ok = found if expect == 'present' else not found
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {label}: {'present' if found else 'absent'} in {path}")
    print(f"markers expected {expect}: {'PASS' if bad == 0 else 'FAIL'} ({len(MARKERS) - bad}/{len(MARKERS)})")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
