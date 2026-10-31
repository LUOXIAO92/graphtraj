"""A closing Claude or Codex host tries every child, reports the unconfirmed ones and ends (415).

Each test runs a host's real entry point in its own process: the agents and
GraphTraj Claude hosts' ``main()`` over a real MCP stdio, and the Codex host's
``main()`` under the controlled peer. Only the driver is fake, and the children
come through the real tool path. No network, no real model, no real Runtime.

The drivers' ``own`` threads inherit ``daemon`` from whoever starts them, and a
real MCP call thread is a daemon. The fake sets ``daemon=False``, the worst case,
so a process that relied on the thread ending would hang here.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'src'
PEER = Path(__file__).with_name('codex_stdio_peer.py')
SESSION = '11111111-1111-4111-8111-111111111111'
KINDS = ['agents-claude', 'graphtraj-claude', 'codex']
CLAUDE_KINDS = KINDS[:2]
# How long a host process may take to end, its 10-second stop included.
HOST_LIMIT = 25
RECORDED = 'agents host recorded its children stopped.'

HOST = r'''
import faulthandler, importlib, json, os, subprocess, sys, threading, time
from pathlib import Path

where, kind, case = Path(os.environ['TEST_WHERE']), os.environ['TEST_KIND'], os.environ['TEST_CASE']
faulthandler.dump_traceback_later(HOST_LIMIT - 3, file=open(where / f'dump-{os.getpid()}.txt', 'w'))

import agent_swarm
from agent_swarm import Caller, bind, handle_request, shutdown

shutdown.STOP_SECONDS = float(os.environ.get('TEST_STOP_SECONDS', shutdown.STOP_SECONDS))
SESSION = os.environ['TEST_SESSION']


def write_atomically(path, text):
    """Replace ``path`` whole, because the test polls it."""
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(text)
    os.replace(temporary, path)


class Driver:
    """Owns each execution on a non-daemon thread and misbehaves on the chosen Agent."""

    def __init__(self):
        self.stops, self.attempts = {}, {}
        self.lock = threading.Lock()
        self.facts = {'module': agent_swarm.__file__, 'agents': []}

    def prepare(self, runtime, caller, **options):
        return {'runtime': runtime}

    def require_available(self, connection):
        pass

    def start(self, run):
        run.events.session('native-' + run.agent[-6:])
        stop = self.stops[run.agent] = threading.Event()

        def own():
            stop.wait()
            run.events.finished('interrupted', last_message='partial work')

        threading.Thread(target=own, name=f'test-{run.agent}', daemon=False).start()
        if case == 'runtime':
            survivor = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            run.events.process(runtime_pid=survivor.pid)
            self.facts.setdefault('survivors', []).append(survivor.pid)
        if case == 'garbage':
            (run.directory.parents[1] / 'control' / 'agents' / 'aaaa-garbage.json').write_text('not json')
        with self.lock:
            self.facts['root'] = str(run.directory.parents[1])
            self.facts['agents'].append(run.agent)
            write_atomically(where / 'facts.json', json.dumps(self.facts))

    def chosen(self, agent):
        """Whether ``agent`` is the one that misbehaves, by its place in the stop order."""
        order = sorted(self.stops)
        position = os.environ.get('TEST_TARGET', 'first')
        return position == 'all' or agent == order[{'first': 0, 'last': -1}[position]]

    def interrupt(self, run):
        count = self.attempts[run.agent] = self.attempts.get(run.agent, 0) + 1
        with (where / 'interrupts.log').open('a') as stream:
            stream.write(run.agent + '\n')
        if self.chosen(run.agent):
            if case == 'raises' or (case == 'raises-once' and count == 1):
                raise RuntimeError('driver broke')
            if case in ('stuck', 'runtime'):
                return True
            if case == 'blocked':
                threading.Event().wait()
        threading.Timer(0.2, self.stops[run.agent].set).start()
        return True

    def requests(self, run):
        return []

    def reply(self, run, request, response):
        return {}


driver = Driver()

if kind == 'agents-claude':
    host = importlib.import_module('agent_swarm.claude.host')
    host.native_parent = lambda *_, **__: os.getppid()
    host.runtime_drivers = lambda *_: {'claude': driver}
    real_calls, made = host.IndependentCalls, []
    host.IndependentCalls = lambda *arguments: made.append(real_calls(*arguments)) or made[-1]
    real_serve = host.serve_concurrent

    def serve(*arguments):
        """The Main's association comes from the native mod; everything after it is real."""
        call = made[0].make_call(SESSION, Path.cwd())
        made[0].call = lambda request: call('agents', request)
        real_serve(*arguments)

    host.serve_concurrent = serve
    sys.argv = ['host', 'serve', '--config', str(where / 'config.json')]
