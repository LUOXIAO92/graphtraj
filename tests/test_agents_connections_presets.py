"""agents' own Runtime connections, presets, model choice and multi-driver hosts (380).

Every check runs through the public seams: ``config.yml`` reading, the bound
``agents`` function over :class:`AgentControl`, and the agents drivers'
``prepare``/``require_available``. Native discovery is faked where it would
query an installed Runtime; nothing here starts a Runtime.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import agent_swarm
import agent_swarm.control
from agent_swarm import AgentControl, AgentsError, Caller, explicit_choices, read_connections, write_config
from agent_swarm.claude.driver import ClaudeDriver
from agent_swarm.codex.driver import CodexDriver
from agent_swarm.dsh.driver import DshDriver
from agent_swarm.pi.driver import PiDriver


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


class OldDriver(RecordingDriver):
    """A driver written before 380: ``prepare`` takes no keyword arguments."""

    def prepare(self, runtime, caller):
        self.prepared.append({'runtime': runtime})
        return {'runtime': runtime}


def configured(root: Path, text: str = CONFIG) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'config.yml').write_text(text, encoding='utf-8')
    return root


def create(control: AgentControl, **arguments) -> tuple[dict, bool]:
    result = agent_swarm.bind(control, CALLER)({'action': 'create', 'instruction': 'Work.', **arguments})
    return result.document, result.failed


@pytest.fixture
def catalog(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Fake native discovery for connections without declared models."""
    seen: list[dict] = []

    def discover(connection):
        seen.append(dict(connection))
        if connection.get('models') is not None:
            return agent_swarm.discover_models(connection)
        return {'runtime': connection['runtime'], 'status': 'available', 'message': 'fake catalog',
                'models': [{'id': 'gpt-5.5', 'alias': 'GPT-5.5', 'provider': 'openai',
                            'supported_efforts': ['low', 'medium', 'high']},
                           {'id': 'claude-opus-5-5', 'alias': 'Opus', 'provider': 'anthropic',
                            'supported_efforts': None}]}

    monkeypatch.setattr(agent_swarm.control, '_discover_models', discover)
    return seen


# -- config.yml ---------------------------------------------------------------

def test_connections_and_presets_are_read_with_their_names(tmp_path: Path) -> None:
    root = configured(tmp_path)
    declared = read_connections(root)
    assert declared['connections']['work-claude'] == {
        'name': 'work-claude', 'runtime': 'claude', 'home': '/native/claude',
        'base_url': 'https://proxy.example/v1', 'api_key_env': 'WORK_CLAUDE_KEY',
        'models': ['claude-opus-5-5', {'id': 'claude-sonnet-5-5', 'supported_efforts': ['low', 'high']}]}
    assert declared['connections']['local-codex'] == {'name': 'local-codex', 'runtime': 'codex'}
    assert declared['presets'] == {
        'reviewer': {'name': 'reviewer', 'connection': 'work-claude', 'model': 'claude-sonnet-5-5',
                     'reasoning_effort': 'high'},
        'quick': {'name': 'quick', 'runtime': 'codex', 'model': 'gpt-5.5'}}
    # The booleans keep their own reader and defaults.
    assert explicit_choices(root) == {'save_normalized_sessions': False}
    assert agent_swarm.read_config(root) == {'save_normalized_sessions': False, 'backfill_history': False}


def test_no_file_and_boolean_only_files_read_as_before(tmp_path: Path) -> None:
    assert read_connections(tmp_path) == {'connections': {}, 'presets': {}}
    configured(tmp_path, '# comment\n\nbackfill_history: true\n')
    assert explicit_choices(tmp_path) == {'backfill_history': True}
    assert read_connections(tmp_path) == {'connections': {}, 'presets': {}}


