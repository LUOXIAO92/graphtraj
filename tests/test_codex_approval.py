"""Custom approval decisions at the managed Codex request/reply boundary."""

from __future__ import annotations

import asyncio
import copy
import json
import sys
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
import yaml

from graphtraj.configuration.project_configuration import (
    DEFAULT_CONFIG_CONTENT,
    ProjectConfigurationError,
    load_project_configuration,
)
from graphtraj.configuration.project_roles import RolePreset, load_project_roles
from graphtraj.configuration.role_definitions import ResolvedChildRole
from graphtraj.runtimes.codex import approval
from graphtraj.runtimes.codex.app_server import CodexServerRequest
from graphtraj.runtimes.codex.managed_session import CodexManagedExecution
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError
from test_codex_app_server import context, peer


ROUTE = {'model': 'deepseek-flash', 'base_url': 'https://api.deepseek.com',
         'api_key_env': 'DEEPSEEK_API_KEY'}
DEFAULT_ROUTE = {'model': 'default-review', 'base_url': 'https://default.example/v1',
                 'api_key_env': 'DEFAULT_REVIEW_KEY'}


@pytest.fixture(autouse=True)
def work_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep approval-only peers supplied with their explicit work credential."""
    monkeypatch.setenv('WORK_KEY', 'controlled-work-key')


def project_defaults(root: Path, codex: object) -> None:
    """Write project settings through the supported general configuration file."""
    directory = root / '.graphtraj'
    directory.mkdir(parents=True)
    document = yaml.safe_load(DEFAULT_CONFIG_CONTENT)
    document['codex'] = codex
    (directory / 'config.yml').write_text(yaml.safe_dump(document))


def custom_context(tmp_path: Path, peer: Path, route_source: str = 'role'):
    """Resolve production permissions and a distinct approval route."""
    root = tmp_path / 'worktree'
    project_defaults(root, {} if route_source == 'hosted-native' else {'approval': DEFAULT_ROUTE})
    if route_source == 'hosted-native':
        (root / '.codex').mkdir()
        (root / '.codex/config.toml').write_text('approvals_reviewer = "auto_review"\n')
    role = ResolvedChildRole('temporary-role', 'Do not delete files.',
        RolePreset('codex', 'work-model',
                   None if route_source.startswith('hosted-') else 'https://work.example/v1',
                   'WORK_KEY', codex={'approval': ROUTE} if route_source.endswith('role') else None))
    return context(root, peer, role)


def managed(
    tmp_path: Path,
    peer: Path,
    monkeypatch: pytest.MonkeyPatch,
    route_source: str = 'role',
):
    """Use the controlled external peer with the real managed adapter."""
    resolved = custom_context(tmp_path, peer, route_source)
    executable = tmp_path / 'managed-peer'
    executable.write_text('#!' + sys.executable + '\n' +
                          Path(__file__).with_name('managed_codex_peer.py').read_text())
    executable.chmod(0o755)
    request = resolved.launch_document()['adapter_request']
    request['arguments'][0] = str(executable)
    directory = tmp_path / 'session'
    directory.mkdir()
    monkeypatch.setenv('MANAGED_NATIVE_ROOT', str(tmp_path / 'native'))
    monkeypatch.setenv('GRAPHTRAJ_TICKET_ID', '145')
    monkeypatch.setenv('GRAPHTRAJ_ROLE', 'temporary-role')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setenv('DEFAULT_REVIEW_KEY', 'default-key')
    return request, directory


def completion_stub(
    monkeypatch: pytest.MonkeyPatch, decision: str, calls: list, request_id: int | str = 'approval',
) -> None:
    """Capture the actual HTTP request while controlling the provider response."""
    class Provider:
        def open(self, request, timeout: int):
            """Return a provider envelope or simulate transport failure."""
            body = json.loads(request.data)
            calls.append((request, body))
            if decision == 'timeout':
                raise TimeoutError('transport deadline')
            if decision == 'error':
                raise OSError('provider unavailable')
            review = {'request_id': request_id, 'decision': decision, 'rationale': 'test decision'}
            if decision == 'bad-shape':
                review = {'type': 'json_object', 'decision': 'accept', 'rationale': 'test decision'}
            if decision == 'wrong-request':
                review.update(request_id='other', decision='accept')
            content = 'invalid JSON' if decision == 'malformed' else json.dumps(review)
            return BytesIO(json.dumps({'choices': [{'finish_reason': 'stop',
                'message': {'content': content}}]}).encode())
    monkeypatch.setattr(approval, 'build_opener', lambda *args: Provider())


@pytest.mark.parametrize('route_source', ['role', 'default', 'hosted-role', 'hosted-default'])
@pytest.mark.parametrize('decision,expected', [
    ('accept', 'accept'), ('decline', 'decline'), ('acceptForSession', 'error'),
    ('wrong-request', 'error'), ('malformed', 'error'),
    ('timeout', 'error'), ('error', 'error'),
])
def test_model_decision_reaches_only_native_request(
    tmp_path: Path,
    peer: Path,
    monkeypatch: pytest.MonkeyPatch,
    decision: str,
    expected: str,
    route_source: str,
) -> None:
    """Allow/deny/error results cross the native reply seam with exact context and route."""
    request, directory = managed(tmp_path, peer, monkeypatch, route_source)
    calls = []
    completion_stub(monkeypatch, decision, calls)
    worker = CodexManagedExecution(request, 'request: authorize printf APPROVAL_121 only',
        directory, lambda *_: None, {}, directory / 'events.jsonl')
    result = worker.run()
    assert result['outcome'] == ('runtime-error' if expected == 'error' else 'completed')
    replies = list((tmp_path / 'native').glob('*.replies.jsonl'))
    reply = json.loads(replies[0].read_text())
    if expected == 'error':
        assert reply['id'] == 'approval'
        assert reply['error']['code'] == -32603
        assert 'RUNTIME_REQUEST_FAILED' == result['error']['code']
    else:
        assert reply == {'id': 'approval', 'result': {'decision': expected}}
    assert len(calls) == 1
    route = ROUTE if route_source.endswith('role') else DEFAULT_ROUTE
    http, body = calls[0]
    assert http.full_url == route['base_url'] + '/chat/completions'
    key = 'test-key' if route_source.endswith('role') else 'default-key'
    assert http.get_header('Authorization') == 'Bearer ' + key
    assert body['model'] == route['model']
    reviewed = json.loads(body['messages'][1]['content'])
    assert reviewed['request']['command'] == 'printf APPROVAL_121'
    assert reviewed['authorization'] == 'request: authorize printf APPROVAL_121 only'
    assert reviewed['developer_instructions'] == 'Do not delete files.'
    assert reviewed['permissions']
    assert reviewed['allowed_decisions'] == ['accept', 'decline']
    assert worker.context.session_document()['adapter_request']['model'] == 'work-model'
    config = worker.context.session_document()['adapter_request']['config']
    if not route_source.startswith('hosted-'):
        assert config['model_provider'] == 'graphtraj-role'
        assert config['model_providers']['graphtraj-role']['base_url'] == 'https://work.example/v1'
        assert config['model_providers']['graphtraj-role']['env_key'] == 'WORK_KEY'
    else:
        assert config.get('model_provider', 'openai') == 'openai'
    assert request['session_parameters']['config']['approvals_reviewer'] == 'user'
    assert 'test-key' not in json.dumps(reply)


def resume_settings(
    tmp_path: Path,
    directory: Path,
    monkeypatch: pytest.MonkeyPatch,
    codex: dict | None,
    defaults: dict,
    inline: bool = False,
) -> Path:
    """Change current approval settings while retaining Session ownership and time."""
    root = tmp_path / 'harness'
    project_defaults(root, defaults)
    settings = {
        'runtime': 'codex', 'model': 'changed-work-model-must-not-apply',
        'base_url': 'https://changed-work.example', 'worktree_access': 'read',
        **({'codex': codex} if codex is not None else {}),
    }
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({'roles': {'expert': {
        'temporary-role': settings,
    }, 'normal': {'temporary-role': {'runtime': 'codex', 'model': 'other'}}}}))
    batch = root / 'batch.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{
        'ticket_id': '145', 'ticket_name': 'resume-probe',
        'role': {'inline-role': settings} if inline else 'expert.temporary-role',
        'instruction': 'Keep the existing Session.',
    }]}))
    mapping = {
        'role': 'inline-role' if inline else 'temporary-role',
        'role_reference': 'inline-role' if inline else 'expert.temporary-role',
        'retained_batch_file': str(batch), 'ticket_id': '145',
        'session': yaml.safe_load((directory / 'session.yml').read_text())['session'],
        'parent_alias': 'actual-parent',
        'started_at': '2026-09-28T00:00:00Z', 'execution_budget': {'total': 30},
    }
    (directory / 'mapping.yml').write_text(yaml.safe_dump(mapping))
    monkeypatch.setenv('GRAPHTRAJ_HARNESS_ROOT', str(root))
    return root


@pytest.mark.parametrize('initial_source,route_source', [
    ('role', 'role'), ('default', 'default'),
    ('hosted-role', 'hosted-role'), ('hosted-default', 'hosted-default'),
    ('hosted-native', 'hosted-native'), ('hosted-native', 'hosted-default'),
    ('role', 'default'),
])
@pytest.mark.parametrize('inline', [False, True])
def test_resume_refreshes_route_preserving_session_and_work_model(
    tmp_path: Path,
    peer: Path,
    monkeypatch: pytest.MonkeyPatch,
    initial_source: str,
    route_source: str,
    inline: bool,
) -> None:
    """Retained launch requests resume the same native Session using current selection."""
    request, directory = managed(tmp_path, peer, monkeypatch, initial_source)
    originally_native = initial_source == 'hosted-native'
    original = copy.deepcopy(request)
    calls, notices = [], []
    completion_stub(monkeypatch, 'accept', calls, request_id=0)
    monkeypatch.setenv('MANAGED_APPROVAL_REQUEST_ID', '0')

    async def native_reply(
        worker: CodexManagedExecution, native: CodexServerRequest, token: str,
    ) -> None:
        """Reply through the owned native request when native review remains selected."""
        notices.append(native.request_id)
        while worker.execution is None or worker.result is None:
            await asyncio.sleep(0.001)
        outcome = await asyncio.to_thread(worker.operate, {
            'operation': 'reply', 'session': native.params['threadId'],
            'execution_id': native.params['turnId'], 'request_token': token,
            'response': {'decision': 'decline'},
        })
        assert outcome['request_id'] == 0

    monkeypatch.setattr(CodexManagedExecution, '_notify_direct_parent', native_reply)
    first = CodexManagedExecution(request, 'request: printf only', directory,
        lambda *_: None, {}, directory / 'events.jsonl').run()
    new_route = {**ROUTE, 'model': 'new-approval-model', 'base_url': 'https://review.example/v1'}
    native = route_source == 'hosted-native'
    dedicated = route_source.endswith('role')
    resume_settings(tmp_path, directory, monkeypatch,
        {'approval': new_route} if dedicated else None,
        {} if native else {'approval': DEFAULT_ROUTE if dedicated else new_route}, inline)
    mapping_before = (directory / 'mapping.yml').read_bytes()
    # Resume from the serialized launch request, as Runner does, not a new preflight.
    retained = directory / 'launch-request.yml'
    retained.write_text(yaml.safe_dump(request))
    completion_stub(monkeypatch, 'decline', calls, request_id=0)
    resumed = CodexManagedExecution(yaml.safe_load(retained.read_text()),
        'request: do not allow this', directory, lambda *_: None, {},
        directory / 'events.jsonl', expected_session=first['session_id'])
    second = resumed.run()
    assert second['session_id'] == first['session_id']
    assert second['outcome'] == 'completed'
    assert request == original == yaml.safe_load(retained.read_text())
    assert (directory / 'mapping.yml').read_bytes() == mapping_before
    params = resumed.context.session_document()['adapter_request']
    expected = copy.deepcopy(original['session_parameters'])
    if not native:
        expected['approvalsReviewer'] = 'user'
        expected['config']['approvals_reviewer'] = 'user'
    assert params == expected
    assert params['config']['approvals_reviewer'] == ('auto_review' if native else 'user')
    if native:
        assert not calls
        assert notices == [0, 0]
    else:
        assert notices == ([0] if originally_native else [])
        assert len(calls) == (1 if originally_native else 2)
        assert calls[-1][0].full_url == 'https://review.example/v1/chat/completions'
        assert calls[-1][1]['model'] == 'new-approval-model'
        reviewed = json.loads(calls[-1][1]['messages'][1]['content'])
        assert reviewed['request_id'] == 0
        assert reviewed['request']['threadId'] == first['session_id']
    replies = next((tmp_path / 'native').glob('*.replies.jsonl'))
    records = [json.loads(line) for line in replies.read_text().splitlines()]
    assert [record['id'] for record in records] == [0, 0]
    assert [record['result']['decision'] for record in records] == [
        'decline' if originally_native else 'accept', 'decline',
    ]


@pytest.mark.parametrize('decision', ['timeout', 'malformed', 'bad-shape', 'wrong-request'])
def test_resume_review_failure_keeps_native_error(
    tmp_path: Path, peer: Path, monkeypatch: pytest.MonkeyPatch, decision: str,
) -> None:
    """A resumed default review fails once, without another reviewer or repaired ID."""
    request, directory = managed(tmp_path, peer, monkeypatch, 'hosted-default')
    calls = []
    completion_stub(monkeypatch, 'accept', calls)
    first = CodexManagedExecution(request, 'request: first', directory,
        lambda *_: None, {}, directory / 'events.jsonl').run()
    resume_settings(tmp_path, directory, monkeypatch, None, {'approval': DEFAULT_ROUTE})
    completion_stub(monkeypatch, decision, calls)
    result = CodexManagedExecution(request, 'request: resumed', directory,
        lambda *_: None, {}, directory / 'events.jsonl', expected_session=first['session_id']).run()
    assert result['session_id'] == first['session_id']
    assert result['outcome'] == 'runtime-error'
    assert result['error']['code'] == 'RUNTIME_REQUEST_FAILED'
    assert len(calls) == 2
    records = [json.loads(line) for line in
               next((tmp_path / 'native').glob('*.replies.jsonl')).read_text().splitlines()]
    assert records[-1]['id'] == 'approval'
    assert records[-1]['error']['code'] == -32603


@pytest.mark.parametrize('route_source', ['role', 'hosted-role'])
@pytest.mark.parametrize('invalid', [None, {}, 'bad-route'])
def test_resume_invalid_dedicated_route_never_uses_default(
    tmp_path: Path,
    peer: Path,
    monkeypatch: pytest.MonkeyPatch,
    route_source: str,
    invalid: object,
) -> None:
    """A present invalid route fails recovery before HTTP or native launch."""
    request, directory = managed(tmp_path, peer, monkeypatch, route_source)
    calls = []
    completion_stub(monkeypatch, 'accept', calls)
    first = CodexManagedExecution(request, 'request: first', directory,
        lambda *_: None, {}, directory / 'events.jsonl').run()
    resume_settings(tmp_path, directory, monkeypatch, {'approval': invalid}, {'approval': DEFAULT_ROUTE})
    with pytest.raises(RuntimeAdapterError, match='codex.approval'):
        CodexManagedExecution(request, 'request: resumed', directory,
            lambda *_: None, {}, directory / 'events.jsonl', expected_session=first['session_id'])
    assert len(calls) == 1


def test_resume_custom_provider_requires_a_route(
    tmp_path: Path, peer: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Removing all routes cannot silently enable native review for custom work."""
    request, directory = managed(tmp_path, peer, monkeypatch)
    calls = []
    completion_stub(monkeypatch, 'accept', calls)
    first = CodexManagedExecution(request, 'request: first', directory,
        lambda *_: None, {}, directory / 'events.jsonl').run()
    resume_settings(tmp_path, directory, monkeypatch, None, {})
    with pytest.raises(RuntimeAdapterError, match='codex.approval.model'):
        CodexManagedExecution(request, 'request: resumed', directory,
            lambda *_: None, {}, directory / 'events.jsonl', expected_session=first['session_id'])
    assert len(calls) == 1


