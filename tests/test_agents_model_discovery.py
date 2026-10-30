"""agents model discovery through its public function, with controlled native clients.

Each Runtime client is a small executable on ``PATH`` that speaks the native
catalog protocol and records what it was asked. No real Runtime, account or
network is used, and no inference request is possible.
"""

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

import pytest
import yaml

from agent_swarm import discover_models
from agent_swarm.dsh.execution import _PatchLoader


ROOT = Path(__file__).resolve().parents[1]
SECRET = 'sk-controlled-secret-value'

AVAILABLE = 'Native catalog metadata does not establish account calling permission.'
UNKNOWN   = 'Native metadata query failed. Check installation/login in the original Runtime client and refresh.'

PRELUDE = f'''#!{sys.executable}
import json, os, sys
def record(entry):
    with open(os.environ['FAKE_LOG'], 'a', encoding='utf-8') as stream:
        stream.write(json.dumps(entry) + '\\n')
record({{'argv': sys.argv[1:], 'cwd': os.getcwd(),
         'home': {{name: os.environ.get(name) for name in
                  ('CODEX_HOME', 'CLAUDE_CONFIG_DIR', 'PI_CODING_AGENT_DIR', 'DSH_HOME')}}}})
if os.environ.get('FAKE_FAIL'):
    print('native failure with ' + os.environ['FAKE_SECRET'], file=sys.stderr)
    print('native failure with ' + os.environ['FAKE_SECRET'])
    sys.exit(3)
'''

CODEX = PRELUDE + '''
pages = {None: ([{'model': 'gpt-a', 'displayName': 'GPT A',
                  'supportedReasoningEfforts': [{'reasoningEffort': 'low'}, {'reasoningEffort': 'high'}]}],
                'page-2'),
         'page-2': ([{'model': 'gpt-b'}], None)}
for line in sys.stdin:
    message = json.loads(line)
    record({'method': message.get('method')})
    if 'id' not in message:
        continue
    method, params = message['method'], message.get('params') or {}
    if method == 'initialize':
        result = {'userAgent': 'controlled-codex'}
    elif method == 'config/read':
        result = {'config': {'model_provider': 'controlled-provider'}}
    elif method == 'model/list':
        data, cursor = pages[params.get('cursor')]
        result = {'data': data, 'nextCursor': cursor}
    else:
        print(json.dumps({'id': message['id'], 'error': {'code': -32601, 'message': method}}), flush=True)
        continue
    print(json.dumps({'id': message['id'], 'result': result}), flush=True)
'''

CLAUDE = PRELUDE + '''
for line in sys.stdin:
    message = json.loads(line)
    record({'stdin': message})
    assert message == {'type': 'control_request', 'request_id': 'catalog',
                       'request': {'subtype': 'initialize'}}
    print(json.dumps({'type': 'system', 'subtype': 'init'}))
    print(json.dumps({'type': 'control_response', 'response': {
        'subtype': 'success', 'request_id': 'catalog', 'response': {'models': [
            {'value': 'opus', 'displayName': 'Opus', 'supportedEffortLevels': ['low', 'high', 'max']},
            {'value': 'haiku'},
        ]}}}), flush=True)
    break
'''

PI = PRELUDE + '''
agent = os.environ['PI_CODING_AGENT_DIR']
record({'agent': {name: os.readlink(os.path.join(agent, name)) if os.path.islink(os.path.join(agent, name)) else None
                  for name in os.listdir(agent)}})
# What real Pi does in the directory it runs on: its stores, a lock beside auth.json, a package install.
for name in ('models-store.json', 'auth.json.lock', 'npm'):
    open(os.path.join(agent, name), 'w').close()
for line in sys.stdin:
    message = json.loads(line)
    record({'stdin': message})
    assert message == {'id': 'models', 'type': 'get_available_models'}
    print(json.dumps({'type': 'event'}))
    print(json.dumps({'id': 'models', 'success': True, 'data': {'models': [
        {'id': 'model-a', 'name': 'Model A', 'provider': 'first', 'reasoning': True,
         'baseUrl': 'https://first.invalid/v1'},
        {'id': 'model-b', 'provider': 'second', 'baseUrl': 'https://second.invalid/v1'},
    ]}}), flush=True)
    break
'''

