"""Registered task Sessions through installed public Runner operations."""

import json
import os
import shutil
import sys
import time
import tomllib
from pathlib import Path
from typing import Callable, Iterator

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, run_process
from runner_fixtures import configure_harness
from test_ticket_graph import _ticket


ManagedProject = tuple[Path, str, Callable[..., dict], Path]


CALL = """
import json, sys
from pathlib import Path
from typing import Callable, Iterator
from graphtraj.execution.runner_batch import parse_batch
from graphtraj.execution.runner_launch import launch_batch
from graphtraj.execution.runner_status import status_aliases
from graphtraj.execution.runner_control import send_instruction, interrupt_session
from graphtraj.execution.runner_models import RunnerError
root = Path(sys.argv[1])
operation, arguments = json.loads(sys.argv[2])
try:
    if operation == 'launch':
        result = launch_batch(parse_batch(arguments), root).document
    elif operation == 'status':
        result = status_aliases(arguments, root, operation_total=True).document
    elif operation == 'send':
        result = send_instruction(arguments[0], arguments[1], root, tuple(arguments[2]))
    elif operation == 'requests':
        from graphtraj.execution.runner_control import pending_requests
        result = pending_requests(arguments[0], root, execution_id=arguments[1] if len(arguments) > 1 else None)
    elif operation == 'reply':
        from graphtraj.execution.runner_control import reply_to_request
        result = reply_to_request(arguments[0], arguments[1], arguments[2], root)
    else:
        result = interrupt_session(arguments[0], root)
    print(json.dumps(result))
except RunnerError as error:
    print(json.dumps({'error': error.as_document()}))
    sys.exit(1)
"""


