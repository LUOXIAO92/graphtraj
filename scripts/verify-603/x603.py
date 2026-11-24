"""Task 603 real-host helper, run by steps.zsh with the isolated project's venv Python inside the project.

    python -I x603.py connection                  the Claude connection to use (VERIFY603_CONNECTION, else the
                                                  first user-catalog Claude login connection whose model holds haiku)
    python -I x603.py prepare <project> <conn>    roles (probe_team.engineer on Claude) + probe Tasks 1 and 2, ready
    python -I x603.py batch                       ONE swarm batch: one Engineer of Task 1 and one of Task 2
    python -I x603.py ended <project> <s>         every probe Session's execution ended; prints outcome and timer
    python -I x603.py cancel <project>            Task 1: a commit on its branch, then task revise cancelled
    python -I x603.py wait <project>              sleeps past Task 1's planned end + allowance; PASS/FAIL on notices
    python -I x603.py clean <project>             public cleanup of Task 1 (cancelled) and Task 2 (active)

Task 1 is the cancelled probe; Task 2 stays active and is the control: its idle timer must still record the
planned-end notice, which shows the timer ran in this environment. Neither Session is interrupted: the shell has
no public interrupt (the subagents tool needs a verified Main), so each execution ends by itself. The Worker then
starts the idle budget timer on the same path an interrupt takes (runner_worker.py, any execution end that the
budget did not stop). Nothing here signals a process or writes outside the project.
Exit status: 0 = passed, 1 = failed, 2 = could not observe (inconclusive).
"""
from __future__ import annotations

import json
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
CANCELLED, CONTROL = ('1', 'cancel-probe'), ('2', 'active-control')
MINUTES = 2        # estimated_minutes.total: the planned end (Task 602's reproduction used 2)
MARGIN = 30        # seconds waited past planned end + allowance (the timer sleeps in 5 s slices)
INSTRUCTION = ('This is a scripted GraphTraj probe (Task {0}). Change no file, run no command, call no tool and '
               'dispatch nobody. Reply with exactly one line, PROBE-603 task {0}, and end your turn.')
BODY = f'''---
difficulty: low
difficulty_reason: 603 real-host probe
execution_budget:
  estimated_minutes:
    total: {MINUTES}
  estimation_note: 603 probe; the smallest practical planned end
  planned_sessions:
    engineer: 1
  correction_rounds: 0
  on_exceed: Notify the caller
---
# 603 probe

The member replies with one line and ends its turn.
'''
REASON = '603 probe: cancelled by the verification step.'


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


def stamp(seconds: float) -> str:
    return datetime.fromtimestamp(seconds).astimezone().isoformat(timespec='seconds')


def work(project: Path) -> Path:
    path = project / '.graphtraj/probe-603'
    path.mkdir(exist_ok=True)
    return path


def task_directory(project: Path, task: tuple[str, str]) -> Path:
    return load_project_configuration(project).state / 'tasks' / f'{task[0]}-{task[1]}'


def sessions(project: Path, task: tuple[str, str] | None = None) -> list[Path]:
    """Return the probe Sessions (of one Task when given)."""
    root = Path(discover_runner_directory(project)) / 'sessions'
    found = sorted(path for path in root.glob('[12]-*') if path.is_dir()) if root.is_dir() else []
    return [path for path in found if task is None or path.name.startswith(task[0] + '-')]


def definition(task: tuple[str, str], **facts) -> dict:
    return {'task_id': task[0], 'task_name': task[1], 'source': f'local:scratch/603-{task[0]}', 'title': task[1],
            'body': BODY, 'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
            'replaced_by': [], 'retirement_reason': None, **facts}


def connection() -> int:
    """Print the Claude connection reference the probe members use (names only, never secrets)."""
    import os

    chosen = os.environ.get('VERIFY603_CONNECTION')
    if not chosen:
        from graphtraj.configuration.runtime_connections import read_catalog

        names = []
        for runtime_id, runtime in (read_catalog()[0].get('runtimes') or {}).items():
            if runtime.get('runtime') != 'claude':
                continue
            for provider_id, provider in runtime['providers'].items():
                if provider.get('api_key_env') or provider.get('base_url'):
                    continue  # only the native Claude login: no key variable, no endpoint
                names += [(f'{runtime_id}/{provider_id}/{model_id}', model['id'])
                          for model_id, model in provider['models'].items()]
        print('user catalog Claude login connections: '
              + (', '.join(f'{name} ({model})' for name, model in names) or 'none'), file=sys.stderr)
        chosen = next((name for name, model in names if 'haiku' in model), '')
    if not chosen:
        print('no haiku connection in the user catalog; set VERIFY603_CONNECTION=<reference> (one listed above)',
              file=sys.stderr)
        return 2
    print(chosen)
    return 0


