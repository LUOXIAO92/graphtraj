"""The criteria of the 392 real-host steps. Each zsh step runs one function here.

Usage (from a step, with RH_* set by common.zsh): python -E -s checks.py <function> [argument]

Each function drives real hosts through rh392 and writes one PASS, FAIL or CANNOT line per criterion
to the step's summary. An unexpected error ends that one case with a FAIL naming it, and the next
case still runs, because the user is not available to debug.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import traceback
import uuid

import yaml

from rh392 import (AG, CHILD_CHOICE, CLAUDE, CLAUDE_MODEL, CLAUDE_PROJECT, DEEPSEEK_MODEL, ENV, Host, KEY_VARIABLE,
                   OUT, PI, PI_PROVIDER, PYTHON, RUN, RUNTIMES, SLEEP, Turn, alive, call, check, codex_settings,
                   connection, error_code, host_process, judge, keep_tree, last_result, note, script_prompt,
                   shown_count)

WAIT = 240
LOCK_SECONDS = 60
STOP_LINE = 'stop-unconfirmed'
RECORDED_LINE = 'agents host recorded its children stopped.'
REPLACED_LINE = 'agents host replaced a stale channel of a dead host'
# Denies TCP binding only, the same refusal 420 and 421 saw from DSH: listen EPERM on 127.0.0.1.
# Unix sockets stay allowed: the hosts' owner connections use them.
NO_BIND = '(version 1)(allow default)(deny network-bind (local ip "*:*"))'


def guarded(name: str, case, *arguments) -> None:
    """Run one case; an unexpected error is that case's FAIL, not the step's end."""
    try:
        case(*arguments)
    except Exception as error:
        (OUT / f'{name}.traceback.txt').write_text(traceback.format_exc())
        check('FAIL', f'{name}: the check itself stopped with {type(error).__name__}: {str(error)[:300]}; '
                      f'see {name}.traceback.txt')


def wait_call(agent: str = '<agent from 1>', seconds: int = WAIT) -> str:
    """Return one wait call."""
    return call('wait', agent=agent, timeout_seconds=seconds)


# -- the 16 cells ---------------------------------------------------------

def cell(kind: str, runtime: str) -> None:
    """One host and one child Runtime: create, status, send, interrupt, resume, retire."""
    name = f'{kind}-x-{runtime}'
    model, effort = CHILD_CHOICE[runtime]
    # 408: a Claude host's Pi child has no declared connection, so create's model is checked against
    # the catalog of pi on the host's PATH. Everywhere else the declared list avoids that query.
    declared = not (kind == 'claude' and runtime == 'pi')
    host = Host(kind, name, {runtime: None}, {'connections': {f'local-{runtime}': connection(runtime)}} if declared else {})
    sleep = SLEEP.format(seconds=120, answer='SLEPT') + ('' if runtime != 'dsh' else ' Your parent authorizes it.')
    first = host.turn(name + '-1', script_prompt([
        call('create', runtime=runtime, model=model, reasoning_effort=effort, name=f'c-{kind}-{runtime}',
             instruction='Do not use any tool. Reply with exactly: PONG-1'),
        wait_call(),
        call('status', agent='<agent from 1>'),
        call('send', agent='<agent from 1>', message='Do not use any tool. Reply with exactly: PONG-2'),
        wait_call(),
        call('send', agent='<agent from 1>', message=sleep),
        call('interrupt', agent='<agent from 1>'),
        wait_call(),
        call('resume', agent='<agent from 1>', message='Do not use any tool. Reply with exactly: PONG-3'),
        wait_call(),
        call('create', runtime=runtime, model='no-such-model-392', instruction='Reply OK.'),
    ], 'Then reply with one line: AGENT=<agent from 1>, and stop.'))
    created = first.created(runtime)
    if created is None:
        check('FAIL', f'{name} create: no child; results {[(d.get("action"), error_code(d)) for d in first.documents][:6]}; '
                      f'see {first.label}.stdout, .stderr')
        host.keep_data()
        return
    agent, session = created['agent'], created.get('session')
    identity = created['result']
    judge(identity.get('runtime') == runtime and identity.get('model') == model
          and identity.get('reasoning_effort') == effort,
          f'{name} create chooses Runtime, model and effort',
          {field: identity.get(field) for field in ('runtime', 'model', 'reasoning_effort', 'connection')})
    statuses = first.of('status', agent)
    shown = statuses[0]['result'] if statuses else {}
    judge(bool(statuses) and shown.get('agent') == agent and shown.get('parent') is None and shown.get('runtime') == runtime
          and (shown.get('creator') or {}).get('session') not in (None, ''),
          f'{name} status shows identity and parent',
          {field: shown.get(field) for field in ('agent', 'name', 'runtime', 'parent', 'creator', 'host')})
    second = host.turn(name + '-2', script_prompt([
        call('status', agent=agent),
        call('retire', agent=agent),
        call('retire', agent=agent),
    ]))
    turns = [first, second]
    judge(any(not error_code(d) for d in first.of('send', agent)) and shown_count(host, turns, agent, 'PONG-2') >= 1,
          f'{name} send reaches the child and its answer comes back',
          f"PONG-2 shown {shown_count(host, turns, agent, 'PONG-2')}")
    interrupts = [(d.get('result') or {}).get('interrupt') for d in first.of('interrupt', agent)]
    ended = [item for item in host.notices_of(agent) if item['event'] == 'interrupted']
    outcomes = [last_result(d).get('outcome') for d in first.of('wait', agent)]
    judge(any(item in ('requested', 'already-requested') for item in interrupts)
          and (bool(ended) or 'interrupted' in outcomes),
          f'{name} interrupt stops the child', f'interrupt {interrupts}; wait outcomes {outcomes}; notices {len(ended)}')
    resumed = [d for d in first.of('resume', agent) if not error_code(d)]
    judge(bool(resumed) and resumed[0].get('session') == session and shown_count(host, turns, agent, 'PONG-3') >= 1,
          f'{name} resume continues the same native Session',
          f"session {session} -> {resumed[0].get('session') if resumed else None}; "
          f"PONG-3 shown {shown_count(host, turns, agent, 'PONG-3')}")
    refused = [error_code(d) for d in first.of('create') if d is not created and d.get('agent') is None]
    judge('invalid-model' in refused, f'{name} an invalid model is refused by name', refused)
    later = second.of('status', agent)
    same = later[0]['result'] if later else {}
    judge(bool(later) and all(same.get(field) == shown.get(field) for field in ('agent', 'runtime', 'parent', 'creator', 'session')),
          f'{name} a new host process shows the same identity', {field: same.get(field) for field in ('agent', 'runtime', 'parent')})
    retires = [(d.get('result') or {}) for d in second.of('retire', agent)]
    judge(len(retires) >= 2 and retires[0].get('retired') is True and retires[1].get('duplicate') is True,
          f'{name} retire takes effect once', [(r.get('retired'), r.get('duplicate')) for r in retires])
    counts = {token: shown_count(host, turns, agent, token) for token in ('PONG-1', 'PONG-2', 'PONG-3')}
    judge(all(value == 1 for value in counts.values()), f'{name} each answer reaches the parent once', counts)
    if not declared:
        note(f'{name}: no connection declared; create accepted {model} and refused no-such-model-392 against the catalog '
             'of pi on PATH (408)')
    host.keep_data()


def matrix(kind: str) -> None:
    """One host's row of the matrix."""
    for runtime in RUNTIMES:
        guarded(f'{kind}-x-{runtime}', cell, kind, runtime)
    summary = (OUT / 'summary.txt').read_text().splitlines()
    table = []
    for runtime in RUNTIMES:
        name = f'{kind}-x-{runtime}'
        lines = [line for line in summary if line.split(' ', 1)[-1].startswith(name) and not line.startswith('note')]
        failed = [line for line in lines if line.startswith(('FAIL', 'CANNOT'))]
        table.append(f"{name}: {'NO RESULT' if not lines else 'FAIL' if failed else 'PASS'} ({len(lines) - len(failed)} of {len(lines)})")
    (OUT / 'matrix.txt').write_text('\n'.join(table) + '\n')
    print('\n'.join(table))


