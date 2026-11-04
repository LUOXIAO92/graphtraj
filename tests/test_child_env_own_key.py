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
import time
from fnmatch import fnmatchcase
import json

import pytest
import yaml

from graftling import AgentControl, AgentsResult, Caller, bind
from graftling.child_env import CODEX_SHELL_EXCLUDE, child_environment, is_credential_name
from graftling.claude import ClaudeDriver
from graftling.claude.execution import ClaudeExecution
from graftling.codex.managed_session import CodexManagedExecution
from graftling.config import read_connections
from graftling.connection import agents_connection
from graftling.sessions import SessionArchive
from graftling.dsh.execution import DshExecution
from graftling.pi.driver import selected as pi_selected
from graftling.pi.execution import PiExecution
from graftling.process import authenticate_process
from graphtraj.configuration.project_roles import ProjectRolesError, load_project_roles, parse_inline_role
from graphtraj.configuration.runtime_connections import resolve_connection, validate_catalog
from graphtraj.configuration.role_definitions import resolve_child_role
from graphtraj.runtimes.runtime_adapter import select_runtime_adapter

from test_claude_review import native  # noqa: F401  (fixture)
from test_codex_app_server import peer  # noqa: F401  (fixture)
from test_codex_approval import managed
from test_pi_runtime import pi_environment  # noqa: F401  (fixture)


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
              'from graftling.connection import call_owner\n'
              'assert "CHILD_KEY" not in os.environ\n'
              'print(json.dumps(call_owner({"action": "execute", "feature": "status", "arguments": {}}).document))\n')
    environment = {'PATH': os.environ['PATH'], 'HOME': os.environ['HOME'],
                   'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src'),
                   'GIT_AUTHOR_NAME': 'write child', 'GIT_CONFIG_GLOBAL': os.devnull}

    with agents_connection(tmp_path / 'channel', call, lambda pid: authenticate_process(child, pid)) as address:
        child = subprocess.Popen([sys.executable, '-c', script], env={**environment, 'GRAFTLING_CONNECTION': address},
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
    # fake_environment's GIT_CONFIG_COUNT/KEY_0 stand for an owner's names, not a Git
    # setting; this setup runs Git without them or the user's own configuration.
    git = {name: value for name, value in os.environ.items() if not name.startswith('GIT_')}
    git.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
    made = subprocess.run(['git', 'init', '-q', str(tmp_path / 'write' / 'worktree')], env=git,
                          capture_output=True, text=True)
    assert made.returncode == 0, made.stderr
    written = launch_pi(tmp_path / 'write', worktree_access='write', git_common_directory=str(tmp_path / 'write/worktree/.git'))
    assert written['GIT_CONFIG_GLOBAL'] == os.devnull
    assert 'GIT_CONFIG_GLOBAL' not in os.environ

    read = launch_pi(tmp_path / 'read')
    assert not {'GIT_CONFIG_GLOBAL', 'GIT_AUTHOR_NAME', 'GIT_COMMITTER_NAME'} & read.keys()


# --- GraphTraj's Runner members, through their own adapters --------------------------------------


def _member_role(root: Path, **fields) -> object:
    """Resolve a role from the user's roles.yml, the way a Runner dispatch does."""
    (root / '.graphtraj').mkdir(exist_ok=True)
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({'roles': {'author': fields}}))
    return resolve_child_role('author', load_project_roles(root).presets['author'], root)


def test_runner_pi_member(tmp_path: Path, pi_environment: dict) -> None:  # noqa: F811
    """A Pi member: GraphTraj's execution over the same rule, with a role's declaration."""
    from graphtraj.runtimes.pi.managed_session import PiManagedExecution

    worktree = tmp_path / 'worktrees/research'
    worktree.mkdir(parents=True)
    role = _member_role(tmp_path, runtime='pi', model='deepseek/deepseek-flash', api_key_env=OWN, pass_env=[DECLARED],
                        worktree_access='read', pi={'sandbox_python': pi_environment['sandbox_python'],
                                                    'sandbox_path': pi_environment['sandbox_path'],
                                                    'agent_dir': pi_environment['agent_dir']})
    prepared = select_runtime_adapter('pi').preflight_runtime_context(
        harness_root=tmp_path, git_common_directory=worktree / '.git', role=role, worktree=worktree,
        evidence=tmp_path / 'state', requested_skills=(),
    ).finalize()
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


