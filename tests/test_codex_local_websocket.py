"""Controlled existing-service transport and scoped permission adoption."""

import asyncio
import copy
import json
from pathlib import Path

import pytest

from graphtraj.runtimes.codex.app_server import CodexAppServer
from graphtraj.runtimes.codex.local_websocket import project_access, validate_connection
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError
from test_codex_app_server import context, peer


def settings(tmp_path: Path) -> dict:
    """Use an isolated test token, never the proposed deployment secret."""
    token = tmp_path / 'test-token'
    token.write_text('controlled-test-secret')
    return {'url': 'ws://127.0.0.1:45345/rpc', 'codex_home': str(tmp_path / 'home'),
            'token_file': str(token), 'worktrees': [str(tmp_path)]}


class Peer:
    """In-memory native RPC boundary; no listener or Runtime is started."""
    def __init__(self, home: str) -> None:
        self.home = home
        self.messages = asyncio.Queue()
        self.closed = False

    async def send(self, encoded: str) -> None:
        """Reply to initialize and thread/read through ordinary JSON-RPC."""
        message = json.loads(encoded)
        if 'id' in message:
            result = {'codexHome': self.home} if message['method'] == 'initialize' else {'thread': {'id': 'native'}}
            await self.messages.put(json.dumps({'id': message['id'], 'result': result}))

    def __aiter__(self) -> 'Peer':
        """Expose the same asynchronous message contract as websockets."""
        return self

    async def __anext__(self) -> str:
        """Stop on connection close."""
        message = await self.messages.get()
        if message is None:
            raise StopAsyncIteration
        return message

    async def close(self) -> None:
        """Close only the client connection, never the existing service."""
        self.closed = True
        await self.messages.put(None)


@pytest.mark.parametrize('variant', ['valid', 'wrong-token', 'empty-token', 'wrong-home', 'disconnect'])
def test_existing_service_auth_identity_and_disconnect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str,
) -> None:
    """Check the client boundary; this does not claim native authentication acceptance."""
    config = settings(tmp_path)
    if variant in {'wrong-token', 'empty-token'}:
        Path(config['token_file']).write_text('wrong-secret' if variant == 'wrong-token' else '')

    async def run() -> None:
        remote = Peer('/different' if variant == 'wrong-home' else config['codex_home'])
        async def connect(url: str, **kwargs) -> Peer:
            assert url == config['url']
            assert kwargs['proxy'] == 'http://127.0.0.1:12345'
            if kwargs['additional_headers']['Authorization'] != 'Bearer controlled-test-secret':
                raise ValueError('Rejected wrong-secret')
            return remote
        monkeypatch.setattr('websockets.asyncio.client.connect', connect)
        async def no_process(*args, **kwargs) -> None:
            raise AssertionError('A connection must not start any Runtime')
        monkeypatch.setattr(asyncio, 'create_subprocess_exec', no_process)
        client = CodexAppServer(cwd=tmp_path, local_websocket=config,
                                environment={'HTTP_PROXY': 'http://127.0.0.1:12345'})
        if variant in {'wrong-token', 'empty-token', 'wrong-home'}:
            with pytest.raises(RuntimeAdapterError) as caught:
                async with client:
                    pass
            assert 'wrong-secret' not in str(caught.value)
            assert 'controlled-test-secret' not in str(caught.value)
        else:
            async with client:
                assert (await client.read_thread('native'))['id'] == 'native'
                if variant == 'disconnect':
                    await remote.close()
                    await asyncio.sleep(0)
                    with pytest.raises(RuntimeAdapterError):
                        await client.read_thread('native')
            assert remote.closed
    asyncio.run(run())


