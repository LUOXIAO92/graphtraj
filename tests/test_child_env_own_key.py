"""A child Agent receives its own connection's key and no other credential (Task 433).

Every test goes through a Runtime's actual launch code: Pi's and DSH's
``prepare_launch``, Claude's ``_prepare``, and for Codex a real ``run`` against an
executable that records the environment it was started with and exits. All values are
fake; the autouse fixture removes every credential-class variable of the running shell.
"""

import inspect
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading

import pytest

from agent_swarm import AgentControl, AgentsResult, Caller, bind
from agent_swarm.child_env import child_environment, is_credential_name
from agent_swarm.claude import ClaudeDriver
from agent_swarm.claude.execution import ClaudeExecution
from agent_swarm.codex.managed_session import CodexManagedExecution
from agent_swarm.config import read_connections
from agent_swarm.connection import agents_connection
from agent_swarm.dsh.execution import DshExecution
from agent_swarm.pi.driver import selected as pi_selected
from agent_swarm.pi.execution import PiExecution
from agent_swarm.process import authenticate_process
from graphtraj.configuration.project_roles import parse_inline_role
from graphtraj.configuration.runtime_connections import resolve_connection, validate_catalog
from graphtraj.configuration.role_definitions import resolve_child_role
from graphtraj.runtimes.runtime_adapter import select_runtime_adapter

from test_claude_review import native  # noqa: F401  (fixture)
from test_codex_app_server import peer  # noqa: F401  (fixture)
from test_pi_runtime import context as pi_role_context, pi_environment  # noqa: F401  (fixture)


# Names seen on real machines; test_rule pins each one.
MUST_DROP = ('DEEPSEEK_API_KEY', 'GEMINI_API_KEY', 'ALI_BAILIAN_API_KEY', 'OPEN_ROUTER_API_KEY', 'OPENCODE_API_KEY',
             'HF_TOKEN', 'GH_TOKEN', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN', 'PGPASSWORD',
             'CLOUDSDK_PROXY_PASSWORD', 'GOOGLE_APPLICATION_CREDENTIALS', 'APIKEY', 'my_api_key')
MUST_KEEP = ('GIT_CONFIG_KEY_0', 'GIT_CONFIG_KEY_3', 'GIT_CONFIG_COUNT', 'TOKENIZERS_PARALLELISM', 'SSH_AUTH_SOCK',
             'PATH', 'HOME', 'PWD', 'CLAUDE_CODE_MAX_OUTPUT_TOKENS', 'MAX_THINKING_TOKENS', 'KEYCHAIN_PROFILE')

OWN, UNRELATED, DECLARED, REVIEW = 'CHILD_KEY', 'UNRELATED_API_KEY', 'DECLARED_TOKEN', 'REVIEW_KEY'
REVIEWER = {'name': 'checker', 'base_url': 'https://review.invalid/v1', 'model': 'm', 'api_key_env': REVIEW}


