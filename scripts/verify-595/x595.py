"""Task 595 real-host helper, run by steps.zsh with the isolated project's venv Python inside the project.

    python -I x595.py connection                    the Claude connection to use (VERIFY595_CONNECTION, else the
                                                    first user-catalog Claude connection whose name holds 'haiku')
    python -I x595.py prepare <project> <conn>      roles (probe_team.engineer on Claude) + probe Task 1, ready
    python -I x595.py batch <project> <n>           ONE swarm batch: n Engineer entries of Task 1 (own instructions)
    python -I x595.py ended <project> <s>           every Task 1 Session's current execution has its terminal record
    python -I x595.py check <project>               PASS/FAIL: every started member registered once, one
                                                    team-started, team.yml lists all, no MEMBER_REGISTRATION_FAILED;
                                                    prints each member's registration interval and their overlap

The members are root entries of one Task in one `agent-runner --swarm-input` call: the first to take the Worldline
lock starts the Team, the others join it, all through the Claude Worker's member registration (the 581/591 path;
no real Leader is needed). It never signals a process and never writes outside the project.
Exit status: 0 = the observation passed, 1 = it failed, 2 = could not observe.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.configuration.project_roles import roles_file
from graphtraj.workspace.runner_project import discover_runner_directory

ROLE = 'probe_team.engineer'
TASK_ID, TASK_NAME = '1', 'member-registration-probe'
INSTRUCTION = (
    'This is a scripted probe of GraphTraj member registration (member {0}). Change no file, run no command, call '
    'no tool and dispatch nobody. Reply with exactly one line, PROBE-595 member {0}, and end your turn.'
)
BODY = f'''---
difficulty: low
difficulty_reason: 595 real-host probe
execution_budget:
  estimated_minutes:
    total: 15
  estimation_note: 595 probe
  planned_sessions:
    engineer: 3
  correction_rounds: 0
  on_exceed: Notify the caller
---
# 595 probe {TASK_NAME}

Each member replies with one line and ends its turn.
'''


def run(*argv: str, cwd: Path) -> subprocess.CompletedProcess:
    """Run one command in the project; echo a failure."""
    done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    if done.returncode:
        print('command failed:', ' '.join(argv), '\n', (done.stdout + done.stderr)[-800:])
    return done


def tool(name: str) -> str:
    """Return a console script of the venv running this helper."""
    return str(Path(sys.executable).parent / name)


def read(path: Path) -> dict:
    """Read one YAML mapping, or an empty mapping when it is absent or unreadable."""
    try:
        record = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        return {}
    return record if isinstance(record, dict) else {}


def task_directory(project: Path) -> Path:
    """Return the probe Task's state directory."""
    return load_project_configuration(project).state / 'tasks' / f'{TASK_ID}-{TASK_NAME}'


def sessions(project: Path) -> list[Path]:
    """Return the probe Task's Session directories."""
    root = Path(discover_runner_directory(project)) / 'sessions'
    return sorted(path for path in root.glob(f'{TASK_ID}-*') if path.is_dir()) if root.is_dir() else []


def connection() -> int:
    """Print the Claude connection reference the probe members use (names only, never secrets)."""
    chosen = os.environ.get('VERIFY595_CONNECTION')
    if not chosen:
        from graphtraj.configuration.runtime_connections import read_catalog

        # Only Claude connections on the native login: no key variable, no endpoint.
        names = []
        for runtime_id, runtime in (read_catalog()[0].get('runtimes') or {}).items():
            if runtime.get('runtime') != 'claude':
                continue
            for provider_id, provider in runtime['providers'].items():
                if provider.get('api_key_env') or provider.get('base_url'):
                    continue
                names += [(f'{runtime_id}/{provider_id}/{model_id}', model['id'])
                          for model_id, model in provider['models'].items()]
        print('user catalog Claude login connections: '
              + (', '.join(f'{name} ({model})' for name, model in names) or 'none'), file=sys.stderr)
        chosen = next((name for name, model in names if 'haiku' in model), '')
    if not chosen:
        print('no haiku connection in the user catalog; set VERIFY595_CONNECTION=<reference> (one listed above)',
              file=sys.stderr)
        return 2
    print(chosen)
    return 0


def prepare(project: Path, reference: str) -> int:
    """Write the probe role and register the probe Task as ready."""
    path = roles_file(project)
    path.write_text(yaml.safe_dump({
        'roles': {'probe_team': {'engineer': {
            'connection': reference, 'reasoning_effort': 'low', 'reports': ['engineer.md'],
            'claude': {'permission_mode': 'auto'}}}},
        'role_tree': {ROLE: {}}}, sort_keys=False))
    print(f'roles file: {path} ({ROLE}: connection {reference})')
    work = project / '.graphtraj/probe-595'
    work.mkdir(exist_ok=True)
    (work / 'evidence.md').write_text('595 probe: ready.\n')
    graph = run(tool('graphtraj'), 'task', 'graph', cwd=project)
    known = ({t.get('task_id') for t in (yaml.safe_load(graph.stdout) or {}).get('tasks', [])}
             if graph.returncode == 0 else set())
    rc = 0
    if TASK_ID in known:
        print(f'task {TASK_ID} already registered: register skipped')
    else:
        register = work / 'register.yml'
        register.write_text(yaml.safe_dump({
            'task_id': TASK_ID, 'task_name': TASK_NAME, 'source': 'local:scratch/595', 'title': TASK_NAME,
            'body': BODY, 'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
            'replaced_by': [], 'retirement_reason': None}))
        state = work / 'ready.yml'
        state.write_text(yaml.safe_dump({
            'task_id': TASK_ID, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
            'current_candidate': None, 'caused_by_event_ids': [],
            'evidence_refs': ['.graphtraj/probe-595/evidence.md']}))
        rc |= run(tool('graphtraj'), 'task', 'register', '--task-file', str(register), cwd=project).returncode
        rc |= run(tool('graphtraj'), 'task', 'update', '--state-file', str(state), cwd=project).returncode
    doctor = run(tool('graphtraj'), 'doctor', cwd=project)
    roles_ok = 'roles: OK' in doctor.stdout
    print('roles OK' if roles_ok else 'roles NOT OK: ' + (doctor.stdout + doctor.stderr)[-600:])
    status = read(task_directory(project) / 'task.yml').get('status')
    print(f'task {TASK_ID} {TASK_NAME}: status {status} (ready before the dispatch)')
    started = sessions(project)
    if started:
        print('Task 1 already has Sessions (an earlier dispatch): ' + ', '.join(path.name for path in started))
    return 1 if rc or not roles_ok or status != 'ready' or started else 0


