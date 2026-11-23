"""GraphTraj's own test helpers for the installed graftling (agents) package.

These helpers were taken unchanged from the graftling test modules once copied
here (Task 506); the graftling tests themselves run in the graftling repository.
Each section names the graftling test module it came from. Not collected by
pytest: this module defines no tests.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any
from uuid import uuid4

import pytest

import graftling
import graftling.control
from graftling import AgentControl, AgentsError, Caller
from graftling.claude.host import IndependentCalls
from graftling.dsh import execution
from graftling.dsh import host as dsh_host
from graftling.pi import host as pi_host
from dsh_standalone_peer import FakeDshService, install_dsh


SOURCE = Path(__file__).resolve().parents[1] / 'src'


# -- from graftling tests/test_agent_control.py --------------------------------

class ScriptedDriver:
    """In-process driver: each execution runs until released or interrupted.

    It counts executions per native Session so a test can prove that no two
    executions of one Session ever overlap.
    """

    def __init__(self, deliver_error: Exception | None = None) -> None:
        """Start with no executions; ``deliver_error`` makes delivery fail."""
        self.lock          = threading.Lock()
        self.releases      = {}
        self.inputs        = {}
        self.started       = []
        self.active        = {}
        self.max_active    = 0
        self.deliveries    = 0
        self.deliver_error = deliver_error
        self.replies       = []

    def prepare(self, runtime, caller):
        """Retain the continuation settings a caller would pass explicitly."""
        return {'cwd': '/explicit/cwd', 'runtime': runtime}

    def start(self, run):
        """Bind a Session at once, then work on a thread until released."""
        if hasattr(self, 'start_gate'):
            self.start_gate.wait(10)
        session = run.session or 'native-' + run.agent[-6:]
        release = threading.Event()
        with self.lock:
            self.releases[run.execution] = release
            self.inputs[run.execution]   = [run.message]
            self.started.append((run.agent, run.session, run.message, run.archive))
            self.active[session] = self.active.get(session, 0) + 1
            self.max_active      = max(self.max_active, self.active[session])
        run.events.session(session)
        run.events.process(runtime_pid=os.getpid())

        def work():
            """Finish with the inputs seen, as a Runtime result would."""
            release.wait(10)
            with self.lock:
                self.active[session] -= 1
                messages = '|'.join(self.inputs[run.execution])
            outcome = 'interrupted' if getattr(release, 'interrupted', False) else 'completed'
            run.events.finished(outcome, last_message=messages)

        threading.Thread(target=work, daemon=True).start()

    def deliver(self, run, message):
        """Add input to the running execution."""
        self.deliveries += 1
        if self.deliver_error is not None:
            raise self.deliver_error
        self.inputs[run.execution].append(message)

    def interrupt(self, run):
        """Stop the execution natively."""
        release = self.releases[run.execution]
        release.interrupted = True
        release.set()
        return True

    def requests(self, run):
        """Return one pending native approval."""
        return [{'request_token': 'token-1', 'method': 'native/approve', 'params': {'tool': 'Bash'}}]

    def reply(self, run, request, response):
        """Submit the reply; a second native submission would be a defect."""
        self.replies.append((request['request_token'], dict(response)))
        return {'reply_status': 'submitted'}

    def release(self, execution):
        """Let one execution complete normally."""
        self.releases[execution].set()


# -- from graftling tests/test_agents_connections_presets.py -------------------

CALLER = Caller('test-host', None, 'main-session', 'claude')

CONFIG = """\
save_normalized_sessions: false   # unchanged booleans
connections:
  work-claude:
    runtime: claude
    home: /native/claude
    base_url: https://proxy.example/v1
    api_key_env: WORK_CLAUDE_KEY
    models:
      - claude-opus-5-5
      - id: claude-sonnet-5-5
        supported_efforts: [low, high]
  local-codex:
    runtime: codex
presets:
  reviewer:
    connection: work-claude
    model: claude-sonnet-5-5
    reasoning_effort: high
  quick:
    runtime: codex
    model: gpt-5.5
