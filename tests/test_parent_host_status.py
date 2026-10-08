"""Public root-parent observation reads native metadata without sending input."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from graphtraj.execution import parent_status
from graphtraj.execution.runner_models import RunnerError
from graphtraj.interfaces.cli.agent_runner import main
from graphtraj.interfaces.local_tool import bind
from test_current_host_events import PROXY


@pytest.fixture
def host_peer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Serve the existing WebSocket proxy contract with controlled metadata."""
    reads = """
            if request['method'] == 'thread/resume':
                assert request['params'] == {'threadId':'original-host', 'excludeTurns':True}
                subscribed = True
                result['result'] = {'thread':{'id':'original-host'}}
                if (root / 'pending-request').exists():
                    ws.send_text(json.dumps({'id':'host-approval',
                        'method':'item/commandExecution/requestApproval',
                        'params':{'threadId':'original-host','turnId':'main-turn','itemId':'command'}
                    }).encode())
            if request['method'] == 'hooks/list':
                assert request['params'] == {'cwds':[str(root)]}
                result['result'] = {'data':[{'cwd':str(root), 'hooks':[
                    {'key':'observed-stop', 'eventName':'stop', 'enabled':True,
                     'trustStatus':'trusted', 'currentHash':'native-hash'}
                ], 'warnings':[], 'errors':[]}]}
                if subscribed:
                    for event, status in [('hook/started','running'), ('hook/completed','completed')]:
                        ws.send_text(json.dumps({'method':event, 'params':{
                            'threadId':'original-host', 'turnId':'main-turn',
                            'run':{'status':status, 'entries':[{'kind':'warning','text':'visible result'}]}
                        }}).encode())
            if request['method'] == 'thread/turns/list':
                assert request['params'] == {'threadId':'original-host', 'limit':1, 'itemsView':'notLoaded'}
                mode = (root / 'mode').read_text()
                if mode == 'disconnect':
                    raise SystemExit(0)
                result['result'] = {'data':[{'id':'main-turn', 'status':'inProgress' if mode in ('active','turn','quiet','unrelated','drop','stale') else 'completed', 'items':['private']} ]}
            if request['method'] == 'thread/read':
                assert request['params'] == {'threadId':'original-host', 'includeTurns':False}
                mode = (root / 'mode').read_text()
                result['result'] = {'thread':{'id':'wrong' if mode == 'wrong' else 'original-host', 'status':{'type':'notLoaded' if mode == 'unloaded' else 'active' if mode in ('active','turn','quiet','unrelated','drop') else 'idle'}}}
                result['result']['thread'].update(cwd=str(root), source='appServer', sessionId='native-session')
                if subscribed and mode in ('active','turn','quiet','unrelated','drop'):
                    (root / 'mode').write_text('idle')
"""
    notifications = """
            if subscribed and request['method'] == 'thread/read':
                if mode == 'drop':
                    raise SystemExit(0)
                if mode in ('active','turn','unrelated'):
                    notification = {'method':'thread/status/changed', 'params':{
                        'threadId':'other-host' if mode == 'unrelated' else 'original-host',
                        'status':{'type':'idle'},
                    }}
                    if mode == 'turn':
                        notification = {'method':'turn/completed', 'params':{
                            'threadId':'original-host', 'turn':{'id':'main-turn', 'status':'completed', 'items':[]},
                        }}
                    ws.send_text(json.dumps(notification).encode())
                    flush()
"""
    executable = tmp_path / 'codex'
    executable.write_text('#!' + sys.executable + '\n' + PROXY.replace(
        '    initialized = False', '    initialized = False\n    subscribed = False',
    ).replace(
        '            payload = json.dumps(result)', reads + '\n            payload = json.dumps(result)',
    ).replace('\n    raise SystemExit(0)\n', '\n' + notifications + '    raise SystemExit(0)\n'))
    executable.chmod(0o755)
    monkeypatch.setenv('PATH', str(tmp_path) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('HOST_TEST_ROOT', str(tmp_path))
    connection = {'runtime':'codex', 'session':'original-host', 'codex_home':str(tmp_path / 'home')}
    monkeypatch.setattr(parent_status, 'discover_runner_directory', lambda cwd: tmp_path)
    monkeypatch.setattr(parent_status, 'caller_alias', lambda directory: 'root-child')
    monkeypatch.setattr(parent_status, 'read_alias_mapping', lambda *a: (
        {'parent':None, 'parent_connection':connection}, tmp_path,
    ))
    return tmp_path


@pytest.mark.parametrize(('mode', 'method'), [('active', 'thread/status/changed'), ('turn', 'turn/completed')])
def test_public_parent_wait_reads_active_then_idle(host_peer: Path, mode: str, method: str) -> None:
    """Only a relevant native event triggers a second metadata observation."""
    (host_peer / 'mode').write_text(mode)
    result = bind(host_peer)({'action':'execute', 'feature':'parent_status',
                              'arguments':{'timeout_seconds':180}})
    assert not result.failed
    assert result.document['outcome'] == 'idle'
    observations = result.document['observations']
    assert [item['activity'] for item in observations] == ['active', 'idle']
    assert observations[-1]['turn'] == {'id':'main-turn', 'status':'completed'}
    assert observations[0]['observed_at'] < observations[-1]['observed_at']
    assert observations[0]['trigger'] is None
    assert observations[1]['trigger']['method'] == method
    assert 'private' not in json.dumps(result.document)
    wire = [json.loads(line)['request'] for line in (host_peer / 'wire.jsonl').read_text().splitlines()]
    assert {item['method'] for item in wire} == {'initialize', 'initialized', 'thread/read', 'thread/resume', 'thread/turns/list'}
    assert sum(item['method'] == 'thread/read' for item in wire) == 3


@pytest.mark.parametrize('state', ['missing', 'matching', 'mismatched'])
def test_public_hook_observer_projects_existing_association(host_peer: Path, state: str) -> None:
    """The owning host lookup is visible without repairing records or sending input."""
    import yaml
    from graphtraj.configuration.project_configuration import default_configuration_content
    from graphtraj.execution.main_finalize import session_binding

    config = host_peer / '.graphtraj/config.yml'
    config.parent.mkdir()
    config.write_text(default_configuration_content(host_peer, host_peer))
    path = session_binding(host_peer, 'codex', 'original-host')
    if state != 'missing':
        path.parent.mkdir(parents=True)
        path.write_text(yaml.safe_dump({
            'runtime': 'codex', 'session': 'original-host',
            'connection': {'runtime': 'codex', 'session': 'original-host',
                           'codex_home': str(host_peer / 'home'),
                           'hook_session': 'native-session' if state == 'matching' else 'old-session'},
        }))
    before = path.read_bytes() if path.exists() else None
    (host_peer / 'mode').write_text('idle')
    result = bind(host_peer)({'action': 'execute', 'feature': 'parent_status',
                              'arguments': {'include_hooks': True}})
    assert not result.failed
    assert result.document['completion_association'] == {
        'cwd': str(host_peer), 'binding_path': str(path), 'status': state,
    }
    assert (path.read_bytes() if path.exists() else None) == before
    wire = [json.loads(line)['request'] for line in (host_peer / 'wire.jsonl').read_text().splitlines()]
    assert {item['method'] for item in wire} <= {
        'initialize', 'initialized', 'thread/read', 'thread/turns/list', 'hooks/list',
    }


@pytest.mark.parametrize(('mode', 'outcome'), [('quiet', 'timeout'), ('unrelated', 'timeout'), ('drop', 'error')])
def test_parent_wait_needs_own_host_event(host_peer: Path, mode: str, outcome: str) -> None:
    """Silent changes and unrelated events never cause polling; EOF stays an error."""
    (host_peer / 'mode').write_text(mode)
    result = bind(host_peer)({'action':'execute', 'feature':'parent_status',
                              'arguments':{'timeout_seconds':0.5}})
    assert result.failed
    assert result.document['outcome'] == outcome
    wire = [json.loads(line)['request'] for line in (host_peer / 'wire.jsonl').read_text().splitlines()]
    assert sum(item['method'] == 'thread/read' for item in wire) == 2
    assert sum(item['method'] == 'thread/turns/list' for item in wire) == 1


def test_public_usage_diagnostic_excludes_conversation(
    host_peer: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inspect an existing check's native usage phases without exposing its text."""
    import yaml
    from graphtraj.configuration.project_configuration import default_configuration_content
    from graphtraj.execution.main_finalize import session_binding
    from graphtraj.runtimes.codex.app_server import CodexAppServer

    config = host_peer / '.graphtraj/config.yml'
    config.parent.mkdir()
    config.write_text(default_configuration_content(host_peer, host_peer))
    path = session_binding(host_peer, 'codex', 'original-host')
    check = path.parent / 'checks/retained'
    check.mkdir(parents=True)
    path.write_text(yaml.safe_dump({'runtime': 'codex', 'session': 'original-host',
        'connection': {'runtime': 'codex', 'session': 'original-host',
                       'codex_home': str(host_peer / 'home'), 'hook_session': 'native-session'}}))
    (check / 'session.yml').write_text(yaml.safe_dump({
        'runtime': 'codex', 'session': 'checker', 'parent': 'original-host'}))
    (check / 'execution.yml').write_text('output: private checker prose\n')
    trace = host_peer / 'checker.jsonl'
    records = [
        {'type': 'session_meta', 'payload': {'id': 'checker'}},
        {'type': 'response_item', 'payload': {'text': 'private inherited prose'}},
        {'type': 'turn_context', 'payload': {'turn_id': 'check-turn'}},
        {'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {
            'total_token_usage': {'input_tokens': 120, 'cached_input_tokens': 90}}}},
        {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 'check-turn'}},
        {'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {
            'total_token_usage': {'input_tokens': 150}}}},
    ]
    trace.write_text(''.join(json.dumps(record) + '\n' for record in records))
    original_read = CodexAppServer.read_thread
    original_status = CodexAppServer.read_host_status

    async def read_thread(client: CodexAppServer, session: str) -> dict:
        """Supply only the checker's public metadata; retain the real host peer."""
        if session == 'checker':
            return {'id': session, 'path': str(trace)}
        return await original_read(client, session)

    async def read_status(client: CodexAppServer, session: str) -> dict:
        """Supply the retained checker's terminal turn without loading its items."""
        if session == 'checker':
            return {'turn': {'id': 'check-turn', 'status': 'completed'}}
        return await original_status(client, session)

    monkeypatch.setattr(CodexAppServer, 'read_thread', read_thread)
    monkeypatch.setattr(CodexAppServer, 'read_host_status', read_status)
    (host_peer / 'mode').write_text('idle')
    result = bind(host_peer)({'action': 'execute', 'feature': 'parent_status',
                             'arguments': {'include_hooks': True}})
    assert not result.failed, result.document
    facts = result.document['completion_usage']
    assert facts['session_matches'] and facts['turn_found'] and facts['completion_found']
    assert facts['phases']['before_turn']['token_count_events'] == 0
    assert facts['phases']['in_turn']['totals'] == {'input_tokens': 120, 'cached_input_tokens': 90}
    assert facts['phases']['after_completion']['totals'] == {'input_tokens': 150}
    assert 'private checker prose' not in json.dumps(result.document)
    assert 'private inherited prose' not in json.dumps(result.document)


