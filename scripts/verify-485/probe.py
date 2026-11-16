"""485 probe helper (from verify-484): the interactive Codex Main's completion check fails with Codex's
'failed to load workspace requirements: invalid input parameter'.

Run with the isolated candidate venv's Python (-I). Reads the isolated projects, 484's retained check evidence
(read only), Codex logs (read only) and talks to Codex's shared background server through `codex app-server proxy`.

  probe.py prepare PROJECT              roles.yml (advisor: Codex) and role_tree, a fresh Task 1 ready
  probe.py mcp CONFIG_TOML              the graphtraj MCP server as CONFIG names it: initialize, tools/list, task_graph
  probe.py daemon CODEX_HOME [THREAD]   one read-only thread/loaded/list through `codex app-server proxy`
  probe.py evidence PROJECT CODEX_HOME [SINCE]   retained completion checks of PROJECT (since SINCE epoch seconds)
  probe.py repro LABEL PROJECT CODEX_HOME MODEL   start a Main-like thread in PROJECT, one turn, then forks with and
                                        without the checker's permission profile, each with one turn (R)
  probe.py main ROOT RUNTIME SESSION    F: the current Main claim (last continuity record) is unchanged
Exit 0 means every printed criterion passed.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import yaml

TASK_ID = '1'
NAME    = 'codex-main-check-probe'
MODEL   = 'gpt-6-luna'
BODY = '''---
difficulty: low
difficulty_reason: Scratch probe for 485
execution_budget:
  estimated_minutes:
    total: 60
  planned_sessions:
    advisor: 1
  correction_rounds: 0
  estimation_note: Probe for the 485 completion check of an interactive Codex Main
  on_exceed: Report only
---
Follow the instruction exactly.
'''
TURN_LIMIT = 180
SYMPTOM    = 'workspace requirements'


def say(*parts: object) -> None:
    """Print one line at once."""
    print(' '.join(str(p) for p in parts), flush=True)


def verdict(name: str, ok: bool, observable: str) -> bool:
    """Print one PASS/FAIL line and return ``ok``."""
    say(f"{'PASS' if ok else 'FAIL'} {name}: {observable}")
    return ok


def run(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run one command (limit 300 s), printing its tail on failure."""
    done = subprocess.run(argv, capture_output=True, text=True, timeout=300, cwd=cwd)
    say(f'$ {" ".join(argv[-3:])} -> rc={done.returncode}')
    if done.returncode:
        say(done.stdout[-600:], done.stderr[-600:])
    return done


