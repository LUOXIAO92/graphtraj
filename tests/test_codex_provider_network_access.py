"""Task345 provider grant is narrow, reversible and subordinate to explicit deny."""
import copy
from pathlib import Path

import pytest
from graphtraj.runtimes.codex.local_websocket import project_access
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


def request_and_connection(tmp_path: Path, domains: dict) -> tuple[dict, dict]:
    """Create a native request at the existing scoped resource projection seam."""
    request = {
        'worktree_path': str(tmp_path), 'arguments': ['codex', 'exec'],
        'session_parameters': {'config': {
            'default_permissions': 'scoped', 'features': {'network_proxy': True},
            'approvals_reviewer': 'auto_review',
            'permissions': {'scoped': {
                'extends': ':workspace',
                'filesystem': {'/credential-home': 'none'},
                'network': {'enabled': True, 'domains': copy.deepcopy(domains),
                            'unix_sockets': {'/existing.sock': 'allow'}},
            }},
        }},
    }
    connection = {
        'url': 'ws://127.0.0.1:45345/rpc', 'codex_home': str(tmp_path / 'home'),
        'token_file': str(tmp_path / 'token'), 'worktrees': [str(tmp_path)],
    }
    return request, connection


@pytest.mark.parametrize('prior', [None, 'allow'])
def test_provider_grant_restores_previous_policy(tmp_path: Path, prior: str | None) -> None:
    """Withdrawal restores provider policy, unrelated denies, filesystem and approval."""
    domains = {'unrelated.example': 'deny'}
    if prior is not None:
        domains['chatgpt.com'] = prior
    request, connection = request_and_connection(tmp_path, domains)
    before = copy.deepcopy(request['session_parameters'])
    project_access(request, connection)
    policy = request['session_parameters']['config']['permissions']['scoped']
    assert policy['network']['domains'] == {**domains, '127.0.0.1': 'allow', 'chatgpt.com': 'allow'}
    assert policy['filesystem']['/credential-home'] == 'none'
    assert request['session_parameters']['config']['approvals_reviewer'] == 'auto_review'
    project_access(request, None)
    assert request['session_parameters'] == before


@pytest.mark.parametrize('after_prior_grant', [False, True])
def test_explicit_provider_deny_is_never_granted(tmp_path: Path, after_prior_grant: bool) -> None:
    """An initial or newly introduced deny survives a rejected projection."""
    request, connection = request_and_connection(tmp_path, {})
    if after_prior_grant:
        project_access(request, connection)
    domains = request['session_parameters']['config']['permissions']['scoped']['network']['domains']
    domains['chatgpt.com'] = 'deny'
    with pytest.raises(RuntimeAdapterError):
        project_access(request, connection)
    assert domains['chatgpt.com'] == 'deny'


def test_other_worktree_gets_no_provider_grant(tmp_path: Path) -> None:
    """Configured service access remains limited to its named worktrees."""
    request, connection = request_and_connection(tmp_path, {})
    request['worktree_path'] = str(tmp_path / 'unrelated')
    before = copy.deepcopy(request['session_parameters'])
    project_access(request, connection)
    assert request['session_parameters'] == before


def test_old_projection_can_resume_and_withdraw(tmp_path: Path) -> None:
    """Retained pre-provider grants can adopt the change without losing old rules."""
    request, connection = request_and_connection(tmp_path, {'unrelated.example': 'deny'})
    before = copy.deepcopy(request['session_parameters'])
    project_access(request, connection)
    del request['local_websocket_projection']['provider_domain']
    del request['session_parameters']['config']['permissions']['scoped']['network']['domains']['chatgpt.com']
    project_access(request, connection)
    project_access(request, None)
    assert request['session_parameters'] == before