@pytest.mark.parametrize(('mode', 'outcome'), [('stale', 'timeout'), ('disconnect', 'error'), ('wrong', 'error')])
def test_parent_wait_does_not_invent_idle(host_peer: Path, mode: str, outcome: str) -> None:
    """Inconsistent state, a closed proxy and wrong identity cannot prove idle."""
    (host_peer / 'mode').write_text(mode)
    result = bind(host_peer)({'action':'execute', 'feature':'parent_status',
                              'arguments':{'timeout_seconds':0.5}})
    assert result.failed
    assert result.document['outcome'] == outcome
    if mode == 'stale':
        assert result.document['observations'][-1]['turn']['status'] == 'inProgress'
    else:
        assert result.document['error']['code']


def test_cli_parent_status_reads_once(host_peer: Path) -> None:
    """CLI and host tool expose the same operation without a budget side effect."""
    (host_peer / 'mode').write_text('active')
    result = CliRunner().invoke(main, ['parent-status'])
    assert result.exit_code == 0, result.output
    assert 'outcome: observed' in result.output
    assert 'activity: active' in result.output


def test_hook_diagnostics_preserve_native_events_and_do_not_answer_approvals(host_peer: Path) -> None:
    """The existing public observer projects native evidence without controlling Main."""
    (host_peer / 'mode').write_text('active')
    (host_peer / 'pending-request').touch()
    result = bind(host_peer)({'action':'execute', 'feature':'parent_status',
                             'arguments':{'timeout_seconds':1, 'include_hooks':True}})
    assert not result.failed, result.document
    document = result.document
    assert document['native_identity']['source'] == 'appServer'
    assert document['hook_configuration']['data'][0]['hooks'][0]['trustStatus'] == 'trusted'
    assert [event['method'] for event in document['hook_events']] == ['hook/started', 'hook/completed']
    assert document['hook_events'][-1]['params']['run']['entries'][0]['text'] == 'visible result'
    wire = [json.loads(line)['request'] for line in (host_peer / 'wire.jsonl').read_text().splitlines()]
    assert not any(request.get('id') == 'host-approval' for request in wire)
    assert not any(request.get('method') in {'turn/start','thread/start','config/batchWrite'} for request in wire)


