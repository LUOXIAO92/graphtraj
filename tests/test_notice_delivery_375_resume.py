"""Task 375: continuation, resume and transport residuals after Task 372."""
from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path

import pytest
import yaml

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


# --- F2, F4, F7: held ends and budget notices across stop and continuation ---

from graphtraj.execution import runner_control  # noqa: E402
from test_notice_delivery_372 import (  # noqa: E402,F401
    DELIVERED, MAPPINGS, _deliver_received, records, runner, stopped_monitor,
)


def _hold_analyst_end(runner: Path) -> Path:
    """The analyst's end, stopped by the Task's budget, held for its Leader."""
    analyst = runner / 'sessions' / 'analyst'
    receipt = runner_control.deliver_execution_end(
        analyst, MAPPINGS['analyst'], {'outcome': 'interrupted', 'budget_stopped': True},
        parent_input=True)
    assert receipt['held'] == 'budget-stop'
    return analyst


@pytest.fixture
def leader_sends(tmp_path: Path, runner: Path, monkeypatch):
    """Parent input to the Leader through the real send entry, with a stopped Task."""
    DELIVERED.clear()
    monkeypatch.setitem(MAPPINGS, 'leader', dict(MAPPINGS['leader'], worktree_path=str(tmp_path)))
    monkeypatch.setattr(runner_control, 'deliver_parent_event', _deliver_received)
    monkeypatch.setattr(runner_control, 'require_execution_allowed', lambda *_, **__: None)
    monkeypatch.setattr(runner_control, '_send_session_locked',
                        lambda *_, **__: {'send_status': 'sent'})
    monitor = stopped_monitor(tmp_path, monkeypatch)
    monkeypatch.setattr(runner_control, '_task_budget_monitor', lambda *_: monitor, raising=False)
    leader = runner / 'sessions' / 'leader'

    def send() -> None:
        runner_control._send_session('leader', 'report', leader, MAPPINGS['leader'], (), tmp_path)

    return monitor, send


def test_f2_input_to_a_stopped_parent_keeps_held_ends_until_continuation(
        runner: Path, leader_sends) -> None:
    """U1: a report request to a still-stopped Leader delivers no budget-held end."""
    monitor, send = leader_sends
    _hold_analyst_end(runner)
    send()                                         # report-only turn while stopped
    assert DELIVERED == []
    assert [directory.name for directory, _ in runner_control.held_ends(runner, 'leader')] == ['analyst']
    monitor.continue_after_stop()
    send()                                         # ordinary input after continuation
    send()
    assert [(alias, kind) for alias, kind, _ in DELIVERED] == [('analyst', 'interrupted')]


def test_f4_budget_notices_held_over_a_budget_only_continuation_arrive_once(
        runner: Path, leader_sends, monkeypatch) -> None:
    """After a budget-only continuation, the Leader's next ordinary input gets them once."""
    monitor, send = leader_sends
    sent: list[str] = []
    monkeypatch.setattr(runner_control, 'notify_direct_parent',
                        lambda directory, message, identity, **_: sent.append(identity['key'])
                        or {'delivery': 'received'})
    keys = [notice['key'] for notice in monitor.pending_parent_notices()]
    assert keys and monitor.deliver_parent_notices(runner / 'sessions' / 'engineer') is True
    send()                                         # still stopped: nothing yet
    assert sent == []
    monitor.continue_after_stop()                  # budget-only: resumes no Session
    send()
    send()
    assert sent == keys
    assert monitor.pending_parent_notices() == []


def test_f7b_stale_concurrent_scans_deliver_a_held_end_once(runner: Path, monkeypatch) -> None:
    """Two callers that scanned before either delivered still deliver the end once."""
    DELIVERED.clear()
    monkeypatch.setattr(runner_control, 'deliver_parent_event', _deliver_received)
    _hold_analyst_end(runner)
    first = runner_control.held_ends(runner, 'leader', frozenset({'budget-stop'}))
    second = runner_control.held_ends(runner, 'leader', frozenset({'budget-stop'}))
    runner_control.deliver_held_ends(first)
    runner_control.deliver_held_ends(second)       # e.g. the aggregate-failure fallback
    assert [(alias, kind) for alias, kind, _ in DELIVERED] == [('analyst', 'interrupted')]


def test_f7b_concurrent_threads_deliver_a_held_end_once(runner: Path, monkeypatch) -> None:
    """While one delivery is in flight, another found by an earlier scan waits and skips."""
    DELIVERED.clear()
    entered, release = threading.Event(), threading.Event()

    def slow(directory: Path, message: str, identity: dict) -> dict:
        entered.set()
        release.wait(5)
        return _deliver_received(directory, message, identity)

    monkeypatch.setattr(runner_control, 'deliver_parent_event', slow)
    _hold_analyst_end(runner)
    scans = [runner_control.held_ends(runner, 'leader') for _ in range(2)]
    threads = [threading.Thread(target=runner_control.deliver_held_ends, args=(held,)) for held in scans]
    threads[0].start()
    assert entered.wait(5)
    threads[1].start()
    threads[1].join(0.3)
    release.set()
    for thread in threads:
        thread.join(5)
    assert len(DELIVERED) == 1


