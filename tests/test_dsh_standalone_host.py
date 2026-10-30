"""DSH as a Task-free agents host: configuration, Runtime routing, binding and notices (383)."""

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

from agent_swarm import AgentControl, AgentsError, Caller, bind
from agent_swarm.dsh import host


SOURCE = Path(__file__).resolve().parents[1] / 'src'
MAIN = Caller('dsh-native', None, session='dsh-main', runtime='dsh')


def header(cwd: Path, **fields) -> dict:
    """A native DSH main Session header as the plugin supplies it."""
    return {'version': 4, 'id': 'dsh-main', 'cwd': str(cwd), 'isSeeded': False, **fields}


@pytest.mark.parametrize(('document', 'message'), [
    ([], 'must be a JSON object'),
    ({'root': '/data', 'roles': {}}, 'Unknown DSH host configuration keys'),
    ({'root': 'relative'}, 'absolute data root'),
    ({}, 'absolute data root'),
    ({'root': '/data', 'claude': 'opus'}, '"claude" must be an object'),
])
def test_configuration_refusals(document: object, message: str) -> None:
    """Anything but the documented Task-free form is refused with a reason."""
    with pytest.raises(ValueError, match=message):
        host.read_configuration(document)


def test_configuration_accepts_root_and_per_runtime_settings() -> None:
    """Every Runtime section is optional."""
    root, settings = host.read_configuration({'root': '/data'})
    assert root == Path('/data')
    assert settings == {'dsh': None, 'claude': None, 'codex': None, 'pi': None}
    _, settings = host.read_configuration({'root': '/data', 'dsh': {'model': 'd'}, 'codex': {'adapter_request': {}}})
    assert settings['dsh'] == {'model': 'd'} and settings['codex'] == {'adapter_request': {}}


@pytest.mark.parametrize('fields', [
    {'origin': 'subagent'}, {'delegationDepth': 1}, {'version': 3}, {'isSeeded': None}, {'id': ''},
])
def test_only_a_native_main_session_is_bound(tmp_path: Path, fields: dict) -> None:
    """A native subagent or an unrecognized header never becomes the host's root caller."""
    assert host.native_main(header(tmp_path), tmp_path) == {
        'runtime': 'dsh', 'session': 'dsh-main', 'source': 'main', 'cwd': str(tmp_path)}
    with pytest.raises(ValueError, match='native DSH main Session'):
        host.native_main(header(tmp_path, **fields), tmp_path)
    with pytest.raises(ValueError, match='cwd does not match'):
        host.native_main(header(tmp_path / 'elsewhere'), tmp_path)


class Fake:
    """Driver stand-in recording its constructor settings and prepare calls."""

    def __init__(self, runtime: str, *arguments: object) -> None:
        """Keep the public constructor's arguments."""
        self.runtime   = runtime
        self.arguments = arguments
        self.prepared: list[dict | None] = []
        self.finish: tuple[str, str | None, dict | None] = ('completed', 'answer', None)
        self.request: dict | None = None

    def prepare(self, runtime, caller, *, selection=None):
        """Record the selection the core resolved for this create."""
        if runtime != self.runtime:
            raise AgentsError('unsupported-runtime', 'wrong driver')
        self.prepared.append(selection)
        return {'runtime': runtime}

    def require_available(self, connection) -> None:
        """Every declared connection is installed and logged in here."""

    def start(self, run) -> None:
        """Bind a Session, optionally report a native request twice, then end."""
        run.events.session('native-' + run.agent[-6:])
        if self.request is not None:
            run.events.request(self.request)
            run.events.request(self.request)
            return
        outcome, message, error = self.finish
        threading.Thread(target=run.events.finished, args=(outcome,),
                         kwargs={'last_message': message, 'error': error}).start()

    def interrupt(self, run) -> bool:
        """End a run waiting on its request as interrupted."""
        threading.Thread(target=run.events.finished, args=('interrupted',)).start()
        return True


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Replace the public driver constructors the host uses."""
    made: dict = {}
    for runtime, name, module in (('claude', 'ClaudeDriver', 'agent_swarm.claude.driver'),
                                  ('codex', 'CodexDriver', 'agent_swarm.codex.driver'),
                                  ('dsh', 'DshDriver', 'agent_swarm.dsh.driver'),
                                  ('pi', 'PiDriver', 'agent_swarm.pi.driver')):
        def factory(*arguments, runtime=runtime):
            made[runtime] = Fake(runtime, *arguments)
            return made[runtime]
        monkeypatch.setattr(f'{module}.{name}', factory)
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


def settings(**sections) -> dict:
    """A read configuration's per-Runtime settings."""
    return {'dsh': None, 'claude': None, 'codex': None, 'pi': None, **sections}


