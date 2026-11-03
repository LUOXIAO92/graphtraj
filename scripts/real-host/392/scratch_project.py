"""Real Task members in a scratch GraphTraj project, for the 416 and 420 checks.

Usage (from a step, RH_* set, the dedicated GraphTraj venv's Python): python -E -s scratch_project.py <function>

The project follows the layout 420 ran and this file's author dry-ran in the sandbox at the same code,
as far as `graphtraj setup`, `roles: OK`, register, ready and dispatch: one Git repository in
target-project, `.graphtraj` beside it, roles naming a Runtime and model directly, so the user's
~/.graphtraj/connections.yml is neither read for them nor changed. The Runner's own tools run from the
venv by absolute path, on a PATH that does not hold the venv, which is the condition 420 fixed.
"""
from __future__ import annotations

import functools
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time

import yaml

from rh392 import CODEX_MODEL, DEEPSEEK_MODEL, ENV, OUT, PI_PROVIDER, RUN, SANDBOX_PATH, SANDBOX_PYTHON, check, judge, keep_tree, note

BIN = Path(sys.executable).parent
HARNESS = RUN / 'harness'
PROJECT = HARNESS / 'target-project'
STATE = HARNESS / '.graphtraj' / 'state'
LIMIT = 1200


def environment() -> dict:
    """Return this shell's environment for the Runner: no other host's markers, no venv on PATH."""
    kept = {name: value for name, value in ENV.items()
            if not name.startswith(('GRAPHTRAJ_', 'AGENT_SWARM_', 'AGENTS_', 'RH_', 'CLAUDECODE', 'CODEX_THREAD'))
            and name not in ('DSH_SESSION_ID', 'DSH_AGENT_SOURCE', 'DSH_AGENT_PACKAGE', 'VIRTUAL_ENV', 'PYTHONPATH')}
    kept['PATH'] = os.pathsep.join(item for item in kept.get('PATH', '').split(os.pathsep) if Path(item) != BIN)
    return kept


def run(label: str, *argv: str, stdin: str | None = None, limit: int = 300) -> subprocess.CompletedProcess:
    """Run one Runner or GraphTraj command from the project root and keep its output."""
    try:
        done = subprocess.run(argv, cwd=HARNESS, env=environment(), input=stdin, capture_output=True, text=True, timeout=limit)
    except subprocess.TimeoutExpired as expired:
        # What the command said so far, and exit 124, so the step can judge it and save its evidence.
        partial = [text.decode(errors='replace') if isinstance(text, bytes) else text or ''
                   for text in (expired.stdout, expired.stderr)]
        done = subprocess.CompletedProcess(argv, 124, *partial)
    (OUT / f'{label}.txt').write_text(f'$ {" ".join(argv)}\nexit {done.returncode}\n{done.stdout}\n--- stderr\n{done.stderr}')
    return done


def roles(runtimes: list[str]) -> dict:
    """Return role definitions for one member per Runtime; each role may reach none below it."""
    pi = {'sandbox_python': SANDBOX_PYTHON, 'sandbox_path': SANDBOX_PATH}
    definitions = {
        # GraphTraj takes only this exact model without a saved connection (runtimes/claude/adapter.py:191).
        'claude': {'runtime': 'claude', 'model': 'claude-opus-5-5', 'reasoning_effort': 'low'},
        'codex': {'runtime': 'codex', 'model': CODEX_MODEL, 'reasoning_effort': 'low'},
        'dsh': {'runtime': 'dsh', 'model': DEEPSEEK_MODEL, 'reasoning_effort': 'low'},
        'pi': {'runtime': 'pi', 'model': f'{PI_PROVIDER}/{DEEPSEEK_MODEL}', 'reasoning_effort': 'low', 'pi': pi},
    }
    return {'roles': {f'member_{name}': {**definitions[name], 'worktree_access': 'write', 'reports': ['report.md']}
                      for name in runtimes},
            'role_tree': {f'member_{name}': {} for name in runtimes}}