@pytest.mark.parametrize(('text', 'line', 'problem'), [
    ('connections:\n  a:\n    runtime: claude\n    token: x\n', 4, 'connections.a.token: unknown field'),
    ('connections:\n  a:\n    runtime: claude\n  a:\n    runtime: codex\n', 4, 'a is repeated'),
    ('connections:\n  a:\n    runtime: claude\n    runtime: codex\n', 4, 'runtime is repeated'),
    ('connections:\n  a:\n    runtime: gemini\n', 3, 'connections.a.runtime: expected one of'),
    ('connections:\n  a:\n    home: /x\n', 2, 'connections.a.runtime: required'),
    ('connections:\n  a:\n    runtime: claude\n    models: claude\n', 4, 'expected a non-empty list'),
    ('connections:\n  a:\n    runtime: claude\n    models: [x, x]\n', 4, 'a model id is repeated'),
    ('connections:\n  a:\n    runtime: claude\n    models: [{alias: y}]\n', 4, 'models.id: required'),
    ('connections:\n  a:\n    runtime: claude\n    home: relative\n', 4, 'expected an absolute path'),
    ('connections:\n  a:\n    runtime: claude\n    api_key_env: sk-123\n', 4, 'never a key'),
    ('connections:\n  a:\n    runtime: claude\n    base_url: https://u:p@h/\n', 4, 'credential-free'),
    ('connections:\n  a:\n    runtime: 3\n', 3, 'expected a non-empty string'),
    ('presets:\n  p:\n    connection: missing\n', 3, "no connection 'missing' is declared"),
    ('presets:\n  p:\n    model: m\n', 2, 'give either connection or runtime'),
    ('connections:\n  a:\n    runtime: claude\npresets:\n  p:\n    connection: a\n    runtime: claude\n',
     5, 'give either connection or runtime'),
    ('presets:\n  p:\n    runtime: pi\n    effort: high\n', 4, 'presets.p.effort: unknown field'),
    ('save_normalized_sessions: "true"\n', 1, 'true or false'),
    ('save_normalized_sessions: yes\n', 1, 'true or false'),
    ('backfill_history: true\nbackfill_history: false\n', 2, 'backfill_history is repeated'),
    ('roles: {}\n', 1, 'roles: unknown field'),
    ('connections: [a]\n', 1, 'connections must be a mapping'),
    ('connections:\n  a: {runtime: claude\n', 3, 'not valid YAML'),
])
def test_reading_is_strict_and_names_file_and_line(tmp_path: Path, text: str, line: int, problem: str) -> None:
    configured(tmp_path, text)
    for read in (explicit_choices, read_connections):
        with pytest.raises(ValueError) as caught:
            read(tmp_path)
        assert str(caught.value).startswith(f'{tmp_path / "config.yml"}:{line}: ')
        assert problem in str(caught.value)


def test_writing_a_choice_keeps_connections_presets_and_comments(tmp_path: Path) -> None:
    root = configured(tmp_path)
    before = read_connections(root)
    assert write_config(root, save_normalized_sessions=True, backfill_history=True) == {
        'save_normalized_sessions': True, 'backfill_history': True}
    text = (root / 'config.yml').read_text()
    assert text.count('save_normalized_sessions') == 1 and '# unchanged booleans' not in text
    assert '    model: claude-sonnet-5-5' in text
    assert read_connections(root) == before
    assert explicit_choices(root) == {'save_normalized_sessions': True, 'backfill_history': True}


# -- create: selection, precedence and errors ---------------------------------

def test_no_connections_keeps_the_original_prepare_call(tmp_path: Path) -> None:
    """A host's own Runtime works as before: no selection reaches the driver."""
    old = OldDriver()
    control = AgentControl(tmp_path, {'claude': old})
    document, failed = create(control, runtime='claude')
    assert not failed
    assert old.prepared == [{'runtime': 'claude'}]
    assert {name: document['result'][name] for name in ('runtime', 'preset', 'connection', 'model',
                                                         'reasoning_effort')} == {
        'runtime': 'claude', 'preset': None, 'connection': None, 'model': None, 'reasoning_effort': None}


def test_preset_fills_model_and_effort_and_the_document_reports_them(tmp_path: Path, catalog) -> None:
    driver = RecordingDriver()
    control = AgentControl(configured(tmp_path), {'claude': driver})
    document, failed = create(control, runtime='claude', preset='reviewer')
    assert not failed, document
    selection = driver.prepared[0]['selection']
    assert {name: selection[name] for name in ('preset', 'connection', 'model', 'reasoning_effort')} == {
        'preset': 'reviewer', 'connection': 'work-claude', 'model': 'claude-sonnet-5-5',
        'reasoning_effort': 'high'}
    assert selection['settings']['api_key_env'] == 'WORK_CLAUDE_KEY'
    assert driver.checked == [read_connections(tmp_path)['connections']['work-claude']]
    result = document['result']
    assert (result['preset'], result['connection'], result['model'], result['reasoning_effort']) == (
        'reviewer', 'work-claude', 'claude-sonnet-5-5', 'high')
    # The choice stays visible in later documents.
    status = agent_swarm.bind(control, CALLER)({'action': 'status', 'agent': result['agent']}).document
    assert status['result']['model'] == 'claude-sonnet-5-5'


