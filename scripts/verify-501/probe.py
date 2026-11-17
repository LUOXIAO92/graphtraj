"""501 probe helper: a Claude Task member that creates an agents Claude child, and the member's Runner Worker.

Usage (a scratch venv's Python, -I, from its isolated project):
  python -I probe.py imports SRC -            which graphtraj/graftling this venv imports, and the profiler hook
  python -I probe.py prepare PROJECT MODEL    roles (team_leader claude, permission_mode auto); Task 1 ready
  python -I probe.py isolation PROJECT -      project root, git top level, CLAUDE.md upward
  python -I probe.py init STREAM HARNESS      the host's init record (model, apiKeySource name) and its answer
  python -I probe.py run PROJECT FACTS        FACTS (JSON from steps.zsh): label, out, prof. Dispatches Task 1's
                                              member (refuses when it has one), samples its Worker with ps every
                                              ~10 s (raw lines kept) with the child's running state, then reports
  python -I probe.py report RESULT -          per-phase CPU, the CHECK 468 window, and the profiler's stacks
  python -I probe.py compare BEFORE AFTER     two results side by side
The member creates one child that keeps six tool processes (sleeps) alive for ~2.5 min, waits for it, then reads
it back. Signals nothing; reads no key.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import yaml

TASK = '1'
CHILD = 'cpu501-child'
SAMPLE_SECONDS = 10
WAIT_SECONDS = 560  # plus <= 30 s for agent-runner to return: the step stays under 10 min
LIMIT_468 = 0.25
BODY = '''---
difficulty: low
difficulty_reason: Scratch probe for 501
execution_budget:
  estimated_minutes:
    total: 30
  planned_sessions:
    team_leader: 1
  correction_rounds: 0
  estimation_note: One Claude member and one agents child for several minutes
  on_exceed: Report only
---
Follow the dispatch instruction exactly.
'''
# A Python frame that only waits (the thread is blocked in C below it); everything else counts as work.
IDLE = re.compile(r'^(threading\.py:(wait|_wait_for_tstate_lock|join)|queue\.py:get|selectors\.py:select|'
                  r'socket\.py:(readinto|accept)|subprocess\.py:(_wait|wait|_communicate|communicate)|'
                  r'prof501\.py)|:(sleep|_sleep|wait|_wait|read|readline|recv|accept|poll|select)\b')


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def run(*argv: str, **kwargs) -> subprocess.CompletedProcess:
    done = subprocess.run(argv, capture_output=True, text=True, timeout=300, **kwargs)
    print(f'$ {" ".join(Path(a).name if i == 0 else a for i, a in enumerate(argv[-4:]))} -> rc={done.returncode}')
    if done.returncode:
        print(done.stdout[-600:], done.stderr[-600:])
    return done


def imports(source: Path, _unused: str) -> int:
    """Print where graphtraj and graftling come from, the graftling version and whether prof501 is installed."""
    import graftling
    import graphtraj
    import importlib.util
    import importlib.metadata

    gt, gl = Path(graphtraj.__file__).resolve(), Path(graftling.__file__).resolve()
    print(f'graphtraj: {gt} | under {source}: {source.resolve() in gt.parents}')
    print(f'graftling: {gl} {importlib.metadata.version("graftling")}')
    spec = importlib.util.find_spec('prof501')
    print(f'profiler hook prof501: {spec.origin if spec else "not installed"}')
    return 0 if source.resolve() in gt.parents else 1


def prepare(project: Path, model: str) -> int:
    bin_dir = Path(sys.executable).parent
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'team_leader': {'runtime': 'claude', 'model': model, 'worktree_access': 'write',
                                  'reports': ['report.md'], 'claude': {'permission_mode': 'auto'}}},
        'role_tree': {'team_leader': {}},
    }))
    work = project / '.graphtraj/probe-501'
    work.mkdir(exist_ok=True)
    register = work / 'register.yml'
    register.write_text(yaml.safe_dump({
        'task_id': TASK, 'task_name': 'worker-cpu-probe', 'source': 'local:scratch/501', 'title': 'worker cpu probe',
        'body': BODY, 'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
        'replaced_by': [], 'retirement_reason': None}))
    state = work / 'state.yml'
    state.write_text(yaml.safe_dump({
        'task_id': TASK, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
        'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-501/evidence.md']}))
    (work / 'evidence.md').write_text('501 probe: ready for one Claude member.\n')
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
            print('cc-plugin-agents-md loaded:', 'YES' if any('cc-plugin-agents-md' in str(n) for n in plugins) else 'NO')
        if record.get('type') == 'result':
            text = record.get('result') or ''
            model_ok = 'MODEL OK' in text
            print('result:', ' | '.join(text.splitlines()), '| is_error:', record.get('is_error'),
                  '| models:', list((record.get('modelUsage') or {}).keys()))
    leaked = [word for word in re.split(r'[\s,]+', text) if word.startswith(harness) and '/tmp/501/' not in word]
    print('Harness instruction files loaded:', leaked or 'none')
    if plugins is None:
        print('init: none in the stream')
    return 0 if plugins is not None and model_ok and not leaked else 1


def child_message() -> str:
    """The child's steps: six tool processes alive for ~2.5 min, then output like 499's child."""
    hold = 'sleep {0}1 & sleep {0}2 & sleep {0}3 & sleep {0}4 & sleep {0}5 & sleep {0}0; echo 501-held-{0}'
    steps = [f"Step 01: write 'Now step 01.' then call Bash with exactly: {hold.format(7)}",
             f"Step 02: write 'Now step 02.' then call Bash with exactly: {hold.format(7)}"]
    steps += [f"Step {n:02d}: write 'Now step {n:02d}.' then call Bash with exactly: seq -f '501-{n:02d}-%g' 1 400"
              for n in range(3, 13)]
    return ('This is a scripted probe. Do exactly these steps in order, one Bash call at a time, never in parallel, '
            'nothing else; do not summarize output. ' + '; '.join(steps) + '. Then reply with exactly: DONE-501-CHILD')


def instruction() -> str:
    return (
        'This is a scripted probe. Do NOT call submit_result or submit_report. '
        f'(a) Using the agents tool, create ONE claude child named {CHILD} with configuration team_leader and this '
        f'message: <<{child_message()}>>. Quote the raw create result (agent id, execution id). If the child asks to '
        'approve a Bash command, approve exactly the commands the message lists. '
        '(b) Call agents wait on that agent id with timeout_seconds 300, repeating until its execution has ended; '
        'quote the final last_message. '
        '(c) Call the agents tool feature session_read on the child three times: {agent: <agent id>}; '
        '{agent: <agent id>, start: -10, stop: -5}; {agent: <agent id>, search: 501-08}. For each quote one compact '
        'line: total, start, stop and the size of the result; no event contents. '
        '(d) Retire the child by its agent id and quote the raw result. Then reply with exactly: DONE-501 and end '
        'your turn.')


def seconds(text: str) -> float:
    """Parse ps cumulative CPU time: [[dd-]hh:]mm:ss[.ss]."""
    days, _, text = text.rpartition('-')
    total = 0.0
    for part in text.split(':'):
        total = total * 60 + float(part)
    return (int(days) if days else 0) * 86400 + total


def ps_sample(pid: int) -> str | None:
    """One raw ps line for ``pid`` (pid, ppid, %cpu, cumulative CPU time, elapsed, command) or None if gone."""
    done = subprocess.run(['ps', '-o', 'pid=,ppid=,pcpu=,time=,etime=,command=', '-p', str(pid)],
                          capture_output=True, text=True)
    line = done.stdout.strip()
    return None if done.returncode or not line else line


def child_running(project: Path) -> bool | None:
    """True while the child's last execution has no outcome (None: no child record yet)."""
    for path in (project / '.graphtraj/swarm/control/agents').glob('*.json'):
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if record.get('name') == CHILD:
            executions = record.get('executions') or []
            return bool(executions) and executions[-1].get('outcome') is None
    return None