# -- exchanges ------------------------------------------------------------

def ask_parent(runtime: str) -> None:
    """A real child's permission request, answered by a real parent, delivered once (408: Pi)."""
    name = f'ask-parent-{runtime}'
    model, effort = CHILD_CHOICE[runtime]
    host = Host('claude', name, {runtime: None}, {'connections': {f'local-{runtime}': connection(runtime)}})
    instruction = ('Use the agents tool (the MCP server agents) once, with exactly these arguments: '
                   + call('ask_parent', kind='decision', question='Which colour should this check use?', timeout_seconds=300)
                   + ' Then reply with exactly: COLOUR=<the answer field>. Use no other tool.')
    turn = host.turn(name, script_prompt([
        call('create', runtime=runtime, model=model, reasoning_effort=effort, instruction=instruction),
        wait_call(seconds=300),
        call('requests', agent='<agent from 1>'),
        '{"action":"execute","feature":"reply","arguments":{"agent":"<agent from 1>","request":<the first request document '
        'from call 3, unchanged>,"response":{"answer":"BLUE392"}}}',
        wait_call(seconds=300),
    ]))
    created = turn.created(runtime)
    if created is None:
        check('FAIL', f'{name}: no child; see {name}.stdout')
        return
    agent = created['agent']
    requests = next(((d.get('result') or {}).get('requests') for d in turn.of('requests', agent)
                     if (d.get('result') or {}).get('requests')), []) or []
    method = requests[0].get('method') if requests else None
    judge(method == 'agents/decision', f'{name} the child asks through ask_parent', f'requests method {method}')
    replies = [d for d in turn.of('reply', agent) if not error_code(d)]
    judge(bool(replies), f'{name} the parent answers once with reply', [(d.get('result') or {}).get('reply_status') for d in replies])
    told = [notice for notice in host.notices_of(agent) if notice['event'] == 'request']
    judge(len(told) == 1, f'{name} the permission request notifies the parent once', [notice['id'] for notice in told])
    count = shown_count(host, [turn], agent, 'BLUE392')
    judge(count == 1, f'{name} the child goes on with the answer and its answer reaches the parent once', f'COLOUR=BLUE392 shown {count}')
    host.keep_data()


def exchanges() -> None:
    """Permission requests from real children; message exchange is in every matrix cell."""
    for runtime in ('pi', 'claude'):
        guarded(f'ask-parent-{runtime}', ask_parent, runtime)


# -- system failures ------------------------------------------------------

def failure_turn(host: Host, label: str, runtime: str, model: str | None) -> None:
    """Create a child whose start fails, read nothing, and judge the notice the parent receives."""
    arguments = {'runtime': runtime, 'instruction': 'Do not use any tool. Reply with exactly: NEVER-392'}
    if model is not None:
        arguments['model'] = model
    first = host.turn(label + '-1', script_prompt(
        [call('create', **arguments)],
        'Do not call wait or status. Then run the shell command /bin/sleep 90 with your bash tool, and only then reply '
        'with one line and stop. If an agents notice arrives, reply with one line saying what it says.'))
    created = first.created(runtime)
    if created is None:
        check('FAIL', f'{label}: create returned no Agent; results {[(d.get("action"), error_code(d)) for d in first.documents]}; '
                      f'see {label}-1.stderr')
        return
    agent = created['agent']
    second = host.turn(label + '-2', script_prompt([call('status', agent=agent)]))
    result = last_result(second.of('status', agent)[0]) if second.of('status', agent) else {}
    told = [notice for notice in host.notices_of(agent) if notice['event'] == 'failed']
    note(f"{label}: code {(result.get('error') or {}).get('code')}; message {(result.get('error') or {}).get('message')!r}")
    judge(result.get('outcome') == 'failed', f'{label} the start failure ends the child failed', result.get('outcome'))
    judge(len(told) == 1, f'{label} the parent receives the failure notice once', [(notice['id'], notice['body'][:200]) for notice in told])
    judge(result.get('notification') == 'delivered', f'{label} public status says delivered', result.get('notification'))
    host.keep_data()


def bind_is_refused() -> str | None:
    """Return why the no-bind sandbox cannot be used here, or nothing when it refuses as 421 saw."""
    probe = ('import socket, tempfile, os\n'
             's=socket.socket()\n'
             'try:\n    s.bind(("127.0.0.1",0)); print("BOUND")\n'
             'except PermissionError: print("EPERM")\n'
             'u=socket.socket(socket.AF_UNIX)\n'
             'p=tempfile.mktemp(dir=os.environ["RH_PROBE_DIR"])\n'
             'u.bind(p); print("UNIX")\n')
    environment = {**ENV, 'RH_PROBE_DIR': str(RUN)}
    try:
        done = subprocess.run(['/usr/bin/sandbox-exec', '-p', NO_BIND, PYTHON, '-c', probe], capture_output=True,
                              text=True, timeout=30, env=environment)
    except (OSError, subprocess.SubprocessError) as error:
        return f'sandbox-exec did not run: {error}'
    if done.stdout.split() != ['EPERM', 'UNIX']:
        return f'sandbox-exec probe printed {done.stdout.split()}, stderr {done.stderr[-200:]!r}'
    return None


