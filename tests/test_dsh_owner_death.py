"""A DSH service whose owner dies still stops, and the log says what happened (436).

Everything here runs a real ``DshService`` on a stub ``dsh`` executable. The stub
starts in its own process group, starts a child holding a pipe on stdin the way
``dsh web`` holds ``agent_swarm.mcp``, and sleeps without printing a URL, so
``start`` is waiting on a real process tree and needs no port. No network, model
or real DSH.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import http.cookiejar
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import textwrap
import time
import urllib.request

import pytest

from agent_swarm.dsh.errors import DshError
from agent_swarm.dsh.service import DshService
from test_claude_codex_host_shutdown import RECORDED, SESSION, SOURCE, locate, tool_call

# The three signal steps of 5 seconds each, and room for a loaded machine.
STOP_BOUND = 25.0
RECOGNISABLE_CHILD = 'agent_swarm_mcp_stand_in'
STOPPED = 'stopped the DSH process group'
COULD_NOT_STOP = 'could not stop the DSH process group'
WATCHER_LINE = 'DSH watcher'

STUB = r'''
import os, signal, subprocess, sys, time

for name in filter(None, os.environ.get('STUB_IGNORES', '').split(',')):
    signal.signal(getattr(signal, name), signal.SIG_IGN)
if os.environ.get('STUB_EXIT'):
    raise SystemExit(int(os.environ['STUB_EXIT']))

pids = [os.getpid()]
if os.environ.get('STUB_CHILD'):
    pids.append(subprocess.Popen([os.environ['STUB_CHILD']], stdin=subprocess.PIPE).pid)

temporary = os.environ['STUB_PIDS'] + '.tmp'
with open(temporary, 'w') as stream:
    stream.write(' '.join(map(str, pids)))
os.replace(temporary, os.environ['STUB_PIDS'])
if os.environ.get('STUB_URL'):
    print(os.environ['STUB_URL'], flush=True)
time.sleep(600)
'''

# Stays until the pipe closes, as agent_swarm.mcp does: mcp.py reads stdin to its end.
CHILD = 'import sys\nsys.stdin.read()\n'

# The smallest process that owns a service.
OWNER = r'''
import json, os, sys
from pathlib import Path
from agent_swarm.dsh.service import DshService

service = DshService(sys.argv[1], Path.cwd(), json.loads(os.environ['TEST_DSH_ENVIRONMENT']))
service.start()
'''

# A real agents Claude host, as in test_claude_codex_host_shutdown.py. Only the
# driver is fake, and it owns a real service. TEST_STOP says what its stop does.
HOST = r'''
import importlib, json, os, sys, threading, time
from pathlib import Path

from agent_swarm.dsh.errors import DshError
from agent_swarm.dsh.service import DshService

where = Path(os.environ['TEST_WHERE'])


class Driver:
    """Owns one real service per execution."""

    def __init__(self):
        self.stops = {}

    def prepare(self, runtime, caller, **options):
        return {'runtime': runtime}

    def require_available(self, connection):
        pass

    def start(self, run):
        run.events.session('native-' + run.agent[-6:])
        options = {'profile_patch': Path(os.environ['TEST_PATCH'])} if os.environ.get('TEST_PATCH') else {}
        service = DshService(os.environ['TEST_DSH'], Path.cwd(), json.loads(os.environ['TEST_DSH_ENVIRONMENT']), **options)

        def launch():
            try:
                service.start()
            except DshError:
                pass  # The stub never authenticates; closing it ends this wait.

        threading.Thread(target=launch, daemon=True).start()
        while service.process is None:
            time.sleep(0.01)
        run.events.process(runtime_pid=service.process.pid)
        stop = self.stops[run.agent] = threading.Event()
        (where / 'started').touch()

        def own():
            stop.wait()
            service.close()
            run.events.finished('interrupted', last_message='stopped')

        threading.Thread(target=own, daemon=True).start()

    def interrupt(self, run):
        (where / 'interrupted').touch()
        if os.environ['TEST_STOP'] == 'finishes':
            self.stops[run.agent].set()
        return True

    def requests(self, run):
        return []

    def reply(self, run, request, response):
        return {}


host = importlib.import_module('agent_swarm.claude.host')
host.native_parent = lambda *_, **__: os.getppid()
host.runtime_drivers = lambda *_: {'claude': Driver()}
real_calls, made = host.IndependentCalls, []
host.IndependentCalls = lambda *arguments: made.append(real_calls(*arguments)) or made[-1]
real_serve = host.serve_concurrent


def serve(*arguments):
    """The Main's association comes from the native mod; everything after it is real."""
    call = made[0].make_call(os.environ['TEST_SESSION'], Path.cwd())
    made[0].call = lambda request: call('agents', request)
    real_serve(*arguments)


