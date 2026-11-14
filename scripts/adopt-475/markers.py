"""Check the markers of the adopted Tasks 465 and 469 in a site-packages tree.

usage: markers.py <site-packages> <expect: present|absent>

Each marker is read from the diff 44729d5b..4ca57419. ``add`` markers are lines
the target adds; ``removed`` markers are lines the target removes (so for the
target they must be missing, and for 44729d5b they must be there). The files
are read as text; nothing is imported. Exit 0 only when every marker is as
expected: ``present`` for the candidate or the installed venv (the target's
state), ``absent`` for production (44729d5b) before the install.
"""
import sys
from pathlib import Path

ADD, REMOVED = 'add', 'removed'
MARKERS = [
    # 465: Claude and Codex member settings no longer grant each associated history file.
    ('465 Claude member settings: no project_history_files grant', 'graphtraj/runtimes/claude/execution.py',
     'from graphtraj.runtimes.codex.access import project_history_files', REMOVED),
    ('465 Claude member settings: only explicit resources', 'graphtraj/runtimes/claude/execution.py',
     "explicit = [Path(path).resolve() for path in request['resources']]", ADD),
    ('465 Claude member settings: deny exceptions only for explicit files', 'graphtraj/runtimes/claude/execution.py',
     'if not any(path.is_relative_to(protected) for path in explicit):', ADD),
    ('465 Codex development reads take history', 'graphtraj/runtimes/codex/access.py',
     'def project_development_reads(root: Path, *, history: bool = True) -> dict[str, str]:', ADD),
    ('465 Codex member reads pass history=False', 'graphtraj/runtimes/codex/access.py',
     'filesystem.update(project_development_reads(root, history=False))', ADD),
    ('465 Codex member profile passes history=False', 'graphtraj/runtimes/codex/codex_adapter.py',
     'filesystem.update(private_filesystem(runtime_store, self.runtime_home, history=False))', ADD),
    # 469: member launch, recovery and registration read only their own Task.
    ('469 single-Task loader', 'graphtraj/graph/task_graph.py',
     'def _load_task_state(tasks: Path, task_id: str) -> tuple[Path, dict[str, Any]]:', ADD),
    ('469 UnknownTask', 'graphtraj/graph/task_graph.py', 'class UnknownTask(KeyError, ValueError):', ADD),
    ('469 Task directory created complete', 'graphtraj/graph/task_graph.py', 'def _create_task_directory(', ADD),
    ('469 launch looks up one Task name', 'graphtraj/execution/runner_launch.py', 'class _RegisteredTaskNames:', ADD),
    ('469 launch no longer reads the whole graph', 'graphtraj/execution/runner_launch.py',
     'from graphtraj.graph.task_graph import read_graph', REMOVED),
    ('469 Worker registration reads its own Task', 'graphtraj/execution/runner_worker.py',
     'task_directory, task = _load_task_state(project.state_directory / "tasks", mapping["task_id"])', ADD),
    ('469 Runner control reads its own Task', 'graphtraj/execution/runner_control.py',
     'task_directory, task = _load_task_state(configuration.state / "tasks", mapping["task_id"])', ADD),
    ('469 Runner status reads its own Task', 'graphtraj/execution/runner_status.py',
     'from graphtraj.graph.task_graph import UnknownTask, _load_task_state', ADD),
    ('469 Runner results read their own Task', 'graphtraj/execution/runner_results.py',
     'from graphtraj.graph.task_graph import _load_task_state', ADD),
]


def main() -> int:
    site, expect = Path(sys.argv[1]), sys.argv[2]
    bad = 0
    for label, relative, text, kind in MARKERS:
        path = site / relative
        found = path.is_file() and text in path.read_text(encoding='utf-8', errors='replace')
        target_state = found if kind == ADD else (path.is_file() and not found)
        ok = target_state if expect == 'present' else (path.is_file() and not target_state)
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {label} [{kind}]: line {'found' if found else 'not found'} in {path}")
    print(f"markers expected {expect}: {'PASS' if bad == 0 else 'FAIL'} ({len(MARKERS) - bad}/{len(MARKERS)})")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
