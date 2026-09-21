"""Behavior at the production Session Adapter's public stdio seam."""

from __future__ import annotations

import asyncio
import errno
import json
import os
import re
import tomllib
from dataclasses import replace
from datetime import datetime
import sys
from pathlib import Path

import pytest
import yaml

from graphtraj.configuration.project_roles import RolePreset
from graphtraj.configuration.role_definitions import ResolvedChildRole
from graphtraj.runtimes.codex.codex_adapter import (
    preflight_runtime_context,
    read_codex_last_agent_message,
    refresh_codex_report_paths,
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
    leader_control_write_paths: tuple[Path, ...] = (),
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
        leader_control_write_paths=leader_control_write_paths,
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


def test_native_trace_reads_the_native_session_through_a_link(
    tmp_path: Path, peer: Path,
) -> None:
    """The retained Trace reads the Runtime-owned record live and after resume."""

    async def exercise() -> None:
        trace_directory = tmp_path / 'trace'
        trace_file = trace_directory / 'events.jsonl'
        trace_directory.mkdir()
        trace_file.touch()
        rollout_root = tmp_path / 'native-rollouts'
        environment = {'PEER_NATIVE_ROLLOUT': str(rollout_root)}
        resolved = context(tmp_path / 'worktree', peer)

        async with CodexAppServer(command=[str(peer)], cwd=tmp_path, environment=environment) as adapter:
            session = await adapter.create_session(resolved)
            adapter.retain_native_trace(session, trace_file)
            starting = asyncio.create_task(adapter.start_execution(session, 'first native result'))
            while (
                not trace_file.is_symlink()
                or b'"encrypted_content":"opaque"' not in trace_file.read_bytes()
            ):
                await asyncio.sleep(0.01)
            assert not starting.done()
            assert os.readlink(trace_file) == str(session.rollout_path)
            # The Trace reads the Runtime-owned file itself, including records
            # the Runtime appends while this execution continues.
            live = trace_file.read_bytes()
            assert live == session.rollout_path.read_bytes()
            assert b'"timestamp":"native-1"' in live
            assert b'"timestamp":"native-2"' in live

            execution = await starting
            result = await adapter.wait(execution, timeout=2)
            assert result['last_agent_message'] == 'first native result'
            assert trace_file.read_bytes() == session.rollout_path.read_bytes()
            # The Runtime owns the linked file and receives no Harness record.
            assert b'"type":"runtime"' not in session.rollout_path.read_bytes()

        async with CodexAppServer(command=[str(peer)], cwd=tmp_path, environment=environment) as adapter:
            resumed = await adapter.resume_session(resolved, session.thread_id)
            adapter.retain_native_trace(resumed, trace_file)
            execution = await adapter.start_execution(resumed, 'resumed native result')
            result = await adapter.wait(execution, timeout=2)
            assert result['last_agent_message'] == 'resumed native result'

        assert trace_file.read_bytes() == session.rollout_path.read_bytes()
        assert trace_file.read_bytes().count(b'"timestamp":"native-1"') == 1
        assert trace_file.read_bytes().count(b'"timestamp":"native-5"') == 1
        assert read_codex_last_agent_message(trace_file) == 'resumed native result'

    asyncio.run(exercise())


def test_terminal_trace_link_failure_keeps_confirmed_execution_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    peer: Path,
) -> None:
    """A post-terminal Trace failure keeps the native execution confirmation."""

    from graphtraj.runtimes.codex import codex_adapter

    original_link = codex_adapter._link_native_trace
    failing = False

    def link_or_fail(trace_file: Path, rollout: Path) -> None:
        if failing:
            raise OSError(errno.ENOSPC, 'No space left on device')
        original_link(trace_file, rollout)

    monkeypatch.setattr(codex_adapter, '_link_native_trace', link_or_fail)

    async def exercise() -> None:
        nonlocal failing

        environment = {'PEER_NATIVE_ROLLOUT': str(tmp_path / 'native-rollouts')}
        trace_directory = tmp_path / 'trace'
        trace_file = trace_directory / 'events.jsonl'
        trace_directory.mkdir()
        trace_file.touch()
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path, environment=environment) as adapter:
            session = await adapter.create_session(context(tmp_path / 'worktree', peer))
            adapter.retain_native_trace(session, trace_file)
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


