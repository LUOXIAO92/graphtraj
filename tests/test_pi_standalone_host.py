"""Pi as a Task-free agents host: configuration, Runtime routing and notices (382)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

import pytest

import agent_swarm
from agent_swarm import AgentControl, AgentsError, Caller, bind
from agent_swarm.pi import host
from agent_swarm.pi.driver import PiDriver


SOURCE = Path(__file__).resolve().parents[1] / 'src'
MAIN = Caller('pi-native', None, session='pi-main', runtime='pi')
PARENT = {'AGENT_SWARM_PI_ENTRY': '/opt/pi/cli.js', 'AGENT_SWARM_PI_PROVIDER': 'anthropic',
          'AGENT_SWARM_PI_MODEL': 'parent-model', 'PATH': '/usr/bin:/bin', 'PI_CODING_AGENT_DIR': '/pi/agent'}


@pytest.mark.parametrize(('document', 'message'), [
    ([], 'must be a JSON object'),
    ({'root': '/data', 'adapter_request': {}}, 'adapter_request is no longer accepted'),
    ({'root': '/data', 'roles': {}}, 'Unknown Pi host configuration keys'),
    ({'root': 'relative'}, 'absolute data root'),
    ({}, 'absolute data root'),
    ({'root': '/data', 'claude': 'opus'}, '"claude" must be an object'),
    ({'root': '/data', 'pi': {'worktree_path': '/elsewhere'}}, 'worktree_path is always the cwd'),
    ({'root': '/data', 'pi': {'harness_root': '/project'}}, 'Unknown or fixed Pi settings'),
    ({'root': '/data', 'pi': {'model': ''}}, 'non-empty string'),
    ({'root': '/data', 'pi': {'read_paths': ['docs']}}, 'absolute paths'),
    ({'root': '/data', 'pi': {'worktree_access': 'admin'}}, "'read' or 'write'"),
])
def test_configuration_refusals(document: object, message: str) -> None:
    """Anything but the documented Task-free form is refused with a reason."""
    with pytest.raises(ValueError, match=message):
        host.read_configuration(document)


def test_configuration_accepts_root_and_per_runtime_settings() -> None:
    """Every Runtime section is optional; Codex stays absent unless given."""
    root, settings = host.read_configuration({'root': '/data'})
    assert root == Path('/data')
    assert settings == {'pi': {}, 'claude': {}, 'dsh': {}, 'codex': None}
    _, settings = host.read_configuration({
        'root': '/data', 'pi': {'model': 'm', 'deny_read': ['/secret'], 'worktree_access': 'write'},
        'claude': {'model': 'claude-opus-5-5'}, 'codex': {'adapter_request': {}}, 'dsh': {'model': 'd'}})
    assert settings['pi']['deny_read'] == ['/secret'] and settings['codex'] == {'adapter_request': {}}


def test_default_request_comes_from_the_native_parent(tmp_path: Path) -> None:
    """The verified parent supplies defaults; no Task field, path or domain is added."""
    request = host.pi_request({}, tmp_path, PARENT)
    assert request == {
        'executable': '/opt/pi/cli.js', 'provider': 'anthropic', 'model': 'parent-model',
        'worktree_path': str(tmp_path.resolve()), 'agent_dir': '/pi/agent', 'instructions': '',
        'sandbox_python': sys.executable, 'sandbox_path': '/usr/bin:/bin', 'worktree_access': 'read'}
    home = {key: value for key, value in PARENT.items() if key != 'PI_CODING_AGENT_DIR'}
    assert host.pi_request({}, tmp_path, home)['agent_dir'] == str(Path.home() / '.pi/agent')
    chosen = host.pi_request({'model': 'other', 'provider_domain': 'api.example.com',
                              'deny_read': ['/secret']}, tmp_path, PARENT)
    assert (chosen['model'], chosen['provider_domain'], chosen['deny_read']) == (
        'other', 'api.example.com', ['/secret'])


def test_default_request_refusals_and_write_access(tmp_path: Path) -> None:
    """No entry or model is refused; write access resolves the Git common directory."""
    with pytest.raises(ValueError, match='agents Pi extension'):
        host.pi_request({}, tmp_path, {})
    with pytest.raises(ValueError, match='no selected model'):
        host.pi_request({}, tmp_path, {**PARENT, 'AGENT_SWARM_PI_MODEL': ''})
    with pytest.raises(ValueError, match='needs a Git worktree'):
        host.pi_request({'worktree_access': 'write'}, tmp_path, PARENT)
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    request = host.pi_request({'worktree_access': 'write'}, tmp_path, PARENT)
    assert Path(request['git_common_directory']) == (tmp_path / '.git').resolve()
    given = host.pi_request({'worktree_access': 'write', 'git_common_directory': '/repo/.git'}, tmp_path, PARENT)
    assert given['git_common_directory'] == '/repo/.git'


def test_child_model_is_not_bound_to_the_parent_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """create's model reaches the Pi child; the parent's model is only the default."""
    # A fake catalog stands in for Pi's native destination lookup.
    monkeypatch.setattr('agent_swarm.pi.driver.pi_destination', lambda *arguments: 'api.example.com')
    driver = PiDriver(host.pi_request({}, tmp_path, PARENT))
    assert driver.prepare('pi', MAIN)['adapter_request']['model'] == 'parent-model'
    chosen = driver.prepare('pi', MAIN, selection={'settings': None, 'model': 'child-model',
                                                   'reasoning_effort': 'high', 'provider': None})
    assert (chosen['adapter_request']['model'], chosen['adapter_request']['reasoning_effort']) == (
        'child-model', 'high')


class Fake:
    """Driver stand-in recording its constructor settings and prepare calls."""

    def __init__(self, runtime: str, *arguments: object) -> None:
        """Keep the public constructor's arguments."""
        self.runtime = runtime
        self.arguments = arguments
        self.prepared: list[dict | None] = []
        self.finish: tuple[str, str | None, dict | None] = ('completed', 'answer', None)

    def prepare(self, runtime, caller, *, selection=None):
        """Record the selection the core resolved for this create."""
        if runtime != self.runtime:
            raise AgentsError('unsupported-runtime', 'wrong driver')
        self.prepared.append(selection)
        return {'runtime': runtime}

    def require_available(self, connection) -> None:
        """Every declared connection is installed and logged in here."""

    def start(self, run) -> None:
        """Bind a Session and end at once with the scripted outcome."""
        run.events.session('native-' + run.agent[-6:])
        outcome, message, error = self.finish
        threading.Thread(target=run.events.finished, args=(outcome,),
                         kwargs={'last_message': message, 'error': error}).start()


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Replace the four public driver constructors inside the host."""
    made: dict = {}
    for runtime, name, module in (('pi', 'PiDriver', host), ('claude', 'ClaudeDriver', 'agent_swarm.claude.driver'),
                                  ('codex', 'CodexDriver', 'agent_swarm.codex.driver'),
                                  ('dsh', 'DshDriver', 'agent_swarm.dsh.driver')):
        def factory(*arguments, runtime=runtime):
            made[runtime] = Fake(runtime, *arguments)
            return made[runtime]
        if isinstance(module, str):
            monkeypatch.setattr(f'{module}.{name}', factory)
        else:
            monkeypatch.setattr(module, name, factory)
    return made


def wait_until(check, seconds: float = 5.0):
    """Poll ``check`` until it returns a truthy value."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError('condition not reached')