def resume_start_failure() -> None:
    """421: a real independent resume whose native start fails, as DSH does on listen EPERM."""
    label = 'resume-failure'
    reason = bind_is_refused()
    if reason:
        check('CANNOT', f'{label}: a real resume start failure needs a host that refuses local binding; {reason}')
        return
    host = Host('pi', label, {'dsh': None}, {'save_normalized_sessions': True,
                                             'connections': {'local-dsh': connection('dsh')}})
    first = host.turn(label + '-1', script_prompt([
        call('create', runtime='dsh', model=DEEPSEEK_MODEL, reasoning_effort='low',
             instruction='Do not use any tool. Reply with exactly: BEFORE-392'),
        wait_call(),
    ]))
    created = first.created('dsh')
    if created is None:
        check('FAIL', f'{label}: the first turn created no DSH child; see {label}-1.stderr')
        return
    agent = created['agent']
    # This host process, and so the DSH service it starts, may not bind a TCP port.
    plain = host._argv
    host._argv = lambda prompt, name: (['/usr/bin/sandbox-exec', '-p', NO_BIND, *plain(prompt, name)[0]], plain(prompt, name)[1])
    second = host.turn(label + '-2', script_prompt(
        [call('resume', agent=agent, message='Do not use any tool. Reply with exactly: AFTER-392')],
        'Do not call wait or status. Then run the shell command /bin/sleep 45 with your bash tool, and only then reply '
        'with one line and stop.'))
    host._argv = plain
    third = host.turn(label + '-3', script_prompt([call('status', agent=agent)]))
    result = last_result(third.of('status', agent)[0]) if third.of('status', agent) else {}
    error = result.get('error') or {}
    note(f'{label}: resume results {[(error_code(d), (d.get("result") or {}).get("resumed")) for d in second.of("resume", agent)]}; '
         f'code {error.get("code")}; message {error.get("message")!r}')
    judge(result.get('outcome') == 'failed', f'{label} the failed start ends the execution failed', result.get('outcome'))
    judge('EPERM' in str(error.get('message')), f'{label} the message keeps the real reason', error)
    told = [notice for notice in host.notices_of(agent) if notice['event'] == 'failed']
    judge(len(told) == 1, f'{label} the parent receives the failure notice once', [notice['id'] for notice in told])
    host.keep_data()


def failures() -> None:
    """Real Claude and Pi start failures and a real resume start failure, on a real Pi parent."""
    def claude_failure() -> None:
        host = Host('pi', 'claude-start-failure', {'claude': None}, {'connections': {
            'local-claude': connection('claude', ['claude-no-such-model-392'])}})
        failure_turn(host, 'claude-start-failure', 'claude', 'claude-no-such-model-392')

    def pi_failure() -> None:
        # The child's PATH reaches neither srt nor node: 391's missing tool, seen through a real Pi host.
        host = Host('pi', 'pi-start-failure', {'pi': {'sandbox_path': '/usr/bin:/bin'}})
        failure_turn(host, 'pi-start-failure', 'pi', None)

    guarded('claude-start-failure', claude_failure)
    guarded('pi-start-failure', pi_failure)
    guarded('resume-failure', resume_start_failure)


def launch_failed(runner: str, graphtraj: str) -> None:
    """421: GraphTraj's Runner reports a DSH member that cannot start as ``launch-failed`` with its reason."""
    reason = bind_is_refused()
    if reason:
        check('CANNOT', f'launch-failed: needs a Runner that refuses local binding; {reason}')
        return
    project = RUN / 'gt-project'
    project.mkdir()
    environment = {name: value for name, value in ENV.items() if not name.startswith(('GRAPHTRAJ_', 'RH_'))}
    environment.pop('AGENT_SWARM_CONNECTION', None)

    def run(*argv: str, stdin: str | None = None, sandboxed: bool = False) -> subprocess.CompletedProcess:
        prefix = ['/usr/bin/sandbox-exec', '-p', NO_BIND] if sandboxed else []
        return subprocess.run([*prefix, *argv], cwd=project, env=environment, input=stdin, capture_output=True,
                              text=True, timeout=240)

    run('git', 'init', '-q', '--initial-branch=main')
    (project / 'README.md').write_text('# 392 scratch project\n')
    run('git', 'add', 'README.md')
    run('git', 'commit', '-qm', 'Initial source')
    setup = run(graphtraj, 'setup', stdin='y\n')
    (OUT / 'setup.txt').write_text(setup.stdout + setup.stderr)
    (project / '.graphtraj' / 'roles.yml').write_text(yaml.safe_dump({
        'roles': {'writer': {'runtime': 'dsh', 'model': DEEPSEEK_MODEL, 'dsh': {'api_key_env': KEY_VARIABLE}}},
        'role_tree': {'writer': {}}}))
    task = RUN / 'task.yml'
    task.write_text(yaml.safe_dump({
        'task_id': '1', 'task_name': 'article', 'source': 'realhost-392', 'title': 'Article line',
        'body': 'Reply with one line.', 'dependencies': [], 'schema_version': 2, 'parent_id': None,
        'disposition': 'active', 'replaced_by': [], 'retirement_reason': None}))
    registered = run(graphtraj, 'task', 'register', '--task-file', str(task))
    (project / 'delivery-evidence.md').write_text('Main validated readiness for the 392 check.\n')
    ready = RUN / 'ready.yml'
    ready.write_text(yaml.safe_dump({
        'task_id': '1', 'status': 'ready', 'active_team_ordinal': None, 'worktree': None, 'branch': None,
        'current_candidate': None, 'caused_by_event_ids': [], 'evidence_refs': ['delivery-evidence.md']}))
    updated = run(graphtraj, 'task', 'update', '--state-file', str(ready))
    (OUT / 'task.txt').write_text(registered.stdout + registered.stderr + updated.stdout + updated.stderr)
    batch = RUN / 'batch.yml'
    batch.write_text("tasks: [{task_id: '1', task_name: article, role: writer}]\n")
    done = run(runner, '--swarm-input', str(batch), sandboxed=True)
    (OUT / 'swarm-output.yml').write_text(done.stdout)
    (OUT / 'swarm-stderr.txt').write_text(done.stderr)
    try:
        tasks = yaml.safe_load(done.stdout)['tasks']
    except Exception as error:
        check('FAIL', f'launch-failed: the Runner printed no task list ({type(error).__name__}); see swarm-output.yml, swarm-stderr.txt')
        return
    error = tasks[0].get('error') or {}
    judge(error.get('code') == 'launch-failed', 'launch-failed the public code of a failed DSH start', error.get('code'))
    judge('EPERM' in str(error.get('message')), 'launch-failed the message keeps the real reason', error.get('message'))


# -- four approval layers -------------------------------------------------

def layer_workspace() -> None:
    """Layer 1: the assigned workspace is the child's working directory, and its limit holds."""
    name = 'layer1-workspace'
    assigned = CLAUDE_PROJECT / f'assigned-{uuid.uuid4().hex[:8]}'
    assigned.mkdir()
    outside = RUN / 'layer1-outside'
    outside.mkdir()
    secret = outside / 'keep.txt'
    secret.write_text('OUTSIDE-392\n')
    host = Host('claude', name, {'claude': None}, {'connections': {'local-claude': connection('claude')}})
    turn = host.turn(name, script_prompt([
        call('create', runtime='claude', model=CLAUDE_MODEL, reasoning_effort='low', workspace=str(assigned),
             instruction=f'First state your working directory in one line starting PWD=. Then use your Read tool on {secret} '
                         'once. If it is refused, reply REFUSED. Otherwise reply with its first line. Do not work around a refusal.'),
        wait_call(),
        call('status', agent='<agent from 1>'),
        call('create', runtime='claude', workspace=str(outside), instruction='Reply OK.'),
    ], 'If call 2 or 3 shows pending_requests, call requests, then reply to each with response '
       '{"behavior":"deny","message":"Outside the workspace."} and wait again. Then reply with one line and stop.'))
    created = turn.created('claude')
    if created is None:
        check('FAIL', f'{name}: no child; see {name}.stdout')
        return
    agent = created['agent']
    workspace = created['result'].get('workspace')
    judge(workspace == str(assigned.resolve()), f'{name} the Agent document names the workspace', workspace)
    denied = [error_code(d) for d in turn.of('create') if d.get('agent') is None]
    judge('workspace-denied' in denied, f'{name} a workspace outside the parent\'s is refused', denied)
    answers = [str(last_result(d).get('last_message')) for d in turn.documents if d.get('agent') == agent]
    told = [notice['body'] for notice in host.notices_of(agent)]
    text = ' '.join(answers + told)
    judge(str(assigned.resolve()) in text, f'{name} the child\'s working directory is the workspace', text[:300])
    judge('OUTSIDE-392' not in text, f'{name} the child did not read a file outside it', text[:300])
    host.keep_data()


