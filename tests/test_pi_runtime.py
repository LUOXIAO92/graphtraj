"""Pi's public Runtime contract with controlled native pipes and hosted CLI."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import threading
import time

import pytest
import yaml

from agent_swarm.models import pi_destination
from agent_swarm.pi import PiExecution
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
                   'if os.environ.get("PI_FIXTURE_POLICY"): json.dump(policy,open(os.environ["PI_FIXTURE_POLICY"],"w"))\n'
                   # As srt 0.0.49: the command words joined with spaces, parsed by an inner shell.
                   'command=" ".join(sys.argv[sys.argv.index("--")+1:])\n'
                   'if os.environ.get("PI_FIXTURE_SRT"): json.dump([sys.argv,command],open(os.environ["PI_FIXTURE_SRT"],"w"))\n'
                   'os.execv("/bin/bash",["bash","-c",command])\n')
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
    native_directory: Path | None = None,
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
        native = (native_directory or trace.with_suffix('.pi')) / 'session.jsonl'
        if not expected:
            assert len(native.read_text().splitlines()) == 1
        mapping = yaml.safe_load((directory / 'mapping.yml').read_text())
        mapping.update(runtime='pi', session=session, worker_pid=os.getpid(), runtime_pid=pid, trace_file=str(trace))
        (directory / 'mapping.yml').write_text(yaml.safe_dump(mapping))

    def started(session: str, pid: int) -> None:
        """Signal a bound execution with a ready control channel."""
        ready.set()

    stack.enter_context(hold_ownership(directory, os.getpid()))
    request = prepared.launch_document()['adapter_request']
    if native_directory is not None:
        request['native_directory'] = str(native_directory)
    turn = adapter.managed_execution(request, prompt, directory,
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


# Each would run or split a command if it reached the inner shell unquoted.
SHELL_TEXT = "a b;$(touch canary)`touch canary`'q"
FAKE_KEY = 'fake key;$(touch canary)`touch canary`\'q"!'


def launcher(tmp_path: Path, pi_environment: dict, monkeypatch: pytest.MonkeyPatch, **fields) -> tuple[list[str], dict, dict]:
    """Prepare a real launch of the Pi fixture; return its command, environment and request."""
    worktree = tmp_path / 'worktree'
    worktree.mkdir(exist_ok=True)
    monkeypatch.setenv('PI_FIXTURE_ARGV', str(tmp_path / 'pi-argv.json'))
    monkeypatch.setenv('PI_FIXTURE_SRT', str(tmp_path / 'srt-call.json'))
    request = {'executable': shutil.which('pi'), 'provider': 'deepseek', 'model': 'deepseek-flash',
               'worktree_path': str(worktree), 'agent_dir': pi_environment['agent_dir'], 'instructions': 'Be brief.',
               'sandbox_python': pi_environment['sandbox_python'], 'sandbox_path': pi_environment['sandbox_path'],
               'worktree_access': 'read', 'provider_domain': 'api.deepseek.com',
               'native_directory': str(tmp_path / 'native'), **fields}
    directory = tmp_path / 'data/native/one'
    directory.mkdir(parents=True)
    turn = PiExecution(request, 'unused', directory, lambda *a: None, lambda *a: None, tmp_path / 'trace.jsonl', None)
    argv, env = turn.prepare_launch(None)
    return argv, env, request


def ask_state(argv: list[str], env: dict, request: dict) -> subprocess.CompletedProcess:
    """Run the launcher to one native reply and its exit at end of input."""
    return subprocess.run(argv, input=json.dumps({'id': 'state', 'type': 'get_state'}) + '\n', text=True,
                          capture_output=True, cwd=request['worktree_path'], env=env, timeout=30)


@pytest.mark.parametrize('route', [{}, {'provider': 'custom', 'base_url': 'http://localhost:8080/v1',
                                        'provider_api': 'openai-completions'}], ids=['key-only', 'base-url'])
def test_a_key_reaches_no_command_line_and_no_file(
    tmp_path: Path, pi_environment: dict, monkeypatch: pytest.MonkeyPatch, route: dict,
) -> None:
    """Pi gets the key's name in a private auth.json and its value only by environment."""
    monkeypatch.setenv('FAKE_412_KEY', FAKE_KEY)
    argv, env, request = launcher(tmp_path, pi_environment, monkeypatch, api_key_env='FAKE_412_KEY', **route)
    completed = ask_state(argv, env, request)
    srt_argv, command = json.loads((tmp_path / 'srt-call.json').read_text())
    assert FAKE_KEY not in srt_argv and FAKE_KEY not in command
    assert not list(tmp_path.rglob('canary'))
    assert completed.returncode == 0, completed.stderr
    assert '--api-key' not in command
    assert FAKE_KEY not in json.loads((tmp_path / 'pi-argv.json').read_text())
    assert env['FAKE_412_KEY'] == FAKE_KEY
    native = Path(request['native_directory'])
    for root in (tmp_path / 'data', native):
        for path in root.rglob('*'):
            if path.is_file():
                assert FAKE_KEY.encode() not in path.read_bytes(), path
    auth = native / 'agent/auth.json'
    assert not auth.is_symlink() and stat.S_IMODE(auth.stat().st_mode) == 0o600
    assert json.loads(auth.read_text()) == {request['provider']: {'type': 'api_key', 'key': '$FAKE_412_KEY'}}