def prepare(project: Path, reference: str) -> int:
    """Write the probe role and register both probe Tasks as ready."""
    path = roles_file(project)
    path.write_text(yaml.safe_dump({
        'roles': {'probe_team': {'engineer': {
            'connection': reference, 'reasoning_effort': 'low', 'reports': ['engineer.md'],
            'claude': {'permission_mode': 'auto'}}}},
        'role_tree': {ROLE: {}}}, sort_keys=False))
    print(f'roles file: {path} ({ROLE}: connection {reference}, effort low, permission_mode auto)')
    (work(project) / 'evidence.md').write_text('603 probe: ready.\n')
    graph = run(tool('graphtraj'), 'task', 'graph', '--view', 'full', cwd=project)
    known = ({t.get('task_id') for t in (yaml.safe_load(graph.stdout) or {}).get('tasks', [])}
             if graph.returncode == 0 else set())
    rc = 0
    for task in (CANCELLED, CONTROL):
        if task[0] in known:
            print(f'task {task[0]} already registered: register skipped')
            continue
        register = work(project) / f'register-{task[0]}.yml'
        register.write_text(yaml.safe_dump(definition(task)))
        ready = work(project) / f'ready-{task[0]}.yml'
        ready.write_text(yaml.safe_dump({
            'task_id': task[0], 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
            'current_candidate': None, 'caused_by_event_ids': [],
            'evidence_refs': ['.graphtraj/probe-603/evidence.md']}))
        rc |= run(tool('graphtraj'), 'task', 'register', '--task-file', str(register), cwd=project).returncode
        rc |= run(tool('graphtraj'), 'task', 'update', '--state-file', str(ready), cwd=project).returncode
    doctor = run(tool('graphtraj'), 'doctor', cwd=project)
    roles_ok = 'roles: OK' in doctor.stdout
    print('roles OK' if roles_ok else 'roles NOT OK: ' + (doctor.stdout + doctor.stderr)[-600:])
    statuses = {task[0]: read(task_directory(project, task) / 'task.yml').get('status') for task in (CANCELLED, CONTROL)}
    print(f'task statuses before the dispatch: {statuses} (both must be ready)')
    started = sessions(project)
    if started:
        print('probe Tasks already have Sessions (an earlier dispatch): ' + ', '.join(p.name for p in started))
    return 1 if rc or not roles_ok or set(statuses.values()) != {'ready'} or started else 0


def batch() -> int:
    """Print ONE swarm batch: one Engineer of the cancel probe and one of the control."""
    print(yaml.safe_dump({'tasks': [
        {'task_id': task[0], 'task_name': task[1], 'role': ROLE, 'instruction': INSTRUCTION.format(task[0])}
        for task in (CANCELLED, CONTROL)]}, sort_keys=False, width=100000), end='')
    return 0


def ended(project: Path, seconds: float) -> int:
    """Wait until every probe Session's current execution has its terminal execution.yml."""
    deadline = time.time() + seconds
    pending = ['(none started)']
    while time.time() < deadline:
        found = sessions(project)
        pending = []
        for directory in found:
            current = read(directory / 'mapping.yml').get('execution_id')
            terminal = read(directory / 'execution.yml')
            if not terminal or (current is not None and terminal.get('execution_id') != current):
                pending.append(directory.name)
        if len(found) >= 2 and not pending:
            for directory in found:
                terminal = read(directory / 'execution.yml')
                timer = read(directory / 'budget-timer.yml')
                print(f'{directory.name}: execution ended, outcome {terminal.get("outcome")}, error '
                      f'{(terminal.get("error") or {}).get("code")}; idle budget timer: '
                      + (f'started (token {timer.get("token")})' if timer else 'NOT started'))
            return 0
        time.sleep(3)
    print(f'not ended within {seconds:.0f} s: {pending}')
    return 2


def _budget(project: Path, task: tuple[str, str]) -> dict:
    return read(task_directory(project, task) / 'execution-budget.yml')


def _deadline(state: dict) -> tuple[float, float]:
    """Planned end and the end of the additional allowance (epoch seconds)."""
    total = state['budget']['execution_budget']['estimated_minutes']['total']
    return state['started_at'] + total * 60, state['started_at'] + (total + state['allowance_minutes']) * 60