def _controlled_stop_ticket(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Return a Ticket monitor whose next stopping check samples a real stop."""
    from graphtraj.execution import execution_budget
    from graphtraj.execution.execution_budget import execution_budget_monitor

    ticket = tmp_path / "ticket"
    ticket.mkdir()
    (ticket / "ticket.yml").write_text(
        "current_definition: ticket.md\n", encoding="utf-8"
    )
    (ticket / "ticket.md").write_text(
        "---\n"
        "difficulty: high\n"
        "difficulty_reason: controlled caller delivery\n"
        "execution_budget:\n"
        "  estimated_minutes: {implementation: 0.01, validation: 0.01, review: 0.01, total: 0.01}\n"
        "  planned_sessions: {team_leader: 1, engineer: 1, standards_reviewer: 1, spec_reviewer: 1, delivery_state: 1}\n"
        "  correction_rounds: 1\n"
        "  estimation_note: controlled caller delivery\n"
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
    return monitor, now


def _retro_skill(tmp_path: Path) -> Path:
    skill = tmp_path / "harness/.agents/skills/retro/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("name: retro\n", encoding="utf-8")
    return skill


def test_budget_stop_returns_one_in_band_delivery_to_the_awaiting_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A sampled stop reaches Main with the result of the call it is awaiting."""

    from graphtraj.execution.execution_budget import budget_notice_output

    monitor, now = _controlled_stop_ticket(monkeypatch, tmp_path)
    skill = _retro_skill(tmp_path)
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    native_client_log = tmp_path / "native-client.log"
    native_client = bin_directory / "codex"
    native_client.write_text(
        "#!" + sys.executable + "\n"
        "import pathlib\n"
        "pathlib.Path(" + repr(str(native_client_log)) + ").write_text('started')\n",
        encoding="utf-8",
    )
    native_client.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_directory))

    reminder = {
        "type": "execution-budget-exceeded",
        "occurred_at": datetime.fromtimestamp(1000.0).astimezone().isoformat(timespec="seconds"),
        "ticket": {"ticket_id": "116", "ticket_name": "session-budget-control"},
        "threshold": {"kind": "estimated_minutes", "limit": "total"},
        "actual": {"elapsed_minutes": 0.5},
        "message": "System reminder: Elapsed time: 00:00:30.",
    }

    with CodexMainRecovery(skill) as recovery:
        with budget_notice_output(recovery.notice_fd):
            # The monitor's own checks raise the ordinary reminder and then the
            # enforced stop, exactly as a live Runner operation would.
            assert monitor.check("engineer", "implementation") is False
            now[0] += 0.7
            assert monitor.check("engineer", "implementation") is False
            now[0] += 120
            assert monitor.check("engineer", "implementation") is True
            os.write(recovery.notice_fd, (json.dumps(reminder) + "\n").encode())
            # A repeated delivery of the same stop stays deduplicated.
            os.write(recovery.notice_fd, (
                json.dumps({
                    "type": "execution-budget-exceeded",
                    "occurred_at": datetime.fromtimestamp(1120.7).astimezone().isoformat(timespec="seconds"),
                    "ticket": {"ticket_id": "116", "ticket_name": "session-budget-control"},
                    "threshold": {"kind": "stochastic_stop", "limit": 2},
                    "actual": {"elapsed_minutes": 2.011},
                }) + "\n"
            ).encode())
        document = recovery.attach_stop_deliveries({"tasks": []})

    deliveries = document["stop_deliveries"]
    assert len(deliveries) == 1
    delivery = deliveries[0]
    assert delivery["stop_id"] == "fd403ef4-1047-54e3-9eb3-ec71c26912eb"
    assert delivery["stop"] == "stochastic_stop:2"
    assert delivery["ticket"] == {
        "ticket_id": "116", "ticket_name": "session-budget-control",
    }
    assert delivery["elapsed"] == "00:02:00"
    assert delivery["instruction"].startswith("$retro ")
    assert delivery["skill"] == {"name": "retro", "path": str(skill.resolve())}
    triggered_at = datetime.fromisoformat(delivery["triggered_at"])
    delivered_at = datetime.fromisoformat(delivery["delivered_at"])
    assert delivery["triggered_at"] == (
        datetime.fromtimestamp(1120.7).astimezone().isoformat(timespec="seconds")
    )
    assert triggered_at.utcoffset() is not None
    assert delivered_at.utcoffset() is not None
    # The delivery is late by construction, so it must not read as just-happened.
    assert abs((datetime.now().astimezone() - triggered_at).total_seconds()) > 60
    assert delivered_at > triggered_at
    # The delivered stop is the result of the awaiting call: no native input
    # request, no second Main and no other client process is started for it.
    assert not native_client_log.exists()
    with pytest.raises(RuntimeAdapterError):
        _ = recovery.notice_fd


def test_main_recovery_surfaces_caller_notice_errors(
    tmp_path: Path,
) -> None:
    """Malformed caller-channel input remains visible to the owning host."""
    recovery = CodexMainRecovery(_retro_skill(tmp_path))

    with pytest.raises(RuntimeAdapterError) as caught:
        with recovery:
            os.write(recovery.notice_fd, b"not-json\n")
    assert caught.value.code == "RUNTIME_REQUEST_INVALID"
    with pytest.raises(RuntimeAdapterError) as repeated:
        recovery.close()
    assert repeated.value.code == "RUNTIME_REQUEST_INVALID"


