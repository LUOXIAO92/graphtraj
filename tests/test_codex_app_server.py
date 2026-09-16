"""Behavior at the production Session Adapter's public stdio seam."""

from __future__ import annotations

import asyncio
import errno
import json
import os
from dataclasses import replace
import sys
from pathlib import Path

import pytest
import yaml

from graphtraj.configuration.project_roles import RolePreset
from graphtraj.configuration.role_definitions import ResolvedChildRole
from graphtraj.runtimes.codex.codex_adapter import (
    preflight_runtime_context,
    read_codex_last_agent_message,
)
from graphtraj.runtimes.codex.app_server import (
    CodexAppServer,
    CodexMainRecovery,
    CodexServerRequest,
    CodexSession,
)
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError, RuntimeContext


@pytest.fixture
def peer(tmp_path: Path) -> Path:
    """Provide an executable external Runtime peer, including role preflight."""
    executable = tmp_path / 'codex-peer'
    executable.write_text('#!' + sys.executable + '\n' +
                          Path(__file__).with_name('codex_stdio_peer.py').read_text())
    executable.chmod(0o755)
    return executable


def context(
    root: Path,
    executable: Path,
    role: ResolvedChildRole | None = None,
    requested_skills: tuple[str, ...] = (),
    report_files: tuple[Path, ...] = (),
) -> RuntimeContext:
    """Resolve real packaged permissions without unrelated Runner dispatch."""
    root.mkdir(exist_ok=True)
    return preflight_runtime_context(
        runtime_store=root / '.codex', executable=executable,
        git_common_directory=root / 'git-common',
        role=role or ResolvedChildRole('temporary-role', 'Follow the bounded task.', (),
                               RolePreset('codex', 'chosen-model', None, None,
                                          reasoning_effort='low')),
        worktree=root, evidence=root / 'evidence',
        repository_skill_source=root, requested_skills=requested_skills,
        report_files=report_files,
    ).finalize()


def test_session_execution_result_and_resume_survive_turn_completion(
    tmp_path: Path, peer: Path,
) -> None:
    """A completed native turn leaves the connection usable and history resumable."""

    async def exercise() -> None:
        resolved = context(tmp_path / 'worktree', peer)
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path) as adapter:
            session = await adapter.create_session(resolved)
            execution = await adapter.start_execution(session, 'first output')
            result = await adapter.wait(execution, timeout=2)
            assert result == {
                'outcome': 'completed', 'session_id': 'thread-1',
                'execution_id': 'turn-1', 'last_agent_message': 'first output',
            }
            assert session.thread_id == execution.thread_id == 'thread-1'
            assert execution.turn_id == 'turn-1'
            assert session.rollout_path == Path('/native/thread-1.jsonl')
            continued = await adapter.start_execution(session, 'continued output')
            assert (await adapter.wait(continued, timeout=2))['last_agent_message'] == 'continued output'
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path) as adapter:
            resumed = await adapter.resume_session(resolved, session.thread_id)
            assert resumed.thread_id == session.thread_id
            execution = await adapter.start_execution(resumed, 'resumed output')
            assert (await adapter.wait(execution, timeout=2))['last_agent_message'] == 'resumed output'

    asyncio.run(exercise())


def test_native_trace_retains_one_app_server_session_incrementally_and_on_resume(
    tmp_path: Path, peer: Path,
) -> None:
    """Raw rollout records remain complete, readable, and unique across continuation."""

    async def exercise() -> None:
        trace_directory = tmp_path / 'trace'
        trace_file = trace_directory / 'events.jsonl'
        rollout_root = tmp_path / 'native-rollouts'
        environment = {'PEER_NATIVE_ROLLOUT': str(rollout_root)}
        resolved = context(tmp_path / 'worktree', peer)

        async with CodexAppServer(command=[str(peer)], cwd=tmp_path, environment=environment) as adapter:
            session = await adapter.create_session(resolved)
            adapter.retain_native_trace(session, trace_directory)
            starting = asyncio.create_task(adapter.start_execution(session, 'first native result'))
            while b'"encrypted_content":"opaque"' not in trace_file.read_bytes():
                await asyncio.sleep(0.01)
            assert not starting.done()
            assert b'"timestamp":"native-3"' not in trace_file.read_bytes()

            execution = await starting
            result = await adapter.wait(execution, timeout=2)
            assert result['last_agent_message'] == 'first native result'
            first_trace = trace_file.read_bytes()
            assert first_trace == (
                b'{"type":"runtime","runtime":"codex"}\n'
                + session.rollout_path.read_bytes()
            )
            assert b'"encrypted_content":"opaque"' in first_trace

        async with CodexAppServer(command=[str(peer)], cwd=tmp_path, environment=environment) as adapter:
            resumed = await adapter.resume_session(resolved, session.thread_id)
            adapter.retain_native_trace(resumed, trace_directory)
            execution = await adapter.start_execution(resumed, 'resumed native result')
            result = await adapter.wait(execution, timeout=2)
            assert result['last_agent_message'] == 'resumed native result'

        trace = trace_file.read_bytes()
        assert trace.startswith(first_trace)
        assert trace.count(b'"timestamp":"native-1"') == 1
        assert trace.count(b'"timestamp":"native-5"') == 1
        assert read_codex_last_agent_message(trace_file) == 'resumed native result'

    asyncio.run(exercise())


