"""Choosing a provider through GraphTraj's catalog, discovery, roles and ``create`` (611).

A stand-in DSH install carries a stand-in pi-ai catalog that Node reads as the
installed DSH does (graftling 608); controlled services stand in for ``dsh web``,
so no model is asked anything. The controlled Claude peer stands in for Claude.
"""

from contextlib import nullcontext
import json
from pathlib import Path
import shutil

from click.testing import CliRunner
import pytest
import yaml

from graphtraj.configuration.project_roles import load_project_roles
from graphtraj.configuration.role_definitions import resolve_child_role
from graphtraj.interfaces.local_tool import bind
from graphtraj.interfaces.cli.graphtraj import main
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError, select_runtime_adapter
from test_agents_native_claude import agents
from test_claude_runtime import claude_environment  # noqa: F401 - pytest fixture
from test_dsh_runtime import NativePeer, TaggedLoader
from test_role_organization import CONFIG

KEY_ENV = 'OPENCODE_611_KEY'
KEY     = 'never-shown-611-key'

needs_node = pytest.mark.skipif(shutil.which('node') is None, reason='Node reads the DSH provider catalog.')


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project whose user catalog lives in an isolated home."""
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    root = tmp_path / 'project'
    (root / '.graphtraj').mkdir(parents=True)
    (root / '.graphtraj/config.yml').write_text(CONFIG)
    (root / '.graphtraj/roles.yml').write_text('roles: {}\n')
    return root


@pytest.fixture
def installed_dsh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in DSH on PATH whose pi-ai catalog serves opencode-go and openrouter."""
    package = tmp_path / 'installed-dsh'
    (package / 'bin').mkdir(parents=True)
    (package / 'bin/dsh').write_text('#!/bin/sh\nexit 1\n')
    (package / 'bin/dsh').chmod(0o755)
    (package / 'package.json').write_text('{"version":"0.2.2-rc.5"}')
    pi_ai = package / 'node_modules/@earendil-works/pi-ai'
    pi_ai.mkdir(parents=True)
    (pi_ai / 'package.json').write_text(json.dumps({
        'name': '@earendil-works/pi-ai', 'type': 'module', 'exports': {'./providers/all': './all.js'}}))
    (pi_ai / 'all.js').write_text(
        'const chat = {"opencode-go": ["glm-5.3"], "openrouter": ["some/model"]};\n'
        'export const builtinProviders = () => Object.keys(chat).map((id) => ({id}));\n'
        'export const getBuiltinModels = (id) => chat[id];\n'
        'export const getAllBuiltinModels = (id) => chat[id];\n')
    monkeypatch.setenv('PATH', f"{package / 'bin'}:{__import__('os').environ['PATH']}")
    monkeypatch.setenv(KEY_ENV, KEY)
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'never-shown-611-default-key')
    return package


def operation(project: Path, arguments: dict) -> dict:
    """Call the public runtime_connections feature."""
    return bind(project, recovery_reviewer=lambda proposal: {'decision': 'accept'})(
        {'action': 'execute', 'feature': 'runtime_connections', 'arguments': arguments},
    ).document


def save(project: Path, document: dict) -> dict:
    """Save a catalog at the revision read just before."""
    current = operation(project, {'action': 'read'})
    return operation(project, {'action': 'save', 'expected_revision': current['revision'], 'catalog': document})


def dsh_catalog(tmp_path: Path) -> dict:
    """One DSH home offering DSH's own opencode-go and openrouter providers and deepseek-official."""
    def provider(model: str, **fields: object) -> dict:
        return {**fields, 'models': {'m': {'id': model, 'source': 'native'}}}

    return {'version': 1, 'runtimes': {'dsh-home': {
        'runtime': 'dsh', 'home': str(tmp_path / 'dsh-home'), 'providers': {
            'opencode-go':       provider('glm-5.3', api_key_env=KEY_ENV),
            'deepseek-official': provider('deepseek-flash'),
            'unkeyed':           provider('glm-5.3'),
            'not-served':        provider('x', api_key_env=KEY_ENV),
        },
    }}}