def batch(count: int) -> int:
    """Print ONE swarm batch with ``count`` Engineer entries of the probe Task."""
    print(yaml.safe_dump({'tasks': [
        {'task_id': TASK_ID, 'task_name': TASK_NAME, 'role': ROLE, 'instruction': INSTRUCTION.format(index)}
        for index in range(1, count + 1)]}, sort_keys=False, width=100000), end='')
    return 0


def ended(project: Path, seconds: float) -> int:
    """Wait until every probe Session's current execution has its terminal execution.yml."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        pending = []
        for directory in sessions(project):
            current = read(directory / 'mapping.yml').get('execution_id')
            terminal = read(directory / 'execution.yml')
            if not terminal or (current is not None and terminal.get('execution_id') != current):
                pending.append(directory.name)
        if sessions(project) and not pending:
            for directory in sessions(project):
                terminal = read(directory / 'execution.yml')
                print(f'{directory.name}: ended ({terminal.get("outcome")}, error '
                      f'{(terminal.get("error") or {}).get("code")})')
            return 0
        time.sleep(3)
    print(f'not ended within {seconds:.0f} s: {pending}')
    return 2


def check(project: Path) -> int:
    """Check the registration observables and print the members' registration intervals."""
    ok = True

    def verdict(passed: bool, text: str) -> None:
        nonlocal ok
        ok &= passed
        print(('PASS: ' if passed else 'FAIL: ') + text)

    assigned = [path for path in sessions(project) if read(path / 'launch.yml').get('member_registration')]
    print('members started by the swarm call: ' + ', '.join(path.name for path in assigned))
    verdict(len(assigned) >= 2, f'{len(assigned)} members were started (at least 2)')
    failed = {path.name: read(path / 'execution.yml').get('error')
              for path in (Path(discover_runner_directory(project)) / 'sessions').iterdir()
              if (read(path / 'execution.yml').get('error') or {}).get('code') == 'MEMBER_REGISTRATION_FAILED'}
    verdict(not failed, f'no MEMBER_REGISTRATION_FAILED in any execution.yml {failed or ""}')
    events = []
    worldline = load_project_configuration(project).state / 'worldline'
    for shard in sorted(worldline.glob('*.jsonl')):
        for line in shard.read_text().splitlines():
            event = json.loads(line)
            if event.get('task_id') == TASK_ID and event['event'] in ('team-started', 'team-member-started'):
                events.append(event)
    kinds = [event['event'] for event in events]
    verdict(kinds.count('team-started') == 1, f'one team-started ({kinds.count("team-started")})')
    registered = [event['evidence_refs'][0].split('/')[-2] for event in events]
    for path in assigned:
        verdict(registered.count(path.name) == 1,
                f'{path.name}: one registration event ({registered.count(path.name)})')
    team = read(task_directory(project) / 'teams/1/team.yml')
    listed = sorted(member.get('session_ref') for member in (team.get('members') or {}).values())
    verdict(listed == sorted(path.name for path in assigned), f'team.yml lists all members: {listed}')

    # Registration interval: the Worker writes mapping.yml just before it registers,
    # and the Worldline event's captured_at is the commit under the lock.
    intervals = []
    for event in events:
        alias = event['evidence_refs'][0].split('/')[-2]
        mapping = Path(discover_runner_directory(project)) / 'sessions' / alias / 'mapping.yml'
        begin = datetime.fromtimestamp(mapping.stat().st_mtime).astimezone()
        end = datetime.fromisoformat(event['captured_at'])
        intervals.append((begin, end, alias, event['event']))
    intervals.sort()
    for begin, end, alias, kind in intervals:
        print(f'registration {alias}: mapping.yml {begin.isoformat(timespec="microseconds")} -> '
              f'{kind} {end.isoformat(timespec="microseconds")} ({(end - begin).total_seconds():.3f} s)')
    overlaps = [(a[2], b[2]) for i, a in enumerate(intervals) for b in intervals[i + 1:] if b[0] < a[1]]
    print('registrations overlapped: ' + (f'yes {overlaps}' if overlaps else
          'no (each began after the previous commit; the race window was not exercised)'))
    print('verdict: ' + ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


def main() -> int:
    """Dispatch one helper command."""
    command = sys.argv[1]
    if command == 'connection':
        return connection()
    if command == 'batch':
        return batch(int(sys.argv[3]))
    project = Path(sys.argv[2]).resolve()
    if command == 'prepare':
        return prepare(project, sys.argv[3])
    if command == 'ended':
        return ended(project, float(sys.argv[3]))
    if command == 'check':
        return check(project)
    print(f'unknown command {command}')
    return 2


if __name__ == '__main__':
    sys.exit(main())