def test_missing_custom_route_reports_field_and_hosted_keeps_guardian(tmp_path: Path, peer: Path) -> None:
    """Config parsing carries Codex settings; only its adapter interprets them."""
    root = tmp_path / 'harness'
    (root / '.graphtraj').mkdir(parents=True)
    path = root / '.graphtraj/roles.yml'
    path.write_text(yaml.safe_dump({'roles': {'temporary-role': {
        'runtime': 'codex', 'model': 'work', 'base_url': 'https://work.example',
        'codex': {'approval': ROUTE},
    }}}))
    settings = load_project_roles(root).presets['temporary-role']
    role = ResolvedChildRole('temporary-role', 'restrictions', settings)
    resolved = context(tmp_path / 'valid', peer, role)
    assert resolved.launch_document()['adapter_request']['approval'] == ROUTE
    for field in ROUTE:
        missing = {k: v for k, v in ROUTE.items() if k != field}
        with pytest.raises(RuntimeAdapterError, match='codex.approval.' + field):
            context(tmp_path / ('missing-' + field), peer,
                    replace(role, settings=replace(settings, codex={'approval': missing})))
    hosted = tmp_path / 'hosted'
    (hosted / '.codex').mkdir(parents=True)
    (hosted / '.codex/config.toml').write_text('approvals_reviewer = "auto_review"\n')
    request = context(hosted, peer, replace(role, settings=replace(settings, base_url=None, codex=None))).launch_document()['adapter_request']
    assert 'approval' not in request
    assert request['session_parameters']['config']['approvals_reviewer'] == 'auto_review'


