"""User connection behavior through public tools and the existing Runtime seam."""

import copy
import asyncio
from contextlib import nullcontext
import json
import os
from pathlib import Path

import pytest
import yaml

from graphtraj.configuration.project_roles import load_project_roles
from graphtraj.configuration.role_definitions import resolve_child_role
from graphtraj.interfaces.local_tool import bind
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError, select_runtime_adapter
from test_role_organization import CONFIG
from test_pi_runtime import pi_environment
from test_codex_app_server import context as codex_context, peer
from graphtraj.runtimes.codex.app_server import CodexAppServer


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep both the user's catalog and project configuration isolated."""
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    root = tmp_path / 'project'
    (root / '.graphtraj').mkdir(parents=True)
    (root / '.graphtraj/config.yml').write_text(CONFIG)
    (root / '.graphtraj/roles.yml').write_text('roles: {}\n')
    return root


def catalog(project: Path, runtime: str = 'codex') -> dict:
    """Describe two custom routes sharing a single native Home."""
    provider = {'base_url': 'https://provider.example/v1', 'api_key_env': 'CUSTOM_KEY',
                'models': {'model': {'id': 'actual-model', 'alias': 'Friendly name',
                                     'source': 'manual', 'supported_efforts': ['low']}}}
    if runtime == 'pi':
        provider['api'] = 'openai-completions'
    return {'version': 1, 'runtimes': {'shared': {
        'runtime': runtime, 'home': str(project.parent / 'native'),
        'providers': {'first': provider, 'second': {
            **copy.deepcopy(provider), 'base_url': 'http://localhost:8080/v1',
            'api_key_env': 'OTHER_KEY',
        }},
    }}}


def operation(project: Path, arguments: dict, reviewer=None) -> dict:
    """Call the same public operation used by CLI and downstream desktop hosts."""
    return bind(project, recovery_reviewer=reviewer)(
        {'action': 'execute', 'feature': 'runtime_connections', 'arguments': arguments},
    ).document


def save(project: Path, document: dict) -> dict:
    """Save an explicitly accepted catalog at the revision returned by read."""
    current = operation(project, {'action': 'read'})
    return operation(project, {'action': 'save', 'expected_revision': current['revision'],
                               'catalog': document}, lambda proposal: {'decision': 'accept'})


def test_catalog_preview_save_refusal_and_conflict(project: Path) -> None:
    """Denied, stale and failed review leave the complete prior file untouched."""
    original = operation(project, {})
    path = Path(original['path'])
    assert original['scope'] == 'user' and not path.exists()
    draft = catalog(project)
    assert operation(project, {'action': 'preview', 'catalog': draft})['catalog'] == draft
    assert not path.exists()
    request = {'action': 'save', 'expected_revision': original['revision'], 'catalog': draft}
    with pytest.raises(Exception, match='did not approve'):
        operation(project, request, lambda proposal: {'decision': 'decline'})
    assert not path.exists()
    saved = save(project, draft)
    before = path.read_bytes()
    assert saved['catalog'] == draft and saved['revision'] != original['revision']
    with pytest.raises(Exception, match='changed'):
        operation(project, request, lambda proposal: {'decision': 'accept'})
    assert path.read_bytes() == before
    draft['runtimes']['shared']['providers']['first']['models']['model']['alias'] = 'Changed'

    def concurrent_edit(proposal: dict) -> dict:
        """Simulate an external editor while native approval is pending."""
        path.write_bytes(before + b'\n')
        return {'decision': 'accept'}

    with pytest.raises(Exception, match='changed during review'):
        operation(project, {**request, 'catalog': draft, 'expected_revision': saved['revision']}, concurrent_edit)
    assert path.read_bytes() == before + b'\n'


def test_global_desktop_bridge_requires_the_native_review(project: Path) -> None:
    """The existing host pipe exposes the same safe catalog and save semantics."""
    from test_desktop_settings import call

    current = call(project, {'scope': 'user', 'action': 'read'})[-1]['result']
    request = {'scope': 'user', 'action': 'save', 'catalog': catalog(project),
               'expected_revision': current['revision']}
    assert call(project, request, 'decline')[-1]['failed'] is True
    assert not Path(current['path']).exists()
    replies = call(project, request, 'accept')
    assert replies[0]['review']['scope'] == 'user'
    assert replies[-1]['result']['applied'] is True
    assert replies[-1]['result']['catalog'] == request['catalog']


