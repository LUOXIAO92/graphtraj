"""Slow native Session loading remains cancellable through its actual owners."""

import asyncio
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from graphtraj.configuration.project_roles import RolePreset
from graphtraj.configuration.role_definitions import ResolvedChildRole
from graphtraj.runtimes.codex.app_server import CodexAppServer
from graphtraj.runtimes.codex.managed_session import CodexManagedExecution
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError
from test_codex_app_server import context, peer
from test_codex_approval import ROUTE, managed, completion_stub, resume_settings


@pytest.mark.parametrize('resume', [False, True])
@pytest.mark.parametrize('outcome', ['success', 'failure', 'cancel', 'close'])
def test_session_loading_outlives_control_deadline(
    tmp_path: Path, peer: Path, resume: bool, outcome: str,
) -> None:
    """Shared Main/Worker loading waits for a result, failure or explicit stop."""
    async def exercise() -> None:
        """Use the public adapter with a delayed external native response."""
        resolved = context(tmp_path / 'worktree', peer)
        environment = {'PEER_SESSION_DELAY': '0.6' if outcome in {'success', 'failure'} else '60'}
        if outcome == 'failure':
            environment['PEER_SESSION_FAILURE'] = '1'
        async with CodexAppServer(
            cwd=tmp_path, command=[str(peer)], request_timeout=0.2,
            environment=environment,
        ) as adapter:
            loading = asyncio.create_task(
                adapter.resume_session(resolved, 'existing-thread') if resume
                else adapter.create_session(resolved)
            )
            try:
                assert (await adapter.next_notification(timeout=2))['method'] == 'thread/loading'
                if outcome == 'cancel':
                    loading.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await asyncio.wait_for(loading, 2)
                elif outcome == 'close':
                    await asyncio.wait_for(adapter.close(), 2)
                    with pytest.raises(RuntimeAdapterError) as caught:
                        await loading
                    assert caught.value.code == 'RUNTIME_CONNECTION_CLOSED'
                elif outcome == 'failure':
                    with pytest.raises(RuntimeAdapterError) as caught:
                        await asyncio.wait_for(loading, 2)
                    assert caught.value.code == 'RUNTIME_RPC_ERROR'
                else:
                    session = await asyncio.wait_for(loading, 2)
                    assert session.thread_id == ('existing-thread' if resume else 'thread-1')
                    turn = await adapter.start_execution(session, 'ready')
                    assert (await adapter.wait(turn, timeout=2))['outcome'] == 'completed'
            finally:
                loading.cancel()
                await asyncio.gather(loading, return_exceptions=True)

    asyncio.run(exercise())


@pytest.mark.parametrize('resume', [False, True])
def test_session_request_write_still_has_a_transport_deadline(
    tmp_path: Path, peer: Path, resume: bool,
) -> None:
    """A service that stops reading cannot strand a large Session request."""
    async def exercise() -> None:
        """Fill the native pipe through the public Session API."""
        role = ResolvedChildRole('temporary-role', 'x' * 1_000_000,
                                 RolePreset('codex', 'chosen-model', None, None))
        resolved = context(tmp_path / 'worktree', peer, role)
        async with CodexAppServer(
            cwd=tmp_path, command=[str(peer)], request_timeout=0.5,
            environment={'PEER_PAUSE_BEFORE_SESSION': '1'},
        ) as adapter:
            with pytest.raises(RuntimeAdapterError) as caught:
                await asyncio.wait_for(
                    adapter.resume_session(resolved, 'existing-thread') if resume
                    else adapter.create_session(resolved), 2,
                )
            assert caught.value.code == 'RUNTIME_TIMEOUT'
            assert not caught.value.terminal_confirmed

    asyncio.run(exercise())


@pytest.mark.parametrize('resume', [False, True])
def test_managed_termination_reaps_a_session_still_loading(
    tmp_path: Path, peer: Path, monkeypatch: pytest.MonkeyPatch, resume: bool,
) -> None:
    """Worker stop cancels loading before an execution ID exists and reaps Codex."""
    request, directory = managed(tmp_path, peer, monkeypatch)
    previous = None
    if resume:
        completion_stub(monkeypatch, 'accept', [])
        first = CodexManagedExecution(request, 'request: initial', directory,
            lambda *_: None, {}, directory / 'events.jsonl').run()
        previous = first['session_id']
        resume_settings(tmp_path, directory, monkeypatch, {'approval': ROUTE}, {}, False)
    loading = tmp_path / 'loading'
    monkeypatch.setenv('MANAGED_SESSION_LOADING', str(loading))
    monkeypatch.setenv('MANAGED_SESSION_DELAY', '60')
    started = []
    worker = CodexManagedExecution(request, 'hold', directory,
        lambda *args: started.append(args), {}, directory / 'events.jsonl',
        expected_session=previous)
    with ThreadPoolExecutor(max_workers=1) as executor:
        running = executor.submit(worker.run)
        try:
            deadline = time.monotonic() + 3
            while not loading.exists() and not running.done() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert loading.exists()
            pid = int(loading.read_text())
            assert worker.execution_id is None
            assert worker.terminate()
            with pytest.raises(RuntimeAdapterError) as caught:
                running.result(timeout=8)
            assert caught.value.code == 'RUNTIME_EXECUTION_INTERRUPTED'
            assert caught.value.terminal_confirmed
            assert not started
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
        finally:
            worker.terminate()
