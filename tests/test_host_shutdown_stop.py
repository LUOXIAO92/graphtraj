"""A closing Pi or DSH host stops every child, and reports the ones it cannot confirm (414).

The fake drivers end a while after the interrupt, as a real Runtime does: an end
that beats the status read would hide the defect. No network, no real model.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Callable

import pytest

from graftling import AgentsError, AgentsResult, Caller, bind, shutdown
import test_pi_dsh_notice_holding as holding
from test_pi_dsh_notice_holding import CALLERS, Driver, Process, SOURCE, native_host, read_record, wait_until  # noqa: F401


class Stopping(Driver):
    """Ends each execution 0.2 seconds after its interrupt, unless told otherwise."""

    def __init__(self, stubborn: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.finish = None
        self.stubborn = stubborn
        self.broken: dict[str, list[Exception]] = {}
        self.interrupted: list[str] = []

    def interrupt(self, run) -> bool:
        """Record the attempt; fail, ignore or schedule the end."""
        self.interrupted.append(run.agent)
        if self.broken.get(run.agent):
            raise self.broken[run.agent].pop(0)
        if run.agent not in self.stubborn:
            threading.Timer(0.2, run.events.finished, args=('interrupted',),
                            kwargs={'last_message': 'partial work'}).start()
        return True


def stop_order(status: dict) -> list[str]:
    """The Agents in the order a host stops them: descendants first."""
    pending, owned = list(status['agents']), []
    while pending:
        agent = pending.pop()
        owned.append(agent['agent'])
        pending.extend(agent['children'])
    return owned[::-1]


def ask(process: Process, agent: str, how: str, run: Any) -> None:
    """Leave one unanswered request on ``agent``."""
    if how == 'native':
        run.events.request({'request_token': 'token-1', 'request_id': 7, 'method': 'claude/can_use_tool',
                            'params': {'tool_name': 'Bash'}})
    else:
        bind(process.control, Caller('runtime-mcp', agent))({'action': 'ask_parent', 'kind': 'decision',
                                                             'question': 'Which?', 'timeout_seconds': 0.05})
    assert process.inner({'action': 'status', 'agent': agent}).document['result']['pending_requests'] == 1


def family(build: Callable, driver: Stopping, **options) -> tuple[Process, str, str, str]:
    """Two running children and a running grandchild below the first."""
    process = build(driver=driver, **options)
    first, second = process.create('one'), process.create('two')
    made = bind(process.control, Caller('runtime-mcp', first))({'action': 'create', 'runtime': 'claude', 'instruction': 'three'})
    grandchild = made.document['agent']
    for agent in (first, second, grandchild):
        wait_until(lambda: read_record(process.tmp, agent)['executions'][-1]['started'])
    return process, first, second, grandchild


@pytest.fixture
def build(native_host: Callable, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable:  # noqa: F811
    """One host process, with a short stop deadline except where a test restores it."""
    monkeypatch.setattr(shutdown, 'STOP_SECONDS', 1.0)

    def made(**options) -> Process:
        """Keep the data root's parent for reading records."""
        process = native_host(**options)
        process.tmp = tmp_path
        return process

    return made


def standby(process: Process, agent: str) -> bool:
    """Whether status shows the Agent stopped."""
    return process.inner({'action': 'status', 'agent': agent}).document['result']['state'] == 'standby'


@pytest.mark.parametrize('how', ['native', 'ask_parent'])
@pytest.mark.parametrize('position', [0, -1], ids=['first', 'last'])
def test_an_unanswered_request_does_not_stop_the_others(build: Callable, position: int, how: str) -> None:
    """Whichever Agent is asking and wherever it stops: all end, nothing raises, none is left."""
    driver = Stopping()
    process, first, second, grandchild = family(build, driver)
    order = stop_order(process.inner({'action': 'status'}).document['result'])
    ask(process, order[position], how, driver.runs[order[position]])

    assert process.stop_children() == []
    assert all(standby(process, agent) for agent in order)
    assert sorted(driver.interrupted) == sorted(order)
    assert driver.interrupted.index(grandchild) < driver.interrupted.index(first)
    for agent in order:
        assert read_record(process.tmp, agent)['executions'][-1]['outcome'] == 'interrupted'