def test_runtime_drivers_use_public_constructors_with_read_defaults(tmp_path: Path, fakes: dict) -> None:
    """Claude and DSH default to read-only access like Pi; Codex needs its own settings."""
    request = host.pi_request({}, tmp_path, PARENT)
    drivers = host.runtime_drivers(tmp_path, request, {'pi': {}, 'claude': {}, 'dsh': {'model': 'd'},
                                                       'codex': None})
    assert set(drivers) == {'pi', 'claude', 'codex', 'dsh'}
    assert fakes['pi'].arguments == (request,)
    assert fakes['claude'].arguments == (tmp_path, {'worktree_access': 'read'})
    assert fakes['codex'].arguments == (None,)
    assert fakes['dsh'].arguments == (tmp_path, {'sandbox': 'read-only', 'model': 'd'})
    host.runtime_drivers(tmp_path, request, {'claude': {'worktree_access': 'write'}, 'dsh': {}, 'codex': {}})
    assert fakes['claude'].arguments[1] == {'worktree_access': 'write'}


def test_codex_without_settings_is_refused_at_create(tmp_path: Path) -> None:
    """The real Codex driver without captured settings names the missing input."""
    drivers = host.runtime_drivers(tmp_path, host.pi_request({}, tmp_path, PARENT),
                                   {'claude': {}, 'dsh': {}, 'codex': None})
    call = bind(AgentControl(tmp_path / 'data', drivers), MAIN)
    result = call({'action': 'create', 'runtime': 'codex', 'instruction': 'hi'})
    assert result.document['error']['code'] == 'invalid-config'