# --- Round 2: an inline role names no environment variable (results 2 and 8) ---------------------


@pytest.mark.parametrize('field', [{'pass_env': [UNRELATED]}, {'api_key_env': UNRELATED}])
def test_a_swarm_inline_role_cannot_name_a_variable(tmp_path: Path, field: dict) -> None:
    """The real Batch entry refuses it, so a model dispatching a role cannot ask for a key."""
    from graphtraj.execution.runner_batch import parse_batch
    from graphtraj.execution.runner_models import RunnerError

    role = {'coding_team.engineer': {'runtime': 'codex', 'model': 'm', **field}}
    with pytest.raises(ProjectRolesError, match=next(iter(field))):
        parse_inline_role(role)
    with pytest.raises(RunnerError) as caught:
        parse_batch({'tasks': [{'task_id': '1', 'task_name': 'one', 'role': role}]})
    assert caught.value.code == 'ROLE_NOT_CONFIGURED'
    assert next(iter(field)) in caught.value.message and 'connection: runtime/provider/model' in caught.value.message
    assert UNRELATED not in caught.value.message


def test_a_retained_inline_role_keeps_loading(tmp_path: Path) -> None:
    """A Session started from a retained Batch resumes: only a new dispatch is refused."""
    from graphtraj.execution.runner_batch import parse_batch

    role = {'coding_team.engineer': {'runtime': 'dsh', 'model': 'm', 'base_url': 'https://gateway.invalid',
                                     'api_key_env': 'DEEPSEEK_API_KEY'}}
    assert parse_inline_role(role, retained=True)[1].api_key_env == 'DEEPSEEK_API_KEY'
    task = parse_batch({'tasks': [{'task_id': '1', 'task_name': 'one', 'role': role}]}, retained=True).tasks[0]
    assert task.inline_preset.api_key_env == 'DEEPSEEK_API_KEY'


def test_an_inline_role_still_selects_a_connection_and_its_other_fields(tmp_path: Path) -> None:
    """Refusing the two variable fields leaves every other inline use as it was."""
    assert parse_inline_role({'a': {'connection': 'one/two/three'}})[1].connection == 'one/two/three'
    assert parse_inline_role({'a': {'runtime': 'codex', 'model': 'm', 'codex': {'approval': {'connection': 'one/two/three'}}}})


def test_the_users_roles_file_still_declares_both(tmp_path: Path) -> None:
    """roles.yml is the user's own, so it keeps both fields."""
    role = _member_role(tmp_path, runtime='codex', model='m', api_key_env=OWN, pass_env=[DECLARED])
    assert (role.settings.api_key_env, role.settings.pass_env) == (OWN, (DECLARED,))


# --- Round 2: Pi's models.json and auth.json name the child's key (result 3) -----------------------


def write_pi_home(tmp_path: Path, name: str, document: dict) -> Path:
    """Write one of Pi's home files under a fake agent directory."""
    agent = Path(os.environ['PI_TEST_AGENT'])
    agent.mkdir(parents=True, exist_ok=True)
    (agent / name).write_text(json.dumps(document))
    return agent


@pytest.mark.parametrize('value', [OWN, '$' + OWN, '${' + OWN + '}'])
def test_pi_key_named_in_models_json(tmp_path: Path, pi_agent: None, value: str) -> None:
    """Real Pi lists this provider with no key set, so only the file can say which variable it means."""
    write_pi_home(tmp_path, 'models.json', {'providers': {'deepseek': {'apiKey': value}}})
    assert_only_own_credentials(launch_pi(tmp_path), OWN)


def test_pi_key_named_in_auth_json(tmp_path: Path, pi_agent: None) -> None:
    """auth.json's key reference for the selected provider is the child's own."""
    write_pi_home(tmp_path, 'auth.json', {'deepseek': {'type': 'api_key', 'key': '$' + OWN}})
    assert_only_own_credentials(launch_pi(tmp_path), OWN)


@pytest.mark.parametrize('value', ['!printf ' + OWN, 'not-a-variable', '$NOT_SET_ANYWHERE_KEY'])
def test_pi_home_value_naming_no_set_variable_hands_over_nothing(tmp_path: Path, pi_agent: None, value: str) -> None:
    """A command is never run or read for a name; a literal or an unset name adds nothing."""
    write_pi_home(tmp_path, 'models.json', {'providers': {'deepseek': {'apiKey': value}}})
    assert_only_own_credentials(launch_pi(tmp_path))