def test_every_child_is_interrupted_before_any_is_waited_for(build: Callable) -> None:
    """The stops run in parallel, so the shared deadline covers them all at once."""
    driver = Stopping()
    process, first, second, grandchild = family(build, driver)
    process.stop_children()
    began = [record['executions'][-1]['stop_requested_at'] for record in map(
        lambda agent: read_record(process.tmp, agent), (first, second, grandchild))]
    ended = [read_record(process.tmp, agent)['executions'][-1]['ended_at'] for agent in (first, second, grandchild)]
    assert max(began) < min(ended)


def test_this_shutdowns_ends_stay_held_and_arrive_once(build: Callable, tmp_path: Path) -> None:
    """403 holds: not pushed at the stop; the next host delivers each once, a further one nothing."""
    driver = Stopping()
    process, first, second, grandchild = family(build, driver, shown=False)
    ask(process, first, 'native', driver.runs[first])
    before = list(process.pipe.lines)

    process.shutdown()
    assert process.pipe.lines == before
    for agent in (first, second, grandchild):
        record = read_record(tmp_path, agent)['executions'][-1]
        assert (record['outcome'], record['notification']) == ('interrupted', 'held')

    resumed = build()
    written = resumed.flush()
    assert sorted(line['agent'] for line in written) == sorted([first, second])
    assert {line['event'] for line in written} == {'interrupted'}  # the ended request is withdrawn
    assert resumed.flush() == written
    assert build().flush() == []
    assert read_record(tmp_path, first)['executions'][-1]['notification'] == 'delivered'
    assert read_record(tmp_path, grandchild)['executions'][-1]['notification'] == 'held'


def test_a_child_that_never_stops_is_named_and_the_others_end_within_the_bound(build: Callable) -> None:
    """Only the stubborn Agent is unconfirmed; the deadline is shared, not per Agent."""

    class Stubborn(Stopping):
        """The first Agent the host stops ignores its interrupt."""

        def interrupt(self, run) -> bool:
            """Decide on first use, since the order depends on generated references."""
            if not self.stubborn:
                self.stubborn = (run.agent,)
            return super().interrupt(run)

    driver = Stubborn()
    process, first, second, grandchild = family(build, driver)
    began = time.monotonic()
    assert process.stop_children() == list(driver.stubborn)
    assert 1.0 <= time.monotonic() - began < 3.0
    others = {first, second, grandchild} - set(driver.stubborn)
    assert len(others) == 2 and all(standby(process, agent) for agent in others)
    document = process.inner({'action': 'status', 'agent': driver.stubborn[0]}).document['result']
    assert document['state'] == 'active' and document['stopping'] is True


def test_the_deadline_is_ten_seconds() -> None:
    """The contract's number."""
    assert shutdown.STOP_SECONDS == 10.0


@pytest.mark.parametrize('error', [RuntimeError('driver broke'), AgentsError('runtime-failed', 'refused')],
                         ids=['raises', 'failed-result'])
def test_a_failing_interrupt_is_reported_and_stops_nobody_else(build: Callable, error: Exception) -> None:
    """Interrupting the first Agent keeps failing: it is named, and the others still end."""

    class Broken(Stopping):
        """The first Agent the host stops fails every interrupt."""

        def interrupt(self, run) -> bool:
            """Decide on first use, since the order depends on generated references."""
            if not self.broken:
                self.broken[run.agent] = [error] * 1000
            return super().interrupt(run)

    driver = Broken()
    process, first, second, grandchild = family(build, driver)
    unconfirmed = process.stop_children()
    bad = list(driver.broken)
    assert unconfirmed == bad
    assert all(standby(process, agent) for agent in {first, second, grandchild} - set(bad))


def test_an_agent_that_was_still_starting_is_interrupted_again(build: Callable) -> None:
    """``starting`` is refused once; the next pass reaches it, so nothing is left."""
    driver = Stopping()
    process, first, second, grandchild = family(build, driver)
    driver.broken[second] = [AgentsError('starting', 'The execution is still starting.')]
    assert process.stop_children() == []
    assert standby(process, second) and driver.interrupted.count(second) == 2


def status_that(call: Callable, behave: Callable) -> Callable:
    """``call`` with its status answers replaced by ``behave(count, real_call)``."""
    count = [0]

    def wrapped(request: dict) -> AgentsResult:
        """Count status calls and let ``behave`` answer them."""
        if request['action'] != 'status':
            return call(request)
        count[0] += 1
        return behave(count[0], lambda: call(request))

    return wrapped


FAILED = AgentsResult({'action': 'status', 'error': {'code': 'broken', 'message': 'no status'}}, failed=True)


def raise_error(*_: Any) -> AgentsResult:
    """A status call that does not even return."""
    raise OSError('record store unavailable')