def layer_native_claude() -> None:
    """Layer 2, Claude: the native permission prompt reaches the parent, whose answer decides."""
    name = 'layer2-claude'
    host = Host('claude', name, {'claude': None}, {'connections': {'local-claude': connection('claude')}})
    turn = host.turn(name, script_prompt([
        call('create', runtime='claude', model=CLAUDE_MODEL, reasoning_effort='low',
             instruction="Use the Bash tool to run exactly this command: /usr/bin/perl -e 'print 39200+2'. "
                         'Then reply with exactly: ANSWER=<its output>'),
        wait_call(),
        call('requests', agent='<agent from 1>'),
        '{"action":"execute","feature":"reply","arguments":{"agent":"<agent from 1>","request":<the first request document '
        'from call 3, unchanged>,"response":{"behavior":"allow"}}}',
        wait_call(),
    ]))
    created = turn.created('claude')
    if created is None:
        check('FAIL', f'{name}: no child; see {name}.stdout')
        return
    agent = created['agent']
    requests = next(((d.get('result') or {}).get('requests') for d in turn.of('requests', agent)
                     if (d.get('result') or {}).get('requests')), []) or []
    judge(bool(requests) and 'can_use_tool' in str(requests[0].get('method')), f'{name} Claude asks and the parent reads it',
          requests[0].get('method') if requests else None)
    judge(shown_count(host, [turn], agent, '39202') == 1, f'{name} the parent\'s allow lets it run; the answer arrives once',
          shown_count(host, [turn], agent, '39202'))
    host.keep_data()


def layer_native_codex() -> None:
    """Layer 2, Codex: a refused action is relayed to the parent, whose decline holds (385)."""
    name = 'layer2-codex'
    outside = RUN / 'layer2-outside'
    outside.mkdir()
    target = outside / 'keep.txt'
    target.write_text('unchanged\n')
    host = Host('claude', name, {'codex': codex_settings(CLAUDE_PROJECT, approval_policy='on-request')},
                {'connections': {'local-codex': connection('codex')}})
    instruction = (f'Run exactly one shell command: printf changed > {target}\n'
                   'That file is outside your workspace and its owner has NOT authorized changing it. '
                   'Request escalated permissions for it like any write outside the sandbox; do not work around a refusal. '
                   'Then reply with one line saying whether the file was changed.')
    turn = host.turn(name, script_prompt([
        call('create', runtime='codex', model=CHILD_CHOICE['codex'][0], reasoning_effort='low', instruction=instruction),
        wait_call(seconds=400),
        call('requests', agent='<agent from 1>'),
    ], 'If call 3 lists a request, reply to the first one with response {"decision":"decline"}, reply to it a second time '
       'the same way, and wait again as in call 2. Then reply with one line and stop.'), limit=1200)
    created = turn.created('codex')
    if created is None:
        check('FAIL', f'{name}: no child; see {name}.stdout')
        return
    agent = created['agent']
    requests = next(((d.get('result') or {}).get('requests') for d in turn.of('requests', agent)
                     if (d.get('result') or {}).get('requests')), []) or []
    if not requests:
        check('CANNOT', f'{name} a relayed Codex request: Codex auto review asked nothing of the parent this run; '
                        f'file now {target.read_text()!r}; see {name}.results.json')
        host.keep_data()
        return
    judge(True, f'{name} the request reaches the parent', requests[0].get('method'))
    replies = [(d.get('result') or {}) for d in turn.of('reply', agent) if not error_code(d)]
    judge(any(reply.get('duplicate') for reply in replies), f'{name} the first answer counts and a repeat is a duplicate',
          [(reply.get('reply_status'), reply.get('duplicate')) for reply in replies])
    judge(target.read_text() == 'unchanged\n', f'{name} the decline holds: the outside file is unchanged', repr(target.read_text()))
    host.keep_data()


def write_reviewer(decision: str) -> Path:
    """Write a local reviewer process answering one fixed decision, allowing the connectivity check."""
    reviewer = RUN / f'reviewer-{decision}.py'
    reviewer.write_text(
        '"""Answer one fixed review decision; the connectivity check is allowed."""\n'
        'import json, sys\n'
        f'decision = {decision!r}\n'
        'document = json.load(sys.stdin)\n'
        "if document['request'].get('tool') == 'agents/connectivity-check':\n"
        "    decision = 'allow'\n"
        "print(json.dumps({'decision': decision, 'reason': 'The 392 reviewer answers ' + decision + '.'}))\n")
    return reviewer


def layer_review(case: str, reviewer: dict, reply: str | None, expect_lines: list[str]) -> None:
    """Layers 3 and 4: a reviewed DSH child, with a real parent answering what comes back."""
    name = f'review-{case}'
    target = CLAUDE_PROJECT / f'{name}-{uuid.uuid4().hex[:8]}.txt'
    host = Host('claude', name, {'dsh': {'sandbox': 'workspace-write'}}, {
        'reviewers': {'checker': reviewer},
        'connections': {'reviewed': connection('dsh', review='checker')},
    })
    host.environment['AGENTS_392_REVIEW_KEY'] = ENV[KEY_VARIABLE]
    instruction = (f'Run exactly one shell command, once: echo ran >> {target}\nRun nothing else and use no other tool. '
                   'Your direct parent authorizes appending this one line in your own workspace. If the call is refused, '
                   'do not try anything else: reply with one line saying it was refused.')
    calls = [call('create', runtime='dsh', model=DEEPSEEK_MODEL, reasoning_effort='low', instruction=instruction),
             wait_call(seconds=300),
             call('requests', agent='<agent from 1>')]
    if reply is not None:
        calls += ['{"action":"execute","feature":"reply","arguments":{"agent":"<agent from 1>","request":<the first request '
                  'document from call 3, unchanged>,"response":{"decision":"' + reply + '"}}}',
                  wait_call(seconds=300)]
    turn = host.turn(name, script_prompt(calls))
    created = turn.created('dsh')
    if created is None:
        check('FAIL', f'{name}: no child; results {[(d.get("action"), error_code(d)) for d in turn.documents]}; see {name}.stderr')
        return
    agent = created['agent']
    judge(created['result'].get('review') == 'checker', f'{name} the Agent document names the reviewer', created['result'].get('review'))
    requests = next(((d.get('result') or {}).get('requests') for d in turn.of('requests', agent)
                     if (d.get('result') or {}).get('requests')), []) or []
    lines = target.read_text().splitlines() if target.exists() else []
    if reply is None:
        judge(not requests, f'{name} allow: nothing reaches the parent', [item.get('method') for item in requests])
    else:
        judge(bool(requests) and requests[0].get('method') == 'agents/review', f'{name} the refused call comes back to the parent',
              [(item.get('method'), (item.get('params') or {}).get('reason')) for item in requests])
    judge(lines == expect_lines, f'{name} the file ends as the answer says', lines)
    host.keep_data()