def test_pi_host_routes_creates_to_every_runtime(tmp_path: Path, fakes: dict) -> None:
    """One Pi Main creates children on Pi, Claude, Codex and DSH, each with its own model."""
    root = tmp_path / 'data'
    root.mkdir()
    (root / 'config.yml').write_text('''connections:
  work-claude:
    runtime: claude
    models: [claude-sonnet-5-5]
  work-pi:
    runtime: pi
    provider: anthropic
    models: [child-model]
presets:
  reviewer:
    connection: work-claude
    model: claude-sonnet-5-5
    reasoning_effort: high
''')
    drivers = host.runtime_drivers(tmp_path, host.pi_request({}, tmp_path, PARENT),
                                   {'claude': {}, 'dsh': {}, 'codex': None})
    control = AgentControl(root, drivers)
    control.require_connections()
    call = bind(control, MAIN)
    created = {}
    for runtime, extra in (('pi', {'model': 'child-model'}), ('claude', {'preset': 'reviewer'}),
                           ('codex', {}), ('dsh', {'reasoning_effort': 'low'})):
        result = call({'action': 'create', 'runtime': runtime, 'instruction': 'hi', **extra})
        assert not result.failed, result.document
        created[runtime] = result.document['result']
    assert {runtime: document['runtime'] for runtime, document in created.items()} == {
        runtime: runtime for runtime in created}
    assert fakes['pi'].prepared[0]['model'] == 'child-model'
    assert fakes['pi'].prepared[0]['connection'] == 'work-pi'
    assert (fakes['claude'].prepared[0]['model'], fakes['claude'].prepared[0]['reasoning_effort']) == (
        'claude-sonnet-5-5', 'high')
    assert fakes['codex'].prepared == [None]
    assert fakes['dsh'].prepared[0]['reasoning_effort'] == 'low'
    assert created['claude']['preset'] == 'reviewer' and created['pi']['model'] == 'child-model'
    for request, code in (({'runtime': 'gemini'}, 'unsupported-runtime'),
                          ({'runtime': 'pi', 'model': 'parent-model'}, 'invalid-model'),
                          ({'runtime': 'pi', 'preset': 'reviewer'}, 'invalid-preset')):
        result = call({'action': 'create', 'instruction': 'hi', **request})
        assert result.document['error']['code'] == code


class Pipe:
    """The extension side of the host's notice pipe."""

    def __init__(self, shown: bool | None = True) -> None:
        """``shown`` is the acknowledgement to send; ``None`` sends none."""
        self.lines: list[dict] = []
        self.shown = shown
        self.notices: host.Notices | None = None
        self.closed = False

    def write(self, text: str) -> None:
        """Record one line and acknowledge it the way the extension does."""
        if self.closed:
            raise ValueError('I/O operation on closed file.')
        document = json.loads(text)
        self.lines.append(document)
        if self.shown is not None and 'notice' in document:
            threading.Thread(target=self.notices.acknowledge,
                             args=(document['notice']['id'], self.shown)).start()

    def flush(self) -> None:
        """Lines are recorded at once."""


def notice(**fields) -> dict:
    """One AgentControl host notice addressed to this Main."""
    return {'parent': None, 'agent': 'agent-1', 'session': 'child', 'execution': 'exec-1',
            'body': 'answer', 'outcome': 'completed', 'creator': {'session': 'pi-main'}, 'error': None,
            **fields}