def test_scoped_grant_and_withdrawal_preserve_other_policy(tmp_path: Path, peer: Path) -> None:
    """An ordinary retained request restores pre-existing host and file decisions."""
    config = settings(tmp_path)
    request = context(tmp_path, peer).launch_document()['adapter_request']
    native = request['session_parameters']['config']
    profile = native['permissions'][native['default_permissions']]
    native['features'] = {**native['features'], 'network_proxy': True}
    profile['network'] = {'enabled': True, 'domains': {'api.example.org': 'allow'},
                          'unix_sockets': {'/existing.sock': 'allow'}}
    baseline = copy.deepcopy(profile)
    project_access(request, config)
    assert profile['network']['domains'] == {'api.example.org': 'allow', '127.0.0.1': 'allow'}
    assert profile['filesystem'][config['token_file']] == 'read'
    retained = copy.deepcopy(request)
    project_access(retained, None)
    after = retained['session_parameters']['config']['permissions'][native['default_permissions']]
    assert after['filesystem'] == baseline['filesystem']
    assert after['network']['domains'] == baseline['network']['domains']
    assert after == baseline
    assert 'local_websocket_projection' not in retained
    assert native.get('approvals_reviewer') == retained['session_parameters']['config'].get('approvals_reviewer')


@pytest.mark.parametrize('url', ['ws://0.0.0.0:45345/rpc', 'ws://127.0.0.1:45346/rpc', 'ws://example.org/rpc'])
def test_unapproved_endpoint_rejected(tmp_path: Path, url: str) -> None:
    """Reject addresses outside this explicitly bounded candidate."""
    config = settings(tmp_path)
    config['url'] = url
    with pytest.raises(RuntimeAdapterError):
        validate_connection(config)