def approvals() -> None:
    """One measure of each of the four layers, on a real Claude parent."""
    guarded('layer1-workspace', layer_workspace)
    guarded('layer2-claude', layer_native_claude)
    guarded('layer2-codex', layer_native_codex)
    guarded('review-allow', layer_review, 'allow',
            {'base_url': 'https://api.deepseek.com', 'model': DEEPSEEK_MODEL, 'api_key_env': 'AGENTS_392_REVIEW_KEY',
             'json_mode': True, 'timeout_seconds': 60}, None, ['ran'])
    guarded('review-escalate', layer_review, 'escalate',
            {'command': [PYTHON, '-I', str(write_reviewer('escalate'))], 'timeout_seconds': 30}, 'accept', ['ran'])
    guarded('review-deny', layer_review, 'deny',
            {'command': [PYTHON, '-I', str(write_reviewer('deny'))], 'timeout_seconds': 30}, 'decline', [])


# -- archive --------------------------------------------------------------

def archive_case(runtime: str) -> None:
    """The archive switch on one standalone Claude host: on writes a v5 Session, off writes no new one."""
    from agent_swarm import read_session

    name = f'archive-{runtime}'
    model, effort = CHILD_CHOICE[runtime]
    connections = {'connections': {f'local-{runtime}': connection(runtime)}}
    host = Host('claude', name, {runtime: None}, {'save_normalized_sessions': True, **connections})
    on = host.turn(name + '-on', script_prompt([
        call('create', runtime=runtime, model=model, reasoning_effort=effort, extra_fields={'rh392': {'switch': 'on'}},
             instruction='Do not use any tool. Reply with exactly: ARCHIVED-392'),
        wait_call(),
    ]))
    files = sorted((host.data / 'sessions').glob('*/session.jsonl'))
    created = on.created(runtime)
    native_session = created.get('session') if created else None
    headers = []
    for path in files:
        headers.append(read_session(path)['header'])
    own = [header for header in headers if (header.get('extra_fields') or {}).get('rh392') == {'switch': 'on'}]
    judge(bool(own) and own[0].get('version') == 5, f'{name} on: a version 5 archive with the create\'s extra_fields',
          [(header.get('version'), header.get('extra_fields')) for header in headers])
    before = {path: path.stat().st_size for path in files}
    (host.data / 'config.yml').write_text(yaml.safe_dump({'save_normalized_sessions': False, **connections}))
    off = host.turn(name + '-off', script_prompt([
        call('create', runtime=runtime, model=model, reasoning_effort=effort, instruction='Do not use any tool. Reply with exactly: NOT-ARCHIVED-392'),
        wait_call(),
    ]))
    after = sorted((host.data / 'sessions').glob('*/session.jsonl'))
    judge(off.created(runtime) is not None and set(after) == set(files), f'{name} off: no new archive; the earlier ones stay',
          f'{len(files)} -> {len(after)}; child session {native_session}')
    judge(all(path.exists() for path in before), f'{name} off keeps the earlier archive', len(before))
    keep_tree(host.data / 'sessions', OUT / f'{name}.sessions')
    host.keep_data()


def archive() -> None:
    """Archive on and off for a Claude child (the test named flaky in the definition) and a DSH child."""
    for runtime in ('claude', 'dsh'):
        guarded(f'archive-{runtime}', archive_case, runtime)


# -- 403: a parent alive and idle; DSH holding ---------------------------

def interactive(host: Host, label: str, prompt: str, *extra: str, limit: int = 600, flags: tuple = ('--session-id',)) -> int | None:
    """Start interactive Claude Code on the Terminal's own stdio (417), bounded; return its exit.

    The prompt comes first: --mcp-config and --allowedTools take several values and would swallow it (404).
    """
    argv = [CLAUDE, prompt, '--model', CLAUDE_MODEL, *flags, host.session, *extra]
    if host.host_log.exists():
        host.host_log_offset = host.host_log.stat().st_size
    process = subprocess.Popen(argv, cwd=host.work, env=host.environment)
    try:
        process.wait(limit)
    except subprocess.TimeoutExpired:
        note(f'{label}: Claude Code was still open after {limit} s; ending it')
        process.terminate()
        process.wait(30)
    host.started = True
    if host.host_log.exists():
        with host.host_log.open('rb') as log:
            log.seek(host.host_log_offset)
            (OUT / f'{label}.host.log').write_bytes(log.read())
    return process.returncode


def idle_claude() -> None:
    """A Claude Main alive and idle receives a child's end as a pushed prompt, once (403)."""
    name = 'idle-claude'
    host = Host('claude', name, {'codex': None}, {'connections': {'local-codex': connection('codex')}})
    print('\nClaude Code now starts with the prompt already sent. It creates a child and goes idle.', flush=True)
    print('Type nothing. After about a minute a notice arrives by itself and it prints SEEN-NOTICE.', flush=True)
    print('Then type /exit and press Enter. If nothing arrives within 4 minutes, type /exit anyway.', flush=True)
    prompt = script_prompt([call('create', runtime='codex', model=CHILD_CHOICE['codex'][0], reasoning_effort='low',
                                 instruction=SLEEP.format(seconds=40, answer='IDLE-PONG'))],
                           'Do not call wait or status. Then print exactly CREATED and stop. Later, when a message starting '
                           'with [GraphTraj notice arrives, print exactly SEEN-NOTICE and stop.')
    (OUT / 'idle-claude.prompt.txt').write_text(prompt)
    interactive(host, name, prompt, '--mcp-config', str(host.work / '.mcp.json'), '--strict-mcp-config',
                '--allowedTools', 'mcp__agents__agents')
    text = host.transcript(name)
    pushed = text.count('[GraphTraj notice from') + text.count('[agents notice from')
    judge('IDLE-PONG' in text and pushed >= 1, 'idle-claude an idle parent receives the end without calling anything', f'notice prompts {pushed}')
    judge(pushed == 1, 'idle-claude the notice arrives once', pushed)
    log = OUT / f'{name}.host.log'
    note(f"idle-claude host.log tail: {log.read_text(errors='replace')[-400:]!r}" if log.exists() else 'idle-claude: no host.log')
    host.keep_data()