def test_explicit_values_equal_to_the_preset_are_accepted(tmp_path: Path, catalog) -> None:
    driver = RecordingDriver()
    control = AgentControl(configured(tmp_path), {'claude': driver})
    _, failed = create(control, runtime='claude', preset='reviewer', model='claude-sonnet-5-5',
                       reasoning_effort='high')
    assert not failed


@pytest.mark.parametrize(('arguments', 'code', 'text'), [
    ({'runtime': 'claude', 'preset': 'missing'}, 'invalid-preset', "Preset 'missing' is not declared"),
    ({'runtime': 'codex', 'preset': 'reviewer'}, 'invalid-preset', "uses Runtime 'claude'"),
    ({'runtime': 'claude', 'preset': 'reviewer', 'model': 'claude-opus-5-5'}, 'invalid-model',
     "contradicts preset 'reviewer'"),
    ({'runtime': 'claude', 'preset': 'reviewer', 'reasoning_effort': 'low'}, 'invalid-reasoning-effort',
     "contradicts preset 'reviewer'"),
    ({'runtime': 'claude', 'model': 'claude-haiku-5-5'}, 'invalid-model', 'is not a candidate'),
    ({'runtime': 'claude', 'model': 'claude-sonnet-5-5', 'reasoning_effort': 'max'},
     'invalid-reasoning-effort', "supports reasoning_effort ['low', 'high']"),
    ({'runtime': 'pi', 'model': 'x'}, 'unsupported-runtime', "Runtime 'pi'"),
    ({'runtime': 'claude', 'preset': ''}, 'invalid-input', 'request.preset: must not be empty'),
    ({'runtime': 'claude', 'effort': 'high'}, 'invalid-input', 'request.effort'),
])
def test_invalid_choices_fail_with_a_code_naming_the_field(
    tmp_path: Path, catalog, arguments: dict, code: str, text: str,
) -> None:
    drivers = {'claude': RecordingDriver(), 'codex': RecordingDriver()}
    control = AgentControl(configured(tmp_path), drivers)
    document, failed = create(control, **arguments)
    assert failed and document['error']['code'] == code, document
    assert text in document['error']['message']
    # Nothing was substituted: no driver prepared and no Agent was recorded.
    assert not any(driver.prepared for driver in drivers.values())
    assert not (tmp_path / 'control' / 'agents').exists()


def test_a_model_discovery_cannot_verify_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent_swarm.control, '_discover_models', lambda connection: {
        'runtime': 'codex', 'status': 'unknown', 'models': [], 'message': 'Native metadata query failed.'})
    driver = RecordingDriver()
    control = AgentControl(configured(tmp_path), {'codex': driver})
    document, failed = create(control, runtime='codex', model='gpt-5.5')
    assert failed and document['error']['code'] == 'invalid-model'
    assert 'cannot be verified' in document['error']['message'] and not driver.prepared


def test_discovery_supplies_candidates_and_efforts(tmp_path: Path, catalog) -> None:
    driver = RecordingDriver()
    control = AgentControl(configured(tmp_path), {'codex': driver})
    _, failed = create(control, runtime='codex', preset='quick', reasoning_effort='medium')
    assert not failed
    assert catalog == [read_connections(tmp_path)['connections']['local-codex']]
    selection = driver.prepared[0]['selection']
    assert (selection['connection'], selection['model'], selection['reasoning_effort'], selection['provider']) == (
        'local-codex', 'gpt-5.5', 'medium', 'openai')
    document, failed = create(control, runtime='codex', model='gpt-5.5', reasoning_effort='xhigh')
    assert failed and document['error']['code'] == 'invalid-reasoning-effort'


def test_without_a_connection_a_model_is_checked_against_the_native_login(tmp_path: Path, catalog) -> None:
    driver = RecordingDriver()
    control = AgentControl(tmp_path, {'claude': driver})
    _, failed = create(control, runtime='claude', model='claude-opus-5-5', reasoning_effort='max')
    assert not failed
    assert catalog == [{'runtime': 'claude'}]
    assert driver.checked == []  # the host's own login is the driver's, as before
    selection = driver.prepared[0]['selection']
    assert (selection['connection'], selection['settings'], selection['model']) == (None, None, 'claude-opus-5-5')


