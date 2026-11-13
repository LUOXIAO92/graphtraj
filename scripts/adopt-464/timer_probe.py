"""README 3(a): a budget idle timer started under 4e3aafce that wakes after the b3d522ad files replace it.

usage: timer_probe.py <live dir holding the OLD graphtraj and graftling packages> <dir holding the NEW packages>

Loads what `python -I -m graphtraj.execution.budget_idle_timer` loads at start, replaces the
package files on disk as pip --force-reinstall does (modules already loaded stay old), then runs
the imports deliver_parent_notices makes lazily at the threshold (execution_budget.py) and the
ones graftling.control._stop_escaped makes lazily (457/459: member_processes, review,
tool_descendants), the latter by calling it on an execution whose descendants record is empty
(no marker, no entries: it scans nothing and signals nothing).
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
except Exception as e:
    print('lazy import after the install:', type(e).__name__, e)
newly = sorted(m for m in sys.modules if m.startswith(('graphtraj', 'graftling')) and m not in loaded)
print('newly imported after the install:', len(newly)); print('  ', ' '.join(newly))
# Modules whose files change in 4e3aafce..b3d522ad (git diff --stat, src only); tool_descendants is new.
changed = {'graftling.claude.driver', 'graftling.claude.execution', 'graftling.control', 'graftling.member_processes',
           'graftling.tool_descendants', 'graphtraj.execution.agent_driver'}
print('changed modules that were OLD in memory before the install:', sorted(changed & set(loaded)) or 'none')
print('changed modules loaded NEW after the install:', sorted(changed & set(newly)) or 'none')