def tool_processes(worker: int) -> int:
    """The number of live processes below the Worker (its Claude member, the child and their tools)."""
    out = subprocess.run(['ps', '-axo', 'pid=,ppid='], capture_output=True, text=True).stdout
    children = defaultdict(list)
    for line in out.splitlines():
        pid, ppid = map(int, line.split())
        children[ppid].append(pid)
    count, pending = 0, [worker]
    while pending:
        for child in children.get(pending.pop(), ()):
            count += 1
            pending.append(child)
    return count


def find_member(runner: Path) -> tuple[Path, int] | None:
    for directory in sorted((runner / 'sessions').glob(f'{TASK}-*team_leader*')):
        for name in ('heartbeat.yml', 'mapping.yml'):
            try:
                record = yaml.safe_load((directory / name).read_text()) or {}
            except (OSError, yaml.YAMLError):
                continue
            if isinstance(record, dict) and isinstance(record.get('worker_pid'), int):
                return directory, record['worker_pid']
    return None


def run_member(project: Path, facts_file: str) -> int:
    """Dispatch Task 1's member, sample its Worker until the turn ends, write the raw samples and the result."""
    from graphtraj.configuration.project_configuration import runner_directory
    from graphtraj.execution.runner_status import status_aliases

    facts = json.loads(Path(facts_file).read_text())
    runner = runner_directory(project)
    existing = sorted(path.name for path in (runner / 'sessions').glob(f'{TASK}-*team_leader*') if path.is_dir())
    if existing:
        print(f'STOP: Task {TASK} already has a member {existing}; nothing was dispatched (rerun step 0).')
        return 2
    batch = Path(facts_file).with_suffix('.swarm.yml')
    batch.write_text(yaml.safe_dump({'tasks': [{'task_id': TASK, 'role': 'team_leader', 'instruction': instruction()}]}))
    output = Path(facts_file).with_suffix('.agent-runner.txt')
    with output.open('w') as stream:
        dispatch = subprocess.Popen([str(Path(sys.executable).parent / 'agent-runner'), '--swarm-input', str(batch)],
                                    cwd=project, stdout=stream, stderr=subprocess.STDOUT, text=True)
    print(f'{now()} agent-runner started (pid {dispatch.pid}, never signalled); its output: {output}')
    raw = Path(facts['out']).with_suffix('.ps.jsonl')
    found, seen_running = None, False
    deadline = time.monotonic() + WAIT_SECONDS
    with raw.open('w') as log:
        while time.monotonic() < deadline:
            if found is None:
                found = find_member(runner)
                if found is not None:
                    print(f'{now()} member {found[0].name} | Worker pid {found[1]}')
                elif dispatch.poll() is not None:
                    print(f'{now()} agent-runner ended (rc {dispatch.returncode}) before a Worker was seen')
                    break
            if found is not None:
                directory, worker = found
                line = ps_sample(worker)
                if line is None:
                    print(f'{now()} Worker {worker} has exited')
                    break
                row = {'at': time.time(), 'child_running': child_running(project),
                       'below_worker': tool_processes(worker), 'ps': line[:300]}
                log.write(json.dumps(row) + '\n')
                log.flush()
                print(f"{now()} child_running={row['child_running']} below={row['below_worker']} {line[:150]}",
                      flush=True)
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
    result = {'label': facts['label'], 'alias': found[0].name, 'worker_pid': found[1], 'raw': str(raw),
              'prof': str(Path(facts['prof']) / f'{found[1]}.jsonl')}
    Path(facts['out']).write_text(json.dumps(result, indent=2))
    return report(Path(facts['out']), '-')