def test_managed_same_session_adopts_then_revokes(
    tmp_path: Path, peer: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real managed adapter sends grant and withdrawal to a controlled native peer."""
    from graphtraj.runtimes.codex.managed_session import CodexManagedExecution
    from test_codex_approval import resume_settings
    import yaml

    worktree = tmp_path / 'worktree'
    worktree.mkdir()
    config = settings(worktree)
    request = context(worktree, peer).launch_document()['adapter_request']
    from graphtraj.runtimes.codex.codex_adapter import apply_unix_socket_access
    apply_unix_socket_access(request, {str(worktree): []})
    directory = tmp_path / 'session'
    directory.mkdir()
    log = tmp_path / 'wire.jsonl'
    monkeypatch.setenv('PEER_PROTOCOL_LOG', str(log))
    monkeypatch.setenv('PEER_NATIVE_ROLLOUT', str(tmp_path / 'native'))
    first = CodexManagedExecution(request, 'first', directory, lambda *_: None,
                                  {}, directory / 'events.jsonl').run()
    assert first['outcome'] == 'completed', first
    root = resume_settings(tmp_path, directory, monkeypatch, {'local_websocket_access': True},
                           {'local_websocket': config})
    execution = CodexManagedExecution(request, 'grant', directory, lambda *_: None,
                                     {}, directory / 'events.jsonl', expected_session=first['session_id'])
    second = execution.run()
    assert second['outcome'] == 'completed', second
    retained = execution.context.launch_document()['adapter_request']
    path = root / '.graphtraj/config.yml'
    document = yaml.safe_load(path.read_text())
    document['codex'] = {}
    path.write_text(yaml.safe_dump(document))
    third = CodexManagedExecution(retained, 'revoke', directory, lambda *_: None,
                                  {}, directory / 'events.jsonl', expected_session=first['session_id']).run()
    assert third['outcome'] == 'completed', third
    assert first['session_id'] == second['session_id'] == third['session_id']
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    params = [c['params'] for c in calls if c.get('method') in {'thread/start', 'thread/resume'}]
    assert len(params) == 3
    profiles = [p['config']['permissions'][p['config']['default_permissions']] for p in params]
    assert profiles[1]['network']['domains']['127.0.0.1'] == 'allow'
    assert profiles[1]['filesystem'][config['token_file']] == 'read'
    assert '127.0.0.1' not in profiles[2].get('network', {}).get('domains', {})
    assert profiles[2] == profiles[0]
    assert all(p['model'] == 'chosen-model' for p in params)


def test_harness_connection_cannot_be_retargeted_by_event(tmp_path: Path) -> None:
    """A selected home must match trusted Harness configuration before any connect."""
    from test_codex_approval import project_defaults
    from graphtraj.runtimes.codex.local_websocket import configured_connection
    config = settings(tmp_path)
    project_defaults(tmp_path, {'local_websocket': config})
    assert configured_connection(tmp_path, config['codex_home']) == config
    with pytest.raises(RuntimeAdapterError, match='another Codex home'):
        configured_connection(tmp_path, '/other-home')
    child = tmp_path / 'unselected'
    child.mkdir()
    assert configured_connection(child, config['codex_home']) is None


@pytest.mark.parametrize('enabled', [False, True])
def test_only_selected_role_receives_native_access(tmp_path: Path, peer: Path, enabled: bool) -> None:
    """Other roles in the same Worktree do not inherit the new local capability."""
    from test_codex_approval import project_defaults
    from graphtraj.configuration.project_roles import RolePreset
    from graphtraj.configuration.role_definitions import ResolvedChildRole
    config = settings(tmp_path)
    project_defaults(tmp_path, {'local_websocket': config})
    role = ResolvedChildRole('temporary-role', '', RolePreset(
        'codex', 'chosen-model', None, None,
        codex={'local_websocket_access': enabled, 'unix_sockets': {str(tmp_path): []}},
    ))
    request = context(tmp_path, peer, role).launch_document()['adapter_request']
    native = request['session_parameters']['config']
    profile = native['permissions'][native['default_permissions']]
    assert (config['token_file'] in profile['filesystem']) is enabled
    assert ('127.0.0.1' in profile.get('network', {}).get('domains', {})) is enabled


@pytest.mark.parametrize('denial', ['host', 'file', 'network'])
def test_existing_denial_is_not_replaced(tmp_path: Path, peer: Path, denial: str) -> None:
    """A resource grant cannot silently override an existing native denial."""
    config = settings(tmp_path)
    request = context(tmp_path, peer).launch_document()['adapter_request']
    native = request['session_parameters']['config']
    profile = native['permissions'][native['default_permissions']]
    native['features'] = {**native['features'], 'network_proxy': True}
    profile['network'] = {'enabled': True}
    if denial == 'file':
        profile['filesystem'][config['token_file']] = 'deny'
    elif denial == 'host':
        profile['network'] = {'enabled': True, 'domains': {'127.0.0.1': 'deny'}}
    else:
        profile['network'] = {'enabled': False}
    with pytest.raises(RuntimeAdapterError):
        project_access(request, config)


@pytest.mark.parametrize('proxy_enabled', [False, True])
def test_no_domains_requires_existing_enforced_proxy(tmp_path: Path, peer: Path, proxy_enabled: bool) -> None:
    """Do not activate a default-deny proxy over previously unmediated networking."""
    config = settings(tmp_path)
    request = context(tmp_path, peer).launch_document()['adapter_request']
    native = request['session_parameters']['config']
    profile = native['permissions'][native['default_permissions']]
    profile['network'] = {'enabled': True}
    native['features'] = {**native['features'], 'network_proxy': proxy_enabled}
    before = copy.deepcopy(request)
    if not proxy_enabled:
        with pytest.raises(RuntimeAdapterError, match='already enabled'):
            project_access(request, config)
        assert request == before
    else:
        project_access(request, config)
        assert profile['network']['domains'] == {'127.0.0.1': 'allow'}
        # On 0.163.0, absent domains under an enabled proxy already denies external hosts.
        # Only the loopback allow is added; no wildcard or external permission is emitted.
        project_access(request, None)
        assert request['session_parameters'] == before['session_parameters']
        assert 'local_websocket_projection' not in request