def prepare(runtimes: list[str]) -> None:
    """Create the project: a Git repository, `graphtraj setup`, roles and archiving on."""
    PROJECT.mkdir(parents=True)
    for argv in (['init', '-q', '-b', 'main', '.'], ['config', 'user.email', 'probe@example.invalid'],
                 ['config', 'user.name', 'probe']):
        subprocess.run(['git', *argv], cwd=PROJECT, check=True)
    (PROJECT / 'README.md').write_text('Scratch project for Task 392.\n')
    subprocess.run(['git', 'add', '.'], cwd=PROJECT, check=True)
    subprocess.run(['git', '-c', 'commit.gpgsign=false', 'commit', '-qm', 'init'], cwd=PROJECT, check=True)
    setup = run('setup', str(BIN / 'graphtraj'), 'setup', stdin='y\n')
    if setup.returncode != 0:
        raise RuntimeError(f'graphtraj setup failed: {setup.stderr[-300:]}')
    (HARNESS / '.graphtraj' / 'roles.yml').write_text(yaml.safe_dump(roles(runtimes)))
    swarm = HARNESS / '.graphtraj' / 'swarm'
    swarm.mkdir()
    (swarm / 'config.yml').write_text('save_normalized_sessions: true\n')
    (HARNESS / 'delivery-evidence.md').write_text('Main validated the current delivery fact.\n')
    doctor = run('doctor', str(BIN / 'graphtraj'), 'doctor')
    judge('roles: OK' in doctor.stdout, 'the scratch project\'s roles resolve (graphtraj doctor)', doctor.stdout.strip()[:200])


def budgeted(runtime: str, body: str) -> str:
    """Add the public execution budget, the one finite limit a Task can carry.

    It is not a hard limit: past the estimate and its allowance, each 2-minute check stops the Task at random
    (execution_budget.py:642-647), so the step still ends what is left, in stop_leftovers.
    """
    budget = {'difficulty': 'low', 'difficulty_reason': 'Scratch probe',
              'execution_budget': {'estimated_minutes': {'total': 20}, 'planned_sessions': {f'member_{runtime}': 1},
                                   'correction_rounds': 0, 'estimation_note': 'One scratch member of a real-host step',
                                   'on_exceed': 'Stop; the step records what it reached'}}
    return f'---\n{yaml.safe_dump(budget)}---\n{body}'