"""


class RecordingDriver:
    """Finishes at once and keeps every ``prepare`` call's keyword arguments."""

    def __init__(self, unavailable: str | None = None) -> None:
        self.prepared: list[dict] = []
        self.checked: list[dict] = []
        self.unavailable = unavailable

    def prepare(self, runtime, caller, *, configuration=None, selection=None):
        self.prepared.append({'runtime': runtime, 'configuration': configuration, 'selection': selection})
        return {'runtime': runtime}

    def require_available(self, connection):
        self.checked.append(dict(connection))
        if self.unavailable:
            raise AgentsError('runtime-unavailable', self.unavailable)

    def start(self, run):
        run.events.session('native-' + run.agent[-6:])
        run.events.finished('completed', last_message='done')

    def deliver(self, run, message):
        raise AssertionError('not used')

    def interrupt(self, run):
        return False

    def requests(self, run):
        return []

    def reply(self, run, request, response):
        raise AssertionError('not used')


def configured(root: Path, text: str = CONFIG) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'config.yml').write_text(text, encoding='utf-8')
    return root


def create(control: AgentControl, **arguments) -> tuple[dict, bool]:
    result = graftling.bind(control, CALLER)({'action': 'create', 'instruction': 'Work.', **arguments})
    return result.document, result.failed


