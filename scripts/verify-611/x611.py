"""Task 611 real-host helper, run by steps.zsh. Names only: no key value is ever read into output.

    python3 -I x611.py selfenv                             credential-class variable NAMES this process sees
    <venv python> -I x611.py catalog <out> <dsh home>      the isolated catalog document (two DSH providers)
    <venv python> -I x611.py prepare <project>             roles (probe_team.opencode / .deepseek) + Tasks 1, 2 ready
    <venv python> -I x611.py batch <task>                  ONE swarm batch: one member of Task 1 or 2
    <venv python> -I x611.py listing <yaml> <provider> <model> <key name>   verdicts on one discover output
    <venv python> -I x611.py pids <runner sessions dir> <task>   runtime_pid values recorded for that Task's members
    python3 -I x611.py envnames <out file>                 stdin: `ps -E -ww -o command= -p <pid>`; writes NAMES only
    <venv python> -I x611.py ended <runner sessions dir> <task> <seconds>   waits until that member's execution ended
    <venv python> -I x611.py judge <runner sessions dir> <task> <provider> <model> <env dir> <credential> <word>
        the member's launch request, outcome, native DSH trace (provider, model pairs and the reply word) and the
        credential-class variable names sampled from its DSH process, which must be exactly <credential>.

Every verdict line starts PASS or FAIL; the exit status is 0 only when every line is PASS (2: could not observe).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

FAILED = []
# graftling child_env.is_credential_name, restated: a '_'-separated part ending in a marker.
PART = re.compile(r'(?:KEY|TOKEN|SECRET|SECRETS|PASSWORD|CREDENTIAL|CREDENTIALS)$')
OPENCODE, DEEPSEEK = 'OPENCODE_API_KEY', 'DEEPSEEK_API_KEY'
RUNTIME = 'dsh-611'
ROLES = {'1': ('probe_team.opencode', 'opencode-go', 'glm', 'READY-611-OPENCODE'),
         '2': ('probe_team.deepseek', 'deepseek-official', 'flash', 'READY-611-DEEPSEEK')}
NAMES = {'1': 'opencode-probe', '2': 'deepseek-probe'}
BODY = '''---
difficulty: low
difficulty_reason: 611 real-host probe
execution_budget:
  estimated_minutes:
    total: 10
  estimation_note: one one-line member turn
  planned_sessions:
    engineer: 1
  correction_rounds: 0
  on_exceed: Notify the caller
---
# 611 probe

One DSH member replies with one line and ends its turn.
'''
INSTRUCTION = ('This is a scripted GraphTraj probe. Change no file, run no command, call no tool and dispatch '
               'nobody. Reply with exactly one line, {0}, and end your turn.')


def credential(name: str) -> bool:
    upper = name.upper()
    return not re.fullmatch(r'GIT_CONFIG_KEY_[0-9]+', upper) and any(PART.search(p) for p in upper.split('_'))


def check(ok: bool, message: str) -> None:
    print(('PASS: ' if ok else 'FAIL: ') + message)
    if not ok:
        FAILED.append(message)


def read_yaml(path: Path) -> dict:
    import yaml

    try:
        found = yaml.safe_load(path.read_text())
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def values(node, key: str):
    """Every value of ``key`` anywhere in a JSON/YAML document."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key and not isinstance(v, (dict, list)):
                yield v
            yield from values(v, key)
    elif isinstance(node, list):
        for v in node:
            yield from values(v, key)


def pairs(node):
    """Every (provider, model) named together in one JSON object."""
    if isinstance(node, dict):
        if isinstance(node.get('provider'), str) and isinstance(node.get('model'), str):
            yield node['provider'], node['model']
        for v in node.values():
            yield from pairs(v)
    elif isinstance(node, list):
        for v in node:
            yield from pairs(v)


def catalog(out: str, dsh_home: str) -> int:
    """Write the isolated catalog: opencode-go keyed by OPENCODE_API_KEY, deepseek-official by DEEPSEEK_API_KEY."""
    import yaml

    document = {'version': 1, 'runtimes': {RUNTIME: {'runtime': 'dsh', 'home': dsh_home, 'providers': {
        'opencode-go': {'api_key_env': OPENCODE, 'models': {'glm': {'id': 'glm-5.3', 'source': 'native'}}},
        'deepseek-official': {'api_key_env': DEEPSEEK,
                              'models': {'flash': {'id': 'deepseek-flash', 'source': 'native'}}},
    }}}}
    Path(out).write_text(yaml.safe_dump(document, sort_keys=False))
    print(f'catalog draft {out}: runtime entry {RUNTIME} (dsh, home {dsh_home}); providers opencode-go '
          f'(api_key_env {OPENCODE}, model glm-5.3) and deepseek-official (api_key_env {DEEPSEEK}, model deepseek-flash)')
    return 0