def test_several_connections_for_one_runtime_need_a_preset(tmp_path: Path, catalog) -> None:
    configured(tmp_path, CONFIG.replace('  local-codex:\n', '  local-claude:\n    runtime: claude\n'
                                                            '  local-codex:\n'))
    driver = RecordingDriver()
    control = AgentControl(tmp_path, {'claude': driver})
    document, failed = create(control, runtime='claude')
    assert failed and document['error']['code'] == 'ambiguous-connection'
    assert "['local-claude', 'work-claude']" in document['error']['message']
    _, failed = create(control, runtime='claude', preset='reviewer')
    assert not failed and driver.prepared[0]['selection']['connection'] == 'work-claude'


def test_an_invalid_config_fails_create_with_its_line(tmp_path: Path) -> None:
    configured(tmp_path, 'connections:\n  a:\n    runtime: claude\n    secret: x\n')
    control = AgentControl(tmp_path, {'claude': RecordingDriver()})
    document, failed = create(control, runtime='claude')
    assert failed and document['error']['code'] == 'invalid-config'
    assert f'{tmp_path / "config.yml"}:4:' in document['error']['message']


def test_a_driver_without_selection_support_refuses_a_choice(tmp_path: Path, catalog) -> None:
    control = AgentControl(tmp_path, {'claude': OldDriver()})
    document, failed = create(control, runtime='claude', model='claude-opus-5-5')
    assert failed and document['error']['code'] == 'invalid-config'
    assert 'cannot run a selected' in document['error']['message']


def test_create_schema_lists_the_new_optional_arguments() -> None:
    from agent_swarm.discovery import handle_request

    described = handle_request({'action': 'describe', 'feature': 'create', 'schema': True},
                               lambda request: None).document['input_schema']
    assert {'preset', 'model', 'reasoning_effort'} <= set(described['properties'])
    assert described['required'] == ['instruction', 'runtime']


# -- several drivers in one host, availability -------------------------------

def test_one_host_registers_drivers_for_several_runtimes(tmp_path: Path, catalog) -> None:
    drivers = {name: RecordingDriver() for name in ('claude', 'codex', 'pi', 'dsh')}
    control = AgentControl(configured(tmp_path), drivers)
    control.require_connections()
    assert [len(drivers[name].checked) for name in ('claude', 'codex', 'pi', 'dsh')] == [1, 1, 0, 0]
    for runtime in ('claude', 'codex', 'pi', 'dsh'):
        document, failed = create(control, runtime=runtime)
        assert not failed and document['result']['runtime'] == runtime
        assert len(drivers[runtime].prepared) == 1
    document, failed = create(control, runtime='gemini')
    assert failed and document['error']['code'] == 'unsupported-runtime'


def test_a_declared_runtime_without_a_driver_is_refused_at_host_start(tmp_path: Path) -> None:
    control = AgentControl(configured(tmp_path), {'claude': RecordingDriver()})
    with pytest.raises(AgentsError) as caught:
        control.require_connections()
    assert caught.value.code == 'unsupported-runtime' and "'local-codex'" in caught.value.message


def test_an_unavailable_runtime_fails_create_without_an_agent(tmp_path: Path) -> None:
    driver = RecordingDriver(unavailable="Runtime 'codex' is not installed on this machine.")
    control = AgentControl(configured(tmp_path), {'codex': driver, 'claude': RecordingDriver()})
    document, failed = create(control, runtime='codex')
    assert failed and document['error']['code'] == 'runtime-unavailable'
    assert not driver.prepared and not (tmp_path / 'control' / 'agents').exists()
    with pytest.raises(AgentsError) as caught:
        control.require_connections()
    assert caught.value.code == 'runtime-unavailable'


def executable(directory: Path, name: str, output: str = '') -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(f'#!/bin/sh\necho "{output}"\n')
    path.chmod(0o755)
    return path


