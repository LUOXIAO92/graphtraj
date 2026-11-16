"""Check the markers of the adopted Tasks 488, 490, 494 and 495 in a site-packages tree (497).

usage: markers.py <site-packages> <expect: present|absent>

Each marker is a line (or, for 494's agents.py, two consecutive lines) the diff 9faa0274..2da634af adds under src/
(489's verify-common script, 491's tests/scripts and the CHANGELOG are not installed). The files are read as text;
nothing is imported. Exit 0 only when every marker is as expected: ``present`` for the candidate or the installed venv
(2da634af), ``absent`` for production (9faa0274).
"""
import sys
from pathlib import Path

ADD = 'add'
MARKERS = [
    ('488 Worker argv read skips an ended process', 'graphtraj/execution/runner_process.py',
     'def _worker_arguments(pid: int) -> list[str] | None:', ADD),
    ('488 kernel shows exiting/zombie/reaped', 'graphtraj/execution/runner_process.py', 'def _process_ended(pid: int) -> bool:', ADD),
    ('490 timer exits when the watched work ended', 'graphtraj/execution/budget_idle_timer.py',
     'def _work_ended(session_directory: Path, task_directory: Path) -> bool:', ADD),
    ('490 timer collects its ended children', 'graphtraj/execution/budget_idle_timer.py', 'def _collect_ended_children() -> None:', ADD),
    ('490 timer sleeps in 5 s slices', 'graphtraj/execution/budget_idle_timer.py', 'SLICE_SECONDS = 5.0', ADD),
    ('490 cleanup: a zombie is not executing', 'graphtraj/execution/runner_cleanup.py', '    return not process_is_zombie(pid)', ADD),
    ('494 Claude host receiver defers the push', 'graftling/claude/host.py', '    receive.defers_push = True', ADD),
    ('494 answered defers_push settles the push', 'graftling/control.py',
     "                            ended.pop('push_deferred', None)", ADD),
    ('494 member hold thread started inside _HOLDS_LOCK', 'graphtraj/interfaces/agents.py',
     '            _HOLDS.append(thread)\n            thread.start()', ADD),
    ('495 tool descendants refresh argv each sample', 'graftling/tool_descendants.py',
     "                        live[key] = {**entry, 'argv': shown_command(argv)}", ADD),
    ('495 tool descendants written on any change', 'graftling/tool_descendants.py', '                if live != self.entries:', ADD),
]


def main() -> int:
    site, expect = Path(sys.argv[1]), sys.argv[2]
    bad = 0
    for label, relative, text, kind in MARKERS:
        path = site / relative
        found = path.is_file() and text in path.read_text(encoding='utf-8', errors='replace')
        ok = found if expect == 'present' else not found
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {label} [{kind}]: line {'found' if found else 'not found'} in {path}")
    print(f"markers expected {expect}: {'PASS' if bad == 0 else 'FAIL'} ({len(MARKERS) - bad}/{len(MARKERS)})")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