def test_terminal_trace_failure_keeps_confirmed_execution_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    peer: Path,
) -> None:
    """A post-terminal Trace failure keeps the native execution confirmation."""

    from graphtraj.runtimes.codex import codex_adapter

    original_append = codex_adapter._append_native_records
    failing = False

    def append_or_fail(*args: object, **kwargs: object) -> int:
        if failing:
            raise OSError(errno.ENOSPC, 'No space left on device')
        return original_append(*args, **kwargs)

    monkeypatch.setattr(codex_adapter, '_append_native_records', append_or_fail)

    async def exercise() -> None:
        nonlocal failing

        environment = {'PEER_NATIVE_ROLLOUT': str(tmp_path / 'native-rollouts')}
        trace_directory = tmp_path / 'trace'
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path, environment=environment) as adapter:
            session = await adapter.create_session(context(tmp_path / 'worktree', peer))
            adapter.retain_native_trace(session, trace_directory)
            execution = await adapter.start_execution(session, 'hold')
            await adapter.interrupt(execution)
            assert session.rollout_path is not None
            session.rollout_path.parent.mkdir(parents=True, exist_ok=True)
            session.rollout_path.write_text(
                json.dumps({'timestamp': 'terminal-tail', 'type': 'event_msg'}) + '\n',
                encoding='utf-8',
            )
            failing = True
            try:
                with pytest.raises(RuntimeAdapterError) as caught:
                    await adapter.wait(execution, timeout=2)
            finally:
                failing = False

            assert caught.value.code == 'RUNTIME_TRACE_FAILED'
            assert caught.value.terminal_confirmed is True
            assert isinstance(caught.value.__cause__, RuntimeAdapterError)
            assert caught.value.__cause__.terminal_confirmed is False
            assert isinstance(caught.value.__cause__.__cause__, OSError)

    asyncio.run(exercise())


def test_position_storage_failure_never_replays_native_records(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    peer: Path,
) -> None:
    """A failed position checkpoint is retried before any later native append."""

    from graphtraj.runtimes.codex import codex_adapter

    original_write = codex_adapter.write_yaml_durably
    failed = False

    def write_position_once(path: Path, document: object) -> None:
        nonlocal failed

        if path.name == 'native-session.yml' and not failed:
            failed = True
            raise OSError(errno.ENOSPC, 'No space left on device')
        original_write(path, document)

    monkeypatch.setattr(codex_adapter, 'write_yaml_durably', write_position_once)

    async def exercise() -> None:
        environment = {'PEER_NATIVE_ROLLOUT': str(tmp_path / 'native-rollouts')}
        trace_directory = tmp_path / 'trace'
        trace_file = trace_directory / 'events.jsonl'
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path, environment=environment) as adapter:
            session = await adapter.create_session(context(tmp_path / 'worktree', peer))
            adapter.retain_native_trace(session, trace_directory)
            execution = await adapter.start_execution(session, 'hold')
            assert session.rollout_path is not None
            session.rollout_path.parent.mkdir(parents=True, exist_ok=True)
            session.rollout_path.write_text(
                json.dumps({'timestamp': 'position-tail', 'type': 'event_msg'}) + '\n',
                encoding='utf-8',
            )
            with pytest.raises(RuntimeAdapterError) as caught:
                await adapter.wait(execution, timeout=2)

            assert caught.value.code == 'RUNTIME_TRACE_FAILED'
            assert trace_file.read_bytes().count(b'"timestamp": "position-tail"') == 1
            retained = yaml.safe_load((trace_directory / 'native-session.yml').read_text())
            assert retained['position'] == session.rollout_path.stat().st_size

        assert trace_file.read_bytes().count(b'"timestamp": "position-tail"') == 1

    asyncio.run(exercise())


def test_initial_trace_checkpoint_failure_is_settled_before_same_session_resume(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    peer: Path,
) -> None:
    """Close retains an initial collector's pending position before reconnecting."""

    from graphtraj.runtimes.codex import codex_adapter

    session_id = 'thread-1'
    rollout = tmp_path / 'native-rollouts' / ('rollout-' + session_id + '.jsonl')
    prefix = (json.dumps({'timestamp': 'prefix', 'type': 'session_meta'}) + '\n').encode()
    appended = (json.dumps({'timestamp': 'initial-tail', 'type': 'event_msg'}) + '\n').encode()
    rollout.parent.mkdir(parents=True)
    rollout.write_bytes(prefix + appended)
    trace_directory = tmp_path / 'trace'
    trace_directory.mkdir()
    (trace_directory / 'events.jsonl').write_bytes(
        b'{"type":"runtime","runtime":"codex"}\n' + prefix
    )
    (trace_directory / 'native-session.yml').write_text(
        yaml.safe_dump({'path': str(rollout), 'position': len(prefix)}),
        encoding='utf-8',
    )

    original_write = codex_adapter.write_yaml_durably
    failed = False

    def fail_initial_checkpoint(path: Path, document: object) -> None:
        nonlocal failed

        if path.name == 'native-session.yml' and not failed:
            failed = True
            raise OSError(errno.ENOSPC, 'No space left on device')
        original_write(path, document)

    monkeypatch.setattr(codex_adapter, 'write_yaml_durably', fail_initial_checkpoint)

    async def exercise() -> None:
        environment = {'PEER_NATIVE_ROLLOUT': str(rollout.parent)}
        resolved = context(tmp_path / 'worktree', peer)
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path, environment=environment) as adapter:
            session = await adapter.resume_session(resolved, session_id)
            with pytest.raises(RuntimeAdapterError) as caught:
                adapter.retain_native_trace(session, trace_directory)
            assert caught.value.code == 'RUNTIME_TRACE_FAILED'
            assert isinstance(caught.value.__cause__, OSError)
            assert isinstance(caught.value.__cause__.__cause__, OSError)
            assert caught.value.__cause__.__cause__.errno == errno.ENOSPC

        async with CodexAppServer(command=[str(peer)], cwd=tmp_path, environment=environment) as adapter:
            session = await adapter.resume_session(resolved, session_id)
            adapter.retain_native_trace(session, trace_directory)

        trace = (trace_directory / 'events.jsonl').read_bytes()
        assert trace.count(appended) == 1
        retained = yaml.safe_load((trace_directory / 'native-session.yml').read_text())
        assert retained['position'] == len(prefix + appended)

    asyncio.run(exercise())


def test_active_input_and_interrupt_target_only_the_expected_execution(
    tmp_path: Path, peer: Path,
) -> None:
    """Independent Sessions continue while a selected execution is interrupted."""

    async def exercise() -> None:
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path) as adapter:
            first = await adapter.create_session(context(tmp_path / 'first', peer))
            second = await adapter.create_session(context(tmp_path / 'second', peer))
            target = await adapter.start_execution(first, 'hold')
            independent = await adapter.start_execution(second, 'hold')
            with pytest.raises(RuntimeAdapterError, match='active'):
                await adapter.start_execution(first, 'would accidentally steer')
            await adapter.send_input(independent, 'peer finishes')
            await adapter.interrupt(target)
            assert (await adapter.wait(target, timeout=2))['outcome'] == 'interrupted'
            assert (await adapter.wait(independent, timeout=2))['last_agent_message'] == 'peer finishes'
            with pytest.raises(RuntimeAdapterError, match='active'):
                await adapter.send_input(target, 'stale input')
            continued = await adapter.start_execution(first, 'after interrupt')
            assert (await adapter.wait(continued, timeout=2))['outcome'] == 'completed'

    asyncio.run(exercise())