@pytest.mark.parametrize('behave', [lambda *_: FAILED, raise_error], ids=['failed-result', 'raises'])
def test_a_status_that_never_answers_confirms_nothing(build: Callable, behave: Callable) -> None:
    """No status at all is not success: the result says so, within the bound."""
    driver = Stopping()
    process, *_ = family(build, driver)
    order = process.control.visible_agents(process.caller)
    began = time.monotonic()
    assert process.stop_children(status_that(process.inner, behave)) == [*order, shutdown.STATUS_UNREADABLE]
    assert time.monotonic() - began < 3.0
    process.stop_children()  # no timer outlives the test


def test_agents_that_cannot_be_listed_confirm_nothing(build: Callable) -> None:
    """Who exists is unknown, so nothing is claimed about anyone."""
    def unlisted() -> list[str]:
        """The record directory cannot be read."""
        raise OSError('record store unavailable')

    process, *_ = family(build, Stopping())
    assert process.host.stop_children(process.inner, unlisted) == [shutdown.STATUS_UNREADABLE]
    process.stop_children()  # no timer outlives the test


def test_a_status_lost_after_the_first_keeps_every_agent_unconfirmed(build: Callable) -> None:
    """Interrupted, but never seen to end: each one is named, none is claimed stopped."""
    driver = Stopping()
    process, first, second, grandchild = family(build, driver)
    call = status_that(process.inner, lambda count, real: real() if count == 1 else FAILED)
    assert sorted(process.stop_children(call)) == sorted([first, second, grandchild, shutdown.STATUS_UNREADABLE])
    assert sorted(driver.interrupted) == sorted([first, second, grandchild])
    wait_until(lambda: all(standby(process, agent) for agent in (first, second, grandchild)))


def test_a_status_that_recovers_stops_everything(build: Callable) -> None:
    """One failed read costs a pass, not the shutdown."""
    driver = Stopping()
    process, first, second, grandchild = family(build, driver)
    call = status_that(process.inner, lambda count, real: FAILED if count == 1 else real())
    assert process.stop_children(call) == []
    assert all(standby(process, agent) for agent in (first, second, grandchild))


