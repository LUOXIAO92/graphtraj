"""Task 375: continuation, resume and transport residuals after Task 372."""
from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path

import pytest

from agent_swarm.codex.app_server import CodexAdapterError, CodexAppServer
from agent_swarm.codex.host import CodexHost
from graphtraj.execution import runner_heartbeat


# --- F8: Codex send failures before submission stay readable ------------------

class _FailingAdapter:
    """Raise one prepared error from send_host_event."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    async def send_host_event(self, thread_id: str, event: dict) -> dict:
        raise self.error


@pytest.fixture
def host_loop():
    """Run an event loop in a thread, as the host's native connection does."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join(5)
    loop.close()


def _host(loop: asyncio.AbstractEventLoop, error: Exception) -> CodexHost:
    host = object.__new__(CodexHost)
    host.native_session, host.loop, host.outcome = 'parent-thread', loop, None
    host.adapter, host.deliveries = _FailingAdapter(error), []
    host._display = lambda *arguments: None
    return host


_NOTICE = {'parent': None, 'agent': 'child', 'outcome': 'completed', 'body': 'child body'}


def test_f8_failure_before_write_is_not_delivered(host_loop) -> None:
    """A transport error before the write never showed the body: keep it readable."""
    error = CodexAdapterError('RUNTIME_CONNECTION_FAILED', 'Writing Codex stdio failed: closed',
                              terminal_confirmed=False)
    assert _host(host_loop, error)._receive_child(dict(_NOTICE)) is False


def test_f8_rpc_rejection_is_not_delivered(host_loop) -> None:
    """A host that refused the event did not show it either."""
    from agent_swarm.codex.app_server import CodexRPCError
    error = CodexRPCError('turn/start', 3, {'code': -32600, 'message': 'rejected'})
    assert _host(host_loop, error)._receive_child(dict(_NOTICE)) is False


def test_f8_failure_after_write_is_unconfirmed(host_loop) -> None:
    """A written event whose acknowledgement was lost stays unconfirmed."""
    error = CodexAdapterError('RUNTIME_TIMEOUT', 'timed out', terminal_confirmed=False)
    error.request_written = True
    assert _host(host_loop, error)._receive_child(dict(_NOTICE)) == 'unconfirmed'


def test_f8_malformed_reply_counts_as_written() -> None:
    """A reply with an unusable turn still proves the host received the event."""
    server = object.__new__(CodexAppServer)
    server._fail = lambda error: None

    async def reply(method, params, *, wait_for_session=False):
        return {'turn': None}

    server._call = reply
    with pytest.raises(CodexAdapterError) as raised:
        asyncio.run(server.send_host_event('thread', {'source': 'agents'}))
    assert raised.value.request_written is True


# --- F9: heartbeat leaves no temporary file in a moved directory --------------

def test_f9_move_before_replace_leaves_no_temporary(tmp_path: Path, monkeypatch) -> None:
    """Retirement moving the directory mid-write must not strand a .tmp file in it."""
    active, retained = tmp_path / 'session', tmp_path / 'trace' / 'session'
    active.mkdir()
    retained.parent.mkdir()
    real_replace = os.replace

    def move_then_replace(source, destination, **keywords):
        real_replace(active, retained)  # Retirement wins the race.
        return real_replace(source, destination, **keywords)

    monkeypatch.setattr(runner_heartbeat.os, 'replace', move_then_replace)
    runner_heartbeat.write_heartbeat(active, {'alias': 'a', 'worker_pid': os.getpid()})
    assert not active.exists()
    assert sorted(path.name for path in retained.iterdir()) == []


def test_f9_ordinary_write_leaves_only_the_record(tmp_path: Path) -> None:
    """The unchanged path still publishes the record and nothing else."""
    runner_heartbeat.write_heartbeat(tmp_path, {'alias': 'a', 'worker_pid': os.getpid()})
    assert [path.name for path in tmp_path.iterdir()] == ['heartbeat.yml']
    assert runner_heartbeat.read_heartbeat(tmp_path)['alias'] == 'a'