def test_runtime_drivers_use_public_constructors_with_read_defaults(tmp_path: Path, fakes: dict) -> None:
    """DSH children default to read-only and the parent's model; Pi exists only when configured."""
    drivers = host.runtime_drivers(tmp_path, settings(), 'deepseek-v4-pro')
    assert set(drivers) == {'dsh', 'claude', 'codex'}
    assert fakes['dsh'].arguments == (tmp_path, {'sandbox': 'read-only', 'model': 'deepseek-v4-pro'})
    assert fakes['claude'].arguments == (tmp_path, {'worktree_access': 'read'})
    assert fakes['codex'].arguments == (None,)
    drivers = host.runtime_drivers(tmp_path, settings(
        dsh={'model': 'other', 'sandbox': 'workspace-write'}, claude={'worktree_access': 'write'},
        pi={'provider': 'anthropic', 'model': 'm'}), None)
    assert set(drivers) == {'dsh', 'claude', 'codex', 'pi'}
    assert fakes['dsh'].arguments[1] == {'sandbox': 'workspace-write', 'model': 'other'}
    assert fakes['claude'].arguments[1] == {'worktree_access': 'write'}
    assert fakes['pi'].arguments == ({'worktree_path': str(tmp_path), 'provider': 'anthropic', 'model': 'm'},)


def test_dsh_host_routes_creates_to_every_runtime_with_per_child_models(tmp_path: Path, fakes: dict) -> None:
    """One DSH Main creates DSH, Claude and Codex children, each with its own model and effort."""
    root = tmp_path / 'data'
    root.mkdir()
    (root / 'config.yml').write_text('''connections:
  work-claude:
    runtime: claude
    models: [claude-sonnet-5-5]
  work-dsh:
    runtime: dsh
    models: [deepseek-child]
presets:
  reviewer:
    connection: work-claude
    model: claude-sonnet-5-5
    reasoning_effort: high
''')
    control = AgentControl(root, host.runtime_drivers(tmp_path, settings(), 'deepseek-parent'))
    control.require_connections()
    call = bind(control, MAIN)
    created = {}
    for runtime, extra in (('dsh', {'model': 'deepseek-child', 'reasoning_effort': 'low'}),
                           ('claude', {'preset': 'reviewer'}), ('codex', {})):
        result = call({'action': 'create', 'runtime': runtime, 'instruction': 'hi', **extra})
        assert not result.failed, result.document
        created[runtime] = result.document['result']
    assert {runtime: document['runtime'] for runtime, document in created.items()} == {
        runtime: runtime for runtime in created}
    assert (fakes['dsh'].prepared[0]['model'], fakes['dsh'].prepared[0]['reasoning_effort'],
            fakes['dsh'].prepared[0]['connection']) == ('deepseek-child', 'low', 'work-dsh')
    assert (fakes['claude'].prepared[0]['model'], fakes['claude'].prepared[0]['reasoning_effort']) == (
        'claude-sonnet-5-5', 'high')
    assert fakes['codex'].prepared == [None]
    for request, code in (({'runtime': 'gemini'}, 'unsupported-runtime'),
                          ({'runtime': 'pi'}, 'unsupported-runtime'),
                          ({'runtime': 'dsh', 'model': 'unlisted'}, 'invalid-model')):
        result = call({'action': 'create', 'instruction': 'hi', **request})
        assert result.document['error']['code'] == code