def phases(rows: list[dict]) -> list[str]:
    """Per sample: start (before the child), child (while it runs), after (once it ended)."""
    labels, seen = [], False
    for row in rows:
        if row['child_running']:
            seen = True
            labels.append('child')
        else:
            labels.append('after' if seen else 'start')
    return labels


def report(result_file: Path, _unused: str) -> int:
    """Per-phase Worker CPU, the CHECK 468 window, and what the Worker's threads ran in its busiest windows."""
    result = json.loads(result_file.read_text())
    rows = [json.loads(line) for line in Path(result['raw']).read_text().splitlines() if line.strip()]
    for row in rows:
        row['cpu'] = seconds(row['ps'].split()[3])
    labels = phases(rows)
    print(f"== {result['label']}: Worker {result['worker_pid']} | {len(rows)} samples (raw {result['raw']})")
    spans = defaultdict(lambda: [0.0, 0.0])
    for (a, b, label) in zip(rows, rows[1:], labels[1:]):
        spans[label][0] += b['cpu'] - a['cpu']
        spans[label][1] += b['at'] - a['at']
    for label in ('start', 'child', 'after'):
        cpu, wall = spans[label]
        print(f'phase {label:5s}: {cpu:6.1f} CPU-s / {wall:6.0f} wall-s = '
              f'{(cpu / wall if wall else float("nan")):.3f}')
    busy = [row for row in rows if row['child_running']]
    window = None
    if len(busy) >= 2 and busy[-1]['at'] > busy[0]['at']:
        window = (busy[-1]['cpu'] - busy[0]['cpu']) / (busy[-1]['at'] - busy[0]['at'])
        print(f"CHECK 468 window (child_running=True, first to last sample): {busy[-1]['cpu'] - busy[0]['cpu']:.1f} / "
              f"{busy[-1]['at'] - busy[0]['at']:.0f} = {window:.3f} (limit {LIMIT_468}); processes below the Worker "
              f"while the child ran: {sorted({row['below_worker'] for row in busy})}")
    else:
        print('CHECK 468 window: n/a (fewer than two samples while the child ran)')
    result['window_468'] = window
    result['phases'] = {label: spans[label] for label in spans}
    profile(Path(result['prof']), rows, labels)
    result_file.write_text(json.dumps(result, indent=2))
    return 0 if window is not None else 1


