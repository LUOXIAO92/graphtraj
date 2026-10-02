"""Single native entry and caller authorization through the controlled host peer."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.interfaces import gateway, tools
from graphtraj.runtimes.codex import main_session
from graphtraj.runtimes.codex.app_server import CodexAppServer, CodexServerRequest
from graphtraj.runtimes.codex.codex_adapter import NATIVE_RUNNER_TOOLS
from graphtraj.runtimes.codex.managed_session import CodexManagedExecution, run_native_operation
from test_codex_app_server import context, peer


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def native_result(document: dict, success: bool = True) -> dict:
    """Encode the expected business result in the native response envelope."""
    return {'contentItems': [{'type': 'inputText', 'text': json.dumps(document)}],
            'success': success}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Provide an empty project for real status and graph operations."""
    configuration = tmp_path / '.graphtraj/config.yml'
    configuration.parent.mkdir()
    configuration.write_text(default_configuration_content(tmp_path, tmp_path))
    return tmp_path


@pytest.mark.parametrize('host', ['main', 'managed'])
def test_native_gateway_disclosure_execution_and_correction(
    project: Path, peer: Path, monkeypatch: pytest.MonkeyPatch, host: str,
) -> None:
    """Fresh hosts register one tool and handle all actions on the same turn."""
    root = project
    manual = root / 'manual.txt'
    manual.write_text('Fixture status manual', encoding='utf-8')
    status = replace(tools.TOOLS['alias_status'], manual_ref=str(manual))
    monkeypatch.setitem(tools.TOOLS, 'alias_status', status)
    exchanges = []
    for arguments, document, success in [
        ({'action': 'discover', 'query': 'alias_status'}, {
            'features': [{'feature': 'alias_status', 'description': status.description}],
            'describe': {'action': 'describe', 'feature': '<feature>'},
        }, True),
        ({'action': 'describe', 'feature': 'alias_status'}, {
            'feature': 'alias_status', 'description': status.description,
            'input_schema': status.input_schema, 'examples': list(status.examples),
            'manual_ref': str(manual), 'manual': 'Fixture status manual',
            'call': {'action': 'execute', 'feature': 'alias_status', 'arguments': {}},
        }, True),
        ({'action': 'execute', 'feature': 'alias_status',
          'arguments': {'operation_total': 'yes'}}, {
            'feature': 'alias_status', 'error': 'arguments.operation_total: expected boolean',
        }, False),
        ({'action': 'execute', 'feature': 'alias_status', 'arguments': {}}, {'agents': []}, True),
    ]:
        exchanges.append({'method': 'item/tool/call', 'params': {
            'threadId': 'thread-1', 'turnId': 'turn-1', 'callId': 'different-from-rpc-id',
            'tool': 'graphtraj', 'arguments': arguments,
        }, 'response': native_result(document, success)})
    protocol = root / 'protocol.jsonl'
    monkeypatch.setenv('PEER_REQUEST_EXCHANGES', json.dumps(exchanges))
    monkeypatch.setenv('PEER_PROTOCOL_LOG', str(protocol))
    monkeypatch.setenv('PEER_NATIVE_ROLLOUT', str(root / 'native'))
    if host == 'main':
        monkeypatch.setattr(main_session, 'runtime_executable', lambda runtime: peer)

        async def unexpected(request: CodexServerRequest) -> dict:
            """Gateway callbacks must not be forwarded as native user requests."""
            raise AssertionError(request.method)

        result = asyncio.run(main_session.run_main(root, 'configured-request', None, unexpected))
    else:
        resolved = context(root, peer)
        directory = root / '.graphtraj/runner/sessions/probe@e1'
        directory.mkdir(parents=True)
        managed = CodexManagedExecution(
            resolved.launch_document()['adapter_request'], 'configured-request',
            directory, lambda session, pid: None, resolved.evidence_document(),
            directory / 'native.jsonl',
        )
        result = managed.run()
    assert result['last_agent_message'] == 'request accepted'
    messages = [json.loads(line) for line in protocol.read_text().splitlines()]
    starts = [item for item in messages if item.get('method') == 'thread/start']
    assert len(starts) == 1
    registered = starts[0]['params']['dynamicTools']
    assert [tool['name'] for tool in registered] == ['graphtraj']
    assert registered[0]['type'] == 'function'
    assert registered[0]['inputSchema'] == gateway.INPUT_SCHEMA
    replies = [item for item in messages if str(item.get('id', '')).startswith('native-request-1')]
    assert [reply['result'] for reply in replies] == [item['response'] for item in exchanges]
    assert [reply['id'] for reply in replies] == [
        'native-request-1' + '-next' * index for index in range(len(exchanges))
    ]
    assert not any('dynamicTools' in item.get('params', {}) for item in messages if item not in starts)


