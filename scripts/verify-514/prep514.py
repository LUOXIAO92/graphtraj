"""Task 514: roles and one ready probe Task in an isolated GraphTraj project (from verify-444 probe.py prepare).

Run with the project venv's python, from the project:  python -I prep514.py <project>
Roles: claude_member (claude-opus-5-5, permission_mode auto, so its own agents/tasks tools are not held by
Claude Code's default mode, 513 lesson) and codex_member (gpt-6-luna, user rule). Exit 0 = roles OK, Task 1 ready.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

TASK_ID = '1'
BODY = '''---
difficulty: low
difficulty_reason: Scratch probe for 514
execution_budget:
  estimated_minutes:
    total: 60
  planned_sessions:
    team_leader: 1
  correction_rounds: 0
  estimation_note: Probe members of the 514 server-name checks
  on_exceed: Report only
---
Follow the dispatch instruction exactly.
'''


def run(*argv: str, cwd: Path) -> subprocess.CompletedProcess:
    """Run one GraphTraj command in the project."""
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=120)


def main() -> int:
    project = Path(sys.argv[1]).resolve()
    graphtraj = str(Path(sys.executable).parent / 'graphtraj')
    roles = {
        'claude_member': {'runtime': 'claude', 'model': 'claude-opus-5-5', 'worktree_access': 'read',
                          'claude': {'permission_mode': 'auto'}},
        'codex_member': {'runtime': 'codex', 'model': 'gpt-6-luna', 'worktree_access': 'read'},
    }
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump(
        {'roles': roles, 'role_tree': {'claude_member': {}, 'codex_member': {}}}))
    work = project / '.graphtraj/probe-514'
    work.mkdir(exist_ok=True)
    (work / 'evidence.md').write_text('514 probe: ready.\n')
    register, state = work / 'register.yml', work / 'state.yml'
    register.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'task_name': 'server-name-probe', 'source': 'local:scratch/514', 'title': 'server-name-probe',
        'body': BODY, 'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
        'replaced_by': [], 'retirement_reason': None}))
    state.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
        'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-514/evidence.md']}))

    def task1() -> dict | None:
        graph = run(graphtraj, 'task', 'graph', cwd=project)
        tasks = (yaml.safe_load(graph.stdout) or {}).get('tasks', []) if graph.returncode == 0 else []
        return next((t for t in tasks if t.get('task_id') == TASK_ID), None)

    if task1() is None:
        done = run(graphtraj, 'task', 'register', '--task-file', str(register), cwd=project)
        print('register:', done.returncode, (done.stdout + done.stderr).strip()[-300:])
    current = task1()
    if current is not None and current.get('status') != 'ready':
        done = run(graphtraj, 'task', 'update', '--state-file', str(state), cwd=project)
        print('update:', done.returncode, (done.stdout + done.stderr).strip()[-300:])
    doctor = run(graphtraj, 'doctor', cwd=project)
    roles_ok = doctor.returncode == 0 and 'roles: OK' in doctor.stdout
    print('roles OK' if roles_ok else 'roles NOT OK (doctor): ' + (doctor.stdout + doctor.stderr)[-600:])
    current = task1()
    ready = current is not None and current.get('status') == 'ready'
    print('probe Task 1 ready' if ready else f'probe Task 1 NOT ready: {current}')
    return 0 if roles_ok and ready else 1


if __name__ == '__main__':
    sys.exit(main())
