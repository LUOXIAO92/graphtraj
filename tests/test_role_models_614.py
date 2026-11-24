"""Task 614: subagents ``models`` lists the project roles GraphTraj's create can select.

Discovery is graftling's own (every GraphTraj host serves it), so a feature it
lists must be executable through GraphTraj's backend: ``models`` answers with
the roles' catalog choices grouped by provider, key variable names only.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from graftling import Caller, bind
from graftling.discovery import handle_request

from graphtraj.interfaces.agents import GraphTrajAgents
from test_provider_selection import project  # noqa: F401 - pytest fixture

KEY_ENV = 'FAKE614_KEY'
SECRET  = 'fake-614-secret-never-shown'


@pytest.fixture
def roles_project(project: Path, monkeypatch: pytest.MonkeyPatch) -> Path:  # noqa: F811
    """Claude roles on two catalog providers plus an inline one; one Codex role."""
    monkeypatch.setenv(KEY_ENV, SECRET)
    catalog = Path.home() / '.graphtraj/connections.yml'
    catalog.parent.mkdir(parents=True)
    catalog.write_text(yaml.safe_dump({'version': 1, 'runtimes': {
        'claude-home': {'runtime': 'claude', 'providers': {
            'anthropic': {'models': {'opus': {'id': 'claude-opus-5-5', 'source': 'manual',
                                              'supported_efforts': ['low', 'high']}}},
            'gateway': {'base_url': 'https://gateway.invalid/v1', 'api_key_env': KEY_ENV,
                        'models': {'sonnet': {'id': 'claude-sonnet-5-5', 'source': 'manual'}}},
        }},
        'codex-home': {'runtime': 'codex', 'providers': {
            'openai': {'models': {'gpt': {'id': 'gpt-5', 'source': 'manual'}}}}},
    }}))
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {
            'claude': {'connection': 'claude-home/anthropic/opus'},
            'routed': {'connection': 'claude-home/gateway/sonnet'},
            'inline': {'runtime': 'claude', 'model': 'claude-haiku-5-5'},
            'coder':  {'connection': 'codex-home/openai/gpt'},
        },
        'role_tree': {'claude': {}, 'routed': {}, 'inline': {}, 'coder': {}},
    }))
    return project


def models(root: Path, caller: Caller | None = None, **arguments: str):
    """Execute subagents models through graftling's bound callback with GraphTraj's backend."""
    call = bind(GraphTrajAgents(root), caller or Caller('claude-native', None, 'session-614', 'claude'))
    return call({'action': 'models', **arguments})


def test_models_groups_the_roles_create_can_select_by_provider(roles_project: Path) -> None:
    """Each claude role is one model in its catalog provider's group; the inline role is provider-null."""
    result = models(roles_project, runtime='claude')
    assert not result.failed, result.document
    listed = result.document['result']
    assert listed['runtime'] == 'claude' and listed['status'] == 'available'
    assert 'runtime_connections discover' in listed['message']
    assert [group['provider'] for group in listed['groups']] == ['anthropic', None, 'gateway']
    by_role = {model['configuration']: model for model in listed['models']}
    assert set(by_role) == {'claude', 'routed', 'inline'}  # not the Codex role
    assert by_role['claude'] == {'id': 'claude-opus-5-5', 'provider': 'anthropic', 'configuration': 'claude',
                                 'connection': 'claude-home/anthropic/opus', 'api_key_env': None,
                                 'supported_efforts': ['low', 'high']}
    assert by_role['routed'] == {'id': 'claude-sonnet-5-5', 'provider': 'gateway', 'configuration': 'routed',
                                 'connection': 'claude-home/gateway/sonnet', 'api_key_env': KEY_ENV,
                                 'supported_efforts': None}
    # A role without a catalog provider still is a create choice, in the provider-null group.
    assert by_role['inline'] == {'id': 'claude-haiku-5-5', 'provider': None, 'configuration': 'inline',
                                 'connection': None, 'api_key_env': None, 'supported_efforts': None}
    assert [model['configuration'] for model in listed['groups'][1]['models']] == ['inline']


def test_models_provider_filter_and_invalid_provider_match_create(roles_project: Path) -> None:
    """provider keeps one group; a provider no candidate role uses is refused as create refuses it."""
    result = models(roles_project, runtime='claude', provider='gateway')
    assert not result.failed, result.document
    assert [group['provider'] for group in result.document['result']['groups']] == ['gateway']
    assert [model['configuration'] for model in result.document['result']['models']] == ['routed']

    refused = models(roles_project, runtime='claude', provider='elsewhere')
    assert refused.failed and refused.document['error']['code'] == 'invalid-provider', refused.document
    assert "['anthropic', 'gateway']" in refused.document['error']['message']

    other = models(roles_project, runtime='codex')
    assert [model['configuration'] for model in other.document['result']['models']] == ['coder']


def test_models_shows_key_names_only_and_any_caller_may_read(roles_project: Path) -> None:
    """The key variable's value never appears; a Task member caller reads the same list."""
    for caller in (None, Caller('graphtraj-runner', 'T614-engineer', None, 'claude')):
        result = models(roles_project, caller, runtime='claude')
        assert not result.failed, result.document
        text = json.dumps(result.document)
        assert KEY_ENV in text and SECRET not in text


def test_every_feature_graftling_discovers_for_graphtraj_executes_models(roles_project: Path) -> None:
    """What the shared matcher lists is what GraphTraj's backend executes: models is not refused."""
    call = bind(GraphTrajAgents(roles_project), Caller('claude-native', None, 'session-614', 'claude'))
    listed = handle_request({'action': 'discover', 'query': ''}, call)
    features = [item['feature'] for item in listed.document['features']]
    assert 'models' in features

    described = handle_request({'action': 'describe', 'feature': 'models'}, call)
    assert not described.failed, described.document
    executed = handle_request({'action': 'execute', 'feature': 'models', 'arguments': {'runtime': 'claude'}}, call)
    assert not executed.failed, executed.document
    assert executed.document['result']['groups'] and SECRET not in json.dumps(executed.document)

    # No feature the matcher lists is answered not-implemented by GraphTraj for want of an implementation.
    for feature, arguments in {'models': {'runtime': 'codex'}, 'status': {}}.items():
        assert feature in features
        answer = handle_request({'action': 'execute', 'feature': feature, 'arguments': arguments}, call)
        assert (answer.document.get('error') or {}).get('code') != 'not-implemented', answer.document
