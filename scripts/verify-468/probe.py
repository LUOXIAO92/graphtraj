"""468 probe helper: one actively working Claude Task member and its Runner Worker's CPU.

Usage (a scratch venv's Python, -I, from its isolated project):
  python -I probe.py fix SRC -                whether the venv imports SRC; whether SRC has the 468 change
  python -I probe.py prepare PROJECT MODEL    roles (team_leader claude, permission_mode auto); Task 1 ready
  python -I probe.py isolation PROJECT -      project root, git top level, CLAUDE.md upward
  python -I probe.py init STREAM HARNESS      the init record (model, apiKeySource name, plugins) and the
                                              instruction files the host says it was given
  python -I probe.py run PROJECT FACTS        FACTS (JSON, written by steps.zsh): label, out. Dispatches Task 1's
                                              member with agent-runner (refuses when it has one), samples its
                                              Worker with ps every ~10 s for <= 9 min, prints CPU-s per wall-s
  python -I probe.py compare BEFORE AFTER     the two runs' results side by side, with the verdict
The member works actively: many short Bash calls, each with output. Signals nothing; reads no key.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

TASK = '1'
STEPS = 60  # each Bash output ~4.4 KB (400 lines): ~265 KB in all
SAMPLE_SECONDS = 10
WAIT_SECONDS = 520  # plus <= 30 s for agent-runner to return: the step stays under 10 min
# AFTER passes when its Worker used less than this share of one core while the member worked.
AFTER_LIMIT = 0.25
BODY = '''---
difficulty: low
difficulty_reason: Scratch probe for 468
execution_budget:
  estimated_minutes:
    total: 30
  planned_sessions:
    team_leader: 1
  correction_rounds: 0
  estimation_note: One Claude member that works for several minutes
  on_exceed: Report only
---
Follow the dispatch instruction exactly.
'''


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def run(*argv: str, **kwargs) -> subprocess.CompletedProcess:
    done = subprocess.run(argv, capture_output=True, text=True, timeout=300, **kwargs)
    print(f'$ {" ".join(Path(a).name if i == 0 else a for i, a in enumerate(argv[-4:]))} -> rc={done.returncode}')
    if done.returncode:
        print(done.stdout[-600:], done.stderr[-600:])
    return done


def fix(source: Path, _unused: str) -> int:
    """Print whether the venv imports SOURCE and whether SOURCE has the 468 change (both venvs pass)."""
    import graftling.sessions.archive as archive
    import graphtraj.execution.runner_worker as worker

    files = [Path(module.__file__).resolve() for module in (archive, worker)]
    inside = all(source.resolve() in path.parents for path in files)
    changed = hasattr(archive.JsonlSessionStore, 'batch') and hasattr(worker, 'BUDGET_SAMPLE_SECONDS')
    print('imports:', ', '.join(map(str, files)), '| under', source, ':', inside)
    print('468 fix loaded:', 'YES' if changed else 'NO')
    return 0 if inside else 1


def prepare(project: Path, model: str) -> int:
    bin_dir = Path(sys.executable).parent
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'team_leader': {'runtime': 'claude', 'model': model, 'worktree_access': 'write',
                                  'reports': ['report.md'], 'claude': {'permission_mode': 'auto'}}},
        'role_tree': {'team_leader': {}},
    }))
    work = project / '.graphtraj/probe-468'
    work.mkdir(exist_ok=True)
    register = work / 'register.yml'
    register.write_text(yaml.safe_dump({
        'task_id': TASK, 'task_name': 'busy-worker-probe', 'source': 'local:scratch/468', 'title': 'busy worker probe',
        'body': BODY, 'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
        'replaced_by': [], 'retirement_reason': None}))
    state = work / 'state.yml'
    state.write_text(yaml.safe_dump({
        'task_id': TASK, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
        'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-468/evidence.md']}))
    (work / 'evidence.md').write_text('468 probe: ready for one Claude member.\n')
    rc = 0
    if not list(project.glob(f'.graphtraj/state/tasks/{TASK}-*/task.yml')):
        rc = run(str(bin_dir / 'graphtraj'), 'task', 'register', '--task-file', str(register), cwd=project).returncode
    rc = rc or run(str(bin_dir / 'graphtraj'), 'task', 'update', '--state-file', str(state), cwd=project).returncode
    doctor = run(str(bin_dir / 'graphtraj'), 'doctor', cwd=project)
    print('roles OK' if 'roles: OK' in doctor.stdout else 'roles NOT OK: ' + doctor.stdout[-400:])
    graph = run(str(bin_dir / 'graphtraj'), 'task', 'graph', cwd=project)
    ready = sorted(task['task_id'] for task in (yaml.safe_load(graph.stdout) or {}).get('tasks', [])
                   if task['status'] == 'ready')
    print('probe Task ready:', 'YES' if ready == [TASK] else f'NO (ready: {ready})')
    return rc or ('roles: OK' not in doctor.stdout) or ready != [TASK]


def isolation(project: Path, _unused: str) -> int:
    """Print how discovery stops at the isolated project (read only)."""
    from graphtraj.workspace.runner_project import discover_project_root

    root = discover_project_root(project)
    top = subprocess.run(['git', '-C', str(project), 'rev-parse', '--show-toplevel'],
                         capture_output=True, text=True).stdout.strip()
    upward = [str(p / name) for p in (project, *project.parents) for name in ('CLAUDE.md', 'CLAUDE.local.md')
              if (p / name).exists()]
    print(f'graphtraj project root: {root} | isolated: {root == project.resolve()}')
    print(f'git top level: {top} | isolated: {Path(top).resolve() == project.resolve() if top else False}')
    print(f'CLAUDE.md/CLAUDE.local.md at or above the project: {upward or "none"}')
    ok = root == project.resolve() and top and Path(top).resolve() == project.resolve() and not upward
    print('isolation:', 'OK' if ok else 'NOT OK')
    return 0 if ok else 1


def init(stream: Path, harness: str) -> int:
    """Print the host's init record and its answer; refuse a Harness instruction file."""
    plugins, text, model_ok = None, '', False
    for line in stream.read_text().splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get('type') == 'system' and record.get('subtype') == 'init':
            plugins = [item.get('name') if isinstance(item, dict) else item for item in record.get('plugins', [])]
            print('init: version', record.get('claude_code_version'), '| model', record.get('model'),
                  '| apiKeySource', record.get('apiKeySource'), '(a source name, never a key)')
            print('plugins loaded:', plugins)
            print('cc-plugin-agents-md loaded:', 'YES' if any('cc-plugin-agents-md' in str(n) for n in plugins) else 'NO')
        if record.get('type') == 'result':
            text = record.get('result') or ''
            model_ok = 'MODEL OK' in text
            print('result:', ' | '.join(text.splitlines()), '| is_error:', record.get('is_error'),
                  '| models:', list((record.get('modelUsage') or {}).keys()))
    leaked = [word for word in re.split(r'[\s,]+', text) if word.startswith(harness) and '/tmp/468/' not in word]
    print('Harness instruction files loaded:', leaked or 'none')
    if plugins is None:
        print('init: none in the stream')
    return 0 if plugins is not None and model_ok and not leaked else 1


