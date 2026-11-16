"""Check the markers of the adopted Tasks 466, 467, 468, 473, 474, 476, 477 and 479 in a site-packages tree.

usage: markers.py <site-packages> <expect: present|absent>

Each marker is a line the diff 4ca57419..a3fe1b92 adds under src/ (470, 471, 472, 482 and 483 changed only tests or
scripts, which are not installed). The files are read as text; nothing is imported. Exit 0 only when every marker is
as expected: ``present`` for the candidate or the installed venv (a3fe1b92), ``absent`` for production (4ca57419).
"""
import sys
from pathlib import Path

ADD = 'add'
MARKERS = [
    ('466 session_read reader module', 'graftling/sessions/reading.py', 'DEFAULT_COUNT = 5', ADD),
    ('466 session_read in the agents interface', 'graphtraj/interfaces/agents.py', '            if action == "session_read":', ADD),
    ('466 member Session read policy', 'graphtraj/interfaces/agents.py',
     '    def _member_session(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:', ADD),
    ('467 superseded stop notice', 'graphtraj/execution/execution_budget.py',
     'def _superseded(notice: dict[str, Any]) -> dict[str, Any]:', ADD),
    ('467 stop cleared', 'graphtraj/execution/execution_budget.py',
     'def _stop_cleared(notice: dict[str, Any], state: dict[str, Any]) -> bool:', ADD),
    ('468 archive identity (no reparse per record)', 'graftling/sessions/archive.py',
     'def _identity(status: os.stat_result) -> tuple:', ADD),
    ('468 archive batch', 'graftling/sessions/archive.py', '    def batch(self) -> Iterator[None]:', ADD),
    ('468 budget sampled once a second', 'graphtraj/execution/runner_worker.py', 'BUDGET_SAMPLE_SECONDS = 1.0', ADD),
    ('473 Codex owner blocking calls on own thread', 'graftling/codex/managed_session.py',
     'async def in_thread(function: Callable, *args: object) -> object:', ADD),
    ('474 interrupt execution_record pending', 'graphtraj/execution/runner_control.py',
     'return {"alias": alias, "interrupt_status": "interrupted", "execution_record": "pending"}', ADD),
    ('476 reopened Worktree restored', 'graphtraj/execution/approved_recovery.py',
     'def _restore_reopened_worktree(project: Any, alias: str) -> None:', ADD),
    ('476 missing Worktree named', 'graphtraj/execution/runner_control.py',
     'def missing_worktree(worktree: Path, detail: str = "") -> RunnerError:', ADD),
    ('477 take_push', 'graftling/control.py', '    def take_push(self, notice: Mapping[str, Any]) -> bool:', ADD),
    ('477 waited', 'graftling/control.py', 'def _waited(execution: Mapping[str, Any]) -> bool:', ADD),
    ('477 Main notice defers push', 'graphtraj/interfaces/agents.py', '    _main_notice.defers_push = True', ADD),
    ('479 Pi extension starts graphtraj-session pi', 'graphtraj/runtimes/pi/extension.mjs',
     "const child = spawn(installedCommand('graphtraj-session', env.PATH), ['pi'], {", ADD),
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