def test_wait_refuses_to_load_a_host(host_peer: Path) -> None:
    """An unloaded original host is an error, never a request to create execution."""
    (host_peer / 'mode').write_text('unloaded')
    result = bind(host_peer)({'action':'execute', 'feature':'parent_status',
                              'arguments':{'timeout_seconds':180}})
    assert result.failed
    wire = [json.loads(line)['request']['method'] for line in (host_peer / 'wire.jsonl').read_text().splitlines()]
    assert wire == ['initialize', 'initialized', 'thread/read']


def test_main_cannot_wait_on_itself(host_peer: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unbound caller is rejected before opening the native host connection."""
    monkeypatch.setattr(parent_status, 'caller_alias', lambda directory: None)
    with pytest.raises(RunnerError, match='Only a root Agent'):
        bind(host_peer)({'action':'execute', 'feature':'parent_status', 'arguments':{}})
    assert not (host_peer / 'wire.jsonl').exists()


@pytest.mark.parametrize('timeout', [-1, float('nan'), float('inf')])
def test_parent_wait_is_bounded(host_peer: Path, timeout: float) -> None:
    """Unbounded waits fail before any native operation."""
    with pytest.raises(RunnerError, match='finite and nonnegative'):
        bind(host_peer)({'action':'execute', 'feature':'parent_status',
                        'arguments':{'timeout_seconds':timeout}})
    assert not (host_peer / 'wire.jsonl').exists()


def test_recipient_cannot_be_supplied(host_peer: Path) -> None:
    """Public arguments cannot select another Main or transport."""
    result = bind(host_peer)({'action':'execute', 'feature':'parent_status',
                              'arguments':{'session':'another-main'}})
    assert result.failed
    assert not (host_peer / 'wire.jsonl').exists()


@pytest.mark.parametrize('mapping', [
    {'parent':'actual-parent', 'parent_connection':{'runtime':'codex', 'session':'ancestor'}},
    {'parent':None, 'parent_connection':None},
    {'parent':None, 'parent_connection':'callback-directory'},
])
def test_observation_does_not_cross_parent_boundary(
    host_peer: Path, monkeypatch: pytest.MonkeyPatch, mapping: dict,
) -> None:
    """Mapped children cannot skip their parent or reinterpret a callback as Main."""
    monkeypatch.setattr(parent_status, 'read_alias_mapping', lambda *a: (mapping, host_peer))
    with pytest.raises(RunnerError, match='no recorded Runtime host parent'):
        bind(host_peer)({'action':'execute', 'feature':'parent_status', 'arguments':{}})
    assert not (host_peer / 'wire.jsonl').exists()