@pytest.mark.parametrize('custom', [False, True])
@pytest.mark.parametrize('invalid', [
    None, {}, 'invalid',
    {**ROUTE, 'base_url': 'http://review.example'},
    {**ROUTE, 'api_key_env': 'not-an-env-name'},
    {**ROUTE, 'extra': 'unsupported'},
])
def test_invalid_present_role_never_uses_project_default(
    tmp_path: Path,
    peer: Path,
    custom: bool,
    invalid: object,
) -> None:
    """A configured but invalid role route fails before any approval request."""
    root = tmp_path / 'worktree'
    project_defaults(root, {'approval': DEFAULT_ROUTE})
    role = ResolvedChildRole('temporary-role', 'restrictions',
        RolePreset('codex', 'work-model', 'https://work.example' if custom else None,
                   None, codex={'approval': invalid}))
    with pytest.raises(RuntimeAdapterError, match='codex.approval'):
        context(root, peer, role)


@pytest.mark.parametrize('codex', [None, {}, {'approval': None}, {'approval': {}}])
def test_custom_provider_without_usable_route_fails(
    tmp_path: Path, peer: Path, codex: dict | None,
) -> None:
    """Missing defaults and invalid present defaults cannot permit custom work."""
    root = tmp_path / 'worktree'
    if codex is not None:
        project_defaults(root, codex)
    role = ResolvedChildRole('temporary-role', 'restrictions',
        RolePreset('codex', 'work-model', 'https://work.example', None))
    with pytest.raises(RuntimeAdapterError, match='codex.approval.model'):
        context(root, peer, role)


