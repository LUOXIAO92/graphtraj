"""465 probe helper: roles, probe Tasks, seeded associations, one Runner-launched Claude member, and the CHECKs.

Usage (the scratch venv's Python, -I, from the isolated project):
  python -I probe.py prepare PROJECT MODEL     roles (team_leader claude, permission_mode auto); Tasks 1 and 2 ready;
                                               isolation facts (project root, git top level, CLAUDE.md upward)
  python -I probe.py seed PROJECT COUNT:DIR    add COUNT associated Sessions: runner session.yml records whose
                                               rollout_path names a dummy JSONL under DIR (half Claude-like, half
                                               Codex-like); also one Claude and one Codex Session in the isolated
                                               archive (SEEDED_CLAUDE/SEEDED_CODEX native IDs). Prints the total.
  python -I probe.py run PROJECT FACTS         FACTS is a JSON file written by steps.zsh: task, label, target
                                               (session_read ID), unassociated (file), credential (file),
                                               expect_version. Dispatches one member with agent-runner, waits
                                               (<= 9 min) until it settles, prints the CHECKs and the settings counts.
  python -I probe.py plugins STREAM -          prints the init record's model/apiKeySource (a source name, never a key)
Signals nothing. Never reads or prints a credential: the member checks the credential file with a Bash redirect
only, and this probe prints only fixed RESULT fields, never tool output.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import yaml

TASKS = {'1': 'history-grants-probe-323', '2': 'history-grants-probe-325'}
SEEDED_CLAUDE = '4650c1a0-0000-4000-8000-000000000465'
SEEDED_CODEX = '01a1d465-0000-7000-8000-000000000465'
BODY = '''---
difficulty: low
difficulty_reason: Scratch probe for 465
execution_budget:
  estimated_minutes:
    total: 30
  planned_sessions:
    team_leader: 1
  correction_rounds: 0
  estimation_note: One Claude member checks Bash startup, session_read and read denials
  on_exceed: Report only
---
Follow the dispatch instruction exactly.
'''
RESULT = re.compile(r'RESULT-465 bash=(\S+) session_read=(\S+) unassoc_bash=(\S+) unassoc_read=(\S+) cred_bash=(\S+)')


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def run(*argv: str, **kwargs) -> subprocess.CompletedProcess:
    done = subprocess.run(argv, capture_output=True, text=True, timeout=300, **kwargs)
    print(f'$ {" ".join(Path(a).name if i == 0 else a for i, a in enumerate(argv[-4:]))} -> rc={done.returncode}')
    if done.returncode:
        print(done.stdout[-600:], done.stderr[-600:])
    return done


def prepare(project: Path, model: str) -> int:
    bin_dir = Path(sys.executable).parent
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'team_leader': {'runtime': 'claude', 'model': model, 'worktree_access': 'write',
                                  'reports': ['report.md'], 'claude': {'permission_mode': 'auto'}}},
        'role_tree': {'team_leader': {}},
    }))
    work = project / '.graphtraj/probe-465'
    work.mkdir(exist_ok=True)
    rc = 0
    for task_id, name in TASKS.items():
        register = work / f'register-{task_id}.yml'
        register.write_text(yaml.safe_dump({
            'task_id': task_id, 'task_name': name, 'source': 'local:scratch/465', 'title': name, 'body': BODY,
            'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
            'replaced_by': [], 'retirement_reason': None}))
        state = work / f'state-{task_id}.yml'
        state.write_text(yaml.safe_dump({
            'task_id': task_id, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
            'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-465/evidence.md']}))
        if not list(project.glob(f'.graphtraj/state/tasks/{task_id}-*/task.yml')):
            rc = rc or run(str(bin_dir / 'graphtraj'), 'task', 'register', '--task-file', str(register), cwd=project).returncode
        (work / 'evidence.md').write_text('465 probe: ready for one Claude member per Claude Code version.\n')
        rc = rc or run(str(bin_dir / 'graphtraj'), 'task', 'update', '--state-file', str(state), cwd=project).returncode
    doctor = run(str(bin_dir / 'graphtraj'), 'doctor', cwd=project)
    print('roles OK' if 'roles: OK' in doctor.stdout else 'roles NOT OK: ' + doctor.stdout[-400:])
    graph = run(str(bin_dir / 'graphtraj'), 'task', 'graph', cwd=project)
    tasks = (yaml.safe_load(graph.stdout) or {}).get('tasks', [])
    ready = sorted(task['task_id'] for task in tasks if task['status'] == 'ready')
    print('ready tasks:', ready)
    return rc or ('roles: OK' not in doctor.stdout) or ready != sorted(TASKS)


def isolation(project: Path, _unused: str) -> int:
    """Print how discovery stops at the isolated project (read only)."""
    from graphtraj.workspace.runner_project import discover_project_root

    root = discover_project_root(project)
    top = subprocess.run(['git', '-C', str(project), 'rev-parse', '--show-toplevel'], capture_output=True, text=True).stdout.strip()
    upward = [str(p / name) for p in (project, *project.parents) for name in ('CLAUDE.md', 'CLAUDE.local.md')
              if (p / name).exists()]
    agents = [str(p / 'AGENTS.md') for p in project.parents if (p / 'AGENTS.md').exists()]
    print(f'graphtraj project root: {root} | isolated: {root == project.resolve()}')
    print(f'git top level: {top} | isolated: {Path(top).resolve() == project.resolve() if top else False}')
    print(f'CLAUDE.md/CLAUDE.local.md at or above the project: {upward or "none"}')
    print(f'AGENTS.md above the project (Claude Code does not load AGENTS.md; graphtraj stops at the project): {agents or "none"}')
    ok = root == project.resolve() and top and Path(top).resolve() == project.resolve() and not upward
    print('isolation:', 'OK' if ok else 'NOT OK')
    return 0 if ok else 1


def header(identity: str, runtime: str, native: str) -> dict:
    from graftling.sessions.protocol import upgrade_header

    value = upgrade_header({'version': 4, 'id': identity, 'createdAt': 1, 'isSeeded': False,
                            'graphtraj': {'version': 1, 'projectId': 'project', 'agentId': 'seed-465',
                                          'taskIds': ['1'], 'native': {'runtime': runtime, 'sessionId': native,
                                                                       'locator': 'header'}}})
    value['native'].update(runtime=runtime, sessionId=native)
    return value


def seed(project: Path, spec: str) -> int:
    from graphtraj.configuration.project_configuration import runner_directory
    from graphtraj.interfaces.agents import swarm_root
    from graphtraj.runtimes.codex.access import project_history_files
    from graftling.sessions.archive import SessionArchive
    from graftling.sessions.protocol import retain_native

    count, _, directory = spec.partition(':')
    homes = Path(directory)
    sessions = runner_directory(project) / 'sessions'
    start = len(list(sessions.glob('seed-465-*')))
    for index in range(start, start + int(count)):
        if index % 2:
            native = homes / f'codex/sessions/2026/11/14/rollout-2026-11-14T00-00-00-{index:05d}.jsonl'
        else:
            native = homes / f'claude/projects/-seed-465/{uuid.UUID(int=index)}.jsonl'
        native.parent.mkdir(parents=True, exist_ok=True)
        native.write_text('{"type": "seed-465", "content": "dummy associated history"}\n')
        record = sessions / f'seed-465-{index:05d}/session.yml'
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(yaml.safe_dump({'session': f'seed-465-native-{index:05d}', 'rollout_path': str(native)}))
    archive = SessionArchive(swarm_root(project), save_normalized_sessions=True)
    for runtime, native in (('claude', SEEDED_CLAUDE), ('codex', SEEDED_CODEX)):
        identity = f'{runtime}:{native}'
        if archive.native_header(runtime, native):
            continue
        archive.map_session(header(identity, runtime, native))
        archive.collect(identity, [retain_native(runtime, {'text': f'SEEDED-465 {runtime} associated session'},
                                                 session_id=native, locator='byte:0', seq=0, time=1)],
                        source='rollout', position=1)
    associated = project_history_files(project)
    print(f'seeded runner records: {len(list(sessions.glob("seed-465-*")))} | associated JSONL files '
          f'(project_history_files): {len(associated)}')
    print(f'isolated archive: SEEDED_CLAUDE={SEEDED_CLAUDE} SEEDED_CODEX={SEEDED_CODEX}')
    return 0


def plugins(stream: Path, _unused: str) -> int:
    for line in stream.read_text().splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get('type') == 'system' and record.get('subtype') == 'init':
            print('init: version', record.get('claude_code_version'), '| model', record.get('model'),
                  '| apiKeySource', record.get('apiKeySource'))
            return 0
    print('init: none in the stream')
    return 1


def instruction(target: str, unassociated: str, credential: str) -> str:
    return ' '.join([
        'Do exactly these steps, in order, and nothing else. Do not read, print or quote any file content.',
        '1. Bash tool: run exactly `echo bash-ok`.',
        f'2. Call the mcp__agents__tasks tool with action execute, feature session_read, arguments '
        f'{{"session_id": "{target}", "limit": 5}}. Note the returned header id (or ERROR if it fails).',
        f'3. Bash tool: run exactly `cat {unassociated} >/dev/null 2>&1 && echo READABLE || echo DENIED`.',
        f'4. Read tool on {unassociated} with limit 1. Do not repeat its content; note only READABLE if it '
        'returned content, otherwise DENIED.',
        f'5. Bash tool: run exactly `cat {credential} >/dev/null 2>&1 && echo READABLE || echo DENIED`. '
        'Never read that file in any other way.',
        'Then reply with exactly one line: RESULT-465 bash=<step 1 output> session_read=<header id or ERROR> '
        'unassoc_bash=<READABLE|DENIED> unassoc_read=<READABLE|DENIED> cred_bash=<READABLE|DENIED>',
    ])


def strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def settings_counts(directory: Path) -> dict:
    path = directory / 'claude-settings.yml'
    if not path.is_file():
        return {'file': None}
    data = yaml.safe_load(path.read_text())
    settings = data.get('settings', data) if isinstance(data, dict) else {}
    permissions = settings.get('permissions', {})
    filesystem = settings.get('sandbox', {}).get('filesystem', {})
    return {'file': str(path), 'bytes': path.stat().st_size,
            'allow': len(permissions.get('allow', [])), 'deny': len(permissions.get('deny', [])),
            'additionalDirectories': len(permissions.get('additionalDirectories', [])),
            **{key: len(filesystem.get(key, [])) for key in ('allowRead', 'denyRead', 'allowWrite', 'denyWrite')},
            'seeded paths present': sum('seed-465' in line for line in path.read_text().splitlines())}


def member_aliases(runner: Path, task: str) -> list[str]:
    """Existing member Session directories of one probe Task (read only)."""
    return sorted(path.name for path in (runner / 'sessions').glob(f'{task}-*team_leader*') if path.is_dir())


def read_all(project: Path, runner: Path, alias: str, session_id: str) -> tuple[list[str], int, int]:
    """Read every page (limit 1000, the archive's maximum) as the member; return strings, pages, events."""
    from graphtraj.execution.runner_status import runtime_caller
    from graphtraj.sessions.query import read_session

    texts, after, pages, events = [], -1, 0, 0
    with runtime_caller(runner, alias):
        while True:
            page = read_session(project, session_id, after, 1000)
            pages += 1
            events += len(page.get('events', []))
            # Every page carries the header and the unfinished output ('pending').
            texts.extend(strings(page))
            if not page.get('has_more') or page.get('after', after) == after:
                return texts, pages, events
            after = page['after']


def check_version(facts: dict) -> str | None:
    from graphtraj.runtimes.claude.adapter import current_cli

    binary, version = current_cli()
    print(f'member Claude Code (Runner resolves claude on PATH): {binary} | {version}')
    if facts['expect_version'] not in version:
        print(f"STOP: expected {facts['expect_version']}; nothing was dispatched or collected")
        return None
    return version


def run_member(project: Path, facts_file: str) -> int:
    """Dispatch one fresh member for facts['task'], then collect it. Refuses if the Task already has a member."""
    from graphtraj.configuration.project_configuration import runner_directory

    facts = json.loads(Path(facts_file).read_text())
    runner = runner_directory(project)
    existing = member_aliases(runner, facts['task'])
    if existing:
        print(f"STOP: Task {facts['task']} already has a member {existing}; nothing was dispatched. "
              f"Use the collect-only step for it.")
        return 2
    if check_version(facts) is None:
        return 1
    batch = Path(facts_file).with_suffix('.swarm.yml')
    batch.write_text(yaml.safe_dump({'tasks': [{'task_id': facts['task'], 'role': 'team_leader',
                                                'instruction': instruction(facts['target'], facts['unassociated'],
                                                                           facts['credential'])}]}))
    done = run(str(Path(sys.executable).parent / 'agent-runner'), '--swarm-input', str(batch), cwd=project)
    Path(facts_file).with_suffix('.dispatch.yml').write_text(done.stdout)
    if done.returncode:
        return 1
    task = yaml.safe_load(done.stdout)['tasks'][0]
    print(f"{now()} agent-runner returned: alias={task.get('alias')} execution_id={task.get('execution_id')} "
          f"session={task.get('session')}")
    return collect_member(project, facts_file, task)


def collect(project: Path, facts_file: str) -> int:
    """Collect-only: the existing member of facts['task']; dispatches nothing."""
    from graphtraj.configuration.project_configuration import runner_directory

    facts = json.loads(Path(facts_file).read_text())
    dispatch = Path(facts_file).with_suffix('.dispatch.yml')
    if dispatch.is_file() and dispatch.read_text().strip():
        task = yaml.safe_load(dispatch.read_text())['tasks'][0]
        print(f"dispatch record {dispatch.name}: alias={task.get('alias')} execution_id={task.get('execution_id')} "
              f"session={task.get('session')}")
    else:
        aliases = member_aliases(runner_directory(project), facts['task'])
        if len(aliases) != 1:
            print(f"STOP: Task {facts['task']} has members {aliases}; expected exactly one. Nothing was collected.")
            return 1
        # No saved agent-runner stdout (the first 02 run did not keep it): the expected native
        # Session is the one that run printed ('settled: ... native=...'), passed by steps.zsh.
        task = {'alias': aliases[0], 'session': facts.get('expect_session') or None}
        print(f"no dispatch record; the Task's only member alias={task['alias']} expected session={task['session']}")
        if not task['session']:
            print('STOP: no expected session to match; nothing was collected.')
            return 1
    return collect_member(project, facts_file, task)


def collect_member(project: Path, facts_file: str, task: dict) -> int:
    from graphtraj.configuration.project_configuration import runner_directory
    from graphtraj.execution.runner_status import runtime_caller, status_aliases
    from graphtraj.sessions.query import read_session

    facts = json.loads(Path(facts_file).read_text())
    version = check_version(facts)
    if version is None:
        return 1
    runner = runner_directory(project)
    seeded = len(list((runner / 'sessions').glob('seed-465-*')))
    print(f'associated seeded Sessions now: {seeded}')
    alias = task['alias']
    mapping_file = runner / 'sessions' / alias / 'mapping.yml'
    print(f'{now()} waiting (<= 9 min) for {alias}')
    deadline = time.time() + 540
    value = {}
    while time.time() < deadline:
        value = status_aliases([alias], project).document['aliases'][0]
        if value.get('activity') != 'running' and mapping_file.is_file():
            break
        time.sleep(5)
    else:
        print(f'STOP: {alias} still running after 9 min: activity={value.get("activity")}. Rerun the collect-only step later.')
        return 1
    mapping = yaml.safe_load(mapping_file.read_text()) or {}
    native = mapping.get('session')
    print(f'{now()} settled: activity={value.get("activity")} last_outcome={value.get("last_outcome")}')
    # The settle must belong to this dispatch, not to an earlier execution of the alias.
    print(f"identity: dispatched execution_id={task.get('execution_id')} session={task.get('session')} | "
          f"mapping execution_id={mapping.get('execution_id')} session={native}")
    same = ((task.get('execution_id') is not None and task.get('execution_id') == mapping.get('execution_id'))
            or (task.get('session') is not None and task.get('session') == native))
    if not same:
        print('STOP: mapping.yml names another execution and Session than the dispatch; nothing was checked.')
        return 1
    texts, pages, events = read_all(project, runner, alias, native)
    print(f'member Session read: {pages} page(s), {events} events')
    joined = '\n'.join(texts)
    results = [m for text in texts for m in RESULT.finditer(text)]
    result = results[-1].groups() if results else None
    counts = settings_counts(runner / 'sessions' / alias)
    with runtime_caller(runner, alias):
        try:
            target_id = read_session(project, facts['target'], -1, 1)['header']['id']
        except (ValueError, KeyError) as error:
            target_id = f'unreadable-by-probe ({type(error).__name__})'
    checks = [
        ('no E2BIG / Could not start', 'E2BIG' not in joined and 'Could not start' not in joined),
        ('bash-ok present', 'bash-ok' in joined and bool(result) and result[0] == 'bash-ok'),
        (f'session_read returned header {target_id}', bool(result) and result[1] == target_id),
        ('unassociated session file: Bash DENIED', bool(result) and result[2] == 'DENIED'),
        ('unassociated session file: Read DENIED', bool(result) and result[3] == 'DENIED'),
        ('~/.codex credential file: Bash DENIED', bool(result) and result[4] == 'DENIED'),
        ('claude-settings.yml has no seeded path', counts.get('seeded paths present') == 0),
    ]
    print('RESULT line:', ' '.join(results[-1].group(0).split()) if results else 'none')
    print('settings:', json.dumps(counts))
    for number, (label, ok) in enumerate(checks, 1):
        print(f'CHECK {number} {"PASS" if ok else "FAIL"}: {label}')
    Path(facts_file).with_suffix('.out.json').write_text(json.dumps({
        'alias': alias, 'execution_id': mapping.get('execution_id'), 'native': native, 'version': version,
        'seeded': seeded, 'settings': counts,
        'result': results[-1].group(0) if results else None, 'checks': dict(checks)}, indent=2))
    summary = all(ok for _, ok in checks)
    print('== summary:', 'ALL PASS' if summary else f'{sum(not ok for _, ok in checks)} FAIL of {len(checks)}')
    return 0 if summary else 1


if __name__ == '__main__':
    command, target, extra = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    commands = {'prepare': prepare, 'isolation': isolation, 'seed': seed, 'plugins': plugins,
                'run': run_member, 'collect': collect}
    raise SystemExit(commands[command](target, extra))