def notices(shown: bool | None = True, timeout: float = 2.0) -> tuple[host.Notices, Pipe]:
    """Bind a notice sender to a recording pipe."""
    pipe = Pipe(shown)
    sender = host.Notices(pipe, 'pi-main', timeout)
    pipe.notices = sender
    return sender, pipe


def test_notice_receiver_outcomes() -> None:
    """Shown is delivered, refused or unwritable is unavailable, silence is unconfirmed."""
    sender, pipe = notices()
    assert sender.receive(notice()) is True
    assert pipe.lines == [{'notice': {'id': 'exec-1:completed', 'alias': 'agent-1', 'agent': 'agent-1',
                                      'event': 'completed', 'message': 'answer', 'execution': 'exec-1'}}]
    assert sender.receive(notice(parent='agent-0')) is False
    assert sender.receive(notice(creator={'session': 'another-main'})) is False
    assert len(pipe.lines) == 1
    sender.receive(notice(execution='exec-2', outcome='failed', body=None,
                          error={'code': 'RUNTIME_REQUEST_FAILED', 'message': 'provider refused'}))
    assert pipe.lines[-1]['notice']['message'] == 'provider refused'
    sender, pipe = notices(shown=False)
    assert sender.receive(notice()) is False
    sender, pipe = notices(shown=None, timeout=0.05)
    assert sender.receive(notice()) == 'unconfirmed'
    sender, pipe = notices()
    pipe.closed = True
    assert sender.receive(notice()) is False


def test_notice_waiting_at_shutdown_is_unavailable_and_later_ones_are_not_written() -> None:
    """Native shutdown settles a pending notice as not shown and stops pushing."""
    sender, pipe = notices(shown=None, timeout=10)
    outcome: list = []
    worker = threading.Thread(target=lambda: outcome.append(sender.receive(notice())))
    worker.start()
    wait_until(lambda: pipe.lines)
    sender.close()
    worker.join(5)
    assert outcome == [False]
    assert sender.receive(notice(execution='exec-2')) is False
    assert len(pipe.lines) == 1


def test_a_body_being_pushed_is_hidden_from_wait_and_status() -> None:
    """While this host pushes an end, wait/status do not show its body a second time."""
    sender, _ = notices()

    def agent(notification: str, ended_at: float, parent=None, children=()) -> dict:
        return {'parent': parent, 'children': list(children), 'last_result': {
            'notification': notification, 'ended_at': ended_at, 'last_message': 'answer'}}

    now = time.time()
    pushing, older, member = agent('queueing', now), agent('queueing', sender.started - 60), agent(
        'queueing', now, parent='agent-1')
    shown = agent('unavailable', now, children=[member])
    for document in (pushing, older, shown):
        sender.hide_pushed(document)
    assert pushing['last_result']['last_message'] is None
    assert older['last_result']['last_message'] == 'answer'
    assert shown['last_result']['last_message'] == 'answer'
    assert member['last_result']['last_message'] == 'answer'
    sender.close()
    closing = agent('queueing', time.time())
    sender.hide_pushed(closing)
    assert closing['last_result']['last_message'] == 'answer'


def last_result(call, agent: str) -> dict:
    """Read the Agent's last result once it has one."""
    return wait_until(lambda: (call({'action': 'status', 'agent': agent}).document['result']
                               .get('last_result')))