@pytest.fixture(autouse=True)
def fake_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Hold only fake credentials, whatever the running shell exports."""
    for name in tuple(os.environ):
        if is_credential_name(name):
            monkeypatch.delenv(name)
    for name in (OWN, UNRELATED, DECLARED, REVIEW, 'HF_TOKEN', 'AWS_SECRET_ACCESS_KEY', 'PGPASSWORD'):
        monkeypatch.setenv(name, 'fake-' + name)
    monkeypatch.setenv('GIT_CONFIG_COUNT', '1')
    monkeypatch.setenv('GIT_CONFIG_KEY_0', 'core.sshCommand')
    monkeypatch.setenv('TOKENIZERS_PARALLELISM', 'false')
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'codex-home'))


def assert_only_own_credentials(environment: dict, *own: str) -> None:
    """Assert the child's credential-class names are exactly ``own`` and ordinary names kept.

    Only names appear in a failure message, so the assertion never prints a value.
    """
    names = sorted(name for name in environment if is_credential_name(name))
    assert names == sorted(own)
    home, git, tokenizers = environment.get('HOME'), environment.get('GIT_CONFIG_KEY_0'), environment.get('TOKENIZERS_PARALLELISM')
    assert (home, git, tokenizers) == (os.environ.get('HOME'), 'core.sshCommand', 'false')
    assert environment.get('PATH')


def launch_pi(tmp_path: Path, *, session: str | None = None, **fields) -> dict:
    """Return the environment of a real Pi launch of the controlled peer."""
    worktree = tmp_path / 'worktree'
    worktree.mkdir(exist_ok=True)
    request = {'executable': _which('pi'), 'provider': 'deepseek', 'model': 'deepseek-flash',
               'worktree_path': str(worktree), 'agent_dir': os.environ['PI_TEST_AGENT'], 'instructions': 'Be brief.',
               'sandbox_python': sys.executable, 'sandbox_path': os.environ['PATH'],
               'worktree_access': 'read', 'provider_domain': 'api.deepseek.com',
               'native_directory': str(tmp_path / 'native'), **fields}
    directory = tmp_path / 'one'
    directory.mkdir(exist_ok=True)
    if session is not None:
        (tmp_path / 'native').mkdir(exist_ok=True)
        (tmp_path / 'native/session.jsonl').write_text('')
    turn = PiExecution(request, 'unused', directory, lambda *a: None, lambda *a: None, tmp_path / 'trace.jsonl', session)
    # A reviewed Pi needs the agents extension, which is loaded only with a connection.
    return turn.prepare_launch(str(tmp_path / 'channel') if 'review' in fields else None)[1]


def _which(name: str) -> str:
    """Return the controlled peer put on PATH by a fixture."""
    import shutil

    return shutil.which(name)


def launch_dsh(tmp_path: Path, *, session: str | None = None, **fields) -> dict:
    """Return the environment of a real DSH launch."""
    request = {'executable': 'dsh', 'package': str(tmp_path / 'package.json'), 'worktree_path': str(tmp_path),
               'provider': 'deepseek-official', 'model': 'deepseek-flash', 'reasoning_effort': None,
               'sandbox': 'read-only', 'instructions': '', **fields}
    return DshExecution(request, 'unused', tmp_path, lambda *a: None, lambda *a: None,
                        tmp_path / 'trace.jsonl', session).prepare_launch()


def launch_claude(tmp_path: Path, *, session: str | None = None, **fields) -> dict:
    """Return the environment of a real Claude launch of the controlled peer."""
    pass_env, review = fields.pop('pass_env', None), fields.pop('review', None)
    driver   = ClaudeDriver(tmp_path, {'model': 'claude-opus-5-5', **fields})
    settings = driver.prepare('claude', Caller('h', None))
    settings = {**settings, **({'pass_env': pass_env} if pass_env else {}), **({'review': review} if review else {})}
    turn = ClaudeExecution(settings, 'x', tmp_path, lambda *a: None, lambda *a: None, tmp_path / 't', session)
    return turn._prepare(None)[1]


def recording_codex(tmp_path: Path) -> tuple[Path, Path]:
    """Return an executable that records its environment's names and exits, and the record."""
    record = tmp_path / 'codex-environment'
    executable = tmp_path / 'codex-recorder'
    executable.write_text(f'#!/bin/sh\nenv > {record}\nexit 3\n')
    executable.chmod(executable.stat().st_mode | stat.S_IEXEC)
    return executable, record


def codex_request(tmp_path: Path, executable: Path, config: dict | None = None, **fields) -> dict:
    """Return a retained launch request naming the recording executable."""
    return {'arguments': [str(executable), 'exec'], 'worktree_path': str(tmp_path),
            'session_parameters': {'cwd': str(tmp_path), 'model': 'm', 'developerInstructions': '',
                                   'config': {'default_permissions': 'p', 'permissions': {'p': {'filesystem': {}}},
                                              **(config or {})}}, **fields}


def launch_codex(tmp_path: Path, *, session: str | None = None, connection: dict | None = None,
                 review: dict | None = None, config: dict | None = None, **fields) -> dict:
    """Run a real Codex owner to the point its service starts; return what the service received."""
    executable, record = recording_codex(tmp_path)
    worker = CodexManagedExecution(codex_request(tmp_path, executable, config, **fields), 'unused', tmp_path,
                                   lambda *a: None, {}, tmp_path / 'trace.jsonl', session,
                                   connection=connection, review=review)
    with pytest.raises(Exception):
        worker.run()
    return dict(line.split('=', 1) for line in record.read_text().splitlines() if '=' in line)


