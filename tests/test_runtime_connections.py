"""User connection behavior through public tools and the existing Runtime seam."""

import copy
import asyncio
from contextlib import nullcontext
import json
import os
import shutil
import subprocess
from typing import Any, Callable
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


NATIVE_METADATA = os.environ.get('GRAPHTRAJ_NATIVE_METADATA') == '1'
NATIVE_PI = shutil.which('pi')


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


def operation(project: Path, arguments: dict, reviewer: Callable[[dict], dict] | None = None) -> dict:
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
    assert env == {'CUSTOM_KEY': 'custom-only', 'CODEX_HOME': connection['runtime_home']}
    assert adapter.recovery_environment({'base_url': 'http://localhost:8000'})['OPENAI_API_KEY'] == ''
    assert adapter.recovery_environment({'base_url': 'https://api.openai.com/v1'})['OPENAI_API_KEY'] == 'official-must-not-leak'
    assert os.environ['OPENAI_API_KEY'] == 'official-must-not-leak'


def test_pi_reference_captures_overlay(project: Path, pi_environment: dict,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """A shared native Home yields separate captured custom routes for recovery."""
    monkeypatch.setenv('CUSTOM_KEY', 'controlled-secret-value')
    monkeypatch.setenv('OTHER_KEY', 'other-private')
    document = catalog(project, 'pi')
    original_home = Path(document['runtimes']['shared']['home'])
    original_home.mkdir()
    original_models = json.dumps({'providers': {'original': {'models': [{'id': 'original-model'}]}}})
    (original_home / 'models.json').write_text(original_models)
    (original_home / 'auth.json').write_text('{"graphtraj-role":{"type":"api_key","key":"controlled-old-key"}}')
    original_auth_stat = (original_home / 'auth.json').stat()
    save(project, document)
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({'roles': {
        'one': {'connection': 'shared/first/model', 'pi': pi_environment},
        'two': {'connection': 'shared/second/model', 'pi': pi_environment},
    }}))
    adapter = select_runtime_adapter('pi')
    worktree = project.parent / 'worktree'
    worktree.mkdir()
    from graphtraj.interfaces import hosted_cli

    monkeypatch.setattr(hosted_cli, 'cli_connection', lambda *args, **kwargs: nullcontext('/bound-channel'))
    native_homes = set()
    original_popen = subprocess.Popen

    def observe_process(*args: object, **kwargs: Any) -> subprocess.Popen:
        """Observe the native process environment without retaining any credential."""
        environment = kwargs.get('env', {})
        if environment.get('PI_ASB_NO_ALIAS_PROMPT') == '1':
            native_homes.add(environment['PI_CODING_AGENT_DIR'])
        return original_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, 'Popen', observe_process)
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
            if resume:
                # Reproduce the retained links made by the prior implementation.
                agent = trace.with_suffix('.pi') / 'agent'
                for name in ('models.json', 'auth.json'):
                    (agent / name).unlink(missing_ok=True)
                    (agent / name).symlink_to(original_home / name)
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
            agent = trace.with_suffix('.pi') / 'agent'
            assert not (agent / 'models.json').is_symlink()
            assert not (agent / 'auth.json').is_symlink()
            assert (original_home / 'models.json').read_text() == original_models
            assert (original_home / 'auth.json').stat() == original_auth_stat
            assert 'controlled-secret-value' not in (directory / 'pi-process.json').read_text()
    if NATIVE_METADATA:
        assert NATIVE_PI is not None
        monkeypatch.setenv('PATH', str(Path(NATIVE_PI).parent) + os.pathsep + os.environ['PATH'])
        assert len(native_homes) == 2
        for home in native_homes:
            save(project, {'version': 1, 'runtimes': {'metadata': {
                'runtime': 'pi', 'home': home, 'providers': {},
            }}})
            discovered = operation(project, {'action': 'discover', 'runtime': 'metadata'})['discovery']
            assert discovered['status'] == 'available', discovered
            assert any(model['provider'] == 'graphtraj-role' and model['id'] == 'actual-model'
                       for model in discovered['models'])
        print('pi: real RPC accepted both generated provider catalogs; no inference')


