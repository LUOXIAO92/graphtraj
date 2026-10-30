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

from agent_swarm import AgentsError, AgentsResult, Caller, bind, shutdown
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

    assert process.host.stop_children(process.inner) == []
    assert all(standby(process, agent) for agent in order)
    assert sorted(driver.interrupted) == sorted(order)
    assert driver.interrupted.index(grandchild) < driver.interrupted.index(first)
    for agent in order:
        assert read_record(process.tmp, agent)['executions'][-1]['outcome'] == 'interrupted'


def test_every_child_is_interrupted_before_any_is_waited_for(build: Callable) -> None:
    """The stops run in parallel, so the shared deadline covers them all at once."""
    driver = Stopping()
    process, first, second, grandchild = family(build, driver)
    process.host.stop_children(process.inner)
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
    assert process.host.stop_children(process.inner) == list(driver.stubborn)
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
    unconfirmed = process.host.stop_children(process.inner)
    bad = list(driver.broken)
    assert unconfirmed == bad
    assert all(standby(process, agent) for agent in {first, second, grandchild} - set(bad))


def test_an_agent_that_was_still_starting_is_interrupted_again(build: Callable) -> None:
    """``starting`` is refused once; the next pass reaches it, so nothing is left."""
    driver = Stopping()
    process, first, second, grandchild = family(build, driver)
    driver.broken[second] = [AgentsError('starting', 'The execution is still starting.')]
    assert process.host.stop_children(process.inner) == []
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
    began = time.monotonic()
    assert process.host.stop_children(status_that(process.inner, behave)) == [shutdown.STATUS_UNREADABLE]
    assert time.monotonic() - began < 3.0
    process.host.stop_children(process.inner)  # no timer outlives the test


def test_a_status_lost_after_the_first_keeps_every_agent_unconfirmed(build: Callable) -> None:
    """Interrupted, but never seen to end: each one is named, none is claimed stopped."""
    driver = Stopping()
    process, first, second, grandchild = family(build, driver)
    call = status_that(process.inner, lambda count, real: real() if count == 1 else FAILED)
    assert sorted(process.host.stop_children(call)) == sorted([first, second, grandchild])
    assert sorted(driver.interrupted) == sorted([first, second, grandchild])
    wait_until(lambda: all(standby(process, agent) for agent in (first, second, grandchild)))


def test_a_status_that_recovers_stops_everything(build: Callable) -> None:
    """One failed read costs a pass, not the shutdown."""
    driver = Stopping()
    process, first, second, grandchild = family(build, driver)
    call = status_that(process.inner, lambda count, real: FAILED if count == 1 else real())
    assert process.host.stop_children(call) == []
    assert all(standby(process, agent) for agent in (first, second, grandchild))


# --- The real main() in a real process, closed by ending its stdin ---

# How long a host process may take to end, its 10-second stop included.
HOST_LIMIT = 30

HOST = r'''
import importlib, json, os, subprocess, sys, threading, time
from pathlib import Path
import agent_swarm
from agent_swarm import Caller, bind, shutdown

kind, where, stubborn = os.environ['TEST_KIND'], Path(os.environ['TEST_WHERE']), os.environ['TEST_STUBBORN']
host = importlib.import_module(f'agent_swarm.{kind}.host')
if os.environ.get('TEST_STOP_SECONDS'):
    shutdown.STOP_SECONDS = float(os.environ['TEST_STOP_SECONDS'])
facts = {'module': agent_swarm.__file__}


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
        if run.agent != facts.get('stubborn'):
            threading.Timer(0.2, self.stops[run.agent].set).start()
        return True

    def requests(self, run):
        return []

    def reply(self, run, request, response):
        return {}


driver = Driver()
real_start = host.start


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
    (where / 'facts.json').write_text(json.dumps(facts))
    return result


host.verify_native_parent = lambda *_: None
host.runtime_drivers = lambda *_: {'claude': driver}
host.start = started
if kind == 'pi':
    host.pi_request = lambda *_: {}
    host.current_connection = lambda: {'runtime': 'pi', 'session': 'main', 'session_file': str(where / 's.jsonl')}
sys.argv = ['host', '--config', str(where / 'host.json')]
host.main()
'''


def run_host(tmp_path: Path, kind: str, position: str = 'first', stubborn: str = '', stop_seconds: float | None = None,
             then: str = '') -> tuple[subprocess.CompletedProcess, dict]:
    """Run ``main()`` in its own process group, end its stdin and wait at most ``HOST_LIMIT``."""
    script = tmp_path / 'run-host.py'
    script.write_text(HOST)
    (tmp_path / 'host.json').write_text(json.dumps({'root': str(tmp_path / 'data')}))
    if kind == 'pi':
        header = {'type': 'session', 'version': 3, 'id': 'main', 'cwd': str(tmp_path)}
        launch = json.dumps({'header': header, 'entries': []})
    else:
        launch = json.dumps({'header': {'version': 4, 'id': 'main', 'cwd': str(tmp_path), 'isSeeded': False}})
    # Built, not copied: nothing of the real environment reaches this process or its output.
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path), 'PYTHONPATH': str(SOURCE), 'TEST_KIND': kind,
           'TEST_WHERE': str(tmp_path), 'TEST_POSITION': position, 'TEST_STUBBORN': stubborn,
           'AGENT_SWARM_PI_ENTRY': sys.executable}
    if stop_seconds is not None:
        env['TEST_STOP_SECONDS'] = str(stop_seconds)
    process = subprocess.Popen([sys.executable, str(script)], cwd=tmp_path, env=env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        # communicate reads to EOF: like Node's close, it also waits for whoever holds the pipes.
        stdout, stderr = process.communicate(launch + '\n' + then, timeout=HOST_LIMIT)
    except subprocess.TimeoutExpired:
        pytest.fail(f'The host process did not exit within {HOST_LIMIT} seconds.')
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        process.wait(5)
    facts = json.loads((tmp_path / 'facts.json').read_text())
    assert Path(facts['module']).is_relative_to(SOURCE)
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
