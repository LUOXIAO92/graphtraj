"""480 probe helper: isolated project roles/Task, model-less Pi member dispatch and PASS/FAIL judgements.

Run with the installation under test (`<venv>/bin/python -I`). Reads and writes only the isolated project and
OUT. Prints no key value: printed text passes through redact(), which removes the DEEPSEEK_API_KEY value.

  probe.py prepare PROJECT           roles.yml (pi_member = production pi_dsh_trial.team_leader pi values,
                                     pi/deepseek/deepseek-flash, worktree_access read, reports [pi-member.md]),
                                     role_tree, Task 1 ready; prints ROLES <path>
  probe.py pisandbox -               Pi sandbox paths exist and srt is on sandbox_path
  probe.py dispatch PROJECT OUT LABEL  agent-runner --swarm-input (this installation) dispatches pi_member on
                                     Task 1 and returns when its turn ends (<= 480 s, then the probe stops it)
  probe.py judge PROJECT OUT LABEL   report at the parent-readable state path and in `agent-runner reports`;
                                     out-of-scope writes refused (EPERM) and absent
Exit 0 means every printed criterion passed.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

TASK_ID = '1'
NAME = 'pi-report-probe'
PI = {  # production roles.yml pi_dsh_trial.team_leader pi values (as verify-444 E1/E2)
    'sandbox_python': '/Users/luoxiao/agents-pi-sandbox/venv/bin/python',
    'sandbox_path': '/Users/luoxiao/agents-pi-sandbox/srt/node_modules/.bin:/opt/homebrew/bin:'
                    '/Users/luoxiao/agents-pi-sandbox/bin:/usr/bin:/bin:/usr/sbin:/sbin',
    'agent_dir': '/Users/luoxiao/.pi/agent',
}
REPORT = '.state/teams/1/rounds/1/pi-member.md'
EXTRA = '.state/teams/1/rounds/1/pi-member-extra.md'
BODY = '''---
difficulty: low
difficulty_reason: Scratch probe for 480
execution_budget:
  estimated_minutes:
    total: 30
  planned_sessions:
    team_leader: 1
  correction_rounds: 0
  estimation_note: One Pi member writes its report
  on_exceed: Report only
---
Follow the dispatch instruction exactly.
'''
BIN = Path(sys.executable).parent


def redact(text: str) -> str:
    key = os.environ.get('DEEPSEEK_API_KEY')
    return text.replace(key, '[redacted]') if key else text


def say(*parts: object) -> None:
    print(redact(' '.join(str(p) for p in parts)), flush=True)


def verdict(name: str, ok: bool, observable: str) -> bool:
    say(f"{'PASS' if ok else 'FAIL'} {name}: {observable}")
    return ok


def run(*argv: str, cwd: Path | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    say(f'$ {" ".join(argv[-3:])} -> rc={done.returncode}')
    if done.returncode:
        say(done.stdout[-600:], done.stderr[-600:])
    return done


def roles_file(project: Path) -> Path:
    core = project / '.graphtraj/core/roles.yml'
    return core if core.exists() else project / '.graphtraj/roles.yml'


def fixed_line(label: str) -> str:
    return f'REPORT-480-{label}'


def prepare(project: Path) -> int:
    graphtraj = str(BIN / 'graphtraj')
    roles = {'pi_member': {'connection': 'pi/deepseek/deepseek-flash', 'worktree_access': 'read',
                           'reports': ['pi-member.md'], 'pi': dict(PI)}}
    target = roles_file(project)
    target.write_text(yaml.safe_dump({'roles': roles, 'role_tree': {'pi_member': {}}}))
    say('ROLES', target)
    work = project / '.graphtraj/probe-480'
    work.mkdir(exist_ok=True)
    register = work / 'register.yml'
    register.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'task_name': NAME, 'source': 'local:scratch/480', 'title': NAME, 'body': BODY,
        'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
        'replaced_by': [], 'retirement_reason': None}))
    state = work / 'state.yml'
    state.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
        'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-480/evidence.md']}))
    (work / 'evidence.md').write_text('480 probe: ready.\n')

    def task1() -> dict | None:
        graph = run(graphtraj, 'task', 'graph', cwd=project)
        tasks = (yaml.safe_load(graph.stdout) or {}).get('tasks', []) if graph.returncode == 0 else []
        return next((t for t in tasks if t.get('task_id') == TASK_ID), None)
    rc = 0
    if task1() is None:
        rc = 2 if run(graphtraj, 'task', 'register', '--task-file', str(register), cwd=project).returncode else 0
    current = task1()
    if current is not None and current.get('status') != 'ready':
        rc = rc or (2 if run(graphtraj, 'task', 'update', '--state-file', str(state), cwd=project).returncode else 0)
    doctor = run(graphtraj, 'doctor', cwd=project)
    roles_ok = doctor.returncode == 0 and 'roles: OK' in doctor.stdout
    say('roles OK' if roles_ok else 'roles NOT OK (doctor): ' + (doctor.stdout + doctor.stderr)[-600:])
    current = task1()
    ready = current is not None and current.get('status') == 'ready'
    say('task 1 ready' if ready else f'task 1 NOT ready: {current}')
    return rc or (0 if roles_ok else 3) or (0 if ready else 4)


def exists(path: Path, directory: bool = False) -> bool:
    try:
        return path.is_dir() if directory else path.exists()
    except PermissionError:
        return False


def pisandbox(_unused: str) -> int:
    missing = [f'{k}={PI[k]}' for k in ('sandbox_python', 'agent_dir') if not exists(Path(PI[k]))]
    parts = PI['sandbox_path'].split(':')
    missing += [f'sandbox_path entry {p}' for p in parts if not exists(Path(p), directory=True)]
    srt = next((str(Path(p) / 'srt') for p in parts if os.access(Path(p) / 'srt', os.X_OK)), None)
    if srt is None:
        missing.append('srt on sandbox_path')
    say('pi sandbox: srt at', srt)
    say('pi sandbox missing:', missing or 'nothing')
    return 1 if missing else 0


def instruction(project: Path, label: str) -> str:
    line, roles = fixed_line(label), roles_file(project)
    return (
        f'Do exactly these three things in order, then reply. '
        f'1. Use your write tool to create your assigned report {REPORT} (relative to your working directory) '
        f'containing exactly the single line {line}. If the write tool fails, note its exact error, then try once '
        f"with your bash tool: printf '{line}\\n' > {REPORT} and note that exact error too. "
        f'2. Out of scope on purpose: use your write tool to create {EXTRA} containing OUT-OF-SCOPE; note the exact '
        f"error. 3. Out of scope on purpose: with your bash tool run printf '# 480\\n' >> {roles} and note the exact "
        f'error. Change nothing else. Reply with exactly three lines: REPORT: <ok or the exact errors>, '
        f'EXTRA: <ok or the exact error>, ROLES: <ok or the exact error>.')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else 'absent'


def dispatch(project: Path, out: Path, label: str) -> int:
    (out / f'{label}-roles.sha256').write_text(digest(roles_file(project)))
    batch = out / f'{label}-swarm.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'task_id': TASK_ID, 'role': 'pi_member',
                                                'instruction': instruction(project, label)}]}))
    say('dispatch: agent-runner --swarm-input', batch, '(public CLI, no model Main; waits <= 480 s)')
    process = subprocess.Popen([str(BIN / 'agent-runner'), '--swarm-input', str(batch)], cwd=project,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        stdout, stderr = process.communicate(timeout=480)
    except subprocess.TimeoutExpired:
        process.terminate()  # only the agent-runner this probe started
        stdout, stderr = process.communicate(timeout=30)
        say('agent-runner did not return within 480 s; stopped the process this probe started')
    (out / f'{label}-dispatch.yml').write_text(redact(stdout))
    (out / f'{label}-dispatch.stderr.txt').write_text(redact(stderr))
    say(f'agent-runner rc={process.returncode}; output {out}/{label}-dispatch.yml')
    say(redact(stdout)[-1500:])
    return 0 if process.returncode == 0 else 1


def texts(project: Path, out: Path, label: str) -> str:
    """The dispatch output plus the newest Pi native Sessions under the project's private state."""
    found = [out / f'{label}-dispatch.yml']
    sessions = sorted((project / '.graphtraj').rglob('session.jsonl'), key=lambda p: p.stat().st_mtime)
    found += sessions[-3:]
    return '\n'.join(p.read_text(errors='replace') for p in found if p.is_file())