def test_pi_another_providers_name_is_not_own(tmp_path: Path, pi_agent: None) -> None:
    """Only the selected provider's entry counts."""
    write_pi_home(tmp_path, 'models.json', {'providers': {'other': {'apiKey': '$' + UNRELATED}}})
    assert_only_own_credentials(launch_pi(tmp_path))


def test_pi_reviewer_holding_the_named_key_is_refused(tmp_path: Path, pi_agent: None) -> None:
    """A models.json naming the reviewer's key would leave the child with only that name."""
    from graftling import AgentsError
    from graftling.pi.driver import _refuse_key_held_by_reviewer

    write_pi_home(tmp_path, 'models.json', {'providers': {'deepseek': {'apiKey': '$' + REVIEW}}})
    request = {'executable': _which('pi'), 'agent_dir': os.environ['PI_TEST_AGENT'], 'provider': 'deepseek',
               'model': 'deepseek-flash', 'review': REVIEWER}
    with pytest.raises(AgentsError, match=REVIEW):
        _refuse_key_held_by_reviewer(request)


# --- Round 2: Codex's tool shells exclude credential names (result 7) ------------------------------


@pytest.mark.parametrize('name', MUST_DROP)
def test_codex_globs_cover_each_credential_name(name: str) -> None:
    """Every name the rule drops is matched by a glob; globs ignore case on real Codex."""
    assert any(fnmatchcase(name.upper(), pattern) for pattern in CODEX_SHELL_EXCLUDE)


@pytest.mark.parametrize('name', MUST_KEEP)
def test_codex_globs_spare_each_ordinary_name(name: str) -> None:
    """GIT_CONFIG_KEY_<n> above all: Git fails without it when GIT_CONFIG_COUNT is set."""
    assert not any(fnmatchcase(name.upper(), pattern) for pattern in CODEX_SHELL_EXCLUDE)


def test_codex_globs_difference_from_the_rule_is_the_written_one() -> None:
    """PUBLIC_API 3.1 names this: a digit after a middle KEY part cannot be spared only for Git."""
    assert is_credential_name('MY_KEY_2')
    assert not any(fnmatchcase('MY_KEY_2', pattern) for pattern in CODEX_SHELL_EXCLUDE)