def test_role_route_precedes_invalid_default(tmp_path: Path, peer: Path) -> None:
    """Only the selected route is validated by the Codex adapter."""
    root = tmp_path / 'worktree'
    project_defaults(root, {'approval': None})
    role = ResolvedChildRole('temporary-role', 'restrictions',
        RolePreset('codex', 'work-model', None, None, codex={'approval': ROUTE}))
    request = context(root, peer, role).launch_document()['adapter_request']
    assert request['approval'] == ROUTE


@pytest.mark.parametrize('codex', [None, [], 'invalid'])
def test_project_codex_requires_mapping(tmp_path: Path, codex: object) -> None:
    """The project config rejects malformed adapter settings at its public loader."""
    project_defaults(tmp_path, codex)
    with pytest.raises(ProjectConfigurationError, match='codex must be a mapping'):
        load_project_configuration(tmp_path)


@pytest.mark.parametrize('decision', ['accept', 'decline'])
def test_permission_request_uses_model_decision(
    tmp_path: Path, peer: Path, monkeypatch: pytest.MonkeyPatch, decision: str,
) -> None:
    """A reviewed permission request returns its exact grant or a model denial."""
    request, directory = managed(tmp_path, peer, monkeypatch)
    calls = []
    completion_stub(monkeypatch, decision, calls)
    result = CodexManagedExecution(request, 'request:permissions for the task', directory,
        lambda *_: None, {}, directory / 'events.jsonl').run()
    assert result['outcome'] == 'completed'
    reply = json.loads(next((tmp_path / 'native').glob('*.replies.jsonl')).read_text())
    expected = {'network': {'enabled': True}} if decision == 'accept' else {}
    assert reply == {'id': 'approval', 'result': {'permissions': expected}}
    reviewed = json.loads(calls[0][1]['messages'][1]['content'])
    assert reviewed['request']['permissions'] == {'network': {'enabled': True}}


