"""466 probe helper: roles, probe Tasks, two Runner-launched Claude members, and the session_read CHECKs.

Usage (the scratch venv's Python, -I, from the isolated project):
  python -I probe.py fix SRC -               whether the venv imports SRC and it has the 466 change
  python -I probe.py prepare PROJECT MODEL   roles (team_leader claude, permission_mode auto); Tasks 1 and 2 ready
  python -I probe.py isolation PROJECT -     project root, git top level, CLAUDE.md upward
  python -I probe.py init STREAM HARNESS     the init record (model, apiKeySource name, plugins) and the
                                             instruction files the host says it was given
  python -I probe.py run PROJECT FACTS       FACTS (JSON, written by steps.zsh): task, label, out. Dispatches one
                                             member with agent-runner unless the Task has one, waits <= 9 min, checks
  python -I probe.py collect PROJECT FACTS   the same checks for the Task's existing member; dispatches nothing
Task 1's member writes a conversation long enough to page (a marker early, a fake credential late). Task 2's
member reads Task 1's member Session with agents session_read three times: default, one page back, one search.
Signals nothing. Prints no key: the only credential-shaped value is the fake FAKE_CREDENTIAL planted by Task 1.
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

TASKS = {'1': 'session-read-probe-source', '2': 'session-read-probe-reader'}
KEYWORD = 'KW466-ORCHID'
FAKE_CREDENTIAL = 'sk-probe466fakevalue0000'
STEPS = 12
BODY = '''---
difficulty: low
difficulty_reason: Scratch probe for 466
execution_budget:
  estimated_minutes:
    total: 30
  planned_sessions:
    team_leader: 1
  correction_rounds: 0
  estimation_note: One Claude member per Task; the second reads the first one's Session
  on_exceed: Report only
---
Follow the dispatch instruction exactly.
'''
RESULT = re.compile(r'RESULT-466 a=(\S+) b=(\S+) c=(\S+) memory=(.*)')
# What Claude Code puts in place of a tool result that is over its limit or cut.
OVER_LIMIT = re.compile(r'(?i)exceeds maximum|too large|tool-results/|truncat|saved to|maximum allowed tokens')
TOOL = 'mcp__agents__agents'


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def run(*argv: str, **kwargs) -> subprocess.CompletedProcess:
    done = subprocess.run(argv, capture_output=True, text=True, timeout=540, **kwargs)
    print(f'$ {" ".join(Path(a).name if i == 0 else a for i, a in enumerate(argv[-4:]))} -> rc={done.returncode}')
    if done.returncode:
        print(done.stdout[-600:], done.stderr[-600:])
    return done


def fix(source: Path, _unused: str) -> int:
    """The venv imports the commit under test and it has agents session_read."""
    import inspect

    import graftling
    import graphtraj.sessions.query as query
    from graftling.sessions import read_events

    files = [Path(module.__file__).resolve() for module in (graftling, query)]
    inside = all(source.resolve() in path.parents for path in files)
    loaded = ('session_read' in graftling.ACTION_FIELDS and 'read_events(' in inspect.getsource(query.read_session)
              and Path(inspect.getfile(read_events)).resolve().is_relative_to(source.resolve()))
    print('imports:', ', '.join(map(str, files)), '| under', source, ':', inside)
    print('466 fix loaded:', 'YES' if inside and loaded else 'NO')
    return 0 if inside and loaded else 1


def prepare(project: Path, model: str) -> int:
    bin_dir = Path(sys.executable).parent
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'team_leader': {'runtime': 'claude', 'model': model, 'worktree_access': 'write',
                                  'reports': ['report.md'], 'claude': {'permission_mode': 'auto'}}},
        'role_tree': {'team_leader': {}},
    }))
    work = project / '.graphtraj/probe-466'
    work.mkdir(exist_ok=True)
    rc = 0
    for task_id, name in TASKS.items():
        register = work / f'register-{task_id}.yml'
        register.write_text(yaml.safe_dump({
            'task_id': task_id, 'task_name': name, 'source': 'local:scratch/466', 'title': name, 'body': BODY,
            'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
            'replaced_by': [], 'retirement_reason': None}))
        state = work / f'state-{task_id}.yml'
        state.write_text(yaml.safe_dump({
            'task_id': task_id, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
            'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-466/evidence.md']}))
        if not list(project.glob(f'.graphtraj/state/tasks/{task_id}-*/task.yml')):
            rc = rc or run(str(bin_dir / 'graphtraj'), 'task', 'register', '--task-file', str(register), cwd=project).returncode
        (work / 'evidence.md').write_text('466 probe: ready for one Claude member per Task.\n')
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
    leaked = [word for word in re.split(r'[\s,]+', text) if word.startswith(harness) and '/tmp/466/' not in word]
    print('instruction files from the Harness:', leaked or 'none')
    if plugins is None:
        print('init: none in the stream')
    return 0 if plugins is not None and model_ok and not leaked else 1


def instruction(task: str, facts: dict) -> str:
    if task == '1':
        # The marker and the fake value are assembled by the member, so only its own text holds them.
        marker, value = KEYWORD.split('-'), (FAKE_CREDENTIAL[:11], FAKE_CREDENTIAL[11:])
        steps = []
        for number in range(2, STEPS + 2):
            sentence = f'"Now step {number:02d}."'
            if number == 3:
                sentence += (f' followed by the sentence "Marker X reached." where X is {marker[0]}, a hyphen and '
                             f'{marker[1]} with no spaces')
            if number == STEPS:
                sentence += (' followed by the sentence "Fake credential for a redaction check: api_key=V" where V '
                             f'is {value[0]} immediately followed by {value[1]} (a made-up value, not a secret)')
            steps.append(f'Step {number:02d}: write {sentence}, then call the Bash tool with exactly '
                         f'`echo 466-step-{number:02d}`.')
        return ' '.join([
            'This is a scripted probe; do exactly these steps in order and nothing else. Write each step\'s '
            'sentences as their own short text before that step\'s tool call. Use only the Bash tool.',
            'Step 01: write "Starting the 466 probe."', *steps,
            'Finally reply with exactly: DONE-466-T1'])
    return ' '.join([
        f'Use only the {TOOL} tool, exactly three calls in this order, each with action "execute" and feature '
        '"session_read". Use no other tool and do not repeat a call.',
        f'Call A arguments: {{"agent": "{facts["source_alias"]}"}}.',
        f'Call B arguments: {{"session": "{facts["source_native"]}", "start": -10, "stop": -5}}.',
        f'Call C arguments: {{"session": "{facts["source_native"]}", "search": "{KEYWORD}"}}.',
        'From A note result.start, result.stop and result.total; from B result.start and result.stop; from C '
        'result.hits_total and the index of the first hit. Write ERROR for a call that failed.',
        'Then reply with exactly one line: RESULT-466 a=<start>:<stop>/<total> b=<start>:<stop> '
        'c=<hits_total>@<index> memory=<the absolute paths of every CLAUDE.md or AGENTS.md file whose contents '
        'you were given as instructions, comma-separated, or NONE>',
    ])


def member_aliases(runner: Path, task: str) -> list[str]:
    return sorted(path.name for path in (runner / 'sessions').glob(f'{task}-*team_leader*') if path.is_dir())


def check_version() -> str:
    from graphtraj.runtimes.claude.adapter import current_cli

    binary, version = current_cli()
    print(f'member Claude Code (Runner resolves claude on PATH): {binary} | {version}')
    return version


def run_member(project: Path, facts_file: str) -> int:
    """Dispatch one member for facts['task'], then collect it; refuses when the Task already has one."""
    from graphtraj.configuration.project_configuration import runner_directory

    facts = json.loads(Path(facts_file).read_text())
    existing = member_aliases(runner_directory(project), facts['task'])
    if existing:
        print(f"STOP: Task {facts['task']} already has a member {existing}; nothing was dispatched. "
              'Use the collect-only step for it.')
        return 2
    check_version()
    batch = Path(facts_file).with_suffix('.swarm.yml')
    batch.write_text(yaml.safe_dump({'tasks': [{'task_id': facts['task'], 'role': 'team_leader',
                                                'instruction': instruction(facts['task'], facts)}]}))
    done = run(str(Path(sys.executable).parent / 'agent-runner'), '--swarm-input', str(batch), cwd=project)
    Path(facts_file).with_suffix('.dispatch.yml').write_text(done.stdout)
    if done.returncode:
        return 1
    task = yaml.safe_load(done.stdout)['tasks'][0]
    print(f"{now()} agent-runner returned: alias={task.get('alias')} execution_id={task.get('execution_id')} "
          f"session={task.get('session')}")
    return settle_and_check(project, facts, task)


def collect(project: Path, facts_file: str) -> int:
    """Collect-only for the Task's existing member; dispatches nothing."""
    from graphtraj.configuration.project_configuration import runner_directory

    facts = json.loads(Path(facts_file).read_text())
    dispatch = Path(facts_file).with_suffix('.dispatch.yml')
    if dispatch.is_file() and dispatch.read_text().strip():
        task = yaml.safe_load(dispatch.read_text())['tasks'][0]
    else:
        aliases = member_aliases(runner_directory(project), facts['task'])
        if len(aliases) != 1:
            print(f"STOP: Task {facts['task']} has members {aliases}; expected exactly one.")
            return 1
        task = {'alias': aliases[0]}
    print(f"collecting alias={task.get('alias')} execution_id={task.get('execution_id')} session={task.get('session')}")
    check_version()
    return settle_and_check(project, facts, task)


