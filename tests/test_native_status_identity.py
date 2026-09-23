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


@pytest.mark.parametrize('issuer, forged, operation', [
    ('thread-1', False, 'status'), ('helper', False, 'status'),
    ('helper', True, 'status'), ('outsider', False, 'status'),
    ('thread-1', False, 'send'), ('helper', False, 'send'),
])
def test_native_status_uses_callback_identity(
    tmp_path: Path,
    peer: Path,
    monkeypatch: pytest.MonkeyPatch,
    issuer: str,
    forged: bool,
    operation: str,
) -> None:
    """Native identity governs detail and control through the same public boundary."""
    from graphtraj.execution import runner_control
    from graphtraj.execution.runner_status import caller_alias
    from graphtraj.teams.coding import team_replacement
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
    delivered = []
    if operation == 'send':
        document = {'alias': 'probe@e1', 'session': 'child-session', 'send_status': 'sent'}
        def deliver(*args: object, **kwargs: object) -> dict:
            """Control only native delivery after real public relationship checks."""
            delivered.append(caller_alias(tmp_path / '.graphtraj/runner'))
            return {'alias': 'probe@e1', 'session': 'child-session', 'send_status': 'sent'}
        monkeypatch.setattr(runner_control, '_send_session', deliver)
        monkeypatch.setattr(runner_control, '_require_project_events', lambda *args: None)
        monkeypatch.setattr(runner_control, 'discover_project', lambda *args, **kwargs: None)
        monkeypatch.setattr(team_replacement, 'require_active_session', lambda *args: None)
        if issuer == 'helper':
            document = {'error': {'code': 'authority-denied',
                                 'message': 'Temporary native helpers have read-only Runner access.'}}
    if forged:
        document = {'error': {'code': 'invalid-input', 'message': 'Supply only supported tool arguments.'}}
    elif issuer == 'outsider':
        document = {'error': {'code': 'authority-denied', 'message': 'Native caller is outside this Session subtree.'}}
    reply = {'contentItems': [{'type': 'inputText', 'text': json.dumps(document)}],
             'success': 'error' not in document}
    arguments = (
        {'aliases': ['probe@e1']} if operation == 'status'
        else {'alias': 'probe@e1', 'instruction': 'Continue.', 'caused_by_event_ids': ['cause']}
    )
    if forged:
        arguments['threadId'] = 'thread-1'
    exchange = {
        'method': 'item/tool/call',
        'params': {'threadId': issuer, 'turnId': 'turn-1', 'callId': 'call',
                   'tool': 'graphtraj_' + operation, 'arguments': arguments},
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
        if operation == 'send':
            if issuer == 'helper':
                assert document['error']['code'] == 'authority-denied'
                assert not delivered
            else:
                assert document['send_status'] == 'sent'
                assert delivered == ['probe@l1']
        elif forged or issuer == 'outsider':
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
