"""Native Main notices whose turn/start was written but whose reply was lost.

Only the proxy transport is replaced: the real CodexAppServer._call, host
event submission and host-record check run against a daemon that records
each turn/start it receives.
"""
from pathlib import Path

import pytest
import yaml

from graphtraj.runtimes.codex import app_server, host_events
from graphtraj.runtimes.codex.codex_adapter import CodexAdapterError
from graphtraj.workspace import runner_project
from test_task_budget_control import monitor_at, sample_stop


class Daemon:
    """The parent's host: records submissions; may lose replies or record late."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.starts: list[str] = []
        self.recorded: list[str] = []
        self.later: list[str] = []
        self.reads = 0


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
                if daemon.mode == 'ok':
                    daemon.recorded.append(output)
                    future.set_result({'id': message['id'], 'result': {'turn': {
                        'id': f'turn-{len(daemon.starts)}', 'status': 'inProgress', 'items': []}}})
                    return
                (daemon.recorded if daemon.mode == 'found' else daemon.later).append(output)
                return  # Applied by the host, but the reply never arrives.
            if message['method'] == 'thread/turns/list':
                daemon.reads += 1
                if daemon.mode == 'unreadable':
                    future.set_result({'id': message['id'], 'error': {'code': -32000, 'message': 'busy'}})
                    return
                if daemon.mode == 'delayed' and daemon.reads >= 2:
                    daemon.recorded.extend(daemon.later)
                    daemon.later.clear()
                future.set_result({'id': message['id'], 'result': {'data': [
                    {'id': f'turn-{index}', 'items': [
                        {'type': 'functionCallOutput', 'id': 'item', 'name': 'graphtraj', 'output': output}]}
                    for index, output in enumerate(daemon.recorded)]}})

    monkeypatch.setattr(app_server, 'CodexAppServer', Transport)
    monkeypatch.setattr(runner_project, 'runtime_executable', lambda name: Path('/usr/bin/true'))
    monkeypatch.setattr(host_events, '_UNRESOLVED', set())
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


@pytest.mark.parametrize('mode', ['found', 'delayed'])
def test_written_notice_is_never_submitted_twice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    """A lost reply is resolved only from the host's own record, however late it appears."""
    monitor, session, notices = stopped_child(tmp_path, monkeypatch)
    daemon = Daemon(mode)
    install(daemon, tmp_path, monkeypatch)
    monitor.deliver_parent_notices(session)
    if mode == 'delayed':
        # The first notice was not recorded when read: it stays pending
        # (unresolved, never marked received) until the host records it.
        first = next(iter(notices))
        assert first in {notice['key'] for notice in monitor.pending_parent_notices()}
    monitor.deliver_parent_notices(session)  # the Worker's next one-second retry
    monitor.deliver_parent_notices(session)
    print('per-notice turn/start', submissions(daemon, notices))
    assert set(submissions(daemon, notices).values()) == {1}
    assert monitor.pending_parent_notices() == []


def test_unreadable_record_keeps_notice_pending_without_resubmission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """While the host record cannot be read, nothing is received and nothing is resent."""
    monitor, session, notices = stopped_child(tmp_path, monkeypatch)
    daemon = Daemon('unreadable')
    install(daemon, tmp_path, monkeypatch)
    for _ in range(3):
        monitor.deliver_parent_notices(session)
    assert set(submissions(daemon, notices).values()) == {1}
    assert {notice['key'] for notice in monitor.pending_parent_notices()} == set(notices)
    records = [yaml.safe_load(line) for line in (session / 'parent-notices.jsonl').read_text().splitlines()]
    assert {record['delivery'] for record in records} == {'not-delivered'}
    assert records[-1]['error']['code'] == 'delivery-unresolved'
    assert all('output' not in str(record.get('error')) for record in records)


def test_failure_before_writing_is_retried_normally(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A transport failure before turn/start is written keeps an ordinary retry."""
    monitor, session, notices = stopped_child(tmp_path, monkeypatch)
    daemon = Daemon('unreachable')
    install(daemon, tmp_path, monkeypatch)
    monitor.deliver_parent_notices(session)
    assert {notice['key'] for notice in monitor.pending_parent_notices()} == set(notices)
    daemon.mode = 'ok'
    monitor.deliver_parent_notices(session)
    assert set(submissions(daemon, notices).values()) == {1}
    assert monitor.pending_parent_notices() == []
