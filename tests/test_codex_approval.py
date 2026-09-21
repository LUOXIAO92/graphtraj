"""Custom approval decisions at the managed Codex request/reply boundary."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
import yaml

from graphtraj.configuration.project_roles import RolePreset, load_project_roles
from graphtraj.configuration.role_definitions import ResolvedChildRole
from graphtraj.runtimes.codex import approval
from graphtraj.runtimes.codex.managed_session import CodexManagedExecution
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError
from test_codex_app_server import context, peer


ROUTE = {'model': 'deepseek-flash', 'base_url': 'https://api.deepseek.com',
         'api_key_env': 'DEEPSEEK_API_KEY'}


def custom_context(tmp_path: Path, peer: Path):
    """Resolve production permissions and a distinct approval route."""
    role = ResolvedChildRole('temporary-role', 'Do not delete files.', (),
        RolePreset('codex', 'work-model', 'https://work.example/v1', 'WORK_KEY',
                   codex={'approval': ROUTE}))
    return context(tmp_path / 'worktree', peer, role)


def managed(tmp_path: Path, peer: Path, monkeypatch: pytest.MonkeyPatch):
    """Use the controlled external peer with the real managed adapter."""
    resolved = custom_context(tmp_path, peer)
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
    return request, directory


def completion_stub(monkeypatch: pytest.MonkeyPatch, decision: str, calls: list) -> None:
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
            review = {'request_id': 'approval', 'decision': decision, 'rationale': 'test decision'}
            if decision == 'wrong-request':
                review.update(request_id='other', decision='accept')
            content = 'invalid JSON' if decision == 'malformed' else json.dumps(review)
            return BytesIO(json.dumps({'choices': [{'finish_reason': 'stop',
                'message': {'content': content}}]}).encode())
    monkeypatch.setattr(approval, 'build_opener', lambda *args: Provider())


@pytest.mark.parametrize('decision,expected', [
    ('accept', 'accept'), ('decline', 'decline'), ('acceptForSession', 'decline'),
    ('wrong-request', 'decline'), ('malformed', 'decline'),
    ('timeout', 'decline'), ('error', 'decline'),
])
def test_model_decision_reaches_only_native_request(
    tmp_path: Path, peer: Path, monkeypatch: pytest.MonkeyPatch, decision: str, expected: str,
) -> None:
    """Allow/deny/error results cross the native reply seam with exact context and route."""
    request, directory = managed(tmp_path, peer, monkeypatch)
    calls = []
    completion_stub(monkeypatch, decision, calls)
    worker = CodexManagedExecution(request, 'request: authorize printf APPROVAL_121 only',
        directory, lambda *_: None, {}, directory / 'events.jsonl')
    result = worker.run()
    assert result['outcome'] == 'completed'
    replies = list((tmp_path / 'native').glob('*.replies.jsonl'))
    reply = json.loads(replies[0].read_text())
    assert reply == {'id': 'approval', 'result': {'decision': expected}}
    http, body = calls[0]
    assert http.full_url == 'https://api.deepseek.com/chat/completions'
    assert http.get_header('Authorization') == 'Bearer test-key'
    assert body['model'] == 'deepseek-flash'
    reviewed = json.loads(body['messages'][1]['content'])
    assert reviewed['request']['command'] == 'printf APPROVAL_121'
    assert reviewed['authorization'] == 'request: authorize printf APPROVAL_121 only'
    assert reviewed['developer_instructions'] == 'Do not delete files.'
    assert reviewed['permissions']
    assert reviewed['allowed_decisions'] == ['accept', 'decline']
    assert worker.context.session_document()['adapter_request']['model'] == 'work-model'
    assert request['session_parameters']['config']['approvals_reviewer'] == 'user'
    assert 'test-key' not in (directory / 'approval-decisions.jsonl').read_text()


def test_resume_refreshes_route_preserving_session_and_work_model(
    tmp_path: Path, peer: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed roles.yml route reaches a second call on the same native identity."""
    request, directory = managed(tmp_path, peer, monkeypatch)
    calls = []
    completion_stub(monkeypatch, 'accept', calls)
    first = CodexManagedExecution(request, 'request: printf only', directory,
        lambda *_: None, {}, directory / 'events.jsonl').run()
    root = tmp_path / 'harness'
    (root / '.graphtraj').mkdir(parents=True)
    new_route = {**ROUTE, 'model': 'new-approval-model', 'base_url': 'https://review.example/v1'}
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({'roles': {'expert': {'temporary-role': {
        'runtime': 'codex', 'model': 'changed-work-model-must-not-apply',
        'codex': {'approval': new_route},
    }}, 'normal': {'temporary-role': {'runtime': 'codex', 'model': 'other'}}}}))
    (directory / 'mapping.yml').write_text('role: temporary-role\nrole_reference: expert.temporary-role\n')
    monkeypatch.setenv('GRAPHTRAJ_HARNESS_ROOT', str(root))
    completion_stub(monkeypatch, 'decline', calls)
    resumed = CodexManagedExecution(request, 'request: do not allow this', directory,
        lambda *_: None, {}, directory / 'events.jsonl', expected_session=first['session_id'])
    second = resumed.run()
    assert second['session_id'] == first['session_id']
    params = resumed.context.session_document()['adapter_request']
    assert params['model'] == 'work-model'
    assert params['config']['model_providers']['graphtraj-role']['base_url'] == 'https://work.example/v1'
    assert params['approvalsReviewer'] == 'user'
    assert calls[-1][0].full_url == 'https://review.example/v1/chat/completions'
    assert calls[-1][1]['model'] == 'new-approval-model'
    records = [json.loads(line) for line in (directory / 'approval-decisions.jsonl').read_text().splitlines()]
    assert [record['decision'] for record in records] == ['accept', 'decline']


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
    role = ResolvedChildRole('temporary-role', 'restrictions', (), settings)
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
    request = context(hosted, peer, replace(role, settings=replace(settings, base_url=None))).launch_document()['adapter_request']
    assert 'approval' not in request
    assert request['session_parameters']['config']['approvals_reviewer'] == 'auto_review'