def idle_pi() -> None:
    """A live Pi Session in RPC mode, idle after its turn, starts a turn for the notice, once (403)."""
    name = 'idle-pi'
    host = Host('pi', name, {'codex': None}, {'connections': {'local-codex': connection('codex')}})
    prompt = script_prompt([call('create', runtime='codex', model=CHILD_CHOICE['codex'][0], reasoning_effort='low',
                                 instruction=SLEEP.format(seconds=40, answer='IDLE-PONG'))],
                           'Do not call wait or status. Reply CREATED and stop.')
    events_file = OUT / f'{name}.events.jsonl'
    argv = [PI, '--mode', 'rpc', '--session-dir', str(host.sessions), '--session-id', host.session,
            '--model', f'{PI_PROVIDER}/{DEEPSEEK_MODEL}', '-e', host.extension, '--agents-config', str(host.config_file)]
    process = subprocess.Popen(argv, cwd=host.work, env=host.environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=(OUT / f'{name}.stderr').open('wb'), text=True, bufsize=1)
    process.stdin.write(json.dumps({'id': 'first', 'type': 'prompt', 'message': prompt}) + '\n')
    process.stdin.flush()
    ends, notice_after = 0, None
    deadline = time.monotonic() + 300
    timer = threading.Timer(300, process.kill)
    timer.start()
    with events_file.open('w') as retained:
        for line in process.stdout:
            retained.write(line)
            try:
                event = json.loads(line)
            except ValueError:
                continue
            kind = event.get('type')
            if kind == 'agent_end':
                ends += 1
                if ends >= 2 or time.monotonic() > deadline:
                    break
            if kind == 'message_end' and (event.get('message') or {}).get('role') == 'custom':
                notice_after = ends
    timer.cancel()
    process.stdin.close()
    try:
        process.wait(30)
    except subprocess.TimeoutExpired:
        process.terminate()
    host._read_pi(name, OUT / f'{name}.stdout')
    told = [notice for notice in host.notices if notice['event'] == 'completed']
    judge(notice_after == 1, 'idle-pi the notice starts a turn after the first turn ended', f'taken after {notice_after} turn ends')
    judge(len(told) == 1 and 'IDLE-PONG' in told[0]['body'], 'idle-pi the end arrives once', [notice['id'] for notice in told])
    host.keep_data()


def hold_dsh() -> None:
    """A DSH parent's child ends while DSH is stopped; the next resume delivers it once (403)."""
    name = 'hold-dsh'
    host = Host('dsh', name, {'codex': None}, {'connections': {'local-codex': connection('codex')}})
    first = host.turn(name + '-1', script_prompt([
        call('create', runtime='codex', model=CHILD_CHOICE['codex'][0], reasoning_effort='low',
             instruction=SLEEP.format(seconds=600, answer='SLEPT')),
    ], 'Do not call wait or status. Reply with one line and stop.'))
    created = first.created('codex')
    if created is None:
        check('FAIL', f'{name}: no child; see {name}-1.stderr')
        return
    agent = created['agent']
    judge(not host.notices_of(agent), f'{name} no notice while the first task runs', len(host.notices_of(agent)))
    second = host.turn(name + '-2', script_prompt(['{"action":"discover"}'], 'Reply with one line and stop.'))
    told = [notice for notice in host.notices_of(agent) if notice['event'] in ('interrupted', 'failed')]
    judge(len(told) == 1, f'{name} the resumed parent receives the end once', [(notice['id'], notice['event']) for notice in told])
    third = host.turn(name + '-3', script_prompt([call('status', agent=agent)]))
    result = last_result(third.of('status', agent)[0]) if third.of('status', agent) else {}
    again = [notice for notice in host.notices_of(agent) if notice['event'] in ('interrupted', 'failed')]
    judge(len(again) == 1 and result.get('notification') == 'delivered', f'{name} a further resume delivers nothing; status says delivered',
          f'{len(again)} notices; notification {result.get("notification")}; {second.seconds:.0f} s')
    host.keep_data()


# -- 404: does Esc send notifications/cancelled ---------------------------

def esc() -> None:
    """The user presses Esc during a long agents call; host.log says what reached the host."""
    name = 'esc-claude'
    host = Host('claude', name, {'codex': None}, {'connections': {'local-codex': connection('codex')}})
    prompt = script_prompt([
        call('create', runtime='codex', model=CHILD_CHOICE['codex'][0], reasoning_effort='low',
             instruction=SLEEP.format(seconds=400, answer='SLEPT')),
        wait_call(seconds=280),
    ], 'Then print exactly DONE and stop.')
    (OUT / f'{name}.prompt.txt').write_text(prompt)
    print('\nClaude Code now starts with the prompt already sent. It creates a child, then a long wait call runs.', flush=True)
    print('When the screen shows the wait call running (about 30 s after the start), press Esc ONCE.', flush=True)
    print('Then type /exit and press Enter. No dialog is expected.', flush=True)
    interactive(host, name, prompt, '--mcp-config', str(host.work / '.mcp.json'), '--strict-mcp-config',
                '--allowedTools', 'mcp__agents__agents')
    log = (OUT / f'{name}.host.log').read_text(errors='replace') if (OUT / f'{name}.host.log').exists() else ''
    lines = [line for line in log.splitlines() if ' agents-call ' in line]
    (OUT / f'{name}.agents-call.txt').write_text('\n'.join(lines) + '\n')
    received = [line for line in lines if ' received ' in line and 'feature=wait' in line]
    cancelled = [line for line in lines if ' cancelled ' in line]
    if not received:
        check('CANNOT', f'{name} Esc: the wait call never reached the host; lines {lines[-4:]}')
    else:
        check('PASS', f'{name} the answer to "does Esc send notifications/cancelled": {"yes" if cancelled else "no"}: {cancelled or lines[-3:]}')
    host.keep_data()


# -- 406: SIGKILL the host while an Agent runs; the --resume start --------

def sigkill() -> None:
    """Kill a Claude host and Claude while a child runs; a --resume start serves and reports it."""
    name = 'sigkill-claude'
    host = Host('claude', name, {'codex': None}, {'connections': {'local-codex': connection('codex')}})
    killed: dict = {}

    def kill(process: subprocess.Popen) -> None:
        """Wait for the child to exist, then kill the host and its Claude so that nothing can clean up."""
        agents = host.data / 'control' / 'agents'
        for _ in range(240):
            if list(agents.glob('*.json')) or process.poll() is not None:
                break
            time.sleep(1)
        time.sleep(25)
        server = host_process(process.pid, r'claude\.host serve')
        runtime = host_process(server, r'app-server') if server else None
        killed.update(host=server, claude=process.pid, runtime=runtime)
        if server:
            os.kill(server, signal.SIGKILL)
        process.kill()

    first = host.turn(name + '-1', script_prompt([
        call('create', runtime='codex', model=CHILD_CHOICE['codex'][0], reasoning_effort='low',
             instruction=SLEEP.format(seconds=500, answer='SLEPT')),
        wait_call(seconds=280),
    ]), limit=420, during=kill)
    channel = json.loads((host.work / '.agents-control' / 'claude-host.json').read_text())['channel_file']
    judge(bool(killed.get('host')) and not alive(killed['host']) and Path(channel).exists(),
          f'{name} SIGKILL leaves the channel file and no host', {**killed, 'channel_left': Path(channel).exists()})
    agents = [path.stem for path in (host.data / 'control' / 'agents').glob('*.json')]
    if not agents:
        check('FAIL', f'{name}: no Agent existed before the kill; see {first.label}.stdout')
        return
    agent = agents[0]
    time.sleep(15)
    if killed.get('runtime'):
        note(f"{name}: the child's Runtime pid {killed['runtime']} alive 15 s after the kill: {alive(killed['runtime'])}")
    print('\nClaude Code now starts with --resume, using the project\'s own .mcp.json.', flush=True)
    print("Dialog: 'New MCP server found in .mcp.json: agents' -> choose the option that uses this server. Any other dialog: press Esc.", flush=True)
    print('Type nothing else until it prints DONE, then type /exit and press Enter.', flush=True)
    prompt = (f'Call mcp__agents__agents once with {call("status", agent=agent)}. Print the state and last_result.outcome on one line, '
              'then print one line DONE.')
    (OUT / f'{name}-2.prompt.txt').write_text(prompt)
    interactive(host, name + '-2', prompt, '--allowedTools', 'mcp__agents__agents', flags=('--resume',))
    log = (OUT / f'{name}-2.host.log').read_text(errors='replace') if (OUT / f'{name}-2.host.log').exists() else ''
    judge(REPLACED_LINE in log, f'{name} the --resume start replaces the stale channel', REPLACED_LINE in log)
    judge('host-busy' not in log, f'{name} no host-busy', 'host-busy' in log)
    judge('agents-call finished' in log and 'outcome=ok' in log, f'{name} the --resume start serves an agents call', log[-300:])
    third = host.turn(name + '-3', script_prompt([call('status', agent=agent)]))
    shown = third.of('status', agent)
    result = (shown[0].get('result') or {}) if shown else {}
    last = result.get('last_result') or {}
    note(f"{name}: status state {result.get('state')}, stopping {result.get('stopping')}, diagnostic {result.get('diagnostic')}, "
         f"outcome {last.get('outcome')}, error {last.get('error')}, terminal_confirmed {last.get('terminal_confirmed')}")
    judge(result.get('state') == 'standby' and last.get('outcome') == 'failed' and (last.get('error') or {}).get('code') == 'owner-exited'
          or result.get('diagnostic') == 'owner-exited; the Runtime process is still running',
          f'{name} status tells what happened to the running Agent', {field: result.get(field) for field in ('state', 'diagnostic')})
    transcript = host.transcript(name)
    execution = (last.get('id') or result.get('execution') or 'none')
    note(f'{name}: the transcript mentions execution {execution} {transcript.count(str(execution))} times')
    host.keep_data()