def test_each_end_is_pushed_once_and_shutdown_ends_are_recorded(tmp_path: Path, fakes: dict) -> None:
    """Message and system exception reach the Pi Main once; ends at shutdown stay readable."""
    sender, pipe = notices()
    drivers = host.runtime_drivers(tmp_path, host.pi_request({}, tmp_path, PARENT),
                                   {'claude': {}, 'dsh': {}, 'codex': None})
    call = bind(AgentControl(tmp_path / 'data', drivers, event_receiver=sender.receive), MAIN)
    answered = call({'action': 'create', 'runtime': 'claude', 'instruction': 'hi'}).document['agent']
    assert wait_until(lambda: last_result(call, answered)['notification'] == 'delivered')
    assert last_result(call, answered)['last_message'] is None
    fakes['codex'].finish = ('failed', None, {'code': 'RUNTIME_REQUEST_FAILED', 'message': 'login expired'})
    failed = call({'action': 'create', 'runtime': 'codex', 'instruction': 'hi'}).document['agent']
    assert wait_until(lambda: last_result(call, failed)['notification'] == 'delivered')
    assert [line['notice']['event'] for line in pipe.lines] == ['completed', 'failed']
    assert pipe.lines[1]['notice']['message'] == 'login expired'
    # Repeated reads and waits never push again.
    call({'action': 'wait', 'agent': answered, 'timeout_seconds': 0.1})
    call({'action': 'status'})
    assert len(pipe.lines) == 2

    sender.close()
    fakes['dsh'].finish = ('interrupted', 'partial work', None)
    stopped = call({'action': 'create', 'runtime': 'dsh', 'instruction': 'hi'}).document['agent']
    assert wait_until(lambda: last_result(call, stopped)['notification'] == 'unavailable')
    assert last_result(call, stopped)['last_message'] == 'partial work'
    assert len(pipe.lines) == 2


def test_pi_package_manifest_loads_the_extension() -> None:
    """Pi installs agent_swarm/pi as a package; its version repeats the single version."""
    directory = SOURCE / 'agent_swarm/pi'
    manifest = json.loads((directory / 'package.json').read_text())
    assert manifest['version'] == agent_swarm.__version__
    assert 'pi-package' in manifest['keywords']
    assert [(directory / path).resolve() for path in manifest['pi']['extensions']] == [
        (directory / 'extension.mjs').resolve()]


def host_environment(tmp_path: Path, session: str = 'pi-main') -> dict:
    """The environment the extension gives the host, with this test as the Pi parent."""
    environment = {key: value for key, value in os.environ.items()
                   if key not in {'AGENT_SWARM_CONNECTION', 'DSH_SESSION_ID', 'DSH_AGENT_SOURCE'}}
    return {**environment, 'AGENT_SWARM_PI_ENTRY': sys.executable, 'AGENT_SWARM_PI_PROVIDER': 'anthropic',
            'AGENT_SWARM_PI_MODEL': 'parent-model', 'GRAPHTRAJ_NATIVE_RUNTIME': 'pi',
            'GRAPHTRAJ_NATIVE_SESSION': session, 'GRAPHTRAJ_NATIVE_SESSION_FILE': str(tmp_path / 's.jsonl'),
            'PI_CODING_AGENT_DIR': str(tmp_path / 'pi-home'), 'PYTHONPATH': str(SOURCE)}


def run_host(tmp_path: Path, configuration: dict, close: bool = True) -> tuple[subprocess.Popen, str]:
    """Start the host as the extension does and return its first stdout line."""
    (tmp_path / 'host.json').write_text(json.dumps(configuration))
    process = subprocess.Popen([sys.executable, '-m', 'agent_swarm.pi.host', '--config', str(tmp_path / 'host.json')],
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


def test_host_starts_from_root_only_and_closes_at_shutdown(tmp_path: Path) -> None:
    """The Task-free form starts, serves a connection and ends cleanly on pipe close."""
    process, first = run_host(tmp_path, {'root': str(tmp_path / 'data')})
    assert process.returncode == 0, process.stderr.read()
    assert json.loads(first)['connection']


def test_host_start_refusals(tmp_path: Path) -> None:
    """The old form, an unusable declared connection and archiving stop the host with a code."""
    def refused(configuration: dict) -> dict:
        process, first = run_host(tmp_path, configuration)
        assert process.returncode == 1 and first == ''
        return json.loads(process.stderr.read())['error']

    assert 'adapter_request is no longer accepted' in refused(
        {'root': str(tmp_path / 'data'), 'adapter_request': {}})['message']
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'config.yml').write_text(f'connections:\n  p:\n    runtime: pi\n    home: {tmp_path / "no-login"}\n')
    assert refused({'root': str(data)})['code'] == 'runtime-unavailable'
    (data / 'config.yml').write_text('save_normalized_sessions: true\n')
    assert refused({'root': str(data)})['code'] == 'archive-unavailable'