@pytest.mark.parametrize('issuer', ['outsider', None])
@pytest.mark.parametrize('action', ['discover', 'describe', 'execute'])
def test_native_gateway_authenticates_before_disclosure(
    project: Path, peer: Path, issuer: str | None, action: str,
) -> None:
    """Foreign and unknown native callers receive no gateway material."""
    arguments = {'action': action}
    if action != 'discover':
        arguments['feature'] = 'alias_status'
    if action == 'execute':
        arguments['arguments'] = {}

    async def exercise() -> dict:
        """Use real metadata requests before reaching the shared gateway."""
        async with CodexAppServer(command=[str(peer)], cwd=project, environment={
            'PEER_THREAD_PARENTS': '{"outsider":null}',
        }) as adapter:
            request = CodexServerRequest(1, 'item/tool/call', {
                'threadId': issuer, 'tool': 'graphtraj', 'arguments': arguments,
            })
            return await run_native_operation(adapter, 'owner', 'parent@l1', project, request)

    result = asyncio.run(exercise())
    assert not result['success']
    document = json.loads(result['contentItems'][0]['text'])
    assert document['error']['code'] == ('invalid-input' if issuer is None else 'authority-denied')


@pytest.mark.parametrize('issuer', ['owner', 'helper'])
def test_native_gateway_restricts_features_and_context(
    project: Path, peer: Path, issuer: str,
) -> None:
    """The host allowlist and helper identity cannot be replaced by model fields."""
    async def exercise() -> None:
        """Keep one trusted native connection for discovery and rejection checks."""
        async with CodexAppServer(command=[str(peer)], cwd=project, environment={
            'PEER_THREAD_PARENTS': '{"helper":"owner"}',
        }) as adapter:
            async def call(arguments: dict) -> tuple[dict, bool]:
                """Send arguments through the production native callback."""
                response = await run_native_operation(adapter, 'owner', 'parent@l1', project,
                    CodexServerRequest(1, 'item/tool/call', {
                        'threadId': issuer, 'tool': 'graphtraj', 'arguments': arguments,
                    }))
                return json.loads(response['contentItems'][0]['text']), response['success']

            discovered, success = await call({'action': 'discover'})
            assert success
            callable_features = (
                set(NATIVE_RUNNER_TOOLS.values()) | {'parent_status', 'retire', 'replace', 'cleanup'} if issuer == 'owner'
                else {'alias_status', 'ticket_graph'}
            )
            assert {entry['feature'] for entry in discovered['features']} == (
                callable_features | set(tools.METHOD_FEATURE_NAMES)
            )
            for feature in ('ticket_update', 'not_registered'):
                for action in ('describe', 'execute'):
                    request = {'action': action, 'feature': feature}
                    if action == 'execute':
                        request['arguments'] = {}
                    assert not (await call(request))[1]
            for field, value in [('caller', 'parent@l1'), ('threadId', 'owner'),
                                 ('allowed_features', ['ticket_update']), ('cwd', str(project))]:
                assert not (await call({'action': 'discover', field: value}))[1]
                assert not (await call({'action': 'execute', 'feature': 'alias_status',
                                       'arguments': {field: value}}))[1]
            if issuer == 'helper':
                document, success = await call({'action': 'execute', 'feature': 'submit_report',
                                               'arguments': {'name': 'engineer.md', 'text': 'forged'}})
                assert not success
                assert document['error']['code'] == 'authority-denied'
                assert not (await call({'action': 'describe', 'feature': 'submit_report'}))[1]
                assert not (await call({'action': 'execute', 'feature': [], 'arguments': {}}))[1]
                assert (await call({'action': 'execute', 'feature': 'ticket_graph', 'arguments': {}}))[1]

    asyncio.run(exercise())


