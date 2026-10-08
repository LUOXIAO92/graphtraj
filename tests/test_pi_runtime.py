"""Pi's public Runtime contract with controlled native pipes and hosted CLI."""

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

from graphtraj.configuration.project_roles import RolePreset, parse_inline_role
from graphtraj.configuration.role_definitions import resolve_child_role
from graphtraj.execution.runner_heartbeat import hold_ownership
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError, select_runtime_adapter
from graphtraj.runtimes.pi.managed_session import PiManagedExecution
from test_result_submission import result_project


@pytest.fixture
def pi_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Install controlled native executables; isolation itself needs live evidence."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    fixture = Path(__file__).with_name('pi_rpc_fixture.py')
    pi = bin_dir / 'pi'
    pi.write_text(f'#!{sys.executable}\n' + fixture.read_text())
    pi.chmod(0o755)
    srt = bin_dir / 'srt'
    srt.write_text(f'#!{sys.executable}\nimport os,sys,json\n'
                   'policy=json.load(open(sys.argv[sys.argv.index("--settings")+1]))\n'
                   'assert isinstance(policy["network"]["deniedDomains"],list)\n'
                   'a=sys.argv[sys.argv.index("--")+1:]\nos.execv(a[0],a)\n')
    srt.chmod(0o755)
    sandbox = tmp_path / 'agent_sandbox'
    sandbox.mkdir()
    (sandbox / '__init__.py').write_text(
        'import shutil\ndef is_sandbox_available(): return shutil.which("srt") is not None\n'
        'def resolve_profile(name): return {"filesystem": {"denyRead": [], "denyWrite": []}}\n'
        'def wrap_command(cmd, profile): return ["srt", "--settings", profile, "--", *cmd]\n')
    monkeypatch.setenv('PATH', str(bin_dir) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('PYTHONPATH', str(tmp_path) + os.pathsep + str(Path(__file__).resolve().parents[1] / 'src'))
    monkeypatch.setenv('PI_FIXTURE_ROOT', str(tmp_path))
    return {'sandbox_python': sys.executable, 'sandbox_path': os.environ['PATH'],
            'agent_dir': str(tmp_path / 'user-agent')}


def context(root: Path, config: dict, model: str = 'deepseek/deepseek-flash', **role_fields):
    """Prepare a real Pi Adapter through the public role/Runtime boundary."""
    _, settings = parse_inline_role({'author': {
        'runtime': 'pi', 'model': model, 'pi': config, **role_fields,
    }})
    role = resolve_child_role('author', settings, root)
    adapter = select_runtime_adapter('pi')
    prepared = adapter.preflight_runtime_context(
        harness_root=root, git_common_directory=root / 'worktrees/research/.git', role=role,
        worktree=root / 'worktrees/research', evidence=root / 'state', requested_skills=(),
        report_files=(Path('.state/teams/1/rounds/1/researcher-x1.md'),),
    ).finalize()
    return adapter, prepared


def execution(
    root: Path,
    config: dict,
    alias: str,
    prompt: str,
    stack: ExitStack,
    expected: str | None = None,
    **role_fields,
):
    """Bind fixture ownership using actual process IDs before native task work."""
    adapter, prepared = context(root, config, **role_fields)
    runner = root / '.graphtraj/runner'
    directory = runner / 'sessions' / alias
    trace = root / 'state' / (alias + '.jsonl')
    trace.parent.mkdir(exist_ok=True)
    ready = threading.Event()

    def created(session: str, pid: int) -> None:
        """Check pre-prompt order and provide real ownership to hosted CLI tests."""
        native = trace.with_suffix('.pi') / 'session.jsonl'
        if not expected:
            assert len(native.read_text().splitlines()) == 1
        mapping = yaml.safe_load((directory / 'mapping.yml').read_text())
        mapping.update(runtime='pi', session=session, worker_pid=os.getpid(), runtime_pid=pid, trace_file=str(trace))
        (directory / 'mapping.yml').write_text(yaml.safe_dump(mapping))

    def started(session: str, pid: int) -> None:
        """Signal a bound execution with a ready control channel."""
        ready.set()

    stack.enter_context(hold_ownership(directory, os.getpid()))
    turn = adapter.managed_execution(prepared.launch_document()['adapter_request'], prompt, directory,
                                    started, prepared.evidence_document(), trace_file=trace,
                                    expected_session=expected, session_created=created)
    return turn, ready, trace


def wait_started(turn: PiManagedExecution, ready: threading.Event) -> None:
    """Wait for fixture acceptance, not for runtime work by repeated status calls."""
    assert ready.wait(5)
    deadline = time.monotonic() + 5
    while not turn.prompt_started and time.monotonic() < deadline:
        time.sleep(0.005)
    assert turn.prompt_started


def test_pi_config_dependency_and_host_limits(tmp_path: Path, pi_environment: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve provider IDs, refuse missing isolation, and keep secrets out of Context."""
    result_project(tmp_path)
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fixture-secret')
    adapter, prepared = context(tmp_path, pi_environment, 'openrouter/google/gemini-3.8-flash')
    launch = prepared.launch_document()
    assert launch['adapter_request']['model'] == 'google/gemini-3.8-flash'
    assert 'fixture-secret' not in json.dumps(launch)
    assert launch['adapter_request']['reports'] == [str(tmp_path / 'state/teams/1/rounds/1/researcher-x1.md')]
    assert Path(adapter.finalize_hook(tmp_path, {})['extension']).is_file()
    (tmp_path / 'bin/srt').unlink()
    with pytest.raises(RuntimeAdapterError, match='requires srt'):
        context(tmp_path, pi_environment)


def test_pi_startup_failure_preserves_diagnostics(tmp_path: Path, pi_environment: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """A pre-binding native exit retains its cause without claiming cleanup or exposing credentials."""
    result_project(tmp_path)
    monkeypatch.setenv('PI_FIXTURE_STARTUP_FAILURE', '1')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fixture-private-key')
    with ExitStack() as stack:
        turn, ready, _ = execution(tmp_path, pi_environment, 'research@x1', 'unused', stack)
        (turn.directory / 'stderr.log').write_text('old execution stderr must stay private\n')
        with pytest.raises(RuntimeAdapterError) as caught:
            turn.run()
    message = str(caught.value)
    assert caught.value.terminal_confirmed is False
    assert 'Original error [RUNTIME_' in message
    assert 'PermissionError: fixture startup resource denied' in message
    assert 'Native process exit: 71' in message
    assert 'fixture-private-key' not in message
    assert 'fixture-token' not in message
    assert 'old execution stderr' not in message
    assert not ready.is_set()


def test_pi_private_stderr_is_not_inherited(tmp_path: Path, pi_environment: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Native stdio metadata access must not require reading a private Runner file."""
    result_project(tmp_path)
    monkeypatch.setenv('PI_FIXTURE_PIPE_STDERR', '1')
    with ExitStack() as stack:
        turn, _, _ = execution(tmp_path, pi_environment, 'research@x1', 'pipe-stderr', stack)
        assert turn.run()['outcome'] == 'completed'


def test_pi_continuation_and_native_trace(tmp_path: Path, pi_environment: dict) -> None:
    """Same native Session and original context survive a new Worker invocation."""
    result_project(tmp_path)
    with ExitStack() as stack:
        turn, _, trace = execution(tmp_path, pi_environment, 'research@x1', 'remember-247', stack)
        first = turn.run()
    assert first['outcome'] == 'completed'
    assert 'remember-247' in first['last_agent_message']
    assert json.loads(trace.read_text().splitlines()[0])['id'] == first['session_id']
    with ExitStack() as stack:
        resumed, _, _ = execution(tmp_path, pi_environment, 'research@x1', 'continue', stack, first['session_id'])
        second = resumed.run()
    assert second['session_id'] == first['session_id']
    assert 'remember-247' in second['last_agent_message']
    assert second['execution_id'] != first['execution_id']


def test_pi_active_input_and_independent_confirmed_stop(tmp_path: Path, pi_environment: dict) -> None:
    """Queue clearing precedes abort; stopping one pipe leaves the other running."""
    result_project(tmp_path)
    with ExitStack() as stack, ThreadPoolExecutor(max_workers=2) as pool:
        a, ar, _ = execution(tmp_path, pi_environment, 'research@x1', 'wait-a', stack)
        b, br, _ = execution(tmp_path, pi_environment, 'research@x2', 'wait-b', stack)
        af, bf = pool.submit(a.run), pool.submit(b.run)
        wait_started(a, ar)
        wait_started(b, br)
        a.operate({'operation': 'send', 'session': a.session, 'execution_id': a.execution_id, 'instruction': 'must-be-cleared'})
        a.operate({'operation': 'interrupt', 'session': a.session, 'execution_id': a.execution_id})
        result = af.result(timeout=5)
        assert result['outcome'] == 'interrupted'
        assert 'must-be-cleared' not in result['last_agent_message']
        assert not bf.done()
        with pytest.raises(RuntimeAdapterError, match='not owned'):
            b.operate({'operation': 'interrupt', 'session': a.session, 'execution_id': a.execution_id})
        b.operate({'operation': 'send', 'session': b.session, 'execution_id': b.execution_id,
                   'instruction': 'finish'})
        delivered = bf.result(timeout=5)
        assert delivered['outcome'] == 'completed'
        assert 'finish' in delivered['last_agent_message']
    with ExitStack() as stack:
        resumed, _, _ = execution(tmp_path, pi_environment, 'research@x1', 'after-stop', stack, result['session_id'])
        assert 'wait-a' in resumed.run()['last_agent_message']


def test_pi_input_at_native_settlement(tmp_path: Path, pi_environment: dict) -> None:
    """Input reaching an already idle Pi must start work rather than strand a queue."""
    result_project(tmp_path)
    with ExitStack() as stack, ThreadPoolExecutor(max_workers=1) as pool:
        turn, ready, trace = execution(tmp_path, pi_environment, 'research@x1', 'settled-race', stack)
        future = pool.submit(turn.run)
        wait_started(turn, ready)
        marker = trace.with_suffix('.pi') / 'idle-marker'
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.005)
        try:
            assert marker.exists()
            turn.operate({'operation': 'send', 'session': turn.session,
                          'execution_id': turn.execution_id, 'instruction': 'after-settled'})
            result = future.result(timeout=3)
            assert result['outcome'] == 'completed'
            assert 'after-settled' in result['last_agent_message']
        finally:
            if not future.done():
                turn.terminate()
                future.result(timeout=5)


def test_pi_dialog_and_provider_error(tmp_path: Path, pi_environment: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Status notifications are harmless; actual dialogs wait for explicit replies."""
    result_project(tmp_path)
    notices = []
    monkeypatch.setattr('graphtraj.execution.runner_control.notify_direct_parent',
                        lambda *args: notices.append(args))
    with ExitStack() as stack, ThreadPoolExecutor(max_workers=1) as pool:
        turn, ready, _ = execution(tmp_path, pi_environment, 'research@x1', 'dialog', stack)
        future = pool.submit(turn.run)
        wait_started(turn, ready)
        deadline = time.monotonic() + 5
        while not notices and time.monotonic() < deadline:
            time.sleep(0.01)
        assert notices and not future.done()
        pending = turn.operate({'operation': 'requests', 'session': turn.session, 'execution_id': turn.execution_id})['requests'][0]
        turn.operate({'operation': 'reply', 'session': turn.session, 'execution_id': turn.execution_id,
                      'request_token': pending['request_token'], 'response': {'cancelled': True}})
        assert future.result(timeout=5)['outcome'] == 'completed'
    with ExitStack() as stack:
        error, _, _ = execution(tmp_path, pi_environment, 'research@x2', 'provider-error', stack)
        with pytest.raises(RuntimeAdapterError, match='provider rejected'):
            error.run()


def test_pi_child_cli_preserves_real_caller(tmp_path: Path, pi_environment: dict) -> None:
    """A real child process uses the hosted CLI from its Worktree and cannot forge a sibling identity."""
    result_project(tmp_path)
    with ExitStack() as stack:
        turn, _, _ = execution(tmp_path, pi_environment, 'research@x1', 'cli', stack)
        result = turn.run()
    assert 'authority-denied' in result['last_agent_message']
    receipt = json.loads(result['last_agent_message'])
    assert receipt['authorized_exit'] == 0, receipt
    assert receipt['refused_exit'] == 1
    assert yaml.safe_load(receipt['refused'])['error']['code'] == 'authority-denied'