def prepare(project: Path) -> int:
    """Write roles and register a ready Task 1; exit 2 register, 3 roles, 4 not ready."""
    graphtraj = str(Path(sys.executable).parent / 'graphtraj')
    roles = {'advisor': {'runtime': 'codex', 'model': MODEL, 'worktree_access': 'read'}}
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({'roles': roles, 'role_tree': {'advisor': {}}}))
    work = project / '.graphtraj/probe-485'
    work.mkdir(exist_ok=True)
    register = work / 'register.yml'
    register.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'task_name': NAME, 'source': 'local:scratch/485', 'title': NAME, 'body': BODY,
        'dependencies': [], 'schema_version': 2, 'parent_id': None, 'disposition': 'active',
        'replaced_by': [], 'retirement_reason': None}))
    state = work / 'state.yml'
    state.write_text(yaml.safe_dump({
        'task_id': TASK_ID, 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
        'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['.graphtraj/probe-485/evidence.md']}))
    (work / 'evidence.md').write_text('485 probe: ready.\n')

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
    doctor   = run(graphtraj, 'doctor', cwd=project)
    roles_ok = doctor.returncode == 0 and 'roles: OK' in doctor.stdout
    say('roles OK' if roles_ok else 'roles NOT OK (doctor): ' + (doctor.stdout + doctor.stderr)[-600:])
    current = task1()
    ready   = current is not None and current.get('status') == 'ready'
    say('task 1 ready' if ready else f'task 1 NOT ready: {current}')
    return rc or (0 if roles_ok else 3) or (0 if ready else 4)


def claims(project: Path) -> list[dict]:
    """Every continuity claim of PROJECT, oldest first."""
    path = project / '.graphtraj/runner/main-sessions/continuity.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.is_file() else []


def daemon(codex_home: str, thread: str | None) -> int:
    """One read-only ``thread/loaded/list`` through ``codex app-server proxy`` (send_event's own channel)."""
    from graphtraj.runtimes.codex.app_server import CodexAppServer

    async def loaded() -> dict:
        async with CodexAppServer(cwd=Path.cwd(), command=('codex', 'app-server', 'proxy'),
                                  environment={'CODEX_HOME': codex_home}, experimental_api=True) as client:
            return await client.call('thread/loaded/list', {})

    try:
        result = asyncio.run(asyncio.wait_for(loaded(), 60))
    except Exception as error:  # the probe prints any failure as evidence
        say('app-server proxy thread/loaded/list: NO |', type(error).__name__, str(error)[:600])
        return 1
    text = json.dumps(result)
    say('app-server proxy thread/loaded/list: YES | CODEX_HOME', codex_home, '| result', text[:600])
    if thread:
        return 0 if verdict('Main thread loaded in the shared background server', thread in text,
                            f'{thread} {"is" if thread in text else "is NOT"} in thread/loaded/list') else 1
    return 0


def mcp(config: Path) -> int:
    """One read-only session with the graphtraj MCP server exactly as CONFIG (.codex/config.toml) names it:
    initialize, tools/list and one ``tasks`` ``task_graph`` call (newline-delimited JSON-RPC over stdio)."""
    import tomllib

    server = tomllib.loads(config.read_text())['mcp_servers']['graphtraj']
    argv   = [server['command'], *server.get('args', [])]
    say('MCP server from', config, ':', argv, 'cwd', server['cwd'])
    proc = subprocess.Popen(argv, cwd=server['cwd'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)

    def request(number: int, method: str, params: dict) -> dict:
        proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': number, 'method': method, 'params': params}) + '\n')
        proc.stdin.flush()
        while line := proc.stdout.readline():
            reply = json.loads(line)
            if reply.get('id') == number:
                return reply
        raise RuntimeError(f'{method}: server closed; stderr {proc.stderr.read()[-600:]}')

    try:
        init = request(1, 'initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                         'clientInfo': {'name': 'verify-485', 'version': '1'}})
        say('MCP initialize:', 'OK' if 'result' in init else 'FAILED', json.dumps(init)[:300])
        proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\n')
        proc.stdin.flush()
        tools = [t.get('name') for t in request(2, 'tools/list', {}).get('result', {}).get('tools', [])]
        say('MCP tools/list:', tools)
        graph = request(3, 'tools/call', {'name': 'tasks', 'arguments': {
            'action': 'execute', 'feature': 'task_graph', 'arguments': {}}})
    except Exception as error:  # printed as evidence
        say('MCP session FAILED:', type(error).__name__, str(error)[:600])
        return 1
    finally:
        proc.stdin.close()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
    text = json.dumps(graph)
    say('MCP tasks task_graph:', 'error' if 'error' in graph or graph.get('result', {}).get('isError') else 'OK', text[:400])
    ok = {'agents', 'tasks'} <= set(tools) and NAME in text
    say('graphtraj tools agents and tasks served:', 'YES' if {'agents', 'tasks'} <= set(tools) else 'NO')
    say('task_graph shows probe Task 1:', 'YES' if NAME in text else 'NO')
    return 0 if ok else 1


def _short(value: object, limit: int = 1500) -> str:
    """Compact JSON for evidence lines."""
    return json.dumps(value, ensure_ascii=False, default=str)[:limit]


def evidence(project: Path, codex_home: str, since: float) -> int:
    """Print PROJECT's retained completion checks (session.yml, execution.yml, error records of the trace).

    Paths follow ``main_finalize.session_binding``/``bind_checker``:
    ``.graphtraj/runner/main-sessions/finalize_<sha256(runtime:session)>/checks/<sha256(child)>/``.
    With SINCE (I2) the newest check after it is judged: PASS when it reached a checker conclusion.
    """
    sessions = project / '.graphtraj/runner/main-sessions'
    say('continuity claims:', [(c.get('runtime'), c.get('session'), c.get('at')) for c in claims(project)])
    found = sorted(sessions.glob('finalize_*/checks/*'), key=lambda d: d.stat().st_mtime)
    say('retained check directories under', sessions, ':', len(found))
    judged = None
    for d in found:
        if d.stat().st_mtime < since:
            continue
        say('== CHECK', d)
        for name in ('session.yml', 'execution.yml'):
            f = d / name
            if not f.is_file():
                say(f'  {name}: ABSENT')
                continue
            doc = yaml.safe_load(f.read_text()) or {}
            if name == 'session.yml':
                say('  session.yml:', _short(doc, 800))
                continue
            judged = (d, doc)
            for key in ('session', 'parent', 'parent_turn', 'turn', 'model', 'provider', 'outcome', 'error'):
                say(f'  {key}:', _short(doc.get(key), 1200))
            say('  output:', _short(doc.get('output'), 1200))
            for key in ('configuration', 'parent_configuration', 'authorized_difference'):
                say(f'  {key}:', _short(doc.get(key), 3000))
        trace = d / 'events.jsonl'
        if trace.exists():
            say('  events.jsonl ->', trace.resolve())
            try:
                for number, line in enumerate(trace.read_text(errors='replace').splitlines(), 1):
                    low = line.lower()
                    if 'error' in low or SYMPTOM in low or 'requirements' in low:
                        say(f'  trace:{number}', line[:800])
            except OSError as error:
                say('  events.jsonl unreadable:', error)
        else:
            say('  events.jsonl: ABSENT (ephemeral fork without a rollout path, or never started)')
    logs = sorted(Path(codex_home, 'log').glob('*.log*')) if Path(codex_home, 'log').is_dir() else []
    say('Codex logs (read only, lines naming the symptom):', [str(p) for p in logs] or 'NONE')
    for log in logs:
        try:
            hits = [line for line in log.read_text(errors='replace').splitlines()
                    if 'requirements' in line.lower()]
        except OSError as error:
            say(' ', log.name, 'unreadable:', error)
            continue
        say(f'  {log.name}: {len(hits)} lines with "requirements"; last 15:')
        for line in hits[-15:]:
            say('   ', line[:600])
    if since <= 0:
        return 0
    if judged is None:
        say('no completion checker was retained since I1 (a check decided before the fork leaves none;'
            ' the user copies the TUI "Completion Check" lines)')
        return 1
    d, doc = judged
    output, status = doc.get('output'), None
    try:
        status = json.loads(output).get('status') if isinstance(output, str) else None
    except ValueError:
        pass
    ok = doc.get('outcome') == 'completed' and status in ('completed', 'waiting', 'actionable')
    verdict('I2 completion check reached a conclusion', ok,
            f"outcome {doc.get('outcome')} | checker status {status} | error {_short(doc.get('error'), 600)}")
    return 0 if ok else 1


def repro(label: str, project: Path, codex_home: str, model: str) -> int:
    """R: a Main-like thread in PROJECT through the checker's own proxy, then the checker's fork.

    a  base thread (model and cwd only, like an interactive Main), one trivial turn
    R1 fork exactly as ``finalize.check`` (graphtraj_checker profile + the daemon control socket), one turn
    R1b the same fork while a base turn is still in progress (as at Stop), one turn
    R2 fork without the network profile/socket (Main's own profile), one turn
    Every request is limited; the base thread is archived at the end; forks are ephemeral.
    """
    from graphtraj.runtimes.codex.app_server import CHECKER_PERMISSION_PROFILE
    from graphtraj.runtimes.codex.finalize import control_socket, proxy

    socket = control_socket(codex_home)
    say(f'[{label}] project {project} | CODEX_HOME {codex_home} | control socket {socket}')
    results: dict[str, str] = {}

    async def refuse(request) -> dict:
        say(f'  server request {request.method} (refused):', _short(request.params, 400))
        raise RuntimeError('verify-485 approves nothing')

    seen: dict[str, dict] = {}

    async def turn(client, thread: str, prompt: str, name: str) -> dict:
        """Start one base turn (raw turn/start, like a host's own input)."""
        try:
            started = await client.call('turn/start', {'threadId': thread, 'input': [{'type': 'text', 'text': prompt}]})
        except Exception as error:
            say(f'  {name} turn/start ERROR:', type(error).__name__, str(error)[:1200])
            results[name] = 'turn/start error: ' + str(error)[:300]
            return {}
        tid = started.get('turn', {}).get('id')
        say(f'  {name} turn/start -> turn {tid} status {started.get("turn", {}).get("status")}')
        return {'thread': thread, 'turn': tid}

    async def finished(client, started: dict, name: str) -> None:
        """Wait for the base turn's turn/completed; other notices are kept by turn id."""
        if not started:
            return
        deadline = time.monotonic() + TURN_LIMIT
        while started['turn'] not in seen and time.monotonic() < deadline:
            try:
                notice = await client.next_notification(timeout=deadline - time.monotonic())
            except Exception as error:
                say(f'  {name} wait ERROR:', type(error).__name__, str(error)[:600])
                break
            params = notice.get('params', {}) if isinstance(notice, dict) else {}
            if notice.get('method') == 'error':
                say(f'  error notice ({params.get("threadId")}):', _short(params, 1200))
            if notice.get('method') == 'turn/completed':
                seen[params.get('turn', {}).get('id')] = params.get('turn', {})
        t = seen.get(started['turn'])
        if t is None:
            say(f'  {name}: no turn/completed within {TURN_LIMIT} s')
            results[name] = 'no turn/completed'
            return
        say(f'  {name} TURN {t.get("id")} status {t.get("status")} | error {_short(t.get("error"), 1200)}')
        results[name] = f'{t.get("status")} {_short(t.get("error"), 300)}'

    async def checker_turn(client, child, name: str) -> None:
        """The checker's own path: start_execution + wait (finalize.check), error text verbatim."""
        try:
            execution = await client.start_execution(child, 'Reply with exactly one line: PONG-fork. Use no tool.')
            result = await client.wait(execution, timeout=TURN_LIMIT)
        except Exception as error:
            say(f'  {name} EXECUTION ERROR:', type(error).__name__, str(error)[:1200])
            results[name] = 'execution error: ' + str(error)[:400]
            return
        say(f'  {name} EXECUTION', _short(result, 600))
        results[name] = f"{result.get('outcome')} {_short(result.get('last_agent_message'), 100)}"

    async def main() -> None:
        async with proxy({'session': 'verify-485', 'codex_home': codex_home}, refuse) as client:
            original = client._call

            async def logged(method, params, **options):
                if method in ('thread/start', 'thread/fork'):
                    say(f'  -> {method}', _short(params, 2000))
                reply = await original(method, params, **options)
                if method in ('thread/start', 'thread/fork', 'thread/resume'):
                    say(f'  <- {method}', _short({k: reply.get(k) for k in (
                        'model', 'cwd', 'runtimeWorkspaceRoots', 'approvalPolicy', 'approvalsReviewer', 'sandbox',
                        'activePermissionProfile', 'reasoningEffort')}, 2000),
                        '| thread', _short({k: (reply.get('thread') or {}).get(k) for k in (
                            'id', 'ephemeral', 'forkedFromId', 'source', 'path')}, 600))
                return reply
            client._call = logged
            base = (await client.call('thread/start', {'model': model, 'cwd': str(project)}))['thread']['id']
            try:
                await finished(client, await turn(client, base, 'Reply with exactly one line: PONG-a. Use no tool.',
                                                  'a base'), 'a base')
                parent = await client.read_thread(base)
                configuration = await client.subscribe_host(base)
                parent = {**parent, 'model': model, 'configuration': configuration, 'turn_settings': {}}
                if 'reasoningEffort' in configuration:
                    parent['turn_settings']['effort'] = configuration['reasoningEffort']
                for name, kwargs in (('R1 checker fork', {'network_profile': CHECKER_PERMISSION_PROFILE,
                                                          'unix_socket': socket}),
                                     ('R2 plain fork', {})):
                    try:
                        child = await client.fork_session(parent, **kwargs)
                    except Exception as error:
                        say(f'  {name} fork ERROR:', type(error).__name__, str(error)[:1200])
                        results[name] = 'fork error: ' + str(error)[:300]
                        continue
                    say(f'  {name} fork -> {child.thread_id} | configuration', _short(child.configuration, 2000))
                    await checker_turn(client, child, name)
                # R1b: fork while a base turn is in progress, as the Stop hook does.
                name = 'R1b checker fork during base turn'
                busy = await turn(client, base, 'Count from 1 to 200, one number per line. Use no tool.', 'b base')
                try:
                    child = await client.fork_session(parent, network_profile=CHECKER_PERMISSION_PROFILE,
                                                      unix_socket=socket)
                    say(f'  {name} fork -> {child.thread_id}')
                    await checker_turn(client, child, name)
                except Exception as error:
                    say(f'  {name} fork ERROR:', type(error).__name__, str(error)[:1200])
                    results[name] = 'fork error: ' + str(error)[:300]
                await finished(client, busy, 'b base')
            finally:
                try:
                    say('  archive base thread:', _short(await client.call('thread/archive', {'threadId': base}), 300))
                except Exception as error:
                    say('  archive base thread FAILED:', type(error).__name__, str(error)[:300])

    try:
        asyncio.run(asyncio.wait_for(main(), 900))
    except Exception as error:  # printed as evidence
        say(f'[{label}] session ERROR:', type(error).__name__, str(error)[:1200])
        results['session'] = 'error: ' + str(error)[:300]
    say(f'[{label}] SUMMARY:')
    for name, value in results.items():
        say(f'  {label} {name}: {value}', '<= SYMPTOM' if SYMPTOM in value else '')
    hit = [n for n, v in results.items() if SYMPTOM in v]
    say(f'[{label}] REPRODUCED' if hit else f'[{label}] NOT reproduced', '(' + ', '.join(hit) + ')' if hit else '')
    return 0


def variants(label: str, project: Path, codex_home: str, model: str) -> int:
    """R5: which part of the checker's permission override makes Codex fail the fork's turn.

    For each base profile (':read-only', ':workspace'; explicit ``permissions`` on thread/start, so both run
    in the same project and Codex reports what it applied), one base thread with one trivial turn, then
    forks built like ``fork_session`` but with these overrides of ``permissions.graphtraj_checker``:
      plain     Main's own profile, no override (control)
      net+sock  extends Main's profile, network enabled, unix_sockets {realpath socket: allow} (today's form)
      net       extends Main's profile, network enabled, no unix_sockets
      net+lit   network enabled, unix_sockets {literal $CODEX_HOME/app-server-control/app-server-control.sock}
      sock      extends Main's profile, network NOT enabled, unix_sockets {realpath socket: allow}
    Each fork's one turn asks the model to run one command that connects to the control socket, so a
    completing variant also shows whether the checker keeps its access (SOCKET-CONNECT-OK).
    """
    import os
    from graftling.codex.app_server import CodexSession
    from graphtraj.runtimes.codex.finalize import control_socket, proxy

    real = control_socket(codex_home)
    literal = str(Path(codex_home) / 'app-server-control' / 'app-server-control.sock')
    command = (f'{sys.executable} -I -c "import socket; s = socket.socket(socket.AF_UNIX); '
               f"s.connect('{real}'); print('SOCKET-CONNECT-OK')\"")
    prompt = ('Run exactly this one shell command, once, with no other command and without asking for any '
              f'approval or escalation, then reply with only its last output line or its error line: {command}')
    say(f'[{label}] project {project} | CODEX_HOME {codex_home} | socket realpath {real} | literal {literal}'
        f' (is symlink: {os.path.islink(literal)})')
    say(f'[{label}] checker command: {command}')
    results: list[tuple[str, str, str]] = []

    async def refuse(request) -> dict:
        say(f'  server request {request.method} (refused):', _short(request.params, 400))
        raise RuntimeError('verify-485 approves nothing')

    def overrides(base: str) -> list[tuple[str, dict | None]]:
        return [
            ('plain', None),
            ('net+sock', {'extends': base, 'network': {'enabled': True, 'unix_sockets': {real: 'allow'}}}),
            ('net', {'extends': base, 'network': {'enabled': True}}),
            ('net+lit', {'extends': base, 'network': {'enabled': True, 'unix_sockets': {literal: 'allow'}}}),
            ('sock', {'extends': base, 'network': {'unix_sockets': {real: 'allow'}}}),
        ]

    async def one(client, parent: dict, configuration: dict, base: str, name: str, override: dict | None,
                  tag: str) -> None:
        params = {'threadId': parent['id'], 'model': model, 'modelProvider': parent['modelProvider'],
                  'excludeTurns': True, 'ephemeral': True}
        for key in ('serviceTier', 'cwd', 'runtimeWorkspaceRoots', 'approvalPolicy', 'approvalsReviewer'):
            if key in configuration:
                params[key] = configuration[key]
        params['config'] = ({'model_reasoning_effort': configuration['reasoningEffort']}
                            if configuration.get('reasoningEffort') else {})
        if override is None:
            params['permissions'] = base
        else:
            params['permissions'] = 'graphtraj_checker'
            params['config']['permissions.graphtraj_checker'] = override
        say(f'  [{base} {name}] -> thread/fork', _short(params, 1500))
        try:
            reply = await client.call('thread/fork', params)
        except Exception as error:
            say(f'  [{base} {name}] fork ERROR:', type(error).__name__, str(error)[:1200])
            results.append((tag, name, 'fork error: ' + str(error)[:300]))
            return
        thread = reply['thread']
        say(f'  [{base} {name}] <- fork {thread["id"]}', _short({k: reply.get(k) for k in (
            'sandbox', 'activePermissionProfile')}, 800))
        session = CodexSession(thread['id'], None, {}, {}, thread, inherited_history_excluded=True)
        client._sessions[session.thread_id] = session
        try:
            execution = await client.start_execution(session, prompt)
            result = await client.wait(execution, timeout=TURN_LIMIT)
        except Exception as error:
            say(f'  [{base} {name}] EXECUTION ERROR:', type(error).__name__, str(error)[:1200])
            results.append((tag, name, 'execution error: ' + str(error)[:400]))
            return
        text = str(result.get('last_agent_message'))
        say(f'  [{base} {name}] EXECUTION {result.get("outcome")} | last message {text[:600]!r}')
        notices(client, thread['id'], f'[{base} {name}]')
        if result.get('last_agent_message') is None:
            results.append((tag, name, f"{result.get('outcome')} | NO MODEL REPLY: row invalid (see its notices)"))
            return
        results.append((tag, name, f"{result.get('outcome')} | socket "
                                    f"{'REACHED' if 'SOCKET-CONNECT-OK' in text else 'NOT reached'} | {text[:200]!r}"))

    def notices(client, thread: str, tag: str) -> None:
        """Print this thread's received notices: method, item type, hook output; shows a hook-stopped turn."""
        for notice in client.drain_notifications():
            params = notice.get('params', {}) if isinstance(notice, dict) else {}
            if params.get('threadId') != thread or notice.get('method', '').endswith('/delta'):
                continue
            item = params.get('item') or params.get('run') or {}
            detail = {k: item.get(k) for k in ('type', 'status', 'eventName', 'statusMessage', 'entries', 'text',
                                                'command', 'aggregatedOutput', 'exitCode') if k in item}
            if notice.get('method') in ('error', 'turn/completed'):
                detail = params.get('error') or (params.get('turn') or {}).get('error') or detail
            say(f'  {tag} notice {notice.get("method")}', _short(detail, 500))

    async def main() -> None:
        async with proxy({'session': 'verify-485', 'codex_home': codex_home}, refuse) as client:
            for base in (':read-only', ':workspace'):
                try:
                    started = await client.call('thread/start', {'model': model, 'cwd': str(project),
                                                                 'permissions': base})
                except Exception as error:
                    say(f'  [{base}] thread/start ERROR:', type(error).__name__, str(error)[:800])
                    results.append((base, 'base', 'thread/start error: ' + str(error)[:300]))
                    continue
                tid = started['thread']['id']
                applied = (started.get('activePermissionProfile') or {}).get('id')
                say(f'  [{base}] base {tid} | applied profile {applied} | sandbox {_short(started.get("sandbox"), 300)}')
                try:
                    session = CodexSession(tid, None, {}, {}, started['thread'])
                    client._sessions[tid] = session
                    done = await client.wait(await client.start_execution(
                        session, 'Reply with exactly one line: PONG-base. Use no tool.'), timeout=TURN_LIMIT)
                    say(f'  [{base}] base turn {done.get("outcome")} {done.get("last_agent_message")!r}')
                    notices(client, tid, f'[{base}] base')
                    parent = {**await client.read_thread(tid)}
                    configuration = await client.subscribe_host(tid)
                    for name, override in overrides(applied or base):
                        await one(client, parent, configuration, applied or base, name, override,
                                  f'{base}(applied {applied})')
                except Exception as error:
                    say(f'  [{base}] ERROR:', type(error).__name__, str(error)[:800])
                    results.append((base, 'base', 'error: ' + str(error)[:300]))
                finally:
                    try:
                        await client.call('thread/archive', {'threadId': tid})
                        say(f'  [{base}] base thread archived')
                    except Exception as error:
                        say(f'  [{base}] archive FAILED:', type(error).__name__, str(error)[:300])

    try:
        asyncio.run(asyncio.wait_for(main(), 1500))
    except Exception as error:  # printed as evidence
        say(f'[{label}] session ERROR:', type(error).__name__, str(error)[:1200])
    say(f'[{label}] SUMMARY (base profile, variant: outcome | socket | message):')
    for base, name, value in results:
        say(f'  {label} {base} {name}: {value}', '<= SYMPTOM' if SYMPTOM in value else '')
    return 0


def main_unchanged(root: Path, rt: str, sess: str) -> int:
    """F: the last continuity claim is the one recorded at 00."""
    found = claims(root)
    last  = found[-1] if found else {}
    ok    = bool(last) and last.get('runtime') == rt and last.get('session') == sess
    verdict('F production Main', ok, f"last continuity claim {last.get('runtime')}:{last.get('session')} "
                                     f'== recorded at 00 {rt}:{sess}')
    return 0 if ok else 1


def main() -> int:
    """Dispatch one probe command."""
    cmd, *args = sys.argv[1:]
    if cmd == 'prepare':
        return prepare(Path(args[0]))
    if cmd == 'mcp':
        return mcp(Path(args[0]))
    if cmd == 'daemon':
        return daemon(args[0], args[1] if len(args) > 1 else None)
    if cmd == 'evidence':
        return evidence(Path(args[0]), args[1], float(args[2]) if len(args) > 2 else 0)
    if cmd == 'repro':
        return repro(args[0], Path(args[1]), args[2], args[3])
    if cmd == 'variants':
        return variants(args[0], Path(args[1]), args[2], args[3])
    if cmd == 'main':
        return main_unchanged(Path(args[0]), args[1], args[2])
    say('unknown command', cmd)
    return 2


if __name__ == '__main__':
    sys.exit(main())