def test_budget_stop_queues_one_explicit_retro_without_waiting_for_active_main(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    peer: Path,
) -> None:
    """A sampled stop reaches Main's native queue while its turn stays active."""

    from graphtraj.execution import execution_budget
    from graphtraj.execution.execution_budget import (
        budget_notice_output,
        execution_budget_monitor,
    )

    ticket = tmp_path / "ticket"
    ticket.mkdir()
    (ticket / "ticket.yml").write_text(
        "current_definition: ticket.md\n", encoding="utf-8"
    )
    (ticket / "ticket.md").write_text(
        "---\n"
        "difficulty: high\n"
        "difficulty_reason: controlled host recovery\n"
        "execution_budget:\n"
        "  engineer_tier: senior\n"
        "  tier_reason: controlled host recovery\n"
        "  estimated_minutes: {implementation: 0.01, validation: 0.01, review: 0.01, total: 0.01}\n"
        "  planned_sessions: {team_leader: 1, engineer: 1, standards_reviewer: 1, spec_reviewer: 1, delivery_state: 1}\n"
        "  correction_rounds: 1\n"
        "  estimation_note: controlled host recovery\n"
        "  on_exceed: stop\n"
        "---\n",
        encoding="utf-8",
    )
    now = [1000.0]
    monkeypatch.setattr(execution_budget.time, "time", lambda: now[0])
    monkeypatch.setattr(execution_budget.random, "uniform", lambda lower, upper: lower)
    monkeypatch.setattr(execution_budget.random, "random", lambda: 0.99)
    monitor = execution_budget_monitor(ticket, "116", "session-budget-control")
    assert monitor is not None

    async def exercise() -> None:
        protocol = tmp_path / "protocol.jsonl"
        skill = tmp_path / "harness/.agents/skills/retro/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("name: retro\n", encoding="utf-8")
        duplicate = {
            "type": "execution-budget-exceeded",
            "ticket": {"ticket_id": "116", "ticket_name": "session-budget-control"},
            "threshold": {"kind": "stochastic_stop", "limit": 2},
            "actual": {"elapsed_minutes": 2.011},
            "stage": "implementation",
            "responsible_role": "engineer",
        }

        def queued_messages() -> list[dict]:
            if not protocol.exists():
                return []
            return [
                json.loads(line)
                for line in protocol.read_text(encoding="utf-8").splitlines()
            ]

        async with CodexAppServer(command=[str(peer)], cwd=tmp_path) as adapter:
            session = await adapter.create_session(context(tmp_path / "worktree", peer))
            active = await adapter.start_execution(session, "hold")
            with CodexMainRecovery(
                session.thread_id,
                skill,
                cwd=tmp_path,
                command=[str(peer)],
                environment={"PEER_PROTOCOL_LOG": str(protocol)},
            ) as recovery:
                with budget_notice_output(recovery.notice_fd):
                    assert monitor.check("engineer", "implementation") is False
                    now[0] += 0.7
                    assert monitor.check("engineer", "implementation") is False
                    now[0] += 120
                    assert monitor.check("engineer", "implementation") is True
                    os.write(recovery.notice_fd, (json.dumps(duplicate) + "\n").encode())

                with pytest.raises(RuntimeAdapterError, match="active"):
                    await adapter.start_execution(session, "must still reject")

            queued = queued_messages()
            initialized = next(item for item in queued if item.get("method") == "initialize")
            assert initialized["params"]["capabilities"] == {"experimentalApi": True}
            queue = [item for item in queued if item.get("method") == "thread/queue/add"]
            assert len(queue) == 1
            assert not any(item.get("method") == "turn/start" for item in queued)
            assert queue[0]["params"] == {
                "threadId": session.thread_id,
                "clientUserMessageId": "fd403ef4-1047-54e3-9eb3-ec71c26912eb",
                "input": [
                    {
                        "type": "text",
                        "text": (
                            "$retro Analyze the enforced stochastic stop for Ticket 116 "
                            "using the supplied wrap-up and retained evidence. Identify "
                            "scheduling corrections before deciding continuation. Reuse "
                            "existing findings; do not restart work."
                        ),
                    },
                    {"type": "skill", "name": "retro", "path": str(skill.resolve())},
                ],
            }
            assert recovery.queue_submissions == ("queued-1",)
            await adapter.interrupt(active)
            assert (await adapter.wait(active, timeout=2))["outcome"] == "interrupted"

    asyncio.run(exercise())


def test_main_recovery_surfaces_caller_notice_errors(
    tmp_path: Path,
    peer: Path,
) -> None:
    """Malformed caller-channel input remains visible to the owning host."""
    skill = tmp_path / "harness/.agents/skills/retro/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("name: retro\n", encoding="utf-8")
    recovery = CodexMainRecovery("thread-main", skill, cwd=tmp_path, command=[str(peer)])

    with pytest.raises(RuntimeAdapterError) as caught:
        with recovery:
            os.write(recovery.notice_fd, b"not-json\n")
    assert caught.value.code == "RUNTIME_REQUEST_INVALID"
    with pytest.raises(RuntimeAdapterError) as repeated:
        recovery.close()
    assert repeated.value.code == "RUNTIME_REQUEST_INVALID"