@pytest.fixture
def managed_project(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> Iterator[ManagedProject]:
    """Set up a project and register a bounded task without starting a Team."""
    from graphtraj.graph.ticket_graph import register_ticket
    from graphtraj.graph.delivery_worldline import append_project_worldline_event

    root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    state = root / '.graphtraj/state'
    register_ticket(state, root, _ticket('113', 'managed-probe'))
    (root / 'instruction.md').write_text('Exercise the registered Session.\n')
    cause = append_project_worldline_event(state, root, {
        'kind': 'main-decision', 'decision': 'Exercise the registered Session.',
        'caused_by_event_ids': [], 'evidence_refs': ['instruction.md'],
    })['event_id']
    executable = fake_codex.executable
    executable.write_text('#!' + sys.executable + '\n' +
                          Path(__file__).with_name('managed_codex_peer.py').read_text())
    executable.chmod(0o755)
    environment['MANAGED_NATIVE_ROOT'] = str(tmp_path / 'native')
    environment['CODEX_HOME'] = str(tmp_path / 'codex-home')
    environment.pop('PYTHONPATH', None)
    python = installed_commands.runner.with_name('python')

    def call(
        operation: str,
        arguments: dict | list,
        timeout: float = 12,
        returncode: int = 0,
    ) -> dict:
        """Each invocation is a separate caller process that must return."""
        command = (
            [str(installed_commands.runner), *arguments] if operation == 'cli' else
            [str(python), '-c', CALL, str(root), json.dumps([operation, arguments])]
        )
        completed = run_process(
            command, cwd=root, env=environment, timeout=timeout,
        )
        with (root / 'public-operations.jsonl').open('a') as evidence:
            evidence.write(json.dumps({
                'operation': operation, 'arguments': arguments,
                'returncode': completed.returncode, 'stdout': completed.stdout,
                'stderr': completed.stderr,
            }) + '\n')
        assert completed.returncode == returncode, completed.stdout + completed.stderr
        return yaml.safe_load(completed.stdout)

    yield root, cause, call, executable
    for path in (root / '.graphtraj/runner/sessions').glob('*/mapping.yml'):
        try:
            call('interrupt', [path.parent.name])
        except AssertionError:
            pass


def launch_document(instruction: str = 'hold', role: str = 'managed-probe') -> dict:
    """Use the existing inline role on a registered task."""
    return {'tasks': [{
        'ticket_id': '113', 'ticket_name': 'managed-probe',
        'role': {role: {'runtime': 'codex', 'model': 'gpt-5.6', 'reasoning_effort': 'low'}},
        'instruction': instruction,
    }]}


def observe(
    call: Callable[..., dict],
    alias: str,
    activity: str,
    outcome: str | None = None,
    timeout: float = 10,
    waiting_for: str | None = None,
) -> dict:
    """Wait for an observable execution state, bounded independently of a PID."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = call('status', [alias])['aliases'][0]
        if (
            status.get('activity') == activity
            and (outcome is None or status.get('last_outcome') == outcome)
            and (waiting_for is None or status.get('waiting_for') == waiting_for)
        ):
            return status
        time.sleep(0.02)
    raise AssertionError(status)


def test_returned_launch_keeps_execution_owned(managed_project: ManagedProject) -> None:
    """The launch caller exits while its registered native execution remains owned."""
    root, _, call, _ = managed_project
    launched = call('launch', launch_document())['tasks'][0]
    assert launched['launch_status'] == 'launched'
    status = observe(call, launched['alias'], 'running')
    assert status['session'] == launched['session']
    assert status['execution_id']


@pytest.mark.skipif(os.environ.get('CODEX_MANAGED_REAL') != '1', reason='explicit real Codex acceptance probe')
def test_real_registered_session(managed_project: ManagedProject) -> None:
    """Exercise public Runner ownership against the installed real Codex Adapter."""
    root, cause, call, executable = managed_project
    real = shutil.which('codex')
    assert real
    executable.unlink()
    executable.symlink_to(real)
    # Use an isolated native store while preserving the operator's connection settings.
    native_home = root / 'codex-home'
    native_home.mkdir()
    operator = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
    for name in ('config.toml', 'auth.json'):
        if (operator / name).is_file():
            shutil.copy2(operator / name, native_home / name)
    document = launch_document('Remember MANAGED_MEMORY_113 for this conversation. Reply exactly MANAGED_SESSION_READY. Do not use tools in this turn.')
    config = tomllib.loads((native_home / 'config.toml').read_text()) if (native_home / 'config.toml').exists() else {}
    document['tasks'][0]['role']['managed-probe']['model'] = os.environ.get(
        'CODEX_MANAGED_MODEL', config.get('model', 'gpt-5.6'),
    )
    launched = call('launch', document, timeout=30)['tasks'][0]
    assert launched['launch_status'] == 'launched'
    alias = launched['alias']
    timeout = float(os.environ.get('CODEX_MANAGED_WAIT', '120'))
    first = observe(call, alias, 'idle', 'completed', timeout=timeout)
    from graphtraj.execution.runner_status import read_alias_mapping
    from graphtraj.runtimes.codex.codex_adapter import read_codex_last_agent_message
    mapping, directory = read_alias_mapping(root / '.graphtraj/runner', alias)

    def answer_contains(*words: str) -> None:
        """Check consumed input using the Adapter's retained native final answer."""
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            answer = read_codex_last_agent_message(Path(mapping['trace_file'])) or ''
            if all(word in answer for word in words):
                return
            time.sleep(0.02)
        raise AssertionError(answer)

    def wait_for_tool(target: str, previous_total: int) -> dict:
        """Wait for a real native tool request before active control."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = call('status', [target])['aliases'][0]
            if status.get('operation_total', 0) > previous_total:
                assert status['activity'] == 'running', status
                return status
            time.sleep(0.05)
        raise AssertionError(status)

    answer_contains('MANAGED_SESSION_READY')
    call('send', [alias, 'Run a shell sleep for 15 seconds, then reply with the word you remembered and any later instruction.', [cause]])
    active = wait_for_tool(alias, first['operation_total'])
    assert active['session'] == launched['session']
    assert active['execution_id'] != first['execution_id']
    call('send', [alias, 'Include MANAGED_STEER_113 in your final reply.', [cause]])
    steered = observe(call, alias, 'idle', 'completed', timeout=timeout)
    assert steered['execution_id'] == active['execution_id']
    answer_contains('MANAGED_MEMORY_113', 'MANAGED_STEER_113')

    peer_document = json.loads(json.dumps(document))
    task = peer_document['tasks'][0]
    task['role']['peer-probe'] = task['role'].pop('managed-probe')
    task['instruction'] = 'Run a shell sleep for 30 seconds before replying.'
    peer = call('launch', peer_document)['tasks'][0]
    wait_for_tool(peer['alias'], 0)
    call('send', [alias, 'Run a shell sleep for 30 seconds before replying.', [cause]])
    wait_for_tool(alias, steered['operation_total'])
    call('interrupt', [alias])
    observe(call, alias, 'idle', 'interrupted')
    observe(call, peer['alias'], 'running')
    call('interrupt', [peer['alias']])
    call('send', [alias, 'Reply with the word remembered at the start. Use no tools.', [cause]])
    final = observe(call, alias, 'idle', 'completed', timeout=timeout)
    assert final['session'] == launched['session']
    answer_contains('MANAGED_MEMORY_113')
    metadata = yaml.safe_load((directory / 'session.yml').read_text())
    native = Path(metadata['rollout_path'])
    native_records = [json.loads(line) for line in native.read_text().splitlines()]
    assert native_records[0]['payload']['id'] == launched['session']
    # The Trace entry reads that Runtime-owned native file directly, while the
    # Runner's own records stay in the Session directory.
    trace = Path(mapping['trace_file'])
    assert os.readlink(trace) == str(native)
    assert trace.read_bytes() == native.read_bytes()
    session_records = (directory / 'events.jsonl').read_text()
    assert '"type":"runtime"' in session_records
    assert '"type": "runner-execution-start"' in session_records
    assert '"type":"runner-follow-up"' in session_records
    assert '"type":"runtime"' not in native.read_text()
    assert 'runner-execution-start' not in native.read_text()
    assert 'runner-follow-up' not in native.read_text()


def test_active_input_reaches_the_same_native_execution(managed_project: ManagedProject) -> None:
    """Input steers the active turn instead of starting a queued continuation."""
    root, cause, call, _ = managed_project
    launched = call('launch', launch_document())['tasks'][0]
    alias = launched['alias']
    before = observe(call, alias, 'running')
    assert call('send', [alias, 'complete after active input', [cause]]) == {
        'alias': alias, 'send_status': 'sent',
    }
    after = observe(call, alias, 'idle', 'completed')
    assert after['session'] == before['session'] == launched['session']
    assert after['execution_id'] == before['execution_id']


def test_idle_continuation_preserves_alias_and_native_history(managed_project: ManagedProject) -> None:
    """A later caller restores the same conversation with a new execution ID."""
    root, cause, call, _ = managed_project
    launched = call('launch', launch_document())['tasks'][0]
    alias = launched['alias']
    call('send', [alias, 'complete first execution', [cause]])
    first = observe(call, alias, 'idle', 'completed')
    # Allow explicit connection cleanup before testing a separate owner.
    time.sleep(0.2)
    call('send', [alias, 'hold', [cause]])
    second = observe(call, alias, 'running')
    assert second['session'] == first['session'] == launched['session']
    assert second['execution_id'] != first['execution_id']
    assert second['last_outcome'] == 'completed'
    call('send', [alias, 'complete second execution', [cause]])
    observe(call, alias, 'idle', 'completed')
    from graphtraj.execution.runner_status import read_alias_mapping
    from graphtraj.runtimes.codex.codex_adapter import read_codex_last_agent_message
    mapping, directory = read_alias_mapping(root / '.graphtraj/runner', alias)
    assert read_codex_last_agent_message(Path(mapping['trace_file'])) == 'complete second execution'
    records = [json.loads(line) for line in Path(mapping['trace_file']).read_text().splitlines()]
    assert [r['payload']['id'] for r in records if r['type'] == 'session_meta'] == [launched['session']]


def test_interrupt_is_targeted_and_terminal_before_service_exit(managed_project: ManagedProject) -> None:
    """Native cancellation leaves a peer running and confirms only the target turn."""
    root, cause, call, _ = managed_project
    first = call('launch', launch_document(role='first-probe'))['tasks'][0]
    second = call('launch', launch_document(role='second-probe'))['tasks'][0]
    before = observe(call, first['alias'], 'running')
    assert call('interrupt', [first['alias']]) == {
        'alias': first['alias'], 'interrupt_status': 'interrupted',
    }
    status = observe(call, first['alias'], 'idle', 'interrupted')
    assert status['execution_id'] == before['execution_id']
    assert not (root / 'native' / (first['session'] + '.closed')).exists()
    observe(call, second['alias'], 'running')
    call('send', [second['alias'], 'complete unaffected peer', [cause]])
    observe(call, second['alias'], 'idle', 'completed')


def test_native_failure_is_distinct_from_interruption(managed_project: ManagedProject) -> None:
    """A failed native turn remains a runtime error while its service is alive."""
    root, cause, call, _ = managed_project
    launched = call('launch', launch_document())['tasks'][0]
    call('send', [launched['alias'], 'fail execution', [cause]])
    failed = observe(call, launched['alias'], 'idle', 'runtime-error')
    assert failed['session'] == launched['session']
    assert not (root / 'native' / (launched['session'] + '.closed')).exists()


def test_concurrent_idle_sends_keep_one_native_owner(managed_project: ManagedProject) -> None:
    """Competing callers cannot resume the alias into two concurrent native turns."""
    from concurrent.futures import ThreadPoolExecutor
    from graphtraj.execution.runner_status import read_alias_mapping

    root, cause, call, _ = managed_project
    launched = call('launch', launch_document())['tasks'][0]
    alias = launched['alias']
    call('send', [alias, 'complete initial work', [cause]])
    observe(call, alias, 'idle', 'completed')
    with ThreadPoolExecutor(2) as callers:
        results = list(callers.map(lambda text: call('send', [alias, text, [cause]]), ('hold', 'hold')))
    assert results == [{'alias': alias, 'send_status': 'sent'}] * 2
    observe(call, alias, 'idle', 'completed')
    mapping, _ = read_alias_mapping(root / '.graphtraj/runner', alias)
    native = root / 'native' / ('rollout-' + launched['session'] + '.jsonl')
    contexts = [json.loads(line)['payload'] for line in native.read_text().splitlines()
                if json.loads(line)['type'] == 'turn_context']
    assert len(contexts) == 2
    assert contexts[-1]['execution_id'] == mapping['execution_id']


def test_each_registered_task_keeps_its_role_context(managed_project: ManagedProject) -> None:
    """The shared launch operation passes independent native task/model/effort contexts."""
    from graphtraj.graph.ticket_graph import register_ticket

    root, cause, call, _ = managed_project
    register_ticket(root / '.graphtraj/state', root, _ticket('114', 'other-probe'))
    first = launch_document(role='first-probe')['tasks'][0]
    second = {
        **first, 'ticket_id': '114', 'ticket_name': 'other-probe',
        'role': {'second-probe': {'runtime': 'codex', 'model': 'different-model', 'reasoning_effort': 'high'}},
    }
    launched = call('launch', {'tasks': [first, second]})['tasks']
    observed = []
    for task in launched:
        observe(call, task['alias'], 'running')
        native = root / 'native' / ('rollout-' + task['session'] + '.jsonl')
        context = [json.loads(line)['payload'] for line in native.read_text().splitlines()
                   if json.loads(line)['type'] == 'turn_context'][0]
        observed.append((context['ticket_id'], context['role'], context['model'], context['effort']))
        call('send', [task['alias'], 'complete task', [cause]])
    assert observed == [('113', 'first-probe', 'gpt-5.6', 'low'),
                        ('114', 'second-probe', 'different-model', 'high')]
    assert len({task['session'] for task in launched}) == 2


def test_later_caller_can_answer_native_approval(managed_project: ManagedProject) -> None:
    """Human approval survives the RPC deadline and returns to the owned turn."""
    root, cause, call, _ = managed_project
    launched = call('launch', launch_document())['tasks'][0]
    call('send', [launched['alias'], 'unhandled request', [cause]])
    pending = call('requests', [launched['alias']])
    request, = pending['requests']
    assert request['request_id'] == 'approval'
    assert request['method'] == 'item/commandExecution/requestApproval'
    assert request['params'] == {
        'threadId': launched['session'], 'turnId': request['execution_id'],
        'command': 'printf APPROVAL_121', 'cwd': str(root / '.graphtraj/.agent-worktrees/dev'),
    }
    assert request['session'] == pending['session'] == launched['session']
    assert request['execution_id'] == pending['execution_id']
    # A human takes longer than the Worker's five-second RPC deadline.
    time.sleep(5.2)
    status = call('status', [launched['alias']])['aliases'][0]
    assert status['activity'] == 'running'
    assert status['waiting_for'] == 'runtime-request'
    assert status['execution_id'] == request['execution_id']
    assert not (root / 'native' / (launched['session'] + '.closed')).exists()
    reply = call('reply', [launched['alias'], request, {'decision': 'accept'}])
    assert reply['reply_status'] == 'submitted'
    assert reply['request_id'] == 'approval'
    completed = observe(call, launched['alias'], 'idle', 'completed')
    assert completed['execution_id'] == request['execution_id']
    assert call('requests', [launched['alias']])['requests'] == []
    native = root / 'native' / ('rollout-' + launched['session'] + '.jsonl')
    records = [json.loads(line) for line in native.read_text().splitlines()]
    assert records[-1]['payload']['last_agent_message'] == 'approval:accept'


def test_installed_cli_declines_the_same_request_as_python(managed_project: ManagedProject) -> None:
    """Both interfaces expose identical requests and preserve an explicit decline."""
    root, cause, call, _ = managed_project
    launched = call('launch', launch_document())['tasks'][0]
    alias = launched['alias']
    call('send', [alias, 'unhandled request', [cause]])
    queried = call('requests', [alias])
    assert call('cli', ['requests', alias, '--execution-id', queried['execution_id']]) == queried
    request, = queried['requests']
    request_file = root / 'request.yml'
    request_file.write_text(yaml.safe_dump(request))
    reply = call('cli', ['reply', alias, '--request-file', str(request_file),
                         '--response', '{"decision":"decline"}'])
    assert reply == {
        'alias': alias, 'session': request['session'], 'execution_id': request['execution_id'],
        'request_id': 'approval', 'reply_status': 'submitted',
    }
    completed = observe(call, alias, 'idle', 'completed')
    assert completed['execution_id'] == request['execution_id']
    from graphtraj.execution.runner_status import read_alias_mapping
    from graphtraj.runtimes.codex.codex_adapter import read_codex_last_agent_message
    mapping, _ = read_alias_mapping(root / '.graphtraj/runner', alias)
    assert read_codex_last_agent_message(Path(mapping['trace_file'])) == 'approval:decline'


def test_waiting_requests_are_isolated_and_interruptible(managed_project: ManagedProject) -> None:
    """Colliding native request IDs cannot route a reply or interrupt to a peer."""
    root, _, call, _ = managed_project
    first = call('launch', launch_document('request:approval', 'first-probe'))['tasks'][0]
    second = call('launch', launch_document('request:approval', 'second-probe'))['tasks'][0]
    left, = call('requests', [first['alias']])['requests']
    right, = call('requests', [second['alias']])['requests']
    assert left['request_id'] == right['request_id'] == 'approval'
    assert left['session'] != right['session']
    assert left['request_token'] != right['request_token']
    rejected = call('reply', [second['alias'], left, {'decision': 'accept'}], returncode=1)
    assert rejected['error']['code'] == 'operation-failed'
    assert call('requests', [second['alias']])['requests'] == [right]
    assert call('status', [first['alias']])['aliases'][0]['waiting_for'] == 'runtime-request'
    assert call('interrupt', [first['alias']])['interrupt_status'] == 'interrupted'
    ended = observe(call, first['alias'], 'idle', 'interrupted')
    assert ended['execution_id'] == left['execution_id']
    assert call('requests', [first['alias']])['requests'] == []
    assert call('reply', [first['alias'], left, {'decision': 'accept'}], returncode=1)['error']
    assert call('requests', [second['alias']])['requests'] == [right]
    assert call('status', [second['alias']])['aliases'][0]['activity'] == 'running'
    call('reply', [second['alias'], right, {'decision': 'decline'}])
    observe(call, second['alias'], 'idle', 'completed')


def test_expired_reply_cannot_answer_a_reused_native_id(managed_project: ManagedProject) -> None:
    """Withdrawal, duplicate replies and successor turns cannot revive an old request."""
    _, cause, call, _ = managed_project
    launched = call('launch', launch_document('request:approval'))['tasks'][0]
    alias = launched['alias']
    old, = call('requests', [alias])['requests']
    call('send', [alias, 'withdraw and reissue', [cause]])
    current, = call('requests', [alias])['requests']
    assert current['request_id'] == old['request_id']
    assert current['execution_id'] == old['execution_id']
    assert current['request_token'] != old['request_token']
    assert call('reply', [alias, old, {'decision': 'accept'}], returncode=1)['error']
    assert call('requests', [alias])['requests'] == [current]
    call('reply', [alias, current, {'decision': 'decline'}])
    observe(call, alias, 'idle', 'completed')
    assert call('reply', [alias, current, {'decision': 'accept'}], returncode=1)['error']
    call('send', [alias, 'request:approval', [cause]])
    successor, = call('requests', [alias])['requests']
    assert successor['session'] == current['session']
    assert successor['execution_id'] != current['execution_id']
    assert successor['request_id'] == current['request_id']
    assert call('requests', [alias, current['execution_id']], returncode=1)['error']
    assert call('reply', [alias, current, {'decision': 'accept'}], returncode=1)['error']
    assert call('requests', [alias])['requests'] == [successor]
    call('reply', [alias, successor, {'decision': 'decline'}])
    observe(call, alias, 'idle', 'completed')


def test_multiple_native_requests_keep_input_and_trace_contents(managed_project: ManagedProject) -> None:
    """User input and command replies retain their native schemas and ID types."""
    root, _, call, _ = managed_project
    launched = call('launch', launch_document('request:multiple'))['tasks'][0]
    alias = launched['alias']
    approval, user_input = call('requests', [alias])['requests']
    assert user_input['request_id'] == 7
    assert user_input['method'] == 'item/tool/requestUserInput'
    assert user_input['params']['questions'] == [{'id': 'color', 'question': 'Choose a color.'}]
    # Invalid caller values must leave both requests answerable.
    for invalid in (None, [], 'accept', {'value': float('nan')}):
        rejected = call('reply', [alias, approval, invalid], returncode=1)
        assert rejected['error']['code'] == 'invalid-input'
    assert call('requests', [alias])['requests'] == [approval, user_input]
    call('reply', [alias, approval, {'decision': 'accept'}])
    assert call('status', [alias])['aliases'][0]['waiting_for'] == 'runtime-request'
    assert call('requests', [alias])['requests'] == [user_input]
    answer = {'answers': {'color': {'answers': ['蓝色']}}}
    request_file = root / 'input-request.json'
    request_file.write_text(json.dumps(user_input))
    call('cli', ['reply', alias, '--request-file', str(request_file), '--response', json.dumps(answer)])
    observe(call, alias, 'idle', 'completed')
    native = root / 'native' / ('rollout-' + launched['session'] + '.jsonl')
    assert [json.loads(line) for line in native.with_suffix('.replies.jsonl').read_text().splitlines()] == [
        {'id': 'approval', 'result': {'decision': 'accept'}}, {'id': 7, 'result': answer},
    ]
    from graphtraj.execution.runner_status import read_alias_mapping
    from graphtraj.runtimes.codex.codex_adapter import read_codex_last_agent_message
    mapping, session_directory = read_alias_mapping(root / '.graphtraj/runner', alias)
    trace = Path(mapping['trace_file'])
    assert json.loads(read_codex_last_agent_message(trace)) == answer
    assert os.readlink(trace) == str(native)
    assert trace.read_bytes() == native.read_bytes()
    session_records = (session_directory / 'events.jsonl').read_text()
    assert '"type":"runtime"' in session_records
    assert '"type": "runner-execution-start"' in session_records
    assert '"type":"runtime"' not in native.read_text()
    assert 'runner-execution-start' not in native.read_text()


@pytest.mark.parametrize('operation', ['send', 'interrupt'])
def test_fast_completion_keeps_the_control_reply_available(
    managed_project: ManagedProject, operation: str,
) -> None:
    """Immediate service exit must not delete an acknowledged caller's response."""
    _, cause, call, executable = managed_project
    executable.write_text(executable.read_text().replace('time.sleep(1)', 'time.sleep(0)'))
    launched = call('launch', launch_document())['tasks'][0]
    alias = launched['alias']
    arguments = [alias, 'complete immediately', [cause]] if operation == 'send' else [alias]
    assert call(operation, arguments) == {
        'alias': alias,
        'send_status' if operation == 'send' else 'interrupt_status':
            'sent' if operation == 'send' else 'interrupted',
    }
    observe(call, alias, 'idle', 'completed' if operation == 'send' else 'interrupted')


def test_idle_continuation_survives_predecessor_status_reply_cleanup(
    managed_project: ManagedProject, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A delayed status acknowledgement cannot restore an older execution's result."""
    import tempfile
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from graphtraj.execution.runner_process import process_is_alive
    from graphtraj.execution.runner_status import read_alias_mapping, status_aliases

    root, cause, call, _ = managed_project
    launched = call('launch', launch_document())['tasks'][0]
    alias = launched['alias']
    predecessor, _ = read_alias_mapping(root / '.graphtraj/runner', alias)
    acknowledged = threading.Event()
    release = threading.Event()
    status_caller = None
    cleanup = tempfile.TemporaryDirectory.cleanup

    def delayed_cleanup(directory: tempfile.TemporaryDirectory) -> None:
        """Deschedule only the status caller before it removes its acknowledged reply."""
        if threading.current_thread() is status_caller:
            acknowledged.set()
            assert release.wait(8), 'Delayed status exceeded the control timeout'
        cleanup(directory)

    def delayed_status() -> dict:
        """Use the public status operation with a controlled filesystem scheduling pause."""
        nonlocal status_caller
        status_caller = threading.current_thread()
        return status_aliases([alias], root).document

    with ThreadPoolExecutor(1) as callers, monkeypatch.context() as scheduling:
        scheduling.setattr(tempfile.TemporaryDirectory, 'cleanup', delayed_cleanup)
        pending_status = callers.submit(delayed_status)
        try:
            assert acknowledged.wait(3), 'The native status response was not acknowledged'
            call('send', [alias, 'complete the predecessor', [cause]])
            observe(call, alias, 'idle', 'completed')
            # Continuation must return while the earlier status caller is still paused.
            call('send', [alias, 'hold', [cause]], timeout=3)
            successor = observe(call, alias, 'running')
            assert successor['session'] == launched['session']
            assert successor['execution_id'] != predecessor['execution_id']

            release.set()
            earlier = pending_status.result(timeout=3)['aliases'][0]
            assert earlier['execution_id'] == predecessor['execution_id']
            # PID liveness only sequences owner cleanup; execution assertions use Runner.
            deadline = time.monotonic() + 3
            while process_is_alive(predecessor['worker_pid']) and time.monotonic() < deadline:
                time.sleep(0.01)
            assert not process_is_alive(predecessor['worker_pid']), 'Predecessor cleanup did not finish'
            current = call('status', [alias])['aliases'][0]
            assert current['execution_id'] == successor['execution_id']
            assert current['session'] == successor['session']
            assert current['activity'] == 'running'
            assert call('interrupt', [alias]) == {'alias': alias, 'interrupt_status': 'interrupted'}
            observe(call, alias, 'idle', 'interrupted')
        finally:
            release.set()


def test_permission_wait_keeps_heartbeating(managed_project: ManagedProject) -> None:
    """A pending request reply keeps heartbeating while the model stays silent."""
    from graphtraj.execution.runner_heartbeat import read_heartbeat
    from graphtraj.execution.runner_status import read_alias_mapping

    root, _, call, _ = managed_project
    launched = call('launch', launch_document('request:approval'))['tasks'][0]
    alias = launched['alias']
    waiting = observe(call, alias, 'running', waiting_for='runtime-request')
    mapping, session_directory = read_alias_mapping(root / '.graphtraj/runner', alias)
    first = read_heartbeat(session_directory)
    assert first['alias'] == alias
    assert first['worker_pid'] == mapping['worker_pid']
    assert first['execution_id'] == waiting['execution_id']
    deadline = time.monotonic() + 5
    while read_heartbeat(session_directory)['updated_at'] == first['updated_at']:
        assert time.monotonic() < deadline, 'The waiting Worker stopped heartbeating'
        time.sleep(0.05)
    current = call('status', [alias])['aliases'][0]
    assert current['activity'] == 'running'
    assert current['waiting_for'] == 'runtime-request'
    assert call('interrupt', [alias]) == {'alias': alias, 'interrupt_status': 'interrupted'}
    observe(call, alias, 'idle', 'interrupted')


def test_terminal_record_is_kept_without_a_usable_heartbeat(
    managed_project: ManagedProject,
) -> None:
    """A published outcome survives a stale and a missing Worker heartbeat."""
    from graphtraj.execution.runner_heartbeat import HEARTBEAT_FILE_NAME, read_heartbeat
    from graphtraj.execution.runner_status import read_alias_mapping

    root, cause, call, _ = managed_project
    launched = call('launch', launch_document())['tasks'][0]
    alias = launched['alias']
    call('send', [alias, 'complete task', [cause]])
    completed = observe(call, alias, 'idle', 'completed')
    mapping, session_directory = read_alias_mapping(root / '.graphtraj/runner', alias)
    assert read_heartbeat(session_directory)['execution_id'] == completed['execution_id']
    heartbeat_file = session_directory / HEARTBEAT_FILE_NAME
    heartbeat_file.write_text(
        yaml.safe_dump(
            {
                'alias': alias,
                'worker_pid': mapping['worker_pid'],
                'updated_at': 0.0,
            },
            sort_keys=False,
        ),
        encoding='utf-8',
    )
    stale = call('status', [alias])['aliases'][0]
    assert (stale['activity'], stale['last_outcome']) == ('idle', 'completed')
    heartbeat_file.unlink()
    missing = call('status', [alias])['aliases'][0]
    assert (missing['activity'], missing['last_outcome']) == ('idle', 'completed')


def test_identifier_without_the_ownership_lock_is_not_the_owned_execution(
    managed_project: ManagedProject,
) -> None:
    """A live reused identifier and an absent owner both report an abnormal end."""
    import subprocess

    from graphtraj.execution.runner_heartbeat import hold_ownership, write_heartbeat

    root, _, call, _ = managed_project
    stand_in = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    try:
        alias = 'reused-identifier@e1'
        directory = root / '.graphtraj/runner/sessions' / alias
        directory.mkdir(parents=True)
        trace = directory / 'events.jsonl'
        trace.write_text('', encoding='utf-8')
        (directory / 'mapping.yml').write_text(
            yaml.safe_dump(
                {
                    'alias': alias,
                    'runtime': 'codex',
                    'session': 'native-session',
                    'ticket_id': '113',
                    'team_generation': 1,
                    'role': 'managed-probe',
                    'parent': None,
                    'retained_batch_file': 'batch.yml',
                    'worktree_path': str(root),
                    'trace_file': str(trace),
                    'worker_pid': stand_in.pid,
                    'runtime_pid': stand_in.pid,
                },
                sort_keys=False,
            ),
            encoding='utf-8',
        )
        # The identifier is live again in an unrelated process. The earlier
        # owner's lock file is left behind released, as a killed Worker does.
        hold_ownership(directory, stand_in.pid).close()
        write_heartbeat(directory, {
            'alias': alias,
            'worker_pid': stand_in.pid,
            'execution_id': 'native-execution',
        })
        status = call('status', [alias])['aliases'][0]
        assert status['activity'] == 'abnormal', status
        assert 'last_outcome' not in status
        assert status['heartbeat_at'] > 0
        # An owner that is gone entirely reports the same, never death by PID.
        stand_in.terminate()
        stand_in.wait(timeout=5)
        assert call('status', [alias])['aliases'][0]['activity'] == 'abnormal'
    finally:
        stand_in.terminate()
        stand_in.wait(timeout=5)


def test_stopped_worker_reports_lost_contact_and_recovers(
    managed_project: ManagedProject,
) -> None:
    """A stopped Worker is lost contact, not death, and answers again later."""
    import signal

    from graphtraj.execution.runner_heartbeat import read_heartbeat
    from graphtraj.execution.runner_status import read_alias_mapping

    root, _, call, _ = managed_project
    launched = call('launch', launch_document('request:approval'))['tasks'][0]
    alias = launched['alias']
    observe(call, alias, 'running', waiting_for='runtime-request')
    mapping, session_directory = read_alias_mapping(root / '.graphtraj/runner', alias)
    os.kill(mapping['worker_pid'], signal.SIGSTOP)
    try:
        stopped = read_heartbeat(session_directory)
        lost = call('status', [alias], timeout=30)['aliases'][0]
        assert lost['activity'] == 'unreachable', lost
        # The heartbeat stayed frozen while control was unanswered, so the
        # judgement came from the owner and process identity, not from it.
        assert read_heartbeat(session_directory)['updated_at'] == stopped['updated_at']
    finally:
        os.kill(mapping['worker_pid'], signal.SIGCONT)
    recovered = observe(call, alias, 'running', waiting_for='runtime-request', timeout=15)
    assert recovered['session'] == launched['session']
    assert call('interrupt', [alias]) == {'alias': alias, 'interrupt_status': 'interrupted'}
    observe(call, alias, 'idle', 'interrupted')