def ready(task_id: str, name: str, body: str, runtime: str) -> None:
    """Register one Task and move it to ready, as `graphtraj task graph` then shows it."""
    register = RUN / f'register-{task_id}.yml'
    register.write_text(yaml.safe_dump({
        'task_id': task_id, 'task_name': name, 'source': f'local:scratch/{task_id}', 'title': name, 'body': budgeted(runtime, body),
        'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active', 'replaced_by': [],
        'retirement_reason': None}))
    run(f'register-{task_id}', str(BIN / 'graphtraj'), 'task', 'register', '--task-file', str(register))
    state = RUN / f'state-{task_id}.yml'
    state.write_text(yaml.safe_dump({
        'task_id': task_id, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
        'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['delivery-evidence.md']}))
    run(f'ready-{task_id}', str(BIN / 'graphtraj'), 'task', 'update', '--state-file', str(state))


def dispatch(runtimes: list[str], tasks: dict[str, dict]) -> dict:
    """Start every member; return the dispatch document, with what it said on failure."""
    swarm = RUN / 'swarm.yml'
    swarm.write_text(yaml.safe_dump({'tasks': [
        {'task_id': task_id, 'role': f'member_{task["runtime"]}', 'instruction': task['instruction']}
        for task_id, task in tasks.items()]}, width=120))
    # With no host connection this call stays until its Workers exit (team_round.py:1275-1284, 1348):
    # the limit ends only this call, and a Worker it started goes on by itself.
    done = run('dispatch', str(BIN / 'agent-runner'), '--swarm-input', str(swarm), limit=600)
    if done.returncode == 124:
        check('FAIL', 'dispatch: agent-runner --swarm-input had not returned after 600 s, so a member was still '
                      'running; the saved records say what it was doing')
    try:
        return yaml.safe_load(done.stdout) or {}
    except yaml.YAMLError:
        return {}


def worldline() -> list[dict]:
    """Return the project's Worldline events."""
    events = []
    for path in sorted((STATE / 'worldline').glob('*.jsonl')):
        events += [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return events


def wait_for_results(tasks: dict[str, dict], document: dict) -> set[str]:
    """Wait for a result from each launched Task until the limit; return which arrived.

    A member whose execution has ended, or that never launched, can send nothing more.
    """
    deadline = time.monotonic() + LIMIT
    sessions = HARNESS / '.graphtraj' / 'runner' / 'sessions'
    waiting = {str(item.get('task_id')): item.get('alias') for item in document.get('tasks', [])
               if item.get('alias') and item.get('launch_status') != 'failed'}
    while True:
        seen = {str(event.get('task_id')) for event in worldline() if event.get('event') == 'result-submitted'}
        live = {task for task, alias in waiting.items()
                if task not in seen and not (sessions / alias / 'execution.yml').exists()}
        if not live or time.monotonic() > deadline:
            return seen & set(tasks)
        time.sleep(10)


def task_directory(task_id: str) -> Path | None:
    """Return one Task's state directory."""
    found = list((STATE / 'tasks').glob(f'{task_id}-*'))
    return found[0] if found else None


def report_of(task_id: str) -> str:
    """Return the member's report text, or nothing."""
    directory = task_directory(task_id)
    reports = sorted(directory.rglob('report*.md')) if directory else []
    return reports[-1].read_text(errors='replace') if reports else ''


def worktree_of(task_id: str, name: str) -> Path:
    """Return the Worktree the Runner gives this Task."""
    return HARNESS / '.graphtraj' / '.agent-worktrees' / f'{task_id}-{name}'


def value(text: str, name: str) -> str | None:
    """Read `NAME=value` from a report."""
    for line in text.splitlines():
        stripped = line.strip().strip('`*- ')
        if stripped.startswith(name + '='):
            return stripped.split('=', 1)[1].strip().strip('`')
    return None


def keep_state() -> None:
    """Copy the Task records, the member's Session logs and launch records."""
    keep_tree(STATE, OUT / 'state')
    keep_tree(HARNESS / '.graphtraj' / 'runner', OUT / 'runner')
    keep_tree(HARNESS / '.graphtraj' / 'swarm', OUT / 'swarm')


def own_processes() -> dict[int, tuple[int, str]]:
    """Return this run's processes, pid to (ppid, command): only those of this scratch project.

    One belongs if its working directory is in the project or its arguments name it, and so does everything
    under it. This process and its ancestors never do, so the step cannot stop itself.
    """
    table = {}
    for line in subprocess.run(['ps', '-axww', '-o', 'pid=,ppid=,command='], capture_output=True, text=True).stdout.splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit():
            table[int(fields[0])] = (int(fields[1]), fields[2])
    roots = (str(HARNESS), str(HARNESS.resolve()))
    names = re.compile('|'.join(re.escape(root) + r'''(?![^\s/'"])''' for root in roots))
    found = {pid for pid, (_, command) in table.items() if names.search(command)}
    listing = subprocess.run(['lsof', '-nP', '-a', '-d', 'cwd', '-u', str(os.getuid()), '-Fn'], capture_output=True, text=True).stdout
    current = None
    for line in listing.splitlines():
        if line.startswith('p') and line[1:].isdigit():
            current = int(line[1:])
        elif line.startswith('n') and current in table and any(line[1:] == root or line[1:].startswith(root + os.sep) for root in roots):
            found.add(current)
    while True:
        more = {pid for pid, (parent, _) in table.items() if parent in found} - found
        if not more:
            break
        found |= more
    pid = os.getpid()
    while pid in table:
        found.discard(pid)
        pid = table[pid][0]
    return {pid: table[pid] for pid in found}


def masked(text: str) -> str:
    """Hide any long token that follows key, token or =, as step 93 does."""
    return re.sub(r'(?i)((?:key|token|=)[^A-Za-z0-9_-]{0,3})[A-Za-z0-9_-]{20,}', r'\1[masked]', text)


def stop_leftovers() -> None:
    """End what this step's run left: the public stop for each open member, signals for what outlives it."""
    sessions = HARNESS / '.graphtraj' / 'runner' / 'sessions'
    aliases = sorted(path.name for path in sessions.iterdir() if path.is_dir() and not (path / 'execution.yml').exists()) if sessions.is_dir() else []
    record = [f'open members: {aliases}']
    for number, alias in enumerate(aliases, 1):
        done = run(f'stop-{number}', str(BIN / 'agent-runner'), 'interrupt', alias, limit=120)
        record.append(f'agent-runner interrupt {alias}: exit {done.returncode}, see stop-{number}.txt')
        note(f'stop of the member this step left, {alias}: exit {done.returncode}; see stop-{number}.txt')

    def settled(seconds: float) -> dict[int, tuple[int, str]]:
        """Wait for this run's processes to end; return those left."""
        deadline = time.monotonic() + seconds
        left = own_processes()
        while left and time.monotonic() < deadline:
            time.sleep(1)
            left = own_processes()
        return left

    left = settled(30)
    for name, number in (('SIGTERM', signal.SIGTERM), ('SIGKILL', signal.SIGKILL)):
        if not left:
            break
        record += [f'{name} {pid}, parent {parent}: {masked(command)[:300]}' for pid, (parent, command) in sorted(left.items())]
        for pid in left:
            try:
                os.kill(pid, number)
            except OSError as error:
                record.append(f'{name} {pid} failed: {error}')
        left = settled(10)
    record.append(f'left after the stop: {sorted(left)}')
    (OUT / 'leftover-stop.txt').write_text('\n'.join(record) + '\n')
    judge(not left, 'the step\'s own run left no process of its scratch project', f'see leftover-stop.txt; left {sorted(left)}')


def ends_its_run(function):
    """Stop what the step left, then keep its records, however the step's body ended."""
    @functools.wraps(function)
    def whole_step() -> None:
        try:
            function()
        finally:
            try:
                stop_leftovers()
            finally:
                keep_state()
    return whole_step


MEMBER_416 = (
    'Do these in order; if a step fails, write the exact error in the report and go on. '
    'Do not print environment variables. '
    'Creating a child with the agents tool is formal delegation through your own host and is what this Task '
    'asks of you; it is not starting a Runtime directly. '
    '1) Run pwd; call the result MEMBER_PWD. '
    '2) Use the agents tool: execute create with runtime {runtime} and no workspace argument, with this instruction: '
    '"Run pwd. Do not print environment variables. Append the word ok to the file child-work.txt in your working directory, and read it back. Then use the '
    'agents tool: execute create with runtime {runtime} and no workspace argument, with the instruction: Run pwd and reply '
    'with exactly GRANDCHILD_PWD=<its output>. Wait for it with the wait feature. Reply with exactly these lines: '
    'CHILD_PWD=<your pwd>, CHILD_WROTE=<yes or no>, and the GRANDCHILD_PWD line it gave, or GRANDCHILD_ERROR=<the error>." '
    '3) Wait for your child with the wait feature, timeout_seconds 300, again if it is still running. '
    '4) Write your assigned report report.md through the graphtraj submit_report tool, with these lines exactly: '
    'MEMBER_PWD=..., CHILD_PWD=..., CHILD_WROTE=..., GRANDCHILD_PWD=... or GRANDCHILD_ERROR=..., and CHILD_FILE=<yes if '
    'child-work.txt now exists in your working directory, else no>. '
    '5) Commit any changed file on your branch, then submit your task result through the graphtraj submit_result tool '
    'with the commit and a one-line completion. Do not search for workarounds.'
)


@ends_its_run
def r416() -> None:
    """416: a real member on each Runtime, no workspace: child and grandchild pwd, work under Worktree grants."""
    runtimes = ['claude', 'codex', 'dsh', 'pi']
    prepare(runtimes)
    tasks = {}
    for number, runtime in enumerate(runtimes, 1):
        name = f'probe-{runtime}'
        ready(str(number), name, f'Find where a child of a {runtime} member works.', runtime)
        tasks[str(number)] = {'runtime': runtime, 'name': name, 'instruction': MEMBER_416.format(runtime=runtime)}
    (OUT / 'graph.txt').write_text(run('graph', str(BIN / 'graphtraj'), 'task', 'graph').stdout)
    document = dispatch(runtimes, tasks)
    for item in document.get('tasks', []):
        status, error = item.get('launch_status'), item.get('error')
        note(f"dispatch {item.get('task_name')}: {status} {json.dumps(error, ensure_ascii=False)[:500] if error else ''}")
    arrived = wait_for_results(tasks, document)
    for task_id, task in tasks.items():
        runtime, report = task['runtime'], report_of(task_id)
        worktree = worktree_of(task_id, task['name'])
        (OUT / f'report-{runtime}.txt').write_text(report)
        member, child, grandchild = (value(report, key) for key in ('MEMBER_PWD', 'CHILD_PWD', 'GRANDCHILD_PWD'))
        expected = {str(worktree), str(worktree.resolve())}
        judge(task_id in arrived, f'416 {runtime}: the member submitted a result', f'report: {report[:200]!r}')
        judge(child in expected, f'416 {runtime}: a child with no workspace started in the member\'s Worktree',
              f'CHILD_PWD={child}, member {member}, Worktree {worktree}')
        if grandchild is None:
            check('FAIL', f'416 {runtime}: no grandchild pwd: GRANDCHILD_ERROR={value(report, "GRANDCHILD_ERROR")}')
        else:
            judge(grandchild in expected, f'416 {runtime}: the grandchild too', f'GRANDCHILD_PWD={grandchild}')
        judge(value(report, 'CHILD_WROTE') == 'yes' and (worktree / 'child-work.txt').exists(),
              f'416 {runtime}: the child finished work under Worktree-scoped permissions',
              f'CHILD_WROTE={value(report, "CHILD_WROTE")}, file exists {(worktree / "child-work.txt").exists()}')
    session_migration_check()


def session_migration_check() -> None:
    """416 For Main 4: does a member's own Claude Session read as belonging to another project?"""
    from graphtraj.workspace.session_migration import session_sources

    sources = session_sources(STATE, HARNESS / '.graphtraj' / 'runner', HARNESS)
    conflicts = [(item.get('runtime'), item.get('agent'), item.get('identity_conflicts')) for item in sources if item.get('identity_conflicts')]
    (OUT / 'session-sources.json').write_text(json.dumps(sources, indent=1, default=str, ensure_ascii=False))
    claude = [item for item in sources if item.get('runtime') == 'claude']
    note(f'416: session_sources found {len(sources)} Sessions, {len(claude)} on Claude')
    judge(not conflicts, '416: session_migration flags no member Session as another project\'s', conflicts[:4])
    for archive in (HARNESS / '.graphtraj' / 'swarm' / 'sessions').rglob('session.jsonl'):
        header = json.loads(archive.read_text().splitlines()[0])
        fields = (header.get('header') or header).get('extra_fields', {}).get('graphtraj', {})
        note(f"416: archive {archive.parent.name[:12]}: runtime {(header.get('header') or header).get('native', {}).get('runtime')}, "
             f"projectId {fields.get('projectId')}, agent {fields.get('agentId')}")
    note(f'416: the project root here is {PROJECT}; read the projectId values above against it')


def main_pi_child() -> None:
    """416 For Main 5: a scratch Main at this project's root creates a Pi child with no workspace.

    `agent-runner main` is GraphTraj's isolated Main turn on Codex, the one route that gives a verified
    native Main without a host plugin. It runs in the scratch project only. Native requests print to its
    stderr; the agents tool's own is accepted, any other declined, and each is written to the summary.
    """
    arguments = {'action': 'execute', 'feature': 'create',
                 # No model: step 90 named one the user's Pi login does not list, and create refused it first.
                 'arguments': {'runtime': 'pi', 'instruction': 'Run pwd and reply with it.'}}
    instruction = RUN / 'main-instruction.txt'
    instruction.write_text('Use the agents tool once, with exactly these arguments: ' + json.dumps(arguments) + '\n'
                           'Then reply with one line: the "code" and "message" of any error in the result, word for word, '
                           'or the words created and the agent name. Do nothing else.')
    process = subprocess.Popen([str(BIN / 'agent-runner'), 'main', '--instruction-file', str(instruction)], cwd=HARNESS,
                               env=environment(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    errors = []

    def answer() -> None:
        """Answer each native request by its id, as the command's own help says."""
        for line in process.stderr:
            errors.append(line)
            try:
                request = json.loads(line)
            except ValueError:
                continue
            if not isinstance(request, dict) or 'method' not in request:
                continue
            accept = request['method'] == 'mcpServer/elicitation/request' and 'agents' in line
            result = {'action': 'accept', 'content': {}} if accept else (
                {'action': 'decline'} if request['method'].startswith('mcpServer') else {'decision': 'decline'})
            note(f"416 Main native request {request['method']}: {json.dumps(result)}")
            process.stdin.write(json.dumps({'id': request['id'], 'result': result}) + '\n')
            process.stdin.flush()

    thread = threading.Thread(target=answer, daemon=True)
    thread.start()
    try:
        stdout = process.stdout.read() if process.wait(420) is not None else ''
    except subprocess.TimeoutExpired:
        process.kill()
        stdout = process.stdout.read()
    thread.join(5)
    text = stdout + ''.join(errors)
    (OUT / 'main-pi-child.txt').write_text(f'exit {process.returncode}\n--- stdout\n{stdout}\n--- stderr\n{"".join(errors)}')
    # Main keeps this refusal (Worldline 20261102T193403); 438 made its text say to assign a workspace.
    if 'RUNTIME_ACCESS_DENIED' in text:
        refusal = text[text.index('RUNTIME_ACCESS_DENIED'):][:400]
        judge('workspace' in refusal, '416: a Main at the project root is refused a Pi child, and the refusal says to '
              'assign a workspace', f'see main-pi-child.txt: {refusal}')
    elif 'created' in stdout:
        check('FAIL', f'416: a Main at the project root started a Pi child, but Main kept the refusal: {stdout[-300:]}')
    else:
        check('CANNOT', f'416: this Main turn did not reach Pi\'s preparation, exit {process.returncode}; see main-pi-child.txt: {stdout[:400] or text[-400:]}')


@ends_its_run
def r416_main() -> None:
    """Prepare a project with a Pi role and try 416's root-level Pi child in a scratch Main turn."""
    prepare(['pi'])
    main_pi_child()
    inline_role_refused()


def inline_role_refused() -> None:
    """439 item 2: a Batch with an inline role that writes base_url or pi.agent_dir is refused, naming connection:."""
    for number, (field, value) in enumerate((('base_url', {'base_url': 'https://example.invalid/v1'}),
                                             ('pi.agent_dir', {'pi': {'agent_dir': str(RUN / 'agent-dir')}})), 1):
        task_id = str(10 + number)
        ready(task_id, f'inline-{number}', 'Reply done.', 'pi')
        swarm = RUN / f'inline-{number}.yml'
        role = {'inline_probe': {'runtime': 'pi', 'model': f'{PI_PROVIDER}/{DEEPSEEK_MODEL}', **value}}
        swarm.write_text(yaml.safe_dump({'tasks': [{'task_id': task_id, 'role': role, 'instruction': 'Reply done.'}]}))
        done = run(f'inline-{number}', str(BIN / 'agent-runner'), '--swarm-input', str(swarm), limit=120)
        said = done.stdout + done.stderr
        judge(field in said and 'connection:' in said,
              f'439: an inline role writing {field} is refused, naming the field and connection:',
              f'exit {done.returncode}: {said.strip()[-300:]}')


MEMBER_437 = (
    'Do these in order; if a step fails, write the exact error in the report and go on. Do not print environment variables. '
    '1) In Bash run exactly: mkdir -p sub/deeper && cd sub/deeper && pwd. Stay in that directory for the next step. '
    '2) Use your Agent (Task) tool once: a subagent with the prompt "Reply with exactly: HELPER-OK". Keep its answer. '
    '3) In Bash run: cd back to your Worktree root. '
    '4) Write your assigned report report.md through the graphtraj submit_report tool with the line HELPER=<the answer>. '
    '5) Commit any changed file on your branch, then submit your task result through the graphtraj submit_result tool '
    'with the commit and a one-line completion. Do not search for workarounds.'
)


@ends_its_run
def r437_member() -> None:
    """437: a Claude member's native helper completes normally after a plain cd."""
    prepare(['claude'])
    ready('1', 'claude-cd', 'Run one helper after a cd and report its answer.', 'claude')
    tasks = {'1': {'runtime': 'claude', 'name': 'claude-cd', 'instruction': MEMBER_437}}
    document = dispatch(['claude'], tasks)
    items = document.get('tasks', [{}])
    judge(items[0].get('launch_status') not in ('failed', None), '437: dispatch started the Claude member',
          json.dumps(items[0], ensure_ascii=False)[:500])
    if items[0].get('launch_status') == 'failed':
        return
    arrived = wait_for_results(tasks, document)
    report = report_of('1')
    (OUT / 'report.txt').write_text(report)
    alias = items[0].get('alias') or ''
    execution = HARNESS / '.graphtraj' / 'runner' / 'sessions' / alias / 'execution.yml'
    record = yaml.safe_load(execution.read_text()) if alias and execution.exists() else {}
    text = json.dumps(record, ensure_ascii=False, default=str)
    judge('RUNTIME_WORKER_FAILED' not in text and 'Hook Session differs' not in text and '1' in arrived,
          '437: after a plain cd the member was not ended, and it submitted its result',
          f'outcome {record.get("outcome")}; {text[:300]}')
    judge(value(report, 'HELPER') == 'HELPER-OK', "437: the member's native helper completed and answered after the cd",
          f'HELPER={value(report, "HELPER")}')


MEMBER_420 = (
    'Do these in order. Do not print any environment variable other than PATH. '
    '1) Run: command -v agent-runner; command -v graphtraj-session; echo PATH=$PATH. Keep the output. '
    '2) Create probe.txt containing the word ok and commit it on your branch with git. '
    '3) Write your assigned report named report.md with one line saying what you did, followed by the output of step 1, '
    'using the graphtraj submit_report tool with notify_parent true. '
    '4) Submit your result with the graphtraj submit_result tool, giving the commit, result_refs [probe.txt] and a one-line '
    'completion. If a tool is unavailable or fails, say exactly which and what the error said, then stop. Do not search for workarounds.'
)


@ends_its_run
def r420() -> None:
    """420: one real DSH member round under the Runner, with the venv's bin off the host's PATH."""
    prepare(['dsh'])
    ready('1', 'dsh-member-probe', 'Create probe.txt containing the word ok, commit it on your branch, write your assigned report, then submit your task result.', 'dsh')
    from shutil import which
    path = environment()['PATH']
    note(f"420: dsh --version: {subprocess.run(['dsh', '--version'], env=environment(), capture_output=True, text=True).stdout.strip()}")
    note(f'420: on the host PATH: graphtraj-session {which("graphtraj-session", path=path)}, dsh {which("dsh", path=path)}, '
         f'agent-runner {which("agent-runner", path=path)}; beside the Python: {(BIN / "graphtraj-session").exists()}. '
         'This answers which tool the host lacked at 417: the graphtraj-session line')
    tasks = {'1': {'runtime': 'dsh', 'name': 'dsh-member-probe', 'instruction': MEMBER_420}}
    document = dispatch(['dsh'], tasks)
    items = document.get('tasks', [{}])
    judge(items[0].get('launch_status') not in ('failed', None), '420: dispatch started the member',
          json.dumps(items[0], ensure_ascii=False)[:500])
    if items[0].get('launch_status') == 'failed':
        return
    arrived = wait_for_results(tasks, document)
    report = report_of('1')
    (OUT / 'report.txt').write_text(report)
    judge('1' in arrived, '420: a real DSH member submitted its result', f'report: {report[:300]!r}')
    worktree = worktree_of('1', 'dsh-member-probe')
    judge((worktree / 'probe.txt').exists(), '420: the member committed its file', f'{worktree}/probe.txt')
    launch = list((HARNESS / '.graphtraj' / 'runner').rglob('launch.yml'))
    note(f'420: launch record: {launch[0].read_text()[:400] if launch else "none"}')
    logs = [path for path in HARNESS.rglob('*.log') if path.is_file()] + [path for path in HARNESS.rglob('*.jsonl') if 'dsh' in str(path).lower() and path.is_file()]
    emfile = sum(path.read_text(errors='replace').count('EMFILE') for path in logs if path.stat().st_size < 50_000_000)
    note(f'420: EMFILE mentions across {len(logs)} DSH logs: {emfile}; open-file limit in this shell: '
         f'{subprocess.run("ulimit -n", shell=True, capture_output=True, text=True).stdout.strip()}')
    fallback = value(report, 'agent-runner') or ('agent-runner' in report)
    note(f'420: team_round.py:1086 names agent-runner as a fallback; the member\'s `command -v agent-runner` output is in report.txt ({fallback})')


if __name__ == '__main__':
    globals()[sys.argv[1]]()