@needs_node
def test_dsh_discovery_by_provider_uses_its_route_and_groups(
    project: Path, tmp_path: Path, installed_dsh: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider without base_url is saved, then listed through DSH's route for it, by name only."""
    from graftling.dsh import service

    routes = []

    class Host:
        """A catalog-only ``dsh web``: records its route patch and offers two providers."""

        def __init__(self, executable: str, cwd: Path, environment: dict, profile_patch: Path | None = None) -> None:
            routes.append(json.loads(profile_patch.read_text()) if profile_patch else [])

        def start(self) -> None:
            """Nothing starts."""

        def rpc(self, method: str) -> dict:
            """Return the public catalog shape."""
            return {'groups': [
                {'id': 'deepseek-official', 'models': [{'id': 'deepseek-flash', 'name': 'Flash'}]},
                {'id': 'opencode-go', 'models': [{'id': 'glm-5.3', 'name': 'GLM'}, {'id': 'kimi', 'name': 'Kimi'}]},
            ]}

        def close(self) -> None:
            """Nothing to stop."""

    monkeypatch.setattr(service, 'DshService', Host)
    saved = save(project, dsh_catalog(tmp_path))
    assert saved['applied'] is True

    # The CLI entry Main and the manual use.
    shown = CliRunner().invoke(main, ['connections', '--action', 'discover', '--runtime', 'dsh-home',
                                      '--provider', 'opencode-go'])
    assert shown.exit_code == 0, shown.output
    listed = yaml.safe_load(shown.output)['discovery']
    assert listed['provider'] == 'opencode-go' and listed['status'] == 'available'
    assert [(group['provider'], [model['id'] for model in group['models']]) for group in listed['groups']] == [
        ('opencode-go', ['glm-5.3', 'kimi'])]
    assert routes[-1] == [{'id': 'llm-pi-ai', 'config': {'providers': {'opencode-go': {'apiKeyEnv': KEY_ENV}}}}]
    assert KEY not in json.dumps(listed)

    # Without provider the home's whole catalog is listed by provider, as before.
    whole = operation(project, {'action': 'discover', 'runtime': 'dsh-home'})['discovery']
    assert [group['provider'] for group in whole['groups']] == ['deepseek-official', 'opencode-go']
    assert routes[-1] == []

    # graftling's refusal reaches the caller; nothing is queried.
    for provider, reason in (('unkeyed', 'needs api_key_env'), ('not-served', 'does not serve')):
        before = len(routes)
        with pytest.raises(Exception, match=reason):
            operation(project, {'action': 'discover', 'runtime': 'dsh-home', 'provider': provider})
        assert len(routes) == before


@needs_node
def test_a_dsh_role_runs_its_catalog_provider_with_only_its_key(
    project: Path, tmp_path: Path, installed_dsh: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The role's provider reaches DSH as is; deepseek-official keeps its route; others are refused."""
    from graphtraj.interfaces import hosted_cli
    from graphtraj.runtimes.dsh import execution

    launched = []

    class Peer(NativePeer):
        """Record the route row and the credential variables the child service receives."""

        def __init__(self, executable: str, cwd: Path, environment: dict, *, profile_patch: Path) -> None:
            rows = yaml.load(profile_patch.read_text(), Loader=TaggedLoader)
            routes = [row for row in rows if row.get('id') in ('llm-pi-ai', 'llm-deepseek')]
            launched.append((routes, {name for name in environment if name in (KEY_ENV, 'DEEPSEEK_API_KEY')}))
            super().__init__(executable, cwd, {**environment, 'DSH_HOME': str(profile_patch.parents[2])})
            self.frames.append('turn/end')

    monkeypatch.setattr(execution, 'DshService', Peer)
    monkeypatch.setattr(hosted_cli, 'cli_connection', lambda *args, **kwargs: nullcontext('/bound-channel'))
    (tmp_path / 'dsh-home').mkdir()
    save(project, dsh_catalog(tmp_path))
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({'roles': {
        name: {'connection': f'dsh-home/{provider}/m'} for name, provider in (
            ('glm', 'opencode-go'), ('flash', 'deepseek-official'),
            ('unkeyed', 'unkeyed'), ('not-served', 'not-served'))
    }}))
    adapter = select_runtime_adapter('dsh')

    def prepared(name: str) -> dict:
        """Preflight one role through the public Runtime preparation interface."""
        role = resolve_child_role(name, load_project_roles(project).preset(name), project)
        return adapter.preflight_runtime_context(
            harness_root=project, git_common_directory=project / '.git', role=role,
            worktree=project, evidence=tmp_path / 'evidence', requested_skills=(),
        ).finalize().launch_document()['adapter_request']

    requests = {name: prepared(name) for name in ('glm', 'flash')}
    assert (requests['glm']['provider'], requests['glm']['model']) == ('opencode-go', 'glm-5.3')
    assert (requests['flash']['provider'], requests['flash']['model']) == ('deepseek-official', 'deepseek-flash')
    for name, reason in (('unkeyed', 'needs api_key_env'), ('not-served', 'does not serve')):
        with pytest.raises(RuntimeAdapterError, match=reason):
            prepared(name)

    for index, name in enumerate(('glm', 'flash')):
        directory = tmp_path / f'run-{index}'
        directory.mkdir()
        result = adapter.managed_execution(
            requests[name], 'one line', directory, lambda session, pid: None, {},
            trace_file=directory / 'trace.jsonl', expected_session=None,
            session_created=lambda session, pid: None,
        ).run()
        assert result['outcome'] == 'completed'
    (glm_routes, glm_keys), (flash_routes, flash_keys) = launched
    assert glm_routes == [{'id': 'llm-pi-ai', 'config': {'providers': {'opencode-go': {'apiKeyEnv': KEY_ENV}}}}]
    assert glm_keys == {KEY_ENV}
    assert [row['id'] for row in flash_routes] == ['llm-deepseek']
    assert flash_keys == {'DEEPSEEK_API_KEY'}


@pytest.fixture
def claude_project(project: Path) -> Path:
    """Two Claude roles on catalog providers and one inline Claude role."""
    from graphtraj.configuration.project_configuration import default_configuration_content

    (project / '.graphtraj/config.yml').write_text(default_configuration_content(project, project))
    catalog = Path.home() / '.graphtraj/connections.yml'
    catalog.parent.mkdir(parents=True)
    catalog.write_text(yaml.safe_dump({'version': 1, 'runtimes': {'claude-home': {
        'runtime': 'claude', 'providers': {
            name: {'models': {'opus': {'id': 'claude-opus-5-5', 'source': 'manual'}}}
            for name in ('anthropic', 'gateway')
        },
    }}}))
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {
            'claude':  {'connection': 'claude-home/anthropic/opus'},
            'routed':  {'connection': 'claude-home/gateway/opus'},
            'inline':  {'runtime': 'claude', 'model': 'claude-opus-5-5'},
        },
        'role_tree': {'claude': {}, 'routed': {}, 'inline': {}},
    }))
    return project