def test_main_recovery_keeps_queue_error_visible_when_runner_fails(
    tmp_path: Path,
    peer: Path,
) -> None:
    """A queue rejection remains observable beside the Runner failure."""
    from graphtraj.execution.execution_budget import budget_notice_output

    skill = tmp_path / "harness/.agents/skills/retro/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("name: retro\n", encoding="utf-8")
    stop = {
        "type": "execution-budget-exceeded",
        "ticket": {"ticket_id": "116", "ticket_name": "session-budget-control"},
        "threshold": {"kind": "stochastic_stop", "limit": 2},
    }

    with pytest.raises(RuntimeAdapterError) as caught:
        with CodexMainRecovery(
            "thread-main",
            skill,
            cwd=tmp_path,
            command=[str(peer)],
            environment={"PEER_REJECT_QUEUE": "1"},
        ) as recovery:
            with budget_notice_output(recovery.notice_fd):
                os.write(recovery.notice_fd, (json.dumps(stop) + "\n").encode())
            raise RuntimeError("Runner operation failed")
    assert caught.value.code == "RUNTIME_RPC_ERROR"
    assert isinstance(caught.value.__context__, RuntimeError)


def test_main_recovery_close_keeps_cleanup_owned_after_waiter_cancellation(
    tmp_path: Path,
    peer: Path,
) -> None:
    """A cancelled close waiter cannot abandon the queue reader or its descriptor."""

    from graphtraj.execution.execution_budget import budget_notice_output, caller_notice_fd

    async def exercise() -> None:
        skill = tmp_path / "harness/.agents/skills/retro/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("name: retro\n", encoding="utf-8")
        recovery = CodexMainRecovery(
            "thread-main",
            skill,
            cwd=tmp_path,
            command=[str(peer)],
            environment={"PEER_PAUSE_QUEUE": "1"},
        )
        duplicate = None
        recovery.__enter__()
        try:
            with budget_notice_output(recovery.notice_fd):
                duplicate, owned = caller_notice_fd()
                assert owned
                os.write(recovery.notice_fd, (
                    json.dumps({
                        "type": "execution-budget-exceeded",
                        "ticket": {"ticket_id": "116", "ticket_name": "session-budget-control"},
                        "threshold": {"kind": "stochastic_stop", "limit": 2},
                    }) + "\n"
                ).encode())
            closing = asyncio.create_task(asyncio.to_thread(recovery.close))
            await asyncio.sleep(0.05)
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await closing
            await asyncio.to_thread(recovery.close)
            assert recovery.queue_submissions == ("queued-1",)
            with pytest.raises(RuntimeAdapterError):
                _ = recovery.notice_fd
        finally:
            if duplicate is not None:
                os.close(duplicate)
            await asyncio.to_thread(recovery.close)

    asyncio.run(exercise())


def test_agent_runner_uses_native_queue_for_a_codex_main_caller(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    peer: Path,
) -> None:
    """The ordinary Runner caller channel queues a stop without host plumbing."""

    from graphtraj.execution.execution_budget import caller_notice_fd
    from graphtraj.interfaces.cli.agent_runner import _budget_notices

    skill = tmp_path / ".agents/skills/retro/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("name: retro\n", encoding="utf-8")
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    (bin_directory / "codex").symlink_to(peer)
    protocol = tmp_path / "protocol.jsonl"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-main")
    monkeypatch.setenv("PATH", str(bin_directory))
    monkeypatch.setenv("PEER_PROTOCOL_LOG", str(protocol))
    monkeypatch.delenv("GRAPHTRAJ_BUDGET_NOTICE_FD", raising=False)
    monkeypatch.delenv("GRAPHTRAJ_ROLE", raising=False)

    stop = {
        "type": "execution-budget-exceeded",
        "ticket": {"ticket_id": "116", "ticket_name": "session-budget-control"},
        "threshold": {"kind": "stochastic_stop", "limit": 2},
    }
    with _budget_notices():
        descriptor, owned = caller_notice_fd()
        assert descriptor is not None and owned
        try:
            os.write(descriptor, (json.dumps(stop) + "\n").encode())
        finally:
            os.close(descriptor)

    requests = [
        json.loads(line)
        for line in protocol.read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("method") == "thread/queue/add"
    ]
    assert len(requests) == 1
    assert requests[0]["params"]["threadId"] == "thread-main"


def test_server_request_keeps_native_id_and_does_not_block_other_sessions(
    tmp_path: Path, peer: Path,
) -> None:
    """Awaiting a caller's approval does not stop response and notification reading."""

    async def exercise() -> None:
        requested = asyncio.Event()
        release = asyncio.Event()
        requests = []

        async def handle(request: CodexServerRequest) -> dict | None:
            requests.append(request)
            requested.set()
            await release.wait()
            return {'decision': 'accept'}

        async with CodexAppServer(command=[str(peer)], cwd=tmp_path, on_request=handle) as adapter:
            first = await adapter.create_session(context(tmp_path / 'first', peer))
            second = await adapter.create_session(context(tmp_path / 'second', peer))
            target = await adapter.start_execution(first, 'request:item/commandExecution/requestApproval')
            await asyncio.wait_for(requested.wait(), 2)
            independent = await adapter.start_execution(second, 'independent output')
            assert (await adapter.wait(independent, timeout=2))['last_agent_message'] == 'independent output'
            request = requests[0]
            assert request.method == 'item/commandExecution/requestApproval'
            assert request.params['threadId'] == target.thread_id
            assert request.params['turnId'] == target.turn_id
            assert isinstance(request.request_id, int)
            release.set()
            result = await adapter.wait(target, timeout=2)
            assert result['last_agent_message'] == 'request accepted'

    asyncio.run(exercise())


@pytest.mark.parametrize('failure, code', [
    ('rpc-error', 'RUNTIME_RPC_ERROR'),
    ('bad-json', 'RUNTIME_PROTOCOL_ERROR'),
    ('bad-shape', 'RUNTIME_PROTOCOL_ERROR'),
    ('closed', 'RUNTIME_CONNECTION_CLOSED'),
])
def test_transport_failures_are_controlled_and_never_leave_requests_hanging(
    tmp_path: Path, peer: Path, failure: str, code: str,
) -> None:
    """Native RPC errors and unreadable/closed streams reach the Runtime boundary."""

    async def exercise() -> None:
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path, request_timeout=1) as adapter:
            session = await adapter.create_session(context(tmp_path / 'worktree', peer))
            with pytest.raises(RuntimeAdapterError) as caught:
                await adapter.start_execution(session, failure)
            assert caught.value.code == code
            if failure == 'rpc-error':
                assert caught.value.method == 'turn/start'
                assert caught.value.request_id == 3
                assert caught.value.native_error == {
                    'code': -32001, 'message': 'native rejection', 'data': {'retry': False},
                }
                execution = await adapter.start_execution(session, 'recovered')
                assert (await adapter.wait(execution, timeout=2))['outcome'] == 'completed'

    asyncio.run(exercise())