elif kind == 'graphtraj-claude':
    host = importlib.import_module('graphtraj.runtimes.claude.host')
    host.native_parent = lambda *_, **__: os.getppid()
    real_agents, made = host.GraphTrajAgents, []

    def agents(*arguments):
        """The real GraphTraj view with the fake driver in place of its Adapter."""
        made.append(real_agents(*arguments))
        made[-1].control.drivers = {'claude': driver}
        return made[-1]

    host.GraphTrajAgents = agents
    real_serve = host.serve

    def serve(*arguments, **options):
        """As above, for the GraphTraj association."""
        call = bind(made[0].control, Caller('claude-native', None, SESSION, 'claude'))
        options['native_call'] = lambda request, tool='agents': handle_request(request, call)
        real_serve(*arguments, **options)

    host.serve = serve
    sys.argv = ['host', 'serve', '--config', str(where / 'config.json')]
else:
    host = importlib.import_module('agent_swarm.codex.host')
    host.runtime_drivers = lambda settings, root: settings.pop('runtimes', None) or {'claude': driver}
    if os.environ.get('TEST_RUN_RAISES'):
        base = host.CodexManagedExecution.run
        errors = {'runtime': RuntimeError, 'known': OSError}

        def raising(self):
            """The native run ends, then fails."""
            base(self)
            raise errors[os.environ['TEST_RUN_RAISES']]('the run failed')

        host.CodexManagedExecution.run = raising
    if os.environ.get('TEST_HOLD_SECONDS'):
        real_host = host.CodexHost

        def held(*arguments):
            """Stay in the resumed parent turn long enough to receive what was held, then end it."""
            made = real_host(*arguments)
            timer = threading.Timer(float(os.environ['TEST_HOLD_SECONDS']), made.terminate)
            timer.daemon = True
            timer.start()
            return made

        host.CodexHost = held
    if os.environ.get('TEST_LIBRARY'):
        made = host.CodexHost(json.loads((where / 'settings.json').read_text()), where / 'data', 'mcp-requests')
        (where / 'library.json').write_text(json.dumps(made.run()))
        # The caller's process is still running; only this script's own end skips the stuck thread.
        os._exit(0)
    sys.argv = ['host', '--settings', str(where / 'settings.json'), '--directory', str(where / 'data'),
                '--output', str(where / os.environ['TEST_OUTPUT']), *os.environ['TEST_ARGUMENTS'].split(),
                os.environ['TEST_INSTRUCTION']]