@pytest.mark.parametrize('runtime', ['claude', 'codex', 'pi', 'dsh'])
def test_agents_drivers_report_not_installed_and_not_logged_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runtime: str,
) -> None:
    monkeypatch.setenv('HOME', str(tmp_path / 'user'))
    monkeypatch.setenv('PATH', str(tmp_path / 'empty'))
    for variable in ('CLAUDE_CONFIG_DIR', 'CODEX_HOME', 'PI_CODING_AGENT_DIR', 'DSH_HOME', 'ABSENT_KEY'):
        monkeypatch.delenv(variable, raising=False)
    driver = {'claude': lambda: ClaudeDriver(tmp_path, {}), 'codex': lambda: CodexDriver(None),
              'pi': lambda: PiDriver({'worktree_path': str(tmp_path), 'provider': 'p', 'model': 'm'}),
              'dsh': lambda: DshDriver(tmp_path, {})}[runtime]()
    home = tmp_path / 'home'
    connection = {'name': 'c', 'runtime': runtime, 'home': str(home)}

    def refusal(settings: dict) -> str:
        with pytest.raises(AgentsError) as caught:
            driver.require_available(settings)
        assert caught.value.code == 'runtime-unavailable'
        assert f"Runtime '{runtime}' (connection 'c')" in caught.value.message
        return caught.value.message

    assert 'is not installed' in refusal(connection)
    executable(tmp_path / 'bin', runtime)
    monkeypatch.setenv('PATH', str(tmp_path / 'bin'))
    message = refusal({**connection, 'api_key_env': 'ABSENT_KEY'})
    assert 'ABSENT_KEY is unset or empty' in message
    monkeypatch.setenv('ABSENT_KEY', 'secret-value')
    driver.require_available({**connection, 'api_key_env': 'ABSENT_KEY'})
    if runtime == 'dsh':
        # DSH's own login files are not inspected; its start reports them.
        driver.require_available(connection)
        return
    assert 'is not logged in' in refusal(connection)
    login = {'claude': '.credentials.json', 'codex': 'auth.json', 'pi': 'auth.json'}[runtime]
    home.mkdir()
    (home / login).write_text('{}')
    driver.require_available(connection)


# -- the agents drivers apply a selection ------------------------------------