def run(*argv: str, cwd: Path) -> subprocess.CompletedProcess:
    done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    if done.returncode:
        print('command failed:', ' '.join(argv), '\n', (done.stdout + done.stderr)[-800:])
    return done


def tool(name: str) -> str:
    return str(Path(sys.executable).parent / name)


def prepare(project: str) -> int:
    """Write the two probe roles (catalog connections) and register Tasks 1 and 2 as ready."""
    import yaml
    from graphtraj.configuration.project_configuration import load_project_configuration
    from graphtraj.configuration.project_roles import roles_file

    root = Path(project)
    roles = {'probe_team': {}}
    for role, provider, model, _ in ROLES.values():
        roles['probe_team'][role.split('.')[1]] = {'connection': f'{RUNTIME}/{provider}/{model}'}
    path = roles_file(root)
    path.write_text(yaml.safe_dump({'roles': roles, 'role_tree': {role: {} for role, *_ in ROLES.values()}},
                                   sort_keys=False))
    print(f'roles file {path}:')
    print(path.read_text(), end='')
    work = root / '.graphtraj/probe-611'
    work.mkdir(exist_ok=True)
    (work / 'evidence.md').write_text('611 probe: ready.\n')
    rc = 0
    for task, name in NAMES.items():
        register, ready = work / f'register-{task}.yml', work / f'ready-{task}.yml'
        register.write_text(yaml.safe_dump({
            'task_id': task, 'task_name': name, 'source': f'local:scratch/611-{task}', 'title': name, 'body': BODY,
            'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active', 'replaced_by': [],
            'retirement_reason': None}))
        ready.write_text(yaml.safe_dump({
            'task_id': task, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
            'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-611/evidence.md']}))
        rc |= run(tool('graphtraj'), 'task', 'register', '--task-file', str(register), cwd=root).returncode
        rc |= run(tool('graphtraj'), 'task', 'update', '--state-file', str(ready), cwd=root).returncode
    doctor = run(tool('graphtraj'), 'doctor', cwd=root)
    roles_ok = 'roles: OK' in doctor.stdout
    check(roles_ok, 'graphtraj doctor: roles: OK' + ('' if roles_ok else ' -- ' + (doctor.stdout + doctor.stderr)[-600:]))
    state = load_project_configuration(root).state
    for task, name in NAMES.items():
        status = read_yaml(state / 'tasks' / f'{task}-{name}' / 'task.yml').get('status')
        check(status == 'ready', f'Task {task} ({name}) registered and ready: {status}')
    check(rc == 0, 'task register and update exited 0')
    return 1 if FAILED else 0


def batch(task: str) -> int:
    import yaml

    role, *_, word = ROLES[task]
    print(yaml.safe_dump({'tasks': [{'task_id': task, 'task_name': NAMES[task], 'role': role,
                                     'instruction': INSTRUCTION.format(word)}]}, sort_keys=False, width=100000), end='')
    return 0


def listing(path: str, provider: str, model: str, key: str) -> int:
    """Verdicts on one `graphtraj connections --action discover --provider` output."""
    import yaml

    text = Path(path).read_text()
    found = (yaml.safe_load(text) or {}).get('discovery') or {}
    groups = found.get('groups') or []
    print(f'discovery: runtime_entry {found.get("runtime_entry")}, provider {found.get("provider")}, status '
          f'{found.get("status")}, provider_status {found.get("provider_status")}, message {found.get("message")!r}')
    for group in groups:
        ids = [m.get('id') for m in group.get('models') or []]
        print(f'  group {group.get("provider")}: {len(ids)} models: {" ".join(map(str, ids))}')
    check(found.get('status') == 'available', f'{provider}: status available')
    check([g.get('provider') for g in groups] == [provider], f'{provider}: the models are grouped under {provider} only')
    check(any(m.get('id') == model for g in groups for m in g.get('models') or []), f'{provider} lists {model}')
    check(all(m.get('provider') == provider for m in found.get('models') or []),
          f'{provider}: every listed model carries provider {provider}')
    value = os.environ.get(key) or ''
    check(bool(value) and value not in text, f'the discovery output does not contain the {key} value')
    print(f'listing: {"ALL PASS" if not FAILED else f"{len(FAILED)} FAIL"}')
    return 1 if FAILED else 0


def members(sessions: str, task: str) -> list[Path]:
    root = Path(sessions)
    return sorted(p for p in root.glob(f'{task}-*') if p.is_dir()) if root.is_dir() else []


def pids(sessions: str, task: str) -> int:
    found = set()
    for directory in members(sessions, task):
        for record in directory.glob('*.y*ml'):
            found |= {v for v in values(read_yaml(record), 'runtime_pid') if isinstance(v, int) and v > 0}
    print('\n'.join(map(str, sorted(found))))
    return 0