@pytest.fixture
def catalog(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Fake native discovery for connections without declared models."""
    seen: list[dict] = []

    def discover(connection):
        seen.append(dict(connection))
        if connection.get('models') is not None:
            return graftling.discover_models(connection)
        return {'runtime': connection['runtime'], 'status': 'available', 'message': 'fake catalog',
                'models': [{'id': 'gpt-5.5', 'alias': 'GPT-5.5', 'provider': 'openai',
                            'supported_efforts': ['low', 'medium', 'high']},
                           {'id': 'claude-opus-5-5', 'alias': 'Opus', 'provider': 'anthropic',
                            'supported_efforts': None}]}

    monkeypatch.setattr(graftling.control, '_discover_models', discover)
    return seen


# -- from graftling tests/test_claude_jsonl.py ---------------------------------

def message(uid: str, parent: str | None, text: str, *, role: str = 'user', **fields: object) -> dict:
    """Build a transcript entry, with intentionally backward native timestamps."""
    return {'type': role, 'uuid': uid, 'parentUuid': parent, 'sessionId': 's',
            'timestamp': '2026-01-01T00:00:00Z',
            'message': {'role': role, 'id': 'api-' + uid, 'model': 'native-model',
                        'content': [{'type': 'text', 'text': text}]}, **fields}


def write(path: Path, records: list[dict]) -> None:
    """Write a complete fixture transcript in the supplied native file order."""
    path.write_text(''.join(json.dumps(r) + '\n' for r in records))


# -- from graftling tests/test_claude_review.py --------------------------------

@pytest.fixture
def native(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Put the controlled peer where a Claude driver finds it."""
    binary = tmp_path / 'bin/claude'
    binary.parent.mkdir()
    binary.write_text(f'#!{sys.executable}\n' + Path(__file__).with_name('claude_cli_fixture.py').read_text())
    binary.chmod(0o755)
    monkeypatch.setenv('PATH', str(binary.parent) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('CLAUDE_FIXTURE_HOME', str(tmp_path))
    monkeypatch.setenv('PYTHONPATH', str(Path(__file__).resolve().parents[1] / 'src'))


# -- from graftling tests/test_codex_independent_control.py --------------------

@pytest.fixture
def native_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Configure the controlled peer without loading any GraphTraj role or Task."""
    peer = tmp_path / 'codex'
    peer.write_text('#!' + sys.executable + '\n' + Path(__file__).with_name('codex_stdio_peer.py').read_text())
    peer.chmod(0o755)
    monkeypatch.setenv('PYTHONPATH', str(Path(__file__).resolve().parents[1] / 'src'))
    monkeypatch.setenv('PEER_NATIVE_ROLLOUT', str(tmp_path / 'native'))
    return {'adapter_request': {
        'arguments': [str(peer)], 'worktree_path': str(tmp_path),
        'session_parameters': {'cwd': str(tmp_path), 'model': 'chosen-model',
            'developerInstructions': 'Retain native settings.',
            'config': {'default_permissions': 'chosen', 'permissions': {
                'chosen': {'extends': ':workspace', 'filesystem': {str(tmp_path): 'write'}},
            }}},
    }}


# -- from graftling tests/test_dsh_standalone_child.py -------------------------

DSH_KEY = 'never-shown-383-key'
DSH_CONFIG = """connections:
  work-dsh:
    runtime: dsh
    home: {home}
    api_key_env: DSH_383_KEY
    models:
      - id: deepseek-v5
        supported_efforts: [low, high]
"""


@pytest.fixture
def dsh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """A stand-in DSH 0.2.2-alpha.2 install, a key, no GRAPHTRAJ_* variable and the fake service."""
    for name in [name for name in os.environ if name.startswith('GRAPHTRAJ_')]:
        monkeypatch.delenv(name)
    monkeypatch.setenv('DSH_383_KEY', DSH_KEY)
    monkeypatch.setattr(execution.DshExecution, 'service_type', FakeDshService)
    FakeDshService.instances = []
    executable = install_dsh(tmp_path / 'dsh')
    return {'executable': str(executable), 'model': 'deepseek-flash', 'sandbox': 'workspace-write'}


def declare(root: Path, tmp_path: Path) -> Path:
    """Declare one DSH connection with its own home, key variable and models."""
    home = tmp_path / 'dsh-connection-home'
    home.mkdir()
    root.mkdir(parents=True, exist_ok=True)
    (root / 'config.yml').write_text(DSH_CONFIG.format(home=home))
    return home


def claude_main(host: IndependentCalls, cwd: Path):
    session = str(uuid4())
    call = host.make_call(session, cwd)

    def invoke(feature: str, **arguments) -> dict:
        """Call as the Main; ``invoke.shown`` keeps the notices its results carried."""
        result = call('subagents', {'action': 'execute', 'feature': feature, 'arguments': arguments})
        assert not result.failed, result.document
        invoke.shown.extend(result.document.get('main_notices', []))
        return result.document

    invoke.shown = []
    return invoke, call, session


def stop_owned(control) -> None:
    for owned in control.interrupt_owned():
        deadline = time.monotonic() + 10
        while control.owns_running(owned) and time.monotonic() < deadline:
            time.sleep(0.05)


# -- from graftling tests/test_pi_dsh_notice_holding.py ------------------------

class Pipe:
    """The extension or plugin side of a host's notice pipe."""

    def __init__(self, shown: bool | str | None = True) -> None:
        """``shown`` is the acknowledgement to send, or ``'queued'``; ``None`` sends none."""
        self.lines: list[dict] = []
        self.shown = shown
        self.notices = None
        self.on_write = None

    def write(self, text: str) -> None:
        """Record one notice line and acknowledge it the way the native side does."""
        document = json.loads(text)
        if 'notice' not in document:
            return
        self.lines.append(document['notice'])
        if self.on_write is not None:
            self.on_write(document['notice'])
        if self.shown == 'queued':
            threading.Thread(target=self.notices.queue, args=(document['notice']['id'],)).start()
        elif self.shown is not None:
            threading.Thread(target=self.notices.acknowledge, args=(document['notice']['id'], self.shown)).start()

    def flush(self) -> None:
        """Lines are recorded at once."""


class Process:
    """One host process's state, built by that host's own ``start``."""

    def __init__(
        self,
        kind: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        shown: bool | str | None,
        timeout: float,
        driver: Any,
    ) -> None:
        """Start the host for the fixed Session ``main`` on this test's data root."""
        self.kind = kind
        self.driver = driver
        self.pipe = Pipe(shown)
        self.host = {'pi': pi_host, 'dsh': dsh_host}[kind]
        monkeypatch.setattr(self.host, 'verify_native_parent', lambda *_: None)
        monkeypatch.setattr(self.host, 'runtime_drivers', lambda *_: {'claude': driver})
        (tmp_path / 'host.json').write_text(json.dumps({'root': str(tmp_path / 'data')}))
        monkeypatch.chdir(tmp_path)
        with monkeypatch.context() as started:
            # The host keeps sys.stdout as its pipe; pytest gets it back after start.
            started.setattr(sys, 'stdout', self.pipe)
            if kind == 'pi':
                started.setenv('GRAFTLING_PI_ENTRY', sys.executable)
                started.setattr(pi_host, 'pi_request', lambda *_: {})
                started.setattr(pi_host, 'current_connection', lambda: {
                    'runtime': 'pi', 'session': 'main', 'session_file': str(tmp_path / 's.jsonl')})
                header = {'type': 'session', 'version': 3, 'id': 'main', 'cwd': str(tmp_path)}
                started.setattr(sys, 'stdin', io.StringIO(json.dumps({'header': header, 'entries': []}) + '\n'))
                _, self.notices, self.call, self.inner, self.control, self.caller = pi_host.start(tmp_path / 'host.json')
            else:
                header = {'version': 4, 'id': 'main', 'cwd': str(tmp_path), 'isSeeded': False}
                _, _, self.notices, self.call, self.inner, self.control, self.caller = dsh_host.start(
                    tmp_path / 'host.json', {'header': header})
        self.notices.timeout = timeout
        self.pipe.notices = self.notices

    def flush(self, **options) -> list[dict]:
        """Run this process's flush to its end; return what it wrote."""
        if self.kind == 'dsh':
            options.setdefault('attempts', 1)
        self.notices.flush(self.control, self.caller, **options)
        return self.pipe.lines

    def create(self, instruction: str = 'work') -> str:
        """Create one Claude child through the model-facing entry; return its Agent."""
        result = self.call({'action': 'create', 'runtime': 'claude', 'instruction': instruction})
        assert not result.failed, result.document
        return result.document['agent']

    def last(self, agent: str) -> dict:
        """Read the Agent's last result once it has one."""
        return wait_until(lambda: self.call({'action': 'status', 'agent': agent}).document['result'].get('last_result'))

    def stop_children(self, call=None) -> list[str]:
        """The stop ``main`` runs, through ``call`` if given."""
        return self.host.stop_children(call or self.inner, lambda: self.control.visible_agents(self.caller))

    def shutdown(self) -> None:
        """What ``main`` does when the native side closes its pipe."""
        self.control.close_notices()
        self.notices.close()
        self.stop_children()


def wait_until(check, seconds: float = 5.0):
    """Poll ``check`` until it returns a truthy value."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError('condition not reached')


# -- from graftling tests/test_pi_standalone_host.py ---------------------------

def host_environment(tmp_path: Path, session: str = 'pi-main') -> dict:
    """The environment the extension gives the host, with this test as the Pi parent."""
    environment = {key: value for key, value in os.environ.items()
                   if key not in {'GRAFTLING_CONNECTION', 'DSH_SESSION_ID', 'DSH_AGENT_SOURCE'}}
    return {**environment, 'GRAFTLING_PI_ENTRY': sys.executable, 'GRAFTLING_PI_PROVIDER': 'anthropic',
            'GRAFTLING_PI_MODEL': 'parent-model', 'GRAFTLING_NATIVE_RUNTIME': 'pi',
            'GRAFTLING_NATIVE_SESSION': session, 'GRAFTLING_NATIVE_SESSION_FILE': str(tmp_path / 's.jsonl'),
            'PI_CODING_AGENT_DIR': str(tmp_path / 'pi-home'), 'PYTHONPATH': str(SOURCE)}


def run_host(tmp_path: Path, configuration: dict, close: bool = True) -> tuple[subprocess.Popen, str]:
    """Start the host as the extension does and return its first stdout line."""
    (tmp_path / 'host.json').write_text(json.dumps(configuration))
    process = subprocess.Popen([sys.executable, '-m', 'graftling.pi.host', '--config', str(tmp_path / 'host.json')],
                               cwd=tmp_path, env=host_environment(tmp_path), stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    header = {'type': 'session', 'version': 3, 'id': 'pi-main', 'cwd': str(tmp_path)}
    process.stdin.write(json.dumps({'header': header, 'entries': []}) + '\n')
    process.stdin.flush()
    first = process.stdout.readline()
    if close:
        process.stdin.close()
        process.wait(20)
    return process, first
