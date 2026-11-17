"""README judgement 3(a) for 2da634af -> 871aaaa9 (499; taken from adopt-497): a budget idle timer started under
2da634af that wakes after the 871aaaa9 files replace it.

usage: timer_probe.py <live dir holding the OLD graphtraj and graftling packages> <dir holding the NEW packages>

Loads what `python -I -m graphtraj.execution.budget_idle_timer` loads at start (OLD files), replaces the package files
on disk as pip --force-reinstall does (modules already in sys.modules stay old), then runs the imports the threshold
makes lazily (deliver_parent_notices: runner_control, runner_status; graftling.control._stop_escaped's lazy imports).
Prints which changed modules were OLD in memory and which load NEW, and whether the old timer loop (old
budget_idle_timer in memory) still has the attributes it calls, with the new runner modules beside it.
Signals nothing; reads only a temporary directory.
"""
import sys, shutil, os, importlib, json, tempfile, inspect
live, new = sys.argv[1], sys.argv[2]
sys.path.insert(0, live)
import graphtraj.execution.budget_idle_timer as t   # what `python -I -m graphtraj.execution.budget_idle_timer` loads
loaded = sorted(m for m in sys.modules if m.startswith(('graphtraj', 'graftling')))
print('loaded at timer start:', len(loaded)); print('  ', ' '.join(loaded))
old_slice = getattr(t, 'SLICE_SECONDS', None)
print('old timer in memory: SLICE_SECONDS', old_slice, '| has _work_ended:', hasattr(t, '_work_ended'),
      '| has _collect_ended_children:', hasattr(t, '_collect_ended_children'))
for pkg in ('graphtraj', 'graftling'):
    shutil.rmtree(os.path.join(live, pkg)); shutil.copytree(os.path.join(new, pkg), os.path.join(live, pkg))
importlib.invalidate_caches()
try:
    from graphtraj.execution.runner_control import notify_direct_parent
    from graphtraj.execution.runner_status import read_alias_mapping
    print('lazy import at the threshold: OK')
    control = sys.modules['graftling.control']
    empty = os.path.join(tempfile.mkdtemp(), 'tool-descendants-probe.json')
    with open(empty, 'w') as stream:
        json.dump({'version': 1, 'runtime_pid': None, 'entries': []}, stream)
    execution = {'process': {'tool_descendants': empty}}
    control._stop_escaped(execution)
    print('_stop_escaped lazy imports after the install: OK', json.dumps(execution.get('escaped_processes')))
    rp = sys.modules.get('graphtraj.execution.runner_process')
    print('488/490 runner_process in memory after the threshold:', 'NEW' if rp and hasattr(rp, 'process_is_zombie') else
          ('OLD' if rp else 'not loaded'))
    print('494 graftling.control in memory after the threshold:',
          'NEW' if "ended.pop('push_deferred', None)" in open(control.__file__).read() and 'graftling.control' not in loaded else
          ('OLD (loaded at start)' if 'graftling.control' in loaded else 'NEW file, check'))
    # The old loop calls these on its own module object; they must still be there (they are: old module in memory).
    print('old timer loop callables still present:', all(hasattr(t, n) for n in ('run_idle_budget_timer', '_should_exit', 'main')))
except Exception as e:
    print('lazy import after the install:', type(e).__name__, e)
newly = sorted(m for m in sys.modules if m.startswith(('graphtraj', 'graftling')) and m not in loaded)
print('newly imported after the install:', len(newly)); print('  ', ' '.join(newly))
# Modules whose files change in 2da634af..871aaaa9 (git diff --stat, src only; 496, 498).
changed = set("""graftling.control graftling.tool_descendants""".split())
import graftling.tool_descendants as _td
print('499: tool_descendants in memory after the threshold:', 'NEW' if hasattr(_td, '_verdict') and hasattr(_td, 'has_exited') else 'OLD')
print('changed modules that were OLD in memory before the install:', sorted(changed & set(loaded)) or 'none')
print('changed modules loaded NEW after the install:', sorted(changed & set(newly)) or 'none')
