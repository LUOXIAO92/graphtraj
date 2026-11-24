"""Task 610 real-host helper, run by steps.zsh with the isolated project's venv Python inside the project.

    python -I x610.py prepare <project> <codex-home>  Codex config.toml, user catalog (isolated HOME), roles, Tasks
    python -I x610.py batch                           ONE swarm batch: one Codex member per connection
    python -I x610.py ended <project> <seconds>       every probe Session's execution ended
    python -I x610.py observe <project> <codex-home>  rollout session_meta and launch evidence; PASS/FAIL

Both providers point at a closed local port, so no login and no key are used and no inference happens: each
member's turn fails at its first request. The Codex approval route that GraphTraj requires for a non-openai work
provider names an unset variable and the same closed port; it is only read if Codex asks for an approval, and a
turn that fails at its first request asks for none.
Exit status: 0 = passed, 1 = failed, 2 = could not observe (inconclusive).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.configuration.project_roles import roles_file
from graphtraj.configuration.runtime_connections import connections_file, validate_catalog
from graphtraj.workspace.runner_project import discover_runner_directory

CLOSED = 'http://127.0.0.1:9/v1'              # discard port: nothing listens, the request fails at once
NAMED, OVERRIDE = 'probe610', 'override610'    # name only / base_url override
TASKS = {NAMED: ('1', 'name-only-provider'), OVERRIDE: ('2', 'override-provider')}
APPROVAL = {'model': 'probe-review', 'base_url': 'https://127.0.0.1:9/v1', 'api_key_env': 'PROBE610_REVIEW_UNSET'}
INSTRUCTION = ('This is a scripted GraphTraj probe (Task {0}). Change no file, run no command, call no tool and '
               'dispatch nobody. Reply with exactly one line, PROBE-610 task {0}, and end your turn.')
BODY = '''---
difficulty: low
difficulty_reason: 610 real-host probe
execution_budget:
  estimated_minutes:
    total: 10
  estimation_note: 610 probe
  planned_sessions:
    engineer: 1
  correction_rounds: 0
  on_exceed: Notify the caller
---
# 610 probe

One Codex member starts on the selected provider; its first request fails at a closed local port.
'''


def run(*argv: str, cwd: Path) -> subprocess.CompletedProcess:
    done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    if done.returncode:
        print('command failed:', ' '.join(argv), '\n', (done.stdout + done.stderr)[-800:])
    return done


def tool(name: str) -> str:
    return str(Path(sys.executable).parent / name)


def read(path: Path) -> dict:
    try:
        record = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        return {}
    return record if isinstance(record, dict) else {}


def role(provider: str) -> str:
    return f'probe_{provider}.engineer'


def sessions(project: Path) -> list[Path]:
    root = Path(discover_runner_directory(project)) / 'sessions'
    return sorted(path for path in root.glob('[12]-*') if path.is_dir()) if root.is_dir() else []


def prepare(project: Path, codex_home: Path) -> int:
    """Write the native provider, the isolated user catalog, roles and both probe Tasks."""
    codex_home.mkdir(parents=True, exist_ok=True)
    (codex_home / 'config.toml').write_text(
        f'[model_providers.{NAMED}]\nname = "Probe 610"\nbase_url = "{CLOSED}"\nwire_api = "responses"\n'
        'requires_openai_auth = false\nrequest_max_retries = 0\nstream_max_retries = 0\n')
    print(f'{codex_home}/config.toml defines model_providers.{NAMED} (base_url {CLOSED}, no env_key)')
    model = {'m': {'id': 'probe-model', 'source': 'manual'}}
    catalog = {'version': 1, 'runtimes': {'probe': {'runtime': 'codex', 'home': str(codex_home), 'providers': {
        NAMED: {'models': model}, OVERRIDE: {'base_url': CLOSED, 'models': model}}}}}
    validate_catalog(catalog)
    path = connections_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(catalog, sort_keys=False))
    print(f'user catalog {path}: probe/{NAMED}/m (name only), probe/{OVERRIDE}/m (base_url {CLOSED})')
    roles = {f'probe_{name}': {'engineer': {
        'connection': f'probe/{name}/m', 'reasoning_effort': 'low', 'reports': ['engineer.md'],
        'codex': {'approval': APPROVAL}}} for name in TASKS}
    roles_file(project).write_text(yaml.safe_dump(
        {'roles': roles, 'role_tree': {role(name): {} for name in TASKS}}, sort_keys=False))
    print(f'roles file {roles_file(project)}: ' + ', '.join(role(name) for name in TASKS))
    work = project / '.graphtraj/probe-610'
    work.mkdir(exist_ok=True)
    (work / 'evidence.md').write_text('610 probe: ready.\n')
    graph = run(tool('graphtraj'), 'task', 'graph', '--view', 'full', cwd=project)
    known = ({t.get('task_id') for t in (yaml.safe_load(graph.stdout) or {}).get('tasks', [])}
             if graph.returncode == 0 else set())
    rc = 0
    for task_id, task_name in TASKS.values():
        if task_id in known:
            print(f'task {task_id} already registered: register skipped')
            continue
        register, ready = work / f'register-{task_id}.yml', work / f'ready-{task_id}.yml'
        register.write_text(yaml.safe_dump({
            'task_id': task_id, 'task_name': task_name, 'source': f'local:scratch/610-{task_id}',
            'title': task_name, 'body': BODY, 'dependencies': [], 'schema_version': 2, 'parent_id': None,
            'disposition': 'active', 'replaced_by': [], 'retirement_reason': None}))
        ready.write_text(yaml.safe_dump({
            'task_id': task_id, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
            'current_candidate': None, 'caused_by_event_ids': [],
            'evidence_refs': ['.graphtraj/probe-610/evidence.md']}))
        rc |= run(tool('graphtraj'), 'task', 'register', '--task-file', str(register), cwd=project).returncode
        rc |= run(tool('graphtraj'), 'task', 'update', '--state-file', str(ready), cwd=project).returncode
    doctor = run(tool('graphtraj'), 'doctor', cwd=project)
    roles_ok = 'roles: OK' in doctor.stdout
    print('roles OK' if roles_ok else 'roles NOT OK: ' + (doctor.stdout + doctor.stderr)[-600:])
    state = load_project_configuration(project).state / 'tasks'
    statuses = {task_id: read(state / f'{task_id}-{name}' / 'task.yml').get('status')
                for task_id, name in TASKS.values()}
    print(f'task statuses before the dispatch: {statuses} (both must be ready)')
    started = sessions(project)
    if started:
        print('probe Tasks already have Sessions (an earlier dispatch): ' + ', '.join(p.name for p in started))
    return 1 if rc or not roles_ok or set(statuses.values()) != {'ready'} or started else 0


def batch() -> int:
    print(yaml.safe_dump({'tasks': [
        {'task_id': task_id, 'task_name': task_name, 'role': role(name), 'instruction': INSTRUCTION.format(task_id)}
        for name, (task_id, task_name) in TASKS.items()]}, sort_keys=False, width=100000), end='')
    return 0


def ended(project: Path, seconds: float) -> int:
    deadline, pending = time.time() + seconds, ['(none started)']
    while time.time() < deadline:
        found, pending = sessions(project), []
        for directory in found:
            current = read(directory / 'mapping.yml').get('execution_id')
            terminal = read(directory / 'execution.yml')
            if not terminal or (current is not None and terminal.get('execution_id') != current):
                pending.append(directory.name)
        if len(found) >= 2 and not pending:
            for directory in found:
                terminal = read(directory / 'execution.yml')
                print(f'{directory.name}: execution ended, outcome {terminal.get("outcome")}, error '
                      f'{(terminal.get("error") or {}).get("code")}: {str((terminal.get("error") or {}).get("message"))[:200]}')
            return 0
        time.sleep(3)
    print(f'not ended within {seconds:.0f} s: {pending}')
    return 2


def observe(project: Path, codex_home: Path) -> int:
    """Join each Session's launch evidence with the native rollout started in its Worktree."""
    rollouts = {}
    for path in sorted(codex_home.glob('sessions/**/rollout-*.jsonl')):
        for line in path.read_text().splitlines():
            record = json.loads(line)
            if record.get('type') == 'session_meta':
                meta = record.get('payload') or {}
                rollouts[str(Path(meta.get('cwd', '')).resolve())] = (meta.get('model_provider'), path)
                break
    print(f'native rollouts in {codex_home}/sessions: {len(rollouts)}')
    expected = {'1': (NAMED, NAMED, NAMED), '2': (OVERRIDE, 'graphtraj-role', 'graphtraj-role')}
    found, ok = sessions(project), True
    for directory in found:
        launch = read(directory / 'launch.yml')
        evidence = launch.get('context_evidence') or {}
        worktree = str(Path(launch.get('adapter_request', {}).get('worktree_path', '')).resolve())
        native, rollout = rollouts.get(worktree, (None, None))
        want = expected[directory.name.split('-')[0]]
        got = (evidence.get('provider'), evidence.get('model_provider'), native)
        good = got == want
        ok &= good
        print(f'{"PASS" if good else "FAIL"}: {directory.name}: launch evidence provider {got[0]}, '
              f'model_provider {got[1]}; rollout session_meta model_provider {native} ({rollout}); expected {want}')
    if len(found) != 2 or len(rollouts) < 2:
        print(f'INCONCLUSIVE: {len(found)} probe Sessions, {len(rollouts)} rollouts (expected 2 each)')
        return 2
    print('verdict: ' + ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


def main() -> int:
    command = sys.argv[1]
    if command == 'batch':
        return batch()
    project = Path(sys.argv[2]).resolve()
    if command == 'prepare':
        return prepare(project, Path(sys.argv[3]))
    if command == 'ended':
        return ended(project, float(sys.argv[3]))
    if command == 'observe':
        return observe(project, Path(sys.argv[3]))
    print('unknown command', command)
    return 2


if __name__ == '__main__':
    assert os.environ.get('HOME'), 'HOME is required'
    sys.exit(main())
