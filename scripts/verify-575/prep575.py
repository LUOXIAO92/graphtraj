"""Task 575: one ready probe Task 1 in the isolated project, and the arguments files a step's Main names.

usage (the installation's python, from the project):
  python -I -B prep575.py task <project>          register probe Task 1 and set it ready; exit 0 = ready
  python -I -B prep575.py files <project> <tag>   write <project>/args575/*.json for one step's calls

The arguments files lie inside the project (the host's trusted directory) and outside .graphtraj.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

TASK_ID = '1'
BODY = '''---
difficulty: low
difficulty_reason: Scratch probe for 575
execution_budget:
  estimated_minutes:
    total: 30
  planned_sessions:
    team_leader: 1
  correction_rounds: 0
  estimation_note: Probe Task of the 575 arguments_file check
  on_exceed: Report only
---
Probe only.
'''


def run(*argv: str, cwd: Path) -> subprocess.CompletedProcess:
    """Run one CLI command of the same installation in the project."""
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=120)


def task(project: Path) -> int:
    """Register probe Task 1 once and make it ready."""
    graphtraj = str(Path(sys.executable).parent / 'graphtraj')
    work = project / '.graphtraj/probe-575'
    work.mkdir(exist_ok=True)
    (work / 'evidence.md').write_text('575 probe: ready.\n')
    register, state = work / 'register.yml', work / 'state.yml'
    register.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'task_name': 'argsfile-probe', 'source': 'local:scratch/575', 'title': 'argsfile-probe',
        'body': BODY, 'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
        'replaced_by': [], 'retirement_reason': None}))
    state.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
        'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-575/evidence.md']}))

    def current() -> dict | None:
        graph = run(graphtraj, 'task', 'graph', cwd=project)
        tasks = (yaml.safe_load(graph.stdout) or {}).get('tasks', []) if graph.returncode == 0 else []
        return next((item for item in tasks if item.get('task_id') == TASK_ID), None)

    if current() is None:
        done = run(graphtraj, 'task', 'register', '--task-file', str(register), cwd=project)
        print('register:', done.returncode, (done.stdout + done.stderr).strip()[-300:])
    if (found := current()) is not None and found.get('status') != 'ready':
        done = run(graphtraj, 'task', 'update', '--state-file', str(state), cwd=project)
        print('update:', done.returncode, (done.stdout + done.stderr).strip()[-300:])
    found = current()
    ready = found is not None and found.get('status') == 'ready'
    print('probe Task 1 ready' if ready else f'probe Task 1 NOT ready: {found}')
    return 0 if ready else 1


def files(project: Path, tag: str) -> int:
    """Write this step's arguments files; the Worldline event name carries ``tag``."""
    folder = project / 'args575'
    folder.mkdir(exist_ok=True)
    documents = {
        'graph.json':  {'view': 'current'},
        'append.json': {'event': {'event': tag, 'caused_by_event_ids': [], 'evidence_refs': []}},
        'status.json': {},
    }
    for name, document in documents.items():
        (folder / name).write_text(json.dumps(document), encoding='utf-8')
        print(f'args575/{name}: {json.dumps(document)}')
    return 0


if __name__ == '__main__':
    command, project = sys.argv[1], Path(sys.argv[2]).resolve()
    sys.exit(task(project) if command == 'task' else files(project, sys.argv[3]))
