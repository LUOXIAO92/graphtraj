"""Read-only: cleanup's busy judgement for Tasks' Session records, with one GraphTraj source tree.

    python -I -B diag523.py <graphtraj src> <runner directory> <state directory> <task id>...

For every Session record of the Tasks it prints what cleanup's _task_mappings
checks (stopped subtree, recorded pids) and the names under sessions/ that no
Agent alias can take. It reads records only: no cleanup, no write, no signal
(os.kill(pid, 0) only probes existence).
"""
import sys
from pathlib import Path

source, runner, state = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
task_ids = sys.argv[4:]
sys.path.insert(0, str(source))

import yaml  # noqa: E402
import graphtraj  # noqa: E402
from graphtraj.execution.runner_cleanup import _process_alive  # noqa: E402
from graphtraj.execution import runner_status  # noqa: E402
from graphtraj.execution.runner_status import ALIAS, require_stopped_subtree  # noqa: E402

print("graphtraj source:", Path(graphtraj.__file__).parent)
# Retained (retired) Session records are found through the project configuration.
# A reader that cannot load it (a sandbox denying <Harness>/.graphtraj itself)
# would see none, and every live child of a retired parent would look
# unattributable; then this seeds the per-call cache with the same glob.
scan = runner_status.one_retained_scan()
scan.__enter__()
retained = runner_status.retained_session_directories(runner)
if not retained:
    retained = [directory for directory in (state / "tasks").glob("*/teams/*/traces/*/runner")
                if (directory / "session.yml").is_file()]
    runner_status._retained_scan.get()[runner] = retained
    print("retained Session records: configuration unreadable here; seeded from", state, "->", len(retained))
else:
    print("retained Session records (from the project configuration):", len(retained))
sessions = runner / "sessions"
print("names under sessions/ no alias can take:",
      sorted(path.name for path in sessions.iterdir() if not ALIAS.fullmatch(path.name)) or "none")
for directory in sorted(sessions.iterdir()):
    mapping_file = directory / "mapping.yml"
    if not mapping_file.is_file():
        continue
    mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
    if not isinstance(mapping, dict) or mapping.get("task_id") not in task_ids:
        continue
    try:
        require_stopped_subtree(runner, directory.name)
        subtree = "stopped"
    except Exception as error:  # cleanup treats every RunnerError here as busy
        subtree = "refused " + str(getattr(error, "as_document", lambda: {"code": repr(error)})()["code"])
    alive = [pid for pid in (mapping.get("worker_pid"), mapping.get("runtime_pid"))
             if isinstance(pid, int) and _process_alive(pid)]
    busy = subtree != "stopped" or bool(alive)
    print(f"{mapping['task_id']} {directory.name}: subtree {subtree}; live pids {alive or 'none'}"
          f" -> {'BUSY (worktree-busy)' if busy else 'not busy'}")