host.main()
'''.replace('HOST_LIMIT', str(HOST_LIMIT))


@dataclass
class Host:
    """What one host process did."""

    returncode: int
    seconds: float
    stdout: str
    stderr: str
    report: str
    facts: dict
    where: Path
    replies: list[dict]

    @property
    def agents(self) -> list[str]:
        """The children, in the order the host stops them."""
        return sorted(self.facts['agents'])

    @property
    def interrupted(self) -> list[str]:
        """Every interrupt attempt, in order."""
        path = self.where / 'interrupts.log'
        return path.read_text().splitlines() if path.exists() else []

    def record(self, agent: str) -> dict:
        """The last execution as written, with nothing reconciling it first."""
        record = json.loads((Path(self.facts['root']) / 'control' / 'agents' / f'{agent}.json').read_text())
        return record['executions'][-1]


def tool_call(identity: int, feature: str, **arguments: object) -> dict:
    """One real MCP ``tools/call`` of the agents tool."""
    return {'jsonrpc': '2.0', 'id': identity, 'method': 'tools/call',
            'params': {'name': 'agents', 'arguments': {'action': 'execute', 'feature': feature, 'arguments': arguments}}}


# Not status: a result that shows an end settles it, so no notice would be attached.
DISCOVER = [{'jsonrpc': '2.0', 'id': 20, 'method': 'tools/call',
             'params': {'name': 'agents', 'arguments': {'action': 'discover'}}}]
CREATES = [tool_call(10 + number, 'create', runtime='claude', instruction='work') for number in range(3)]


def locate(kind: str, tmp_path: Path) -> tuple[Path, Path, Path | None]:
    """Write the host's configuration; return its working directory, its files and its log."""
    project = tmp_path / 'project'
    if kind == 'agents-claude':
        where = project / 'host'
        document = {'root': str(where / 'data'), 'cwd': str(project), 'claude': sys.executable,
                    'channel_file': str(where / 'control' / 'live' / 'channel.json'), 'settings': {}}
        log = where / 'control' / 'host.log'
    elif kind == 'graphtraj-claude':
        where = project / '.graphtraj' / 'claude-host'
        document = {'root': str(project), 'cwd': str(project), 'claude': sys.executable,
                    'channel_file': str(where / 'live' / 'channel.json')}
        log = where / 'host.log'
    else:
        where = project
        document = {'adapter_request': {
            'arguments': [str(tmp_path / 'codex')], 'worktree_path': str(project),
            'session_parameters': {'cwd': str(project), 'model': 'chosen-model',
                                   'developerInstructions': 'Retain native settings.',
                                   'config': {'default_permissions': 'chosen', 'permissions': {
                                       'chosen': {'extends': ':workspace', 'filesystem': {str(project): 'write'}}}}},
        }}
        log = None
        peer = tmp_path / 'codex'
        peer.write_text('#!' + sys.executable + '\n' + PEER.read_text())
        peer.chmod(0o755)
    where.mkdir(parents=True, exist_ok=True)
    (where / ('settings.json' if kind == 'codex' else 'config.json')).write_text(json.dumps(document))
    return project, where, log


def wait_for(check, seconds: float = 15.0) -> None:
    """Poll until ``check()`` is true, failing the test otherwise."""
    deadline = time.monotonic() + seconds
    while not check():
        assert time.monotonic() < deadline, 'condition not reached'
        time.sleep(0.02)


def run_host(
    kind: str,
    tmp_path: Path,
    case: str = 'clean',
    target: str = 'first',
    stop_seconds: float | None = 1.0,
    requests: list[dict] = CREATES,
    end: str = 'eof',
    **variables: str,
) -> Host:
    """Run one host process to its end, within ``HOST_LIMIT``, and collect what it did.

    A Claude host receives ``requests`` over MCP and is then closed by ``end``:
    EOF, or SIGINT as Claude Code does. The Codex host's parent turn makes them
    through the peer's MCP entry and ends by itself. A second run on the same
    ``tmp_path`` is the next host for the same Session.
    """
    project, where, log = locate(kind, tmp_path)
    script = tmp_path / 'run-host.py'
    script.write_text(HOST)
    for stale in ('facts.json', 'interrupts.log'):
        (where / stale).unlink(missing_ok=True)
    # Built, not copied: nothing of the real environment reaches this process or its output.
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path), 'PYTHONPATH': str(SOURCE), 'TEST_KIND': kind,
           'TEST_WHERE': str(where), 'TEST_CASE': case, 'TEST_TARGET': target, 'TEST_SESSION': SESSION,
           'PEER_NATIVE_ROLLOUT': str(tmp_path / 'native'), 'PEER_HOST_EVENTS': str(tmp_path / 'host-events.jsonl'),
           'PEER_MCP_REQUESTS': json.dumps(requests), 'TEST_OUTPUT': 'output.json', 'TEST_ARGUMENTS': '',
           'TEST_INSTRUCTION': 'mcp-requests', **variables}
    if stop_seconds is not None:
        env['TEST_STOP_SECONDS'] = str(stop_seconds)
    began = time.monotonic()
    process = subprocess.Popen([sys.executable, str(script)], cwd=project, env=env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
                               preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
    # Ends a read that is waiting for a host that never answers.
    watchdog = threading.Timer(HOST_LIMIT, process.kill)
    watchdog.start()
    read: list[str] = []
    try:
        if kind != 'codex':
            messages = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}}, *requests]
            process.stdin.write(''.join(json.dumps(message) + '\n' for message in messages))
            process.stdin.flush()
            if requests is CREATES:
                wait_for(lambda: (where / 'facts.json').exists()
                         and len(json.loads((where / 'facts.json').read_text())['agents']) == 3)
            else:
                # A result sent to a client already gone is given back, so stay until it is read.
                while (line := process.stdout.readline()) and json.loads(line)['id'] != requests[-1]['id']:
                    read.append(line)
                read.append(line)
                time.sleep(0.3)
            if end == 'sigint':
                process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=HOST_LIMIT)
    except subprocess.TimeoutExpired:
        dumps = ''.join(path.read_text() for path in where.glob('dump-*.txt'))
        pytest.fail(f'The host process did not exit within {HOST_LIMIT} seconds.\n{dumps}')
    finally:
        watchdog.cancel()
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        process.wait(5)
    stdout = ''.join(read) + stdout
    facts = json.loads((where / 'facts.json').read_text()) if (where / 'facts.json').exists() else {}
    if facts:
        assert Path(facts['module']).is_relative_to(SOURCE)
    replies = [json.loads(line) for line in stdout.splitlines() if line.startswith('{')] if kind != 'codex' else []
    report = log.read_text() if log is not None and log.exists() else stderr
    return Host(process.returncode, time.monotonic() - began, stdout, stderr, report, facts, where, replies)


def stop_line(report: str) -> str:
    """The message of the one stop-unconfirmed line in a host's report."""
    found = [json.loads(line) for line in report.splitlines()
             if line.startswith('{') and '"stop-unconfirmed"' in line]
    assert len(found) == 1, f'expected one stop-unconfirmed line in:\n{report}'
    return found[0]['error']['message']


def names_only(message: str, named: list[str], others: list[str]) -> None:
    """The line names these Agents and none of the others."""
    assert all(agent in message for agent in named), message
    assert not any(agent in message for agent in others), message


def target_of(host: Host, position: str = 'first') -> str:
    """The misbehaving Agent."""
    return host.agents[{'first': 0, 'last': -1}[position]]


@pytest.mark.parametrize('position', ['first', 'last'])
@pytest.mark.parametrize('kind', KINDS)
def test_one_interrupt_raising_leaves_every_other_child_stopped(tmp_path: Path, kind: str, position: str) -> None:
    """Failing first or last in stop order: the rest end, only that one is named, and no stop is recorded for it."""
    host = run_host(kind, tmp_path, 'raises', position)
    bad = target_of(host, position)
    others = [agent for agent in host.agents if agent != bad]

    assert sorted(set(host.interrupted)) == host.agents
    assert host.returncode != 0
    names_only(stop_line(host.report), [bad], others)
    assert RECORDED not in host.report and 'Traceback' not in host.report
    assert host.record(bad).get('stop_requested_at') is None and host.record(bad)['state'] == 'running'
    for agent in others:
        assert host.record(agent)['outcome'] == 'interrupted'


@pytest.mark.parametrize('kind', KINDS)
def test_a_failed_interrupt_is_tried_again_and_then_confirmed(tmp_path: Path, kind: str) -> None:
    """A failure once costs a pass, not the shutdown: all stop, no line, status as confirmed."""
    host = run_host(kind, tmp_path, 'raises-once')
    assert host.interrupted.count(target_of(host)) == 2
    assert host.returncode == 0 and 'stop-unconfirmed' not in host.report
    for agent in host.agents:
        assert host.record(agent)['outcome'] == 'interrupted'


@pytest.mark.parametrize('kind', KINDS)
def test_a_child_still_running_at_the_deadline_is_named_and_the_host_ends(tmp_path: Path, kind: str) -> None:
    """Its non-daemon thread never ends: non-zero, the one named line, and the others ended."""
    host = run_host(kind, tmp_path, 'stuck')
    stuck = target_of(host)
    others = host.agents[1:]

    assert host.returncode != 0
    names_only(stop_line(host.report), [stuck], others)
    assert RECORDED not in host.report and 'Traceback' not in host.report
    for agent in others:
        assert host.record(agent)['outcome'] == 'interrupted'


@pytest.mark.parametrize('kind', KINDS)
def test_every_agent_still_owned_is_named_not_just_the_first(tmp_path: Path, kind: str) -> None:
    """Three stuck children, three names, in one line."""
    host = run_host(kind, tmp_path, 'stuck', 'all')
    assert host.returncode != 0
    names_only(stop_line(host.report), host.agents, [])


@pytest.mark.parametrize('kind', KINDS)
def test_the_deadline_is_ten_seconds_in_total(tmp_path: Path, kind: str) -> None:
    """Three stuck children share one deadline: not 10 seconds each, and not less than 10."""
    host = run_host(kind, tmp_path, 'stuck', 'all', stop_seconds=None)
    assert 10.0 <= host.seconds < 20.0
    names_only(stop_line(host.report), host.agents, [])


@pytest.mark.parametrize('position', ['first', 'last'])
@pytest.mark.parametrize('kind', KINDS)
def test_a_blocked_interrupt_neither_hangs_the_host_nor_stops_the_others(tmp_path: Path, kind: str, position: str) -> None:
    """A driver call that never returns holds its record's lock: the rest end, and it is named."""
    # Longer than the one second a pass may wait on the attempt it has just blocked.
    host = run_host(kind, tmp_path, 'blocked', position, stop_seconds=3.0)
    bad = target_of(host, position)
    others = [agent for agent in host.agents if agent != bad]

    assert host.returncode != 0
    names_only(stop_line(host.report), [bad], others)
    assert sorted(set(host.interrupted)) == host.agents
    assert host.interrupted.count(bad) == 1
    for agent in others:
        assert host.record(agent)['outcome'] == 'interrupted'


@pytest.mark.parametrize('kind', KINDS)
def test_an_unreadable_record_stops_nobody_else_and_is_reported(tmp_path: Path, kind: str) -> None:
    """A record that cannot be read may be one this process runs: every child ends and it is named."""
    host = run_host(kind, tmp_path, 'garbage')
    assert host.returncode != 0
    assert 'aaaa-garbage' in stop_line(host.report)
    for agent in host.agents:
        assert host.record(agent)['outcome'] == 'interrupted'


@pytest.mark.parametrize('kind', KINDS)
def test_a_confirmed_shutdown_exits_as_before_with_no_report(tmp_path: Path, kind: str) -> None:
    """Not a test of the defect (it passes on old code): the exit and the logged line stay."""
    host = run_host(kind, tmp_path)
    assert host.returncode == 0
    assert 'stop-unconfirmed' not in host.report and 'Traceback' not in host.report
    assert host.interrupted and sorted(host.interrupted) == host.agents
    if kind == 'agents-claude':
        assert RECORDED in host.report


@pytest.mark.parametrize('kind', CLAUDE_KINDS)
def test_claude_codes_sigint_reports_the_same_way(tmp_path: Path, kind: str) -> None:
    """How Claude Code ends a Session: the stop line, then the report, in host.log."""
    host = run_host(kind, tmp_path, 'stuck', end='sigint')
    assert host.returncode != 0
    assert 'agents host stopped: Claude Code ended the session (SIGINT).' in host.report
    names_only(stop_line(host.report), [target_of(host)], host.agents[1:])


@pytest.mark.parametrize('kind', CLAUDE_KINDS)
def test_the_claude_report_lands_in_host_log_not_on_the_mcp_channel(tmp_path: Path, kind: str) -> None:
    """What the contract says: host.log has it; stdout, the MCP channel, and the original stderr do not."""
    host = run_host(kind, tmp_path, 'stuck')
    assert stop_line(host.report)
    assert 'stop-unconfirmed' not in host.stdout and 'stop-unconfirmed' not in host.stderr


# --- What the Codex host's main() and run() leave behind ---


def test_the_codex_output_document_and_stdout_are_written_before_the_process_ends(tmp_path: Path) -> None:
    """A forced exit must not lose the result: the document names the Agent and stdout is flushed."""
    host = run_host('codex', tmp_path, 'stuck')
    output = json.loads((host.where / 'output.json').read_text())
    assert output['stop_unconfirmed'] == [target_of(host)]
    assert output['outcome'] == 'completed' and output['parent_session']
    assert len(output['operations']) == 3
    assert host.stdout.strip() == output['last_agent_message']


def test_a_confirmed_codex_output_has_an_empty_list(tmp_path: Path) -> None:
    """A reader can tell a confirmed stop from an older host."""
    host = run_host('codex', tmp_path)
    assert json.loads((host.where / 'output.json').read_text())['stop_unconfirmed'] == []


@pytest.mark.parametrize('error', ['runtime', 'known'])
def test_a_codex_run_that_raises_still_reports_and_ends(tmp_path: Path, error: str) -> None:
    """Handled or not, the error stays visible beside the line, and a stuck thread holds nothing up."""
    host = run_host('codex', tmp_path, 'stuck', TEST_RUN_RAISES=error)
    assert host.returncode != 0
    assert 'the run failed' in host.stderr
    names_only(stop_line(host.stderr), [target_of(host)], host.agents[1:])
    if error == 'known':
        assert json.loads(host.stdout.splitlines()[-1])['error']['message'] == 'the run failed'


def test_a_codex_run_that_raises_with_every_child_stopped_exits_as_before(tmp_path: Path) -> None:
    """Not a test of the defect (it passes on old code): no line and the same exit."""
    host = run_host('codex', tmp_path, TEST_RUN_RAISES='known')
    assert host.returncode == 1
    assert 'stop-unconfirmed' not in host.stderr and 'Traceback' not in host.stderr
    assert json.loads(host.stdout.splitlines()[-1])['error']['message'] == 'the run failed'


def test_a_library_caller_of_codex_run_keeps_its_process(tmp_path: Path) -> None:
    """``run`` returns the names; the process that called it carries on and decides for itself."""
    host = run_host('codex', tmp_path, 'stuck', TEST_LIBRARY='1')
    assert host.returncode == 0 and 'stop-unconfirmed' not in host.stderr
    assert json.loads((host.where / 'library.json').read_text())['stop_unconfirmed'] == [target_of(host)]


# --- What the next host for this Session shows and delivers ---


def next_status(kind: str, tmp_path: Path, agent: str) -> dict:
    """Ask a new host process for one Agent's status through the tool, as the Session does."""
    request = [tool_call(20, 'status', agent=agent)]
    if kind == 'codex':
        host = run_host(kind, tmp_path, requests=request, TEST_ARGUMENTS='--resume', TEST_OUTPUT='next.json')
        answers = json.loads(json.loads((host.where / 'next.json').read_text())['last_agent_message'])
        return answers[0]['result']['structuredContent']['result']
    host = run_host(kind, tmp_path, requests=request)
    answer = next(reply for reply in host.replies if reply['id'] == 20)
    return answer['result']['structuredContent']['result']


@pytest.mark.parametrize('kind', KINDS)
def test_the_next_host_shows_an_unconfirmed_agent_as_not_stopped(tmp_path: Path, kind: str) -> None:
    """The line's claim: the Runtime is gone, so status shows a failed end, not an interrupted one."""
    first = run_host(kind, tmp_path, 'stuck')
    stuck = target_of(first)
    assert stuck in stop_line(first.report)

    document = next_status(kind, tmp_path, stuck)
    last = document['last_result']
    assert document['state'] == 'standby'
    assert (last['outcome'], last['terminal_confirmed'], last['error']['code']) == ('failed', False, 'owner-exited')


@pytest.mark.parametrize('kind', KINDS)
def test_the_next_host_shows_a_surviving_runtime_as_active(tmp_path: Path, kind: str) -> None:
    """The other half of the claim: a Runtime that outlived the host keeps its Agent active, with the reason."""
    survivors = []
    try:
        first = run_host(kind, tmp_path, 'runtime')
        survivors = first.facts['survivors']
        stuck = target_of(first)
        assert first.returncode != 0 and stuck in stop_line(first.report)

        document = next_status(kind, tmp_path, stuck)
        assert (document['state'], document['stopping']) == ('active', True)
        assert document['diagnostic'] == 'owner-exited; the Runtime process is still running'
    finally:
        for pid in survivors:
            os.kill(pid, signal.SIGKILL)


def test_403_agents_claude_ends_stay_held_and_arrive_once_on_a_later_host(tmp_path: Path) -> None:
    """A child's interrupt fails, the others stop: nothing is pushed then; a later result carries each once."""
    first = run_host('agents-claude', tmp_path, 'raises')
    bad = target_of(first)
    assert bad in stop_line(first.report)
    assert not any('main_notices' in reply.get('result', {}).get('structuredContent', {}) for reply in first.replies)
    for agent in first.agents[1:]:
        assert (first.record(agent)['outcome'], first.record(agent)['notification']) == ('interrupted', 'held')

    second = run_host('agents-claude', tmp_path, requests=DISCOVER)
    answer = next(reply for reply in second.replies if reply['id'] == 20)
    notices = answer['result']['structuredContent']['main_notices']
    assert sorted((notice['event']['alias'], notice['event']['event']) for notice in notices) == sorted(
        [(bad, 'failed')] + [(agent, 'interrupted') for agent in first.agents[1:]])

    third = run_host('agents-claude', tmp_path, requests=DISCOVER)
    answer = next(reply for reply in third.replies if reply['id'] == 20)
    assert 'main_notices' not in answer['result']['structuredContent']


def test_403_codex_ends_stay_held_and_arrive_once_on_a_later_resume(tmp_path: Path) -> None:
    """The same on the Codex host: one host event each on the resume, none on a further one."""
    log = tmp_path / 'host-events.jsonl'
    first = run_host('codex', tmp_path, 'raises')
    bad = target_of(first)
    assert bad in stop_line(first.stderr)
    assert not log.exists()
    for agent in first.agents[1:]:
        assert (first.record(agent)['outcome'], first.record(agent)['notification']) == ('interrupted', 'held')

    def resume() -> list[tuple[str, str]]:
        """One more --resume of the parent, in a turn long enough to take what was held."""
        host = run_host('codex', tmp_path, TEST_ARGUMENTS='--resume', TEST_INSTRUCTION='hold', TEST_HOLD_SECONDS='1.5')
        assert host.returncode == 0 or 'stop-unconfirmed' not in host.stderr
        return [(line['alias'], line['event']) for line in map(json.loads, log.read_text().splitlines())]

    assert sorted(resume()) == sorted([(bad, 'failed')] + [(agent, 'interrupted') for agent in first.agents[1:]])
    assert len(resume()) == 3
