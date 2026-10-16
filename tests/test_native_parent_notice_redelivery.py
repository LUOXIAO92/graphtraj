"""Native Main notices whose turn/start was written but whose reply was lost.

Only the proxy transport is replaced: the real CodexAppServer._call and host
event submission run against a daemon that records each turn/start it receives.
"""
import asyncio
from pathlib import Path

import pytest
import yaml

from graphtraj.runtimes.codex import app_server
from graphtraj.runtimes.codex.codex_adapter import CodexAdapterError
from graphtraj.workspace import runner_project
from test_codex_app_server import peer  # noqa: F401  (fixture)
from test_task_budget_control import monitor_at, sample_stop


class Daemon:
    """The parent's host: records each submission; may lose its reply."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.starts: list[str] = []


def install(daemon: Daemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace only the transport under the real CodexAppServer request path."""

    class Transport(app_server.CodexAppServer):
        async def __aenter__(self) -> 'Transport':
            if daemon.mode == 'unreachable':
                raise CodexAdapterError('RUNTIME_CONNECTION_FAILED', 'Codex WebSocket Upgrade failed: lost')
            self._process = object()
            self._timeout = 0.2
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def _send(self, message: dict) -> None:
            future = self._pending[message['id']]
            if message['method'] == 'turn/start':
                output = message['params']['toolOutput']['output']
                daemon.starts.append(output)
                reply = {'id': message['id'], 'result': {'turn': {
                    'id': f'turn-{len(daemon.starts)}', 'status': 'inProgress', 'items': []}}}
                if daemon.mode == 'ok':
                    future.set_result(reply)
                elif daemon.mode == 'silent':
                    return  # Alive, but never replies.
                elif daemon.mode == 'late':
                    # Replies after the ordinary deadline, on the still-open connection.
                    asyncio.get_running_loop().call_later(0.5, future.set_result, reply)
                else:
                    # Received by the host, then the proxy connection closes.
                    self._fail(CodexAdapterError('RUNTIME_CONNECTION_FAILED', 'Codex proxy closed.'))

    monkeypatch.setattr(app_server, 'CodexAppServer', Transport)
    monkeypatch.setattr(runner_project, 'runtime_executable', lambda name: Path('/usr/bin/true'))
    monkeypatch.chdir(tmp_path)


def stopped_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A real budget stop whose notices go to a native Codex Main parent."""
    monitor = monitor_at(tmp_path / 'task')
    monitor.record_session('researcher', 'researcher')
    sample_stop(monitor, monkeypatch)
    session = tmp_path / 'runner/sessions/research@x1'
    session.mkdir(parents=True)
    (session / 'launch.yml').write_text(yaml.safe_dump({'operation': 'launch', 'mapping': {
        'alias': session.name, 'task_id': '153', 'parent': None,
        'parent_connection': {'runtime': 'codex', 'session': 'main-thread',
                              'codex_home': str(tmp_path / 'codex-home')}}}))
    notices = {notice['key']: notice['message'] for notice in monitor.pending_parent_notices()}
    assert len(set(notices.values())) == len(notices)  # distinct identities
    return monitor, session, notices


def submissions(daemon: Daemon, notices: dict) -> dict:
    """turn/start submissions per notice identity."""
    return {key: sum(message in sent for sent in daemon.starts) for key, message in notices.items()}


def records(session: Path) -> list[dict]:
    """The notifying Session's retained delivery records."""
    return [yaml.safe_load(line) for line in (session / 'parent-notices.jsonl').read_text().splitlines()]


def test_unacknowledged_notice_is_classified_and_never_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A written turn/start whose connection then closes is named as such and stays pending.

    Codex 0.163 offers no safe native way to tell whether it was applied, so the
    retry submits it again: this records that gap rather than claiming a fix.
    """
    monitor, session, notices = stopped_child(tmp_path, monkeypatch)
    daemon = Daemon('lost')
    install(daemon, tmp_path, monkeypatch)
    monitor.deliver_parent_notices(session)
    assert {notice['key'] for notice in monitor.pending_parent_notices()} == set(notices)
    assert {(record['delivery'], record['error']['code']) for record in records(session)} == {
        ('not-delivered', 'delivery-unconfirmed')}
    monitor.deliver_parent_notices(session)  # the Worker's next one-second retry
    print('per-notice turn/start', submissions(daemon, notices))
    assert set(submissions(daemon, notices).values()) == {2}  # known gap: resubmitted


def test_late_reply_on_open_connection_is_awaited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A reply slower than the ordinary deadline is awaited, so nothing is resubmitted."""
    monitor, session, notices = stopped_child(tmp_path, monkeypatch)
    daemon = Daemon('late')
    install(daemon, tmp_path, monkeypatch)
    monitor.deliver_parent_notices(session)
    monitor.deliver_parent_notices(session)
    assert set(submissions(daemon, notices).values()) == {1}
    assert monitor.pending_parent_notices() == []
    assert {record['delivery'] for record in records(session)} == {'received'}