def test_formal_child_cannot_use_gateway_as_its_parent(project: Path, peer: Path) -> None:
    """An authenticated child retains its own alias at the shared control boundary."""
    import yaml

    directory = project / '.graphtraj/runner/sessions/sibling@e1'
    directory.mkdir(parents=True)
    (directory / 'mapping.yml').write_text(yaml.safe_dump({
        'alias': 'sibling@e1', 'parent': 'parent@l1', 'runtime': 'codex',
        'session': 'sibling-thread', 'execution_id': 'turn-2', 'ticket_id': '209',
        'team_generation': 1, 'role': 'engineer', 'retained_batch_file': 'batch.yml',
        'worktree_path': str(project), 'trace_file': 'unused',
        'worker_pid': 1, 'runtime_pid': 1,
    }))

    async def exercise() -> dict:
        """Execute a valid native11 operation with a trusted child binding."""
        async with CodexAppServer(command=[str(peer)], cwd=project) as adapter:
            return await run_native_operation(adapter, 'child-thread', 'child@e1', project,
                CodexServerRequest(1, 'item/tool/call', {
                    'threadId': 'child-thread', 'tool': 'graphtraj', 'arguments': {
                        'action': 'execute', 'feature': 'send_instruction', 'arguments': {
                            'alias': 'sibling@e1', 'instruction': 'Impersonate parent.',
                            'caused_by_event_ids': ['cause'],
                        },
                    },
                }))

    response = asyncio.run(exercise())
    assert not response['success']
    assert json.loads(response['contentItems'][0]['text'])['error']['code'] == 'authority-denied'


def test_native_gateway_discloses_method_guides_without_widening_execution(
    project: Path, peer: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The session and its helpers read method guides while helpers stay read-only."""
    monkeypatch.setattr(gateway, 'delivered_manuals_root', lambda: REPOSITORY_ROOT)
    guide = REPOSITORY_ROOT / 'manuals' / 'task-delivery' / 'guide.md'

    async def exercise() -> None:
        """Reuse the controlled peer for discovery, description and rejection."""
        async with CodexAppServer(command=[str(peer)], cwd=project, environment={
            'PEER_THREAD_PARENTS': '{"helper":"owner"}',
        }) as adapter:
            async def call(issuer: str, arguments: dict) -> tuple[dict, bool]:
                """Send one request through the production native callback."""
                response = await run_native_operation(adapter, 'owner', 'parent@l1', project,
                    CodexServerRequest(1, 'item/tool/call', {
                        'threadId': issuer, 'tool': 'graphtraj', 'arguments': arguments,
                    }))
                return json.loads(response['contentItems'][0]['text']), response['success']

            discovered, success = await call('owner', {'action': 'discover'})
            assert success
            assert set(tools.METHOD_FEATURE_NAMES) <= {
                entry['feature'] for entry in discovered['features']
            }

            for issuer in ('owner', 'helper'):
                described, success = await call(
                    issuer, {'action': 'describe', 'feature': 'task-delivery'},
                )
                assert success
                assert described['manual'] == guide.read_text(encoding='utf-8')
                assert described['call'] is None

            for feature in ('ticket_register', 'task-delivery'):
                document, success = await call('helper', {
                    'action': 'execute', 'feature': feature, 'arguments': {},
                })
                assert not success
                assert document['error']['code'] == 'authority-denied'

    asyncio.run(exercise())