def test_codex_without_settings_is_refused_at_create(tmp_path: Path) -> None:
    """The real Codex driver without captured settings names the missing input."""
    call = bind(AgentControl(tmp_path / 'data', host.runtime_drivers(tmp_path, settings(), None)), MAIN)
    result = call({'action': 'create', 'runtime': 'codex', 'instruction': 'hi'})
    assert result.document['error']['code'] == 'invalid-config'


class Pipe:
    """The plugin side of the host's notice pipe."""

    def __init__(self, shown: bool | None = True) -> None:
        """``shown`` is the acknowledgement to send; ``None`` sends none."""
        self.lines: list[dict] = []
        self.shown = shown
        self.notices: host.Notices | None = None

    def write(self, text: str) -> None:
        """Record one line and acknowledge it the way the plugin does."""
        document = json.loads(text)
        self.lines.append(document)
        if self.shown is not None and 'notice' in document:
            threading.Thread(target=self.notices.acknowledge,
                             args=(document['notice']['id'], self.shown)).start()

    def flush(self) -> None:
        """Lines are recorded at once."""


def notices(shown: bool | None = True, timeout: float = 2.0) -> tuple[host.Notices, Pipe]:
    """Bind a notice sender to a recording pipe."""
    pipe = Pipe(shown)
    sender = host.Notices(pipe, 'dsh-main', timeout)
    pipe.notices = sender
    return sender, pipe


def notice(**fields) -> dict:
    """One AgentControl host notice addressed to this Main."""
    return {'parent': None, 'agent': 'agent-1', 'session': 'child', 'execution': 'exec-1',
            'body': 'answer', 'outcome': 'completed', 'creator': {'session': 'dsh-main'}, 'error': None,
            **fields}


def test_notice_receiver_outcomes() -> None:
    """Admitted is delivered, refused is held, silence is unconfirmed; other Mains are skipped."""
    sender, pipe = notices()
    assert sender.receive(notice()) is True
    assert pipe.lines == [{'notice': {'id': 'exec-1:completed', 'agent': 'agent-1', 'session': 'child',
                                      'event': 'completed', 'message': 'answer', 'execution': 'exec-1'}}]
    assert sender.receive(notice(parent='agent-0')) is False
    assert sender.receive(notice(creator={'session': 'another-main'})) is False
    assert len(pipe.lines) == 1
    sender.receive(notice(execution='exec-2', outcome='request', request='token-1', body='Permission request'))
    assert pipe.lines[-1]['notice']['id'] == 'exec-2:request:token-1'
    assert notices(shown=False)[0].receive(notice()) == 'held'
    assert notices(shown=None, timeout=0.05)[0].receive(notice()) == 'unconfirmed'
    sender.close()
    assert sender.receive(notice(execution='exec-3')) == 'held'
    assert len(pipe.lines) == 2


def last_result(call, agent: str) -> dict:
    """Read the Agent's last result once it has one."""
    return wait_until(lambda: (call({'action': 'status', 'agent': agent}).document['result']
                               .get('last_result')))