def envnames(out: str) -> int:
    text = sys.stdin.read()
    names = sorted(set(re.findall(r'(?:^|\s)([A-Za-z_][A-Za-z0-9_]*)=', text)))
    Path(out).write_text('\n'.join(names) + '\n')
    print(f'{len(names)} names; credential-class: {[n for n in names if credential(n)]}')
    return 0


def ended(sessions: str, task: str, seconds: str) -> int:
    deadline = time.time() + float(seconds)
    while True:
        for directory in members(sessions, task):
            current = read_yaml(directory / 'mapping.yml').get('execution_id')
            terminal = read_yaml(directory / 'execution.yml')
            if terminal and (current is None or terminal.get('execution_id') == current):
                print(f'{directory.name}: execution ended, outcome {terminal.get("outcome")}')
                return 0
        if time.time() >= deadline:
            break
        time.sleep(2)
    print(f'Task {task}: no member execution ended within {seconds} s ({[p.name for p in members(sessions, task)]})')
    return 2


def judge(sessions: str, task: str, provider: str, model: str, envdir: str, expected: str, word: str) -> int:
    found = members(sessions, task)
    check(len(found) == 1, f'one member Session of Task {task}: {[p.name for p in found]}')
    for directory in found:
        launch, mapping, terminal = (read_yaml(directory / name) for name in ('launch.yml', 'mapping.yml', 'execution.yml'))
        request = next(iter(values_of(launch, 'adapter_request')), {})
        print(f'{directory.name}: launch request provider {request.get("provider")!r}, model {request.get("model")!r}, '
              f'api_key_env {request.get("api_key_env")!r}, connection {request.get("connection")!r}, '
              f'runtime_home {request.get("runtime_home")!r}')
        check(request.get('provider') == provider and request.get('model') == model,
              f'the member was launched on {provider}/{model}')
        check(request.get('api_key_env') == expected, f'its launch names only {expected} as its key variable')
        error = terminal.get('error') or {}
        check(terminal.get('outcome') == 'completed',
              f'its execution completed: outcome {terminal.get("outcome")}, error {error.get("code")}: '
              f'{str(error.get("message"))[:300]!r}')
        trace = Path(mapping.get('trace_file') or directory / 'missing-trace')
        seen, named, text = set(), {'provider': set(), 'model': set()}, ''
        if trace.is_file():
            for raw in trace.read_text(errors='replace').splitlines():
                text += raw
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                seen |= set(pairs(event))
                for key in named:
                    named[key] |= {v for v in values(event, key) if isinstance(v, str)}
        print(f'native DSH trace {trace}: provider values {sorted(named["provider"])}; model values '
              f'{sorted(named["model"])}; (provider, model) pairs {sorted(seen)}')
        check((provider, model) in seen, f'the native DSH trace names provider {provider!r} with model {model!r}')
        check(not [p for p in seen if p[0] != provider], 'the native DSH trace names no other provider')
        check(word in text, f'the member replied {word} (native DSH trace)')
        print(f'follow-up (paste): cat {directory / "execution.yml"}; python3 -m json.tool --json-lines {trace} | less')
    samples = sorted(Path(envdir).glob('env-*.txt'))
    print(f'environment samples of the member DSH process (names only): {[s.name for s in samples]}')
    check(bool(samples), f'the member DSH process environment was sampled (see {envdir}/sampler.log if not)')
    for sample in samples:
        names = sample.read_text().split()
        held = sorted(n for n in names if credential(n))
        print(f'  {sample.name}: {len(names)} names; credential-class: {held}')
        check(held == [expected], f'{sample.name}: the only credential-class variable is {expected}')
    print(f'judge: {"ALL PASS" if not FAILED else f"{len(FAILED)} FAIL"}')
    return 1 if FAILED else 0


def values_of(node, key: str):
    """Every mapping value of ``key`` anywhere in a document."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key and isinstance(v, dict):
                yield v
            yield from values_of(v, key)
    elif isinstance(node, list):
        for v in node:
            yield from values_of(v, key)


def main(argv: list[str]) -> int:
    actions = {'catalog': (catalog, 2), 'prepare': (prepare, 1), 'batch': (batch, 1), 'listing': (listing, 4),
               'pids': (pids, 2), 'envnames': (envnames, 1), 'ended': (ended, 3), 'judge': (judge, 7)}
    if argv[:1] == ['selfenv'] and len(argv) == 1:
        print(' '.join(sorted(n for n in os.environ if credential(n))) or 'none')
        return 0
    if argv and argv[0] in actions and len(argv) - 1 == actions[argv[0]][1]:
        return actions[argv[0]][0](*argv[1:])
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
