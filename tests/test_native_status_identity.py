"""Native callback identities select public Runner visibility without process identity."""

import asyncio
import json
from pathlib import Path

import pytest
import yaml

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.runtimes.codex.app_server import CodexAppServer, CodexServerRequest
from graphtraj.runtimes.codex.managed_session import CodexManagedExecution
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError
from test_codex_app_server import context, peer


@pytest.mark.parametrize('issuer, forged', [
    ('thread-1', False), ('helper', False), ('helper', True), ('outsider', False),
])
def test_native_status_uses_callback_identity(
    tmp_path: Path, peer: Path, issuer: str, forged: bool,
) -> None:
    """Identical arguments give parent detail but helper summary through native RPC."""
    configuration = tmp_path / '.graphtraj/config.yml'
    child_directory = tmp_path / '.graphtraj/runner/sessions/probe@e1'
    child_directory.mkdir(parents=True)
    configuration.write_text(default_configuration_content(tmp_path, tmp_path))
    mapping = {
        'alias': 'probe@e1', 'runtime': 'codex', 'session': 'child-session',
        'execution_id': 'child-turn', 'ticket_id': '133', 'team_generation': 2,
        'role': 'engineer', 'parent': 'probe@l1', 'retained_batch_file': 'batch.yml',
        'worktree_path': str(tmp_path), 'trace_file': 'unused',
        'worker_pid': 1, 'runtime_pid': 1,
    }
    (child_directory / 'mapping.yml').write_text(yaml.safe_dump(mapping))
    (child_directory / 'execution.yml').write_text(yaml.safe_dump({
        'outcome': 'completed', 'terminal_confirmed': True,
    }))
    expected = {'alias': 'probe@e1'}
    if issuer == 'thread-1':
        expected.update(session='child-session', execution_id='child-turn')
    expected.update(activity='idle', last_outcome='completed')
    document = {'aliases': [expected]}
    if forged:
        document = {'error': {'code': 'invalid-input', 'message': 'Supply only the target aliases.'}}
    elif issuer == 'outsider':
        document = {'error': {'code': 'authority-denied', 'message': 'Native caller is outside this Session subtree.'}}
    reply = {'contentItems': [{'type': 'inputText', 'text': json.dumps(document)}],
             'success': 'error' not in document}
    arguments = {'aliases': ['probe@e1']}
    if forged:
        arguments['threadId'] = 'thread-1'
    exchange = {
        'method': 'item/tool/call',
        'params': {'threadId': issuer, 'turnId': 'turn-1', 'callId': 'call',
                   'tool': 'graphtraj_status', 'arguments': arguments},
        'response': reply,
    }

    async def exercise() -> None:
        """Drive the production callback over the controlled native transport."""
        resolved = context(tmp_path, peer)
        managed = CodexManagedExecution(
            resolved.launch_document()['adapter_request'], 'unused',
            child_directory.with_name('probe@l1'), lambda session, pid: None,
            resolved.evidence_document(), tmp_path / 'unused-trace',
        )
        received = []

        async def handle(request: CodexServerRequest) -> dict:
            """Record only the result returned by the production callback."""
            result = await managed._request(request)
            received.append(result)
            return result

        async with CodexAppServer(command=[str(peer)], cwd=tmp_path, on_request=handle,
                                  environment={'PEER_REQUEST_EXCHANGE': json.dumps(exchange),
                                               'PEER_THREAD_PARENTS': '{"helper":"thread-1","outsider":"unrelated","unrelated":null}'}) as adapter:
            managed.adapter = adapter
            session = await adapter.create_session(resolved)
            managed.native_session = session.thread_id
            execution = await adapter.start_execution(session, 'configured-request')
            assert (await adapter.wait(execution, timeout=2))['last_agent_message'] == 'request accepted'
        document = json.loads(received[0]['contentItems'][0]['text'])
        if forged or issuer == 'outsider':
            assert document['error']['code'] == ('invalid-input' if forged else 'authority-denied')
        else:
            assert ('session' in document['aliases'][0]) == (issuer == 'thread-1')

    asyncio.run(exercise())


def test_native_parent_cannot_change(tmp_path: Path, peer: Path) -> None:
    """Reject a native metadata response that would reparent an observed entity."""
    async def exercise() -> None:
        """Use metadata-only requests over the public Adapter connection."""
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path,
                                  environment={'PEER_THREAD_PARENTS': '{"helper":["first","second"]}'}) as adapter:
            assert await adapter.read_thread_parent('helper') == 'first'
            with pytest.raises(RuntimeAdapterError):
                await adapter.read_thread_parent('helper')

    asyncio.run(exercise())