def settle_and_check(project: Path, facts: dict, task: dict) -> int:
    from graphtraj.configuration.project_configuration import runner_directory
    from graphtraj.execution.runner_status import status_aliases

    runner = runner_directory(project)
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
        print(f'STOP: {alias} still running after 9 min: activity={value.get("activity")}. Run the collect-only step later.')
        return 1
    mapping = yaml.safe_load(mapping_file.read_text()) or {}
    native = mapping.get('session')
    print(f'{now()} settled: activity={value.get("activity")} last_outcome={value.get("last_outcome")}')
    print(f"identity: dispatched execution_id={task.get('execution_id')} session={task.get('session')} | "
          f"mapping execution_id={mapping.get('execution_id')} session={native}")
    if task.get('execution_id') is not None and task['execution_id'] != mapping.get('execution_id'):
        print('STOP: mapping.yml names another execution than the dispatch; nothing was checked.')
        return 1
    checks = (source_checks if facts['task'] == '1' else reader_checks)(project, facts, alias, native)
    for number, (label, ok) in enumerate(checks, 1):
        print(f'CHECK {number} {"PASS" if ok else "FAIL"}: {label}')
    out = {'alias': alias, 'native': native, 'execution_id': mapping.get('execution_id'),
           'checks': {label: ok for label, ok in checks}}
    Path(facts['out']).write_text(json.dumps(out, indent=2))
    summary = all(ok for _, ok in checks)
    print('== summary:', 'ALL PASS' if summary else f'{sum(not ok for _, ok in checks)} FAIL of {len(checks)}')
    return 0 if summary else 1