def run_codex_member(tmp_path: Path, peer: Path, monkeypatch: pytest.MonkeyPatch, *, session: str | None = None,
                     **fields) -> tuple[list[dict], Path]:
    """Run a real owner against the controlled peer; return what thread/start or resume received."""
    record = tmp_path / 'session-parameters.jsonl'
    monkeypatch.setenv('MANAGED_SESSION_PARAMETERS', str(record))
    request, directory = managed(tmp_path, peer, monkeypatch)
    archive = SessionArchive(tmp_path / 'data', save_normalized_sessions=True, backfill_history=False)
    worker = CodexManagedExecution({**request, **fields}, 'request: inspect only', directory, lambda *a: None, {},
                                   directory / 'events.jsonl', session, archive=archive)

    def own() -> None:
        """Run the owner; only what it sent and wrote is observed."""
        try:
            worker.run()
        except Exception:
            pass

    thread = threading.Thread(target=own, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not record.exists():
        time.sleep(0.05)
    # The Session has started, which is all these tests need; the peer would wait for a reply.
    time.sleep(0.3)
    worker.terminate()
    thread.join(10)
    return [json.loads(line) for line in record.read_text().splitlines()], directory


def test_codex_session_excludes_credentials_on_first_start(tmp_path: Path, peer: Path,  # noqa: F811
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    """Every native Session gets the policy, and what the owner sets for its connection stays."""
    [sent], _ = run_codex_member(tmp_path, peer, monkeypatch)
    policy = sent['params']['config']['shell_environment_policy']
    assert sent['method'] == 'thread/start'
    assert set(CODEX_SHELL_EXCLUDE) <= set(policy['exclude'])


def test_codex_session_excludes_credentials_on_resume(tmp_path: Path, peer: Path,  # noqa: F811
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """A resumed Session gets it too, since a resume carries its own config."""
    sent, _ = run_codex_member(tmp_path, peer, monkeypatch, session='resumed-session')
    assert sent[0]['method'] == 'thread/resume'
    assert set(CODEX_SHELL_EXCLUDE) <= set(sent[0]['params']['config']['shell_environment_policy']['exclude'])


def test_codex_users_exclude_entries_are_kept(tmp_path: Path, peer: Path,  # noqa: F811
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """A Session's list replaces the home's on real Codex, so the home's entries are carried over."""
    home = Path(os.environ['CODEX_HOME'])
    home.mkdir()
    (home / 'config.toml').write_text('[shell_environment_policy]\nexclude = ["MINE_*"]\n')
    [sent], _ = run_codex_member(tmp_path, peer, monkeypatch)
    assert 'MINE_*' in sent['params']['config']['shell_environment_policy']['exclude']


def test_codex_declared_credential_reaches_the_shell_but_no_retained_file(tmp_path: Path, peer: Path,  # noqa: F811
                                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """Sent to Codex once; absent from every document, trace, diagnostic and archive the owner writes."""
    [sent], directory = run_codex_member(tmp_path, peer, monkeypatch, pass_env=[DECLARED])
    assert sent['params']['config']['shell_environment_policy']['set'][DECLARED] == 'fake-' + DECLARED

    value = ('fake-' + DECLARED).encode()
    written = [path for path in tmp_path.rglob('*') if path.is_file() and path.name != 'session-parameters.jsonl']
    assert written
    assert [str(path) for path in written if value in path.read_bytes()] == []


def test_codex_declared_ordinary_name_needs_no_set(tmp_path: Path, peer: Path,  # noqa: F811
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """Only a name the globs would hide travels in the parameters."""
    monkeypatch.setenv('PLAIN_SETTING', 'plain')
    [sent], _ = run_codex_member(tmp_path, peer, monkeypatch, pass_env=['PLAIN_SETTING'])
    assert 'PLAIN_SETTING' not in sent['params']['config']['shell_environment_policy'].get('set', {})


def test_codex_withheld_reviewer_key_is_not_set_when_declared(tmp_path: Path) -> None:
    """A declared reviewer's key stays out of the parameters as out of the environment."""
    executable, _ = recording_codex(tmp_path)
    worker = CodexManagedExecution(codex_request(tmp_path, executable, pass_env=[REVIEW]), 'x', tmp_path,
                                   lambda *a: None, {}, tmp_path / 't', None, review=REVIEWER)
    environment = worker.child_overrides(worker.context.launch_document()['adapter_request'],
                                         worker.context.launch_document()['adapter_request']['session_parameters']['config'])
    assert environment[REVIEW] is None
    transient = worker.declared_context(worker.context.launch_document()['adapter_request'], environment)
    assert transient is worker.context


# --- Task 439: a user-started Codex host keeps the user's environment; its children do not -------


def test_codex_top_level_host_keeps_the_users_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CodexHost takes the user's environment as before 433: no removal and no shell exclude."""
    from graftling.codex.host import CodexHost

    assert CodexHost.user_environment is True and CodexManagedExecution.user_environment is False
    monkeypatch.setenv('GH_TOKEN', 'FAKE439HOSTVALUE')
    executable, _ = recording_codex(tmp_path)
    worker = CodexManagedExecution(codex_request(tmp_path, executable), 'x', tmp_path,
                                   lambda *a: None, {}, tmp_path / 't', None)
    request = worker.context.launch_document()['adapter_request']
    host = worker.host_overrides()
    assert 'GH_TOKEN' not in host  # inherited unchanged from the user's environment
    child = worker.child_overrides(request, request['session_parameters']['config'])
    assert child['GH_TOKEN'] is None


def test_codex_top_level_host_session_has_no_child_exclude(tmp_path: Path, peer: Path,  # noqa: F811
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    """With the host switch on, the native Session gets no 433 exclude; a child's still does."""
    monkeypatch.setattr(CodexManagedExecution, 'user_environment', True)
    [sent], _ = run_codex_member(tmp_path, peer, monkeypatch)
    policy = sent['params']['config'].get('shell_environment_policy', {})
    assert not set(CODEX_SHELL_EXCLUDE) & set(policy.get('exclude', []))