def test_a_blocked_call_keeps_one_thread_and_the_stop_within_its_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every pass reads the others again, but the blocked Agent is not called a second time."""
    monkeypatch.setattr(shutdown, 'STOP_SECONDS', 0.6)
    release, reads = threading.Event(), {'stuck': 0, 'other': 0}

    def call(request: dict) -> AgentsResult:
        """``stuck`` blocks on its first read; ``other`` answers as active until the end."""
        if request['action'] == 'status':
            reads[request['agent']] += 1
            if request['agent'] == 'stuck':
                release.wait()
            return AgentsResult({'result': {'state': 'active'}})
        return AgentsResult({})

    began = time.monotonic()
    try:
        assert shutdown.stop_children(call, lambda: ['stuck', 'other']) == ['stuck', 'other', shutdown.STATUS_UNREADABLE]
        assert time.monotonic() - began < 0.6 + 1.0
        assert reads['stuck'] == 1 and reads['other'] > 1
    finally:
        release.set()


def test_an_agent_seen_stopped_whose_latest_read_is_lost_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """'Confirmed' is the latest answer: an earlier one does not speak for an Agent after its read fails."""
    monkeypatch.setattr(shutdown, 'STOP_SECONDS', 0.3)
    reads = [0]

    def call(request: dict) -> AgentsResult:
        """``idle`` answers standby once; ``busy`` keeps the stop going until the deadline."""
        if request['action'] != 'status':
            return AgentsResult({})
        if request['agent'] == 'busy':
            return AgentsResult({'result': {'state': 'active'}})
        reads[0] += 1
        return AgentsResult({'result': {'state': 'standby'}}) if reads[0] == 1 else FAILED

    assert shutdown.stop_children(call, lambda: ['idle', 'busy']) == ['idle', 'busy', shutdown.STATUS_UNREADABLE]


# --- The real main() in a real process, closed by ending its stdin ---

# How long a host process may take to end, its 10-second stop included.
HOST_LIMIT = 30

HOST = r'''
import contextlib, importlib, json, os, subprocess, sys, threading, time
from pathlib import Path
import graftling
from graftling import AgentsResult, Caller, bind, shutdown

kind, where, stubborn = os.environ['TEST_KIND'], Path(os.environ['TEST_WHERE']), os.environ['TEST_STUBBORN']
host = importlib.import_module(f'graftling.{kind}.host')
if os.environ.get('TEST_STOP_SECONDS'):
    shutdown.STOP_SECONDS = float(os.environ['TEST_STOP_SECONDS'])
facts = {'module': graftling.__file__}


class Driver:
    """Owns each execution on a non-daemon thread, as the four real drivers do."""

    def __init__(self):
        self.stops, self.runs = {}, {}

    def prepare(self, runtime, caller, **options):
        return {'runtime': runtime}

    def require_available(self, connection):
        pass

    def start(self, run):
        run.events.session('native-' + run.agent[-6:])
        stop = self.stops[run.agent] = threading.Event()
        self.runs[run.agent] = run

        def own():
            stop.wait()
            run.events.finished('interrupted', last_message='partial work')

        threading.Thread(target=own, name=f'test-{run.agent}').start()

    def interrupt(self, run):
        if stubborn == 'interrupt' and run.agent == facts.get('stubborn'):
            threading.Event().wait()
        if run.agent != facts.get('stubborn'):
            threading.Timer(0.2, self.stops[run.agent].set).start()
        return True

    def requests(self, run):
        return []

    def reply(self, run, request, response):
        return {}


driver = Driver()
real_start = host.start
real_connection = host.agents_connection
entered = threading.Event()


def hold_lock(agent):
    """Another real process takes this Agent's real record lock and keeps it past any limit."""
    held = where / 'lock-held'
    subprocess.Popen([sys.executable, '-c', HOLDER, str(where / 'data' / 'live' / 'agents' / f'{agent}.lock'), str(held)],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    while not held.exists():
        time.sleep(0.01)


def acknowledgements(notices, agent):
    """What the extension sends for one child's end: taken for a turn, then shown. The end of these lines is the close."""
    driver.stops[agent].set()
    while not notices.waiting:
        time.sleep(0.01)
    identity = next(iter(notices.waiting))
    yield json.dumps({'ack': identity, 'queued': True})
    record = where / 'data' / 'control' / 'agents' / f'{agent}.json'
    while json.loads(record.read_text())['executions'][-1].get('notification') != 'held':
        time.sleep(0.01)
    facts['acknowledged'] = agent
    (where / 'facts.json').write_text(json.dumps(facts))
    if os.environ['TEST_ACK'] == 'locked':
        hold_lock(agent)
    yield json.dumps({'ack': identity, 'shown': True})


def late_status(call):
    """``call`` whose first status answers and whose later ones fail or never return."""
    reads = []

    def wrapped(request):
        if request['action'] == 'status':
            reads.append(request)
            if len(reads) > 1:
                if os.environ['TEST_LATE'] == 'blocks':
                    threading.Event().wait()
                return AgentsResult({'action': 'status', 'error': {'code': 'broken', 'message': 'no status'}}, failed=True)
        return call(request)

    return wrapped


@contextlib.contextmanager
def connection(directory, operate, authenticate, **options):
    """The real channel; a real client process leaves one model request in flight before the pipe closes."""
    def traced(request):
        entered.set()
        time.sleep(float(os.environ.get('TEST_SLOW', 0)))
        return operate(request)

    with real_connection(directory, traced, authenticate, **options) as address:
        if os.environ.get('TEST_IN_FLIGHT'):
            request = {'action': 'execute', 'feature': 'status', 'arguments': {}}
            document = request if kind == 'pi' else {'request': request, 'native': options['native_context']()}
            subprocess.Popen([sys.executable, '-c', CLIENT, address, json.dumps(document), str(where / 'client.txt')],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            entered.wait()
            time.sleep(0.2)  # past the admission, into the blocked operation
        facts['closing_at'] = time.time()
        (where / 'facts.json').write_text(json.dumps(facts))
        yield address


def started(*arguments):
    """The real start, then children that meet the real shutdown."""
    result = real_start(*arguments)
    notices, operate, control = (result[1], result[2], result[4]) if kind == 'pi' else (result[2], result[3], result[5])
    notices.timeout = 0.05
    first = operate({'action': 'create', 'runtime': 'claude', 'instruction': 'one'}).document['agent']
    second = operate({'action': 'create', 'runtime': 'claude', 'instruction': 'two'}).document['agent']
    third = bind(control, Caller('runtime-mcp', first))({'action': 'create', 'runtime': 'claude', 'instruction': 'three'}).document['agent']
    for agent in (first, second, third):
        record = where / 'data' / 'control' / 'agents' / f'{agent}.json'
        while not json.loads(record.read_text())['executions'][-1]['started']:
            time.sleep(0.01)
    pending, owned = list(operate({'action': 'status'}).document['result']['agents']), []
    while pending:
        agent = pending.pop()
        owned.append(agent['agent'])
        pending.extend(agent['children'])
    order = owned[::-1]
    asking = order[0 if os.environ['TEST_POSITION'] == 'first' else -1]
    driver.runs[asking].events.request({'request_token': 'token-1', 'request_id': 7, 'method': 'claude/can_use_tool',
                                        'params': {'tool_name': 'Bash'}})
    facts.update(order=order, asking=asking)
    if stubborn:
        facts['stubborn'] = asking
    if stubborn == 'runtime':
        # The Runtime's wiring in pi/execution.py and claude/execution.py.
        survivor = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'], stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        driver.runs[asking].events.process(runtime_pid=survivor.pid)
        facts['survivor'] = survivor.pid
    if os.environ.get('TEST_LOCK'):
        facts['locked'] = {'second': second, 'first': first}[os.environ['TEST_LOCK']]
        hold_lock(facts['locked'])
    (where / 'facts.json').write_text(json.dumps(facts))
    if os.environ.get('TEST_ACK'):
        notices.timeout = 10.0
        sys.stdin = acknowledgements(notices, second)
    if os.environ.get('TEST_LATE'):
        at = 3 if kind == 'pi' else 4
        result = (*result[:at], late_status(result[at]), *result[at + 1:])
    return result


host.verify_native_parent = lambda *_: None
host.runtime_drivers = lambda *_: {'claude': driver}
host.start = started
host.agents_connection = connection
host.process_ancestors = lambda pid: [pid, os.getppid()]  # the test's client stands for the native side's
if kind == 'pi':
    host.pi_request = lambda *_: {}
    host.current_connection = lambda: {'runtime': 'pi', 'session': 'main', 'session_file': str(where / 's.jsonl')}
sys.argv = ['host', '--config', str(where / 'host.json')]
host.main()
'''

HOLDER = '''
import fcntl, pathlib, sys, time
stream = open(sys.argv[1], 'a+b')
fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
pathlib.Path(sys.argv[2]).write_text('held')
time.sleep(600)
'''

CLIENT = '''
import json, pathlib, sys
from graftling.connection import connection_operation
try:
    outcome = json.dumps(connection_operation(sys.argv[1], json.loads(sys.argv[2]), authenticate=True, await_accepted=True))
except Exception as error:
    outcome = str(error)
pathlib.Path(sys.argv[3]).write_text(outcome)
'''


def run_host(tmp_path: Path, kind: str, position: str = 'first', stubborn: str = '', stop_seconds: float | None = None,
             then: str = '', limit: float = HOST_LIMIT, **tests: str) -> tuple[subprocess.CompletedProcess, dict]:
    """Run ``main()`` in its own process group, end its stdin and wait at most ``limit``.

    ``tests`` become ``TEST_*`` variables: ``lock`` (which child's record lock another process
    holds), ``late`` (how status behaves after its first answer), ``in_flight`` (a model request
    left in flight on the host connection), ``slow`` (seconds that request takes before its
    operation). ``facts['ended_after']`` is the seconds from the
    host entering its stdin loop, by which time the pipe is closed, to its process ending.
    """
    script = tmp_path / 'run-host.py'
    script.write_text(f'HOLDER = {HOLDER!r}\nCLIENT = {CLIENT!r}\n' + HOST)
    (tmp_path / 'host.json').write_text(json.dumps({'root': str(tmp_path / 'data')}))
    if kind == 'pi':
        header = {'type': 'session', 'version': 3, 'id': 'main', 'cwd': str(tmp_path)}
        launch = json.dumps({'header': header, 'entries': []})
    else:
        launch = json.dumps({'header': {'version': 4, 'id': 'main', 'cwd': str(tmp_path), 'isSeeded': False}})
    # Built, not copied: nothing of the real environment reaches this process or its output.
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path), 'PYTHONPATH': str(SOURCE), 'TEST_KIND': kind,
           'TEST_WHERE': str(tmp_path), 'TEST_POSITION': position, 'TEST_STUBBORN': stubborn,
           'GRAFTLING_PI_ENTRY': sys.executable,
           **{f'TEST_{name.upper()}': value for name, value in tests.items()}}
    if stop_seconds is not None:
        env['TEST_STOP_SECONDS'] = str(stop_seconds)
    process = subprocess.Popen([sys.executable, str(script)], cwd=tmp_path, env=env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        # communicate reads to EOF: like Node's close, it also waits for whoever holds the pipes.
        stdout, stderr = process.communicate(launch + '\n' + then, timeout=limit)
        ended = time.time()
    except subprocess.TimeoutExpired:
        pytest.fail(f'The host process did not exit within {limit} seconds.')
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        process.wait(5)
    facts = json.loads((tmp_path / 'facts.json').read_text())
    assert Path(facts['module']).is_relative_to(SOURCE)
    facts['ended_after'] = ended - facts['closing_at']
    return subprocess.CompletedProcess(script, process.returncode, stdout, stderr), facts


def stop_line(stderr: str) -> dict:
    """The one stop-unconfirmed line in the host's stderr."""
    found = [json.loads(line) for line in stderr.splitlines()
             if line.startswith('{') and '"stop-unconfirmed"' in line]
    assert len(found) == 1, 'no stop-unconfirmed line'
    return found[0]['error']


@pytest.mark.parametrize('position', ['first', 'last'])
@pytest.mark.parametrize('kind', ['pi', 'dsh'])
def test_a_real_host_process_with_an_unanswered_request_exits_cleanly(tmp_path: Path, kind: str, position: str) -> None:
    """The acceptance test: every Agent ended, exit 0, nothing on stderr about a stop."""
    result, facts = run_host(tmp_path, kind, position)
    assert result.returncode == 0, 'host exited non-zero'
    assert 'stop-unconfirmed' not in result.stderr and 'Traceback' not in result.stderr
    for agent in facts['order']:
        record = read_record(tmp_path, agent)['executions'][-1]
        assert (record['outcome'], record['notification']) == ('interrupted', 'held')


@pytest.mark.parametrize('kind', ['pi', 'dsh'])
def test_a_real_host_process_names_a_stuck_child_and_exits_anyway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    """Its non-daemon thread never ends: non-zero, the named line, and the next host does not call it stopped."""
    began = time.monotonic()
    result, facts = run_host(tmp_path, kind, stubborn='thread')
    assert 10.0 <= time.monotonic() - began < HOST_LIMIT
    assert result.returncode != 0
    message = stop_line(result.stderr)['message']
    stuck = facts['stubborn']
    assert stuck in message and not any(agent in message for agent in facts['order'] if agent != stuck)
    assert 'Traceback' not in result.stderr
    for agent in facts['order']:
        if agent != stuck:
            record = read_record(tmp_path, agent)['executions'][-1]
            assert (record['outcome'], record['notification']) == ('interrupted', 'held')

    # What the next host shows: an unconfirmed failure, held, not an interrupted end.
    next_host = Process(kind, tmp_path, monkeypatch, True, 2.0, Driver())
    document = next_host.inner({'action': 'status', 'agent': stuck}).document['result']
    last = document['last_result']
    assert document['state'] == 'standby'
    assert (last['outcome'], last['terminal_confirmed'], last['error']['code']) == ('failed', False, 'owner-exited')
    assert read_record(tmp_path, stuck)['executions'][-1]['notification'] == 'held'


@pytest.mark.parametrize('kind', ['pi', 'dsh'])
def test_a_surviving_runtime_does_not_hold_the_hosts_pipes_and_reads_as_active(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    """A Runtime wired as the drivers wire it outlives the host: the pipes still close, and it stays active."""
    survivor = None
    try:
        result, facts = run_host(tmp_path, kind, stubborn='runtime', stop_seconds=1.0)
        survivor = facts['survivor']
        os.kill(survivor, 0)  # still alive: communicate returned anyway
        assert result.returncode != 0 and facts['stubborn'] in stop_line(result.stderr)['message']
        next_host = Process(kind, tmp_path, monkeypatch, True, 2.0, Driver())
        document = next_host.inner({'action': 'status', 'agent': facts['stubborn']}).document['result']
        assert (document['state'], document['stopping']) == ('active', True)
        assert document['diagnostic'] == 'owner-exited; the Runtime process is still running'
        assert 'last_result' not in document
    finally:
        if survivor is None and (tmp_path / 'facts.json').exists():
            survivor = json.loads((tmp_path / 'facts.json').read_text()).get('survivor')
        if survivor is not None:
            os.kill(survivor, signal.SIGKILL)


@pytest.mark.parametrize('kind', ['pi', 'dsh'])
def test_an_error_already_unwinding_survives_the_forced_exit(tmp_path: Path, kind: str) -> None:
    """A bad pipe line and a stuck child: both the traceback and the named line reach stderr."""
    result, facts = run_host(tmp_path, kind, stubborn='thread', stop_seconds=0.5, then='not json\n')
    assert result.returncode != 0
    assert 'JSONDecodeError' in result.stderr and facts['stubborn'] in stop_line(result.stderr)['message']


@pytest.mark.parametrize('kind', ['pi', 'dsh'])
def test_an_error_with_every_child_stopped_exits_as_before(tmp_path: Path, kind: str) -> None:
    """Nothing unconfirmed: no forced exit and no stop line; the error ends the process itself."""
    result, _ = run_host(tmp_path, kind, then='not json\n')
    assert result.returncode == 1
    assert 'JSONDecodeError' in result.stderr and 'stop-unconfirmed' not in result.stderr


# --- One blocked call (434) ---

# The contract: a host process ends this soon after its pipe closes, its 10-second stop included.
END_SECONDS = 20
# Time to fail on old code, where the process waits for a lock released only after this.
BLOCKED_LIMIT = 25
READY = '{"ready": true}\n'


def assert_others_ended(tmp_path: Path, facts: dict, stuck: str, message: str) -> None:
    """Only ``stuck`` is named; every other child was interrupted, seen to end, and its end is held."""
    assert stuck in message and not any(agent in message for agent in facts['order'] if agent != stuck)
    for agent in facts['order']:
        if agent != stuck:
            record = read_record(tmp_path, agent)['executions'][-1]
            assert (record['outcome'], record['notification']) == ('interrupted', 'held')


@pytest.mark.parametrize('kind', ['pi', 'dsh'])
def test_another_process_holding_a_record_lock_does_not_hold_the_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    """392 steps 49 and 50, with every wait at once: the flusher and a model request blocked too, at the real 10 seconds."""
    result, facts = run_host(tmp_path, kind, then=READY, limit=BLOCKED_LIMIT, lock='second', in_flight='status')
    assert facts['ended_after'] < END_SECONDS
    assert result.returncode != 0 and 'Traceback' not in result.stderr
    stuck = facts['locked']
    message = stop_line(result.stderr)['message']
    assert_others_ended(tmp_path, facts, stuck, message)
    assert 'Every other Agent stopped.' in message  # each was read after the lock was taken
    # The caller of the request in flight is told it is unconfirmed, not left waiting.
    assert 'unconfirmed' in wait_until(lambda: (tmp_path / 'client.txt').exists() and (tmp_path / 'client.txt').read_text())

    # With the lock free again the next host shows the real state, as PUBLIC_API section 4 says.
    next_host = Process(kind, tmp_path, monkeypatch, True, 2.0, Driver())
    document = next_host.inner({'action': 'status', 'agent': stuck}).document['result']
    last = document['last_result']
    assert (last['outcome'], last['terminal_confirmed'], last['error']['code']) == ('failed', False, 'owner-exited')


@pytest.mark.parametrize('kind', ['pi', 'dsh'])
def test_a_locked_parent_does_not_hide_or_hold_its_descendants(tmp_path: Path, kind: str) -> None:
    """The locked record is a parent whose child must still end, within the shortened stop."""
    result, facts = run_host(tmp_path, kind, stop_seconds=2.0, limit=10, lock='first')
    assert result.returncode != 0
    assert_others_ended(tmp_path, facts, facts['locked'], stop_line(result.stderr)['message'])


@pytest.mark.parametrize('kind', ['pi', 'dsh'])
def test_a_driver_interrupt_that_never_returns_stops_nobody_else(tmp_path: Path, kind: str) -> None:
    """The first Agent's interrupt blocks while holding its lock: the others still end and only it is named."""
    result, facts = run_host(tmp_path, kind, stubborn='interrupt', stop_seconds=2.0, limit=10)
    assert result.returncode != 0
    assert_others_ended(tmp_path, facts, facts['stubborn'], stop_line(result.stderr)['message'])


@pytest.mark.parametrize('late', ['fails', 'blocks'])
@pytest.mark.parametrize('kind', ['pi', 'dsh'])
def test_a_status_lost_after_the_first_claims_no_other_agent_stopped(tmp_path: Path, kind: str, late: str) -> None:
    """Interrupted but never seen to end: all are named, and the line does not vouch for anyone else."""
    result, facts = run_host(tmp_path, kind, stop_seconds=1.0, limit=10, late=late)
    assert result.returncode != 0
    message = stop_line(result.stderr)['message']
    assert all(agent in message for agent in facts['order'])
    assert 'Every other Agent stopped' not in message
    assert 'no other Agent is confirmed' in message


@pytest.mark.parametrize('kind', ['pi', 'dsh'])
def test_a_request_in_flight_that_finishes_still_gets_its_reply(tmp_path: Path, kind: str) -> None:
    """The bound only cuts what is blocked: a request that takes a second still answers, and the stop is clean."""
    result, facts = run_host(tmp_path, kind, in_flight='status', slow='1')
    assert result.returncode == 0 and 'stop-unconfirmed' not in result.stderr
    outcome = json.loads(wait_until(lambda: (tmp_path / 'client.txt').exists() and (tmp_path / 'client.txt').read_text()))
    assert outcome['failed'] is False


def test_a_shown_acknowledgement_on_a_locked_record_does_not_hold_the_pi_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pi's stdin loop settles what it was told is shown: a held lock must not stop it reading the close.

    Unsettled when the host ends, the notice stays ``held`` as for any host that ended
    first, so the next host pushes it once more.
    """
    result, facts = run_host(tmp_path, 'pi', stop_seconds=2.0, limit=12, ack='locked')
    assert result.returncode != 0 and 'Traceback' not in result.stderr
    agent = facts['acknowledged']
    assert_others_ended(tmp_path, facts, agent, stop_line(result.stderr)['message'])
    assert read_record(tmp_path, agent)['executions'][-1]['notification'] == 'held'
    written = Process('pi', tmp_path, monkeypatch, True, 2.0, Driver()).flush()
    assert [line['agent'] for line in written].count(agent) == 1
    assert read_record(tmp_path, agent)['executions'][-1]['notification'] == 'delivered'


def test_a_shown_acknowledgement_still_settles_when_the_record_is_free(tmp_path: Path) -> None:
    """Nothing blocked: the notice is delivered, however soon the pipe closes after the acknowledgement."""
    result, facts = run_host(tmp_path, 'pi', limit=20, ack='free')
    assert result.returncode == 0 and 'stop-unconfirmed' not in result.stderr
    assert read_record(tmp_path, facts['acknowledged'])['executions'][-1]['notification'] == 'delivered'


# --- Where the line surfaces on the native side ---

STOP_LINE = '{"error": {"code": "stop-unconfirmed", "message": "Host shutdown could not confirm the stop of: agent-1."}}'


def test_the_real_extension_rejects_with_the_line_and_the_next_session_still_gets_a_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pi reports a rejected ``session_shutdown`` handler; a reload's new start must not repeat it."""
    closing = "setTimeout(async () => { await owner.close(); console.log(JSON.stringify(sent)); }, Number(process.env.TEST_RUN_MS));"
    assert closing in holding.EXTENSION
    monkeypatch.setattr(holding, 'EXTENSION', holding.EXTENSION.replace(closing, '''
const errors = [];
await owner.close().catch(error => errors.push(error.message));
errors.push(await owner.start(ctx));
await owner.close().catch(error => errors.push(error.message));
console.log(JSON.stringify(errors));
'''))
    monkeypatch.setattr(holding, 'FAKE_EXTENSION_HOST', holding.FAKE_EXTENSION_HOST + f'sys.stderr.write({STOP_LINE!r} + "\\n")\nsys.exit(1)\n')
    errors, _ = holding.run_extension(tmp_path, turn=False)
    assert errors == [STOP_LINE + '\n', True, STOP_LINE + '\n']


def test_the_real_plugin_logs_the_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """DSH keeps running; its logger receives the text."""
    errors = tmp_path / 'errors.txt'
    assert 'logger: { error() {} }' in holding.PLUGIN
    monkeypatch.setattr(holding, 'PLUGIN', "import { writeFileSync } from 'node:fs';\n" + holding.PLUGIN.replace(
        'logger: { error() {} }', 'logger: { error(text) { writeFileSync(process.env.TEST_ERRORS, text); } }'))
    monkeypatch.setattr(holding, 'FAKE_PLUGIN_HOST', holding.FAKE_PLUGIN_HOST + f'sys.stderr.write({STOP_LINE!r} + "\\n")\nsys.exit(1)\n')
    holding.run_plugin(tmp_path, TEST_RUN_MS='100', TEST_ERRORS=str(errors))
    assert errors.read_text() == f'agents host: {STOP_LINE}\n'