def profile(path: Path, rows: list[dict], labels: list[str]) -> None:
    """Sum the profiler windows by phase; print the top working stacks per phase."""
    if not path.is_file():
        print(f'profile: none at {path}')
        return
    windows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def phase_at(at: float) -> str:
        label = 'start'
        for row, name in zip(rows, labels):
            if row['at'] <= at:
                label = name
        return label

    totals = defaultdict(Counter)
    cpu = defaultdict(float)
    own = 0.0
    print(f'profile: {len(windows)} windows of ~10 s ({path})')
    for window in windows:
        label = phase_at(window['at'])
        cpu[label] += window['cpu']
        own += window.get('sampler_cpu', 0.0)
        work = Counter()
        for thread, stacks in window['threads'].items():
            for stack, count in stacks.items():
                if not IDLE.search(stack.split(' < ')[0]):
                    work[f'[{thread}] {stack}'] += count
        totals[label].update(work)
        top = work.most_common(1)
        print(f"  {time.strftime('%H:%M:%S', time.localtime(window['at']))} {label:5s} cpu "
              f"{window['cpu'] / window['wall']:.2f} | ticks {window['ticks']} | top working: "
              f"{(top[0][0][:160] + f' x{top[0][1]}') if top else '-'}")
    print(f'profiler own CPU: {own:.1f} s in all')
    for label in ('start', 'child', 'after'):
        print(f'-- top working stacks in phase {label} (Worker CPU {cpu[label]:.1f} s; counts at ~50/s):')
        for stack, count in totals[label].most_common(8):
            print(f'   x{count:5d} {stack[:400]}')


def compare(before: Path, after: str) -> int:
    first, second = json.loads(before.read_text()), json.loads(Path(after).read_text())
    for item in (first, second):
        rates = {k: round(c / w, 3) if w else None for k, (c, w) in item.get('phases', {}).items()}
        print(f"{item['label']:6s}: CHECK 468 window {item.get('window_468')} | phases {rates}")
    ok = second.get('window_468') is not None and second['window_468'] < LIMIT_468
    print(f"== before/after: {first.get('window_468')} -> {second.get('window_468')} "
          f"({'below' if ok else 'NOT below'} {LIMIT_468})")
    return 0 if ok else 1


if __name__ == '__main__':
    command, target, extra = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    commands = {'imports': imports, 'prepare': prepare, 'isolation': isolation, 'init': init,
                'run': run_member, 'report': report, 'compare': compare}
    raise SystemExit(commands[command](target, extra))