def test_each_message_request_and_error_reaches_the_main_once(tmp_path: Path, fakes: dict) -> None:
    """A final answer, a native request and a failure each reach the DSH Main once."""
    sender, pipe = notices()
    control = AgentControl(tmp_path / 'data', host.runtime_drivers(tmp_path, settings(), 'm'),
                           event_receiver=sender.receive, request_notices=True)
    call = bind(control, MAIN)
    answered = call({'action': 'create', 'runtime': 'claude', 'instruction': 'hi'}).document['agent']
    assert wait_until(lambda: last_result(call, answered)['notification'] == 'delivered')
    assert last_result(call, answered)['last_message'] is None
    fakes['codex'].finish = ('failed', None, {'code': 'RUNTIME_REQUEST_FAILED', 'message': 'login expired'})
    failed = call({'action': 'create', 'runtime': 'codex', 'instruction': 'hi'}).document['agent']
    assert wait_until(lambda: last_result(call, failed)['notification'] == 'delivered')
    fakes['dsh'].request = {'request_token': 'token-1', 'method': 'dsh/approval-request', 'tool': 'bash'}
    asking = call({'action': 'create', 'runtime': 'dsh', 'instruction': 'hi'}).document['agent']
    wait_until(lambda: len(pipe.lines) == 3)
    call({'action': 'wait', 'agent': answered, 'timeout_seconds': 0.1})
    call({'action': 'status'})
    assert [line['notice']['event'] for line in pipe.lines] == ['completed', 'failed', 'request']
    assert pipe.lines[0]['notice']['message'] == 'answer'
    assert pipe.lines[1]['notice']['message'] == 'login expired'
    assert pipe.lines[2]['notice']['agent'] == asking
    assert 'dsh/approval-request' in pipe.lines[2]['notice']['message']
    call({'action': 'interrupt', 'agent': asking})


def test_ask_parent_reaches_the_main_once_without_its_question(tmp_path: Path, fakes: dict) -> None:
    """A child's decision request reaches the DSH Main like a native one (385 with 383)."""
    sender, pipe = notices()
    control = AgentControl(tmp_path / 'data', host.runtime_drivers(tmp_path, settings(), 'm'),
                           event_receiver=sender.receive, request_notices=True)
    call = bind(control, MAIN)
    fakes['dsh'].request = {'request_token': 'token-1', 'method': 'dsh/approval-request', 'tool': 'bash'}
    agent = call({'action': 'create', 'runtime': 'dsh', 'instruction': 'hi'}).document['agent']
    wait_until(lambda: len(pipe.lines) == 1)
    child = bind(control, Caller('runtime-mcp', agent))
    for _ in range(2):
        asked = child({'action': 'ask_parent', 'kind': 'decision', 'question': 'Secret option?',
                       'timeout_seconds': 0.1}).document['result']
        assert asked['timed_out'] is True
    assert len(pipe.lines) == 2
    assert pipe.lines[1]['notice']['id'] == f"{pipe.lines[1]['notice']['execution']}:request:{asked['request']['request_token']}"
    assert 'agents/decision' in pipe.lines[1]['notice']['message'] and 'Secret' not in pipe.lines[1]['notice']['message']
    call({'action': 'interrupt', 'agent': agent})


# A stand-in for the native DSH entry: it spawns the host the way plugin.mjs
# does, so the host's kernel parent is this script run by the test's Python.
FAKE_DSH = '''
import json, os, subprocess, sys
host = subprocess.Popen([sys.executable, '-m', 'agent_swarm.dsh.host', '--config', os.environ['TEST_CONFIG']],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
host.stdin.write(os.environ['TEST_LAUNCH'] + '\\n')
host.stdin.flush()
first = host.stdout.readline()
calls = []
if first:
    address = json.loads(first)['connection']
    for session in ('dsh-main', 'other-session'):
        env = {**os.environ, 'AGENT_SWARM_CONNECTION': address, 'DSH_SESSION_ID': session, 'DSH_AGENT_SOURCE': 'main'}
        done = subprocess.run([sys.executable, '-m', 'agent_swarm.cli', json.dumps({'action': 'discover'})],
                              env=env, capture_output=True, text=True)
        calls.append([done.returncode, done.stdout])
host.stdin.close()
code = host.wait(20)
print(json.dumps({'first': first, 'code': code, 'stderr': host.stderr.read(), 'calls': calls}))
'''