def test_main_recovery_keeps_delivery_error_visible_when_runner_fails(
    tmp_path: Path,
) -> None:
    """A rejected stop delivery remains observable beside the Runner failure."""
    stop = {
        "type": "execution-budget-exceeded",
        "occurred_at": "2026-09-17T02:20:24",
        "ticket": {"ticket_id": "116", "ticket_name": "session-budget-control"},
        "threshold": {"kind": "stochastic_stop", "limit": 2},
        "actual": {"elapsed_minutes": 2.011},
    }

    with pytest.raises(RuntimeAdapterError) as caught:
        with CodexMainRecovery(_retro_skill(tmp_path)) as recovery:
            os.write(recovery.notice_fd, (json.dumps(stop) + "\n").encode())
            raise RuntimeError("Runner operation failed")
    assert caught.value.code == "RUNTIME_REQUEST_INVALID"
    assert isinstance(caught.value.__context__, RuntimeError)


def test_main_recovery_close_releases_the_caller_channel_once(tmp_path: Path) -> None:
    """Repeated closes stay safe and keep the delivered stop identity."""
    recovery = CodexMainRecovery(_retro_skill(tmp_path))
    stop = {
        "type": "execution-budget-exceeded",
        "occurred_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "ticket": {"ticket_id": "116", "ticket_name": "session-budget-control"},
        "threshold": {"kind": "stochastic_stop", "limit": 2},
        "actual": {"elapsed_minutes": 2.011},
    }
    with recovery:
        os.write(recovery.notice_fd, (json.dumps(stop) + "\n").encode())
        deliveries = recovery.take_stop_deliveries()
        assert len(deliveries) == 1
        assert recovery.take_stop_deliveries() == ()
    recovery.close()
    with pytest.raises(RuntimeAdapterError):
        _ = recovery.notice_fd