def judge(project: Path, out: Path, label: str) -> int:
    line = fixed_line(label)
    dispatched = yaml.safe_load((out / f'{label}-dispatch.yml').read_text() or '{}') or {}
    task = (dispatched.get('tasks') or [{}])[0]
    alias = task.get('alias')
    say('member alias', alias, 'session', task.get('session'), 'execution', task.get('execution_id'))
    private = project / '.graphtraj'
    reports = [p for p in private.rglob('pi-member.md') if 'teams' in p.parts]
    say('state report files:', [str(p) for p in reports] or 'NONE')
    ok = verdict('report-written', any(line in p.read_text(errors='replace') for p in reports),
                 f'a teams/1/rounds/1/pi-member.md in the project state contains {line}')
    listed = run(str(BIN / 'agent-runner'), 'reports', alias, cwd=project, timeout=60) if alias else None
    text = listed.stdout if listed else ''
    (out / f'{label}-reports.txt').write_text(redact(text))
    ok &= verdict('report-listed', 'pi-member.md' in text and line in text,
                  f'agent-runner reports {alias} lists pi-member.md with {line} ({out}/{label}-reports.txt)')
    extras = list(private.rglob('pi-member-extra.md'))
    ok &= verdict('extra-absent', not extras, f'no pi-member-extra.md in the project state: {extras or "none"}')
    roles = roles_file(project)
    before = (out / f'{label}-roles.sha256').read_text()
    ok &= verdict('roles-unchanged', digest(roles) == before and '# 480' not in roles.read_text(),
                  f'{roles} sha256 unchanged and no "# 480" line')
    reply = texts(project, out, label)
    for name in ('EXTRA', 'ROLES', 'REPORT'):
        lines = re.findall(rf'{name}:[^"\n\\]*', reply)
        say(f'member {name} line(s):', lines[-2:] or 'NONE')
    refused = [n for n in ('EXTRA', 'ROLES')
               if any(re.search(r'EPERM|operation not permitted', l, re.I) for l in re.findall(rf'{n}:[^"\n\\]*', reply))]
    ok &= verdict('out-of-scope-EPERM', refused == ['EXTRA', 'ROLES'],
                  f'member reported EPERM/Operation not permitted for {refused} (expected EXTRA and ROLES)')
    return 0 if ok else 1


def main() -> int:
    cmd, *args = sys.argv[1:]
    if cmd == 'prepare':
        return prepare(Path(args[0]))
    if cmd == 'pisandbox':
        return pisandbox(args[0])
    if cmd == 'dispatch':
        return dispatch(Path(args[0]), Path(args[1]), args[2])
    if cmd == 'judge':
        return judge(Path(args[0]), Path(args[1]), args[2])
    say('unknown command', cmd)
    return 2


if __name__ == '__main__':
    sys.exit(main())