@pytest.mark.parametrize('handling, code', [
    ('absent', 'RUNTIME_REQUEST_UNHANDLED'),
    ('unsupported', 'RUNTIME_REQUEST_UNHANDLED'),
    ('raised', 'RUNTIME_REQUEST_FAILED'),
    ('cancelled', 'RUNTIME_REQUEST_FAILED'),
    ('timeout', 'RUNTIME_REQUEST_FAILED'),
])
def test_unhandled_server_requests_fail_visibly_without_blocking_peers(
    tmp_path: Path, peer: Path, handling: str, code: str,
) -> None:
    """The native caller receives an error reply and the execution owner sees why."""

    async def handle(request: CodexServerRequest) -> dict | None:
        if handling == 'raised':
            raise ValueError('approval UI failed')
        if handling == 'cancelled':
            raise asyncio.CancelledError('approval UI was cancelled')
        if handling == 'timeout':
            await asyncio.Event().wait()
        return None

    async def exercise() -> None:
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path,
                                  on_request=None if handling == 'absent' else handle,
                                  request_timeout=0.5) as adapter:
            session = await adapter.create_session(context(tmp_path / 'first', peer))
            target = await adapter.start_execution(session, 'request:unsupported/method')
            with pytest.raises(RuntimeAdapterError) as caught:
                await adapter.wait(target, timeout=2)
            assert caught.value.code == code
            assert 'unsupported/method' in str(caught.value)
            peer_session = await adapter.create_session(context(tmp_path / 'second', peer))
            peer_execution = await adapter.start_execution(peer_session, 'peer still works')
            assert (await adapter.wait(peer_execution, timeout=2))['last_agent_message'] == 'peer still works'

    asyncio.run(exercise())


def test_each_session_projects_resolved_role_skills_and_task_access(
    tmp_path: Path, peer: Path,
) -> None:
    """Distinct roles and exact write grants are delivered per native thread."""

    async def exercise() -> None:
        contexts = []
        for name, role_name, model, effort in [
            ('first', 'engineer', 'first-model', 'low'),
            ('second', 'standards-reviewer', 'second-model', 'high'),
        ]:
            root = tmp_path / name
            for skill_name in ['selected', 'disabled']:
                skill = root / '.agents/skills' / skill_name / 'SKILL.md'
                skill.parent.mkdir(parents=True)
                skill.write_text(f'---\nname: {skill_name}\ndescription: temporary check\n---\n')
            role = ResolvedChildRole(role_name, f'Role {name}.', (),
                                     RolePreset('codex', model, None, None, reasoning_effort=effort))
            contexts.append(context(root, peer, role, ('selected',),
                                    (Path('.state/teams/1/rounds/1/report.md'),)))
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path) as adapter:
            sessions = await asyncio.gather(*(adapter.create_session(value) for value in contexts))
            for index, session in enumerate(sessions):
                turn = await adapter.start_execution(session, 'configuration')
                observed = json.loads((await adapter.wait(turn, timeout=2))['last_agent_message'])
                name = ['first', 'second'][index]
                root = tmp_path / name
                assert observed['model'] == ['first-model', 'second-model'][index]
                assert observed['cwd'] == str(root)
                assert observed['developerInstructions'] == f'Role {name}.'
                config = observed['config']
                assert config['model_reasoning_effort'] == ['low', 'high'][index]
                assert config['agents'] == {'enabled': False}
                assert config['skills']['config'] == [
                    {'path': str(root / '.agents/skills/disabled/SKILL.md'), 'enabled': False},
                    {'path': str(root / '.agents/skills/selected/SKILL.md'), 'enabled': True},
                ]
                filesystem = config['permissions'][config['default_permissions']]['filesystem']
                assert filesystem[':workspace_roots']['.'] == ['write', 'read'][index]
                assert filesystem[':workspace_roots']['CONTEXT.md'] == 'read'
                assert filesystem[':workspace_roots']['docs'] == 'read'
                assert filesystem[str(root / 'evidence/teams/1/rounds/1/report.md')] == 'write'
                assert filesystem[str(root / '.agents/skills/selected')] == 'read'
                assert (str(root / 'git-common') in filesystem) == (index == 0)
                assert not any(str(tmp_path / ['second', 'first'][index]) in key for key in filesystem)
            different_connection = context(tmp_path / 'third', peer, replace(
                role, settings=replace(role.settings, base_url='https://different.invalid/v1')))
            with pytest.raises(RuntimeAdapterError) as caught:
                await adapter.create_session(different_connection)
            assert caught.value.code == 'RUNTIME_CONNECTION_MISMATCH'

    asyncio.run(exercise())


def test_observation_and_wait_cancellation_do_not_cancel_the_execution(
    tmp_path: Path, peer: Path,
) -> None:
    """Callers can observe raw native notifications and retry waiting safely."""

    async def exercise() -> None:
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path) as adapter:
            session = await adapter.create_session(context(tmp_path / 'worktree', peer))
            notice = await adapter.next_notification(timeout=2)
            assert notice['method'] == 'thread/started'
            assert notice['params']['thread']['id'] == session.thread_id
            target = await adapter.start_execution(session, 'hold')
            with pytest.raises(RuntimeAdapterError) as caught:
                await adapter.wait(target, timeout=0.01)
            assert caught.value.code == 'RUNTIME_TIMEOUT'
            waiter = asyncio.create_task(adapter.wait(target))
            await asyncio.sleep(0)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            await adapter.interrupt(target)
            assert (await adapter.wait(target, timeout=2))['outcome'] == 'interrupted'
            await adapter.close()
            # A known terminal result remains retrievable after closing transport.
            assert (await adapter.wait(target))['outcome'] == 'interrupted'

    asyncio.run(exercise())