EXTENSION = '''
import { pathToFileURL } from 'node:url';
const module = await import(pathToFileURL(process.argv[1]).href);
const sent = [];
const pi = {
  registerFlag() {}, getFlag: name => name === 'agents-config' ? process.env.TEST_CONFIG : undefined,
  on() {}, registerMcpServer() {},
  sendMessage: (message, options) => {
    if (process.env.TEST_REFUSE && sent.length === 0) { sent.push(null); throw new Error('refused'); }
    sent.push({message, options});
  },
};
const ctx = {hasUI: false, cwd: process.cwd(), sessionManager: {
  getSessionId: () => 'pi-main', getSessionFile: () => '', getHeader: () => ({id: 'pi-main'}), getEntries: () => []}};
const owner = module.registerAgents(pi);
await owner.start(ctx);
while (sent.length < 2) await new Promise(done => setTimeout(done, 20));
await owner.close();
console.log(JSON.stringify(sent));
'''

FAKE_HOST = '''
import json, os, sys
sys.stdin.readline()
def say(document):
    print(json.dumps(document), flush=True)
def notice(identity, event, message):
    say({'notice': {'id': identity, 'alias': 'agent-1', 'agent': 'agent-1', 'event': event,
                    'message': message, 'execution': identity.split(':')[0]}})
say({'connection': '/fake/address'})
notice('exec-1:completed', 'completed', 'the answer')
acknowledgements = [json.loads(sys.stdin.readline())]
notice('exec-2:failed', 'failed', 'provider refused')
acknowledgements.append(json.loads(sys.stdin.readline()))
assert sys.stdin.read() == ''
notice('exec-3:interrupted', 'interrupted', 'after shutdown')
with open(os.environ['TEST_LOG'], 'w') as log:
    json.dump(acknowledgements, log)
'''


def run_extension(tmp_path: Path, **environment: str) -> tuple[list, list]:
    """Drive the agents Pi extension against a scripted host process."""
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required')
    fake = tmp_path / 'fake-python'
    fake.write_text('#!' + sys.executable + '\n' + FAKE_HOST)
    fake.chmod(0o755)
    env = {key: value for key, value in os.environ.items()
           if key not in {'AGENT_SWARM_CONNECTION', 'DSH_SESSION_ID', 'DSH_AGENT_SOURCE'}}
    env.update(AGENT_SWARM_PYTHON=str(fake), TEST_CONFIG=str(tmp_path / 'host.json'),
               TEST_LOG=str(tmp_path / 'acks.json'), **environment)
    result = subprocess.run([node, '--input-type=module', '-e', EXTENSION, str(SOURCE / 'agent_swarm/pi/extension.mjs')],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout), json.loads((tmp_path / 'acks.json').read_text())


def test_extension_injects_each_notice_natively_and_acknowledges_it(tmp_path: Path) -> None:
    """Idle starts a turn, busy queues a follow-up; nothing is injected after shutdown."""
    sent, acknowledgements = run_extension(tmp_path)
    assert [item['options'] for item in sent] == [{'triggerTurn': True, 'deliverAs': 'followUp'}] * 2
    first = sent[0]['message']
    assert first['customType'] == 'graphtraj:agent-communication' and first['display'] is True
    assert first['content'] == '[agents notice from agent-1 · completed]\nthe answer'
    assert first['details']['fact'] == 'notice:exec-1:completed'
    assert sent[1]['message']['content'].endswith('· failed]\nprovider refused')
    assert acknowledgements == [{'ack': 'exec-1:completed', 'shown': True},
                                {'ack': 'exec-2:failed', 'shown': True}]


def test_extension_reports_a_notice_it_could_not_inject(tmp_path: Path) -> None:
    """A failed injection is acknowledged as not shown, so the host keeps it readable."""
    sent, acknowledgements = run_extension(tmp_path, TEST_REFUSE='1')
    assert sent[0] is None
    assert acknowledgements == [{'ack': 'exec-1:completed', 'shown': False},
                                {'ack': 'exec-2:failed', 'shown': True}]
