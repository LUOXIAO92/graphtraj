"""Task 521 real-host helper, run by steps.zsh with the candidate venv's Python inside the isolated project.

    python -I x521.py prepare <project>             roles (read-only investigator, Sonnet) + Task 1, ready
    python -I x521.py instruction <project>         the investigator's instruction (Task 1's registered body text)
    python -I x521.py ended <project> <alias> <s>   the Session's current execution has its terminal record
    python -I x521.py submitted <project> <alias> <s>   standards 1 and 3: launch access read, its latest submission
                                                    names its own report in result_refs and retains a copy of it
    python -I x521.py decide <project> <alias>      Main's decide-result accepted on that submission, then the event

Adapted from scripts/verify-490/x490.py (prepare, ended, decide). It never signals a process.
Exit status: 0 = the observation passed, 1 = it failed, 2 = could not observe.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import yaml

MODEL = 'claude-sonnet-5-5'
CONNECTION = 'claude/anthropic/sonnet-5_5'   # user catalog ${HOME}/.graphtraj/connections.yml (508's launch.yml)
TASK_ID, TASK_NAME = '1', 'read-only-report-result'
REPORT = '.state/teams/1/rounds/1/investigation.md'
MARK = 'FINDING-521'
INSTRUCTION = (
    'You are a read-only investigator; you change no file. Step 1: read README.md in your Worktree. '
    'Step 2: run exactly one Bash command: git rev-parse HEAD. It prints the full 40-character commit hash. '
    f'Step 3: use the GraphTraj tasks tool feature submit_report with name investigation.md and a text whose first '
    f'line is "{MARK}" and whose second line quotes the first line of README.md. '
    'Step 4: use the GraphTraj tasks tool feature submit_result with commit = that full hash exactly as printed, '
    f'result_refs = ["{REPORT}"] (your own report is your result; do not name any other file), evidence_refs = [], '
    'completion = "investigation report submitted", unresolved = []. Then reply with one line DONE.'
)
BODY = f'''---
difficulty: low
difficulty_reason: 521 real-host probe
execution_budget:
  estimated_minutes:
    total: 20
  estimation_note: 521 probe
  planned_sessions:
    investigator: 1
  correction_rounds: 0
  on_exceed: Notify the caller
---
# 521 probe {TASK_NAME}

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


def task_record(project: Path) -> dict:
    return read(project / '.graphtraj/state/tasks' / f'{TASK_ID}-{TASK_NAME}' / 'task.yml')


def session_dir(project: Path, alias: str) -> Path:
    return project / '.graphtraj/runner/sessions' / alias


def prepare(project: Path) -> int:
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        # A model other than claude-opus-5-5 needs a catalog connection: the one Task 508's investigator used.
        'roles': {'investigator': {'connection': CONNECTION, 'worktree_access': 'read',
                                   'reports': ['investigation.md'], 'claude': {'permission_mode': 'auto'}}},
        'role_tree': {'investigator': {}}}))
    work = project / '.graphtraj/probe-521'
    work.mkdir(exist_ok=True)
    (work / 'evidence.md').write_text('521 probe: ready.\n')
    graph = run(tool('graphtraj'), 'task', 'graph', cwd=project)
    known = {t.get('task_id') for t in (yaml.safe_load(graph.stdout) or {}).get('tasks', [])} if graph.returncode == 0 else set()
    rc = 0
    if TASK_ID in known:
        print(f'task {TASK_ID} already registered: register skipped')
    else:
        register = work / 'register.yml'
        register.write_text(yaml.safe_dump({
            'task_id': TASK_ID, 'task_name': TASK_NAME, 'source': 'local:scratch/521', 'title': TASK_NAME,
            'body': BODY, 'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
            'replaced_by': [], 'retirement_reason': None}))
        state = work / 'ready.yml'
        state.write_text(yaml.safe_dump({
            'task_id': TASK_ID, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
            'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-521/evidence.md']}))
        rc |= run(tool('graphtraj'), 'task', 'register', '--task-file', str(register), cwd=project).returncode
        rc |= run(tool('graphtraj'), 'task', 'update', '--state-file', str(state), cwd=project).returncode
    doctor = run(tool('graphtraj'), 'doctor', cwd=project)
    print(f'roles OK (investigator: connection {CONNECTION} = {MODEL}, worktree_access read)' if 'roles: OK' in doctor.stdout
          else 'roles NOT OK: ' + doctor.stdout[-600:])
    status = task_record(project).get('status')
    print(f'task {TASK_ID} {TASK_NAME}: status {status} (ready before A; implementing after A started)')
    return 1 if rc or 'roles: OK' not in doctor.stdout else 0


def ended(project: Path, alias: str, seconds: float) -> int:
    """The Session's current execution (mapping.yml execution_id) has its terminal execution.yml."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        current = read(session_dir(project, alias) / 'mapping.yml').get('execution_id')
        terminal = read(session_dir(project, alias) / 'execution.yml')
        if current is not None and terminal.get('execution_id') == current and 'outcome' in terminal:
            print(f'{alias}: execution {current} ended ({terminal.get("outcome")}); '
                  f'last_agent_message: {terminal.get("last_agent_message")!r}')
            return 0
        time.sleep(2)
    print(f'{alias}: current execution did not end within {seconds:.0f} s')
    return 2


