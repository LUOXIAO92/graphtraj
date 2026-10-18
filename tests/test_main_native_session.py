"""Main startup keeps native settings and uses the existing Session transport."""

import asyncio
import json
from pathlib import Path

import pytest

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.runtimes.codex import main_session
from graphtraj.runtimes.codex.app_server import CodexServerRequest
from test_codex_app_server import peer


def test_main_start_and_resume_preserve_native_configuration(
    tmp_path: Path, peer: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Main adds file protection without selecting model, account or approvals."""
    config = tmp_path / '.graphtraj/config.yml'
    config.parent.mkdir()
    config.write_text(default_configuration_content(tmp_path, tmp_path))
    protocol = tmp_path / 'protocol.jsonl'
    original = {'default_permissions': 'operator', 'permissions': {
        'operator': {'extends': ':workspace', 'network': {'enabled': False}},
    }, 'model': 'operator-model', 'approvals_reviewer': 'user'}
    monkeypatch.setattr(main_session, 'runtime_executable', lambda runtime: peer)
    monkeypatch.setenv('PEER_CONFIG', json.dumps(original))
    monkeypatch.setenv('PEER_PROTOCOL_LOG', str(protocol))
    monkeypatch.setenv('PEER_NATIVE_ROLLOUT', str(tmp_path / 'native'))

    async def native_request(request: CodexServerRequest) -> dict:
        """Fail if this no-approval scenario unexpectedly asks for a decision."""
        raise AssertionError(request.method)

    async def exercise() -> None:
        """Create and continue one actual peer Session through the public service."""
        created = await main_session.run_main(tmp_path, 'first', None, native_request)
        resumed = await main_session.run_main(tmp_path, 'second', created['record'], native_request)
        assert created['session'] == resumed['session']
        assert resumed['last_agent_message'] == 'second'

    asyncio.run(exercise())
    from graphtraj.sessions.protocol import native_record
    from graphtraj.sessions.archive import JsonlSessionStore, archive_path
    from graphtraj.interfaces.agents import swarm_root

    archive = JsonlSessionStore(archive_path(swarm_root(tmp_path), 'codex:thread-1'))
    saved = [native_record(event) for event in archive.page()['events']]
    source = next((tmp_path / 'native').glob('*.jsonl'))
    assert saved == [json.loads(line) for line in source.read_text().splitlines()]
    assert archive.header['graphtraj']['agentId'] == 'main'
    source.unlink()
    assert [native_record(event) for event in archive.page()['events']] == saved
    requests = [json.loads(line) for line in protocol.read_text().splitlines()]
    start = next(item['params'] for item in requests if item.get('method') == 'thread/start')
    resume = next(item['params'] for item in requests if item.get('method') == 'thread/resume')
    for params in (start, resume):
        assert not {'model', 'modelProvider', 'approvalPolicy', 'approvalsReviewer'} & params.keys()
        assert params['config']['features'] == {'exec_permission_approvals': True}
        assert params['config']['permissions']['operator'] == original['permissions']['operator']
        assert params['permissions'] == params['config']['default_permissions']
        selected = params['config']['permissions'][params['permissions']]
        assert selected['extends'] == 'operator'
        assert selected['filesystem'][str(config.parent)] == 'none'
        assert selected['filesystem'][str(config)] == 'read'
    assert not start.get('dynamicTools')
    assert 'graphtraj' in start['config']['mcp_servers']
    assert 'dynamicTools' not in resume


@pytest.mark.parametrize('method, response', [
    ('item/commandExecution/requestApproval', {'decision': 'decline'}),
    ('item/tool/requestUserInput', {'answers': {'choice': {'answers': ['continue']}}}),
])
def test_main_keeps_native_requests_outside_gateway(
    tmp_path: Path,
    peer: Path,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    response: dict,
) -> None:
    """Approval and user-input callbacks retain their original handler and reply."""
    config = tmp_path / '.graphtraj/config.yml'
    config.parent.mkdir()
    config.write_text(default_configuration_content(tmp_path, tmp_path))
    params = {'threadId': 'thread-1', 'turnId': 'turn-1'}
    monkeypatch.setattr(main_session, 'runtime_executable', lambda runtime: peer)
    monkeypatch.setenv('PEER_REQUEST_EXCHANGE', json.dumps({
        'method': method, 'params': params, 'response': response,
    }))
    monkeypatch.setenv('PEER_NATIVE_ROLLOUT', str(tmp_path / 'native'))
    received = []

    async def native_request(request: CodexServerRequest) -> dict:
        """Return the user's native response without a gateway envelope."""
        received.append(request)
        return response

    result = asyncio.run(main_session.run_main(tmp_path, 'configured-request', None, native_request))
    assert result['last_agent_message'] == 'request accepted'
    assert result['native_operations'] == []
    assert len(received) == 1
    assert received[0].request_id == 'native-request-1'
    assert received[0].method == method
    assert received[0].params == params