def test_dsh_discovery_uses_only_the_host_catalog(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Native provider failures stay unknown and no Session/prompt method is called."""
    from graphtraj.runtimes.dsh import service

    calls = []

    class Host:
        """A controlled native host offering a catalog without a Session."""

        def __init__(self, executable: str, cwd: Path, environment: dict) -> None:
            """Require the selected shared native Home at process construction."""
            assert environment['DSH_HOME'] == str(project.parent / 'native')

        def start(self) -> None:
            """Record the native host startup boundary."""
            calls.append('start')

        def rpc(self, method: str) -> dict:
            """Return only the public catalog response shape."""
            calls.append(method)
            return {'groups': [{'id': 'deepseek-official', 'models': [{
                'id': 'deepseek-flash', 'name': 'Flash',
                'reasoning': {'efforts': [{'id': 'low'}, {'id': 'high'}]},
            }]}], 'failures': [{'id': 'unavailable', 'message': 'secret diagnostic'}]}

        def close(self) -> None:
            """Record ownership cleanup even after a failed query."""
            calls.append('close')

    monkeypatch.setattr(service, 'DshService', Host)
    import shutil

    monkeypatch.setattr(shutil, 'which', lambda runtime: 'controlled-dsh')
    save(project, catalog(project, 'dsh'))
    result = operation(project, {'action': 'discover', 'runtime': 'shared'})['discovery']
    assert result['status'] == 'available' and result['account_access'] == 'unknown'
    assert result['models'][0]['supported_efforts'] == ['low', 'high']
    assert result['provider_status']['unavailable'] == 'unknown'
    assert 'secret diagnostic' not in json.dumps(result)
    assert calls == ['start', 'session/modelCatalog', 'close']


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

        def __init__(
            self,
            executable: str,
            cwd: Path,
            environment: dict,
            *,
            profile_patch: Path,
        ) -> None:
            """Record the actual connection and service-local patch before startup."""
            patch = profile_patch
            rows = yaml.load(patch.read_text(), Loader=TaggedLoader)
            route = next(row['config'] for row in rows if row.get('id') == 'llm-deepseek')
            assert next(row for row in rows if row.get('id') == 'config-editor')['disabled']
            assert route['models'] == [{'id': 'actual-model'}]
            observed.append((environment['DSH_HOME'], route))
            assert 'route-secret' not in patch.read_text()
            super().__init__(executable, cwd, {**environment, 'DSH_HOME': str(patch.parents[2])})
            self.frames.append('turn/end')

    monkeypatch.setattr(execution, 'DshService', Peer)
    save(project, document)
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({'roles': {
        'one': {'connection': 'shared/first/model'},
        'two': {'connection': 'shared/second/model'},
        'legacy': {'runtime': 'dsh', 'model': 'deepseek-flash',
                   'base_url': 'https://api.deepseek.com/anthropic'},
    }}))
    adapter = select_runtime_adapter('dsh')
    captures = []
    for name in ('one', 'two'):
        role = resolve_child_role(name, load_project_roles(project).preset(name), project)
        captures.append(adapter.preflight_runtime_context(
            harness_root=project, git_common_directory=project / '.git', role=role,
            worktree=project, evidence=project.parent / 'evidence', requested_skills=(),
        ).finalize().launch_document())
    legacy = resolve_child_role('legacy', load_project_roles(project).preset('legacy'), project)
    legacy_request = adapter.preflight_runtime_context(
        harness_root=project, git_common_directory=project / '.git', role=legacy,
        worktree=project, evidence=project.parent / 'evidence', requested_skills=(),
    ).finalize().launch_document()['adapter_request']
    assert legacy_request['api_key_env'] == 'DEEPSEEK_API_KEY'
    assert legacy_request['unauthenticated'] is False
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
    document = catalog(project)
    document['runtimes']['shared']['providers']['openai'] = {'models': {
        'model': {'id': 'actual-model', 'source': 'native'},
    }}
    save(project, document)
    approval = {'approval': {'model': 'review', 'base_url': 'https://review.example/v1',
                             'api_key_env': 'REVIEW_KEY'}}
    request = {'change': {'set_presets': {
        name: {'connection': f'shared/{provider}/model', 'codex': approval}
        for name, provider in [('one', 'first'), ('two', 'second'), ('native', 'openai')]
    }}}
    bind(project, recovery_reviewer=lambda proposal: {'decision': 'accept'})(
        {'action': 'execute', 'feature': 'role_organization', 'arguments': request},
    )
    contexts = [codex_context(project.parent / name, peer, resolve_child_role(
        name, load_project_roles(project).preset(name), project,
    )) for name in ('one', 'two', 'native')]
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
                    assert observed['model'] == 'actual-model'
                    if index == 2:
                        assert observed['config']['model_provider'] == 'openai'
                        assert set(context.runtime_environment()) == {'CODEX_HOME'}
                        continue
                    provider = observed['config']['model_providers']['graphtraj-role']
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
@pytest.mark.parametrize('runtime', ['codex', 'pi', 'dsh'])
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


@pytest.mark.skipif(os.environ.get('GRAPHTRAJ_NATIVE_METADATA') != '1',
                    reason='Opt-in installed DSH configuration query; never inference.')
def test_installed_dsh_accepts_execution_overlays_without_creating_sessions(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real native host consumes each captured overlay; Session work is stubbed."""
    from graphtraj.interfaces import hosted_cli
    from graphtraj.runtimes.dsh import execution
    from graphtraj.runtimes.dsh.service import DshService

    monkeypatch.setenv('CUSTOM_KEY', 'metadata-only-key')
    monkeypatch.setenv('OTHER_KEY', 'other-metadata-only-key')
    monkeypatch.setattr(hosted_cli, 'cli_connection', lambda *args, **kwargs: nullcontext('/bound-channel'))
    document = catalog(project, 'dsh')
    native_home = Path(document['runtimes']['shared']['home'])
    native_home.mkdir()
    marker = native_home / 'cordis.patch.yml'
    marker.write_text('[]\n')
    observed = []

    class MetadataHost:
        """Replace Agent creation with a real, read-only native catalog query."""

        def __init__(
            self,
            executable: str,
            cwd: Path,
            environment: dict,
            *,
            profile_patch: Path,
        ) -> None:
            """Use the production service with the exact execution environment."""
            self.native = DshService(executable, cwd, environment, profile_patch=profile_patch)

        def start(self) -> None:
            """Start the installed native host, without creating an Agent."""
            self.native.start()

        def rpc(self, method: str, request: dict) -> dict:
            """Stop before Session creation; query only host metadata."""
            assert method == 'session/create'
            observed.append(self.native.rpc('session/modelCatalog'))
            raise RuntimeAdapterError('METADATA_CHECK_COMPLETE', 'Stopped before Session creation.')

        def close(self) -> None:
            """Always reap the owned native metadata service."""
            self.native.close()

    monkeypatch.setattr(execution, 'DshService', MetadataHost)
    save(project, document)
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({'roles': {
        'one': {'connection': 'shared/first/model'},
        'two': {'connection': 'shared/second/model'},
    }}))
    adapter = select_runtime_adapter('dsh')
    for name in ('one', 'two'):
        role = resolve_child_role(name, load_project_roles(project).preset(name), project)
        captured = adapter.preflight_runtime_context(
            harness_root=project, git_common_directory=project / '.git', role=role,
            worktree=project, evidence=project.parent / 'evidence', requested_skills=(),
        ).finalize()
        directory = project.parent / ('native-' + name)
        directory.mkdir()
        turn = adapter.managed_execution(
            captured.launch_document()['adapter_request'], 'must not be sent', directory,
            lambda session, pid: None, {}, trace_file=directory / 'trace.jsonl',
            session_created=lambda session, pid: None,
        )
        with pytest.raises(RuntimeAdapterError, match='Stopped before Session creation'):
            turn.run()
    assert marker.read_text() == '[]\n'
    for result in observed:
        models = [model['id'] for group in result['groups']
                  if group['id'] == 'deepseek-official' for model in group['models']]
        assert models == ['actual-model']
    print('dsh: real host accepted both shared-Home overlays; no Sessions or inference')