def test_failed_review_does_not_create_a_catalog(project: Path) -> None:
    """A failed native review is not treated as permission to write."""
    current = operation(project, {})

    def unavailable(proposal: dict) -> dict:
        """Represent loss of the selected host approval channel."""
        raise RuntimeError('review unavailable')

    with pytest.raises(RuntimeError, match='unavailable'):
        operation(project, {'action': 'save', 'expected_revision': current['revision'],
                            'catalog': catalog(project)}, unavailable)
    assert not Path(current['path']).exists()


@pytest.mark.parametrize('field,value', [
    ('api_key_env', 'secret-value!'), ('base_url', 'https://user:password@example.org'),
    ('base_url', 'https://example.org?key=secret'), ('credential', 'secret'),
    ('api', 'unknown'),
])
def test_invalid_provider_never_saves(project: Path, field: str, value: str) -> None:
    """Reject credentials and unknown routing parameters at the public boundary."""
    document = catalog(project)
    document['runtimes']['shared']['providers']['first'][field] = value
    with pytest.raises(ValueError):
        save(project, document)
    assert not Path(operation(project, {})['path']).exists()


def test_role_reference_and_legacy_resolution(project: Path) -> None:
    """Full origins distinguish identical ids, aliases never select the model."""
    save(project, catalog(project))
    roles_path = project / '.graphtraj/roles.yml'
    roles_path.write_text(yaml.safe_dump({'roles': {
        'one': {'connection': 'shared/first/model', 'reasoning_effort': 'low'},
        'two': {'connection': 'shared/second/model'},
        'old': {'runtime': 'codex', 'model': 'legacy'},
    }}))
    roles = load_project_roles(project)
    assert roles.preset('one').model == roles.preset('two').model == 'actual-model'
    assert roles.preset('one').base_url != roles.preset('two').base_url
    assert roles.preset('one').runtime_home == roles.preset('two').runtime_home
    assert roles.preset('old').model == 'legacy'
    for fields in ({'connection': 'shared/first/unknown'},
                   {'connection': 'shared/first/model', 'reasoning_effort': 'high'},
                   {'connection': 'shared/first/model', 'model': 'override'}):
        roles_path.write_text(yaml.safe_dump({'roles': {'one': fields}}))
        with pytest.raises(Exception):
            load_project_roles(project).preset("one")


