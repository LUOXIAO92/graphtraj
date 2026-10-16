"""Native Main notices whose turn/start was written but whose reply was lost.

Only the proxy transport is replaced: the real CodexAppServer._call and host
event submission run against a daemon that records each turn/start it receives.
"""
from pathlib import Path

import pytest
import yaml

from graphtraj.runtimes.codex import app_server
from graphtraj.runtimes.codex.codex_adapter import CodexAdapterError
from graphtraj.workspace import runner_project
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
                if daemon.mode == 'ok':
                    future.set_result({'id': message['id'], 'result': {'turn': {
                        'id': f'turn-{len(daemon.starts)}', 'status': 'inProgress', 'items': []}}})
                    return
                return  # Received by the host, but the reply never arrives.

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
    """A written turn/start whose reply is lost is named as such and stays pending.

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