@pytest.mark.skipif(not NATIVE_METADATA, reason='requires explicitly enabled native metadata checks')
@pytest.mark.parametrize('provider,model,domain', [
    ('nativecustom', 'native-custom-model', 'custom.invalid'),
    ('openai', 'gpt-4o', 'api.openai.com'),
    ('graphtraj-role', 'local-model', 'localhost'),
])
def test_pi_native_key_precedence_and_destination(
    project: Path,
    pi_environment: dict,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    model: str,
    domain: str,
) -> None:
    """Real Pi resolves native models and runtime keys without receiving a prompt.

    The sandbox wrapper is controlled; this checks native configuration and the
    generated network policy, not OS isolation or provider calling permission.
    """
    assert NATIVE_PI is not None
    from graphtraj.interfaces import hosted_cli

    monkeypatch.setattr(hosted_cli, 'cli_connection', lambda *args, **kwargs: nullcontext('/bound-channel'))
    monkeypatch.setenv('PATH', str(Path(NATIVE_PI).parent) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('CUSTOM_KEY', 'first-explicit-test-key')
    monkeypatch.setenv('OTHER_KEY', 'second-explicit-test-key')
    monkeypatch.setenv('OPENAI_API_KEY', 'ambient-key-must-not-win')
    home = project.parent / 'native'
    (home / 'extensions').mkdir(parents=True)
    original_models = json.dumps({'providers': {'nativecustom': {
        'baseUrl': 'https://custom.invalid/v1', 'api': 'openai-completions',
        'apiKey': 'model-key-must-not-win', 'models': [{'id': 'native-custom-model'}],
    }}})
    (home / 'models.json').write_text(original_models)
    (home / 'auth.json').write_text(json.dumps({provider: {'type': 'api_key', 'key': 'stored-key-must-not-win'}}))
    auth_stat = (home / 'auth.json').stat()
    # Native extension context exposes resolved auth. Persist comparisons only,
    # never credentials; no stream/complete API or prompt is used.
    (home / 'extensions' / 'observe.js').write_text('''
import fs from 'node:fs';
import path from 'node:path';
export default function(pi) {
  pi.on('session_start', async (_event, ctx) => {
    const auth = await ctx.modelRegistry.getApiKeyAndHeaders(ctx.model);
    fs.writeFileSync(path.join(process.env.PI_CODING_AGENT_DIR, 'observed.json'), JSON.stringify({
      first: auth.ok && auth.apiKey === process.env.CUSTOM_KEY,
      second: auth.ok && auth.apiKey === process.env.OTHER_KEY,
      stored: auth.ok && auth.apiKey === 'stored-key-must-not-win',
      local: auth.ok && auth.apiKey === 'local',
      provider: ctx.model.provider, id: ctx.model.id, baseUrl: ctx.model.baseUrl
    }));
  });
}
''')
    worktree = project.parent / 'worktree'
    worktree.mkdir()
    adapter = select_runtime_adapter('pi')
    contexts = []
    manual = provider == 'graphtraj-role'
    for key in ('CUSTOM_KEY', 'OTHER_KEY', None):
        save(project, {'version': 1, 'runtimes': {'shared': {
            'runtime': 'pi', 'home': str(home), 'providers': {provider: {
                **({'api_key_env': key} if key else {}),
                **({'base_url': 'http://localhost:8080/v1', 'api': 'openai-completions'} if manual else {}),
                'models': {'selected': {'id': model, 'source': 'native'}},
            }},
        }}})
        role_fields = {'connection': f'shared/{provider}/selected', 'pi': pi_environment}
        if key is None and not manual:
            role_fields = {'runtime': 'pi', 'model': f'{provider}/{model}',
                           'pi': {**pi_environment, 'agent_dir': str(home)}}
        (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({'roles': {'one': role_fields}}))
        settings = load_project_roles(project).preset('one')
        context = adapter.preflight_runtime_context(
            harness_root=project, git_common_directory=project / '.git',
            role=resolve_child_role('one', settings, project), worktree=worktree,
            evidence=project.parent / 'evidence', requested_skills=(),
        ).finalize().launch_document()
        if not manual:
            assert context['adapter_request']['provider_domain'] == domain
        contexts.append(context)
    save(project, {'version': 1, 'runtimes': {}})
    for index, context in enumerate(contexts):
        directory = project.parent / f'native-control-{index}'
        directory.mkdir()
        trace = project.parent / f'native-trace-{index}.jsonl'
        agent = trace.with_suffix('.pi') / 'agent'
        if index:
            agent.mkdir(parents=True)
            for name in ('auth.json', 'models.json'):
                (agent / name).symlink_to(home / name)
            # Exercise recovery of a captured request predating destination capture.
            context['adapter_request'].pop('provider_domain', None)

        def stop_before_prompt(session: str, pid: int) -> None:
            """Stop at native Session binding before any inference can occur."""
            raise RuntimeAdapterError('METADATA_CHECK_COMPLETE', 'Native configuration observed without inference.')

        turn = adapter.managed_execution(
            context['adapter_request'], 'MUST NOT BE SENT', directory, lambda session, pid: None,
            {}, trace_file=trace, expected_session=None, session_created=stop_before_prompt,
        )
        with pytest.raises(RuntimeAdapterError, match='Native configuration observed'):
            turn.run()
        assert not turn.prompt_started
        observed = json.loads((agent / 'observed.json').read_text())
        assert observed['first'] is (index == 0)
        assert observed['second'] is (index == 1)
        assert observed['stored'] is (index == 2 and not manual)
        assert observed['local'] is (index == 2 and manual)
        assert (observed['provider'], observed['id']) == (provider, model)
        if manual:
            assert not (agent / 'models.json').is_symlink()
        else:
            assert agent.joinpath('models.json').resolve() == home / 'models.json'
        assert (agent / 'auth.json').is_symlink() is (index == 2 and not manual)
        policy = json.loads((directory / 'pi-policy.json').read_text())
        assert domain in policy['network']['allowedDomains']
        assert (home / 'models.json').read_text() == original_models
        current = (home / 'auth.json').stat()
        assert (current.st_ino, current.st_mtime_ns, current.st_size) == (
            auth_stat.st_ino, auth_stat.st_mtime_ns, auth_stat.st_size)
        assert 'explicit-test-key' not in (directory / 'pi-process.json').read_text()
    print(f'pi: native {provider} model/key precedence and destination verified; no inference')

    save(project, {'version': 1, 'runtimes': {'shared': {
        'runtime': 'pi', 'home': str(home), 'providers': {provider: {
            'api_key_env': 'CUSTOM_KEY', 'models': {'selected': {'id': 'unknown-model', 'source': 'native'}},
        }},
    }}})
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({'roles': {'one': {
        'connection': f'shared/{provider}/selected', 'pi': pi_environment,
    }}}))
    settings = load_project_roles(project).preset('one')
    with pytest.raises(RuntimeAdapterError, match='supported native destination'):
        adapter.preflight_runtime_context(
            harness_root=project, git_common_directory=project / '.git',
            role=resolve_child_role('one', settings, project), worktree=worktree,
            evidence=project.parent / 'evidence', requested_skills=(),
        )


