"""Claude's public Runtime contract with controlled native process evidence."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import threading
import time

import pytest
import yaml

from graphtraj.configuration.project_roles import parse_inline_role
from graphtraj.configuration.role_definitions import resolve_child_role
from graphtraj.execution.runner_heartbeat import hold_ownership
from graphtraj.runtimes.claude.adapter import ClaudeContext
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError, select_runtime_adapter
from test_result_submission import result_project


@pytest.fixture
def claude_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide an explicit controlled native peer without altering real login."""
    binary = tmp_path / 'bin/claude'
    binary.parent.mkdir()
    binary.write_text(f'#!{sys.executable}\n' + Path(__file__).with_name('claude_cli_fixture.py').read_text())
    binary.chmod(0o755)
    monkeypatch.setenv('PATH', str(binary.parent) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('CLAUDE_FIXTURE_HOME', str(tmp_path))
    monkeypatch.setenv('PYTHONPATH', str(Path(__file__).resolve().parents[1] / 'src'))


def context(root: Path, **fields: object):
    """Resolve a role through the public Runtime preparation interface."""
    _, settings = parse_inline_role({'author': {
        'runtime': 'claude', 'model': 'claude-opus-5-5', 'reasoning_effort': 'high', **fields,
    }})
    role = resolve_child_role('author', settings, root)
    adapter = select_runtime_adapter('claude')
    prepared = adapter.preflight_runtime_context(
        harness_root=root, git_common_directory=root / 'worktrees/research/.git', role=role,
        worktree=root / 'worktrees/research', evidence=root / 'state', requested_skills=(),
        report_files=(Path('.state/teams/1/rounds/1/researcher-x1.md'),),
    ).finalize()
    return adapter, prepared


def execution(
    root: Path,
    stack: ExitStack,
    prompt: str,
    expected: str | None = None,
    prepared_context: ClaudeContext | None = None,
    **fields: object,
):
    """Bind real native process identity before releasing its startup hook."""
    if prepared_context is None:
        adapter, prepared = context(root, **fields)
    else:
        adapter = select_runtime_adapter('claude')
        prepared = prepared_context
    directory = root / '.graphtraj/runner/sessions/research@x1'
    trace = root / 'state/claude.jsonl'
    ready = threading.Event()

    def created(session: str, pid: int) -> None:
        """Assert no model work ran before binding; register the exact native PID."""
        if expected is None:
            assert not (root / (session + '.json')).exists()
        mapping = yaml.safe_load((directory / 'mapping.yml').read_text())
        mapping.update(runtime='claude', session=session, execution_id=turn.execution_id,
                       worker_pid=os.getpid(), runtime_pid=pid,
                       trace_file=str(trace))
        (directory / 'mapping.yml').write_text(yaml.safe_dump(mapping))

    def started(session: str, pid: int) -> None:
        """Signal completion of the binding sequence."""
        ready.set()

    stack.enter_context(hold_ownership(directory, os.getpid()))
    turn = adapter.managed_execution(prepared.launch_document()['adapter_request'], prompt, directory,
                                    started, prepared.evidence_document(), trace_file=trace,
                                    expected_session=expected, session_created=created)
    return turn, ready, adapter


@pytest.mark.parametrize('configured,inherited,source', [
    ('https://configured.example', 'https://environment.example', 'configuration'),
    (None, 'https://environment.example', 'native'),
    (None, 'https://secret@example.com', 'native'),
    (None, None, 'native'),
])
def test_claude_retains_endpoint_on_resume(
    tmp_path: Path,
    claude_environment: None,
    monkeypatch: pytest.MonkeyPatch,
    configured: str | None,
    inherited: str | None,
    source: str,
) -> None:
    """Retained Runtime context fixes both endpoint value and absence across resume."""
    result_project(tmp_path)
    monkeypatch.delenv('ANTHROPIC_BASE_URL', raising=False)
    if inherited:
        monkeypatch.setenv('ANTHROPIC_BASE_URL', inherited)
    _, prepared = context(tmp_path, **({'base_url': configured} if configured else {}))
    evidence = prepared.evidence_document()
    assert evidence['base_url'] == configured
    assert evidence['base_url_source'] == source
    with ExitStack() as stack:
        turn, _, _ = execution(tmp_path, stack, 'first', prepared_context=prepared)
        first = turn.run()
    assert json.loads((tmp_path / 'native-endpoint.json').read_text()) == configured
    monkeypatch.setenv('ANTHROPIC_BASE_URL', 'https://later.example')
    with ExitStack() as stack:
        turn, _, _ = execution(tmp_path, stack, 'resume', first['session_id'], prepared_context=prepared)
        assert turn.run()['outcome'] == 'completed'
    assert json.loads((tmp_path / 'native-endpoint.json').read_text()) == configured


@pytest.mark.parametrize('endpoint', [
    'https://secret@example.com', 'https://example.com?token=secret',
])
def test_claude_rejects_secret_configured_endpoint(
    tmp_path: Path, claude_environment: None, monkeypatch: pytest.MonkeyPatch, endpoint: str,
) -> None:
    """Reject credential-bearing selected URLs without reproducing secrets in diagnostics."""
    with pytest.raises(RuntimeAdapterError) as caught:
        context(tmp_path, base_url=endpoint)
    assert 'secret' not in str(caught.value)


@pytest.mark.parametrize('mode', [None, 'default', 'auto'])
def test_claude_permission_mode_configuration_and_resume(
    tmp_path: Path, claude_environment: None, mode: str | None,
) -> None:
    """Pin explicit choices but leave restricted native defaults unmodified."""
    result_project(tmp_path)
    config = {'permission_mode': mode} if mode is not None else {}
    _, prepared = context(tmp_path, claude=config)
    assert prepared.evidence_document()['permission_mode'] == mode
    session = None
    for prompt in ('first', 'resume'):
        with ExitStack() as stack:
            turn, _, _ = execution(tmp_path, stack, prompt, session, prepared_context=prepared)
            result = turn.run()
            session = result['session_id']
        launch = json.loads((tmp_path / 'native-permissions.json').read_text())
        assert launch['mode'] == mode
        permissions = launch['settings']['permissions']
        if mode is None:
            assert 'defaultMode' not in permissions
        else:
            assert permissions['defaultMode'] == mode
        assert launch['restricted'] and launch['permission_handler'] == 'stdio'
        assert permissions['blockReadsOutsideWorkingDirectories'] is True
        assert permissions['deny']
        sandbox = launch['settings']['sandbox']
        assert sandbox['enabled'] and sandbox['failIfUnavailable']
        assert sandbox['allowUnsandboxedCommands'] is False
        assert sandbox['autoAllowBashIfSandboxed'] is False
        assert sandbox['filesystem']['denyRead'] and sandbox['filesystem']['denyWrite']
        assert result['permissions']['requested'] == mode
        assert result['permissions']['observed'] == (mode or 'unknown')


@pytest.mark.parametrize('observed', ['default', 'unknown'])
def test_claude_reports_mode_fallback_or_unknown(
    tmp_path: Path, claude_environment: None, monkeypatch: pytest.MonkeyPatch, observed: str,
) -> None:
    """Do not label a native fallback or unavailable observation as active auto."""
    result_project(tmp_path)
    monkeypatch.setenv('CLAUDE_FIXTURE_PERMISSION_MODE', observed)
    with ExitStack() as stack:
        turn, _, _ = execution(tmp_path, stack, 'mode', claude={'permission_mode': 'auto'})
        with pytest.raises(RuntimeAdapterError, match='requested permission mode') as failed:
            turn.run()
    assert failed.value.terminal_confirmed
    assert turn.done.is_set() and turn.proc.poll() is not None
    assert turn.permission_evidence()['observed'] == observed
    assert turn.permission_evidence()['matches_request'] == (False if observed == 'default' else None)


@pytest.mark.parametrize('mode', ['bypassPermissions', 'acceptEdits', None])
def test_claude_rejects_unsupported_explicit_mode(
    tmp_path: Path, claude_environment: None, mode: str | None,
) -> None:
    """Only the two supported explicit modes enter the Runtime configuration."""
    with pytest.raises(RuntimeAdapterError, match='permission_mode'):
        context(tmp_path, claude={'permission_mode': mode})


def test_claude_native_resume_and_activity(tmp_path: Path, claude_environment: None) -> None:
    """Keep native history and new execution IDs, with usage counted at result only."""
    from graphtraj.runtimes.activity import TraceReader

    result_project(tmp_path)
    with ExitStack() as stack:
        first, ready, _ = execution(tmp_path, stack, 'remember-320')
        result = first.run()
        assert ready.is_set() and result['outcome'] == 'completed'
        assert first.terminal_confirmed
        assert result['terminal_confirmed'] is True
        assert json.loads((tmp_path / 'native-selection.json').read_text()) == {
            'model': 'claude-opus-5-5', 'effort': 'high', 'environment_effort': 'high',
        }
    with ExitStack() as stack:
        resumed, _, _ = execution(tmp_path, stack, 'continue', result['session_id'])
        second = resumed.run()
        assert second['session_id'] == result['session_id']
        assert second['execution_id'] != result['execution_id']
        assert 'remember-320|continue' == second['last_agent_message']
    events = TraceReader(first.trace, 'claude', result['session_id']).page()['events']
    usages = [event['usage']['tokens'] for event in events if event['kind'] == 'usage']
    assert usages == [dict(input_uncached=11, cache_read=7, cache_write=2, output=5, input=20)] * 2


def test_claude_public_launch_diagnostics_are_bounded_and_correlated(
    tmp_path: Path, claude_environment: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compare public diagnostic fields with actual Popen inputs, excluding private data."""
    import subprocess
    from graphtraj.execution.runner_status import runtime_caller
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.interfaces import tools

    runner, _, _ = result_project(tmp_path)
    monkeypatch.setenv('CLAUDE_FIXTURE_DIAGNOSTICS', '1')
    monkeypatch.setenv('CLAUDE_FIXTURE_PERMISSION_MODE', 'default')
    captured = []
    popen = subprocess.Popen

    def observe(argv: list[str], **kwargs: object):
        """Record the real subprocess boundary while executing the controlled native peer."""
        if '--input-format' in argv:
            captured.append(list(argv))
        return popen(argv, **kwargs)

    monkeypatch.setattr(subprocess, 'Popen', observe)
    with ExitStack() as stack:
        turn, _, _ = execution(tmp_path, stack, 'private-prompt-marker', claude={'permission_mode': 'auto'})
        with pytest.raises(RuntimeAdapterError, match='requested permission mode') as failed:
            turn.run()
        assert failed.value.terminal_confirmed
    with runtime_caller(runner, None):
        document = tools.read_reports({'alias': 'research@x1'}, cwd=tmp_path).document
    diagnostics = document['runtime_diagnostics']
    assert diagnostics['execution_id'] == turn.execution_id
    assert diagnostics['session_id'] == turn.session
    assert diagnostics['popen_returned'] is True
    argv = captured[0]
    launch = diagnostics['launch']
    assert launch['permission_mode'] == argv[argv.index('--permission-mode') + 1] == 'auto'
    settings = json.loads(argv[argv.index('--settings') + 1])
    assert launch['inline_default_mode'] == settings['permissions']['defaultMode'] == 'auto'
    assert launch['model'] == argv[argv.index('--model') + 1] == 'claude-opus-5-5'
    assert launch['effort'] == argv[argv.index('--effort') + 1] == 'high'
    assert launch['restricted'] and launch['strict_mcp'] and launch['stdio_permission_handler']
    assert launch['sandbox']['enabled'] is True
    assert launch['sandbox']['allowUnsandboxedCommands'] is False
    assert diagnostics['initialize']['autoModeAvailable'] is False
    assert diagnostics['initialize']['control_status'] == 'success'
    assert diagnostics['system_init']['permissionMode'] == 'default'
    assert diagnostics['initialize']['reason'] == diagnostics['system_init']['reason'] == 'unknown'
    assert {'source': 'stderr', 'category': 'native_auto_unavailable'} in diagnostics['warnings']
    assert {'source': 'stderr', 'category': 'native_permission_forced_default_by_environment_scrub'} in diagnostics['warnings']
    serialized = json.dumps(diagnostics)
    for private in ('sk-diagnosticsecret', 'private@example.invalid', 'private-unknown-reason',
                    'private-prompt-marker', str(tmp_path), 'mcpServers'):
        assert private not in serialized
    assert len(serialized) < 4096
    with runtime_caller(runner, 'research@x2'), pytest.raises(RunnerError):
        tools.read_reports({'alias': 'research@x1'}, cwd=tmp_path)


def test_claude_permission_reply_and_error(tmp_path: Path, claude_environment: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only explicit parent approval releases a native tool request."""
    result_project(tmp_path)
    notified = threading.Event()
    monkeypatch.setattr('graphtraj.execution.runner_control.notify_direct_parent', lambda *args: notified.set())
    with ExitStack() as stack, ThreadPoolExecutor(max_workers=1) as pool:
        turn, ready, _ = execution(tmp_path, stack, 'permission')
        future = pool.submit(turn.run)
        assert ready.wait(5) and notified.wait(5)
        control = {'session': turn.session, 'execution_id': turn.execution_id}
        pending = turn.operate({**control, 'operation': 'requests'})['requests'][0]
        assert not future.done()
        with pytest.raises(RuntimeAdapterError):
            turn.operate({**control, 'operation': 'reply', 'request_token': 'foreign', 'response': {'behavior': 'allow'}})
        turn.operate({**control, 'operation': 'reply', 'request_token': pending['request_token'],
                      'response': {'behavior': 'deny', 'message': 'Denied by parent'}})
        assert json.loads(future.result(timeout=10)['last_agent_message'])['behavior'] == 'deny'
    with ExitStack() as stack:
        turn, _, _ = execution(tmp_path, stack, 'provider-error')
        with pytest.raises(RuntimeAdapterError, match='provider-error') as caught:
            turn.run()
        assert caught.value.terminal_confirmed


def test_claude_send_and_confirmed_stop(tmp_path: Path, claude_environment: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """A control ACK does not mark completion while the actual process still runs."""
    result_project(tmp_path)
    monkeypatch.setenv('CLAUDE_FIXTURE_STOP_DELAY', '0.3')
    with ExitStack() as stack, ThreadPoolExecutor(max_workers=1) as pool:
        turn, ready, _ = execution(tmp_path, stack, 'wait')
        future = pool.submit(turn.run)
        assert ready.wait(5)
        assert turn.terminate()
        assert not turn.done.is_set() and turn.proc.poll() is None
        stopped = future.result(timeout=10)
        assert stopped['outcome'] == 'interrupted'
        assert stopped['terminal_confirmed'] is True
        assert turn.terminal_confirmed and turn.proc.poll() is not None
    with ExitStack() as stack, ThreadPoolExecutor(max_workers=1) as pool:
        turn, ready, _ = execution(tmp_path, stack, 'wait-again')
        future = pool.submit(turn.run)
        assert ready.wait(5)
        turn.operate({'operation': 'send', 'session': turn.session, 'execution_id': turn.execution_id, 'instruction': 'finish'})
        assert 'finish' in future.result(timeout=10)['last_agent_message']


def test_claude_later_prompt_hook_is_answered_behind_a_collection_backlog(
        tmp_path: Path, claude_environment: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """A prompt sent into a live execution is released before its native hook times out."""
    from agent_swarm.sessions.claude import ClaudeJsonlCollector

    result_project(tmp_path)
    hooks = tmp_path / 'hooks.log'
    monkeypatch.setenv('CLAUDE_FIXTURE_HOOK_LOG', str(hooks))
    monkeypatch.setenv('CLAUDE_FIXTURE_LATER_HOOK_TIMEOUT', '2')
    monkeypatch.setenv('CLAUDE_FIXTURE_STREAM_FRAGMENTS', '150')
    accept = ClaudeJsonlCollector.accept

    def durable(self, record: dict, position: int, *rest: object, **options: object) -> None:
        """Stand in for the durable archive rewrite each streamed fragment costs."""
        if record.get('type') == 'stream_event':
            time.sleep(0.03)
        return accept(self, record, position, *rest, **options)

    monkeypatch.setattr(ClaudeJsonlCollector, 'accept', durable)
    with ExitStack() as stack, ThreadPoolExecutor(max_workers=1) as pool:
        turn, ready, _ = execution(tmp_path, stack, 'wait-stream')
        future = pool.submit(turn.run)
        try:
            assert ready.wait(5)
            history = tmp_path / (turn.session + '.json')
            deadline = time.monotonic() + 5
            while not (history.exists() and 'wait-stream' in history.read_text()) and time.monotonic() < deadline:
                time.sleep(0.01)
            # About 4.5 s of fragments are still being collected.
            turn.operate({'operation': 'send', 'session': turn.session, 'execution_id': turn.execution_id,
                          'instruction': 'finish'})
            outcome = future.result(timeout=20)
        finally:
            if not turn.done.is_set():
                turn.terminate()
    assert 'timed out' not in hooks.read_text()
    assert outcome['outcome'] == 'completed' and 'finish' in outcome['last_agent_message']


def test_claude_interrupt_confirms_within_its_window_behind_a_collection_backlog(
        tmp_path: Path, claude_environment: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Queued fragments share archive rewrites, so a stop is confirmed inside the operation window."""
    from agent_swarm.sessions.archive import JsonlSessionStore

    result_project(tmp_path)
    monkeypatch.setenv('CLAUDE_FIXTURE_STREAM_FRAGMENTS', '1500')
    checkpoint = JsonlSessionStore.checkpoint
    rewrites = []

    def durable(self, *args: object, **options: object) -> bool:
        """Stand in for one whole-archive durable rewrite of a long Session."""
        rewrites.append(1)
        time.sleep(0.03)
        return checkpoint(self, *args, **options)

    monkeypatch.setattr(JsonlSessionStore, 'checkpoint', durable)
    with ExitStack() as stack, ThreadPoolExecutor(max_workers=1) as pool:
        turn, ready, _ = execution(tmp_path, stack, 'wait-stream')
        future = pool.submit(turn.run)
        assert ready.wait(5)
        history = tmp_path / (turn.session + '.json')
        deadline = time.monotonic() + 5
        while not (history.exists() and 'wait-stream' in history.read_text()) and time.monotonic() < deadline:
            time.sleep(0.01)
        started = time.monotonic()
        # One rewrite per fragment would hold the confirmation for 45 s.
        assert turn.operate({'operation': 'interrupt', 'session': turn.session,
                             'execution_id': turn.execution_id}) == {}
        assert time.monotonic() - started < 20
        stopped = future.result(timeout=10)
    assert stopped['outcome'] == 'interrupted' and stopped['terminal_confirmed'] is True
    assert len(rewrites) < 200


def test_claude_mid_turn_input_shares_its_turn_result(tmp_path: Path, claude_environment: None) -> None:
    """Echoed input joined to a running turn completes with that turn's one result."""
    result_project(tmp_path)
    with ExitStack() as stack, ThreadPoolExecutor(max_workers=1) as pool:
        turn, ready, _ = execution(tmp_path, stack, 'merge')
        future = pool.submit(turn.run)
        assert ready.wait(5)
        turn.operate({'operation': 'send', 'session': turn.session, 'execution_id': turn.execution_id,
                      'instruction': 'finish'})
        completed = future.result(timeout=10)
        assert completed['outcome'] == 'completed'
        assert completed['last_agent_message'] == 'merge|finish'


def test_claude_input_echoed_after_a_result_waits_for_the_next(
    tmp_path: Path, claude_environment: None,
) -> None:
    """Input echoed after a turn's result is not covered by it, even when idle follows."""
    result_project(tmp_path)
    trace = tmp_path / 'state/claude.jsonl'
    with ExitStack() as stack, ThreadPoolExecutor(max_workers=1) as pool:
        turn, ready, _ = execution(tmp_path, stack, 'merge-late')
        future = pool.submit(turn.run)
        assert ready.wait(5)
        control = {'operation': 'send', 'session': turn.session, 'execution_id': turn.execution_id}
        turn.operate({**control, 'instruction': 'joined'})
        deadline = time.monotonic() + 5
        while not any(json.loads(line).get('type') == 'result' for line in trace.read_text().splitlines()):
            assert time.monotonic() < deadline, 'the joined turn produced no result'
            time.sleep(0.02)
        assert not future.done()
        # Its echo follows that result; the earlier turn's idle then arrives.
        turn.operate({**control, 'instruction': 'late'})
        completed = future.result(timeout=10)
        assert completed['outcome'] == 'completed'
        assert completed['last_agent_message'] == 'merge-late|joined|late'


def test_claude_startup_failure_and_registration_refusal(tmp_path: Path, claude_environment: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reap failed pre-registration processes without creating a false Session."""
    result_project(tmp_path)
    monkeypatch.setenv('CLAUDE_FIXTURE_FAIL', '1')
    with ExitStack() as stack:
        turn, ready, _ = execution(tmp_path, stack, 'unused')
        with pytest.raises(RuntimeAdapterError) as caught:
            turn.run()
        assert caught.value.terminal_confirmed and not ready.is_set()
        assert turn.session is None and turn.proc.poll() == 17
    monkeypatch.delenv('CLAUDE_FIXTURE_FAIL')
    with ExitStack() as stack:
        turn, ready, _ = execution(tmp_path, stack, 'unused')

        def refuse(session: str, pid: int) -> None:
            """Represent Runner's failed membership registration."""
            raise RuntimeAdapterError('MEMBER_REGISTRATION_FAILED', 'registration refused')

        turn.created = refuse
        with pytest.raises(RuntimeAdapterError, match='registration refused') as caught:
            turn.run()
        assert caught.value.terminal_confirmed and not ready.is_set()
        assert not (tmp_path / (turn.session + '.json')).exists()


def test_claude_mcp_uses_owned_runner_channel(tmp_path: Path, claude_environment: None) -> None:
    """Exercise the actual stdio MCP bridge from a native child process."""
    result_project(tmp_path)
    with ExitStack() as stack:
        turn, _, _ = execution(tmp_path, stack, 'mcp')
        result = turn.run()
    response = json.loads(result['last_agent_message'])['result']
    assert not response['isError'], response
    assert 'research@x1' in json.dumps(response)


def test_claude_configuration_is_exact_and_approval_fails_closed(tmp_path: Path, claude_environment: None) -> None:
    """Keep high effort and the explicit model, refusing unsupported configurations."""
    result_project(tmp_path)
    adapter, prepared = context(tmp_path, developer_prompt='Bound role content')
    request = prepared.launch_document()['adapter_request']
    assert request['model'] == 'claude-opus-5-5' and request['reasoning_effort'] == 'high'
    assert 'Bound role content' in request['instructions']
    with pytest.raises(RuntimeAdapterError, match='approval is unavailable'):
        adapter.native_replacement_approval()
    with pytest.raises(RuntimeAdapterError, match='effort'):
        context(tmp_path, reasoning_effort='ultra')
    with pytest.raises(RuntimeAdapterError, match='exact'):
        context(tmp_path, model='opus')


def test_read_resources_do_not_become_native_working_directories(
    tmp_path: Path, claude_environment: None,
) -> None:
    """Deliver read grants without promoting them to writable native workspaces."""
    result_project(tmp_path)
    resources = [tmp_path / 'authorized/bin', tmp_path / 'authorized/lib']
    for path in resources:
        path.mkdir(parents=True)
    with ExitStack() as stack:
        turn, _, _ = execution(tmp_path, stack, 'Inspect native permission configuration',
                               claude={'read_paths': list(map(str, resources))})
        turn.run()
    launch = json.loads((tmp_path / 'native-permissions.json').read_text())
    settings = launch['settings']
    assert settings['permissions']['additionalDirectories'] == []
    filesystem = settings['sandbox']['filesystem']
    for path in resources:
        assert str(path.resolve()) in filesystem['allowRead']
        assert str(path.resolve()) in filesystem['denyWrite']
        assert str(path.resolve()) not in filesystem['allowWrite']


def test_claude_resource_grants_and_read_only_recovery(tmp_path: Path, claude_environment: None) -> None:
    """Retain external read-only resources and refuse grants to private state."""
    result_project(tmp_path)
    resource = tmp_path / 'external-method'
    resource.mkdir()
    adapter, prepared = context(tmp_path, claude={'read_paths': [str(resource)]})
    request = prepared.launch_document()['adapter_request']
    assert request['resources'] == [str(resource)]
    recovered = adapter.refresh_report_paths(
        request, worktree=tmp_path / 'worktrees/research', evidence=tmp_path / 'state',
        report_files=(Path('.state/teams/1/rounds/1/researcher-x1.md'),), role='author', reports_only=True,
    )
    assert recovered['worktree_access'] == 'read' and request['worktree_access'] == 'write'
    assert recovered['resources'] == request['resources']
    with pytest.raises(RuntimeAdapterError, match='private'):
        context(tmp_path, claude={'read_paths': [str(tmp_path / 'state')]})


def test_claude_stop_without_native_settlement_confirms_only_exit(
    tmp_path: Path, claude_environment: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exited runtime whose group closed is terminated, still interrupted, never idle."""
    result_project(tmp_path)
    monkeypatch.setenv('CLAUDE_FIXTURE_NO_SETTLE', '1')
    with ExitStack() as stack, ThreadPoolExecutor(max_workers=1) as pool:
        turn, ready, _ = execution(tmp_path, stack, 'wait-unconfirmed')
        future = pool.submit(turn.run)
        assert ready.wait(5)
        turn.terminate()
        outcome = future.result(timeout=30)
        assert outcome['outcome'] == 'interrupted' and outcome['terminal_confirmed'] is True
        assert turn.proc.poll() is not None
        evidence = yaml.safe_load(
            (turn.directory / f'claude-termination-{turn.execution_id}.yml').read_text())
        assert evidence['native_idle'] is False and evidence['process_group_closed'] is True


def test_claude_stop_with_a_live_unsettled_runtime_stays_unconfirmed(
    tmp_path: Path, claude_environment: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an observed exit and closed group, missing settlement still blocks confirmation."""
    result_project(tmp_path)
    monkeypatch.setenv('CLAUDE_FIXTURE_NO_SETTLE', '1')
    with ExitStack() as stack, ThreadPoolExecutor(max_workers=1) as pool:
        turn, ready, _ = execution(tmp_path, stack, 'wait-unconfirmed')
        close = turn._close

        def unobserved_close() -> None:
            """Reap the peer but leave its exit unobserved, as if the group remained."""
            close()
            turn.terminal_confirmed = False

        monkeypatch.setattr(turn, '_close', unobserved_close)
        future = pool.submit(turn.run)
        assert ready.wait(5)
        turn.terminate()
        with pytest.raises(RuntimeAdapterError) as caught:
            future.result(timeout=30)
        assert not caught.value.terminal_confirmed and turn.outcome is None


def test_default_home_is_not_injected_into_native_environment(
    tmp_path: Path, claude_environment: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Observe the actual native launch environment without querying credentials."""
    import subprocess

    result_project(tmp_path)
    monkeypatch.delenv('CLAUDE_CONFIG_DIR', raising=False)
    captured = []
    popen = subprocess.Popen

    def observe(argv: list[str], **kwargs: object):
        """Capture only nonsecret home-selection fields on the process boundary."""
        if '--input-format' in argv:
            environment = kwargs['env']
            captured.append({key: environment.get(key) for key in ('HOME', 'CLAUDE_CONFIG_DIR')})
        return popen(argv, **kwargs)

    monkeypatch.setattr(subprocess, 'Popen', observe)
    with ExitStack() as stack:
        turn, _, _ = execution(tmp_path, stack, 'home-environment')
        assert turn.request['explicit_runtime_home'] is False
        assert turn.run()['outcome'] == 'completed'
    assert captured == [{'HOME': os.environ.get('HOME'), 'CLAUDE_CONFIG_DIR': None}]


def test_transport_failure_names_only_its_kind(tmp_path: Path, claude_environment: None) -> None:
    """A non-JSON native line is classified without copying the line."""
    result_project(tmp_path)
    with ExitStack() as stack:
        turn, _, _ = execution(tmp_path, stack, 'garbage')
        with pytest.raises(RuntimeAdapterError) as caught:
            turn.run()
    assert caught.value.code == 'RUNTIME_TRANSPORT_FAILED'
    assert '(transport_error; exception=JSONDecodeError)' in caught.value.message
    assert 'secret-token' not in caught.value.message and 'not json' not in caught.value.message


def test_permission_notice_is_retried_while_the_request_is_pending(
    tmp_path: Path, claude_environment: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A parent still closing its settled turn receives the notice on retry.

    The undelivered attempts neither end the execution nor answer the request;
    only the parent's explicit reply releases it.
    """
    from graphtraj.execution import runner_control

    result_project(tmp_path)
    receipts = iter([{'delivery': 'not-delivered'}, {'delivery': 'not-delivered'}])
    attempts = []
    received = threading.Event()

    def notify(*args: object) -> dict:
        """Refuse twice, as a closing parent execution does, then receive."""
        attempts.append(args)
        receipt = next(receipts, {'delivery': 'received'})
        if receipt['delivery'] == 'received':
            received.set()
        return receipt

    monkeypatch.setattr(runner_control, 'notify_direct_parent', notify)
    with ExitStack() as stack, ThreadPoolExecutor(max_workers=1) as pool:
        turn, ready, _ = execution(tmp_path, stack, 'permission')
        future = pool.submit(turn.run)
        assert ready.wait(5) and received.wait(10)
        assert len(attempts) == 3 and not future.done()
        control = {'session': turn.session, 'execution_id': turn.execution_id}
        pending = turn.operate({**control, 'operation': 'requests'})['requests'][0]
        turn.operate({**control, 'operation': 'reply', 'request_token': pending['request_token'],
                      'response': {'behavior': 'deny', 'message': 'Denied by parent'}})
        assert json.loads(future.result(timeout=10)['last_agent_message'])['behavior'] == 'deny'
    assert len(attempts) == 3


@pytest.mark.parametrize(('mode', 'scrub'), [
    ('auto', None), ('default', None), (None, None),
    ('auto', '1'), ('auto', ' TRUE '), ('auto', 'yes'), ('auto', 'On'),
    ('auto', '0'), ('auto', 'false'), ('auto', 'NO'), ('auto', ' off '),
    ('auto', ''), ('auto', 'unrecognized'), ('default', '0'), ('default', '1'),
])
def test_scrub_choice_reaches_native_launch_without_mutating_host(
    tmp_path: Path,
    claude_environment: None,
    monkeypatch: pytest.MonkeyPatch,
    mode: str | None,
    scrub: str | None,
) -> None:
    """Follow the installed CLI's boolean semantics and reject explicit auto conflicts."""
    key = 'CLAUDE_CODE_SUBPROCESS_ENV_SCRUB'
    if scrub is None:
        monkeypatch.delenv(key, raising=False)
    else:
        monkeypatch.setenv(key, scrub)
    result_project(tmp_path)
    config = {} if mode is None else {'permission_mode': mode}
    conflict = mode == 'auto' and scrub is not None and scrub.strip().lower() in {'1', 'true', 'yes', 'on'}
    with ExitStack() as stack:
        turn, _, _ = execution(tmp_path, stack, 'mode', claude=config)
        if conflict:
            with pytest.raises(RuntimeAdapterError, match='conflicts with explicit') as failed:
                turn.run()
            assert failed.value.terminal_confirmed and turn.done.is_set()
            assert turn.proc is None
        else:
            result = turn.run()
            launch = json.loads((tmp_path / 'native-permissions.json').read_text())
            assert launch['scrub'] == (scrub if scrub is not None else '0' if mode == 'auto' else '1')
            assert result['permissions']['requested'] == mode
            assert launch['settings']['sandbox']['failIfUnavailable']
            assert not launch['settings']['sandbox']['allowUnsandboxedCommands']
    assert os.environ.get(key) == scrub