def owner_read(project: Path, native: str, **arguments) -> dict:
    """Read an archived Session as its owner (the probe), with the library agents uses."""
    from graftling.sessions import find_session, read_events
    from graphtraj.interfaces.agents import swarm_root

    store = find_session(swarm_root(project), native)
    if store is None:
        raise SystemExit(f'STOP: no archived Session {native} in {swarm_root(project)}')
    return read_events(store, redacted=False, **arguments)


def source_checks(project: Path, facts: dict, alias: str, native: str) -> list[tuple[str, bool]]:
    """Task 1's Session: long enough to page, the marker before the last page, the fake credential archived."""
    text = owner_read(project, native, start=0)
    tools = owner_read(project, native, start=0, content='tools')
    everything = owner_read(project, native, start=0, content='all')
    hits = owner_read(project, native, search=KEYWORD)
    calls = sum(block.get('type') == 'tool-call' for item in tools['events'] for block in item['content'])
    print(f"Task 1 Session claude:{native}: text events {text['total']}, with tools {tools['total']} "
          f"({calls} tool calls), all archived events {everything['total']}")
    index = hits['hits'][0]['index'] if hits['hits'] else None
    print(f'marker {KEYWORD}: hits {hits["hits_total"]}, first index {index} (the default page starts at '
          f'{max(0, text["total"] - 5)})')
    replies = [item['text'] for item in text['events'] if item['type'] == 'assistant/message']
    return [
        ('Task 1 member wrote at least 12 text events and 10 tool calls', text['total'] >= 12 and calls >= 10),
        (f'marker {KEYWORD} (written by the member, not in its prompt) lies before the last 5 text events',
         index is not None and index < text['total'] - 5),
        ('the member wrote the fake credential (so the redaction check is meaningful)',
         any(FAKE_CREDENTIAL in reply for reply in replies)),
        ('the member replied DONE-466-T1', any('DONE-466-T1' in reply for reply in replies)),
    ]


def tool_calls(project: Path, native: str) -> list[tuple[dict, dict | None]]:
    """Each agents tool call of a Claude member with its tool result, from its archived transcript."""
    events = owner_read(project, native, start=0, content='all')['events']
    calls, results = [], {}
    for item in events:
        event = item['event']
        if event.get('type') not in ('user/message', 'assistant/message'):
            continue
        message = event['data'] if event['type'] == 'user/message' else event['data'].get('message', {})
        for block in message.get('content', []) if isinstance(message.get('content'), list) else []:
            if block.get('type') == 'tool-call' and block.get('name') == TOOL:
                calls.append(block)
            elif block.get('type') == 'tool_result':
                results[block.get('tool_use_id')] = block
    return [(call, results.get(call.get('id'))) for call in calls]