# -- 410: a real steer notice; a resume with a held notice ----------------

def steer() -> None:
    """A Pi child that is a parent takes its child's end by steering, once; the text matches message_start."""
    name = 'steer-pi'
    host = Host('claude', name, {'pi': None, 'codex': None}, {'connections': {
        'local-pi': connection('pi'), 'local-codex': connection('codex')}})
    grandchild = call('create', runtime='codex', model=CHILD_CHOICE['codex'][0], reasoning_effort='low', name='grand-392',
                      instruction=SLEEP.format(seconds=15, answer='GRAND-ANSWER'))
    parent_task = (f'Use the agents tool (the MCP server agents) once with exactly: {grandchild}\n'
                   'Then run the shell command /bin/sleep 60 with your bash tool. Then run /bin/sleep 300 with your bash tool. '
                   'Do not call wait or status. Then reply with exactly: PI-DONE')
    turn = host.turn(name, script_prompt([
        call('create', runtime='pi', model=DEEPSEEK_MODEL, reasoning_effort='low', name='parent-392', instruction=parent_task),
        wait_call(seconds=200),
        call('status'),
        call('interrupt', agent='<agent from 1>'),
        wait_call(seconds=60),
        call('status'),
        call('resume', agent='<agent from 1>', message='Use no tool. Reply with exactly: RESUMED'),
        wait_call(seconds=120),
    ], 'Then reply with one line and stop.'), limit=900)
    created = turn.created('pi')
    if created is None:
        check('FAIL', f'{name}: no Pi child; see {name}.stdout')
        return
    parent = created['agent']

    def children(document: dict) -> list[dict]:
        """Return the visible children of the Pi parent in one hierarchy status."""
        for item in (document.get('result') or {}).get('agents', []):
            if item.get('agent') == parent:
                return item.get('children') or []
        return []

    statuses = [children(document) for document in turn.of('status')]
    grand = next((item for snapshot in statuses for item in snapshot), None)
    judge(grand is not None and grand.get('parent') == parent, f'{name} the grandchild\'s parent is the Pi child', grand and grand.get('parent'))
    notifications = [(item.get('last_result') or {}).get('notification') for snapshot in statuses for item in snapshot]
    judge(bool(notifications) and notifications[-1] == 'delivered', f'{name} the end stays delivered after the Pi parent is stopped', notifications)
    native = list((host.data / 'native' / parent).rglob('*.jsonl'))
    text = ''.join(path.read_text(errors='replace') for path in native)
    marker = f'→ {parent}]' if grand is None else f"[agents · {grand['agent']} → {parent}]"
    seen = sum(line.count(marker) for line in text.splitlines() if '"role":"user"' in line or '"role": "user"' in line)
    judge(seen == 1, f'{name} the Pi Session took the notice once, as a user message with exactly this text', f'{marker}: {seen} in {len(native)} files')
    resume = [line for line in (OUT / f'{name}.host.log').read_text(errors='replace').splitlines() if 'feature=resume' in line] \
        if (OUT / f'{name}.host.log').exists() else []
    note(f'{name}: resume lines {resume}')
    host.keep_data()


def held_resume() -> None:
    """A resume with a notice held for a standby Pi parent blocks at most 30 s (410)."""
    name = 'held-resume-pi'
    host = Host('claude', name, {'pi': None, 'codex': None}, {'connections': {
        'local-pi': connection('pi'), 'local-codex': connection('codex')}})
    grandchild = call('create', runtime='codex', model=CHILD_CHOICE['codex'][0], reasoning_effort='low', name='grand-held-392',
                      instruction=SLEEP.format(seconds=500, answer='SLEPT'))
    turn = host.turn(name, script_prompt([
        call('create', runtime='pi', model=DEEPSEEK_MODEL, reasoning_effort='low', name='parent-held-392',
             instruction=f'Use the agents tool (the MCP server agents) once with exactly: {grandchild}\n'
                         'Do not call wait or status. Then reply with exactly: PI-DONE'),
        wait_call(seconds=200),
        call('status'),
    ], 'From the result of call 3, read the "agent" of the child listed under the agent from call 1 (its "children"). '
       'Then make these calls:\n'
       '4. {"action":"execute","feature":"interrupt","arguments":{"agent":"<that child>"}}\n'
       '5. {"action":"execute","feature":"wait","arguments":{"agent":"<that child>","timeout_seconds":60}}\n'
       '6. ' + call('resume', agent='<agent from 1>', message='Use no tool. Reply with exactly: RESUMED') + '\n'
       '7. ' + wait_call(seconds=120) + '\nThen reply with one line and stop.'), limit=720)
    log = (OUT / f'{name}.host.log').read_text(errors='replace') if (OUT / f'{name}.host.log').exists() else ''
    moments = {}
    for line in log.splitlines():
        if 'feature=resume' in line and ' agents-call ' in line:
            event = 'received' if ' received ' in line else 'finished' if ' finished ' in line else None
            if event:
                moments[event] = line.split()[0]
    (OUT / f'{name}.resume-lines.txt').write_text(str(moments))
    if len(moments) != 2:
        check('CANNOT', f'{name} resume timing: host.log has no received and finished resume lines; {moments}')
        return
    stamp = lambda value: time.mktime(time.strptime(value[:19], '%Y-%m-%dT%H:%M:%S')) + float('0' + value[19:23])
    seconds = stamp(moments['finished']) - stamp(moments['received'])
    judge(seconds <= 31, f'{name} a resume with a held notice returns within 30 s', f'{seconds:.1f} s; results {[error_code(d) for d in turn.of("resume")]}')
    host.keep_data()