def fake_dsh(tmp_path: Path) -> Path:
    """A fake DSH installation whose entry starts the host as its child."""
    package = tmp_path / 'dsh'
    (package / 'lib').mkdir(parents=True, exist_ok=True)
    (package / 'package.json').write_text(json.dumps({'name': '@deepseek-ai/dsh', 'version': '0.2.2-alpha.2'}))
    (package / 'lib' / 'bin.py').write_text(FAKE_DSH)
    return package / 'lib' / 'bin.py'


def run_host(tmp_path: Path, configuration: dict, launch: dict | None = None, **environment: str) -> dict:
    """Start the host below a fake native DSH and report what happened."""
    entry = fake_dsh(tmp_path)
    (tmp_path / 'host.json').write_text(json.dumps(configuration))
    env = {key: value for key, value in os.environ.items()
           if key not in {'AGENT_SWARM_CONNECTION', 'DSH_SESSION_ID', 'DSH_AGENT_SOURCE'}}
    env.update(AGENT_SWARM_DSH_NODE=sys.executable, AGENT_SWARM_DSH_ENTRY=str(entry),
               TEST_CONFIG=str(tmp_path / 'host.json'), PYTHONPATH=str(SOURCE),
               TEST_LAUNCH=json.dumps(launch or {'header': header(tmp_path), 'model': 'deepseek-parent'}),
               **environment)
    result = subprocess.run([sys.executable, str(entry)], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_host_binds_only_the_supplied_native_session(tmp_path: Path) -> None:
    """The Task-free form starts below DSH; only the plugin's Session may call; pipe close ends it."""
    outcome = run_host(tmp_path, {'root': str(tmp_path / 'data')})
    assert outcome['code'] == 0, outcome['stderr']
    assert json.loads(outcome['first'])['connection']
    (bound, bound_output), (other, other_output) = outcome['calls']
    assert bound == 0, bound_output
    assert other == 1 and json.loads(other_output)['error']['code'] == 'authority-denied'


def test_host_start_refusals(tmp_path: Path) -> None:
    """Bad configuration, an unusable declared connection, a subagent and a bound child stop it."""
    def refused(configuration: dict, launch: dict | None = None, **environment: str) -> dict:
        outcome = run_host(tmp_path, configuration, launch, **environment)
        assert outcome['code'] == 1 and outcome['first'] == ''
        return json.loads(outcome['stderr'])['error']

    data = tmp_path / 'data'
    assert refused({'root': str(data), 'roles': {}})['code'] == 'invalid-config'
    assert 'native DSH main Session' in refused(
        {'root': str(data)}, {'header': header(tmp_path, origin='subagent')})['message']
    assert 'already-bound child' in refused({'root': str(data)}, AGENT_SWARM_CONNECTION='/x')['message']
    data.mkdir()
    (data / 'config.yml').write_text('connections:\n  d:\n    runtime: dsh\n    api_key_env: AGENTS_383_UNSET\n')
    assert refused({'root': str(data), 'dsh': {'executable': sys.executable}})['code'] == 'runtime-unavailable'


def test_host_starts_with_archiving_on(tmp_path: Path) -> None:
    """Every host archives when saving is on (384), so the DSH host no longer refuses it."""
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'config.yml').write_text('save_normalized_sessions: true\n')
    outcome = run_host(tmp_path, {'root': str(data)})
    assert outcome['code'] == 0, outcome['stderr']
    assert json.loads(outcome['first'])['connection']