def test_codex_recovery_requires_exact_key_and_home(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Resume uses captured routing and cannot fall back to an official key."""
    adapter = select_runtime_adapter('codex')
    monkeypatch.setenv('OPENAI_API_KEY', 'official-must-not-leak')
    with pytest.raises(RuntimeAdapterError, match='missing'):
        adapter.recovery_environment({'base_url': 'https://custom.example', 'api_key_env': 'CUSTOM_KEY'})
    monkeypatch.setenv('CUSTOM_KEY', 'custom-only')
    connection = {'base_url': 'https://custom.example', 'api_key_env': 'CUSTOM_KEY',
                  'runtime_home': str(project.parent / 'native')}
    env = adapter.recovery_environment(connection)
    assert env['OPENAI_API_KEY'] == 'custom-only' and env['CODEX_HOME'] == connection['runtime_home']
    assert adapter.recovery_environment({'base_url': 'http://localhost:8000'})['OPENAI_API_KEY'] == ''
    assert os.environ['OPENAI_API_KEY'] == 'official-must-not-leak'


def test_pi_reference_captures_overlay(project: Path, pi_environment: dict,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """A shared native Home yields separate captured custom routes for recovery."""
    monkeypatch.setenv('CUSTOM_KEY', 'controlled-secret-value')
    monkeypatch.setenv('OTHER_KEY', 'other-private')
    save(project, catalog(project, 'pi'))
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({'roles': {
        'one': {'connection': 'shared/first/model', 'pi': pi_environment},
        'two': {'connection': 'shared/second/model', 'pi': pi_environment},
    }}))
    adapter = select_runtime_adapter('pi')
    worktree = project.parent / 'worktree'
    worktree.mkdir()
    from graphtraj.interfaces import hosted_cli

    monkeypatch.setattr(hosted_cli, 'cli_connection', lambda *args, **kwargs: nullcontext('/bound-channel'))
    contexts = []
    for name in ('one', 'two'):
        settings = load_project_roles(project).preset(name)
        role = resolve_child_role(name, settings, project)
        context = adapter.preflight_runtime_context(
            harness_root=project, git_common_directory=project / '.git', role=role,
            worktree=project.parent / "worktree", evidence=project.parent / 'evidence', requested_skills=(),
        ).finalize()
        contexts.append(context.launch_document())
    assert contexts[0]['adapter_request']['base_url'] != contexts[1]['adapter_request']['base_url']
    assert contexts[0]['adapter_request']['agent_dir'] == contexts[1]['adapter_request']['agent_dir']
    assert 'controlled-secret-value' not in json.dumps(contexts)
    save(project, {'version': 1, 'runtimes': {}})
    assert adapter.recovery_environment(contexts[0]['connection']) == {'CUSTOM_KEY': 'controlled-secret-value'}
    for index, captured in enumerate(contexts):
        directory = project.parent / f'control-{index}'
        directory.mkdir()
        trace = project.parent / f'trace-{index}.jsonl'
        session = None
        for resume in (False, True):
            turn = adapter.managed_execution(
                captured['adapter_request'], 'controlled route', directory,
                lambda session, pid: None, {}, trace_file=trace, expected_session=session,
                session_created=lambda session, pid: None,
            )
            result = turn.run()
            if resume:
                assert result['session_id'] == session
            session = result['session_id']
            assert result['outcome'] == 'completed'
            native = yaml.safe_load((directory / 'session.yml').read_text())
            assert native['model'] == {'provider': 'graphtraj-role', 'id': 'actual-model'}


def test_dsh_discovery_is_explicitly_unsupported(project: Path) -> None:
    """No static catalog is represented as account availability."""
    save(project, catalog(project, 'dsh'))
    result = operation(project, {'action': 'discover', 'runtime': 'shared'})['discovery']
    assert result['status'] == 'unsupported' and result['account_access'] == 'unknown'
    assert result['models'] == []


def test_dsh_reference_home_and_overrides_survive_resume(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The controlled native boundary receives private overlays for a shared Home."""
    from graphtraj.interfaces import hosted_cli
    from graphtraj.runtimes.dsh import adapter as dsh_adapter, execution
    from test_dsh_runtime import NativePeer, TaggedLoader

    monkeypatch.setenv('CUSTOM_KEY', 'first-route-secret')
    monkeypatch.setenv('OTHER_KEY', 'second-route-secret')
    document = catalog(project, 'dsh')
    native_home = Path(document['runtimes']['shared']['home'])
    native_home.mkdir()
    marker = native_home / 'cordis.patch.yml'
    marker.write_text('[]\n')
    package = project.parent / 'installed-dsh'
    (package / 'bin').mkdir(parents=True)
    (package / 'package.json').write_text('{"version":"0.2.0-rc.2"}')
    monkeypatch.setattr(dsh_adapter.shutil, 'which', lambda name: str(package / 'bin' / name))
    monkeypatch.setattr(hosted_cli, 'cli_connection', lambda *args, **kwargs: nullcontext('/bound-channel'))
    observed = []

    class Peer(NativePeer):
        """Interpret the supplied native overlay, without making vendor requests."""

        def __init__(self, executable: str, cwd: Path, environment: dict) -> None:
            """Record the actual connection and service-local patch before startup."""
            patch = Path(environment['GRAPHTRAJ_DSH_PATCH'])
            rows = yaml.load(patch.read_text(), Loader=TaggedLoader)
            route = next(row['config'] for row in rows if row.get('id') == 'llm-deepseek')
            observed.append((environment['DSH_HOME'], route))
            assert 'route-secret' not in patch.read_text()
            super().__init__(executable, cwd, {**environment, 'DSH_HOME': str(patch.parents[2])})
            self.frames.append('turn/end')

    monkeypatch.setattr(execution, 'DshService', Peer)
    save(project, document)
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({'roles': {
        'one': {'connection': 'shared/first/model'},
        'two': {'connection': 'shared/second/model'},
    }}))
    adapter = select_runtime_adapter('dsh')
    captures = []
    for name in ('one', 'two'):
        role = resolve_child_role(name, load_project_roles(project).preset(name), project)
        captures.append(adapter.preflight_runtime_context(
            harness_root=project, git_common_directory=project / '.git', role=role,
            worktree=project, evidence=project.parent / 'evidence', requested_skills=(),
        ).finalize().launch_document())
    save(project, {'version': 1, 'runtimes': {}})
    for index, capture in enumerate(captures):
        directory = project.parent / f'dsh-control-{index}'
        directory.mkdir()
        session = None
        for resume in (False, True):
            turn = adapter.managed_execution(
                capture['adapter_request'], 'controlled route', directory,
                lambda session, pid: None, {}, trace_file=directory / 'trace.jsonl',
                expected_session=session, session_created=lambda session, pid: None,
            )
            result = turn.run()
            if resume:
                assert result['session_id'] == session
            session = result['session_id']
            assert result['outcome'] == 'completed'
    assert marker.read_text() == '[]\n'
    assert all(home == str(native_home) for home, _ in observed)
    assert [route['apiKeyEnv'] for _, route in observed] == ['CUSTOM_KEY'] * 2 + ['OTHER_KEY'] * 2
    assert observed[0][1]['baseURL'] != observed[2][1]['baseURL']