def cancel(project: Path) -> int:
    """Task 1: confirm its execution ended with a timer, commit on its branch, then revise it to cancelled."""
    probe = work(project)
    if (probe / 'cancelled.yml').is_file():
        print('Task 1 was already cancelled by an earlier run: ' + (probe / 'cancelled.yml').read_text())
        return 2
    (session,) = sessions(project, CANCELLED) or [None]
    if session is None:
        print('STOP: Task 1 has no Session')
        return 2
    terminal, timer = read(session / 'execution.yml'), read(session / 'budget-timer.yml')
    print(f'Task 1 member {session.name}: execution outcome {terminal.get("outcome")}; budget-timer.yml '
          + ('present (the idle timer started before the cancellation)' if timer else 'ABSENT'))
    if not terminal or not timer:
        print('STOP: Task 1 needs an ended execution and its idle timer before the cancellation')
        return 2
    state = read(task_directory(project, CANCELLED) / 'task.yml')
    worktree, branch = project / state['worktree'], state['branch']
    # Stand-in for the member's unmerged work, so cleanup removes a branch that dev does not contain.
    if run('git', '-c', 'user.name=603', '-c', 'user.email=603@invalid', 'commit', '-q', '--allow-empty',
           '-m', '603 probe: unmerged Task work', cwd=worktree).returncode:
        return 2
    tip = run('git', 'rev-parse', 'refs/heads/' + branch, cwd=project).stdout.strip()
    team = read(task_directory(project, CANCELLED) / f'teams/{state["active_team_ordinal"]}/team.yml')
    print(f'Task 1 Worktree {worktree} | branch {branch} tip {tip} (not in dev: '
          f'{run("git", "merge-base", "--is-ancestor", tip, "dev", cwd=project).returncode == 1})')
    revision = probe / 'cancel.yml'
    revision.write_text(yaml.safe_dump({
        'product_preserving': True, 'caused_by_event_ids': [],
        'evidence_refs': ['.graphtraj/probe-603/evidence.md'],
        'tasks': [{**definition(CANCELLED, disposition='cancelled', retirement_reason=REASON),
                   'current_definition': state['current_definition']}]}, sort_keys=False))
    revised = run(tool('graphtraj'), 'task', 'revise', '--revision-file', str(revision), cwd=project)
    if revised.returncode:
        return 1
    now = time.time()
    budget = _budget(project, CANCELLED)
    planned, allowance_end = _deadline(budget)
    control_end = _deadline(_budget(project, CONTROL))[1]
    wait_until = max(allowance_end, control_end) + MARGIN
    record = {'cancelled_at': now, 'tip': tip, 'branch': branch, 'worktree': str(worktree),
              'status': state['status'], 'team_status': team.get('status'), 'member': session.name,
              'planned_end': planned, 'allowance_end': allowance_end, 'wait_until': wait_until}
    (probe / 'cancelled.yml').write_text(yaml.safe_dump(record, sort_keys=False))
    after = read(task_directory(project, CANCELLED) / 'task.yml')
    print(f'task revise: Task 1 disposition cancelled at {stamp(now)} (event {(yaml.safe_load(revised.stdout) or {}).get("event_id")})')
    print(f'Task 1 status {after.get("status")} (before {state["status"]}), Team status {team.get("status")}')
    print(f'Task 1 budget: started {stamp(budget["started_at"])}, planned end {stamp(planned)}, '
          f'allowance {budget["allowance_minutes"]:.2f} min -> {stamp(allowance_end)}')
    print(f'Task 2 (control) allowance ends {stamp(control_end)}')
    print(f'the wait ends after {stamp(wait_until)} (latest allowance end + {MARGIN} s)')
    if now >= planned:
        print('NOTE: the cancellation came after Task 1\'s planned end; wait reports INCONCLUSIVE')
    return 0


def _notices(directory: Path) -> list[dict]:
    """The execution-budget notices one member Session recorded as delivered to its parent."""
    path = directory / 'parent-notices.jsonl'
    if not path.is_file():
        return []
    lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [line for line in lines if 'execution-budget' in json.dumps(line)]