host.serve_concurrent = serve
sys.argv = ['host', 'serve', '--config', str(where / 'config.json')]
host.main()
'''


def script(path: Path, body: str) -> str:
    """Write an executable Python script and return its path."""
    path.write_text(f'#!{sys.executable}\n{textwrap.dedent(body)}')
    path.chmod(0o755)
    return str(path)


def stub_environment(tmp_path: Path, *, child: bool = True, **stub: str) -> dict[str, str]:
    """Return the environment a service gives the stub; ``stub`` adds its ``STUB_`` settings."""
    environment = {'PATH': '/usr/bin:/bin', 'STUB_PIDS': str(tmp_path / 'stub-pids')}
    if child:
        environment['STUB_CHILD'] = script(tmp_path / RECOGNISABLE_CHILD, CHILD)
    return {**environment, **{f'STUB_{name}': value for name, value in stub.items()}}


def group_gone(group: int) -> bool:
    """Whether no process of ``group`` remains.

    A zombie still counts: on darwin a group holding only zombies answers EPERM.
    """
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def wait_until(check: Callable[[], object], seconds: float, what: str) -> None:
    """Poll until ``check()`` is true, failing the test with ``what`` otherwise."""
    deadline = time.monotonic() + seconds
    while not check():
        assert time.monotonic() < deadline, f'{what}: not within {seconds} seconds'
        time.sleep(0.02)


def stub_pids(path: Path) -> list[int]:
    """Wait for the stub's process tree and return its pids, the group leader first."""
    wait_until(path.exists, 15.0, 'the stub did not start')
    return [int(pid) for pid in path.read_text().split()]


@contextmanager
def group_cleaned(path: Path) -> Iterator[None]:
    """Leave no stub behind, whatever the test did."""
    try:
        yield
    finally:
        if path.exists():
            group = int(path.read_text().split()[0])
            try:
                os.killpg(group, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


def start_owner(tmp_path: Path, environment: dict[str, str]) -> tuple[subprocess.Popen, Path]:
    """Start the smallest owner of a service; return it and the file taking its stderr."""
    log = tmp_path / 'owner-stderr.log'
    with log.open('ab') as stderr:
        owner = subprocess.Popen(
            [sys.executable, script(tmp_path / 'owner.py', OWNER), script(tmp_path / 'dsh', STUB)],
            cwd=tmp_path, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=stderr, start_new_session=True,
            env={'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path), 'PYTHONPATH': str(SOURCE),
                 'TEST_DSH_ENVIRONMENT': json.dumps(environment)},
        )
    return owner, log


def start_host(tmp_path: Path, stop: str, patch: Path | None, environment: dict[str, str]) -> tuple[subprocess.Popen, Path, Path]:
    """Start a real agents Claude host and create one child; return it, its log and its directory."""
    project, where, log = locate('agents-claude', tmp_path)
    variables = {'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path), 'PYTHONPATH': str(SOURCE), 'TEST_WHERE': str(where),
                 'TEST_SESSION': SESSION, 'TEST_STOP': stop, 'TEST_DSH': script(tmp_path / 'dsh', STUB),
                 'TEST_DSH_ENVIRONMENT': json.dumps(environment), **({'TEST_PATCH': str(patch)} if patch else {})}
    host = subprocess.Popen(
        [sys.executable, script(tmp_path / 'run-host.py', HOST)], cwd=project, env=variables, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, start_new_session=True,
        preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL),
    )
    messages = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
                tool_call(10, 'create', runtime='claude', instruction='work')]
    host.stdin.write(''.join(json.dumps(message) + '\n' for message in messages))
    host.stdin.flush()
    wait_until(lambda: (where / 'started').exists() or host.poll() is not None, 15.0, 'the host did not start the child')
    assert host.poll() is None, log.read_text()
    return host, log, where


@pytest.mark.parametrize('style', ['plain', 'reviewed'])
def test_a_host_killed_during_its_stop_leaves_no_dsh_process(tmp_path: Path, style: str) -> None:
    """What 392 step 83 saw: SIGINT, then a kill while the stop is unfinished. The group ends anyway.

    The service has no notion of review. What a reviewed child brings to the
    service is its launch: a profile patch and a held ``agent_swarm.mcp`` child.
    ``plain`` has neither, so the trigger needs neither.
    """
    reviewed    = style == 'reviewed'
    environment = stub_environment(tmp_path, child=reviewed)
    patch       = tmp_path / 'cordis.patch.yml' if reviewed else None
    with group_cleaned(tmp_path / 'stub-pids'):
        host, log, where = start_host(tmp_path, 'never', patch, environment)
        try:
            pids = stub_pids(tmp_path / 'stub-pids')
            assert len(pids) == (2 if reviewed else 1)
            host.send_signal(signal.SIGINT)
            wait_until((where / 'interrupted').exists, 15.0, 'the host did not begin its stop')
        finally:
            # The kill the test is about, and the clean-up if anything above failed.
            host.kill()
            host.wait(5)

        wait_until(lambda: group_gone(pids[0]), STOP_BOUND, 'the DSH process group outlived its host')
        wait_until(lambda: STOPPED in log.read_text(), 5.0, 'the log did not say the group stopped')

    text = log.read_text()
    assert 'agents host stopped: Claude Code ended the session (SIGINT).' in text
    assert 'recorded' not in text
    assert COULD_NOT_STOP not in text
    assert f'pid={pids[0]}' in text
    assert len([line for line in text.splitlines() if WATCHER_LINE in line]) == 2


def test_a_stub_that_ignores_sigint_and_sigterm_ends_through_escalation(tmp_path: Path) -> None:
    """The kill arrives through the last step, and the outcome line is still ``stopped``."""
    environment = stub_environment(tmp_path, IGNORES='SIGINT,SIGTERM')
    with group_cleaned(tmp_path / 'stub-pids'):
        owner, log = start_owner(tmp_path, environment)
        try:
            # The stub writes its pids after it has set the two signals to be ignored.
            pids = stub_pids(tmp_path / 'stub-pids')
        finally:
            owner.kill()
            owner.wait(5)
        began = time.monotonic()

        wait_until(lambda: group_gone(pids[0]), STOP_BOUND, 'the DSH process group outlived its owner')
        wait_until(lambda: STOPPED in log.read_text(), 5.0, 'the log did not say the group stopped')

    # Neither of the first two steps can have ended it, so both ran their full wait.
    assert time.monotonic() - began >= 9.0
    assert COULD_NOT_STOP not in log.read_text()


def test_a_group_that_will_not_stop_is_reported_as_not_stopped() -> None:
    """Every signal is sent and the group still answers: the outcome says so, and the exit is not 0.

    No process is unkillable on demand, so this runs the real script with its
    bounds shortened and ``killpg`` replaced. It signals nothing real.
    """
    probe = r'''