def test_codex_references_reach_fresh_and_resumed_native_sessions(
    project: Path, peer: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Controlled native sessions receive separate routes with the same Home."""
    monkeypatch.setenv('CUSTOM_KEY', 'first-secret')
    monkeypatch.setenv('OTHER_KEY', 'second-secret')
    save(project, catalog(project))
    approval = {'approval': {'model': 'review', 'base_url': 'https://review.example/v1',
                             'api_key_env': 'REVIEW_KEY'}}
    request = {'change': {'set_presets': {
        name: {'connection': f'shared/{provider}/model', 'codex': approval}
        for name, provider in [('one', 'first'), ('two', 'second')]
    }}}
    bind(project, recovery_reviewer=lambda proposal: {'decision': 'accept'})(
        {'action': 'execute', 'feature': 'role_organization', 'arguments': request},
    )
    contexts = [codex_context(project.parent / name, peer, resolve_child_role(
        name, load_project_roles(project).preset(name), project,
    )) for name in ('one', 'two')]
    retained = [item.launch_document() for item in contexts]
    save(project, {'version': 1, 'runtimes': {}})

    async def exercise() -> None:
        """Inspect observable native requests on both first launch and resume."""
        for index, context in enumerate(contexts):
            session_id = None
            for resume in (False, True):
                async with CodexAppServer(command=[str(peer)], cwd=project,
                                          environment=context.runtime_environment()) as server:
                    session = (await server.resume_session(context, session_id) if resume
                               else await server.create_session(context))
                    session_id = session.thread_id
                    turn = await server.start_execution(session, 'configuration')
                    observed = json.loads((await server.wait(turn, timeout=2))['last_agent_message'])
                    provider = observed['config']['model_providers']['graphtraj-role']
                    assert observed['model'] == 'actual-model'
                    assert provider['base_url'] == ['https://provider.example/v1',
                                                    'http://localhost:8080/v1'][index]
                    assert provider['env_key'] == ['CUSTOM_KEY', 'OTHER_KEY'][index]
                    assert provider['requires_openai_auth'] is False
            assert context.launch_document() == retained[index]

    asyncio.run(exercise())
    adapter = select_runtime_adapter('codex')
    assert adapter.recovery_environment(retained[0]['connection'])['CODEX_HOME'] == \
        adapter.recovery_environment(retained[1]['connection'])['CODEX_HOME']


@pytest.mark.skipif(os.environ.get('GRAPHTRAJ_NATIVE_METADATA') != '1',
                    reason='Opt-in installed Runtime metadata query; never inference.')
@pytest.mark.parametrize('runtime', ['codex', 'pi'])
def test_installed_runtime_metadata(project: Path, runtime: str) -> None:
    """Exercise actual public metadata on an isolated native Home without turns."""
    document = catalog(project, runtime)
    native_home = Path(document['runtimes']['shared']['home'])
    native_home.mkdir()
    save(project, document)
    result = operation(project, {'action': 'discover', 'runtime': 'shared'})['discovery']
    assert result['status'] == 'available', result
    assert result['account_access'] == 'unknown'
    print(f"{runtime}: native metadata, {len(result['models'])} models; account access unknown; no inference")