def test_pi_key_only_legacy_links_survive_resume(
    project: Path, pi_environment: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retained key-only execution preserves native custom models on recovery."""
    from graphtraj.interfaces import hosted_cli
    from test_pi_runtime import context

    monkeypatch.setattr(hosted_cli, 'cli_connection', lambda *args, **kwargs: nullcontext('/bound-channel'))
    monkeypatch.setenv('CUSTOM_KEY', 'explicit-key-only')
    home = Path(pi_environment['agent_dir'])
    home.mkdir()
    models = json.dumps({'providers': {'nativecustom': {
        'baseUrl': 'https://custom.invalid/v1', 'api': 'openai-completions',
        'apiKey': 'original-model-key', 'models': [{'id': 'native-model'}],
    }}})
    (home / 'models.json').write_text(models)
    (home / 'auth.json').write_text('{"nativecustom":{"type":"api_key","key":"old-stored-key"}}')
    auth_stat = (home / 'auth.json').stat()
    (project / 'worktrees/research').mkdir(parents=True)
    adapter, prepared = context(project, pi_environment, 'nativecustom/native-model', api_key_env='CUSTOM_KEY')
    request = prepared.launch_document()['adapter_request']
    directory = project.parent / 'key-only-control'
    directory.mkdir()
    trace = project.parent / 'key-only.jsonl'
    session = None
    for resume in (False, True):
        agent = trace.with_suffix('.pi') / 'agent'
        if resume:
            for name in ('models.json', 'auth.json'):
                (agent / name).unlink(missing_ok=True)
                (agent / name).symlink_to(home / name)
        turn = adapter.managed_execution(
            request, 'controlled key-only recovery', directory, lambda session, pid: None,
            {}, trace_file=trace, expected_session=session, session_created=lambda session, pid: None,
        )
        result = turn.run()
        assert result['outcome'] == 'completed'
        if resume:
            assert result['session_id'] == session
        session = result['session_id']
        assert (agent / 'models.json').resolve() == home / 'models.json'
        assert not (agent / 'auth.json').is_symlink()
        assert (home / 'models.json').read_text() == models
        assert (home / 'auth.json').stat() == auth_stat
        assert 'explicit-key-only' not in (directory / 'pi-process.json').read_text()
        assert 'custom.invalid' in json.loads((directory / 'pi-policy.json').read_text())['network']['allowedDomains']
