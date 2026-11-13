"""README 3(a): a budget idle timer started under cfd5e432 that wakes after the 4e3aafce files replace it.

usage: timer_probe.py <live dir holding the OLD graphtraj and graftling packages> <dir holding the NEW packages>

Loads what `python -I -m graphtraj.execution.budget_idle_timer` loads at start, replaces the
package files on disk as pip --force-reinstall does (modules already loaded stay old), then runs
the imports deliver_parent_notices makes lazily at the threshold (execution_budget.py:311-312).
"""
import sys, shutil, os, importlib
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
    rc = sys.modules['graphtraj.execution.runner_control']
    print('runner_control from new file:', hasattr(rc, '_reconcile_exited_owner'))
except Exception as e:
    print('lazy import at the threshold:', type(e).__name__, e)
newly = sorted(m for m in sys.modules if m.startswith(('graphtraj', 'graftling')) and m not in loaded)
print('newly imported after the install:', len(newly)); print('  ', ' '.join(newly))
changed = {'graftling.claude.driver','graftling.codex.driver','graftling.control','graftling.dsh.driver','graftling.member_processes','graftling.pi.driver','graphtraj.execution.agent_driver','graphtraj.execution.budget_idle_timer','graphtraj.execution.runner_control','graphtraj.execution.runner_worker','graphtraj.execution.task_agents','graphtraj.interfaces.agents'}
print('changed modules that were OLD in memory before the install:', sorted(changed & set(loaded)) or 'none')
print('changed modules loaded NEW after the install:', sorted(changed & set(newly)) or 'none')