@pytest.mark.parametrize('history', ['large-history', 'invalid-history'])
def test_native_history_is_not_replaced_by_an_adapter_denial(
    tmp_path: Path, peer: Path, monkeypatch: pytest.MonkeyPatch, history: str,
) -> None:
    """Long context reaches review; unreadable context uses the native error channel."""
    request, directory = managed(tmp_path, peer, monkeypatch)
    calls = []
    completion_stub(monkeypatch, 'accept', calls)
    result = CodexManagedExecution(request, 'request:' + history, directory,
        lambda *_: None, {}, directory / 'events.jsonl').run()
    reply = json.loads(next((tmp_path / 'native').glob('*.replies.jsonl')).read_text())
    if history == 'large-history':
        assert result['outcome'] == 'completed'
        reviewed = json.loads(calls[0][1]['messages'][1]['content'])
        assert len(reviewed['history'][0]['content']) == 200001
        assert reply['result']['decision'] == 'accept'
    else:
        assert result['outcome'] == 'runtime-error'
        assert reply['error']['code'] == -32603
        assert not calls


def test_official_policy_and_native_compaction_reach_review(
    tmp_path: Path, peer: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Official default rules and current native context reach the provider together."""
    request, directory = managed(tmp_path, peer, monkeypatch)
    calls = []
    completion_stub(monkeypatch, 'accept', calls)
    result = CodexManagedExecution(request, 'request:compacted-context; update scratch.txt only',
        directory, lambda *_: None, {}, directory / 'events.jsonl').run()
    assert result['outcome'] == 'completed'
    messages = calls[0][1]['messages']
    # This asserts the sourced policy reaches the HTTP boundary, not its prose tokens.
    assets = Path(approval.__file__).with_name('policy')
    official = (assets / 'policy_template.md').read_text().rstrip().replace(
        '{{ tenant_policy_config }}', (assets / 'policy.md').read_text().strip())
    assert messages[0]['role'] == 'system'
    assert messages[0]['content'].startswith(official)
    reviewed = json.loads(messages[1]['content'])
    assert reviewed['authorization'].endswith('update scratch.txt only')
    assert reviewed['developer_instructions'] == 'Do not delete files.'
    assert reviewed['turn_context']['model'] == 'work-model'
    assert reviewed['history'] == [
        {'type': 'message', 'role': 'assistant', 'content': [
            {'type': 'output_text', 'text': 'Native current task summary.'}]},
        {'type': 'message', 'role': 'user', 'content': [
            {'type': 'input_text', 'text': 'Keep the protected file unchanged.'}]},
    ]
    assert reviewed['authorization_messages'][0]['content'][0]['text'] == 'Do not delete protected.txt.'
    assert reviewed['authorization_messages'][-1]['content'][0]['text'] == 'Keep the protected file unchanged.'
    assert reviewed['compaction']['message'] == 'Native summary: only update scratch.txt.'
    assert reviewed['compaction']['retained_context']['user_messages'][0]['complete'] is True
    assert [event['questions'][0]['answer'] for event in reviewed['retained_context_events']] == [
        'No.', 'Only scratch.txt.',
    ]
    assert reviewed['request']['command'] == 'printf APPROVAL_121'


@pytest.mark.parametrize('available,decision,expected', [
    (['accept', 'cancel'], 'accept', 'accept'),
    (['accept', 'cancel'], 'decline', 'cancel'),
    (['accept', 'decline', 'cancel'], 'decline', 'decline'),
    (['acceptForSession', 'cancel'], 'accept', 'error'),
])
def test_offered_native_command_decisions_preserve_denial_semantics(
    tmp_path: Path,
    peer: Path,
    monkeypatch: pytest.MonkeyPatch,
    available: list[str],
    decision: str,
    expected: str,
) -> None:
    """Review schema-supported accept/cancel options and return only the offered reply."""
    request, directory = managed(tmp_path, peer, monkeypatch)
    monkeypatch.setenv('MANAGED_APPROVAL_DECISIONS', json.dumps(available))
    monkeypatch.setenv('MANAGED_APPROVAL_REQUEST_ID', '0')
    calls = []
    completion_stub(monkeypatch, decision, calls, request_id=0)
    result = CodexManagedExecution(request, 'request: authorize printf only', directory,
        lambda *_: None, {}, directory / 'events.jsonl').run()
    assert len(calls) == 1
    reviewed = json.loads(calls[0][1]['messages'][1]['content'])
    assert reviewed['request_id'] == 0
    assert reviewed['request']['availableDecisions'] == available
    reply = json.loads(next((tmp_path / 'native').glob('*.replies.jsonl')).read_text())
    assert reply['id'] == 0
    if expected == 'error':
        assert reviewed['allowed_decisions'] == ['decline']
        assert result['outcome'] == 'runtime-error'
        assert reply['error']['code'] == -32603
    else:
        assert reviewed['native_decisions'][decision] == expected
        assert reply['result'] == {'decision': expected}
        assert result['outcome'] == ('interrupted' if expected == 'cancel' else 'completed')


@pytest.mark.parametrize('request_id,malformed', [(0, False), ('0', False), (0, True)])
def test_response_contract_binds_exact_id_without_repairing_live_malformed_shape(
    tmp_path: Path,
    peer: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_id: int | str,
    malformed: bool,
) -> None:
    """JSON mode carries an exact response schema; the observed invalid shape still fails."""
    request, directory = managed(tmp_path, peer, monkeypatch)
    monkeypatch.setenv('MANAGED_APPROVAL_REQUEST_ID', json.dumps(request_id))
    captured = []

    class Provider:
        def open(self, http_request, timeout: int):
            """Inspect the live transport contract and supply a controlled completion."""
            body = json.loads(http_request.data)
            captured.append(body)
            result = {'decision': 'accept', 'rationale': 'The requested action is authorized.'}
            if malformed:
                result['type'] = 'json_object'  # Actual observed invalid provider envelope.
            else:
                result['request_id'] = request_id
            return BytesIO(json.dumps({'choices': [{'finish_reason': 'stop',
                'message': {'content': json.dumps(result)}}]}).encode())

    monkeypatch.setattr(approval, 'build_opener', lambda *args: Provider())
    result = CodexManagedExecution(request, 'request: authorize printf only', directory,
        lambda *_: None, {}, directory / 'events.jsonl').run()
    assert len(captured) == 1
    body = captured[0]
    schema = json.loads(body['messages'][0]['content'].splitlines()[-1])
    assert body['response_format'] == {'type': 'json_object'}
    assert schema['required'] == ['request_id', 'decision', 'rationale']
    assert schema['additionalProperties'] is False
    assert schema['properties']['request_id'] == {
        'type': 'integer' if type(request_id) is int else 'string', 'const': request_id,
    }
    assert schema['properties']['decision']['enum'] == ['accept', 'decline']
    reply = json.loads(next((tmp_path / 'native').glob('*.replies.jsonl')).read_text())
    assert type(reply['id']) is type(request_id)
    assert reply['id'] == request_id
    if malformed:
        assert result['outcome'] == 'runtime-error'
        assert reply['error']['code'] == -32603
    else:
        assert result['outcome'] == 'completed'
        assert reply['result'] == {'decision': 'accept'}