def result_text(block: dict | None) -> str:
    content = (block or {}).get('content')
    if isinstance(content, str):
        return content
    return '\n'.join(part.get('text', '') for part in content or [] if isinstance(part, dict))


def reader_checks(project: Path, facts: dict, alias: str, native: str) -> list[tuple[str, bool]]:
    """Task 2's own transcript: three agents session_read calls, each complete and within the output limit."""
    source = facts['source_native']
    expected = owner_read(project, source, start=0)
    total = expected['total']
    keyword = owner_read(project, source, search=KEYWORD)
    first_hit = keyword['hits'][0]['index'] if keyword['hits'] else None
    pairs = tool_calls(project, native)
    print(f'Task 2 Session claude:{native}: {len(pairs)} {TOOL} call(s); Task 1 text events now {total}')
    documents, checks = [], []
    for label, (call, result) in zip('ABC', pairs):
        text = result_text(result)
        try:
            document = json.loads(text)
        except ValueError:
            document = None
        arguments = (call.get('input') or {}).get('arguments')
        found = (document or {}).get('result') or {}
        positions = {key: found.get(key) for key in ('start', 'stop', 'total', 'hits_total')}
        indices = [item.get('index') for item in found.get('events', [])] or [h.get('index') for h in found.get('hits', [])]
        print(f'call {label}: arguments {json.dumps(arguments)} | tool_result {len(text)} characters | '
              f'is_error {bool((result or {}).get("is_error"))} | over-limit notice '
              f'{bool(OVER_LIMIT.search(text)) if document is None else False} | complete JSON {document is not None} | '
              f'positions {positions} | indices {indices}')
        documents.append((label, call, result, text, document, indices))
    by_label = {label: (document, indices) for label, _, _, _, document, indices in documents}
    for label, call, result, text, document, _ in documents:
        checks.append((f'call {label}: tool_result present, not is_error, no over-limit notice, complete JSON '
                       f'({len(text)} characters)',
                       result is not None and not result.get('is_error') and document is not None
                       and 'error' not in document))
    a, b, c = (by_label.get(label, (None, None)) for label in 'ABC')
    checks += [
        ('exactly three agents session_read calls, in the order A, B, C', len(pairs) == 3),
        ('A default read returned the last 5 text events: indices == list(range(total))[-5:]',
         a[0] is not None and a[1] == list(range(total))[-5:] and a[0]['result']['total'] == total),
        ('B one page back returned list(range(total))[-10:-5]', b[0] is not None and b[1] == list(range(total))[-10:-5]),
        (f'C search for {KEYWORD} returned hit index {first_hit} (the probe\'s own read)',
         c[0] is not None and first_hit is not None and c[1][:1] == [first_hit]),
        ('A shows the fake credential redacted ([redacted] present, the value absent)',
         a[0] is not None and '[redacted]' in json.dumps(a[0]) and FAKE_CREDENTIAL not in json.dumps(a[0])),
    ]
    raw = json.dumps(owner_read(project, native, start=0, content='all'), ensure_ascii=False)
    checks.append(('no credential value anywhere in Task 2\'s transcript (fake value, sk-ant-, Bearer tokens)',
                   FAKE_CREDENTIAL not in raw and 'sk-ant-' not in raw
                   and not re.search(r'Bearer (?!\[redacted\])\S{12,}', raw)))
    replies = [item['text'] for item in owner_read(project, native, start=0)['events']
               if item['type'] == 'assistant/message']
    lines = [match for reply in replies for match in RESULT.finditer(reply)]
    line = lines[-1] if lines else None
    print('RESULT line:', line.group(0) if line else 'none')
    if line:
        memory = line.group(4).strip()
        print('member-reported instruction files:', memory)
        checks.append(('the member reports no Harness CLAUDE.md/AGENTS.md among its instructions',
                       memory.upper().startswith('NONE') or '/tmp/466/' in memory))
    else:
        checks.append(('the member replied with a RESULT-466 line', False))
    return checks


if __name__ == '__main__':
    command, target, extra = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    commands = {'fix': fix, 'prepare': prepare, 'isolation': isolation, 'init': init,
                'run': run_member, 'collect': collect}
    raise SystemExit(commands[command](target, extra))