def test_failed_handshake_retains_service_diagnostics_and_closes_cleanly(
    tmp_path: Path, peer: Path,
) -> None:
    """An early native configuration error is available through the public Adapter."""

    async def exercise() -> None:
        adapter = CodexAppServer(command=[str(peer)], cwd=tmp_path,
                                 environment={'PEER_INITIALIZE_FAIL': '1'})
        with pytest.raises(RuntimeAdapterError):
            async with adapter:
                pytest.fail('An invalid native configuration must not initialize')
        assert 'invalid native configuration' in adapter.stderr_tail
        await adapter.close()

    asyncio.run(exercise())


def test_default_and_resumed_sessions_leave_policy_to_the_runtime(
    tmp_path: Path, peer: Path,
) -> None:
    """Start and resume preserve role permissions without imposing trust or approvals."""

    async def check(adapter: CodexAppServer, session: CodexSession) -> None:
        """Inspect effective invocation settings through the external Runtime peer."""
        execution = await adapter.start_execution(session, 'configuration')
        result = json.loads((await adapter.wait(execution, timeout=2))['last_agent_message'])
        assert result.get('approvalPolicy') is None
        assert result.get('approvalsReviewer') is None
        assert result['config'].get('projects') is None
        permissions = result['config']['permissions'][result['config']['default_permissions']]
        assert permissions['filesystem'][':workspace_roots']['docs'] == 'read'

    async def exercise() -> None:
        resolved = context(tmp_path / 'worktree', peer)
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path) as adapter:
            session = await adapter.create_session(resolved)
            await check(adapter, session)
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path) as adapter:
            resumed = await adapter.resume_session(resolved, session.thread_id)
            await check(adapter, resumed)

    asyncio.run(exercise())


def test_approval_policy_is_a_native_per_session_override(
    tmp_path: Path, peer: Path,
) -> None:
    """Interactive policy uses thread parameters, with responses routed to the caller."""

    async def exercise() -> None:
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path) as adapter:
            first = await adapter.create_session(
                context(tmp_path / 'first', peer), approval_policy='untrusted',
            )
            second = await adapter.create_session(context(tmp_path / 'second', peer), approval_policy='never')
            for session, policy in [(first, 'untrusted'), (second, 'never')]:
                execution = await adapter.start_execution(session, 'configuration')
                result = json.loads((await adapter.wait(execution, timeout=2))['last_agent_message'])
                assert result['approvalPolicy'] == policy
                assert result.get('approvalsReviewer') is None

    asyncio.run(exercise())


def test_foreign_handles_and_duplicate_resume_are_rejected_locally(
    tmp_path: Path, peer: Path,
) -> None:
    """Coincident native IDs from different services must never select another turn."""

    async def exercise() -> None:
        resolved = context(tmp_path / 'worktree', peer)
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path) as first:
            async with CodexAppServer(command=[str(peer)], cwd=tmp_path) as second:
                local = await first.create_session(resolved)
                foreign = await second.create_session(resolved)
                target = await first.start_execution(local, 'hold')
                other = await second.start_execution(foreign, 'hold')
                assert (target.thread_id, target.turn_id) == (other.thread_id, other.turn_id)
                for action in [
                    lambda: first.interrupt(other),
                    lambda: first.send_input(other, 'wrong target'),
                    lambda: first.wait(other, timeout=0.01),
                    lambda: first.resume_session(resolved, local.thread_id),
                    lambda: first.start_execution(foreign, 'wrong Session'),
                ]:
                    with pytest.raises(RuntimeAdapterError) as caught:
                        await action()
                    assert caught.value.code == 'RUNTIME_LIFECYCLE_INVALID'
                await first.interrupt(target)
                await second.send_input(other, 'unaffected')
                assert (await second.wait(other, timeout=2))['last_agent_message'] == 'unaffected'

    asyncio.run(exercise())


@pytest.mark.parametrize('prompt, code', [
    ('bad-turn', 'RUNTIME_PROTOCOL_ERROR'),
    ('bad-completion', 'RUNTIME_PROTOCOL_ERROR'),
    ('bad-final-text', 'RUNTIME_PROTOCOL_ERROR'),
    ('failed-turn', 'RUNTIME_EXECUTION_FAILED'),
])
def test_invalid_native_lifecycle_messages_and_failed_turns_are_controlled(
    tmp_path: Path, peer: Path, prompt: str, code: str,
) -> None:
    """Nested protocol corruption and native execution failure cannot look completed."""

    async def exercise() -> None:
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path) as adapter:
            session = await adapter.create_session(context(tmp_path / 'worktree', peer))
            with pytest.raises(RuntimeAdapterError) as caught:
                target = await adapter.start_execution(session, prompt)
                await adapter.wait(target, timeout=2)
            assert caught.value.code == code
            if prompt == 'failed-turn':
                assert 'native execution failed' in str(caught.value)
                assert caught.value.terminal_confirmed
                continued = await adapter.start_execution(session, 'after failure')
                assert (await adapter.wait(continued, timeout=2))['outcome'] == 'completed'

    asyncio.run(exercise())


def test_explicit_close_wakes_pending_owners_and_bounds_a_stalled_service(
    tmp_path: Path, peer: Path,
) -> None:
    """Connection shutdown is bounded even when the external service ignores EOF."""

    async def exercise() -> None:
        adapter = CodexAppServer(command=[str(peer)], cwd=tmp_path, request_timeout=1,
                                 environment={'PEER_STALL_CLOSE': '1'})
        async with adapter:
            session = await adapter.create_session(context(tmp_path / 'worktree', peer))
            target = await adapter.start_execution(session, 'hold')
            waiter = asyncio.create_task(adapter.wait(target))
            close = asyncio.create_task(adapter.close())
            await asyncio.sleep(0)
            close.cancel()
            with pytest.raises(asyncio.CancelledError):
                await close
            await asyncio.wait_for(adapter.close(), timeout=3)
            assert 'close acknowledged' in adapter.stderr_tail
            with pytest.raises(RuntimeAdapterError) as caught:
                await waiter
            assert caught.value.code == 'RUNTIME_CONNECTION_CLOSED'
            with pytest.raises(RuntimeAdapterError):
                await adapter.start_execution(session, 'after close')

    asyncio.run(exercise())