def instruction() -> str:
    steps = [f'Step {n:02d}: write the sentence "Now step {n:02d}." then call the Bash tool with exactly '
             f"`seq -f '468-{n:02d}-%g' 1 400`." for n in range(1, STEPS + 1)]
    return ' '.join([
        'This is a scripted probe; do exactly these steps in order and nothing else. Write each step\'s sentence as '
        'its own short text before that step\'s tool call. Use only the Bash tool, one call per step, never in '
        'parallel, and do not summarize the output.', *steps, 'Finally reply with exactly: DONE-468'])


def seconds(text: str) -> float:
    """Parse ps cumulative CPU time: [[dd-]hh:]mm:ss[.ss]."""
    days, _, text = text.rpartition('-')
    total = 0.0
    for part in text.split(':'):
        total = total * 60 + float(part)
    return (int(days) if days else 0) * 86400 + total


def ps_sample(pid: int) -> tuple[str, float] | None:
    """One raw ps line for ``pid`` (pid, ppid, %cpu, cumulative CPU time, elapsed, command) or None if gone."""
    done = subprocess.run(['ps', '-o', 'pid=,ppid=,pcpu=,time=,etime=,command=', '-p', str(pid)],
                          capture_output=True, text=True)
    line = done.stdout.strip()
    if done.returncode or not line:
        return None
    return line, seconds(line.split()[3])