def test_host_refuses_a_parent_that_is_not_the_native_dsh(tmp_path: Path) -> None:
    """Copied plugin variables do not make another process the native DSH parent."""
    entry = fake_dsh(tmp_path)
    (tmp_path / 'host.json').write_text(json.dumps({'root': str(tmp_path / 'data')}))
    env = {key: value for key, value in os.environ.items()
           if key not in {'AGENT_SWARM_CONNECTION', 'DSH_SESSION_ID', 'DSH_AGENT_SOURCE'}}
    env.update(AGENT_SWARM_DSH_NODE=sys.executable, AGENT_SWARM_DSH_ENTRY=str(entry), PYTHONPATH=str(SOURCE))
    result = subprocess.run([sys.executable, '-m', 'agent_swarm.dsh.host', '--config', str(tmp_path / 'host.json')],
                            cwd=tmp_path, env=env, input=json.dumps({'header': header(tmp_path)}) + '\n',
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 1 and result.stdout == ''
    assert 'not owned by the native DSH process' in json.loads(result.stderr)['error']['message']


def test_dsh_package_declares_the_host_bundle() -> None:
    """``dsh plugin add`` reads the bundle patch, which inserts the plugin's host row."""
    directory = SOURCE / 'agent_swarm' / 'dsh'
    manifest = json.loads((directory / 'package.json').read_text())
    patch = (directory / manifest['dsh']['bundle']['patch']).read_text()
    assert 'name: agents-dsh' in patch and 'mcpCommand' not in patch
    assert manifest['main'] == 'plugin.mjs'


# Stub DSH packages, enough for plugin.mjs to load outside DSH.
STUBS = {
    'dsh-mcp-client': 'export default { name: "mcp-client" };',
    'schemastery': '''const chain = () => ({ default: () => chain(), required: () => chain() });
export default { object: () => ({}), string: chain, array: chain };''',
    'dsh-typert-protocol': 'export class TypertRemoteService {}\nexport function Remote() {}',
    'dsh-llm': 'export function createUserMessage(message) { return message; }',
}

PLUGIN = '''
import { pathToFileURL } from 'node:url';
const plugin = await import(pathToFileURL(process.argv[1]).href);
const handlers = {}, attached = [], received = [], effects = [];
const ctx = {
  on: (event, handler) => { handlers[event] = handler; },
  effect: effect => effects.push(effect),
  plugin: () => ({}),
  logger: { error: message => received.push({ log: message }) },
  get: name => name === 'agentMessages' ? { receive: async request => {
    received.push(request);
    if (received.length === 2) throw new Error('not active');
    return { accepted: true, duplicate: false };
  } } : undefined,
};
const agent = (id, extra = {}) => ({
  session: { id, header: { version: 4, id, cwd: process.cwd(), isSeeded: false, ...extra } },
  model: { current: () => ({ model: 'deepseek-parent' }) },
  ctx: { plugin: (_client, options) => { attached.push({ id, options }); return { await: async () => {} }; } },
});
plugin.apply(ctx, {});
if (!handlers['agent/created']) { console.log(JSON.stringify({ inert: true })); process.exit(0); }
await handlers['agent/created']({ agent: agent('native-sub', { origin: 'subagent' }) });
await handlers['agent/created']({ agent: agent('dsh-main') });
while (received.length < 3) await new Promise(done => setTimeout(done, 20));
await handlers['session/disposed']({ id: 'dsh-main' });
console.log(JSON.stringify({ attached, received }));
'''

FAKE_HOST = '''
import json, os, sys
launch = json.loads(sys.stdin.readline())
def notice(identity, event, message):
    print(json.dumps({'notice': {'id': identity, 'agent': 'agent-1', 'session': 'child-session',
                                 'event': event, 'message': message, 'execution': identity.split(':')[0]}}), flush=True)
print(json.dumps({'connection': '/fake/address'}), flush=True)
acknowledgements = []
for identity, event, message in (('exec-1:completed', 'completed', 'the answer'),
                                 ('exec-2:failed', 'failed', 'provider refused'),
                                 ('exec-3:request:t', 'request', 'Permission request')):
    notice(identity, event, message)
    acknowledgements.append(json.loads(sys.stdin.readline()))
assert sys.stdin.read() == ''
with open(os.environ['TEST_LOG'], 'w') as log:
    json.dump({'launch': launch, 'environment': {key: os.environ.get(key) for key in (
        'AGENT_SWARM_DSH_NODE', 'AGENT_SWARM_DSH_ENTRY')}, 'acknowledgements': acknowledgements,
        'argv': sys.argv[1:]}, log)
'''


def run_plugin(tmp_path: Path, **environment: str) -> tuple[dict, dict | None]:
    """Drive plugin.mjs's host row against stub DSH packages and a scripted host."""
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required')
    tmp_path.mkdir(parents=True, exist_ok=True)
    modules = tmp_path / 'stub' / 'node_modules' / '@deepseek-ai'
    for name, text in STUBS.items():
        (modules / name).mkdir(parents=True)
        (modules / name / 'package.json').write_text(json.dumps({'name': f'@deepseek-ai/{name}', 'type': 'module',
                                                                 'main': 'index.js'}))
        (modules / name / 'index.js').write_text(text)
    fake = tmp_path / 'fake-python'
    fake.write_text('#!' + sys.executable + '\n' + FAKE_HOST)
    fake.chmod(0o755)
    env = {key: value for key, value in os.environ.items()
           if key not in {'AGENT_SWARM_CONNECTION', 'DSH_AGENT_PACKAGE', 'GRAPHTRAJ_CLI_CONNECTION'}}
    env.update(GRAPHTRAJ_DSH_PACKAGE=str(tmp_path / 'stub' / 'entry.js'), AGENT_SWARM_PYTHON=str(fake),
               TEST_LOG=str(tmp_path / 'host.json'), **environment)
    result = subprocess.run([node, '--input-type=module', '-e', PLUGIN, str(SOURCE / 'agent_swarm/dsh/plugin.mjs')],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    log = tmp_path / 'host.json'
    return json.loads(result.stdout), json.loads(log.read_text()) if log.exists() else None


def test_plugin_host_row_relays_each_notice_to_its_main_session(tmp_path: Path) -> None:
    """Only the main Session gets a host; each notice enters its inbox relay once and is acknowledged."""
    shown, log = run_plugin(tmp_path, AGENT_SWARM_DSH_CONFIG='/abs/dsh-host.json')
    assert [item['id'] for item in shown['attached']] == ['dsh-main']
    options = shown['attached'][0]['options']
    assert options['serverName'] == 'agents' and options['args'] == ['-I', '-m', 'agent_swarm.mcp']
    assert options['env'] == {'DSH_SESSION_ID': 'dsh-main', 'DSH_AGENT_SOURCE': 'main',
                              'AGENT_SWARM_CONNECTION': '/fake/address'}
    assert [item['id'] for item in shown['received'][:3]] == [
        'agents-notice:exec-1:completed', 'agents-notice:exec-2:failed', 'agents-notice:exec-3:request:t']
    first = shown['received'][0]
    assert (first['sessionId'], first['recipient'], first['sender'], first['senderSessionId']) == (
        'dsh-main', 'dsh-main', 'agent-1', 'child-session')
    assert first['body'] == '[agents notice from agent-1 · completed]\nthe answer'
    assert log['acknowledgements'] == [{'ack': 'exec-1:completed', 'shown': True},
                                       {'ack': 'exec-2:failed', 'shown': False},
                                       {'ack': 'exec-3:request:t', 'shown': True}]
    assert log['launch']['header']['id'] == 'dsh-main' and log['launch']['model'] == 'deepseek-parent'
    assert log['argv'] == ['-I', '-m', 'agent_swarm.dsh.host', '--config', '/abs/dsh-host.json']
    assert log['environment']['AGENT_SWARM_DSH_NODE'] and log['environment']['AGENT_SWARM_DSH_ENTRY']


def test_plugin_host_row_is_inert_without_configuration_or_inside_an_agent(tmp_path: Path) -> None:
    """No host starts without AGENT_SWARM_DSH_CONFIG, or in a DSH that already is an Agent."""
    assert run_plugin(tmp_path / 'a')[0] == {'inert': True}
    assert run_plugin(tmp_path / 'b', AGENT_SWARM_DSH_CONFIG='/abs/c.json',
                      AGENT_SWARM_CONNECTION='/bound')[0] == {'inert': True}