def wait(project: Path) -> int:
    """Sleep past the recorded wait time, then judge Task 1's and the control's notices."""
    record = read(work(project) / 'cancelled.yml')
    if not record:
        print('STOP: no cancellation recorded; run realhost first')
        return 2
    remaining = record['wait_until'] - time.time()
    print(f'waiting until {stamp(record["wait_until"])} ({max(remaining, 0):.0f} s)', flush=True)
    while remaining > 0:
        time.sleep(min(remaining, 15))
        remaining = record['wait_until'] - time.time()
    ok = True

    def verdict(passed: bool, text: str) -> None:
        nonlocal ok
        ok &= passed
        print(('PASS: ' if passed else 'FAIL: ') + text)

    budget = _budget(project, CANCELLED)
    print(f'Task 1 execution-budget.yml: notifications {budget.get("notifications")}, '
          f'parent_notices {budget.get("parent_notices")}, stopped {budget.get("stopped")}, '
          f'stopping_checks {budget.get("stopping_checks")}')
    verdict(budget.get('parent_notices') == [] and budget.get('notifications') == [],
            'the cancelled Task recorded no budget notice')
    member = Path(discover_runner_directory(project)) / 'sessions' / record['member']
    sent = _notices(member)
    print(f'{member.name} parent-notices.jsonl execution-budget records: {sent or "none"}')
    verdict(not sent, 'no execution-budget notice reached the cancelled member\'s parent')
    control = _budget(project, CONTROL)
    print(f'Task 2 (control, active) notifications {control.get("notifications")}')
    timed = f'elapsed_minutes:{MINUTES}' in (control.get('notifications') or [])
    print(('PASS: ' if timed else 'INCONCLUSIVE: ') + 'the active control Task\'s idle timer '
          + ('recorded its planned-end notice: timers ran here' if timed else 'recorded nothing: no timer ran here'))
    early = record['cancelled_at'] < record['planned_end']
    print(('PASS: ' if early else 'INCONCLUSIVE: ') + f'the cancellation ({stamp(record["cancelled_at"])}) came '
          f'{"before" if early else "after"} Task 1\'s planned end ({stamp(record["planned_end"])})')
    result = 'PASS' if ok and timed and early else 'FAIL' if not ok else 'INCONCLUSIVE'
    print('verdict: ' + result)
    return {'PASS': 0, 'FAIL': 1}.get(result, 2)


def clean(project: Path) -> int:
    """Public cleanup of the cancelled probe and of the active control."""
    record = read(work(project) / 'cancelled.yml')
    if not record:
        print('STOP: no cancellation recorded; run realhost first')
        return 2
    ok = True

    def verdict(passed: bool, text: str) -> None:
        nonlocal ok
        ok &= passed
        print(('PASS: ' if passed else 'FAIL: ') + text)

    directory = task_directory(project, CANCELLED)
    done = subprocess.run([tool('agent-runner'), 'cleanup', '--task-id', CANCELLED[0]], cwd=project,
                          capture_output=True, text=True)
    print(f'agent-runner cleanup --task-id 1: exit {done.returncode}\n{done.stdout.strip()}')
    document = yaml.safe_load(done.stdout) or {}
    verdict(document.get('cleanup_status') == 'cleaned', 'Task 1 cleanup_status cleaned')
    verdict(not Path(record['worktree']).exists(), f'Worktree {record["worktree"]} is gone')
    ref = run('git', 'show-ref', '--verify', '--quiet', 'refs/heads/' + record['branch'], cwd=project)
    verdict(ref.returncode == 1, f'branch {record["branch"]} is gone')
    recorded = (document.get('evidence') or {}).get('task_commit')
    verdict(recorded == record['tip'], f'recorded task_commit {recorded} equals the branch tip {record["tip"]}')
    state = read(directory / 'task.yml')
    team_file = directory / f'teams/{state.get("active_team_ordinal")}/team.yml'
    kept = {'task.yml': (directory / 'task.yml').is_file(),
            'definitions/': len(list((directory / 'definitions').glob('*.md'))) >= 2,
            'execution-budget.yml': (directory / 'execution-budget.yml').is_file(),
            str(team_file.relative_to(directory)): team_file.is_file(),
            'Traces': any(directory.glob('teams/*/traces/*'))}
    verdict(all(kept.values()), f'Task 1 records kept: {kept}')
    verdict(state.get('status') == record['status'] and read(team_file).get('status') == record['team_status'],
            f'Task 1 status {state.get("status")} and Team status {read(team_file).get("status")} unchanged')
    session = Path(discover_runner_directory(project)) / 'sessions' / record['member']
    verdict(session.is_dir(), f'Session record {session.name} kept')
    control = read(task_directory(project, CONTROL) / 'task.yml')
    refused = subprocess.run([tool('agent-runner'), 'cleanup', '--task-id', CONTROL[0]], cwd=project,
                             capture_output=True, text=True)
    print(f'agent-runner cleanup --task-id 2: exit {refused.returncode}\n{refused.stdout.strip()}')
    code = ((yaml.safe_load(refused.stdout) or {}).get('error') or {}).get('code')
    verdict(refused.returncode == 1 and code == 'cleanup-not-integrated',
            f'Task 2 (active, unintegrated) refused with {code}')
    verdict((project / control['worktree']).is_dir(), 'Task 2 Worktree kept')
    print('verdict: ' + ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


def main() -> int:
    command = sys.argv[1]
    if command == 'connection':
        return connection()
    if command == 'batch':
        return batch()
    project = Path(sys.argv[2]).resolve()
    if command == 'prepare':
        return prepare(project, sys.argv[3])
    if command == 'ended':
        return ended(project, float(sys.argv[3]))
    if command in {'cancel', 'wait', 'clean'}:
        return {'cancel': cancel, 'wait': wait, 'clean': clean}[command](project)
    print(f'unknown command {command}')
    return 2


if __name__ == '__main__':
    sys.exit(main())