def test_rpc_timeout_includes_backpressure_and_allows_explicit_close(
    tmp_path: Path, peer: Path,
) -> None:
    """A peer that stops reading cannot leave a valid large request pending."""

    async def exercise() -> None:
        resolved = context(tmp_path / 'worktree', peer)
        async with CodexAppServer(
            command=[str(peer)], cwd=tmp_path, request_timeout=1,
            environment={'PEER_PAUSE_INPUT': '1', 'PEER_STALL_CLOSE': '1'},
        ) as adapter:
            session = await adapter.create_session(resolved)
            start = asyncio.create_task(adapter.start_execution(session, 'x' * 1_000_000))
            try:
                done, _ = await asyncio.wait([start], timeout=2)
                assert start in done, 'Backpressure exceeded the RPC timeout'
                with pytest.raises(RuntimeAdapterError) as caught:
                    await start
                assert caught.value.code == 'RUNTIME_TIMEOUT'
                assert not caught.value.terminal_confirmed
                with pytest.raises(RuntimeAdapterError) as invalidated:
                    await adapter.start_execution(session, 'after timeout')
                assert invalidated.value.code == 'RUNTIME_TIMEOUT'
            finally:
                start.cancel()
                await asyncio.gather(start, return_exceptions=True)
                await asyncio.wait_for(adapter.close(), timeout=3)
            assert 'close acknowledged' in adapter.stderr_tail

    asyncio.run(exercise())


def test_native_request_resolution_cancels_the_pending_caller_handler(
    tmp_path: Path, peer: Path,
) -> None:
    """A targeted interrupt withdraws its pending approval without killing the service."""

    async def exercise() -> None:
        entered = asyncio.Event()
        cancelled = asyncio.Event()

        async def handle(request: CodexServerRequest) -> dict | None:
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        async with CodexAppServer(command=[str(peer)], cwd=tmp_path, on_request=handle) as adapter:
            session = await adapter.create_session(context(tmp_path / 'worktree', peer))
            target = await adapter.start_execution(session, 'request:item/commandExecution/requestApproval')
            await asyncio.wait_for(entered.wait(), 2)
            await adapter.interrupt(target)
            await asyncio.wait_for(cancelled.wait(), 1)
            assert (await adapter.wait(target, timeout=2))['outcome'] == 'interrupted'
            continued = await adapter.start_execution(session, 'after withdrawn request')
            assert (await adapter.wait(continued, timeout=2))['outcome'] == 'completed'

    asyncio.run(exercise())


def test_reply_followed_by_transport_failure_does_not_orphan_the_execution(
    tmp_path: Path, peer: Path,
) -> None:
    """Failure interleaved immediately after turn/start wakes the result owner too."""

    async def exercise() -> None:
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path) as adapter:
            session = await adapter.create_session(context(tmp_path / 'worktree', peer))
            with pytest.raises(RuntimeAdapterError) as caught:
                target = await adapter.start_execution(session, 'reply-then-malformed')
                await adapter.wait(target, timeout=0.05)
            assert caught.value.code == 'RUNTIME_PROTOCOL_ERROR'

    asyncio.run(exercise())


def test_large_native_output_is_returned_without_truncation(
    tmp_path: Path, peer: Path,
) -> None:
    """Native JSON lines can exceed asyncio's small default line limit."""

    async def exercise() -> None:
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path) as adapter:
            session = await adapter.create_session(context(tmp_path / 'worktree', peer))
            target = await adapter.start_execution(session, 'large-output')
            assert (await adapter.wait(target, timeout=2))['last_agent_message'] == 'x' * 100_000

    asyncio.run(exercise())


def test_connection_overrides_cannot_leak_into_a_session_using_defaults(
    tmp_path: Path, peer: Path,
) -> None:
    """A default Context cannot silently inherit another role's endpoint."""

    async def exercise() -> None:
        role = ResolvedChildRole('temporary-role', 'Bounded task.', (),
                                 RolePreset('codex', 'model', 'https://role.invalid/v1', None))
        selected = context(tmp_path / 'selected', peer, role)
        ordinary = context(tmp_path / 'ordinary', peer)
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path,
                                  environment=selected.runtime_environment()) as adapter:
            session = await adapter.create_session(selected)
            with pytest.raises(RuntimeAdapterError) as caught:
                await adapter.create_session(ordinary)
            assert caught.value.code == 'RUNTIME_CONNECTION_MISMATCH'
            target = await adapter.start_execution(session, 'still uses selected role')
            assert (await adapter.wait(target, timeout=2))['outcome'] == 'completed'

    asyncio.run(exercise())


def test_service_configuration_cannot_override_resolved_native_permissions(
    tmp_path: Path, peer: Path,
) -> None:
    """The actual service's Codex home receives the existing legacy-config check."""

    async def exercise() -> None:
        configured = tmp_path / 'service-home'
        configured.mkdir()
        (configured / 'config.toml').write_text('sandbox_mode = "danger-full-access"\n')
        adapter = CodexAppServer(command=[str(peer)], cwd=tmp_path,
                                 environment={'CODEX_HOME': str(configured)})
        with pytest.raises(RuntimeAdapterError) as caught:
            async with adapter:
                pass
        assert caught.value.code == 'LEGACY_SANDBOX_CONFIG_CONFLICT'

    asyncio.run(exercise())


