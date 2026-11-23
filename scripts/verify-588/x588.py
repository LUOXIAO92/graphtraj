"""Task 588 real-host helper, run by steps.zsh with the isolated project's venv Python inside the project.

    python -I x588.py prepare <project>             roles (opus_coding_team.engineer, claude) + Task 1, ready
    python -I x588.py instruction <project>         the Engineer's instruction (also Task 1's body text)
    python -I x588.py ended <project> <alias> <s>   the Session's current execution has its terminal record
    python -I x588.py check <project> <alias>       PASS/FAIL: the two reports read back through session_reports
                                                    hold the probe texts, the refusal lists the assigned names,
                                                    nothing was written elsewhere

Adapted from scripts/verify-521/x521.py (prepare, ended). It never signals a process and never writes outside the
project, except that check reads (never writes) the Engineer's own Claude transcript when it is present.
Exit status: 0 = the observation passed, 1 = it failed, 2 = could not observe.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import yaml

from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.configuration.project_roles import roles_file

CONNECTION = 'claude/anthropic/opus-5_5'   # the production opus_coding_team presets' connection (user catalog)
ROLE = 'opus_coding_team.engineer'
TASK_ID, TASK_NAME = '1', 'submit-report-name-probe'
BARE, PATH_FORM, UNASSIGNED = 'engineer.md', '.state/teams/1/rounds/1/validation.md', 'engineer-budget'
TEXT_BARE, TEXT_PATH = 'probe bare', 'probe path'
LISTED = 'Assigned reports: engineer.md, validation.md'
INSTRUCTION = (
    'This is a scripted probe of the GraphTraj tasks tool feature submit_report. Change no file and run no shell '
    'command. Make exactly these three calls with the tasks tool (action execute, feature submit_report), in this '
    f'order, each with notify_parent false: 1) name "{BARE}", text "{TEXT_BARE}"; 2) name "{PATH_FORM}", text '
    f'"{TEXT_PATH}"; 3) name "{UNASSIGNED}", text "probe refused" (a refusal is expected). Do not retry a call or '
    'change a name. Do not call submit_result. Then reply with the three raw results verbatim, one per line, as '
    'RESULT1: ..., RESULT2: ..., RESULT3: ..., and end your turn.'
)
BODY = f'''---
difficulty: low
difficulty_reason: 588 real-host probe
execution_budget:
  estimated_minutes:
    total: 15
  estimation_note: 588 probe
  planned_sessions:
    engineer: 1
  correction_rounds: 0
  on_exceed: Notify the caller
---
# 588 probe {TASK_NAME}

{INSTRUCTION}
'''


def run(*argv: str, cwd: Path) -> subprocess.CompletedProcess:
    """Run one command in the project; echo a failure."""
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


def task_directory(project: Path) -> Path:
    return load_project_configuration(project).state / 'tasks' / f'{TASK_ID}-{TASK_NAME}'


def session_dir(project: Path, alias: str) -> Path:
    return load_project_configuration(project).runner / 'sessions' / alias


def prepare(project: Path) -> int:
    path = roles_file(project)
    path.write_text(yaml.safe_dump({
        'roles': {'opus_coding_team': {'engineer': {
            'connection': CONNECTION, 'reasoning_effort': 'high', 'reports': ['engineer.md', 'validation.md'],
            'claude': {'permission_mode': 'auto'}}}},
        'role_tree': {ROLE: {}}}, sort_keys=False))
    print(f'roles file: {path}')
    work = project / '.graphtraj/probe-588'
    work.mkdir(exist_ok=True)
    (work / 'evidence.md').write_text('588 probe: ready.\n')
    graph = run(tool('graphtraj'), 'task', 'graph', cwd=project)
    known = ({t.get('task_id') for t in (yaml.safe_load(graph.stdout) or {}).get('tasks', [])}
             if graph.returncode == 0 else set())
    rc = 0
    if TASK_ID in known:
        print(f'task {TASK_ID} already registered: register skipped')
    else:
        register = work / 'register.yml'
        register.write_text(yaml.safe_dump({
            'task_id': TASK_ID, 'task_name': TASK_NAME, 'source': 'local:scratch/588', 'title': TASK_NAME,
            'body': BODY, 'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
            'replaced_by': [], 'retirement_reason': None}))
        state = work / 'ready.yml'
        state.write_text(yaml.safe_dump({
            'task_id': TASK_ID, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
            'current_candidate': None, 'caused_by_event_ids': [],
            'evidence_refs': ['.graphtraj/probe-588/evidence.md']}))
        rc |= run(tool('graphtraj'), 'task', 'register', '--task-file', str(register), cwd=project).returncode
        rc |= run(tool('graphtraj'), 'task', 'update', '--state-file', str(state), cwd=project).returncode
    doctor = run(tool('graphtraj'), 'doctor', cwd=project)
    roles_ok = 'roles: OK' in doctor.stdout
    print(f'roles OK ({ROLE}: connection {CONNECTION}, reports engineer.md validation.md)' if roles_ok
          else 'roles NOT OK: ' + (doctor.stdout + doctor.stderr)[-600:])
    status = read(task_directory(project) / 'task.yml').get('status')
    print(f'task {TASK_ID} {TASK_NAME}: status {status} (ready before the dispatch)')
    return 1 if rc or not roles_ok or status != 'ready' else 0


def ended(project: Path, alias: str, seconds: float) -> int:
    """The Session's current execution (mapping.yml execution_id) has its terminal execution.yml."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        current = read(session_dir(project, alias) / 'mapping.yml').get('execution_id')
        terminal = read(session_dir(project, alias) / 'execution.yml')
        if current is not None and terminal.get('execution_id') == current and 'outcome' in terminal:
            print(f'{alias}: execution {current} ended ({terminal.get("outcome")})')
            return 0
        time.sleep(3)
    print(f'{alias}: current execution did not end within {seconds:.0f} s')
    return 2