DSH = PRELUDE + '''
from http.server import BaseHTTPRequestHandler, HTTPServer
CATALOG = json.loads(os.environ['FAKE_CATALOG'])

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def do_GET(self):
        self.send_response(200)
        self.send_header('Set-Cookie', 'session=controlled; Path=/')
        self.end_headers()
        self.wfile.write(b'ok')
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        record({'method': body['method'], 'cookie': self.headers.get('Cookie')})
        reply = {'rpcId': body['rpcId'], 'result': {'ok': True, 'value': CATALOG}}
        if body['method'] != 'session/modelCatalog':
            reply['result'] = {'ok': False, 'error': {'code': 'unexpected'}}
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

server = HTTPServer(('127.0.0.1', 0), Handler)
print(f'http://127.0.0.1:{server.server_port}/?token=launch', flush=True)
server.serve_forever()
'''


def _can_bind() -> bool:
    """Report whether this environment lets a process listen on a loopback port."""
    try:
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
        return True
    except OSError:
        return False


CAN_BIND = _can_bind()

CATALOG = {'groups': [{'id': 'deepseek-official', 'models': [
               {'id': 'deepseek-flash', 'name': 'Flash',
                'reasoning': {'efforts': [{'id': 'low'}, {'id': 'high'}]}},
               {'id': 'deepseek-plain', 'reasoning': None}]},
           {'id': 'custom', 'models': [{'id': 'custom-model'}]}],
           'failures': [{'id': 'broken', 'message': 'diagnostic ' + SECRET}]}

DSH_MODELS = [
    {'id': 'deepseek-flash', 'alias': 'Flash', 'provider': 'deepseek-official',
     'supported_efforts': ['low', 'high']},
    {'id': 'deepseek-plain', 'alias': 'deepseek-plain', 'provider': 'deepseek-official',
     'supported_efforts': None},
    {'id': 'custom-model', 'alias': 'custom-model', 'provider': 'custom', 'supported_efforts': None},
]
DSH_PROVIDERS = {'deepseek-official': 'available', 'custom': 'available', 'broken': 'unknown'}

AMBIENT = {'DEEPSEEK_BASE_URL': 'https://ambient.invalid/anthropic',
           'DEEPSEEK_SEARCH_BASE_URL': 'https://ambient-search.invalid/anthropic/v1'}
DECLARED = 'https://declared.invalid/anthropic'
REAL_DSH = shutil.which('dsh')
REAL_PI = shutil.which('pi')


@pytest.fixture
def dsh_host(monkeypatch: pytest.MonkeyPatch):
    """Replace the owned ``dsh web`` service with a catalog-only host and return its calls."""
    from agent_swarm.dsh import service

    calls   = []
    catalog = {'value': CATALOG}

    class Host:
        """A controlled native host offering a catalog without a Session."""

        def __init__(self, executable: str, cwd: Path, environment: dict) -> None:
            """Record the launch settings the real service would receive."""
            calls.append({'executable': executable, 'cwd': str(cwd),
                          'DSH_HOME': environment.get('DSH_HOME')})

        def start(self) -> None:
            """Record the native host startup boundary."""
            calls.append('start')

        def rpc(self, method: str) -> dict:
            """Return the public catalog response shape, or fail like a native error."""
            calls.append(method)
            if isinstance(catalog['value'], Exception):
                raise catalog['value']
            return catalog['value']

        def close(self) -> None:
            """Record ownership cleanup, also after a failed query."""
            calls.append('close')

    monkeypatch.setattr(service, 'DshService', Host)
    return calls, catalog


