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
        assert params['permissions'] == params['config']['default_permissions']
        selected = params['config']['permissions'][params['permissions']]
        assert selected['extends'] == 'operator'
        assert selected['filesystem'][str(config.parent)] == 'none'
        assert selected['filesystem'][str(config)] == 'read'
    assert 'graphtraj_swarm' in {tool['name'] for tool in start['dynamicTools']}
    assert 'dynamicTools' not in resume


@pytest.mark.parametrize('issuer', ['thread-1', 'helper'])
def test_main_summarizes_actual_native_status_callback(
    tmp_path: Path, peer: Path, monkeypatch: pytest.MonkeyPatch, issuer: str,
) -> None:
    """Retain issuer classification and field presence without private identities."""
    import yaml

    config = tmp_path / '.graphtraj/config.yml'
    directory = config.parent / 'runner/sessions/child@e1'
    directory.mkdir(parents=True)
    config.write_text(default_configuration_content(tmp_path, tmp_path))
    mapping = {'alias': 'child@e1', 'parent': None, 'session': 'private-session',
               'execution_id': 'private-turn', 'worker_pid': 1, 'runtime_pid': 1,
               'runtime': 'codex', 'ticket_id': '133', 'team_generation': 2,
               'role': 'engineer', 'retained_batch_file': 'batch.yml',
               'worktree_path': str(tmp_path), 'trace_file': 'unused'}
    (directory / 'mapping.yml').write_text(yaml.safe_dump(mapping))
    (directory / 'execution.yml').write_text(yaml.safe_dump({
        'outcome': 'completed', 'terminal_confirmed': True}))
    entry = {'alias': 'child@e1'}
    if issuer == 'thread-1':
        entry.update(session='private-session', execution_id='private-turn')
    entry.update(activity='idle', last_outcome='completed')
    exchange = {'method': 'item/tool/call', 'params': {
        'threadId': issuer, 'tool': 'graphtraj_status', 'arguments': {'aliases': ['child@e1']}},
        'response': {'contentItems': [{'type': 'inputText', 'text': json.dumps({'aliases': [entry]})}],
                     'success': True}}
    monkeypatch.setattr(main_session, 'runtime_executable', lambda runtime: peer)
    monkeypatch.setenv('PEER_REQUEST_EXCHANGE', json.dumps(exchange))
    monkeypatch.setenv('PEER_PROTOCOL_LOG', str(tmp_path / 'protocol.jsonl'))
    monkeypatch.setenv('PEER_THREAD_PARENTS', '{"helper":"thread-1"}')
    monkeypatch.setenv('PEER_NATIVE_ROLLOUT', str(tmp_path / 'native'))

    async def native_request(request: CodexServerRequest) -> dict:
        """All requests in this scenario must use the native operation handler."""
        raise AssertionError(request.method)

    result = asyncio.run(main_session.run_main(tmp_path, 'configured-request', None, native_request))
    assert result['last_agent_message'] == 'request accepted'
    assert result['native_operations'] == [{
        'tool': 'graphtraj_status', 'success': True, 'from_main': issuer == 'thread-1',
        'aliases': [{'alias': 'child@e1', 'has_session': issuer == 'thread-1',
                     'has_execution_id': issuer == 'thread-1'}]}]
    assert 'private-session' not in json.dumps(result['native_operations'])


def test_main_empty_status_start_resume_and_invalid_formal_record(
    tmp_path: Path, peer: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Main records do not pollute status; malformed formal records still fail."""
    from graphtraj.interfaces.mcp import read_alias_status

    config = tmp_path / '.graphtraj/config.yml'
    config.parent.mkdir()
    config.write_text(default_configuration_content(tmp_path, tmp_path))
    exchange = {'method': 'item/tool/call', 'params': {
        'threadId': 'thread-1', 'tool': 'graphtraj_status', 'arguments': {}},
        'response': {'contentItems': [{'type': 'inputText', 'text': json.dumps({'agents': []})}],
                     'success': True}}
    monkeypatch.setattr(main_session, 'runtime_executable', lambda runtime: peer)
    monkeypatch.setenv('PEER_REQUEST_EXCHANGE', json.dumps(exchange))
    monkeypatch.setenv('PEER_NATIVE_ROLLOUT', str(tmp_path / 'native'))

    async def native_request(request: CodexServerRequest) -> dict:
        """Status must be handled by the real callback, not an external reply."""
        raise AssertionError(request.method)

    async def exercise() -> None:
        """Observe empty status during both turns of the same Main Session."""
        first = await main_session.run_main(tmp_path, 'configured-request', None, native_request)
        second = await main_session.run_main(
            tmp_path, 'configured-request', first['record'], native_request,
        )
        assert first['session'] == second['session']
        assert first['record'] == second['record']
        for result in (first, second):
            assert result['last_agent_message'] == 'request accepted'
            assert result['native_operations'] == [{
                'tool': 'graphtraj_status', 'success': True, 'from_main': True, 'aliases': [],
            }]

    asyncio.run(exercise())
    clean = read_alias_status({}, cwd=tmp_path)
    assert not clean.failed
    assert clean.document == {'agents': []}

    # Do not fix Main by suppressing unreadable or malformed formal records.
    broken = config.parent / 'runner/sessions/broken@e1'
    broken.mkdir(parents=True)
    (broken / 'mapping.yml').write_text('{}\n')
    invalid = read_alias_status({}, cwd=tmp_path)
    assert invalid.failed
    assert invalid.document['agents'][0]['alias'] == 'broken@e1'
    assert invalid.document['agents'][0]['error']['code'] == 'operation-failed'