def transcript_calls(session: str) -> list[tuple[dict, str]]:
    """The Engineer's own submit_report calls and raw results from its Claude transcript (read only), if present."""
    files = sorted((Path.home() / '.claude/projects').glob(f'*/{session}.jsonl'))
    if not files:
        return []
    uses, results = {}, {}
    for line in files[0].read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        content = (record.get('message') or {}).get('content')
        for item in content if isinstance(content, list) else []:
            if not isinstance(item, dict):
                continue
            if item.get('type') == 'tool_use' and 'submit_report' in json.dumps(item.get('input')):
                uses[item.get('id')] = item.get('input')
            elif item.get('type') == 'tool_result':
                body = item.get('content')
                if isinstance(body, list):
                    body = ' '.join(part.get('text', '') for part in body if isinstance(part, dict))
                results[item.get('tool_use_id')] = str(body)
    return [(arguments, results.get(identifier, '(no result)')) for identifier, arguments in uses.items()]


def check(project: Path, alias: str) -> int:
    directory = session_dir(project, alias)
    mapping = read(directory / 'mapping.yml')
    terminal = read(directory / 'execution.yml')
    print(f'alias {alias} | role {mapping.get("role_reference") or mapping.get("role")} | '
          f'report_files {mapping.get("report_files")} | outcome {terminal.get("outcome")}')
    shown = run(tool('agent-runner'), 'reports', alias, cwd=project)
    if shown.returncode:
        return 2
    document = yaml.safe_load(shown.stdout) or {}
    rounds = task_directory(project) / 'teams/1/rounds/1'
    texts = {Path(report['path']).name: report['text'] for report in document.get('reports', [])}
    paths = {Path(report['path']).name: report['path'] for report in document.get('reports', [])}
    print('session_reports (agent-runner reports, read back):')
    for name, text in texts.items():
        print(f'  {paths[name]}: {text!r}')
    message = str(terminal.get('last_agent_message') or '')
    print('Engineer last message (verbatim):')
    print('  ' + message.replace('\n', '\n  '))
    session = mapping.get('session')
    session = session.get('id', '') if isinstance(session, dict) else str(session or '')
    calls = transcript_calls(session.split(':')[-1]) if session else []
    print(f'submit_report calls in the Engineer\'s Claude transcript (read only): {len(calls)}')
    for arguments, result in calls:
        print(f'  call {json.dumps(arguments)}\n    -> {result}')
    refusal = [result for arguments, result in calls if UNASSIGNED in json.dumps(arguments)]
    refused = refusal[0] if refusal else message
    # A submit_report write holds exactly its text; any such file outside Round 1 was written elsewhere.
    probes = {TEXT_BARE, TEXT_PATH, 'probe refused'}
    written = sorted(str(path.relative_to(project)) for path in project.rglob('*')
                     if path.is_file() and '.git' not in path.parts and path.parent != rounds
                     and (path.name.startswith(UNASSIGNED) or _text(path).strip() in probes))
    worktree = Path(mapping.get('worktree_path') or project)
    dirty = run('git', '-C', str(worktree), 'status', '--porcelain', cwd=project).stdout.strip()
    checks = {
        f'{BARE} (bare name) holds {TEXT_BARE!r} at {rounds / "engineer.md"}':
            texts.get('engineer.md') == TEXT_BARE and paths.get('engineer.md') == str(rounds / 'engineer.md'),
        f'validation.md (path form {PATH_FORM}) holds {TEXT_PATH!r} at {rounds / "validation.md"}':
            texts.get('validation.md') == TEXT_PATH and paths.get('validation.md') == str(rounds / 'validation.md'),
        f'the {UNASSIGNED!r} call was refused with authority-denied and lists "{LISTED}"':
            'authority-denied' in refused and LISTED in refused,
        'Round 1 holds only engineer.md and validation.md':
            sorted(path.name for path in rounds.iterdir()) == ['engineer.md', 'validation.md'],
        f'nothing written elsewhere (no {UNASSIGNED}* file, no file holding a probe text outside Round 1, '
        'Worktree clean)':
            not written and not dirty,
    }
    if written or dirty:
        print(f'  elsewhere: {written} | Worktree status: {dirty!r}')
    if not calls:
        print('  (no transcript found: the refusal check reads the Engineer\'s verbatim reply instead)')
    for name, ok in checks.items():
        print(f'  {"PASS" if ok else "FAIL"} {name}')
    return 0 if all(checks.values()) else 1


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8', errors='replace') if path.stat().st_size < 64 else ''
    except OSError:
        return ''


def main() -> int:
    command, project = sys.argv[1], Path(sys.argv[2]).resolve()
    if command == 'prepare':
        return prepare(project)
    if command == 'instruction':
        print(INSTRUCTION)
        return 0
    if command == 'ended':
        return ended(project, sys.argv[3], float(sys.argv[4]))
    if command == 'check':
        return check(project, sys.argv[3])
    print(f'unknown command {command}')
    return 2


if __name__ == '__main__':
    sys.exit(main())