def diagnostics(directory: Path, execution: str | None) -> dict:
    path = directory / f'claude-diagnostics-{execution}.yml'
    try:
        return (yaml.safe_load(path.read_text()) or {}).get('collection_progress') or {}
    except (OSError, yaml.YAMLError):
        return {}


def find_member(runner: Path) -> tuple[Path, int, str] | None:
    """Task 1's member Session directory and its Worker pid, once a record names it."""
    for directory in sorted((runner / 'sessions').glob(f'{TASK}-*team_leader*')):
        for name in ('heartbeat.yml', 'mapping.yml'):
            try:
                record = yaml.safe_load((directory / name).read_text()) or {}
            except (OSError, yaml.YAMLError):
                continue
            if isinstance(record, dict) and isinstance(record.get('worker_pid'), int):
                return directory, record['worker_pid'], name
    return None


def run_member(project: Path, facts_file: str) -> int:
    """Dispatch Task 1's member, sample its Worker's CPU while it works, print the ratio and verdict."""
    from graphtraj.configuration.project_configuration import runner_directory
    from graphtraj.execution.runner_status import status_aliases
    from graphtraj.runtimes.claude.adapter import current_cli

    facts = json.loads(Path(facts_file).read_text())
    runner = runner_directory(project)
    existing = sorted(path.name for path in (runner / 'sessions').glob(f'{TASK}-*team_leader*') if path.is_dir())
    if existing:
        print(f'STOP: Task {TASK} already has a member {existing}; nothing was dispatched.')
        return 2
    binary, version = current_cli()
    print(f'member Claude Code (Runner resolves claude on PATH): {binary} | {version}')
    batch = Path(facts_file).with_suffix('.swarm.yml')
    batch.write_text(yaml.safe_dump({'tasks': [{'task_id': TASK, 'role': 'team_leader', 'instruction': instruction()}]}))
    # agent-runner returns only when the member's turn ends, so it runs in the
    # background while this samples the member's Worker. It is never signalled.
    output = Path(facts_file).with_suffix('.agent-runner.txt')
    with output.open('w') as stream:
        dispatch = subprocess.Popen([str(Path(sys.executable).parent / 'agent-runner'), '--swarm-input', str(batch)],
                                    cwd=project, stdout=stream, stderr=subprocess.STDOUT, text=True)
    print(f'{now()} agent-runner started (pid {dispatch.pid}); its output: {output}')
    raw = Path(facts['out']).with_suffix('.ps.txt')
    samples, found, seen_running = [], None, False
    deadline = time.monotonic() + WAIT_SECONDS
    with raw.open('w') as log:
        while time.monotonic() < deadline:
            if found is None:
                found = find_member(runner)
                if found is not None:
                    print(f'{now()} member {found[0].name} | Worker pid {found[1]} (from {found[2]})')
                elif dispatch.poll() is not None:
                    print(f'{now()} agent-runner ended (rc {dispatch.returncode}) before a Worker was seen')
                    break
            if found is not None:
                directory, worker, _ = found
                sample = ps_sample(worker)
                stamp = time.monotonic()
                if sample is None:
                    print(f'{now()} Worker {worker} has exited')
                    break
                samples.append((stamp, sample[1]))
                line = f'{now()} {sample[0][:200]}'
                print(line, flush=True)
                log.write(line + '\n')
                activity = status_aliases([directory.name], project).document['aliases'][0].get('activity')
                seen_running = seen_running or activity == 'running'
                if activity != 'running' and (seen_running or dispatch.poll() is not None):
                    print(f'{now()} member activity: {activity} (its turn ended)')
                    break
            time.sleep(SAMPLE_SECONDS if found is not None else 1)
        else:
            print(f'STOP: still running after {WAIT_SECONDS} s; the samples so far are used. Nothing was signalled.')
    try:
        dispatch.wait(timeout=30)
    except subprocess.TimeoutExpired:
        print(f'agent-runner (pid {dispatch.pid}) still running; not signalled. Its output: {output}')
    print(f'agent-runner rc {dispatch.returncode}; last output: {output.read_text()[-300:]!r}')
    if found is None:
        print('STOP: no member Worker was found')
        return 1
    directory, worker, _ = found
    alias = directory.name
    mapping = yaml.safe_load((directory / 'mapping.yml').read_text()) or {}
    progress = diagnostics(directory, mapping.get('execution_id'))
    print(f'collection_progress: batches {progress.get("batches")} | elapsed_seconds {progress.get("elapsed_seconds")}')
    working = samples  # (monotonic time, cumulative CPU seconds), taken while the member's turn ran
    ratio = None
    if len(working) >= 3:
        (t0, c0), (t1, c1) = working[0], working[-1]
        ratio = (c1 - c0) / (t1 - t0) if t1 > t0 else None
        intervals = [round((b[1] - a[1]) / (b[0] - a[0]), 3) for a, b in zip(working, working[1:]) if b[0] > a[0]]
        print(f'per-interval CPU-s per wall-s: {intervals}')
        print(f'Worker CPU while the member worked: {c1 - c0:.2f} CPU-s over {t1 - t0:.1f} wall-s '
              f'= {ratio:.3f} CPU-s per wall-s ({len(working)} samples)')
    else:
        print(f'too few samples ({len(working)}): the member ended within {SAMPLE_SECONDS * 2} s')
    value = status_aliases([alias], project).document['aliases'][0]
    print(f"member: activity {value.get('activity')} | last_outcome {value.get('last_outcome')}")
    result = {'label': facts['label'], 'alias': alias, 'worker_pid': worker, 'ratio': ratio,
              'samples': len(working), 'batches': progress.get('batches'),
              'collection_elapsed_seconds': progress.get('elapsed_seconds'), 'raw': str(raw)}
    Path(facts['out']).write_text(json.dumps(result, indent=2))
    print(f'== {facts["label"]}: {"n/a" if ratio is None else f"{ratio:.3f}"} CPU-s per wall-s '
          f'(written to {facts["out"]})')
    return 0 if ratio is not None else 1


def compare(before: Path, after: str) -> int:
    """Print BEFORE and AFTER side by side and the verdict."""
    first, second = json.loads(before.read_text()), json.loads(Path(after).read_text())
    for run_ in (first, second):
        print(f"{run_['label']:6s}: Worker {run_['worker_pid']} {run_['ratio']} CPU-s per wall-s | samples "
              f"{run_['samples']} | collection batches {run_['batches']} in {run_['collection_elapsed_seconds']} s")
    ok = (first['ratio'] is not None and second['ratio'] is not None
          and second['ratio'] < AFTER_LIMIT and second['ratio'] < first['ratio'])
    print(f"== verdict: {'PASS' if ok else 'FAIL'}: AFTER {second['ratio']} CPU-s per wall-s "
          f"(limit {AFTER_LIMIT}) vs BEFORE {first['ratio']}")
    return 0 if ok else 1


if __name__ == '__main__':
    command, target, extra = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    commands = {'fix': fix, 'prepare': prepare, 'isolation': isolation, 'init': init,
                'run': run_member, 'compare': compare}
    raise SystemExit(commands[command](target, extra))