def test_create_provider_selects_the_role_using_it(claude_project: Path, claude_environment: None) -> None:
    """``create``'s provider picks the role whose catalog connection declares it, never another."""
    cwd = claude_project / 'scratch'
    cwd.mkdir()

    created, failed = agents(claude_project, cwd, 'main-a', action='create', runtime='claude',
                             instruction='hello', provider='gateway')
    assert not failed, created
    assert created['result']['configuration'] == 'routed'
    agents(claude_project, cwd, 'main-a', action='wait', agent=created['agent'], timeout_seconds=20)
    agents(claude_project, cwd, 'main-a', action='retire', agent=created['agent'])

    refused, failed = agents(claude_project, cwd, 'main-a', action='create', runtime='claude',
                             instruction='hello', provider='elsewhere')
    assert failed and refused['error']['code'] == 'invalid-provider', refused
    assert "['anthropic', 'gateway']" in refused['error']['message']

    refused, failed = agents(claude_project, cwd, 'main-a', action='create', runtime='claude',
                             instruction='hello', provider='gateway', configuration='inline')
    assert failed and refused['error']['code'] == 'invalid-provider', refused

    # models lists the same role choices create took (614; tests/test_role_models_614.py).
    listed, failed = agents(claude_project, cwd, 'main-a', action='models', runtime='claude')
    assert not failed, listed
    assert {model['configuration']: model['provider'] for model in listed['result']['models']} == {
        'claude': 'anthropic', 'routed': 'gateway', 'inline': None}
