"""Explicit socket access crosses native start/resume without widening identity."""

import copy
import json
from pathlib import Path

import pytest

from graphtraj.configuration.project_roles import RolePreset
from graphtraj.configuration.role_definitions import ResolvedChildRole
from graphtraj.runtimes.codex.managed_session import CodexManagedExecution
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError
from test_codex_app_server import context, peer
from test_codex_approval import resume_settings


@pytest.mark.parametrize('granted', [False, True])
def test_scoped_sockets_apply_on_start_and_same_session_resume(
    tmp_path: Path,
    peer: Path,
    monkeypatch: pytest.MonkeyPatch,
    granted: bool,
) -> None:
    """The native peer sees only the selected paths; removal denies old grants."""
    worktree = tmp_path / 'worktree'
    sockets = [str(tmp_path / 'control.sock'), str(tmp_path / 'target.sock')]
    settings = {'unix_sockets': {str(worktree): sockets}}
    role = ResolvedChildRole('temporary-role', 'Keep native permissions.',
                            RolePreset('codex', 'chosen-model', None, None,
                                       codex=settings if granted else None))
    request = context(worktree, peer, role).launch_document()['adapter_request']
    before = copy.deepcopy(request)
    log = tmp_path / 'wire.jsonl'
    monkeypatch.setenv('PEER_PROTOCOL_LOG', str(log))
    monkeypatch.setenv('PEER_NATIVE_ROLLOUT', str(tmp_path / 'native'))
    directory = tmp_path / 'session'
    directory.mkdir()
    first = CodexManagedExecution(request, 'configuration', directory, lambda *_: None,
                                  {}, directory / 'events.jsonl').run()
    assert first['outcome'] == 'completed', first
    resume_settings(tmp_path, directory, monkeypatch,
                    {'unix_sockets': {str(worktree): [] if granted else sockets}}, {})
    second = CodexManagedExecution(request, 'configuration', directory, lambda *_: None,
                                   {}, directory / 'events.jsonl',
                                   expected_session=first['session_id']).run()
    assert second['outcome'] == 'completed', second
    assert second['session_id'] == first['session_id']
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    params = [call['params'] for call in calls if call.get('method') in {'thread/start', 'thread/resume'}]
    assert len(params) == 2
    original = before['session_parameters']['config']
    for index, native in enumerate(params):
        config = native['config']
        profile = config['permissions'][config['default_permissions']]
        if index == 0 and not granted:
            assert 'network' not in profile
        else:
            expected = 'deny' if index == 1 and granted else 'allow'
            assert profile['network']['unix_sockets'] == dict.fromkeys(sockets, expected)
            assert profile['network']['dangerously_allow_all_unix_sockets'] is False
            assert profile['network']['allow_local_binding'] is False
            assert config['features']['network_proxy'] is True
        assert profile['filesystem'] == original['permissions'][original['default_permissions']]['filesystem']
        assert config.get('approvals_reviewer') == original.get('approvals_reviewer')
        assert native['model'] == 'chosen-model'
    assert request == before


@pytest.mark.parametrize('paths', [['relative.sock'], ['/tmp/*'], ['/tmp/../other.sock'], 'all'])
def test_invalid_socket_grants_fail_preflight(tmp_path: Path, peer: Path, paths: object) -> None:
    """No wildcard, relative path or unbounded grant reaches the Runtime."""
    role = ResolvedChildRole('temporary-role', '', RolePreset(
        'codex', 'chosen-model', None, None,
        codex={'unix_sockets': {str(tmp_path): paths}},
    ))
    with pytest.raises(RuntimeAdapterError, match='codex.unix_sockets'):
        context(tmp_path, peer, role)


def test_other_worktree_does_not_receive_socket_access(tmp_path: Path, peer: Path) -> None:
    """A reusable role does not share one Task's socket grants with other Tasks."""
    role = ResolvedChildRole('temporary-role', '', RolePreset(
        'codex', 'chosen-model', None, None,
        codex={'unix_sockets': {str(tmp_path / 'other'): ['/tmp/authorized.sock']}},
    ))
    config = context(tmp_path, peer, role).session_document()['adapter_request']['config']
    assert 'network' not in config['permissions'][config['default_permissions']]
    assert 'network_proxy' not in config['features']