def test_failure_before_writing_is_retried_normally(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A transport failure before turn/start is written keeps its own code and an ordinary retry."""
    monitor, session, notices = stopped_child(tmp_path, monkeypatch)
    daemon = Daemon('unreachable')
    install(daemon, tmp_path, monkeypatch)
    monitor.deliver_parent_notices(session)
    assert {notice['key'] for notice in monitor.pending_parent_notices()} == set(notices)
    assert {record['error']['code'] for record in records(session)} == {'RUNTIME_CONNECTION_FAILED'}
    daemon.mode = 'ok'
    monitor.deliver_parent_notices(session)
    assert set(submissions(daemon, notices).values()) == {1}
    assert monitor.pending_parent_notices() == []


def test_cancelling_a_waiting_sender_returns_promptly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a reply deadline, cancellation (stop or interrupt) still wakes the sender."""
    import time

    daemon = Daemon('silent')
    install(daemon, tmp_path, monkeypatch)

    async def cancel_while_waiting() -> None:
        async with app_server.CodexAppServer(cwd=tmp_path, command=('codex', 'app-server', 'proxy')) as client:
            sending = asyncio.create_task(client.send_host_event('main-thread', {
                'source': 'graphtraj', 'alias': 'research@x1', 'event': 'completed', 'message': 'done'}))
            await asyncio.sleep(0.5)  # past the ordinary deadline, still waiting
            assert not sending.done()
            sending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await sending

    started = time.monotonic()
    asyncio.run(asyncio.wait_for(cancel_while_waiting(), timeout=5))
    assert time.monotonic() - started < 2 and len(daemon.starts) == 1


SENDER = '''
import asyncio, sys
from pathlib import Path
from graphtraj.runtimes.codex import app_server, host_events
from graphtraj.workspace import runner_project

marks = Path(sys.argv[1])

class Transport(app_server.CodexAppServer):
    """Alive, but never replies to turn/start; records its own close."""
    async def __aenter__(self):
        self._process = object()
        self._timeout = 0.2
        return self
    async def __aexit__(self, *args):
        with marks.open('a') as stream:
            stream.write('closed\\n')
    async def _send(self, message):
        with marks.open('a') as stream:
            stream.write('written\\n')

app_server.CodexAppServer = Transport
runner_project.runtime_executable = lambda name: Path('/usr/bin/true')
result = host_events.send_event(
    {'runtime': 'codex', 'session': 'main-thread', 'codex_home': str(marks.parent)},
    {'source': 'graphtraj', 'alias': 'research@x1', 'event': 'completed', 'message': 'done'})
with marks.open('a') as stream:
    stream.write('received\\n')
'''


def test_stop_signal_ends_a_waiting_production_sender_and_closes_its_proxy(tmp_path: Path) -> None:
    """send_event, run as the CLI runs it, stops on SIGINT and closes its proxy."""
    import os
    import signal
    import subprocess
    import sys
    import time

    marks = tmp_path / 'marks'
    sender = subprocess.Popen([sys.executable, '-c', SENDER, str(marks)], cwd=tmp_path,
                              stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + 5
    while 'written' not in (marks.read_text() if marks.exists() else ''):
        assert time.monotonic() < deadline and sender.poll() is None, sender.stderr.read()
        time.sleep(0.05)
    time.sleep(0.5)  # past the ordinary deadline, still awaiting the reply
    assert sender.poll() is None
    stopped = time.monotonic()
    sender.send_signal(signal.SIGINT)
    try:
        sender.wait(timeout=2)
    finally:
        if sender.poll() is None:
            os.kill(sender.pid, signal.SIGKILL)
    assert time.monotonic() - stopped < 2
    assert sender.returncode != 0
    assert marks.read_text().splitlines() == ['written', 'closed']  # closed, never received


WORKER_LIKE = '''
import os, signal, sys, threading, time
from pathlib import Path
from graphtraj.runtimes.codex import app_server, host_events
from graphtraj.workspace import runner_project

marks, peer = Path(sys.argv[1]), Path(sys.argv[2])

def note(text):
    with marks.open('a') as stream:
        stream.write(text + '\\n')

from graphtraj.execution.runner_worker import DELIVERY_JOIN_SECONDS

stopping = threading.Event()

def request_termination(signum, frame):
    # Like the Worker during a managed execution: SIGTERM does not raise.
    note('worker-sigterm')
    stopping.set()

signal.signal(signal.SIGTERM, request_termination)
runner_project.runtime_executable = lambda name: peer
close = app_server.CodexAppServer.close

async def recorded_close(self):
    await close(self)
    note(f'proxy-exit {self._process.returncode}')

app_server.CodexAppServer.close = recorded_close

def deliver():
    try:
        host_events.send_event(
            {'runtime': 'codex', 'session': 'main-thread', 'codex_home': str(marks.parent)},
            {'source': 'graphtraj', 'alias': 'research@x1', 'event': 'completed', 'message': 'done'})
        note('received')
    except Exception as error:
        note('sender-error ' + getattr(error, 'code', type(error).__name__))

sender = threading.Thread(target=deliver, daemon=True)
sender.start()
stopping.wait()
# The Worker leaves its loop and joins its delivery thread (runner_worker.py:507-510).
sender.join(timeout=DELIVERY_JOIN_SECONDS)
note('worker-exit sender-' + ('alive' if sender.is_alive() else 'ended'))
'''


def test_real_worker_stop_with_a_sender_awaiting_a_written_host_event(tmp_path: Path, peer: Path) -> None:
    """The Runner's group stop, on a Worker whose sender awaits a written host event."""
    import os
    import signal
    import subprocess
    import sys
    import time

    from graphtraj.execution.runner_process import stop_worker

    marks, written = tmp_path / 'marks', tmp_path / 'written'
    worker = subprocess.Popen(
        [sys.executable, '-c', WORKER_LIKE, str(marks), str(peer)], cwd=tmp_path,
        env={**os.environ, 'PEER_SILENT_TURN_START': str(written)},
        stderr=subprocess.PIPE, text=True, start_new_session=True)
    pgid = worker.pid
    deadline = time.monotonic() + 10
    while not written.exists():
        assert time.monotonic() < deadline and worker.poll() is None, worker.stderr.read()
        time.sleep(0.05)
    time.sleep(0.5)  # turn/start written; still awaiting its reply
    started = time.monotonic()
    stopped = stop_worker(worker.pid)  # the real Worker stop (runner_process.py:132-148)
    elapsed = time.monotonic() - started
    try:
        status = worker.wait(timeout=5)  # reap after the stop's own bound, if still pending
    except subprocess.TimeoutExpired:
        status = None
    exited = time.monotonic() - started
    proxy = int(written.read_text())  # the proxy pid, in its own session (app_server.py:272-276)

    def gone(check) -> bool:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                check()
            except ProcessLookupError:
                return True
            time.sleep(0.05)
        return False

    group_gone = gone(lambda: os.killpg(pgid, 0))
    proxy_gone = gone(lambda: os.kill(proxy, 0))
    lines = marks.read_text().splitlines()
    cleanup = not (group_gone and proxy_gone)
    for pid, check in ((pgid, lambda: os.killpg(pgid, signal.SIGKILL)),
                       (proxy, lambda: os.kill(proxy, signal.SIGKILL))):
        try:
            check()
        except ProcessLookupError:
            pass
    print('marks', lines, 'stop_worker', stopped, 'elapsed', round(elapsed, 2),
          'worker-status', status, 'worker-exited-after', round(exited, 2),
          'group-gone', group_gone, 'proxy-gone', proxy_gone, 'cleanup-needed', cleanup)
    assert 'worker-sigterm' in lines and 'received' not in lines
    assert group_gone and proxy_gone and not cleanup
    assert stopped and status is not None  # confirmed by an actual reap within the stop's bound