def test_claude_driver_applies_connection_model_and_effort(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    claude = executable(tmp_path / 'bin', 'claude', '2.1.300 (Claude Code)')
    monkeypatch.setenv('WORK_CLAUDE_KEY', 'secret-value')
    driver = ClaudeDriver(tmp_path, {'executable': str(claude), 'api_key_env': 'HOST_KEY',
                                     'base_url': 'https://host.example/'})
    connection = read_connections(configured(tmp_path / 'root'))['connections']['work-claude']
    settings = driver.prepare('claude', CALLER, selection={
        'settings': connection, 'model': 'claude-sonnet-5-5', 'reasoning_effort': 'high', 'provider': None})
    assert (settings['model'], settings['reasoning_effort'], settings['runtime_home'], settings['base_url'],
            settings['api_key_env']) == ('claude-sonnet-5-5', 'high', '/native/claude',
                                         'https://proxy.example/v1', 'WORK_CLAUDE_KEY')
    assert 'secret-value' not in json.dumps(settings)
    # Without a connection only the model and effort change; the host's endpoint stays with its key.
    monkeypatch.setenv('HOST_KEY', 'host-secret')
    settings = driver.prepare('claude', CALLER, selection={'settings': None, 'model': 'claude-opus-5-5',
                                                           'reasoning_effort': None})
    assert (settings['model'], settings['api_key_env'], settings['base_url']) == (
        'claude-opus-5-5', 'HOST_KEY', 'https://host.example/')
    with pytest.raises(AgentsError) as caught:
        driver.prepare('claude', CALLER, selection={'settings': None, 'model': None, 'reasoning_effort': 'off'})
    assert caught.value.code == 'invalid-reasoning-effort'


def test_codex_driver_applies_connection_model_and_effort(tmp_path: Path) -> None:
    peer = executable(tmp_path, 'codex')
    driver = CodexDriver({'adapter_request': {
        'arguments': [str(peer)], 'worktree_path': str(tmp_path),
        'session_parameters': {'cwd': str(tmp_path), 'model': 'host-model',
                               'developerInstructions': 'Native.', 'config': {}}},
        'connection': {'api_key_env': 'HOST_KEY', 'base_url': 'https://host.example/'}})
    settings = driver.prepare('codex', CALLER, selection={
        'settings': {'name': 'c', 'runtime': 'codex', 'home': '/native/codex', 'provider': 'work'},
        'model': 'gpt-5.5', 'reasoning_effort': 'high', 'provider': 'work'})
    parameters = settings['adapter_request']['session_parameters']
    assert parameters['model'] == 'gpt-5.5'
    assert (parameters['config']['model_reasoning_effort'], parameters['config']['model_provider']) == ('high', 'work')
    assert settings['connection'] == {'runtime_home': '/native/codex'}
    with pytest.raises(AgentsError) as caught:
        driver.prepare('codex', CALLER, selection={'settings': None, 'model': None, 'reasoning_effort': 'max'})
    assert caught.value.code == 'invalid-reasoning-effort'
    assert driver.prepare('codex', CALLER)['adapter_request']['session_parameters']['model'] == 'host-model'


def test_pi_driver_applies_model_and_effort_and_refuses_another_provider(tmp_path: Path) -> None:
    request = {'worktree_path': str(tmp_path), 'provider': 'anthropic', 'model': 'host', 'api_key_env': 'HOST_KEY',
               'agent_dir': '/host/pi'}
    driver = PiDriver(request)
    settings = driver.prepare('pi', CALLER, selection={
        'settings': {'name': 'c', 'runtime': 'pi', 'home': '/native/pi'}, 'model': 'claude-opus-5-5',
        'reasoning_effort': 'xhigh', 'provider': 'anthropic'})
    chosen = settings['adapter_request']
    assert (chosen['model'], chosen['reasoning_effort'], chosen['agent_dir'], chosen.get('api_key_env')) == (
        'claude-opus-5-5', 'xhigh', '/native/pi', None)
    assert request['model'] == 'host'
    for selection, code in (({'provider': 'openai'}, 'invalid-config'),
                            ({'settings': {'runtime': 'pi', 'base_url': 'https://x/'}}, 'invalid-config'),
                            ({'reasoning_effort': 'max'}, 'invalid-reasoning-effort')):
        with pytest.raises(AgentsError) as caught:
            driver.prepare('pi', CALLER, selection=selection)
        assert caught.value.code == code


def test_dsh_driver_applies_connection_model_and_effort(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dsh = executable(tmp_path / 'dsh' / 'bin', 'dsh')
    (tmp_path / 'dsh' / 'package.json').write_text(json.dumps({'version': '0.2.0-rc.2'}))
    monkeypatch.setenv('WORK_KEY', 'secret-value')
    driver = DshDriver(tmp_path, {'executable': str(dsh), 'sandbox': 'workspace-write', 'model': 'host-model',
                                  'api_key_env': 'HOST_KEY'})
    settings = driver.prepare('dsh', CALLER, selection={
        'settings': {'name': 'c', 'runtime': 'dsh', 'home': '/native/dsh', 'api_key_env': 'WORK_KEY',
                     'models': ['deepseek-v5']},
        'model': 'deepseek-v5', 'reasoning_effort': 'max', 'provider': None})
    assert (settings['model'], settings['reasoning_effort'], settings['runtime_home'], settings['api_key_env'],
            settings['model_source']) == ('deepseek-v5', 'max', '/native/dsh', 'WORK_KEY', 'manual')
    for selection, code in (({'provider': 'opencode-go'}, 'invalid-config'),
                            ({'reasoning_effort': 'medium'}, 'invalid-reasoning-effort')):
        with pytest.raises(AgentsError) as caught:
            driver.prepare('dsh', CALLER, selection=selection)
        assert caught.value.code == code


@pytest.mark.parametrize(('text', 'expected'), [
    ('backfill_history:true\n', {'backfill_history': True}),
    ('  save_normalized_sessions: false\nbackfill_history: true  # note\n',
     {'save_normalized_sessions': False, 'backfill_history': True}),
])
def test_boolean_only_files_keep_the_previous_grammar(tmp_path: Path, text: str, expected: dict) -> None:
    configured(tmp_path, text)
    assert explicit_choices(tmp_path) == expected
    write_config(tmp_path, save_normalized_sessions=True)
    assert explicit_choices(tmp_path) == {**expected, 'save_normalized_sessions': True}


def test_a_non_boolean_choice_beside_connections_is_refused(tmp_path: Path) -> None:
    configured(tmp_path, 'backfill_history: yes\nconnections:\n  a:\n    runtime: pi\n')
    with pytest.raises(ValueError, match=r'config.yml:1: backfill_history: expected true or false'):
        explicit_choices(tmp_path)
