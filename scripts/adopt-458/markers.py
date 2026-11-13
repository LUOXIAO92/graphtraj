"""Check one marker per adopted Task (451, 452, 454, 455, 456) in a site-packages tree.

usage: markers.py <site-packages> <expect: present|absent>

Each marker is a line that cfd5e432..4e3aafce adds (read from the diff). The
files are read as text; nothing is imported. Exit 0 only when every marker is
as expected: ``present`` for the candidate or the installed venv, ``absent``
for production before the install.
"""
import sys
from pathlib import Path

MARKERS = [
    ('451 15 s child sweep in the Worker', 'graphtraj/execution/task_agents.py', 'CHILD_SWEEP_SECONDS = 15.0'),
    ('451 Worker starts the sweep', 'graphtraj/execution/runner_worker.py', 'watch_member_children('),
    ('452 non-daemon owner thread (agents driver)', 'graphtraj/execution/agent_driver.py', 'name=f"agents-{run.agent}", daemon=False'),
    ('452 non-daemon owner thread (claude driver)', 'graftling/claude/driver.py', "name=f'claude-{run.agent}', daemon=False"),
    ('454 bounded timer delivery', 'graphtraj/execution/budget_idle_timer.py', 'DELIVERY_SECONDS = 300.0'),
    ('455 configuration recorded', 'graftling/control.py', '"configuration": applied.get("configuration")'),
    ('455 driver reports what it applied', 'graphtraj/execution/agent_driver.py', '"applied":         {"configuration": name'),
    ('456 reconcile before resume', 'graphtraj/execution/runner_control.py', '_reconcile_exited_owner(alias, session_directory, mapping)'),
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