@pytest.fixture
def pi_agent(pi_environment: dict, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """Point launch_pi at the controlled peer's native directory."""
    monkeypatch.setenv('PI_TEST_AGENT', pi_environment['agent_dir'])


# --- The rule ------------------------------------------------------------------------------


@pytest.mark.parametrize('name', MUST_DROP)
def test_a_credential_name_is_dropped(name: str) -> None:
    """The names the Worldline's leak and this Task's decision list are credentials."""
    assert is_credential_name(name)
    assert child_environment({name: 'fake'}) == {}


@pytest.mark.parametrize('name', MUST_KEEP)
def test_an_ordinary_name_stays(name: str) -> None:
    """A substring rule would break Git's indexed configuration and tokenizer settings."""
    assert not is_credential_name(name)
    assert child_environment({name: 'value'}) == {name: 'value'}


def test_order_of_precedence() -> None:
    """Own keys and declared names return; the reviewer's key leaves last, unless it is the connection's."""
    parent = {'PATH': '/bin', 'A_KEY': 'a', 'B_KEY': 'b', 'R_KEY': 'r', 'D_TOKEN': 'd', 'E_KEY': 'e'}

    assert child_environment(parent, api_key_env='A_KEY', defaults=('E_KEY',), declared=('D_TOKEN', 'MISSING_KEY'),
                             review_key='R_KEY') == {'PATH': '/bin', 'A_KEY': 'a', 'E_KEY': 'e', 'D_TOKEN': 'd'}
    assert 'R_KEY' not in child_environment(parent, api_key_env='A_KEY', declared=('R_KEY',), review_key='R_KEY')
    assert 'R_KEY' not in child_environment(parent, defaults=('R_KEY',), review_key='R_KEY')
    assert child_environment(parent, api_key_env='R_KEY', review_key='R_KEY') == {'PATH': '/bin', 'R_KEY': 'r'}
    assert parent['B_KEY'] == 'b' and len(parent) == 6


# --- Each Runtime's launch path ---------------------------------------------------------------


@pytest.mark.parametrize('session', [None, 'resumed-session'])
def test_pi_named_connection(tmp_path: Path, pi_agent: None, session: str | None) -> None:
    """Pi: named key and declared name in, unrelated out, on a first launch and on resume."""
    environment = launch_pi(tmp_path, session=session, api_key_env=OWN, pass_env=[DECLARED])
    assert_only_own_credentials(environment, OWN, DECLARED)
    assert environment[OWN] == 'fake-' + OWN


def test_pi_reviewers_key_withheld_even_when_declared(tmp_path: Path, pi_agent: None) -> None:
    """Pi: declaring the reviewer's key does not give it to the child it judges."""
    environment = launch_pi(tmp_path, api_key_env=OWN, pass_env=[REVIEW], review=REVIEWER)
    assert_only_own_credentials(environment, OWN)


def test_pi_connection_may_name_its_reviewers_key(tmp_path: Path, pi_agent: None) -> None:
    """Pi: naming the reviewer's key as the connection's own deliberately shares it."""
    assert_only_own_credentials(launch_pi(tmp_path, api_key_env=REVIEW, review=REVIEWER), REVIEW)


def test_pi_default_key_is_the_one_pi_asks_for(tmp_path: Path, pi_agent: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pi with no api_key_env: Pi's own listing decides, so only the variable it needs comes through."""
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fake-default')
    monkeypatch.setenv('PI_FIXTURE_LISTING_NEEDS', 'DEEPSEEK_API_KEY')
    assert_only_own_credentials(launch_pi(tmp_path), 'DEEPSEEK_API_KEY')


def test_pi_default_key_named_by_nothing_but_pi(tmp_path: Path, pi_agent: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """A variable unrelated to the provider's name, say from models.json, is still found by asking."""
    monkeypatch.setenv('PI_FIXTURE_LISTING_NEEDS', 'PGPASSWORD')
    assert_only_own_credentials(launch_pi(tmp_path), 'PGPASSWORD')


def test_pi_native_login_needs_no_variable(tmp_path: Path, pi_agent: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pi logged in natively: its login file stays available and no variable is handed over."""
    agent = Path(os.environ['PI_TEST_AGENT'])
    agent.mkdir(exist_ok=True)
    (agent / 'auth.json').write_text('{}')
    monkeypatch.setenv('PI_FIXTURE_LISTING_NEEDS', 'DEEPSEEK_API_KEY')
    environment = launch_pi(tmp_path)
    assert_only_own_credentials(environment)
    assert (Path(environment['PI_CODING_AGENT_DIR']) / 'auth.json').is_symlink()


def test_pi_with_unknown_auth_hands_over_nothing(tmp_path: Path, pi_agent: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """When Pi offers the model under no combination, uncertainty hands over no key."""
    monkeypatch.setenv('PI_FIXTURE_LISTING_NEEDS', 'NOT_SET_ANYWHERE_KEY')
    assert_only_own_credentials(launch_pi(tmp_path))


@pytest.mark.parametrize('session', [None, 'resumed-session'])
def test_dsh_named_connection(tmp_path: Path, session: str | None) -> None:
    """DSH: named key and declared name in, unrelated out, on a first launch and on resume."""
    environment = launch_dsh(tmp_path, session=session, api_key_env=OWN, pass_env=[DECLARED])
    assert_only_own_credentials(environment, OWN, DECLARED)


def test_dsh_default_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """DSH with no api_key_env: DSH's own default variable, and no other."""
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fake-default')
    assert_only_own_credentials(launch_dsh(tmp_path), 'DEEPSEEK_API_KEY')


def test_dsh_login_files_need_no_variable(tmp_path: Path) -> None:
    """DSH with only its own login files gets no variable; its home is the connection's."""
    assert_only_own_credentials(launch_dsh(tmp_path, runtime_home=str(tmp_path / 'dsh-home')))


def test_dsh_official_search_beside_another_key_is_declared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """DSH's search key on a connection naming another key arrives only when declared (PUBLIC_API section 2)."""
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fake-search')
    assert_only_own_credentials(launch_dsh(tmp_path, api_key_env=OWN), OWN)
    assert_only_own_credentials(launch_dsh(tmp_path, api_key_env=OWN, pass_env=['DEEPSEEK_API_KEY']),
                                OWN, 'DEEPSEEK_API_KEY')


def test_dsh_reviewers_key_withheld_even_when_declared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """DSH: declaring the reviewer's key or having it as the default does not hand it over."""
    environment = launch_dsh(tmp_path, api_key_env=OWN, pass_env=[REVIEW], review=REVIEWER)
    assert_only_own_credentials(environment, OWN)
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fake-default')
    default = launch_dsh(tmp_path, review={**REVIEWER, 'api_key_env': 'DEEPSEEK_API_KEY'})
    assert_only_own_credentials(default)


@pytest.mark.parametrize('session', [None, str(__import__('uuid').uuid4())])
def test_claude_named_connection(tmp_path: Path, native: None, session: str | None) -> None:  # noqa: F811
    """Claude: named key as ANTHROPIC_API_KEY and declared name in, unrelated out, also on resume."""
    environment = launch_claude(tmp_path, session=session, api_key_env=OWN, pass_env=[DECLARED])
    assert_only_own_credentials(environment, OWN, 'ANTHROPIC_API_KEY', DECLARED)
    assert environment['ANTHROPIC_API_KEY'] == 'fake-' + OWN


def test_claude_login_variables_stay_without_a_named_key(tmp_path: Path, native: None,  # noqa: F811
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """Claude with no api_key_env: its three login variables stay; anything else does not."""
    for name in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_OAUTH_TOKEN'):
        monkeypatch.setenv(name, 'fake')
    assert_only_own_credentials(launch_claude(tmp_path), 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN',
                                'CLAUDE_CODE_OAUTH_TOKEN')


def test_claude_native_login_needs_no_variable(tmp_path: Path, native: None) -> None:  # noqa: F811
    """Claude logged in through its keychain or home: no credential-class variable is added."""
    assert_only_own_credentials(launch_claude(tmp_path))


@pytest.mark.parametrize(('mode', 'names'), [
    ('CLAUDE_CODE_USE_BEDROCK', ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN')),
    ('CLAUDE_CODE_USE_VERTEX', ('GOOGLE_APPLICATION_CREDENTIALS',)),
    ('CLAUDE_CODE_USE_FOUNDRY', ('ANTHROPIC_FOUNDRY_API_KEY',)),
])
def test_claude_provider_mode_keeps_its_credentials(tmp_path: Path, native: None,  # noqa: F811
                                                    monkeypatch: pytest.MonkeyPatch, mode: str, names: tuple) -> None:
    """A selected Bedrock, Vertex or Foundry mode keeps that provider's login, and only then."""
    monkeypatch.delenv('AWS_SECRET_ACCESS_KEY')
    for name in names:
        monkeypatch.setenv(name, 'fake')
    assert_only_own_credentials(launch_claude(tmp_path))
    monkeypatch.setenv(mode, '1')
    assert_only_own_credentials(launch_claude(tmp_path), *names)


def test_claude_reviewers_key_withheld_even_when_declared(tmp_path: Path, native: None) -> None:  # noqa: F811
    """Claude: declaring the reviewer's key does not give it to the child it judges."""
    environment = launch_claude(tmp_path, api_key_env=OWN, pass_env=[REVIEW], review=REVIEWER)
    assert_only_own_credentials(environment, OWN, 'ANTHROPIC_API_KEY')


@pytest.mark.parametrize('session', [None, 'resumed-session'])
def test_codex_named_connection_with_its_home(tmp_path: Path, session: str | None) -> None:
    """Codex with a home: named key under its name and declared name in, also on resume."""
    environment = launch_codex(tmp_path, session=session, pass_env=[DECLARED],
                               connection={'api_key_env': OWN, 'runtime_home': str(tmp_path / 'home')})
    assert_only_own_credentials(environment, OWN, DECLARED)
    assert environment['CODEX_HOME'] == str(tmp_path / 'home')


def test_codex_named_connection_with_an_endpoint(tmp_path: Path) -> None:
    """Codex with an endpoint: the key arrives as OPENAI_API_KEY, the existing routing."""
    environment = launch_codex(tmp_path, connection={'api_key_env': OWN, 'base_url': 'https://gateway.invalid/v1'})
    assert_only_own_credentials(environment, OWN, 'OPENAI_API_KEY')
    assert environment['OPENAI_API_KEY'] == 'fake-' + OWN


def test_codex_defaults_without_a_named_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Codex with no api_key_env: its own default variables stay; a native login needs none."""
    assert_only_own_credentials(launch_codex(tmp_path))
    monkeypatch.setenv('OPENAI_API_KEY', 'fake')
    monkeypatch.setenv('CODEX_API_KEY', 'fake')
    assert_only_own_credentials(launch_codex(tmp_path), 'OPENAI_API_KEY', 'CODEX_API_KEY')


def test_codex_native_provider_env_key(tmp_path: Path) -> None:
    """Codex: the env_key of the selected provider in the home's config.toml stays."""
    home = Path(os.environ['CODEX_HOME'])
    home.mkdir()
    (home / 'config.toml').write_text(f'model_provider = "work"\n[model_providers.work]\nenv_key = "{OWN}"\n')
    assert_only_own_credentials(launch_codex(tmp_path), OWN)
    assert_only_own_credentials(launch_codex(tmp_path, config={'model_provider': 'other'}))


def test_codex_reviewers_key_withheld_even_when_declared(tmp_path: Path) -> None:
    """Codex: declaring the reviewer's key does not hand it over; naming it as the connection's does."""
    assert_only_own_credentials(launch_codex(tmp_path, pass_env=[REVIEW], review=REVIEWER))
    assert_only_own_credentials(
        launch_codex(tmp_path, review=REVIEWER, connection={'api_key_env': REVIEW, 'runtime_home': str(tmp_path / 'h')}),
        REVIEW)


# --- The declaration: user-owned configuration only --------------------------------------------


class RecordingDriver:
    """Record what control retains for a child, without starting anything."""

    def __init__(self) -> None:
        """Start with no recorded settings."""
        self.settings = None
        self.done = threading.Event()

    def prepare(self, runtime: str, caller: Caller, *, selection=None, workspace=None) -> dict:
        """Return settings of the shape a real driver returns."""
        return {'adapter_request': {}}

    def start(self, run) -> None:
        """Keep the settings the Runtime would receive and end the execution."""
        self.settings = dict(run.settings)
        run.events.finished('completed', last_message='')
        self.done.set()


CONFIG_NO_CONNECTION = 'pass_env: [DECLARED_TOKEN]\n'
CONFIG_CONNECTION = (
    'pass_env: [UNRELATED_API_KEY]\n'
    'connections:\n'
    '  work:\n'
    '    runtime: pi\n'
    '    pass_env: [DECLARED_TOKEN]\n'
)


@pytest.mark.parametrize(('config', 'expected'), [
    ('', None), (CONFIG_NO_CONNECTION, ['DECLARED_TOKEN']), (CONFIG_CONNECTION, ['DECLARED_TOKEN']),
])
def test_control_retains_the_files_declaration(tmp_path: Path, config: str, expected: list | None) -> None:
    """A connection's list applies to it; a child with no connection takes the file's list."""
    (tmp_path / 'config.yml').write_text(config)
    driver = RecordingDriver()
    control = AgentControl(tmp_path, {'pi': driver})
    document = bind(control, Caller('h', None))({'action': 'create', 'runtime': 'pi', 'instruction': 'x'}).document

    assert driver.done.wait(5), document
    assert driver.settings.get('pass_env') == expected


def test_a_model_cannot_ask_for_a_key(tmp_path: Path) -> None:
    """``create`` has no such argument and the tool refuses one, so a child cannot request a variable."""
    assert 'pass_env' not in inspect.signature(AgentControl.create).parameters
    driver = RecordingDriver()
    result = bind(AgentControl(tmp_path, {'pi': driver}), Caller('h', None))(
        {'action': 'create', 'runtime': 'pi', 'instruction': 'x', 'pass_env': [UNRELATED]})

    assert result.document['error'] == {'code': 'invalid-input', 'message': 'request.pass_env: unexpected parameter'}
    assert driver.settings is None


@pytest.mark.parametrize('value', ['DECLARED_TOKEN', '[]', '[sk-not-a-name]', '[1]'])
def test_the_declaration_is_validated(tmp_path: Path, value: str) -> None:
    """A wrong shape, or anything but a variable's name, fails with the file and line."""
    (tmp_path / 'config.yml').write_text(f'connections:\n  work:\n    runtime: pi\n    pass_env: {value}\n')
    with pytest.raises(ValueError, match=r'config\.yml:4: connections\.work\.pass_env'):
        read_connections(tmp_path)
    (tmp_path / 'config.yml').write_text(f'pass_env: {value}\n')
    with pytest.raises(ValueError, match=r'config\.yml:1: pass_env'):
        read_connections(tmp_path)


def test_read_connections_returns_the_names(tmp_path: Path) -> None:
    """Reading keeps names only; a file without the field looks as before."""
    (tmp_path / 'config.yml').write_text(CONFIG_CONNECTION)
    declared = read_connections(tmp_path)
    assert declared['pass_env'] == [UNRELATED]
    assert declared['connections']['work']['pass_env'] == [DECLARED]
    (tmp_path / 'config.yml').write_text('backfill_history: true\n')
    assert read_connections(tmp_path) == {'connections': {}, 'presets': {}}


# --- A grandchild: launched by the owner, from the owner's environment --------------------------


def test_a_childs_create_runs_in_the_owner_with_the_owners_environment(tmp_path: Path) -> None:
    """A child's process, holding neither key, reaches the owner; the owner holds both keys.

    The owner's call handler runs in this process, so control's key-presence check, model
    discovery and the launch all read this environment. That is why narrowing a child's
    environment cannot break a grandchild, and why a write child's Git variables never
    reach a read-only sibling or grandchild (Task 429's open question).
    """
    seen = {}
    child = None

    def call(request: dict) -> AgentsResult:
        """Record where the request is served."""
        seen.update(pid=os.getpid(), own=os.environ.get(OWN), git=os.environ.get('GIT_AUTHOR_NAME'))
        return AgentsResult({'action': request['action'], 'result': {}})

    script = ('import os, json\n'
              'from agent_swarm.connection import call_owner\n'
              'assert "CHILD_KEY" not in os.environ\n'
              'print(json.dumps(call_owner({"action": "execute", "feature": "status", "arguments": {}}).document))\n')
    environment = {'PATH': os.environ['PATH'], 'HOME': os.environ['HOME'],
                   'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src'),
                   'GIT_AUTHOR_NAME': 'write child', 'GIT_CONFIG_GLOBAL': os.devnull}

    with agents_connection(tmp_path / 'channel', call, lambda pid: authenticate_process(child, pid)) as address:
        child = subprocess.Popen([sys.executable, '-c', script], env={**environment, 'AGENT_SWARM_CONNECTION': address},
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        output, errors = child.communicate(timeout=20)

    assert child.returncode == 0, errors[-400:]
    assert 'error' not in output, output[-400:]
    assert seen == {'pid': os.getpid(), 'own': 'fake-' + OWN, 'git': None}


def test_a_grandchild_on_another_connection_gets_its_own_key(tmp_path: Path, pi_agent: None,  # noqa: F811
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """From one owner, a child on A gets A and a grandchild on B gets B; neither gets the other."""
    monkeypatch.setenv('A_KEY', 'fake-a')
    monkeypatch.setenv('B_KEY', 'fake-b')
    host = {'executable': _which('pi'), 'provider': 'deepseek', 'model': 'deepseek-flash', 'api_key_env': 'A_KEY',
            'agent_dir': os.environ['PI_TEST_AGENT']}
    grandchild = pi_selected(host, {'settings': {'runtime': 'pi', 'api_key_env': 'B_KEY'}})

    (tmp_path / 'child').mkdir()
    (tmp_path / 'grandchild').mkdir()
    assert_only_own_credentials(launch_pi(tmp_path / 'child', api_key_env='A_KEY'), 'A_KEY')
    assert_only_own_credentials(launch_pi(tmp_path / 'grandchild', api_key_env=grandchild['api_key_env']), 'B_KEY')


def test_a_read_only_pi_child_carries_no_git_setting_of_a_write_child(tmp_path: Path, pi_agent: None) -> None:  # noqa: F811
    """A write launch sets Git's variables in its own environment only, never in the owner's."""
    (tmp_path / 'write').mkdir()
    (tmp_path / 'read').mkdir()
    subprocess.run(['git', 'init', '-q', str(tmp_path / 'write' / 'worktree')], check=True)
    written = launch_pi(tmp_path / 'write', worktree_access='write', git_common_directory=str(tmp_path / 'write/worktree/.git'))
    assert written['GIT_CONFIG_GLOBAL'] == os.devnull
    assert 'GIT_CONFIG_GLOBAL' not in os.environ

    read = launch_pi(tmp_path / 'read')
    assert not {'GIT_CONFIG_GLOBAL', 'GIT_AUTHOR_NAME', 'GIT_COMMITTER_NAME'} & read.keys()


# --- GraphTraj's Runner members, through their own adapters --------------------------------------


def _member_role(root: Path, **fields) -> object:
    """Resolve an inline role the way a Runner dispatch does."""
    _, settings = parse_inline_role({'author': fields})
    return resolve_child_role('author', settings, root)


def test_runner_pi_member(tmp_path: Path, pi_environment: dict) -> None:  # noqa: F811
    """A Pi member: GraphTraj's execution over the same rule, with a role's declaration."""
    from graphtraj.runtimes.pi.managed_session import PiManagedExecution

    worktree = tmp_path / 'worktrees/research'
    worktree.mkdir(parents=True)
    _, prepared = pi_role_context(tmp_path, {'sandbox_python': pi_environment['sandbox_python'],
                                             'sandbox_path': pi_environment['sandbox_path'],
                                             'agent_dir': pi_environment['agent_dir']},
                                  api_key_env=OWN, pass_env=[DECLARED], worktree_access='read')
    request = prepared.launch_document()['adapter_request']
    directory = tmp_path / '.graphtraj/runner/sessions/one'
    directory.mkdir(parents=True)
    turn = PiManagedExecution(request, 'x', directory, lambda *a: None, lambda *a: None, tmp_path / 'trace.jsonl', None)
    assert_only_own_credentials(turn.prepare_launch(None)[1], OWN, DECLARED)


def test_runner_dsh_member(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A DSH member: an official role keeps its default key; the role's declaration comes through."""
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fake-default')
    executable = tmp_path / 'lib/node_modules/dsh/bin/dsh'
    executable.parent.mkdir(parents=True)
    executable.write_text('#!/bin/sh\n')
    executable.chmod(0o755)
    (executable.parent.parent / 'package.json').write_text('{"version": "0.2.2"}')
    tool = Path(sys.executable).parent / 'graphtraj-session'
    monkeypatch.setenv('PATH', f'{executable.parent}{os.pathsep}{tool.parent}{os.pathsep}{tmp_path}{os.pathsep}{os.environ["PATH"]}')
    (tmp_path / 'graphtraj-session').write_text('#!/bin/sh\n')
    (tmp_path / 'graphtraj-session').chmod(0o755)
    role = _member_role(tmp_path, runtime='dsh', model='deepseek-official/deepseek-flash', pass_env=[DECLARED])
    adapter = select_runtime_adapter('dsh')
    (tmp_path / 'work').mkdir()
    launch = adapter.preflight_runtime_context(
        harness_root=tmp_path, git_common_directory=tmp_path / '.git', role=role,
        worktree=tmp_path / 'work', evidence=tmp_path / 'state', requested_skills=(),
    ).finalize().launch_document()['adapter_request']
    turn = adapter.managed_execution(launch, 'x', tmp_path, lambda *_: None, {},
                                     trace_file=tmp_path / 'trace.jsonl', session_created=lambda *_: None)
    assert_only_own_credentials(turn.prepare_launch(), 'DEEPSEEK_API_KEY', DECLARED)


def test_runner_claude_member(tmp_path: Path, native: None) -> None:  # noqa: F811
    """A Claude member: GraphTraj's execution over the same rule, with a role's declaration."""
    from graphtraj.runtimes.claude.execution import ClaudeExecution as MemberExecution

    (tmp_path / 'worktrees/research').mkdir(parents=True)
    role = _member_role(tmp_path, runtime='claude', model='claude-opus-5-5', api_key_env=OWN, pass_env=[DECLARED])
    prepared = select_runtime_adapter('claude').preflight_runtime_context(
        harness_root=tmp_path, git_common_directory=tmp_path / 'worktrees/research/.git', role=role,
        worktree=tmp_path / 'worktrees/research', evidence=tmp_path / 'state', requested_skills=(),
    ).finalize()
    request = prepared.launch_document()['adapter_request']
    directory = tmp_path / '.graphtraj/runner/sessions/one'
    directory.mkdir(parents=True)
    turn = MemberExecution(request, 'x', directory, lambda *a: None, lambda *a: None, tmp_path / 't', None)
    assert_only_own_credentials(turn._prepare(None)[1], OWN, 'ANTHROPIC_API_KEY', DECLARED)


def test_runner_codex_member(tmp_path: Path, peer: Path) -> None:  # noqa: F811
    """A Codex member: the Runner's adapter retains the declaration and its owner applies the rule."""
    from graphtraj.runtimes.codex.codex_adapter import preflight_runtime_context

    record = tmp_path / 'codex-environment'
    executable = tmp_path / 'codex-recorder'
    # Answer the adapter's own checks with the peer; record the service's start and stop it.
    executable.write_text(f'#!/bin/sh\nif [ "$1" = app-server ]; then env > {record}; exit 3; fi\nexec {peer} "$@"\n')
    executable.chmod(0o755)
    role = _member_role(tmp_path, runtime='codex', model='m', api_key_env=OWN, pass_env=[DECLARED])
    document = preflight_runtime_context(
        runtime_store=tmp_path / '.codex', executable=executable, git_common_directory=tmp_path / 'git-common',
        role=role, worktree=tmp_path, evidence=tmp_path / 'evidence', requested_skills=(),
    ).finalize().launch_document()
    assert document['adapter_request']['pass_env'] == [DECLARED]

    worker = CodexManagedExecution(document['adapter_request'], 'x', tmp_path, lambda *a: None, {}, tmp_path / 't',
                                   connection=document['connection'])
    with pytest.raises(Exception):
        worker.run()
    environment = dict(line.split('=', 1) for line in record.read_text().splitlines() if '=' in line)
    assert_only_own_credentials(environment, OWN, 'OPENAI_API_KEY', DECLARED)


def test_role_connection_catalog_carries_the_declaration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A role connection's provider declares names; anything else is refused without echoing it."""
    monkeypatch.setenv('HOME', str(tmp_path))
    catalog = {'version': 1, 'runtimes': {'one': {'runtime': 'dsh', 'providers': {'deepseek-official': {
        'pass_env': [DECLARED], 'models': {'flash': {'id': 'deepseek-flash', 'source': 'native'}}}}}}}
    assert validate_catalog(catalog) == catalog
    from graphtraj.execution.runner_io import write_yaml_durably

    (tmp_path / '.graphtraj').mkdir()
    write_yaml_durably(tmp_path / '.graphtraj/connections.yml', catalog)
    assert resolve_connection('one/deepseek-official/flash', None)['pass_env'] == (DECLARED,)

    catalog['runtimes']['one']['providers']['deepseek-official']['pass_env'] = ['sk-not-a-name']
    with pytest.raises(ValueError, match='pass_env must list') as caught:
        validate_catalog(catalog)
    assert 'sk-not-a-name' not in str(caught.value)