@pytest.fixture
def native(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Install one controlled Runtime client alone on PATH and return its record reader."""
    bin_directory = tmp_path / 'bin'
    bin_directory.mkdir()
    log = tmp_path / 'native.jsonl'
    monkeypatch.setenv('PATH', str(bin_directory))
    monkeypatch.setenv('HOME', str(tmp_path / 'user'))
    monkeypatch.setenv('FAKE_LOG', str(log))
    monkeypatch.setenv('FAKE_SECRET', SECRET)
    monkeypatch.setenv('FAKE_CATALOG', json.dumps(CATALOG))
    for name in ('CODEX_HOME', 'CLAUDE_CONFIG_DIR', 'PI_CODING_AGENT_DIR', 'DSH_HOME'):
        monkeypatch.delenv(name, raising=False)

    def install(runtime: str) -> Path:
        """Write the runtime's controlled executable."""
        script = bin_directory / runtime
        script.write_text({'codex': CODEX, 'claude': CLAUDE, 'pi': PI, 'dsh': DSH}[runtime])
        script.chmod(0o755)
        return script

    def records() -> list[dict]:
        """Return everything the controlled client recorded, in order."""
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    return install, records


def test_codex_reads_configuration_and_every_catalog_page(native, tmp_path: Path) -> None:
    """The selected home reaches app-server; no thread or turn is requested."""
    install, records = native
    install('codex')
    home = tmp_path / 'codex-home'
    home.mkdir()

    result = discover_models({'runtime': 'codex', 'home': str(home)})

    assert result == {'runtime': 'codex', 'status': 'available', 'message': AVAILABLE, 'models': [
        {'id': 'gpt-a', 'alias': 'GPT A', 'provider': 'controlled-provider',
         'supported_efforts': ['low', 'high']},
        {'id': 'gpt-b', 'alias': 'gpt-b', 'provider': 'controlled-provider', 'supported_efforts': []},
    ]}
    start, *calls = records()
    assert start['argv'] == ['app-server', '--listen', 'stdio://']
    assert start['home']['CODEX_HOME'] == str(home)
    assert Path(start['cwd']).name.startswith('agents-models-')
    assert [call['method'] for call in calls] == [
        'initialize', 'initialized', 'config/read', 'model/list', 'model/list',
    ]


def test_claude_uses_only_the_initialize_catalog(native, tmp_path: Path) -> None:
    """Claude runs restricted, without tools or MCP servers, and receives no user input."""
    install, records = native
    install('claude')

    result = discover_models({'runtime': 'claude', 'home': str(tmp_path / 'claude-home')})

    assert result == {'runtime': 'claude', 'status': 'available', 'message': AVAILABLE, 'models': [
        {'id': 'opus', 'alias': 'Opus', 'provider': 'anthropic', 'supported_efforts': ['low', 'high', 'max']},
        {'id': 'haiku', 'alias': 'haiku', 'provider': 'anthropic', 'supported_efforts': None},
    ]}
    start, stdin = records()
    assert start['home']['CLAUDE_CONFIG_DIR'] == str(tmp_path / 'claude-home')
    for flag in ('--restricted', '--strict-mcp-config'):
        assert flag in start['argv']
    assert start['argv'][start['argv'].index('--tools') + 1] == ''
    assert Path(start['cwd']).name.startswith('agents-models-')
    assert stdin['stdin']['request'] == {'subtype': 'initialize'}


def test_pi_lists_its_catalog_and_filters_the_connection_provider(native, tmp_path: Path) -> None:
    """Pi runs without session, extensions or context files; no key is passed."""
    install, records = native
    install('pi')
    home = str(tmp_path / 'pi-home')

    result = discover_models({'runtime': 'pi', 'home': home, 'api_key_env': 'PI_KEY'})
    selected = discover_models({'runtime': 'pi', 'home': home, 'provider': 'second'})

    assert result == {'runtime': 'pi', 'status': 'available', 'message': AVAILABLE, 'models': [
        {'id': 'model-a', 'alias': 'Model A', 'provider': 'first', 'supported_efforts': None},
        {'id': 'model-b', 'alias': 'model-b', 'provider': 'second', 'supported_efforts': None},
    ]}
    assert [model['id'] for model in selected['models']] == ['model-b']
    start = records()[0]
    assert start['home']['PI_CODING_AGENT_DIR'] != home
    assert start['argv'] == ['--mode', 'rpc', '--no-session', '--no-extensions', '--no-skills',
                             '--no-prompt-templates', '--no-themes', '--no-context-files']
    assert 'baseUrl' not in json.dumps(result)


def home_state(home: Path) -> dict:
    """Paths, sizes and modification times under a native home."""
    return {str(path.relative_to(home)): (path.stat().st_size, path.stat().st_mtime_ns) for path in home.rglob('*')}


def fill_pi_home(home: Path) -> None:
    """A native Pi home holding only fake data."""
    home.mkdir(parents=True)
    for name, content in (('auth.json', '{"first": {"type": "api_key", "key": "fake-stored-key"}}'),
                          ('models.json', '{"providers": {}}'), ('models-store.json', '{"stored": true}'),
                          ('settings.json', '{"packages": ["npm:agents-413-package-must-not-install"]}')):
        (home / name).write_text(content)


@pytest.mark.parametrize('source', ['connection', 'variable', 'default'])
def test_a_pi_listing_reads_the_resolved_home_from_a_private_directory(
    native, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str,
) -> None:
    """Pi never runs on the home: its stores, lock and packages land in a private directory."""
    install, records = native
    install('pi')
    home = {'connection': tmp_path / 'chosen', 'variable': tmp_path / 'from-variable',
            'default': tmp_path / 'user/.pi/agent'}[source]
    fill_pi_home(home)
    before = home_state(home)
    if source == 'connection':
        monkeypatch.setenv('PI_CODING_AGENT_DIR', str(tmp_path / 'not-this-one'))
    if source == 'variable':
        monkeypatch.setenv('PI_CODING_AGENT_DIR', str(home))

    result = discover_models({'runtime': 'pi', **({'home': str(home)} if source == 'connection' else {})})

    assert result['status'] == 'available'
    assert records()[1]['agent'] == {'auth.json': str((home / 'auth.json').resolve()),
                                     'models.json': str((home / 'models.json').resolve()),
                                     'models-store.json': None}
    assert records()[0]['home']['PI_CODING_AGENT_DIR'] != str(home)
    assert home_state(home) == before


def test_a_pi_home_without_a_login_gains_nothing(native, tmp_path: Path) -> None:
    """A missing home stays missing, and no link points at a login that does not exist."""
    install, records = native
    install('pi')
    home = tmp_path / 'absent'

    assert discover_models({'runtime': 'pi', 'home': str(home)})['status'] == 'available'
    assert records()[1]['agent'] == {}
    assert not home.exists()


@pytest.mark.skipif(REAL_PI is None, reason='Installed Pi is required for native catalog evidence.')
def test_installed_pi_lists_the_home_login_and_leaves_the_home_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real Pi: the fake login still authenticates its model; stores, lock and packages stay out of the home."""
    from agent_swarm.pi import pi_destination

    monkeypatch.setenv('HOME', str(tmp_path / 'user'))
    monkeypatch.setenv('PI_OFFLINE', '1')
    monkeypatch.delenv('PI_CODING_AGENT_DIR', raising=False)
    monkeypatch.delenv('FAKE_413_UNSET', raising=False)
    home = tmp_path / 'native-home'
    home.mkdir()
    (home / 'auth.json').write_text(json.dumps({'authed': {'type': 'api_key', 'key': 'fake-stored-key'}}))
    (home / 'models.json').write_text(json.dumps({'providers': {
        'authed': {'baseUrl': 'https://authed.invalid/v1', 'api': 'openai-completions',
                   'models': [{'id': 'authed-model'}]},
        'unauthed': {'baseUrl': 'https://unauthed.invalid/v1', 'api': 'openai-completions',
                     'apiKey': '$FAKE_413_UNSET', 'models': [{'id': 'unauthed-model'}]},
    }}))
    (home / 'settings.json').write_text(json.dumps({'packages': ['npm:agents-413-package-must-not-install']}))
    before = home_state(home)

    # Read-only: Pi locks auth.json where it found it, so a lock in the home would lose the login.
    home.chmod(0o555)
    try:
        assert pi_destination(REAL_PI, str(home), 'authed', 'authed-model') == 'authed.invalid'
        found = discover_models({'runtime': 'pi', 'home': str(home)})
    finally:
        home.chmod(0o755)

    assert found['status'] == 'available'
    assert {model['id'] for model in found['models'] if model['provider'] in ('authed', 'unauthed')} == {'authed-model'}
    assert home_state(home) == before


class RecordingHost:
    """Keep the launch facts of the owned ``dsh web``; nothing starts."""

    launches: list[dict] = []

    def __init__(self, executable: str, cwd: Path, environment: dict, **options: Path) -> None:
        """Read the patch now, because it lives in the query's temporary directory."""
        patch = options.get('profile_patch')
        self.launches.append({
            'executable': executable, 'cwd': cwd, 'environment': environment, 'options': set(options),
            'patch': yaml.load(patch.read_text(), Loader=_PatchLoader) if patch else None,
            'patch_in_cwd': bool(patch) and patch.parent == cwd,
        })

    def start(self) -> None:
        """Nothing runs."""

    def rpc(self, method: str) -> dict:
        """An empty catalog."""
        return {'groups': []}

    def close(self) -> None:
        """Nothing to stop."""


@pytest.fixture
def dsh_launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Ambient endpoints set, the service recorded, a stand-in ``dsh`` on PATH; returns the connection's home."""
    from agent_swarm.dsh import service

    for name, value in AMBIENT.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(service, 'DshService', RecordingHost)
    RecordingHost.launches = []
    home = tmp_path / 'dsh-home'
    home.mkdir()
    (home / 'settings.yml').write_text('kept: true\n')
    return home


@pytest.mark.parametrize(('declared', 'route'), [
    ({}, None),
    ({'base_url': DECLARED}, {'baseURL': DECLARED}),
    ({'api_key_env': 'FAKE_413_NAMED'}, {'apiKeyEnv': 'FAKE_413_NAMED'}),
    ({'base_url': DECLARED, 'api_key_env': 'FAKE_413_NAMED'}, {'baseURL': DECLARED, 'apiKeyEnv': 'FAKE_413_NAMED'}),
], ids=['nothing', 'endpoint', 'key', 'both'])
def test_a_dsh_listing_takes_its_endpoint_and_key_from_the_connection(
    native, dsh_launch: Path, declared: dict, route: dict | None,
) -> None:
    """The parent's endpoint variables are gone, and a private patch names what the connection declares."""
    native[0]('dsh')
    before = home_state(dsh_launch)

    result = discover_models({'runtime': 'dsh', 'home': str(dsh_launch), **declared})

    assert result['status'] == 'available'
    launch = RecordingHost.launches[0]
    assert [name for name in AMBIENT if name in launch['environment']] == []
    assert launch['environment']['DSH_HOME'] == str(dsh_launch)
    if route is None:
        assert launch['options'] == set()
    else:
        assert launch['options'] == {'profile_patch'}
        assert launch['patch_in_cwd'] is True
        assert launch['patch'] == [{'id': 'llm-deepseek', 'config': route}]
    assert home_state(dsh_launch) == before


@pytest.mark.skipif(REAL_DSH is None or shutil.which('node') is None,
                    reason='Installed DSH and Node are required for native endpoint evidence.')
@pytest.mark.parametrize('declared', [None, DECLARED], ids=['official', 'declared'])
def test_installed_dsh_applies_the_listing_route_to_its_row(
    dsh_launch: Path, tmp_path: Path, declared: str | None,
) -> None:
    """The installed DSH composes the patch into its own row and its resolver reaches only that endpoint."""
    connection = {'runtime': 'dsh', 'api_key_env': 'FAKE_413_NAMED', **({'base_url': declared} if declared else {})}
    discover_models(connection)
    launch = RecordingHost.launches[0]
    patch = tmp_path / 'listing.patch.yml'
    patch.write_text(yaml.safe_dump(launch['patch']))
    environment = {**launch['environment'], 'DSH_HOME': str(tmp_path / 'dump-home')}

    dumped = subprocess.run([REAL_DSH, '--profile', 'web', '--patch', str(patch), '--dump-config'],
                            cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=60)
    assert dumped.returncode == 0, dumped.stderr
    row = next(row for row in yaml.load(dumped.stdout, Loader=_PatchLoader) if row.get('id') == 'llm-deepseek')
    assert row['config']['apiKeyEnv'] == 'FAKE_413_NAMED'

    def resolved(launch_environment: dict) -> str:
        result = subprocess.run(['node', str(ROOT / 'tests/fixtures/dsh_resolve_endpoint.mjs'),
                                 str(Path(REAL_DSH).resolve().parent.parent), json.dumps(row['config'])],
                                cwd=tmp_path, env=launch_environment, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    assert resolved(environment) == (declared or 'https://api.deepseek.com/anthropic')
    # This DSH does honour the variable when it is left in: what the removal prevents.
    assert resolved({**environment, **AMBIENT}) == (declared or AMBIENT['DEEPSEEK_BASE_URL'])


@pytest.mark.skipif(not CAN_BIND, reason='loopback port binding is not permitted here')
def test_dsh_reads_the_host_catalog_over_its_web_service(native, tmp_path: Path) -> None:
    """A controlled ``dsh web`` serves only session/modelCatalog behind its launch cookie."""
    install, records = native
    install('dsh')
    home = str(tmp_path / 'dsh-home')

    result = discover_models({'runtime': 'dsh', 'home': home})

    assert result == {'runtime': 'dsh', 'status': 'available', 'message': AVAILABLE,
                      'models': DSH_MODELS, 'provider_status': DSH_PROVIDERS}
    start, call = records()
    assert start['argv'] == ['web', '--no-open', '--port', '0']
    assert start['home']['DSH_HOME'] == home
    assert call == {'method': 'session/modelCatalog', 'cookie': 'session=controlled'}
    assert SECRET not in json.dumps(result)


def test_dsh_projects_the_host_catalog_and_provider_status(native, dsh_host, tmp_path: Path) -> None:
    """Only the catalog method is called; failed providers stay unknown without diagnostics."""
    install, _ = native
    install('dsh')
    calls, _ = dsh_host
    home = str(tmp_path / 'dsh-home')

    result   = discover_models({'runtime': 'dsh', 'home': home})
    selected = discover_models({'runtime': 'dsh', 'home': home, 'provider': 'custom'})

    assert result == {'runtime': 'dsh', 'status': 'available', 'message': AVAILABLE,
                      'models': DSH_MODELS, 'provider_status': DSH_PROVIDERS}
    assert [model['id'] for model in selected['models']] == ['custom-model']
    assert calls[0]['DSH_HOME'] == home and Path(calls[0]['executable']).name == 'dsh'
    assert Path(calls[0]['cwd']).name.startswith('agents-models-')
    assert calls[1:4] == ['start', 'session/modelCatalog', 'close']
    assert SECRET not in json.dumps(result)


def test_dsh_with_every_provider_failing_is_unknown(native, dsh_host) -> None:
    """An empty catalog with failures is not reported as an available empty list."""
    install, _ = native
    install('dsh')
    _, catalog = dsh_host
    catalog['value'] = {'groups': [], 'failures': [{'id': 'broken', 'message': SECRET}]}

    result = discover_models({'runtime': 'dsh'})

    assert result['status'] == 'unknown' and result['models'] == []
    assert result['provider_status'] == {'broken': 'unknown'}
    assert SECRET not in json.dumps(result)


def test_dsh_query_failure_still_closes_the_owned_service(native, dsh_host) -> None:
    """A native catalog error leaves no service running and discloses nothing."""
    install, _ = native
    install('dsh')
    calls, catalog = dsh_host
    catalog['value'] = RuntimeError('failure carrying ' + SECRET)

    result = discover_models({'runtime': 'dsh'})

    assert result == {'runtime': 'dsh', 'status': 'unknown', 'models': [], 'message': UNKNOWN}
    assert calls[1:] == ['start', 'session/modelCatalog', 'close']


@pytest.mark.parametrize('runtime', ['claude', 'codex', 'pi', 'dsh'])
def test_native_failure_is_unknown_without_secrets(
    native, monkeypatch: pytest.MonkeyPatch, runtime: str,
) -> None:
    """A failing client's output, which may hold credentials, never reaches the result."""
    install, records = native
    install(runtime)
    monkeypatch.setenv('FAKE_FAIL', '1')
    monkeypatch.setenv('PI_KEY', SECRET)

    result = discover_models({'runtime': runtime, 'api_key_env': 'PI_KEY'})

    assert result == {'runtime': runtime, 'status': 'unknown', 'models': [], 'message': UNKNOWN}
    assert SECRET not in json.dumps(result)
    assert records(), 'the controlled client was started'


@pytest.mark.parametrize('runtime', ['claude', 'codex', 'pi', 'dsh'])
def test_missing_client_is_unknown(native, runtime: str) -> None:
    """A Runtime that is not installed reports unknown, not an empty available catalog."""
    result = discover_models({'runtime': runtime})

    assert result == {'runtime': runtime, 'status': 'unknown', 'models': [], 'message': UNKNOWN}


@pytest.mark.parametrize(('runtime', 'provider'), [
    ('claude', 'anthropic'), ('codex', 'openai'), ('pi', None), ('dsh', None),
])
def test_configured_models_are_the_candidates_without_a_query(
    native, runtime: str, provider: str | None,
) -> None:
    """A configured list needs no installed client and keeps declared efforts."""
    install, records = native
    install(runtime)

    result = discover_models({'runtime': runtime, 'models': [
        'plain', {'id': 'rich', 'alias': 'Rich', 'supported_efforts': ['high']},
        {'id': 'routed', 'provider': 'explicit'},
    ]})
    routed = discover_models({'runtime': runtime, 'provider': 'named', 'models': ['plain']})

    assert result['status'] == 'available' and result['runtime'] == runtime
    assert result['models'] == [
        {'id': 'plain', 'alias': 'plain', 'provider': provider, 'supported_efforts': None},
        {'id': 'rich', 'alias': 'Rich', 'provider': provider, 'supported_efforts': ['high']},
        {'id': 'routed', 'alias': 'routed', 'provider': 'explicit', 'supported_efforts': None},
    ]
    assert routed['models'][0]['provider'] == 'named'
    assert 'not queried' in result['message']
    assert records() == []


@pytest.mark.parametrize('connection', [
    {'runtime': 'unknown'}, {}, {'runtime': 'codex', 'models': 'gpt'},
    {'runtime': 'codex', 'models': [{'alias': 'no id'}]},
    {'runtime': 'codex', 'models': [{'id': 'x', 'api_key': SECRET}]},
])
def test_invalid_connections_are_configuration_errors(connection: dict) -> None:
    """An unsupported Runtime or malformed model list is refused without echoing values."""
    with pytest.raises(ValueError) as error:
        discover_models(connection)

    assert SECRET not in str(error.value)


def test_discovery_inside_a_running_event_loop(native) -> None:
    """A caller already running asyncio (as hosts do) still gets the Codex catalog."""
    import asyncio

    install, _ = native
    install('codex')

    async def caller() -> dict:
        """Call the synchronous function from inside a loop."""
        return discover_models({'runtime': 'codex'})

    assert asyncio.run(caller())['status'] == 'available'


@pytest.mark.parametrize('runtime', ['claude', 'codex', 'pi', 'dsh'])
def test_graphtraj_discovery_keeps_its_document(
    native, dsh_host, tmp_path: Path, runtime: str,
) -> None:
    """GraphTraj's connection discovery projects the agents result onto its existing shape."""
    from graphtraj.runtimes.model_discovery import discover_models as graphtraj_discover

    install, _ = native
    install(runtime)
    entry = {'runtime': runtime, 'home': str(tmp_path / 'home'), 'providers': {
        'manual': {'models': {'m': {'id': 'manual-only', 'source': 'manual'}}},
    }}

    result = graphtraj_discover(entry)
    agents = discover_models({'runtime': runtime, 'home': entry['home']})

    expected = {'runtime': runtime, 'source': 'native', 'account_access': 'unknown',
                'models': [{**model, 'source': 'native'} for model in agents['models']],
                'supported_efforts': 'unknown', 'catalog_scope': 'runtime',
                'status': 'available', 'message': AVAILABLE}
    if runtime == 'dsh':
        expected['provider_status'] = agents['provider_status']
    assert result == expected
    # Manual catalog entries never replace the native query.
    assert 'manual-only' not in json.dumps(result)


def test_graphtraj_discovery_failure_keeps_its_document(native) -> None:
    """A failed native query keeps GraphTraj's fixed nonsecret failure document."""
    from graphtraj.runtimes.model_discovery import discover_models as graphtraj_discover

    assert graphtraj_discover({'runtime': 'codex', 'providers': {}}) == {
        'runtime': 'codex', 'source': 'native', 'account_access': 'unknown', 'models': [],
        'supported_efforts': 'unknown', 'catalog_scope': 'runtime', 'status': 'unknown',
        'message': UNKNOWN,
    }