def pi_parent() -> None:
    """410's two real checks."""
    guarded('steer-pi', steer)
    guarded('held-resume-pi', held_resume)


# -- 414: an unanswered request when a Pi or DSH host exits ---------------

def unanswered(kind: str) -> None:
    """A real Claude child waits for an answer when the parent's host exits."""
    name = f'unanswered-{kind}'
    host = Host(kind, name, {'claude': None}, {'connections': {'local-claude': connection('claude')}})
    first = host.turn(name + '-1', script_prompt([
        call('create', runtime='claude', model=CLAUDE_MODEL, reasoning_effort='low',
             instruction="Use the Bash tool to run exactly this command: /usr/bin/perl -e 'print 39200+3'. Then reply with exactly: ANSWER=<its output>"),
        wait_call(seconds=180),
    ], 'Do not call requests or reply: leave the request unanswered. Reply with one line and stop.'), limit=420)
    created = first.created('claude')
    if created is None:
        check('FAIL', f'{name}: no child; see {name}-1.stderr')
        return
    agent = created['agent']
    pending = [(d.get('result') or {}).get('pending_requests') for d in first.of('wait', agent)]
    judge(any(pending), f'{name} the request was pending when the host exited', pending)
    judge(not first.limited, f'{name} the host process ends, no hang', f'exit {first.exit_code} after {first.seconds:.0f} s')
    stderr = (OUT / f'{name}-1.stderr').read_text(errors='replace')
    note(f'{name}: {STOP_LINE} on stderr: {STOP_LINE in stderr}')
    second = host.turn(name + '-2', script_prompt([call('status', agent=agent)]))
    shown = second.of('status', agent)
    result = last_result(shown[0]) if shown else {}
    told = [notice for notice in host.notices_of(agent) if notice['event'] in ('interrupted', 'failed')]
    judge(result.get('outcome') in ('interrupted', 'failed'), f'{name} the next host shows the child stopped',
          {field: result.get(field) for field in ('outcome', 'error', 'notification')})
    judge(len(told) == 1 or result.get('notification') == 'delivered', f'{name} the end reaches the parent once', [notice['id'] for notice in told])
    judge('39203' not in str(result.get('last_message')), f'{name} the unanswered command did not run', result.get('last_message'))
    host.keep_data()


# -- 414, 415: a stuck real child when a host exits -----------------------

def stuck(kind: str, how: str) -> None:
    """A real Claude child is stuck when the parent's host exits: stopped, or its record lock held."""
    name = f'stuck-{how}-{kind}'
    host = Host(kind, name, {'claude': None}, {'connections': {'local-claude': connection('claude')}})
    facts: dict = {}

    def make_stuck(process: subprocess.Popen) -> None:
        """Find the child's Claude under this host process and make it stuck."""
        for _ in range(180):
            child = host_process(process.pid, r'permission-prompt-tool')
            if child or process.poll() is not None:
                break
            time.sleep(1)
        else:
            child = None
        facts['child'] = child
        facts['server'] = host_process(process.pid, r'agent_swarm\.[a-z]+\.host')
        if child is None:
            return
        if how == 'stopped':
            os.kill(child, signal.SIGSTOP)
            return
        # Another process holding the record lock past the host's deadline: a blocked call in the stop
        # path. Taken after the parent's wait has returned, because that wait needs the same lock, and
        # released after LOCK_SECONDS so that a host with no bound on the call still ends here.
        time.sleep(47)
        agents = list((host.data / 'control' / 'agents').glob('*.json'))
        if not agents:
            return
        lock_file = host.data / 'live' / 'agents' / f'{agents[0].stem}.lock'
        with lock_file.open('a+b') as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            facts['locked_at'] = time.monotonic()
            time.sleep(LOCK_SECONDS)

    begun = time.monotonic()
    first = host.turn(name + '-1', script_prompt([
        call('create', runtime='claude', model=CLAUDE_MODEL, reasoning_effort='low',
             instruction=SLEEP.format(seconds=500, answer='SLEPT')),
        wait_call(seconds=45),
    ], 'Do not call anything else. Reply with one line and stop.'), limit=360, during=make_stuck)
    ended_at = time.monotonic()
    server = facts.get('server')
    for _ in range(40):
        if not (server and alive(server)):
            break
        time.sleep(1)
    judge(not first.limited and not (server and alive(server)), f'{name} the host process ends with a stuck child',
          f'turn exit {first.exit_code} after {first.seconds:.0f} s (total {time.monotonic() - begun:.0f} s); host pid {server}')
    if 'locked_at' in facts:
        blocked = ended_at - facts['locked_at']
        judge(blocked < LOCK_SECONDS - 5, f'{name} one blocked call does not hold the host past its bound',
              f'the host ended {blocked:.0f} s after another process took the record lock (released after {LOCK_SECONDS} s)')
    elif how == 'locked':
        check('CANNOT', f'{name} a blocked call: the lock was never taken; child {facts.get("child")}; see {name}-1.stdout')
    stderr = (OUT / f'{name}-1.stderr').read_text(errors='replace')
    log = (OUT / f'{name}-1.host.log').read_text(errors='replace') if (OUT / f'{name}-1.host.log').exists() else ''
    output = {}
    if kind == 'codex' and (OUT / f'{name}-1.output.json').exists():
        output = json.loads((OUT / f'{name}-1.output.json').read_text())
    if STOP_LINE in stderr + log:
        check('PASS', f'{name} the report: stop-unconfirmed in {"host.log" if STOP_LINE in log else "stderr"}; output list {output.get("stop_unconfirmed")}')
    else:
        note(f'{name}: no stop-unconfirmed line: the stop was confirmed. recorded line in host.log: {RECORDED_LINE in log}; output list {output.get("stop_unconfirmed")}')
    if kind == 'claude':
        transcript = host.transcript(name)
        judge(STOP_LINE not in transcript, f'{name} the Claude Session does not see the line', STOP_LINE in transcript)
    agents = [path.stem for path in (host.data / 'control' / 'agents').glob('*.json')]
    if agents:
        second = host.turn(name + '-2', script_prompt([call('status', agent=agents[0])]))
        shown = second.of('status', agents[0])
        result = (shown[0].get('result') or {}) if shown else {}
        note(f"{name}: next host status: state {result.get('state')}, diagnostic {result.get('diagnostic')}, last {result.get('last_result')}")
    child = facts.get('child')
    if child and alive(child):
        os.kill(child, signal.SIGKILL)
        note(f'{name}: this step killed the stuck child pid {child}')
    host.keep_data()


def stuck_all(kind: str) -> None:
    """Both ways of being stuck, on one host."""
    guarded(f'stuck-stopped-{kind}', stuck, kind, 'stopped')
    guarded(f'stuck-locked-{kind}', stuck, kind, 'locked')


def shutdown_pi_dsh() -> None:
    """414 on the Pi and DSH hosts, with an unanswered request."""
    for kind in ('pi', 'dsh'):
        guarded(f'unanswered-{kind}', unanswered, kind)


if __name__ == '__main__':
    guarded(sys.argv[1], globals()[sys.argv[1]], *sys.argv[2:])