def test_f7a_a_hold_written_after_continuation_scanned_is_delivered(
        tmp_path: Path, runner: Path, monkeypatch) -> None:
    """A Worker's late budget-stop hold reaches a continued, running parent once."""
    DELIVERED.clear()
    monkeypatch.setattr(runner_control, 'deliver_parent_event', _deliver_received)
    monitor = stopped_monitor(tmp_path, monkeypatch)
    monkeypatch.setattr(runner_control, '_task_budget_monitor', lambda *_: monitor, raising=False)
    activity = {'value': 'running'}
    monkeypatch.setattr(runner_control, 'owning_execution',
                        lambda *_: {'activity': activity['value']})
    monkeypatch.setattr(runner_control, 'runner_project_root', lambda _: tmp_path)
    release = getattr(runner_control, 'release_late_hold', None)
    assert release is not None, 'no late-hold release after the Worker writes a hold'

    analyst = _hold_analyst_end(runner)            # still stopped: stays held
    release(analyst, MAPPINGS['analyst'])
    assert DELIVERED == []
    monitor.continue_after_stop()                  # continuation resumed the Leader, scanned
    release(analyst, MAPPINGS['analyst'])          # ...then the hold was written
    release(analyst, MAPPINGS['analyst'])
    runner_control.deliver_held_ends(runner_control.held_ends(runner, 'leader'))
    assert [(alias, kind) for alias, kind, _ in DELIVERED] == [('analyst', 'interrupted')]


def test_f7a_a_late_hold_waits_for_a_parent_left_stopped(
        tmp_path: Path, runner: Path, monkeypatch) -> None:
    """A budget-only continuation resumes no parent, so the late hold keeps waiting."""
    DELIVERED.clear()
    monkeypatch.setattr(runner_control, 'deliver_parent_event', _deliver_received)
    monitor = stopped_monitor(tmp_path, monkeypatch)
    monitor.continue_after_stop()
    monkeypatch.setattr(runner_control, '_task_budget_monitor', lambda *_: monitor, raising=False)
    monkeypatch.setattr(runner_control, 'owning_execution', lambda *_: None)
    monkeypatch.setattr(runner_control, 'runner_project_root', lambda _: tmp_path)
    analyst = _hold_analyst_end(runner)
    release = getattr(runner_control, 'release_late_hold', None)
    assert release is not None
    release(analyst, MAPPINGS['analyst'])
    assert DELIVERED == []
    assert [directory.name for directory, _ in runner_control.held_ends(runner, 'leader')] == ['analyst']


def test_f5_continuation_leaves_a_stopped_non_root_parents_notices_for_its_input(
        tmp_path: Path, runner: Path, monkeypatch) -> None:
    """A notice for a non-root parent the stop ended waits for that parent's own input."""
    DELIVERED.clear()
    # The engineer observed the threshold; its parent is a Reviewer under the Leader.
    monkeypatch.setitem(MAPPINGS, 'engineer', dict(MAPPINGS['engineer'], parent='reviewer'))
    monkeypatch.setitem(MAPPINGS, 'reviewer', {'alias': 'reviewer', 'task_id': '153', 'parent': 'leader',
                                               'session': 's-r', 'execution_id': 'r1',
                                               'worktree_path': str(tmp_path)})
    (runner / 'sessions' / 'engineer' / 'launch.yml').write_text(
        yaml.safe_dump({'operation': 'launch', 'mapping': MAPPINGS['engineer']}))
    reviewer = runner / 'sessions' / 'reviewer'
    reviewer.mkdir()
    (reviewer / 'launch.yml').write_text(yaml.safe_dump({'operation': 'launch', 'mapping': MAPPINGS['reviewer']}))
    (reviewer / 'execution.yml').write_text(yaml.safe_dump({'outcome': 'interrupted', 'budget_stopped': True}))
    sent: list[str] = []
    monkeypatch.setattr(runner_control, 'notify_direct_parent',
                        lambda directory, message, identity, **_: sent.append(identity['key'])
                        or {'delivery': 'received'})
    monitor = stopped_monitor(tmp_path, monkeypatch)
    keys = [notice['key'] for notice in monitor.pending_parent_notices()]
    engineer = runner / 'sessions' / 'engineer'
    monitor.continue_after_stop()                  # resumes the Leader only
    assert monitor.deliver_parent_notices(engineer) is True     # as the continuation does
    assert sent == []
    # The Leader's own input resumes the Reviewer: its new execution replaces the record.
    monkeypatch.setattr(runner_control, 'deliver_parent_event', _deliver_received)
    monkeypatch.setattr(runner_control, 'require_execution_allowed', lambda *_, **__: None)
    monkeypatch.setattr(runner_control, '_send_session_locked',
                        lambda *_, **__: (reviewer / 'execution.yml').unlink(missing_ok=True)
                        or {'send_status': 'sent'})
    monkeypatch.setattr(runner_control, '_task_budget_monitor', lambda *_: monitor, raising=False)
    for _ in range(2):
        runner_control._send_session('reviewer', 'continue', reviewer, MAPPINGS['reviewer'], (), tmp_path)
    assert sent == keys and monitor.pending_parent_notices() == []