def test_shell_text_in_paths_reaches_pi_intact(
    tmp_path: Path, pi_environment: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The inner shell parses srt's joined command back into Pi's exact arguments and runs nothing else."""
    place = tmp_path / SHELL_TEXT
    place.mkdir()
    executable = place / 'pi'
    executable.write_text(Path(shutil.which('pi')).read_text())
    executable.chmod(0o755)
    (place / 'work tree').mkdir()
    argv, env, request = launcher(tmp_path, pi_environment, monkeypatch, executable=str(executable),
                                  worktree_path=str(place / 'work tree'), native_directory=str(place / 'native'))
    completed = ask_state(argv, env, request)
    assert not list(tmp_path.rglob('canary'))
    assert completed.returncode == 0, completed.stderr
    received = json.loads((tmp_path / 'pi-argv.json').read_text())
    session = str(place / 'native/session.jsonl')
    assert received[1:] == json.loads((tmp_path / 'data/native/one/pi-process.json').read_text())['argv'][1:]
    assert received[received.index('--session') + 1] == session
    assert received[received.index('--append-system-prompt') + 1] == str(place / 'native/role-instructions.txt')
    state = next(event for event in map(json.loads, completed.stdout.splitlines()) if event.get('id') == 'state')
    assert state['data']['sessionFile'] == session


def test_srt_gone_before_launch_is_refused(
    tmp_path: Path, pi_environment: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wrapper that returns its input unchanged never starts Pi unsandboxed."""
    sandbox = tmp_path / 'agent_sandbox/__init__.py'
    sandbox.write_text(sandbox.read_text().replace('return ["srt", "--settings", profile, "--", *cmd]', 'return cmd'))
    argv, env, request = launcher(tmp_path, pi_environment, monkeypatch)
    completed = ask_state(argv, env, request)
    assert completed.returncode != 0
    assert 'srt disappeared' in completed.stderr
    assert not (tmp_path / 'pi-argv.json').exists()


def test_destination_query_keeps_the_key_off_its_command_line_and_home_unwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A key-only model is listed from a private agent directory that holds only what the catalog reads."""
    monkeypatch.setenv('FAKE_412_KEY', FAKE_KEY)
    home = tmp_path / 'home'
    home.mkdir()
    native = {'models.json': '{"providers": {}}', 'models-store.json': '{"stored": true}',
              'auth.json': '{"p": {"type": "api_key", "key": "stored-key"}}',
              'settings.json': '{"packages": ["npm:must-not-install"]}'}
    for name, content in native.items():
        (home / name).write_text(content)
    log = tmp_path / 'query.json'
    peer = tmp_path / 'pi'
    # Pi refreshes models-store.json in place; a query must not reach the Home's file through that.
    peer.write_text(f"""#!{sys.executable}
import json, os, sys
agent = os.environ['PI_CODING_AGENT_DIR']
entries = {{name: os.readlink(os.path.join(agent, name)) if os.path.islink(os.path.join(agent, name)) else None
           for name in os.listdir(agent)}}
auth = json.load(open(os.path.join(agent, 'auth.json')))
json.dump({{'argv': sys.argv, 'agent': agent, 'entries': entries, 'auth': auth}}, open({str(log)!r}, 'w'))
open(os.path.join(agent, 'models-store.json'), 'w').write('{{"refreshed": true}}')
request = json.loads(sys.stdin.readline())
models = [{{'provider': 'p', 'id': 'm', 'baseUrl': 'https://keyed.example/v1'}}]
print(json.dumps({{'id': request['id'], 'success': True, 'data': {{'models': models}}}}))
""")
    peer.chmod(0o755)
    assert pi_destination(str(peer), str(home), 'p', 'm', 'FAKE_412_KEY') == 'keyed.example'
    query = json.loads(log.read_text())
    assert FAKE_KEY not in query['argv'] and '--api-key' not in query['argv']
    assert query['agent'] != str(home) and not Path(query['agent']).exists()
    assert query['auth'] == {'p': {'type': 'api_key', 'key': '$FAKE_412_KEY'}}
    assert query['entries'] == {'auth.json': None, 'models-store.json': None,
                                'models.json': str((home / 'models.json').resolve())}
    assert {path.name: path.read_text() for path in home.iterdir()} == native


def test_a_keyless_destination_query_runs_on_a_private_directory_with_the_native_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pi's stores, lock and packages land beside a link to the login; the Home is unchanged."""
    monkeypatch.delenv('PI_CODING_AGENT_DIR', raising=False)
    home = tmp_path / 'home'
    home.mkdir()
    for name, content in (('models.json', '{"providers": {}}'), ('models-store.json', '{"stored": true}'),
                          ('auth.json', '{"p": {"type": "api_key", "key": "stored-key"}}'),
                          ('settings.json', '{"packages": ["npm:must-not-install"]}')):
        (home / name).write_text(content)
    state = {path.name: (path.stat().st_size, path.stat().st_mtime_ns) for path in home.iterdir()}
    log = tmp_path / 'query.json'
    peer = tmp_path / 'pi'
    peer.write_text(f"""#!{sys.executable}
import json, os, sys
agent = os.environ['PI_CODING_AGENT_DIR']
entries = {{name: os.readlink(os.path.join(agent, name)) if os.path.islink(os.path.join(agent, name)) else None
           for name in os.listdir(agent)}}
json.dump({{'agent': agent, 'entries': entries, 'auth': json.load(open(os.path.join(agent, 'auth.json')))}}, open({str(log)!r}, 'w'))
for name in ('models-store.json', 'auth.json.lock', 'npm'):
    open(os.path.join(agent, name), 'w').close()
request = json.loads(sys.stdin.readline())
models = [{{'provider': 'p', 'id': 'm', 'baseUrl': 'https://native.invalid/v1'}}]
print(json.dumps({{'id': request['id'], 'success': True, 'data': {{'models': models}}}}))
""")
    peer.chmod(0o755)
    assert pi_destination(str(peer), str(home), 'p', 'm') == 'native.invalid'
    query = json.loads(log.read_text())
    assert query['agent'] != str(home) and not Path(query['agent']).exists()
    assert query['auth'] == {'p': {'type': 'api_key', 'key': 'stored-key'}}
    assert query['entries'] == {'auth.json': str((home / 'auth.json').resolve()), 'models-store.json': None,
                                'models.json': str((home / 'models.json').resolve())}
    assert {path.name: (path.stat().st_size, path.stat().st_mtime_ns) for path in home.iterdir()} == state


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


@pytest.mark.parametrize('field', ['allow_mach_lookup', 'allow_mach_register'])
@pytest.mark.parametrize('services', [None, '', 'com.apple.windowserver.active', True,
                                    [None], [''], ['*'], ['com.*.service'], ['service**'], ['service?'],
                                    ['service[1]'], ['service name'], ['service\nname']])
def test_pi_rejects_invalid_mach_services(tmp_path: Path, field: str, services: object) -> None:
    """Reject invalid lists and unrestricted/pattern grants before native preflight."""
    result_project(tmp_path)
    with pytest.raises(RuntimeAdapterError, match='exact Mach service names'):
        context(tmp_path, {field: services})


@pytest.mark.parametrize('value', [None, 0, 1, 'true', [], {}])
def test_pi_rejects_invalid_local_binding(tmp_path: Path, value: object) -> None:
    """Only an explicit boolean can opt into native local binding."""
    result_project(tmp_path)
    with pytest.raises(RuntimeAdapterError, match='must be a boolean'):
        context(tmp_path, {'allow_local_binding': value})


@pytest.mark.parametrize('value', [None, True, '/tmp/owned', [None], [''], ['relative'],
                                 ['/'], ['/tmp/../'], ['/tmp/*'], ['/tmp/socket?'],
                                 ['/tmp/[socket]'], ['/tmp/socket\x00']])
def test_pi_rejects_invalid_unix_sockets(tmp_path: Path, value: object) -> None:
    """Keep socket capabilities explicit, absolute and free of global/pattern grants."""
    result_project(tmp_path)
    with pytest.raises(RuntimeAdapterError, match='absolute non-root paths'):
        context(tmp_path, {'allow_unix_sockets': value})


def test_pi_mach_services_preserve_native_file_policy(
    tmp_path: Path, pi_environment: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Observe optional service grants at the native wrapper with unchanged file rules."""
    result_project(tmp_path)
    captured = tmp_path / 'native-policy.json'
    monkeypatch.setenv('PI_FIXTURE_POLICY', str(captured))
    services = ['com.apple.windowserver.active', 'com.apple.pasteboard.1',
                'com.apple.distributed_notifications@Uv3',
                'com.github.Electron.MachPortRendezvousServer.*']
    registrations = ['com.example.exact', 'com.github.Electron.MachPortRendezvousServer.*']
    sockets = ['/private/tmp/claude/262-native-boundary', '/tmp/owned socket/']
    policies = []
    session = None
    cases = [
        ({}, {}),
        ({'allow_mach_lookup': [], 'allow_mach_register': [], 'allow_local_binding': False,
          'allow_unix_sockets': []}, {}),
        ({'allow_mach_lookup': services}, {'allowMachLookup': services}),
        ({'allow_mach_register': registrations}, {'allowMachRegister': registrations}),
        ({'allow_local_binding': True}, {'allowLocalBinding': True}),
        ({'allow_unix_sockets': sockets}, {'allowUnixSockets': sockets}),
        ({'allow_mach_lookup': services, 'allow_mach_register': registrations, 'allow_local_binding': True},
         {'allowMachLookup': services, 'allowMachRegister': registrations, 'allowLocalBinding': True}),
    ]
    for extra, expected in cases:
        with ExitStack() as stack:
            turn, _, _ = execution(tmp_path, {**pi_environment, **extra}, 'research@x1',
                                   'policy', stack, session)
            result = turn.run()
            assert result['outcome'] == 'completed'
            session = result['session_id']
        policy = json.loads(captured.read_text())
        # Each real hosted CLI connection has a fresh owned address; only that
        # address may vary between otherwise identical native file policies.
        for paths in policy['filesystem'].values():
            paths[:] = ['<owned-cli>' if str(tmp_path / '.graphtraj/cli') in p else p
                        for p in paths]
        policies.append(policy)
        assert policy['network'] == {
            'allowedDomains': ['api.deepseek.com', 'openrouter.ai'], 'deniedDomains': [], **expected,
        }
    assert policies[0] == policies[1]
    assert policies[0]['network'] == {
        'allowedDomains': ['api.deepseek.com', 'openrouter.ai'], 'deniedDomains': [],
    }
    assert all(policy['filesystem'] == policies[0]['filesystem'] for policy in policies)


def test_pi_private_stderr_is_not_inherited(tmp_path: Path, pi_environment: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Native stdio metadata access must not require reading a private Runner file."""
    result_project(tmp_path)
    monkeypatch.setenv('PI_FIXTURE_PIPE_STDERR', '1')
    with ExitStack() as stack:
        turn, _, _ = execution(tmp_path, pi_environment, 'research@x1', 'pipe-stderr', stack)
        assert turn.run()['outcome'] == 'completed'


@pytest.mark.parametrize('relocate', [False, True])
def test_pi_continuation_and_native_trace(tmp_path: Path, pi_environment: dict, relocate: bool) -> None:
    """Same native Session and original context survive a new Worker invocation."""
    result_project(tmp_path)
    with ExitStack() as stack:
        turn, _, trace = execution(tmp_path, pi_environment, 'research@x1', 'remember-247', stack)
        first = turn.run()
    assert first['outcome'] == 'completed'
    assert 'remember-247' in first['last_agent_message']
    assert json.loads(trace.read_text().splitlines()[0])['id'] == first['session_id']
    native_directory = None
    if relocate:
        native_directory = tmp_path / '.graphtraj/swarm/native/retained-pi'
        native_directory.parent.mkdir(parents=True)
        trace.with_suffix('.pi').rename(native_directory)
    with ExitStack() as stack:
        resumed, _, _ = execution(tmp_path, pi_environment, 'research@x1', 'continue', stack,
                                  first['session_id'], native_directory=native_directory)
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


def test_pi_dialog_notice_is_retried_while_the_dialog_is_pending(
    tmp_path: Path, pi_environment: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A parent still closing its turn receives the dialog notice on retry."""
    result_project(tmp_path)
    receipts = iter([{'delivery': 'not-delivered'}, {'delivery': 'not-delivered'}])
    attempts = []
    monkeypatch.setattr('graphtraj.execution.runner_control.notify_direct_parent',
                        lambda *args: attempts.append(args) or next(receipts, {'delivery': 'received'}))
    with ExitStack() as stack, ThreadPoolExecutor(max_workers=1) as pool:
        turn, ready, _ = execution(tmp_path, pi_environment, 'research@x1', 'dialog', stack)
        future = pool.submit(turn.run)
        wait_started(turn, ready)
        deadline = time.monotonic() + 10
        while len(attempts) < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(attempts) == 3 and not future.done()
        pending = turn.operate({'operation': 'requests', 'session': turn.session, 'execution_id': turn.execution_id})['requests'][0]
        turn.operate({'operation': 'reply', 'session': turn.session, 'execution_id': turn.execution_id,
                      'request_token': pending['request_token'], 'response': {'cancelled': True}})
        assert future.result(timeout=5)['outcome'] == 'completed'
    assert len(attempts) == 3


def test_pi_child_cli_preserves_real_caller(tmp_path: Path, pi_environment: dict) -> None:
    """A real child process uses the hosted CLI from its Worktree and cannot forge a sibling identity.

    The forged alias is ignored: the report is written as the child itself.
    Reading the sibling's project reports is ordinary project read access.
    """
    result_project(tmp_path)
    with ExitStack() as stack:
        turn, _, _ = execution(tmp_path, pi_environment, 'research@x1', 'cli', stack)
        result = turn.run()
    receipt = json.loads(result['last_agent_message'])
    assert receipt['authorized_exit'] == 0, receipt
    assert yaml.safe_load(receipt['authorized'])['alias'] == 'research@x1'
    assert receipt['refused_exit'] == 0, receipt


@pytest.mark.parametrize('protected', ['.graphtraj', '.codex'])
def test_pi_standalone_root_worktree_refuses_unexpressible_read_denial(
    tmp_path: Path, pi_environment: dict, monkeypatch: pytest.MonkeyPatch, protected: str,
) -> None:
    """A project-root worktree cannot re-allow a path its host denies to the child."""
    from agent_swarm import AgentControl, Caller, bind
    from agent_swarm.pi import PiDriver

    project = tmp_path / 'standalone'
    (project / 'docs').mkdir(parents=True)
    request = {'executable': shutil.which('pi'), 'provider': 'deepseek', 'model': 'deepseek-flash',
               'worktree_path': str(project), 'agent_dir': pi_environment['agent_dir'], 'instructions': '',
               'sandbox_python': pi_environment['sandbox_python'], 'sandbox_path': pi_environment['sandbox_path'],
               'worktree_access': 'read', 'deny_read': [str(project / '.graphtraj'), str(project / '.codex')]}
    captured = tmp_path / 'native-policy.json'
    monkeypatch.setenv('PI_FIXTURE_POLICY', str(captured))
    call = bind(AgentControl(tmp_path / 'data', {'pi': PiDriver(request)}), Caller('standalone-host', None))

    (project / protected).mkdir()
    (project / protected / 'canary.txt').write_text('canary')
    refused = call({'action': 'create', 'runtime': 'pi', 'instruction': 'policy'})
    error = refused.document['result']['last_result']['error']
    assert refused.failed and error['code'] == 'ROLE_CONFIG_UNSUPPORTED', refused.document
    assert str((project / protected).resolve()) in error['message']
    assert not captured.exists()

    # Absent protected state has nothing to expose; the denial stays declared.
    shutil.rmtree(project / protected)
    created = call({'action': 'create', 'runtime': 'pi', 'instruction': 'policy'})
    assert not created.failed, created.document
    done = call({'action': 'wait', 'agent': created.document['agent'], 'timeout_seconds': 10})
    assert not done.failed and done.document['result']['state'] != 'active', done.document
    filesystem = json.loads(captured.read_text())['filesystem']
    assert str(project / protected) in filesystem['denyRead']
    assert str(project.resolve()) in filesystem['allowRead']


def test_pi_failure_stays_ahead_of_an_archive_failure(tmp_path: Path, pi_environment: dict) -> None:
    """A collector that cannot close does not replace why the execution failed."""
    class BrokenCollector:
        """Collect nothing and fail on the final close."""

        def receive(self, event: dict) -> None:
            """Take no record; only closing fails here."""

        def sync(self, *args: object, **kwargs: object) -> None:
            """Nothing to reconcile."""

        def close(self) -> None:
            """Fail while closing up."""
            raise ValueError('archive broke')

    result_project(tmp_path)
    with ExitStack() as stack:
        turn, _, _ = execution(tmp_path, pi_environment, 'research@x1', 'provider-error', stack)
        turn.archive_collector = lambda header, native: BrokenCollector()
        with pytest.raises(RuntimeAdapterError, match='provider rejected') as caught:
            turn.run()
    assert caught.value.code == 'RUNTIME_PROVIDER_FAILED'
    assert 'archive broke' in (tmp_path / '.graphtraj/runner/sessions/research@x1/stderr.log').read_text()
