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
    requests = [json.loads(line) for line in protocol.read_text().splitlines()]
    start = next(item['params'] for item in requests if item.get('method') == 'thread/start')
    resume = next(item['params'] for item in requests if item.get('method') == 'thread/resume')
    for params in (start, resume):
        assert not {'model', 'modelProvider', 'approvalPolicy', 'approvalsReviewer'} & params.keys()
        assert params['config']['permissions']['operator'] == original['permissions']['operator']
        selected = params['config']['permissions'][params['config']['default_permissions']]
        assert selected['extends'] == 'operator'
        assert selected['filesystem'][str(config.parent)] == 'none'
        assert selected['filesystem'][str(config)] == 'read'
    assert 'graphtraj_swarm' in {tool['name'] for tool in start['dynamicTools']}
    assert 'dynamicTools' not in resume