def test_agent_runner_returns_the_delivered_stop_with_its_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The awaited Runner call returns the stop instead of queueing it."""

    from click.testing import CliRunner

    from graphtraj.execution.execution_budget import caller_notice_fd
    from graphtraj.interfaces.cli import agent_runner

    skill = tmp_path / ".agents/skills/retro/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("name: retro\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-main")
    monkeypatch.delenv("GRAPHTRAJ_BUDGET_NOTICE_FD", raising=False)
    monkeypatch.delenv("GRAPHTRAJ_ROLE", raising=False)
    stop = {
        "type": "execution-budget-exceeded",
        "occurred_at": datetime.fromtimestamp(1000.0).astimezone().isoformat(timespec="seconds"),
        "ticket": {"ticket_id": "116", "ticket_name": "session-budget-control"},
        "threshold": {"kind": "stochastic_stop", "limit": 2},
        "actual": {"elapsed_minutes": 2.011},
    }

    def interrupt_after_a_sampled_stop(alias: str, cwd: Path) -> dict:
        """Return one operation result after a stop reached the caller channel."""
        descriptor, owned = caller_notice_fd()
        assert descriptor is not None
        try:
            os.write(descriptor, (json.dumps(stop) + "\n").encode())
        finally:
            if owned:
                os.close(descriptor)
        return {"alias": alias, "interrupt_status": "interrupted"}

    monkeypatch.setattr(
        agent_runner, "interrupt_session", interrupt_after_a_sampled_stop,
    )
    result = CliRunner().invoke(agent_runner.main, ["interrupt", "engineer@e1"])

    assert result.exit_code == 0, result.output
    document = yaml.safe_load(result.output)
    assert document["alias"] == "engineer@e1"
    delivery = document["stop_deliveries"][0]
    assert delivery["stop_id"] == "fd403ef4-1047-54e3-9eb3-ec71c26912eb"
    assert delivery["stop"] == "stochastic_stop:2"
    assert delivery["instruction"].startswith("$retro ")
    assert delivery["skill"]["path"] == str(skill.resolve())
    assert delivery["elapsed"] == "00:02:00"


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
                role, settings=replace(role.settings, base_url='https://different.invalid/v1',
                    codex={'approval': {'model': 'review', 'base_url': 'https://review.invalid',
                                         'api_key_env': 'REVIEW_KEY'}})))
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
                                 RolePreset('codex', 'model', 'https://role.invalid/v1', None,
                                 codex={'approval': {'model': 'review', 'base_url': 'https://review.invalid',
                                                      'api_key_env': 'REVIEW_KEY'}}))
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


def _native_settings_of_arguments(arguments: list[str]) -> dict:
    """Read the exact native settings one Adapter request renders as -c overrides."""
    settings: dict = {}
    for index, argument in enumerate(arguments[:-1]):
        if argument == '-c':
            settings.update(tomllib.loads(arguments[index + 1]))
    return settings


def _native_settings(resolved: RuntimeContext) -> dict:
    """Read the exact native settings one resolved Context sends to a Session."""
    return _native_settings_of_arguments(
        resolved.launch_document()['adapter_request']['arguments']
    )


def _native_filesystem(request: dict) -> dict:
    """Read the filesystem map one durable Adapter request projects."""
    settings = _native_settings_of_arguments(request['arguments'])
    profile = settings['default_permissions']
    return settings['permissions'][profile]['filesystem']


@pytest.mark.parametrize(
    'selected, expected',
    [('auto_review', 'auto_review'), (None, None), ('user', 'user')],
)
def test_harness_approvals_reviewer_reaches_create_and_resume(
    tmp_path: Path, peer: Path, selected: str | None, expected: str | None,
) -> None:
    """The selected Reviewer travels verbatim; an absent one keeps the native default."""
    root = tmp_path / 'worktree'
    runtime_store = root / '.codex'
    runtime_store.mkdir(parents=True)
    runtime_store.joinpath('config.toml').write_text(
        'approval_policy = "on-request"\n'
        + ('' if selected is None else 'approvals_reviewer = ' + json.dumps(selected) + '\n')
    )
    report_files = (Path('.state/teams/1/rounds/1/engineer.md'),)
    resolved = context(
        root, peer,
        ResolvedChildRole('engineer', 'Implement the Ticket.', (),
                          RolePreset('codex', 'chosen-model', None, None, reasoning_effort='low')),
        report_files=report_files,
    )

    parameters = resolved.session_document()['adapter_request']
    assert parameters['config'].get('approvals_reviewer') == expected
    assert _native_settings(resolved).get('approvals_reviewer') == expected
    # Only the Reviewer travels; the existing per-call approval policy keeps its meaning.
    assert 'approval_policy' not in parameters['config']
    assert 'approval_policy' not in _native_settings(resolved)

    resumed = refresh_codex_report_paths(
        resolved.launch_document()['adapter_request'],
        worktree=root, evidence=root / 'evidence', report_files=report_files,
        role='engineer',
    )
    assert resumed['session_parameters']['config'].get('approvals_reviewer') == expected


def test_team_leader_projection_shares_only_its_direct_control_paths(
    tmp_path: Path, peer: Path,
) -> None:
    """Direct control gains the Runner paths it writes, and nothing wider."""
    root = tmp_path / 'worktree'
    root.mkdir()
    (root / '.codex').mkdir()
    leader_alias = '144-native-dispatch-permissions@l1'
    child_alias = '144-native-dispatch-permissions@e1'
    sessions = root / 'runner' / 'sessions'
    for alias, parent in [
        (leader_alias, None), (child_alias, leader_alias), ('other-ticket@e1', 'other-ticket@l1'),
    ]:
        directory = sessions / alias
        directory.mkdir(parents=True)
        (directory / 'mapping.yml').write_text(
            yaml.safe_dump({'alias': alias, 'parent': parent})
        )
    worldline_lock = root / 'state' / 'worldline' / '.lock'
    capacity = root / 'runner' / 'capacity'
    resolved = context(
        root, peer,
        ResolvedChildRole('team-leader', 'Lead the Team.', (),
                          RolePreset('codex', 'chosen-model', None, None, reasoning_effort='max')),
        leader_control_write_paths=(worldline_lock, capacity),
    )
    launch = _native_filesystem(resolved.launch_document()['adapter_request'])
    assert launch[str(worldline_lock)] == 'write'
    assert launch[str(capacity)] == 'write'
    # Direct child Sessions do not exist yet when this Session is created.
    assert launch.get(str(sessions / child_alias)) != 'write'
    assert launch.get(str(sessions)) != 'write'
    assert launch.get(str(worldline_lock.parent)) != 'write'

    resumed = refresh_codex_report_paths(
        resolved.launch_document()['adapter_request'],
        worktree=root, evidence=root / 'evidence',
        report_files=(Path('.state/teams/1/rounds/1/leader.md'),),
        role='team-leader', session_directory=sessions / leader_alias,
    )
    filesystem = _native_filesystem(resumed)
    assert filesystem[str(sessions / child_alias)] == 'write'
    # The durable launch request keeps its grants across this resume.
    assert filesystem[str(worldline_lock)] == 'write'
    assert filesystem[str(capacity)] == 'write'
    # No wildcard, no shared Runner directory and no other Ticket's Session.
    assert filesystem.get(str(sessions)) != 'write'
    assert filesystem.get(str(sessions / 'other-ticket@e1')) != 'write'
    assert filesystem[':workspace_roots']['.'] == 'write'
