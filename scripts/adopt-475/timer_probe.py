"""README judgement 3(a): a budget idle timer started under 44729d5b that wakes after the 4ca57419 files replace it.

usage: timer_probe.py <live dir holding the OLD graphtraj and graftling packages> <dir holding the NEW packages>

Loads what `python -I -m graphtraj.execution.budget_idle_timer` loads at start, replaces the
package files on disk as pip --force-reinstall does (modules already loaded stay old), then runs
the imports deliver_parent_notices makes lazily at the threshold (execution_budget.py) and the
ones graftling.control._stop_escaped makes lazily (457/459: member_processes, review,
tool_descendants), the latter by calling it on an execution whose descendants record is empty
(no marker, no entries: it scans nothing and signals nothing). 460: runner_control is the module
the threshold imports, and it is changed; its new _reclaim_tool_processes lazily imports
runner_worker and graftling's published names. Those are imported and it is called on a directory
without a record (it returns None and signals nothing).
475 (44729d5b..4ca57419): 469 changes runner_control and runner_status (the threshold's imports) and
task_graph (their lazy import). Both are checked from the new files, and the new single-Task loader is
called on an empty tasks directory (UnknownTask; reads nothing else).
"""
import sys, shutil, os, importlib, json, tempfile
live, new = sys.argv[1], sys.argv[2]
sys.path.insert(0, live)
import graphtraj.execution.budget_idle_timer as t   # what `python -I -m graphtraj.execution.budget_idle_timer` loads at start
loaded = sorted(m for m in sys.modules if m.startswith(('graphtraj', 'graftling')))
print('loaded at timer start:', len(loaded)); print('  ', ' '.join(loaded))
# pip --force-reinstall: files replaced (new mtimes), modules already in sys.modules stay old
for pkg in ('graphtraj', 'graftling'):
    shutil.rmtree(os.path.join(live, pkg)); shutil.copytree(os.path.join(new, pkg), os.path.join(live, pkg))
importlib.invalidate_caches()
try:
    from graphtraj.execution.runner_control import notify_direct_parent
    from graphtraj.execution.runner_status import read_alias_mapping
    print('lazy import at the threshold: OK')
    control = sys.modules['graftling.control']
    print('graftling.control from new file (has _stop_escaped):', hasattr(control, '_stop_escaped'))
    empty = os.path.join(tempfile.mkdtemp(), 'tool-descendants-probe.json')
    with open(empty, 'w') as stream:
        json.dump({'version': 1, 'runtime_pid': None, 'entries': []}, stream)
    execution = {'process': {'tool_descendants': empty}}
    control._stop_escaped(execution)
    print('_stop_escaped lazy imports after the install: OK', json.dumps(execution.get('escaped_processes')))
    from pathlib import Path
    rc = sys.modules['graphtraj.execution.runner_control']
    from graphtraj.execution.runner_worker import TOOL_PROCESSES_RECORD
    from graftling import process_ancestors, read_tool_descendants, stop_tool_processes
    print('460 runner_control from new file (has _reclaim_tool_processes):', hasattr(rc, '_reclaim_tool_processes'))
    print('460 _reclaim_tool_processes lazy imports after the install: OK',
          rc._reclaim_tool_processes(Path(tempfile.mkdtemp()), {'execution_id': 'probe'}))
    import graphtraj.graph.task_graph as tg
    print('469 runner_control from new file (uses _load_task_state):', '_load_task_state' in open(rc.__file__).read())
    try:
        tg._load_task_state(Path(tempfile.mkdtemp()), '475')
        print('469 _load_task_state after the install: returned (unexpected)')
    except tg.UnknownTask:
        print('469 _load_task_state after the install: OK UnknownTask')
except Exception as e:
    print('lazy import after the install:', type(e).__name__, e)
newly = sorted(m for m in sys.modules if m.startswith(('graphtraj', 'graftling')) and m not in loaded)
print('newly imported after the install:', len(newly)); print('  ', ' '.join(newly))
# Modules whose files change in 44729d5b..4ca57419 (git diff --stat, src only).
changed = {'graphtraj.execution.approved_recovery', 'graphtraj.execution.runner_control', 'graphtraj.execution.runner_launch',
           'graphtraj.execution.runner_results', 'graphtraj.execution.runner_retirement', 'graphtraj.execution.runner_status',
           'graphtraj.execution.runner_worker', 'graphtraj.graph.delivery_state', 'graphtraj.graph.task_graph',
           'graphtraj.runtimes.claude.execution', 'graphtraj.runtimes.codex.access', 'graphtraj.runtimes.codex.codex_adapter',
           'graphtraj.teams.team_replacement'}
print('changed modules that were OLD in memory before the install:', sorted(changed & set(loaded)) or 'none')
print('changed modules loaded NEW after the install:', sorted(changed & set(newly)) or 'none')