def latest_submission(project: Path, alias: str) -> dict | None:
    shown = run(tool('agent-runner'), 'reports', alias, cwd=project)
    submissions = ((yaml.safe_load(shown.stdout) or {}) if shown.returncode == 0 else {}).get('submissions') or []
    return submissions[-1] if submissions else None


def submitted(project: Path, alias: str, seconds: float) -> int:
    """Observe standards 1 and 3 from the retained records only."""
    deadline = time.time() + seconds
    while (latest := latest_submission(project, alias)) is None and time.time() < deadline:
        time.sleep(5)
    directory = session_dir(project, alias)
    request = read(directory / 'launch.yml').get('adapter_request', {})
    access = request.get('worktree_access')
    print(f'launch.yml adapter_request: worktree_access {access} (expected read), model {request.get("model")}, '
          f'connection {request.get("connection")}')
    if latest is None:
        print(f'{alias} submitted nothing within {seconds:.0f} s')
        return 2
    task = task_record(project)
    worktree = project / task['worktree']
    head = run('git', '-C', str(worktree), 'rev-parse', 'HEAD', cwd=project).stdout.strip()
    report = project / '.graphtraj/state/tasks' / f'{TASK_ID}-{TASK_NAME}' / REPORT.removeprefix('.state/')
    print(f'submission {latest["event_id"]} (event {latest["event"]}, alias {latest["alias"]}, role {latest["role"]})')
    print(f'  candidate {latest["candidate"]} | Worktree HEAD {head}')
    print(f'  result_refs {latest["result_refs"]}')
    print(f'  evidence_refs {latest["evidence_refs"]}')
    copies = [project / ref for ref in latest['evidence_refs']]
    same = [copy for copy in copies if copy.is_file() and report.is_file() and copy.read_bytes() == report.read_bytes()]
    checks = {
        'launch access is read': access == 'read',
        'result_refs is exactly the own report': latest['result_refs'] == [REPORT],
        'candidate is the Worktree HEAD': latest['candidate'] == head,
        f'report {report} exists and holds {MARK}': report.is_file() and MARK in report.read_text(),
        'a retained copy under traces/<alias>/<event_id>/ equals the report':
            any(f'/traces/{alias}/{latest["event_id"]}/' in copy.as_posix() for copy in same),
    }
    for name, ok in checks.items():
        print(f'  {"OK " if ok else "NO "} {name}')
    for copy in same:
        print(f'  retained copy: {copy}')
    return 0 if all(checks.values()) else 1