@pytest.mark.parametrize('method, params, response', [
    ('item/fileChange/requestApproval', {'itemId': 'patch', 'startedAtMs': 1000}, {'decision': 'decline'}),
    ('item/permissions/requestApproval',
     {'itemId': 'permissions', 'startedAtMs': 1000, 'cwd': '/project', 'permissions': {}},
     {'permissions': {}, 'scope': 'turn'}),
    ('item/tool/requestUserInput',
     {'itemId': 'question', 'isBlocking': True, 'questions': []}, {'answers': {}}),
    ('item/tool/call',
     {'callId': 'call', 'tool': 'example', 'arguments': {'x': 1}}, {'contentItems': [], 'success': True}),
    ('mcpServer/elicitation/request',
     {'serverName': 'example', 'turnId': None, 'mode': 'form', 'message': 'Input',
      'requestedSchema': {'type': 'object', 'properties': {}}}, {'action': 'decline'}),
    ('account/chatgptAuthTokens/refresh', {'reason': 'unauthorized'},
     {'accessToken': 'test-token', 'chatgptAccountId': 'test-account'}),
    ('attestation/generate', {}, {'token': 'test-attestation'}),
    ('applyPatchApproval',
     {'conversationId': 'thread-1', 'callId': 'patch', 'fileChanges': {}},
     {'decision': {'denied': {'rejection': 'bounded test'}}}),
    ('execCommandApproval',
     {'conversationId': 'thread-1', 'callId': 'command', 'command': ['true'],
      'cwd': '/project', 'parsedCmd': []}, {'decision': {'denied': {'rejection': 'bounded test'}}}),
])
def test_native_request_types_round_trip_without_becoming_agent_output(
    tmp_path: Path,
    peer: Path,
    method: str,
    params: dict,
    response: dict,
) -> None:
    """Request envelopes stay native; only command approval has historical live evidence."""

    async def exercise() -> None:
        native_params = dict(params)
        if method.startswith('item/'):
            native_params = {'threadId': 'thread-1', 'turnId': 'turn-1', **native_params}
        elif method == 'mcpServer/elicitation/request':
            native_params = {'threadId': 'thread-1', **native_params}
        exchange = {'method': method, 'params': native_params, 'response': response}
        received = []

        async def handle(request: CodexServerRequest) -> dict:
            received.append(request)
            assert request.request_id == 'native-request-1'
            assert request.method == method
            assert request.params == native_params
            return response

        async with CodexAppServer(command=[str(peer)], cwd=tmp_path, on_request=handle,
                                  environment={'PEER_REQUEST_EXCHANGE': json.dumps(exchange)}) as adapter:
            session = await adapter.create_session(context(tmp_path / 'worktree', peer))
            target = await adapter.start_execution(session, 'configured-request')
            assert (await adapter.wait(target, timeout=2))['last_agent_message'] == 'request accepted'
            assert len(received) == 1

    asyncio.run(exercise())


def test_concurrent_client_replies_can_arrive_in_reverse_order(
    tmp_path: Path, peer: Path,
) -> None:
    """Client request IDs correlate concurrent operations independently of arrival order."""

    async def exercise() -> None:
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path) as adapter:
            first = await adapter.create_session(context(tmp_path / 'first', peer))
            second = await adapter.create_session(context(tmp_path / 'second', peer))
            a, b = await asyncio.gather(adapter.start_execution(first, 'reverse-first'),
                                        adapter.start_execution(second, 'reverse-second'))
            assert a.turn_id == 'turn-1' and b.turn_id == 'turn-2'
            assert (await adapter.wait(a, timeout=2))['last_agent_message'] == 'reverse-first'
            assert (await adapter.wait(b, timeout=2))['last_agent_message'] == 'reverse-second'

    asyncio.run(exercise())


@pytest.mark.parametrize('options', [
    {'request_timeout': 0}, {'request_timeout': float('inf')}, {'command': []},
])
def test_invalid_connection_options_use_the_runtime_error_boundary(
    tmp_path: Path, options: dict,
) -> None:
    """Invalid caller configuration fails before acquiring a service."""

    with pytest.raises(RuntimeAdapterError) as caught:
        CodexAppServer(cwd=tmp_path, **options)
    assert caught.value.code == 'RUNTIME_REQUEST_INVALID'


def test_invalid_input_does_not_reserve_or_steer_a_session(
    tmp_path: Path, peer: Path,
) -> None:
    """An empty instruction is a controlled input error and leaves ownership intact."""

    async def exercise() -> None:
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path) as adapter:
            session = await adapter.create_session(context(tmp_path / 'worktree', peer))
            with pytest.raises(RuntimeAdapterError) as caught:
                await adapter.start_execution(session, '')
            assert caught.value.code == 'RUNTIME_REQUEST_INVALID'
            target = await adapter.start_execution(session, 'hold')
            with pytest.raises(RuntimeAdapterError) as caught:
                await adapter.send_input(target, '')
            assert caught.value.code == 'RUNTIME_REQUEST_INVALID'
            await adapter.interrupt(target)
            assert (await adapter.wait(target, timeout=2))['outcome'] == 'interrupted'

    asyncio.run(exercise())


def test_connection_opening_is_owned_once_and_unopened_observation_is_invalid(
    tmp_path: Path, peer: Path,
) -> None:
    """Concurrent entry cannot create two services behind a single Adapter."""
    async def exercise() -> None:
        adapter = CodexAppServer(command=[str(peer)], cwd=tmp_path, request_timeout=1)
        with pytest.raises(RuntimeAdapterError) as caught:
            await adapter.next_notification(timeout=0.01)
        assert caught.value.code == 'RUNTIME_LIFECYCLE_INVALID'
        try:
            opened = await asyncio.gather(adapter.__aenter__(), adapter.__aenter__(), return_exceptions=True)
            assert sum(item is adapter for item in opened) == 1
            failures = [item for item in opened if isinstance(item, RuntimeAdapterError)]
            assert len(failures) == 1 and failures[0].code == 'RUNTIME_LIFECYCLE_INVALID'
        finally:
            await adapter.close()

    asyncio.run(exercise())


def test_request_failure_leaves_target_interruptible_and_reports_terminal_confirmation(
    tmp_path: Path, peer: Path,
) -> None:
    """An unhandled request is visible before native completion and remains actionable."""
    async def exercise() -> None:
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path,
                                  environment={'PEER_CONTINUE_AFTER_REJECTION': '1'}) as adapter:
            session = await adapter.create_session(context(tmp_path / 'worktree', peer))
            target = await adapter.start_execution(session, 'request:unsupported/method')
            with pytest.raises(RuntimeAdapterError) as pending:
                await adapter.wait(target, timeout=2)
            assert not pending.value.terminal_confirmed
            await adapter.interrupt(target)
            # Completion may precede the interrupt reply, as in the real wire.
            with pytest.raises(RuntimeAdapterError) as terminal:
                await adapter.wait(target, timeout=2)
            assert terminal.value.code == 'RUNTIME_REQUEST_UNHANDLED'
            assert terminal.value.terminal_confirmed

    asyncio.run(exercise())