import importlib.util, json, os, sys
from pathlib import Path

specification = importlib.util.spec_from_file_location('watcher', sys.argv[1])
watcher = importlib.util.module_from_spec(specification)
specification.loader.exec_module(watcher)

sent = []
os.killpg = lambda pid, sig: sig and sent.append((pid, int(sig)))
watcher.STEP_SECONDS = 0.05
sys.argv = ['watcher', '4242424']
try:
    watcher.main()
finally:
    print(json.dumps(sent))
'''
    path   = SOURCE / 'agent_swarm' / 'dsh' / 'watcher.py'
    result = subprocess.run([sys.executable, '-I', '-S', '-c', probe, str(path)], stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, env={}, timeout=15)
    assert json.loads(result.stdout) == [[4242424, int(sig)] for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL)]
    assert result.returncode != 0
    assert COULD_NOT_STOP in result.stderr and 'pid=4242424' in result.stderr
    assert STOPPED not in result.stderr


def test_a_normal_host_stop_records_its_children_and_the_watcher_says_nothing(tmp_path: Path) -> None:
    """The stop finishes: the group is gone, the line is written, the exit is 0, and no watcher line appears."""
    environment = stub_environment(tmp_path)
    with group_cleaned(tmp_path / 'stub-pids'):
        host, log, _ = start_host(tmp_path, 'finishes', None, environment)
        try:
            pids = stub_pids(tmp_path / 'stub-pids')
            host.stdin.close()
            assert host.wait(20) == 0
        finally:
            host.kill()
            host.wait(5)

        wait_until(lambda: group_gone(pids[0]), 5.0, 'the group outlived a normal stop')
    text = log.read_text()
    assert RECORDED in text
    assert WATCHER_LINE not in text


@pytest.fixture
def launched(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let ``start`` authenticate without a port: the launch URL is answered here, with a cookie."""
    class Opener:
        """Answers the one launch request."""

        def __init__(self, jar: http.cookiejar.CookieJar) -> None:
            """Keep the jar the service will read."""
            self.jar = jar

        def open(self, url: str, timeout: float) -> io.BytesIO:
            """Set the login cookie the native service would."""
            self.jar.set_cookie(http.cookiejar.Cookie(
                0, 'session', 'test-value', None, False, '127.0.0.1', False, False,
                '/', False, False, None, False, None, None, {}))
            return io.BytesIO(b'ok')

    monkeypatch.setattr(urllib.request, 'build_opener', lambda proxy, cookies: Opener(cookies.cookiejar))


def started_service(tmp_path: Path, **stub: str) -> DshService:
    """Return a service whose start succeeded on the stub, with its group and watcher running."""
    environment = stub_environment(tmp_path, URL='http://127.0.0.1:1/?token=launch', **stub)
    service     = DshService(script(tmp_path / 'dsh', STUB), tmp_path, environment)
    service.start()
    stub_pids(tmp_path / 'stub-pids')
    return service


def test_a_normal_close_stops_the_group_and_reaps_the_watcher_silently(
    tmp_path: Path, launched: None, capfd: pytest.CaptureFixture[str],
) -> None:
    """The watcher is told to leave: exit 0, not killed, no zombie, and no line in the log."""
    with group_cleaned(tmp_path / 'stub-pids'):
        service = started_service(tmp_path)
        watcher = service.watcher
        group   = service.process.pid
        assert watcher.poll() is None and not group_gone(group)

        service.close()

        assert watcher.returncode == 0
        with pytest.raises(ProcessLookupError):
            os.kill(watcher.pid, 0)
        wait_until(lambda: group_gone(group), 5.0, 'the group outlived close')
        service.close()  # Closing twice is still safe.
    assert WATCHER_LINE not in capfd.readouterr().err


def test_the_watcher_is_given_no_inherited_environment(
    tmp_path: Path, launched: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No credential reaches it, however the host was started."""
    monkeypatch.setenv('TEST_API_KEY', 'never-give-me-to-the-watcher')
    calls      = []
    real_popen = subprocess.Popen

    def recording(arguments: list[str], **options: object) -> subprocess.Popen:
        """Note how each process is started, then start it."""
        calls.append((arguments, options))
        return real_popen(arguments, **options)

    monkeypatch.setattr(subprocess, 'Popen', recording)
    with group_cleaned(tmp_path / 'stub-pids'):
        service = started_service(tmp_path)
        service.close()

    watcher, options = next((arguments, options) for arguments, options in calls if arguments[0] == sys.executable)
    assert watcher[1:3] == ['-I', '-S'] and options['env'] == {} and options['start_new_session'] is True


def test_a_close_that_could_not_stop_the_group_keeps_the_watcher(tmp_path: Path, launched: None) -> None:
    """``RUNTIME_SHUTDOWN_FAILED`` does not tell it to leave, so the owner's death still stops the group."""
    with group_cleaned(tmp_path / 'stub-pids'):
        # Ignoring the first two signals keeps the stub alive until the last, so nothing else fails first.
        service = started_service(tmp_path, IGNORES='SIGINT,SIGTERM')
        watcher = service.watcher
        process = service.process
        real_poll, real_wait = process.poll, process.wait

        def never_ends(timeout: float | None = None) -> None:
            """Answer as a process that does not end."""
            raise subprocess.TimeoutExpired('dsh', timeout)

        process.poll, process.wait = lambda: None, never_ends
        with pytest.raises(DshError) as failure:
            service.close()
        assert failure.value.code == 'RUNTIME_SHUTDOWN_FAILED'

        process.poll, process.wait = real_poll, real_wait
        process.wait(5)
        assert watcher.poll() is None

        # The owner's death, as the watcher sees it: the pipe closes with nothing written.
        os.close(service.watcher_pipe)
        assert watcher.wait(5) == 0


def test_a_failed_start_leaves_no_watcher_after_the_close_every_caller_makes(
    tmp_path: Path, capfd: pytest.CaptureFixture[str],
) -> None:
    """DSH exits before authentication; the close that follows reaps the watcher with no line."""
    service = DshService(script(tmp_path / 'dsh', STUB), tmp_path, stub_environment(tmp_path, EXIT='7'))
    with pytest.raises(DshError):
        service.start()
    watcher = service.watcher

    service.close()

    assert service.process.poll() == 7
    assert watcher.returncode == 0
    with pytest.raises(ProcessLookupError):
        os.kill(watcher.pid, 0)
    assert WATCHER_LINE not in capfd.readouterr().err