def decide(project: Path, alias: str) -> int:
    latest = latest_submission(project, alias)
    if latest is None:
        print(f'{alias} has no submission; run step A first')
        return 2
    evidence = project / 'decision-521.md'
    evidence.write_text(f'Submission {latest["event_id"]}: result_refs {latest["result_refs"]}; '
                        f'retained {latest["evidence_refs"]}\n')
    arguments = ['decide-result', '--submission-id', latest['event_id'], '--commit', latest['candidate'],
                 '--decision', 'accepted', '--reason', '521 probe: the investigator report is the result',
                 '--evidence-ref', evidence.name]
    for ref in latest.get('evidence_refs') or []:
        arguments += ['--evidence-ref', ref]
    decided = run(tool('agent-runner'), *arguments, cwd=project)
    document = (yaml.safe_load(decided.stdout) or {}) if decided.returncode == 0 else {}
    status = task_record(project).get('status')
    print(f'decision event {document.get("event")} id {document.get("event_id")} '
          f'submission_id {document.get("submission_id")} candidate {document.get("candidate")}')
    ok = (decided.returncode == 0 and document.get('event') == 'team-round-accepted'
          and document.get('submission_id') == latest['event_id'])
    print(f'decision: {"OK" if ok else "NO"} (task {TASK_ID} status {status}; expected awaiting-integration)')
    return 0 if ok else 1


def junit_outcomes(junit: Path, root: Path) -> dict[str, str]:
    """pytest node id -> passed/failed/error/skipped from a junit file of a run under <root>."""
    import xml.etree.ElementTree as ElementTree

    outcomes = {}
    for case in ElementTree.parse(junit).getroot().iter('testcase'):
        parts = (case.get('classname') or '').split('.')
        # The longest dotted prefix naming a file under root is the module; the rest are classes.
        for cut in range(len(parts), 0, -1):
            if (root / Path(*parts[:cut])).with_suffix('.py').is_file():
                node = '::'.join([Path(*parts[:cut]).with_suffix('.py').as_posix(), *parts[cut:], case.get('name', '')])
                break
        else:
            node = f'{case.get("classname")}::{case.get("name")}'
        kinds = {child.tag for child in case}
        outcomes[node] = ('error' if 'error' in kinds else 'failed' if 'failure' in kinds
                          else 'skipped' if 'skipped' in kinds else 'passed')
    return outcomes


def failed_ids(junit: Path, root: Path) -> int:
    """Print the failed or errored ids of a run, one per line."""
    for node, outcome in junit_outcomes(junit, root).items():
        if outcome in ('failed', 'error'):
            print(node)
    return 0


def compare(failed: Path, baseline_junit: Path, baseline_collected: Path, baseline_root: Path) -> int:
    """Each candidate failure against the baseline: new = failed on the candidate, passed or absent on the baseline."""
    ids = [line for line in failed.read_text().splitlines() if line.strip()]
    collected = {line for line in baseline_collected.read_text().splitlines() if '::' in line}
    outcomes = junit_outcomes(baseline_junit, baseline_root) if baseline_junit.is_file() else {}
    new = []
    for node in ids:
        outcome = outcomes.get(node) or ('absent (not collected on the baseline)' if node not in collected else 'not run')
        print(f'{node}: candidate-failed / baseline-{outcome}')
        if outcome != 'failed' and outcome != 'error':
            new.append(node)
    print(f'\nnew failures (failed on the candidate, not failing on the baseline): {len(new)}')
    for node in new:
        print(f'  NEW {node}')
    print('PASS (none new)' if not new else 'FAIL')
    return 0 if not new else 1


def main() -> int:
    command, project = sys.argv[1], Path(sys.argv[2])
    if command == 'failed-ids':
        return failed_ids(project, Path(sys.argv[3]))
    if command == 'compare':
        return compare(project, Path(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[5]))
    if command == 'prepare':
        return prepare(project)
    if command == 'instruction':
        print(INSTRUCTION)
        return 0
    if command == 'ended':
        return ended(project, sys.argv[3], float(sys.argv[4]))
    if command == 'submitted':
        return submitted(project, sys.argv[3], float(sys.argv[4]))
    if command == 'decide':
        return decide(project, sys.argv[3])
    print(f'unknown command {command}')
    return 2


if __name__ == '__main__':
    sys.exit(main())
