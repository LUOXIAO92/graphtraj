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
        mapping.update(runtime='claude', session=session, worker_pid=os.getpid(), runtime_pid=pid,
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
    (None, 'https://environment.example', 'environment'),
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
    assert evidence['base_url'] == (configured or inherited)
    assert evidence['base_url_source'] == source
    with ExitStack() as stack:
        turn, _, _ = execution(tmp_path, stack, 'first', prepared_context=prepared)
        first = turn.run()
    monkeypatch.setenv('ANTHROPIC_BASE_URL', 'https://later.example')
    with ExitStack() as stack:
        turn, _, _ = execution(tmp_path, stack, 'resume', first['session_id'], prepared_context=prepared)
        assert turn.run()['outcome'] == 'completed'
    assert json.loads((tmp_path / 'native-endpoint.json').read_text()) == (configured or inherited)


@pytest.mark.parametrize('endpoint', [
    'https://secret@example.com', 'https://example.com?token=secret',
])
def test_claude_rejects_secret_environment_endpoint(
    tmp_path: Path, claude_environment: None, monkeypatch: pytest.MonkeyPatch, endpoint: str,
) -> None:
    """Reject credential-bearing inherited URLs without reproducing secrets in diagnostics."""
    monkeypatch.setenv('ANTHROPIC_BASE_URL', endpoint)
    with pytest.raises(RuntimeAdapterError) as caught:
        context(tmp_path)
    assert 'secret' not in str(caught.value)


def test_claude_native_resume_and_activity(tmp_path: Path, claude_environment: None) -> None:
    """Keep native history and new execution IDs, with usage counted at result only."""
    from graphtraj.runtimes.activity import TraceReader

    result_project(tmp_path)
    with ExitStack() as stack:
        first, ready, _ = execution(tmp_path, stack, 'remember-320')
        result = first.run()
        assert ready.is_set() and result['outcome'] == 'completed'
        assert first.terminal_confirmed
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
        assert future.result(timeout=10)['outcome'] == 'interrupted'
        assert turn.terminal_confirmed and turn.proc.poll() is not None
    with ExitStack() as stack, ThreadPoolExecutor(max_workers=1) as pool:
        turn, ready, _ = execution(tmp_path, stack, 'wait-again')
        future = pool.submit(turn.run)
        assert ready.wait(5)
        turn.operate({'operation': 'send', 'session': turn.session, 'execution_id': turn.execution_id, 'instruction': 'finish'})
        assert 'finish' in future.result(timeout=10)['last_agent_message']


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


def test_claude_stop_without_native_settlement_is_unconfirmed(
    tmp_path: Path, claude_environment: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupt ACK followed by pipe exit cannot certify native tool settlement."""
    result_project(tmp_path)
    monkeypatch.setenv('CLAUDE_FIXTURE_NO_SETTLE', '1')
    with ExitStack() as stack, ThreadPoolExecutor(max_workers=1) as pool:
        turn, ready, _ = execution(tmp_path, stack, 'wait-unconfirmed')
        future = pool.submit(turn.run)
        assert ready.wait(5)
        turn.terminate()
        with pytest.raises(RuntimeAdapterError) as caught:
            future.result(timeout=15)
        assert not caught.value.terminal_confirmed
        assert turn.proc.poll() is not None and turn.outcome is None
