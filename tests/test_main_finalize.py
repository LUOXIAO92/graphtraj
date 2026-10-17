"""Main completion checks through public host entry and a controlled native peer."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
import sys
from pathlib import Path
from typing import Awaitable, Callable

import pytest
import yaml
from click.testing import CliRunner

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.execution import main_finalize
from graphtraj.execution.runner_models import RunnerError
from graphtraj.interfaces.cli.graphtraj import main as cli
from graphtraj.interfaces.local_tool import bind
from graphtraj.runtimes.codex import finalize
from graphtraj.runtimes.codex.app_server import CodexAppServer, CodexServerRequest
from graphtraj.runtimes.codex.stop_hook import main as stop_hook
from graphtraj.runtimes.runtime_adapter import CheckUsage, finalize_usage, select_runtime_adapter
from graphtraj.sessions.archive import JsonlSessionStore, archive_path
from graphtraj.interfaces.agents import swarm_root


def test_binding_description_delivers_manual(tmp_path: Path) -> None:
    """Describe the binding without Main authority or executing a native hook."""
    result = bind(tmp_path)({'action': 'describe', 'feature': 'bind_main_finalize'})

    assert not result.failed
    assert Path(result.document['manual_ref']).read_text(encoding='utf-8')
    parameters = bind(tmp_path)({'action': 'describe', 'feature': 'bind_main_finalize', 'schema': True})
    assert parameters.document['input_schema']['required'] == ['summary_issue']


PEER = r'''
import json, os, sys, threading, time
from pathlib import Path
root = Path(os.environ['FINALIZE_TEST_ROOT'])
options = json.loads((root / 'options.json').read_text())
if options.get('unique_child'): options['child'] = 'checker-' + str(os.getpid())
interrupted = threading.Event()

def send(message):
    print(json.dumps(message), flush=True)

def main_thread():
    return {'id':'main', 'sessionId':'shared-native-session', 'model':'configured-model', 'modelProvider':'actual-provider',
            'source':options.get('source','appServer'), 'parentThreadId':options.get('parent'),
            'historyMode':options.get('history_mode','legacy'),
            'status':{'type':'active' if not options.get('stopped') else 'idle'}}

for line in sys.stdin:
    request = json.loads(line)
    with (root / 'wire.jsonl').open('a') as stream:
        stream.write(json.dumps({**request, 'observed_at': time.time()}) + '\n')
    method, params = request['method'], request.get('params', {})
    if method == 'initialized': continue
    result = {}
    if method == 'thread/read':
        result = {'thread':main_thread()}
        if options.get('read_id_from_request'): result['thread']['id'] = params['threadId']
        if options.get('session_id_from_request'): result['thread']['sessionId'] = params['threadId']
    elif method == 'thread/resume':
        if options.get('disconnect_on_resume'): sys.exit(0)
        result = {'thread':main_thread(), **options.get('configuration', {})}
        if options.get('parent_approval'):
            send({'id':'parent-approval','method':'item/commandExecution/requestApproval',
                  'params':{'threadId':'main','turnId':'main-turn','itemId':'parent-command',
                            'command':'read approved source','cwd':str(root)}})
    elif method == 'thread/turns/list' and params['threadId'] in options.get('stale_turns', {}):
        if options.get('stale_read_fails'):
            send({'id':request['id'], 'error':{'code':-32000, 'message':'stale thread unavailable'}})
            continue
        result = {'data': options['stale_turns'][params['threadId']]}
    elif method == 'thread/turns/list':
        if options.get('wait_before_start') and (root / 'child-context.json').exists():
            (root / 'snapshot-fixed').touch()
            while not (root / 'delivery-sent').exists(): time.sleep(.01)
        result = {'data':[{'id':options.get('current_turn','main-turn'), 'status':'inProgress'}]}
        if options.get('supersede_after_turn_read'): options['current_turn'] = 'new-main-turn'
    elif method == 'thread/items/list':
        result = {'data': [{'turnId':'inherited-turn', 'item':{'type':'agentMessage',
                   'id':'inherited-answer','text':'inherited context'}}], 'nextCursor': None}
        context_file = root / 'child-context.json'
        if context_file.exists() and len(json.loads(context_file.read_text())) > 2:
            result['data'].append({'turnId':'check-turn', 'item':{'type':'agentMessage',
                'id':'checker-answer','text':'checker result'}})
    elif method == 'thread/fork':
        if options.get('history_mode') == 'paginated' and not params.get('excludeTurns'):
            send({'id':request['id'],'error':{'code':-32600,'message':'history must be excluded'}})
            continue
        if options.get('wait_during_fork'):
            (root / 'snapshot-fixed').touch()
            while not (root / 'delivery-sent').exists(): time.sleep(.01)
        if options.get('fork_error'):
            send({'id':request['id'],'error':{'code':-32600,'message':'fork unavailable'}})
            continue
        # The peer owns context inheritance; the caller supplies no history.
        parent_context = ['original developer instructions','private context sentinel']
        child = {'id':options.get('child','checker'),'forkedFromId':'main',
                 'ephemeral':params.get('ephemeral', False),
                 'turns': [{'id':'inherited-turn','items':[{'type':'agentMessage',
                            'id':'inherited-answer','text':'inherited context'}]}]}
        if params.get('excludeTurns'): child['turns'] = []
        if 'records' in options:
            child['path'] = str(root / 'checker.jsonl')
            records = [{'type':'session_meta','payload':{'id':child['id']}}]
            records.extend(options['records'].get('before', []))
            Path(child['path']).write_text(''.join(json.dumps(r) + '\n' for r in records))
        (root / 'child-context.json').write_text(json.dumps(parent_context))
        result = {'thread':child, 'model':options.get('fork_model','actual-model'),
                  'modelProvider':'actual-provider', **options.get('configuration', {}),
                  **options.get('fork_configuration', {}),
                  'reasoningEffort':params.get('config',{}).get('model_reasoning_effort')}
        if options.get('supersede_during_fork'): options['current_turn'] = 'new-main-turn'
    elif method == 'turn/start':
        if params['threadId'] == 'main':
            if options.get('delay_delivery'):
                (root / 'delivery-pending').touch()
                time.sleep(options['delay_delivery'])
            if options.get('refuse_delivery'):
                send({'id':request['id'], 'error':{'code':-32600, 'message':'delivery refused'}})
            else:
                send({'id':request['id'], 'result':{'turn':{
                    'id':options.get('delivery_turn', 'main-turn'), 'status':'inProgress', 'items':[]}}})
            continue
        assert params['threadId'] == options.get('child','checker')
        context = json.loads((root / 'child-context.json').read_text())
        context.append(params['input'][0]['text'])
        (root / 'child-context.json').write_text(json.dumps(context))
        turn = {'id':'check-turn','status':'inProgress','items':[]}
        send({'id':request['id'],'result':{'turn':turn}})
        if options.get('resolve_parent_approval'):
            send({'method':'serverRequest/resolved',
                  'params':{'threadId':'main','requestId':'parent-approval'}})
        if options.get('approval_request'):
            send({'id':'checker-approval','method':'item/commandExecution/requestApproval',
                  'params':{'threadId':params['threadId'],'turnId':'check-turn',
                            'itemId':'checker-command','command':'read protected source',
                            'cwd':str(root)}})
            # The owner, not the checker, resolves this request natively.
            time.sleep(0.2)
            send({'method':'serverRequest/resolved',
                  'params':{'threadId':params['threadId'],'requestId':'checker-approval'}})
        if options.get('tool_request'):
            send({'id':'checker-tool','method':'item/tool/call','params':{
                'threadId':options.get('tool_caller',params['threadId']),
                'turnId':'check-turn','callId':'checker-call','tool':'graphtraj',
                'arguments':options['tool_request']}})
            reply = json.loads(sys.stdin.readline())
            (root / 'tool-reply.json').write_text(json.dumps(reply))
        if options.get('usage'):
            send({'method':'thread/tokenUsage/updated','params':{
                'threadId':params['threadId'],'tokenUsage':options['usage']}})
        for notice in options.get('notifications', []): send(notice)
        text = options.get('output',json.dumps({'status':'completed',
            'conclusion':'Main may end this turn.','reason':'All required tasks integrated.','nodes':[]}))
        if options.get('hold_check'):
            def finish_later(thread_id=params['threadId'], output=text):
                if not interrupted.wait(options['hold_check']):
                    send({'method':'item/completed','params':{'threadId':thread_id,'turnId':'check-turn',
                          'item':{'id':'answer','type':'agentMessage','text':output}}})
                    send({'method':'turn/completed','params':{'threadId':thread_id,
                          'turn':{'id':'check-turn','status':'completed','items':[]}}})
            threading.Thread(target=finish_later, daemon=True).start()
            (root / 'checker-running').touch()
            continue
        send({'method':'item/completed','params':{'threadId':params['threadId'],'turnId':'check-turn',
              'item':{'id':'answer','type':'agentMessage','text':text}}})
        turn['status'] = 'completed'
        if 'records' in options:
            with (root / 'checker.jsonl').open('a') as stream:
                for record in options['records'].get('after', []):
                    stream.write(json.dumps(record) + '\n')
        send({'method':'turn/completed','params':{'threadId':params['threadId'],'turn':turn}})
        if options.get('interrupt_during_check'): options['stopped'] = True
        continue
    elif method == 'turn/interrupt' and params['threadId'] in options.get('stale_turns', {}):
        if not options.get('ignore_stale_interrupt'):
            for turn in options['stale_turns'][params['threadId']]:
                if turn['id'] == params['turnId']: turn['status'] = 'interrupted'
        send({'id':request['id'], 'result':{}})
        continue
    elif method == 'turn/interrupt':
        interrupted.set()
        send({'id':request['id'], 'result':{}})
        send({'method':'turn/completed','params':{'threadId':params['threadId'],
              'turn':{'id':params['turnId'],'status':'interrupted','items':[]}}})
        continue
    send({'id':request['id'],'result':result})
'''


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Bind an actual native-peer connection through the shared local tool."""
    configuration = tmp_path / '.graphtraj/config.yml'
    configuration.parent.mkdir()
    configuration.write_text(default_configuration_content(tmp_path, tmp_path))
    peer = tmp_path / 'peer.py'
    peer.write_text(PEER)
    (tmp_path / 'options.json').write_text('{}')
    monkeypatch.setenv('FINALIZE_TEST_ROOT', str(tmp_path))
    monkeypatch.setenv('CODEX_HOME', str(tmp_path))
    monkeypatch.setattr(main_finalize, 'current_host_connection', lambda: {
        'runtime':'codex', 'session':'main', 'codex_home':str(tmp_path),
    })

    def connect(
        connection: dict,
        on_request: Callable[[CodexServerRequest], Awaitable[dict]] | None = None,
    ) -> CodexAppServer:
        """Replace only the native transport, retaining the production Adapter."""
        assert connection['runtime'] == 'codex'
        return CodexAppServer(cwd = tmp_path, command = (sys.executable, str(peer)),
                              experimental_api = True, on_request = on_request)

    monkeypatch.setattr(finalize, 'proxy', connect)
    reply = bind(tmp_path)({'action':'execute', 'feature':'bind_main_finalize',
                           'arguments':{'summary_issue':'https://tracker.test/goal/236'}})
    assert not reply.failed, reply.document
    return tmp_path, Path(reply.document['binding'])


def stop(binding: Path, **changes: object) -> dict:
    """Invoke the native command hook exactly as its trusted host does."""
    event = {'hook_event_name':'Stop', 'session_id':'shared-native-session', 'turn_id':'main-turn',
             'stop_hook_active':False, 'model':'actual-model', **changes}
    reply = CliRunner().invoke(stop_hook, ['--binding', str(binding), '--hook-session', 'shared-native-session'],
                               input = json.dumps(event))
    assert reply.exit_code == 0, reply.output
    return json.loads(reply.output)


@pytest.mark.parametrize('status,reason,nodes', [
    ('completed', 'All required tasks integrated.', []),
    ('waiting', 'Required child execution remains running.', ['237']),
    ('waiting', 'User approval pending; no other actionable node.', ['238']),
    ('waiting', 'External event pending; no other actionable node.', ['239']),
    ('actionable', '237 has authorized unfinished work; implement the checker.', ['237']),
    ('error', 'Required task source could not be read.', ['237']),
])
def test_main_end_decision(
    host: tuple[Path, Path], status: str, reason: str, nodes: list[str],
) -> None:
    """Only actionable nodes block Stop; all checks use a native context fork."""
    root, binding = host
    conclusion = f'Checker conclusion for {status}.'
    (root / 'options.json').write_text(json.dumps({'output':json.dumps({
        'status':status, 'conclusion':conclusion, 'reason':reason, 'nodes':nodes,
    })}))
    result = stop(binding)
    if status == 'actionable':
        assert result['decision'] == 'block'
        assert set(result) == {'decision', 'reason'}
        assert reason in result['reason']
    elif status == 'error':
        assert set(result) == {'continue', 'stopReason'}
        assert result['continue'] is False
    else:
        assert set(result) == {'systemMessage'}
        assert reason in result['systemMessage']
    visible = [result[key] for key in ('systemMessage', 'reason', 'stopReason') if key in result]
    assert len(visible) == 1 and visible[0].count(reason) == 1
    # One layered message: English title/status, checker conclusion and reason,
    # optional related Tasks, then this check's usage line, with no blank rows.
    lines = visible[0].splitlines()
    assert lines[0] == f'Completion Check · {status}'
    assert lines[1] == f'Conclusion · {conclusion}'
    assert lines[2] == f'Reason · {reason}'
    related = ['Related · ' + ', '.join(nodes)] if nodes else []
    assert lines[3:3 + len(related)] == related
    usage_line = lines[3 + len(related)]
    assert len(lines) == 4 + len(related)
    assert usage_line.startswith('Reviewer Usage · This Check · ')
    assert all(name in usage_line for name in ('Input ', 'Cached ', 'Output ', 'Reasoning ', 'Tools '))
    assert not any(not line.strip() for line in lines)
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    assert sum(item['method'] == 'thread/fork' for item in wire) == 1
    fork = next(item['params'] for item in wire if item['method'] == 'thread/fork')
    assert fork == {'threadId':'main', 'model':'actual-model', 'modelProvider':'actual-provider',
                    'excludeTurns':False, 'ephemeral':True}
    context = json.loads((root / 'child-context.json').read_text())
    assert context[:2] == ['original developer instructions', 'private context sentinel']
    assert len(context) == 3
    assert 'https://tracker.test/goal/236' in context[2]
    child = next(binding.parent.glob('checks/*/session.yml'))
    assert yaml.safe_load(child.read_text())['parent'] == 'main'
    evidence = yaml.safe_load(child.with_name('execution.yml').read_text())
    assert evidence['model'] == 'actual-model' and evidence['session'] == 'checker'
    # The public carrier returns native Stop continuation; never replaces Main.
    assert [m['params']['threadId'] for m in wire if m['method'] == 'turn/start'] == ['checker']

    # Identical conclusions in an independent Main turn are still delivered.
    (root / 'options.json').write_text(json.dumps({
        'child': 'checker-two', 'current_turn': 'main-turn-two',
        'output': json.dumps({'status': status, 'conclusion': conclusion,
                              'reason': reason, 'nodes': nodes}),
    }))
    assert stop(binding, turn_id='main-turn-two') == result
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    assert [m['params']['threadId'] for m in wire if m['method'] == 'turn/start'] == [
        'checker', 'checker-two',
    ]


@pytest.mark.parametrize('event', [
    {'session_id':'ordinary-child'}, {'session_id':'checker'},
    {'hook_event_name':'SubagentStop'}, {'hook_event_name':'Interrupt'},
])
def test_non_main_and_interrupt_skip_before_private_binding(tmp_path: Path, event: dict) -> None:
    """Unrelated events need neither private binding access nor a Runtime call."""
    assert stop(tmp_path / 'unreadable-binding', **event) == {}


@pytest.mark.parametrize('options', [
    {'fork_error':True}, {'fork_model':'wrong-model'}, {'child':'main'},
    {'output':'not JSON'},
    {'output':json.dumps({'status':'actionable', 'conclusion':'Main must continue this turn.',
                          'reason':'Unfinished', 'nodes':[]})},
    {'output':json.dumps({'status':'error', 'conclusion':'Unable to determine.',
                          'reason':'Referenced Issue unavailable', 'nodes':['237']})},
    {'output':json.dumps({'status':'completed', 'reason':'Missing conclusion.', 'nodes':[]})},
])
def test_checker_failures_are_visible_and_bounded(host: tuple[Path, Path], options: dict) -> None:
    """An error is returned once to Main and cannot generate endless error turns."""
    root, binding = host
    (root / 'options.json').write_text(json.dumps(options))
    first = stop(binding)
    assert first['continue'] is False and first['stopReason']
    assert set(first) == {'continue', 'stopReason'}
    assert 'decision' not in first
    # A fresh native checker Session is still required on the continued Stop.
    if options.get('child') != 'main':
        options['child'] = 'checker-two'
    (root / 'options.json').write_text(json.dumps(options))
    second = stop(binding, stop_hook_active = True)
    assert second['continue'] is False and second['stopReason']
    assert set(second) == {'continue', 'stopReason'}


@pytest.mark.parametrize('options', [{'stopped':True}, {'current_turn':'another-turn'},
                                     {'interrupt_during_check':True}])
def test_stopped_or_changed_main_is_not_continued(host: tuple[Path, Path], options: dict) -> None:
    """A stale Stop cannot wake a stopped Main, including interruption mid-check."""
    root, binding = host
    options['output'] = json.dumps({'status':'actionable', 'conclusion':'Main must continue this turn.',
                                    'reason':'unfinished', 'nodes':['237']})
    (root / 'options.json').write_text(json.dumps(options))
    result = stop(binding)
    if options.get('interrupt_during_check'):
        assert result == {}
    else:
        assert result == {}


def test_binding_rejects_managed_caller(host: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """An actual Runner child cannot become Main using model arguments or role names."""
    root, _ = host
    monkeypatch.setattr(main_finalize, 'caller_alias', lambda directory:'real-child@e1')
    with pytest.raises(RunnerError, match = 'owning Main'):
        bind(root)({'action':'execute', 'feature':'bind_main_finalize',
                    'arguments':{'summary_issue':'different'}})
    forged = bind(root)({'action':'execute', 'feature':'bind_main_finalize',
                       'arguments':{'summary_issue':'different', 'session':'main'}})
    assert forged.failed


def test_cli_and_tool_share_binding(host: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI returns the same captured Session and adoptable command hook."""
    root, binding = host
    monkeypatch.chdir(root)
    reply = CliRunner().invoke(cli, ['bind-finalize', '--summary-issue', 'https://tracker.test/goal/236'])
    assert reply.exit_code == 0, reply.output
    result = json.loads(reply.output)
    assert result['binding'] == str(binding)
    assert 'graphtraj.runtimes.codex.stop_hook' in result['hook']['hooks']['Stop'][0]['hooks'][0]['command']


def test_other_adapter_uses_opaque_host_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Common Runner binding/checking does not require Codex fields or models."""
    configuration = tmp_path / '.graphtraj/config.yml'
    configuration.parent.mkdir()
    configuration.write_text(default_configuration_content(tmp_path, tmp_path))
    calls = []

    class OtherAdapter:
        """Represent a host with unrelated lifecycle and connection formats."""

        finalize_usage = staticmethod(finalize_usage)

        def verify_finalize_main(self, connection: dict) -> str:
            """Attest the root identity on the other host's owned connection."""
            assert connection == {'runtime': 'other', 'endpoint': 'existing'}
            return 'owner'

        def finalize_hook(self, path: Path, binding: dict) -> dict:
            """Produce this host's registration format."""
            return {'target': binding['session'], 'resource': str(path)}

        def finalize_event(self, binding: dict, event: dict) -> dict:
            """Normalize the native lifecycle event."""
            assert event == {'finished': 'owner'}
            return {'continued': False}

        def check_main_finalize(
            self,
            binding: dict,
            context: dict,
            prompt: str,
            created: Callable[[str], None],
        ) -> dict:
            """Create a child and attest ownership before executing its task."""
            assert binding['session'] == 'owner'
            created('actual-child')
            calls.append(prompt)
            return {'session': 'actual-child', 'usage': CheckUsage(input_tokens=7, tool_calls=2),
                    'output': json.dumps({
                'status': 'waiting', 'conclusion': 'Main may end this turn: pending.',
                'reason': 'Approval pending', 'nodes': ['237'],
            })}

        def finalize_response(self, result: dict | None, continued: bool) -> dict:
            """Return this host's end decision without Codex hook fields."""
            assert 'Input 7' in result['usage_summary']
            assert 'Tools 2' in result['usage_summary']
            assert 'Reasoning unknown' in result['usage_summary']
            return {'end': result is None or result['status'] == 'waiting'}

    monkeypatch.setattr(main_finalize, 'current_host_connection',
                        lambda: {'runtime': 'other', 'endpoint': 'existing'})
    monkeypatch.setattr(main_finalize, 'select_runtime_adapter', lambda runtime: OtherAdapter())
    document = bind(tmp_path)({'action': 'execute', 'feature': 'bind_main_finalize',
                              'arguments': {'summary_issue': 'tracker:goal'}}).document
    result = main_finalize.check_main_finalize(Path(document['binding']), {'finished': 'owner'})
    assert result == {'end': True} and len(calls) == 1
    record = next(Path(document['binding']).parent.glob('checks/*/session.yml'))
    assert yaml.safe_load(record.read_text())['parent_connection'] == {
        'runtime': 'other', 'endpoint': 'existing',
    }


@pytest.mark.parametrize('feature,allowed', [('task_graph', True), ('send_instruction', False)])
def test_checker_has_no_sibling_control(
    host: tuple[Path, Path], feature: str, allowed: bool,
) -> None:
    """The actual bound fork can read the graph but cannot become its parent."""
    root, binding = host
    request = {'action': 'execute', 'feature': feature, 'arguments': {}}
    (root / 'options.json').write_text(json.dumps({'tool_request': request}))
    assert stop(binding)['systemMessage']
    reply = json.loads((root / 'tool-reply.json').read_text())
    assert reply['result']['success'] is allowed
    from graphtraj.sessions.protocol import native_record
    from graphtraj.sessions.storage import SessionStore, session_path

    with SessionStore(session_path(root / '.graphtraj/state', 'codex:checker'), readonly=True) as archive:
        records = [native_record(event) for event in archive.page()['events']
                   if event['type'] != 'session/end-seed']
        assert any(record.get('params', {}).get('arguments') == request for record in records)
        assert reply in records


@pytest.mark.parametrize('resolved', [False, True])
def test_checker_observer_does_not_answer_main_approval(
    host: tuple[Path, Path], resolved: bool,
) -> None:
    """Main's pending approval belongs to its native UI, including cancellation."""
    root, binding = host
    (root / 'options.json').write_text(json.dumps({
        'parent_approval': True, 'resolve_parent_approval': resolved,
    }))
    result = stop(binding)
    assert 'Completion Check · completed' in result['systemMessage']
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    assert not any(item.get('id') == 'parent-approval' for item in wire)


@contextmanager
def owned_child(root: Path, requests: list, *, outcome: str | None = None,
                drop: str | None = None, on_query: Callable[[], None] | None = None,
                alias: str = 'engineer@x1', task_id: str = '237', parent: str | None = None,
                activity: dict | None = None):
    """Run Main's own top-level Runner Session with a live control owner."""
    from graphtraj.execution.runner_connection import worker_connection

    directory = root / '.graphtraj/runner/sessions' / alias
    directory.mkdir(parents=True)

    def operate(request: dict) -> dict:
        """Answer the Runner's own pending-request query."""
        if request['operation'] == 'status':
            return activity if activity is not None else {'activity': 'running'}
        assert request['operation'] == 'requests'
        if on_query is not None:
            on_query()
        return {'requests': requests}

    with worker_connection(directory, operate) as address:
        mapping = {
            'alias': alias, 'runtime': 'claude', 'session': 'native-child',
            'execution_id': 'child-execution', 'task_id': task_id, 'team_generation': 1,
            'role': 'engineer', 'parent': parent, 'retained_batch_file': 'batch.yml',
            'parent_connection': {'runtime': 'codex', 'session': 'main', 'codex_home': str(root)},
            'worktree_path': str(root), 'trace_file': 'events.jsonl', 'worker_pid': 1,
            'runtime_pid': 1, 'control_directory': address, 'report_files': [],
        }
        mapping.pop(drop, None)
        (directory / 'mapping.yml').write_text(yaml.safe_dump(mapping))
        if outcome is not None:
            (directory / 'execution.yml').write_text(yaml.safe_dump({'outcome': outcome}))
        yield


def wire(root: Path) -> list[str]:
    """Return the native methods this Stop sent to its host."""
    return [json.loads(line)['method'] for line in (root / 'wire.jsonl').read_text().splitlines()]


def test_pending_child_request_continues_main_without_a_checker(host: tuple[Path, Path]) -> None:
    """Main's own child waiting on its reply is actionable before any fork or model."""
    root, binding = host
    request = {'request_id': 'permission-1', 'method': 'claude/can_use_tool'}
    with owned_child(root, [request]):
        result = stop(binding)
    assert result['decision'] == 'block'
    assert 'Completion Check · actionable' in result['reason']
    assert 'Related · 237' in result['reason']
    assert 'engineer@x1' in result['reason'] and 'permission-1' in result['reason']
    assert 'Input 0' in result['reason'] and 'no checker ran' in result['reason']
    assert 'thread/fork' not in wire(root) and 'turn/start' not in wire(root)


@pytest.mark.parametrize('state', ['running', 'runtime-error', 'interrupted', 'unreadable'])
def test_children_without_a_pending_request_reach_the_full_check(
    host: tuple[Path, Path], state: str,
) -> None:
    """A running, failed, stopped or unreadable child is decided by the full check.

    Terminal and unreadable children still offer a request, so only their
    recorded state keeps it from deciding the Stop.
    """
    root, binding = host
    offered = [] if state == 'running' else [{'request_id': 'stale-1', 'method': 'claude/can_use_tool'}]
    with owned_child(root, offered, outcome=state if state in ('runtime-error', 'interrupted') else None,
                     drop='session' if state == 'unreadable' else None):
        result = stop(binding)
    assert 'Completion Check · completed' in result['systemMessage']
    assert 'thread/fork' in wire(root) and 'turn/start' in wire(root)


@pytest.mark.parametrize('change', ['receipt', 'turn'])
def test_new_input_before_a_pre_fork_verdict_cancels_it(
    host: tuple[Path, Path], change: str,
) -> None:
    """A verdict decided before the fork is never returned for a superseded snapshot."""
    root, binding = host
    if change == 'turn':
        (root / 'options.json').write_text(json.dumps({'supersede_after_turn_read': True}))

    def accept_send() -> None:
        """Append the receipt a native-accepted send writes to this attempt."""
        if change == 'receipt':
            turn, = binding.parent.glob('pending-*/turn')
            with turn.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({'turn': 'main-turn', 'submitted_at': 1, 'accepted_at': 2}) + '\n')

    with owned_child(root, [{'request_id': 'permission-1', 'method': 'claude/can_use_tool'}],
                     on_query=accept_send):
        result = stop(binding)
    assert result == {}
    assert 'thread/fork' not in wire(root)


def submitted_result(root: Path, alias: str = 'research@x1') -> tuple[Path, dict]:
    """Register Task 148 and record one latest-Round submission from ``alias``."""
    from graphtraj.graph.delivery_worldline import append_project_worldline_event, read_worldline
    from test_generic_members import _register_research_team

    configuration = root / '.graphtraj/config.yml'
    document = yaml.safe_load(configuration.read_text())
    document['paths']['state'] = 'state'
    configuration.write_text(yaml.safe_dump(document))
    _register_research_team(root, multiple=False)
    state = root / 'state'
    submission = append_project_worldline_event(state, root, {
        'event': 'result-submitted', 'task_id': '148', 'alias': alias, 'session': 'native-child',
        'role': 'researcher', 'team_ordinal': 1, 'round': 1, 'candidate': 'a' * 40,
        'result_refs': ['result.md'], 'completion': 'Done', 'unresolved': [],
        'caused_by_event_ids': [read_worldline(state, root)[-1]['event_id']], 'evidence_refs': [],
    })
    return state, submission


def test_undecided_root_result_continues_main_without_a_checker(host: tuple[Path, Path]) -> None:
    """Main's own child result awaiting Main's decision is actionable before any fork."""
    root, binding = host
    submitted_result(root)
    with owned_child(root, [], alias='research@x1', task_id='148'):
        result = stop(binding)
    assert result['decision'] == 'block'
    assert 'Completion Check · actionable' in result['reason'] and 'Related · 148' in result['reason']
    assert 'research@x1 submitted ' + 'a' * 40 in result['reason']
    assert 'Main must decide this result; no checker ran' in result['reason']
    assert 'thread/fork' not in wire(root)


@pytest.mark.parametrize('decision', ['accepted', 'rejected'])
def test_decided_root_result_reaches_the_full_check(host: tuple[Path, Path], decision: str) -> None:
    """A result Main already decided is no longer evidence for continuing."""
    from graphtraj.graph.delivery_worldline import append_project_worldline_event

    root, binding = host
    state, submission = submitted_result(root)
    append_project_worldline_event(state, root, {
        'event': 'team-round-accepted' if decision == 'accepted' else 'team-round-implementation-rejected',
        'caused_by_event_ids': [submission['event_id']], 'evidence_refs': [], 'task_id': '148',
        'team_ordinal': 1, 'team_round': 1, 'candidate': 'a' * 40, 'decision': decision,
        'submission_id': submission['event_id'], 'reason': 'Decided by Main.', 'alias': None, 'session': None,
    })
    with owned_child(root, [], alias='research@x1', task_id='148'):
        result = stop(binding)
    assert 'Completion Check · completed' in result['systemMessage']
    assert 'thread/fork' in wire(root)


@pytest.mark.parametrize('case', ['leader-child', 'unreadable'])
def test_other_results_reach_the_full_check(host: tuple[Path, Path], case: str) -> None:
    """A Leader's child result is the Leader's to decide; unreadable results prove nothing."""
    root, binding = host
    state, _ = submitted_result(root)
    if case == 'unreadable':
        shard = next((state / 'worldline').glob('*.jsonl'))
        shard.write_text(shard.read_text() + 'not json\n')
    with owned_child(root, [], alias='research@x1', task_id='148',
                     parent='leader@x1' if case == 'leader-child' else None):
        result = stop(binding)
    assert 'Completion Check · completed' in result['systemMessage']
    assert 'thread/fork' in wire(root)


def test_new_input_cancels_an_undecided_result_verdict(host: tuple[Path, Path]) -> None:
    """The result verdict is also rechecked against new input before it returns."""
    root, binding = host
    submitted_result(root)

    def accept_send() -> None:
        """Append the receipt a native-accepted send writes to this attempt."""
        turn, = binding.parent.glob('pending-*/turn')
        with turn.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'turn': 'main-turn', 'submitted_at': 1, 'accepted_at': 2}) + '\n')

    with owned_child(root, [], alias='research@x1', task_id='148', on_query=accept_send):
        result = stop(binding)
    assert result == {}
    assert 'thread/fork' not in wire(root)


def test_unmarked_childless_result_is_not_a_verdict(
    host: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the explicit pre-fork decision may lack a bound checker."""
    root, binding = host
    output = json.dumps({'status': 'completed', 'conclusion': 'Done.', 'reason': 'Forged.', 'nodes': []})
    monkeypatch.setattr(finalize, 'check', lambda *args: {'outcome': 'completed', 'output': output})
    result = stop(binding)
    assert result['continue'] is False and 'Completion Check · error' in result['stopReason']


def test_lost_host_connection_is_a_check_error(host: tuple[Path, Path]) -> None:
    """A transport failure is a visible error, never a waiting or completed verdict."""
    root, binding = host
    (root / 'options.json').write_text(json.dumps({'disconnect_on_resume': True}))
    result = stop(binding)
    assert result['continue'] is False
    assert result['stopReason'].startswith('Completion Check · error')
    assert 'waiting' not in result['stopReason'] and 'turn/start' not in wire(root)


def test_checker_approval_is_left_to_its_native_owner(host: tuple[Path, Path]) -> None:
    """The checker neither grants nor refuses; the owner's resolution lets it finish."""
    root, binding = host
    (root / 'options.json').write_text(json.dumps({'approval_request': True}))
    result = stop(binding)
    assert 'Completion Check · completed' in result['systemMessage']
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    assert not any(item.get('id') == 'checker-approval' for item in wire)
    from graphtraj.sessions.protocol import native_record
    from graphtraj.sessions.storage import SessionStore, session_path

    with SessionStore(session_path(root / '.graphtraj/state', 'codex:checker'), readonly=True) as archive:
        records = [native_record(event) for event in archive.page()['events']
                   if event['type'] != 'session/end-seed']
    assert any(record.get('id') == 'checker-approval'
               and record['params']['threadId'] == 'checker' for record in records)
    assert any(record.get('method') == 'serverRequest/resolved'
               and record['params'] == {'threadId': 'checker', 'requestId': 'checker-approval'}
               for record in records)
    evidence = yaml.safe_load(next(binding.parent.glob('checks/*/execution.yml')).read_text())
    assert evidence['approval_requests'] == [{
        'request_id': 'checker-approval', 'method': 'item/commandExecution/requestApproval',
        'resolved': True,
    }]


def test_only_observed_cache_usage_is_retained(host: tuple[Path, Path]) -> None:
    """An unscoped last snapshot cannot establish current-check increments."""
    root, binding = host
    usage = {'last': {'inputTokens': 113, 'cachedInputTokens': 0, 'outputTokens': 19}}
    (root / 'options.json').write_text(json.dumps({'usage': usage}))
    assert stop(binding)['systemMessage']
    evidence = next(binding.parent.glob('checks/*/execution.yml'))
    assert all(value is None for value in yaml.safe_load(evidence.read_text())['usage'].values())


def token_record(**totals: int) -> dict:
    """Represent an observed native cumulative usage update."""
    return {'type': 'event_msg', 'payload': {
        'type': 'token_count', 'info': {'total_token_usage': totals},
    }}


def call_record(identifier: str, kind: str = 'function_call') -> dict:
    """Represent one native tool call, including the response-level identifier."""
    key = 'id' if kind in {'web_search_call', 'image_generation_call'} else 'call_id'
    return {'type': 'response_item', 'payload': {'type': kind, key: identifier}}


def check_records(before: list[dict], after: list[dict]) -> dict:
    """Wrap increments in the peer's actual checker-turn start/end records."""
    return {'before': before, 'after': [
        {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'check-turn'}},
        {'type': 'turn_context', 'payload': {'turn_id': 'check-turn'}},
        *after,
        {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 'check-turn'}},
    ]}


def test_whole_check_usage_excludes_inheritance_and_repeated_records(host: tuple[Path, Path]) -> None:
    """Two responses can contain multiple tools; lifetime totals and replays do not add usage."""
    root, binding = host
    baseline = token_record(input_tokens=10000, cached_input_tokens=8000,
                            output_tokens=1000, reasoning_output_tokens=500)
    first = token_record(input_tokens=10100, cached_input_tokens=8000,
                         output_tokens=1020, reasoning_output_tokens=505)
    last = token_record(input_tokens=10400, cached_input_tokens=8240,
                        output_tokens=1030, reasoning_output_tokens=505)
    records = check_records([
        {'type': 'session_meta', 'payload': {'id': 'inherited-parent'}},
        baseline, call_record('old'),
    ], [
        first, call_record('one'), call_record('two', 'custom_tool_call'),
        first, call_record('one'), call_record('old'),
        call_record('search', 'web_search_call'), last, last,
    ])
    # Later native activity is outside this checker turn even in the same file.
    records['after'].extend([
        {'type': 'turn_context', 'payload': {'turn_id': 'unrelated'}},
        token_record(input_tokens=999999), call_record('unrelated'),
    ])
    (root / 'options.json').write_text(json.dumps({'records': records}))
    rollout(root)
    result = native_hook(root)
    usage = yaml.safe_load(next(binding.parent.glob('checks/*/execution.yml')).read_text())['usage']
    assert usage == {'input_tokens': 400, 'cached_input_tokens': 240, 'cache_hit_ratio': 0.6,
                     'output_tokens': 30, 'reasoning_tokens': 5, 'tool_calls': 3,
                     'model_requests': None}
    assert 'Input 400' in result['systemMessage']
    assert 'Cached 240 (60.0%)' in result['systemMessage']
    assert 'Output 30 (Reasoning 5)' in result['systemMessage']
    assert 'Reviewer Usage · This Check' in result['systemMessage']
    assert 'decision' not in result


@pytest.mark.parametrize('baseline,after,expected', [
    ({'input_tokens': 800, 'cached_input_tokens': 600, 'output_tokens': 90,
      'reasoning_output_tokens': 50},
     {'input_tokens': 800, 'cached_input_tokens': 600, 'output_tokens': 90,
      'reasoning_output_tokens': 50},
     {'input_tokens': 0, 'cached_input_tokens': 0, 'output_tokens': 0,
      'reasoning_tokens': 0, 'cache_hit_ratio': None}),
    ({'input_tokens': 100, 'cached_input_tokens': 0},
     {'input_tokens': 125, 'cached_input_tokens': 0},
     {'input_tokens': 25, 'cached_input_tokens': 0, 'cache_hit_ratio': 0.0}),
    ({'input_tokens': 100}, {'input_tokens': 125, 'output_tokens': 300},
     {'input_tokens': 25}),
    ({}, {'input_tokens': 125, 'output_tokens': 300}, {}),
    ({'input_tokens': 100}, {'input_tokens': 50}, {}),
])
def test_partial_and_zero_usage(
    host: tuple[Path, Path], baseline: dict, after: dict, expected: dict,
) -> None:
    """Preserve known zeros; missing baselines and reset totals cannot supply increments."""
    root, binding = host
    records = check_records([token_record(**baseline)], [token_record(**after)])
    (root / 'options.json').write_text(json.dumps({'records': records}))
    result = stop(binding)
    usage = yaml.safe_load(next(binding.parent.glob('checks/*/execution.yml')).read_text())['usage']
    default = {key: None for key in ('input_tokens', 'cached_input_tokens', 'output_tokens',
                                    'reasoning_tokens', 'model_requests', 'cache_hit_ratio')}
    assert usage == {**default, 'tool_calls': 0, **expected}
    assert 'Reviewer Usage · This Check' in result['systemMessage']


def test_each_check_has_a_fresh_usage_boundary(host: tuple[Path, Path]) -> None:
    """Earlier check totals and tools never carry into the next check."""
    root, binding = host
    for child, start, end in [('checker', 100, 140), ('checker-two', 900, 905)]:
        records = check_records([token_record(input_tokens=start)], [
            token_record(input_tokens=end), call_record('same-call-id'),
        ])
        (root / 'options.json').write_text(json.dumps({'child': child, 'records': records}))
        result = stop(binding)
        assert f'Input {end - start}' in result['systemMessage']
        assert 'Tools 1' in result['systemMessage']
    assert len(list(binding.parent.glob('checks/*/execution.yml'))) == 2


@pytest.mark.parametrize('runtime', ['codex', 'pi', 'dsh'])
def test_unsupported_usage_needs_no_native_hook(runtime: str) -> None:
    """The Adapter usage contract reports unknowns without starting a Runtime."""
    usage = select_runtime_adapter(runtime).finalize_usage()
    assert all(value is None for value in usage.document().values())


def test_main_can_bind_its_next_goal_without_reparenting(host: tuple[Path, Path]) -> None:
    """A new summary reference does not change Session identity or old check evidence."""
    root, binding = host
    assert stop(binding)['systemMessage']
    document = bind(root)({'action': 'execute', 'feature': 'bind_main_finalize',
                          'arguments': {'summary_issue': 'https://tracker.test/goal/240'}}).document
    assert document['binding'] == str(binding)
    assert yaml.safe_load(binding.read_text())['summary_issue'].endswith('/240')
    child = next(binding.parent.glob('checks/*/session.yml'))
    assert yaml.safe_load(child.read_text())['summary_issue'].endswith('/236')


def test_fork_cannot_rebind_itself_as_main(
    host: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Runner parent binding remains authoritative without a native child flag."""
    root, binding = host
    assert stop(binding)['systemMessage']
    (root / 'options.json').write_text(json.dumps({'read_id_from_request': True}))
    monkeypatch.setattr(main_finalize, 'current_host_connection', lambda: {
        'runtime': 'codex', 'session': 'checker', 'codex_home': str(root),
    })
    with pytest.raises(RunnerError, match='bound checker'):
        bind(root)({'action': 'execute', 'feature': 'bind_main_finalize',
                    'arguments': {'summary_issue': 'https://tracker.test/goal/236'}})


def test_checker_stop_with_shared_session_id_cannot_recurse(host: tuple[Path, Path]) -> None:
    """Codex fork session_id equality cannot substitute for Main's exact turn."""
    root, binding = host
    assert stop(binding, turn_id='checker-turn') == {}
    assert not (binding.parent / 'checks').exists()
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    assert not any(item['method'] == 'thread/fork' for item in wire)


def native_hook(root: Path, event: str = 'Stop', **changes: object) -> dict:
    """Deliver an actual lifecycle envelope to the public command entry."""
    reply = CliRunner().invoke(stop_hook, [], input=json.dumps({
        'hook_event_name': event, 'cwd': str(root), 'session_id': 'shared-native-session',
        'transcript_path': str(root / 'rollout.jsonl'), 'turn_id': 'main-turn',
        'stop_hook_active': False, 'model': 'actual-model', **changes,
    }))
    assert reply.exit_code == 0, reply.output
    return json.loads(reply.output)


def rollout(root: Path, source: object = 'cli', session: str = 'main') -> None:
    """Write native-format records owned by the controlled Runtime peer."""
    records = [
        {'type': 'session_meta', 'payload': {'id': session, 'source': source}},
        {'type': 'turn_context', 'payload': {'turn_id': 'older-turn', 'effort': 'xhigh'}},
        {'type': 'turn_context', 'payload': {
            'turn_id': 'main-turn', 'model': 'actual-model', 'effort': 'high',
        }},
    ]
    (root / 'rollout.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in records))


def test_native_start_resume_and_stop_need_no_main_binding_input(host: tuple[Path, Path]) -> None:
    """Start/resume associate the event's Session; Stop runs and collects the child."""
    root, binding = host
    binding.unlink()
    rollout(root)
    for source in ('startup', 'resume'):
        assert native_hook(root, 'SessionStart', source=source)['systemMessage']
    result = native_hook(root)
    assert 'Completion Check · completed' in result['systemMessage']
    assert 'decision' not in result and 'continue' not in result
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    forks = [r['params'] for r in wire if r['method'] == 'thread/fork']
    assert len(forks) == 1
    assert forks[0]['config']['model_reasoning_effort'] == 'high'
    assert [r['params']['threadId'] for r in wire if r['method'] == 'turn/start'] == ['checker']
    from graphtraj.sessions.protocol import native_record
    from graphtraj.sessions.storage import SessionStore, session_path

    state = root / '.graphtraj/state'
    with SessionStore(session_path(state, 'codex:main')) as archive:
        archive.validate()
        assert [native_record(event) for event in archive.page()['events']] == [
            json.loads(line) for line in (root / 'rollout.jsonl').read_text().splitlines()
        ]
        assert archive.header['graphtraj']['agentId'] == 'main'
    with SessionStore(session_path(state, 'codex:checker')) as archive:
        archive.validate()
        events = archive.page()['events']
        assert archive.header['parentSession'] == 'codex:main'
        assert archive.header['graphtraj']['agentId'] != 'main'
        assert native_record(events[0])['id'] == 'inherited-turn'
        assert native_record(events[2])['id'] == 'checker'
        assert events[1]['type'] == 'session/end-seed'
        assert events[1]['data'] == {'inherited': True}
        assert any(native_record(event).get('method') == 'item/completed' for event in events[2:])


def test_native_session_end_archives_terminal_tail_without_checking(host: tuple[Path, Path]) -> None:
    """The native shutdown flush exposes records written after the Stop hook."""
    from graphtraj.sessions.protocol import native_record
    from graphtraj.sessions.storage import SessionStore, session_path

    root, _ = host
    rollout(root)
    assert native_hook(root, 'SessionStart')['systemMessage']
    terminal = {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 'main-turn'}}
    with (root / 'rollout.jsonl').open('a') as stream:
        stream.write(json.dumps(terminal) + '\n')
    before = (root / 'wire.jsonl').read_bytes()
    assert native_hook(root, 'SessionEnd') == {}
    assert (root / 'wire.jsonl').read_bytes() == before
    with SessionStore(session_path(root / '.graphtraj/state', 'codex:main')) as store:
        assert native_record(store.page()['events'][-1]) == terminal


def test_native_copied_fork_keeps_own_first_header(host: tuple[Path, Path]) -> None:
    """An inherited Main header cannot replace the current fork's native identity."""
    from graphtraj.execution.main_finalize import session_binding
    from graphtraj.sessions.protocol import native_record
    from graphtraj.sessions.storage import SessionStore, session_path

    root, binding = host
    original = binding.read_bytes()
    (root / 'options.json').write_text(json.dumps({'read_id_from_request': True}))
    records = [
        {'type': 'session_meta', 'payload': {'id': 'fork', 'source': 'cli', 'forked_from_id': 'main'}},
        {'type': 'session_meta', 'payload': {'id': 'main', 'source': 'cli'}},
        {'type': 'response_item', 'payload': {'type': 'reasoning', 'encrypted_content': 'inherited'}},
        {'type': 'event_msg', 'payload': {'type': 'thread_settings_applied', 'thread_id': 'fork',
                                        'thread_settings': {}}},
    ]
    (root / 'rollout.jsonl').write_text(''.join(json.dumps(record) + '\n' for record in records))
    assert native_hook(root, 'SessionStart', source='fork')['systemMessage']
    assert binding.read_bytes() == original
    assert session_binding(root, 'codex', 'fork').is_file()
    with SessionStore(session_path(root / '.graphtraj/state', 'codex:fork')) as store:
        store.validate()
        assert store.header['parentSession'] == 'codex:main'
        assert store.page()['events'][2]['type'] == 'session/end-seed'
        assert native_record(store.page()['events'][3]) == records[0]


@pytest.mark.parametrize('source', [
    {'subagent': {'thread_spawn': {'parent_thread_id': 'main', 'depth': 2, 'agent_path': 'a/b'}}},
    {'subAgent': {'threadSpawn': {'parentThreadId': 'main', 'depth': 1}}},
])
def test_native_children_cannot_overwrite_main(host: tuple[Path, Path], source: dict) -> None:
    """Native source overrides inherited association variables at every depth."""
    root, binding = host
    original = binding.read_bytes()
    rollout(root, source=source)
    assert native_hook(root, 'SessionStart') == {}
    result = native_hook(root)
    assert set(result) == {'systemMessage'} and 'child Session' in result['systemMessage']
    assert binding.read_bytes() == original


def test_unknown_source_and_stale_event_leave_main_unchanged(host: tuple[Path, Path]) -> None:
    """Neither absent provenance nor another Session's event may associate Main."""
    root, binding = host
    original = binding.read_bytes()
    rollout(root, source='unknown')
    assert native_hook(root, 'SessionStart')['continue'] is False
    rollout(root)
    assert native_hook(root, 'SessionStart', session_id='another-session')['continue'] is False
    assert binding.read_bytes() == original


def test_native_checker_and_changed_turn_do_not_recurse(host: tuple[Path, Path]) -> None:
    """Creation-time checker ownership wins even when Codex fork source is root."""
    root, binding = host
    rollout(root)
    native_hook(root)
    rollout(root, session='checker')
    assert native_hook(root, 'SessionStart') == {}
    result = native_hook(root)
    assert set(result) == {'systemMessage'} and 'recorded completion checker' in result['systemMessage']
    rollout(root)
    result = native_hook(root, turn_id='missing-turn')
    assert result['continue'] is False and 'settings' in result['stopReason']


def test_registered_pathless_checker_start_does_not_stop_inference(host: tuple[Path, Path]) -> None:
    """An ephemeral fork's inherited hook skips before requiring nonexistent history."""
    root, binding = host
    main_finalize.bind_checker(binding, yaml.safe_load(binding.read_text()), 'checker')
    original = binding.read_bytes()
    (root / 'options.json').write_text(json.dumps({
        'read_id_from_request': True, 'session_id_from_request': True,
    }))
    assert native_hook(root, 'SessionStart', session_id='checker', transcript_path=None) == {}
    result = native_hook(root, 'Stop', session_id='checker', transcript_path=None)
    assert set(result) == {'systemMessage'}
    assert 'recorded completion checker' in result['systemMessage']
    assert binding.read_bytes() == original
    # A missing transcript alone is not authority to skip an unrelated Session.
    assert native_hook(root, 'SessionStart', session_id='unregistered', transcript_path=None)['continue'] is False
    (root / 'options.json').write_text(json.dumps({'read_id_from_request': True}))
    assert native_hook(root, 'SessionStart', session_id='checker', transcript_path=None)['continue'] is False


@pytest.mark.parametrize('connection_fails', [False, True])
def test_external_checker_cli_identity_needs_metadata_not_rollout(
    host: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, connection_fails: bool,
) -> None:
    """The real CLI verifies its native thread before any target lookup, without history."""
    from graphtraj.interfaces.cli.agent_runner import main as runner_cli
    from graphtraj.runtimes import runtime_adapter
    from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError

    root, binding = host
    main_finalize.bind_checker(binding, yaml.safe_load(binding.read_text()), 'checker')
    monkeypatch.setattr(runtime_adapter, 'current_host_connection', lambda: {
        'runtime': 'codex', 'session': 'checker', 'codex_home': str(root),
    })
    # Deliberately keep native sessionId different: CLI uses CODEX_THREAD_ID,
    # not an assumed equality with hook_session. No transcript is created.
    (root / 'options.json').write_text(json.dumps({'read_id_from_request': True}))
    if connection_fails:
        def failed_proxy(*args: object, **kwargs: object) -> None:
            """Represent the observed failure at connection setup, before RPC."""
            raise RuntimeAdapterError('RUNTIME_CONNECTION_FAILED',
                                      'Codex WebSocket Upgrade failed: Connection lost')
        monkeypatch.setattr(finalize, 'proxy', failed_proxy)
    monkeypatch.chdir(root)
    reply = CliRunner().invoke(runner_cli, ['status', 'requested-current-alias'])
    assert reply.exit_code == 1
    # CLI keeps its structured stdout separate from any human stderr detail.
    document = yaml.safe_load(reply.stdout)
    if connection_fails:
        assert document['diagnostic'] == {
            'feature': 'alias_status', 'stage': 'caller_identity', 'entry': 'cli',
            'requested_aliases': ['requested-current-alias'],
            'native_error_code': 'RUNTIME_CONNECTION_FAILED',
        }
        assert 'Connection lost' in document['error']['message']
        assert 'aliases' not in document  # No target was queried or classified.
    else:
        assert document['aliases'][0]['alias'] == 'requested-current-alias'
        assert document['aliases'][0]['error']['code'] == 'alias-not-found'
        wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
        assert any(message.get('method') == 'thread/read' and message['params'] == {
            'threadId': 'checker', 'includeTurns': False,
        } for message in wire)


def test_checker_retains_only_structured_cli_status_failure(host: tuple[Path, Path]) -> None:
    """Existing canonical command output carries bounded next-call error evidence."""
    root, binding = host
    output = yaml.safe_dump({
        'error': {'code': 'operation-failed', 'message': 'private transport details'},
        'diagnostic': {'entry': 'cli', 'feature': 'alias_status', 'stage': 'caller_identity',
                       'requested_aliases': ['current-target']},
    }, sort_keys=False)
    (root / 'options.json').write_text(json.dumps({'notifications': [{
        'method': 'item/completed', 'params': {'threadId': 'checker', 'turnId': 'check-turn',
            'item': {'id': 'status-command', 'type': 'commandExecution',
                     'aggregatedOutput': output, 'command': 'private shell details'}},
    }]}))
    stop(binding)
    evidence = yaml.safe_load(next(binding.parent.glob('checks/*/execution.yml')).read_text())
    assert evidence['response_usage']['status_query_errors'] == [{
        'item_id': 'status-command', 'entry': 'cli', 'stage': 'caller_identity',
        'requested_aliases': ['current-target'], 'error_code': 'operation-failed',
        'native_error_code': None,
    }]
    assert 'private transport details' not in json.dumps(evidence)
    assert 'private shell details' not in json.dumps(evidence)


def test_native_stop_reports_managed_and_stale_routing(
    host: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quiet skips disclose their routing without a checker or continuation."""
    from graphtraj.execution import runner_status

    root, binding = host
    original = binding.read_bytes()
    rollout(root)
    with monkeypatch.context() as patch:
        patch.setattr(runner_status, 'process_caller_alias', lambda runner, pid: 'member@e1')
        assert native_hook(root, 'SessionStart') == {}
        result = native_hook(root)
        assert set(result) == {'systemMessage'} and 'member@e1' in result['systemMessage']
    result = native_hook(root, session_id='different-native-session')
    assert result == {}
    assert binding.read_bytes() == original
    assert not (binding.parent / 'checks').exists()


def test_unassociated_native_stop_needs_existing_owner(host: tuple[Path, Path]) -> None:
    """Root-like source alone cannot adopt an unrelated running Session."""
    root, binding = host
    binding.unlink()
    rollout(root)
    result = native_hook(root)
    assert result['continue'] is False and 'root ownership' in result['stopReason']
    assert not binding.exists() and not (binding.parent / 'checks').exists()


def test_native_mcp_call_context_does_not_leak_between_sessions(
    host: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Host request metadata wins over parent environment and resets after calls."""
    from graphtraj.execution.runner_status import caller_alias
    from graphtraj.runtimes.codex.host_events import calling_session
    from graphtraj.workspace.runner_project import discover_runner_directory

    root, _ = host
    runner = discover_runner_directory(root)
    monkeypatch.setenv('CODEX_THREAD_ID', 'main')
    (root / 'options.json').write_text(json.dumps({'read_id_from_request': True, 'source': {
        'subAgent': {'threadSpawn': {'parentThreadId': 'main', 'depth': 2}},
    }}))
    with calling_session('actual-child'):
        assert caller_alias(runner) == 'actual-child'
    (root / 'options.json').write_text('{}')
    assert caller_alias(runner) is None


@pytest.fixture
def routed(host: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, list[str]]:
    """Record the Codex home each identity read targets, as in an MCP server env."""
    root, binding = host
    homes: list[str] = []
    connect = finalize.proxy

    def record(connection: dict, on_request=None):
        """Retain the daemon selection, then use the same fake native peer."""
        homes.append(connection['codex_home'])
        return connect(connection, on_request)

    monkeypatch.setattr(finalize, 'proxy', record)
    monkeypatch.delenv('CODEX_HOME', raising=False)
    return root, binding, homes


def test_mcp_caller_without_codex_home_uses_its_recorded_daemon(
    routed: tuple[Path, Path, list[str]],
) -> None:
    """An MCP server env omits CODEX_HOME; Main's association names its daemon."""
    from graphtraj.execution.runner_status import caller_alias
    from graphtraj.runtimes.codex.host_events import calling_session
    from graphtraj.workspace.runner_project import discover_runner_directory

    root, _, homes = routed
    with calling_session('main'):
        assert caller_alias(discover_runner_directory(root)) is None
    assert homes == [str(root)]


def test_explicit_codex_home_keeps_precedence(
    routed: tuple[Path, Path, list[str]], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller that carries CODEX_HOME keeps it and is still verified natively."""
    from graphtraj.execution.runner_status import caller_alias
    from graphtraj.runtimes.codex.host_events import calling_session
    from graphtraj.workspace.runner_project import discover_runner_directory

    root, _, homes = routed
    monkeypatch.setenv('CODEX_HOME', str(root / 'explicit'))
    with calling_session('main'):
        assert caller_alias(discover_runner_directory(root)) is None
    assert homes == [str(root / 'explicit')]


@pytest.mark.parametrize('record', ['invalid', 'conflicting'])
def test_unusable_association_never_routes_elsewhere(
    routed: tuple[Path, Path, list[str]], record: str,
) -> None:
    """An unreadable or contradictory association fails before any daemon is chosen."""
    import hashlib

    from graphtraj.execution.runner_status import caller_alias
    from graphtraj.runtimes.codex.host_events import calling_session
    from graphtraj.workspace.runner_project import discover_runner_directory

    root, binding, homes = routed
    if record == 'invalid':
        binding.write_text('session: main\n')
    else:
        checker = binding.parent / 'checks' / hashlib.sha256(b'main').hexdigest() / 'session.yml'
        checker.parent.mkdir(parents=True)
        checker.write_text(yaml.safe_dump({'runtime': 'codex', 'session': 'main', 'parent': 'other',
                                           'parent_connection': {'codex_home': str(root / 'other')}}))
    with calling_session('main'), pytest.raises(RunnerError):
        caller_alias(discover_runner_directory(root))
    assert homes == []


def test_unregistered_default_home_entry_keeps_official_resolution(
    routed: tuple[Path, Path, list[str]],
) -> None:
    """A Session with no association still reaches Codex's default home and is verified."""
    import os

    from graphtraj.execution.runner_status import caller_alias
    from graphtraj.runtimes.codex.host_events import calling_session
    from graphtraj.workspace.runner_project import discover_runner_directory

    root, _, homes = routed
    (root / 'options.json').write_text(json.dumps({'read_id_from_request': True}))
    with calling_session('fresh'), pytest.raises(RunnerError, match='association is unavailable'):
        caller_alias(discover_runner_directory(root))
    assert homes == [os.path.abspath(Path.home() / '.codex')]


def test_hook_configuration_is_only_adoption_material(tmp_path: Path) -> None:
    """Producing configuration does not activate hooks or require identity input."""
    reply = CliRunner().invoke(stop_hook, ['--configuration'])
    assert reply.exit_code == 0
    configuration = json.loads(reply.output)
    assert set(configuration['hooks']) == {'SessionStart', 'Stop', 'SessionEnd'}
    for groups in configuration['hooks'].values():
        handler = groups[0]['hooks'][0]
        assert handler['statusMessage'].strip()
        assert '--binding' not in handler['command']
        assert '--hook-session' not in handler['command']
    assert not list(tmp_path.iterdir())


def test_fork_without_baseline_does_not_guess_request_increments(host: tuple[Path, Path]) -> None:
    """Without a baseline, last usage may be inherited even after new output."""
    root, binding = host
    first = token_record(input_tokens=956010000, cached_input_tokens=936721800,
                         output_tokens=3158000, reasoning_output_tokens=1810800)
    first['payload']['info']['last_token_usage'] = {
        'input_tokens': 100, 'cached_input_tokens': 80,
        'output_tokens': 20, 'reasoning_output_tokens': 10}
    second = token_record(input_tokens=956010225, cached_input_tokens=936721920,
                          output_tokens=3158058, reasoning_output_tokens=1810854)
    second['payload']['info']['last_token_usage'] = {
        'input_tokens': 225, 'cached_input_tokens': 120,
        'output_tokens': 58, 'reasoning_output_tokens': 54}
    replay = token_record(input_tokens=900000000)
    replay['payload']['info']['last_token_usage'] = {'input_tokens': 999999}
    records = check_records([], [replay, call_record('one'), call_record('two'),
        first, first, {'type': 'response_item', 'payload': {
            'type': 'message', 'role': 'assistant', 'content': []}}, second, second])
    (root / 'options.json').write_text(json.dumps({'records': records}))
    result = stop(binding)
    evidence = yaml.safe_load(next(binding.parent.glob('checks/*/execution.yml')).read_text())
    assert evidence['usage'] == {
        'input_tokens': None, 'cached_input_tokens': None, 'output_tokens': None,
        'reasoning_tokens': None, 'model_requests': None, 'cache_hit_ratio': None,
        'tool_calls': 2,
    }
    assert 'unknown' in result['systemMessage']


def response_notice(identifier: str, usage: dict | None, turn: str = 'check-turn') -> dict:
    """Represent exact app-server response usage, independent of lifetime totals."""
    return {'method': 'rawResponse/completed', 'params': {
        'threadId': 'checker', 'turnId': turn, 'responseId': identifier, 'usage': usage,
    }}


def test_pathless_fork_retains_first_response_and_unique_usage(host: tuple[Path, Path]) -> None:
    """An ephemeral checker retains live usage without requiring native disk history."""
    root, binding = host
    first = response_notice('response-one', {
        'inputTokens': 100, 'cachedInputTokens': 80, 'outputTokens': 20, 'reasoningOutputTokens': 5,
    })
    last = response_notice('response-two', {
        'inputTokens': 300, 'cachedInputTokens': 240, 'outputTokens': 10, 'reasoningOutputTokens': 0,
    })
    tool = {'method': 'rawResponseItem/completed', 'params': {
        'threadId': 'checker', 'turnId': 'check-turn',
        'item': {'type': 'function_call', 'call_id': 'one-tool'},
    }}
    (root / 'options.json').write_text(json.dumps({
        'notifications': [response_notice('old-response', {'inputTokens': 900000}, 'old-turn'),
                          tool, tool, first, first, last, last],
        'usage': {'total': {'inputTokens': 900400}, 'last': {'inputTokens': 300}},
    }))
    result = stop(binding)
    evidence = yaml.safe_load(next(binding.parent.glob('checks/*/execution.yml')).read_text())
    assert evidence['parent'] == 'main' and evidence['parent_turn'] == 'main-turn'
    assert evidence['turn'] == 'check-turn' and evidence['outcome'] == 'completed'
    assert evidence['configuration']['thread']['ephemeral'] is True
    assert evidence['usage'] == {
        'input_tokens': 400, 'cached_input_tokens': 320, 'output_tokens': 30,
        'reasoning_tokens': 5, 'tool_calls': 1, 'model_requests': 2, 'cache_hit_ratio': 0.8,
    }
    responses = evidence['response_usage']
    assert responses['first_response'] == responses['responses'][0]
    assert responses['first_response']['input_tokens'] == 100
    assert responses['first_response']['cached_input_tokens'] == 80
    assert len(responses['responses']) == 2
    assert 'Reviewer Usage · This Check' in result['systemMessage']
    assert 'decision' not in result


def test_response_with_unknown_usage_does_not_become_zero(host: tuple[Path, Path]) -> None:
    """A missing response measurement makes the corresponding aggregate unknown."""
    root, binding = host
    (root / 'options.json').write_text(json.dumps({'notifications': [
        response_notice('first', None), response_notice('second', {'inputTokens': 100}),
    ]}))
    stop(binding)
    evidence = yaml.safe_load(next(binding.parent.glob('checks/*/execution.yml')).read_text())
    assert evidence['usage']['model_requests'] == 2
    assert evidence['usage']['input_tokens'] is None
    assert evidence['response_usage']['first_response']['cached_input_tokens'] is None


@pytest.mark.parametrize('missing_final_usage', [False, True])
def test_pathless_public_usage_without_raw_subscription(
    host: tuple[Path, Path], missing_final_usage: bool,
) -> None:
    """A native fork suppresses raw events; public increments still exclude history/replays."""
    root, binding = host
    rollout(root)
    with (root / 'rollout.jsonl').open('a') as stream:
        stream.write(json.dumps(token_record(input_tokens=900000, cached_input_tokens=0,
                                            output_tokens=0, reasoning_output_tokens=0)) + '\n')

    def update(total: int, current: int, cached: int) -> dict:
        """Provide the public native cumulative identity and last response usage."""
        return {'method': 'thread/tokenUsage/updated', 'params': {
            'threadId': 'checker', 'turnId': 'check-turn', 'tokenUsage': {
                'total': {'inputTokens': total, 'cachedInputTokens': cached,
                          'outputTokens': 20 if total == 900400 else 10 if total == 900100 else 0,
                          'reasoningOutputTokens': 4 if total == 900400 else 2 if total == 900100 else 0}, 'last': {
                    'inputTokens': current, 'cachedInputTokens': cached,
                    'outputTokens': 10, 'reasoningOutputTokens': 2,
                }}}}

    tool = {'method': 'item/started', 'params': {
        'threadId': 'checker', 'turnId': 'check-turn',
        'item': {'id': 'tool-one', 'type': 'commandExecution'},
    }}
    answer = {'method': 'item/completed', 'params': {
        'threadId': 'checker', 'turnId': 'check-turn', 'item': {
            'id': 'answer', 'type': 'agentMessage',
            'text': json.dumps({'status': 'completed', 'conclusion': 'Main may end this turn.',
                                'reason': 'Verified current task.', 'nodes': []}),
        },
    }}
    first = update(900100, 100, 0)
    second = update(900400, 300, 240)
    inherited = update(900000, 99999, 90000)
    inherited['params']['turnId'] = 'inherited-turn'
    # A hidden first websocket retry can replay Main's last usage after new
    # output. The inherited total, not an absent retry notice, excludes it.
    replay = update(900000, 99999, 0)
    notices = [inherited, tool, tool, replay, first, first, answer]
    if not missing_final_usage:
        notices += [second, second]
    (root / 'options.json').write_text(json.dumps({'notifications': notices}))
    result = native_hook(root)
    assert 'Completion Check · completed' in result['systemMessage'] and 'decision' not in result
    evidence = yaml.safe_load(next(binding.parent.glob('checks/*/execution.yml')).read_text())
    usage = evidence['usage']
    assert usage['input_tokens'] == (None if missing_final_usage else 400)
    assert usage['cached_input_tokens'] == (None if missing_final_usage else 240)
    assert usage['model_requests'] is None and usage['tool_calls'] == 1
    facts = evidence['response_usage']
    assert facts['responses'] == [] and facts['first_response'] is None
    assert facts['first_usage_update']['input_tokens'] == 100
    assert facts['first_usage_update']['cached_input_tokens'] == 0
    assert len(facts['usage_updates']) == (1 if missing_final_usage else 2)
    assert facts['usage_attribution_errors'] == []


@pytest.mark.parametrize('uncertain_event', ['retry', 'compaction', 'unattributed'])
def test_public_usage_does_not_attribute_replayed_or_compacted_values(
    host: tuple[Path, Path], uncertain_event: str,
) -> None:
    """Public exception paths cannot turn inherited last usage into first-response proof."""
    root, binding = host
    item = {'method': 'item/started', 'params': {
        'threadId': 'checker', 'turnId': 'check-turn',
        'item': {'id': 'answer', 'type': 'agentMessage'},
    }}
    usage = {'method': 'thread/tokenUsage/updated', 'params': {
        'threadId': 'checker', 'turnId': 'check-turn', 'tokenUsage': {
            'total': {'inputTokens': 900000}, 'last': {'inputTokens': 99999, 'cachedInputTokens': 90000},
        },
    }}
    if uncertain_event == 'retry':
        # Core may emit unchanged usage after stream failure before willRetry.
        notices = [item, usage, {'method': 'error', 'params': {
            'threadId': 'checker', 'turnId': 'check-turn', 'willRetry': True,
            'error': {'message': 'stream disconnected'},
        }}]
    elif uncertain_event == 'compaction':
        notices = [{'method': 'item/started', 'params': {
            'threadId': 'checker', 'turnId': 'check-turn',
            'item': {'type': 'contextCompaction', 'id': 'compact'},
        }}, item, usage]
    else:
        notices = [usage, item]
    (root / 'options.json').write_text(json.dumps({'notifications': notices}))
    stop(binding)
    evidence = yaml.safe_load(next(binding.parent.glob('checks/*/execution.yml')).read_text())
    assert evidence['usage']['input_tokens'] is None
    assert evidence['usage']['cached_input_tokens'] is None
    assert evidence['response_usage']['first_usage_update'] is None
    assert evidence['response_usage']['usage_attribution_errors']


@pytest.mark.parametrize('options', [
    {'supersede_during_fork': True},
    {'notifications': [{'method': 'turn/started', 'params': {
        'threadId': 'main', 'turn': {'id': 'new-main-turn'},
    }}]},
])
def test_superseded_fork_retains_cancellation(host: tuple[Path, Path], options: dict) -> None:
    """A new Main turn cancels the old snapshot and never wakes Main with its result."""
    root, binding = host
    (root / 'options.json').write_text(json.dumps(options))
    result = stop(binding)
    assert result == {}
    evidence = yaml.safe_load(next(binding.parent.glob('checks/*/execution.yml')).read_text())
    assert evidence['outcome'] == 'cancelled'
    if options.get('supersede_during_fork'):
        wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
        assert not any(message['method'] == 'turn/start' for message in wire)

    # Cancellation is not a task verdict or turn-ID deduplication: another
    # legitimate Stop in the same Main turn must still check the current task.
    (root / 'options.json').write_text(json.dumps({'child': 'next-checker'}))
    resumed = stop(binding)
    assert set(resumed) == {'systemMessage'}
    assert 'completed' in resumed['systemMessage']
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    starts = [message['params']['threadId'] for message in wire if message['method'] == 'turn/start']
    assert starts[-1] == 'next-checker'
    assert 'main' not in starts


@pytest.mark.parametrize('delivery', ['same-turn', 'different-turn', 'refused'])
@pytest.mark.parametrize('sender_directory', ['root', 'worktree'])
def test_acknowledged_input_cancels_running_check(
    host: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, delivery: str,
    sender_directory: str,
) -> None:
    """A real send receipt interrupts the peer before its delayed verdict exists."""
    import threading
    from conftest import wait_for_file
    from graphtraj.runtimes.codex import app_server, host_events

    root, binding = host
    cwd = root if sender_directory == 'root' else root / '.graphtraj' / '.agent-worktrees' / 'child'
    cwd.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(app_server, 'CodexAppServer', lambda **kwargs: CodexAppServer(
        cwd=root, command=(sys.executable, str(root / 'peer.py')), experimental_api=True,
    ))
    options = {'hold_check': 2 if delivery == 'same-turn' else 0.3,
               'output': json.dumps({'status': 'actionable', 'conclusion': 'Continue Main.',
                                     'reason': 'Old task verdict.', 'nodes': ['237']})}
    if delivery == 'different-turn':
        options['delivery_turn'] = 'another-turn'
    if delivery == 'refused':
        options['refuse_delivery'] = True
    (root / 'options.json').write_text(json.dumps(options))
    sends = []

    def deliver() -> None:
        """Exercise the production root notification path while Stop is pending."""
        try:
            wait_for_file(root / 'checker-running')
            sends.append(host_events.send_event(
                {'session': 'main', 'codex_home': str(root)},
                {'source': 'graphtraj', 'alias': 'child', 'event': 'completed', 'message': 'New task result.'},
            ))
        except Exception as error:
            sends.append(error)

    sender = threading.Thread(target=deliver)
    sender.start()
    result = stop(binding)
    sender.join(timeout=5)
    assert not sender.is_alive() and len(sends) == 1
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    interrupts = [row for row in wire if row['method'] == 'turn/interrupt']
    evidence = yaml.safe_load(next(binding.parent.glob('checks/*/execution.yml')).read_text())
    if delivery == 'same-turn':
        assert isinstance(sends[0], dict)
        assert result == {}
        assert evidence['outcome'] == 'cancelled' and evidence['output'] is None
        assert len(interrupts) == 1 and interrupts[0]['params']['threadId'] == 'checker'
        accepted = evidence['cancellation']['accepted_at']
        assert 0 <= interrupts[0]['observed_at'] - accepted < 1
        assert evidence['cancellation']['confirmed_at'] >= interrupts[0]['observed_at']
    else:
        assert not interrupts and result['decision'] == 'block'
        assert evidence['outcome'] == 'completed'
        if delivery == 'refused':
            assert 'delivery refused' in str(sends[0])
    assert not list(binding.parent.glob('pending-*'))

    # Reusing the same native turn does not reuse a cancelled snapshot.
    (root / 'options.json').write_text(json.dumps({'child': 'next-checker'}))
    assert 'completed' in stop(binding)['systemMessage']


def test_late_send_acknowledgement_does_not_cancel_later_snapshot(
    host: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A send captures only checks already active before its native submission."""
    import threading
    from conftest import wait_for_file
    from graphtraj.runtimes.codex import app_server, host_events

    root, binding = host
    monkeypatch.chdir(root)
    monkeypatch.setattr(app_server, 'CodexAppServer', lambda **kwargs: CodexAppServer(
        cwd=root, command=(sys.executable, str(root / 'peer.py')), experimental_api=True,
    ))
    (root / 'options.json').write_text(json.dumps({'hold_check': 0.2, 'delay_delivery': 0.6}))
    sends = []

    def deliver() -> None:
        """Hold the native reply while another Stop forks the current context."""
        wait_for_file(root / 'checker-running')
        sends.append(host_events.send_event(
            {'session': 'main', 'codex_home': str(root)},
            {'source': 'graphtraj', 'alias': 'child', 'event': 'completed', 'message': 'New input.'},
        ))

    sender = threading.Thread(target=deliver)
    sender.start()
    assert 'completed' in stop(binding)['systemMessage']
    wait_for_file(root / 'delivery-pending')
    (root / 'options.json').write_text(json.dumps({'child': 'next-checker', 'hold_check': 0.8}))
    assert 'completed' in stop(binding)['systemMessage']
    sender.join(timeout=5)
    assert not sender.is_alive() and len(sends) == 1
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    assert not any(row['method'] == 'turn/interrupt' for row in wire)
    assert not list(binding.parent.glob('pending-*'))


@pytest.mark.parametrize('stage', ['during_fork', 'before_start'])
def test_input_before_inference_prevents_checker_start(
    host: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, stage: str,
) -> None:
    """Input during or after fork cancels without spending a checker turn."""
    import threading
    from conftest import wait_for_file
    from graphtraj.runtimes.codex import app_server, host_events

    root, binding = host
    monkeypatch.chdir(root)
    monkeypatch.setattr(app_server, 'CodexAppServer', lambda **kwargs: CodexAppServer(
        cwd=root, command=(sys.executable, str(root / 'peer.py')), experimental_api=True,
    ))
    (root / 'options.json').write_text(json.dumps({'wait_' + stage: True}))
    sends = []

    def deliver() -> None:
        """Finish a normal delivery before the pending check can start inference."""
        wait_for_file(root / 'snapshot-fixed')
        try:
            sends.append(host_events.send_event(
                {'session': 'main', 'codex_home': str(root)},
                {'source': 'graphtraj', 'alias': 'child', 'event': 'completed', 'message': 'New input.'},
            ))
        finally:
            (root / 'delivery-sent').touch()

    sender = threading.Thread(target=deliver)
    sender.start()
    result = stop(binding)
    sender.join(timeout=5)
    assert not sender.is_alive() and len(sends) == 1
    assert result == {}
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    starts = [row['params']['threadId'] for row in wire if row['method'] == 'turn/start']
    assert starts == ['main']
    assert not list(binding.parent.glob('pending-*'))


def test_replayed_same_turn_input_is_not_a_new_delivery(host: tuple[Path, Path]) -> None:
    """Native item replay alone cannot invalidate a newly fixed snapshot."""
    root, binding = host
    (root / 'options.json').write_text(json.dumps({'notifications': [
        {'method': 'item/completed', 'params': {'threadId': 'main', 'turnId': 'main-turn',
         'item': {'id': 'old-input', 'type': 'functionCallOutput', 'name': 'graphtraj',
                  'namespace': None, 'output': 'Earlier completion event.'}}},
    ]}))
    assert 'completed' in stop(binding)['systemMessage']
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    assert not any(row['method'] == 'turn/interrupt' for row in wire)


def test_fork_preserves_observed_configuration(host: tuple[Path, Path]) -> None:
    """Live service and approval overrides survive a fork instead of using defaults."""
    root, binding = host
    configuration = {
        'serviceTier': 'fast', 'cwd': str(root), 'runtimeWorkspaceRoots': [str(root)],
        'approvalPolicy': 'untrusted', 'approvalsReviewer': 'user', 'reasoningEffort': 'high',
    }
    (root / 'options.json').write_text(json.dumps({'configuration': configuration}))
    stop(binding)
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    fork = next(message['params'] for message in wire if message['method'] == 'thread/fork')
    assert all(fork[key] == value for key, value in configuration.items() if key != 'reasoningEffort')
    assert fork['config']['model_reasoning_effort'] == 'high'
    evidence = yaml.safe_load(next(binding.parent.glob('checks/*/execution.yml')).read_text())
    assert all(evidence['configuration'][key] == value for key, value in configuration.items())


MAIN_READ_ONLY = {'sandbox': {'type': 'readOnly', 'networkAccess': False},
                  'activePermissionProfile': None}


def test_fork_selects_main_sandbox_and_accepts_its_named_equivalent(host: tuple[Path, Path]) -> None:
    """The checker requests Main's sandbox; the same policy reported by name passes."""
    root, binding = host
    (root / 'options.json').write_text(json.dumps({
        'configuration': MAIN_READ_ONLY,
        'fork_configuration': {'activePermissionProfile': {'id': ':read-only', 'extends': None}},
    }))
    assert 'Completion Check · completed' in stop(binding)['systemMessage']
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    fork = next(message['params'] for message in wire if message['method'] == 'thread/fork')
    assert fork['sandbox'] == 'read-only' and 'permissions' not in fork


def test_fork_with_a_wider_sandbox_never_starts_the_checker(host: tuple[Path, Path]) -> None:
    """A fork reporting a broader policy than Main's is an error before any turn."""
    root, binding = host
    (root / 'options.json').write_text(json.dumps({
        'configuration': MAIN_READ_ONLY,
        'fork_configuration': {'sandbox': {'type': 'workspaceWrite', 'writableRoots': [],
                                           'networkAccess': False},
                               'activePermissionProfile': {'id': ':workspace', 'extends': None}},
    }))
    result = stop(binding)
    assert result['continue'] is False and 'sandbox' in result['stopReason']
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    assert not any(message['method'] == 'turn/start' for message in wire)


MAIN_WORKSPACE = {'sandbox': {'type': 'workspaceWrite', 'writableRoots': [], 'networkAccess': False},
                  'activePermissionProfile': {'id': ':workspace', 'extends': None}}
CHECKER_WORKSPACE = {'sandbox': {'type': 'workspaceWrite', 'writableRoots': [], 'networkAccess': True},
                     'activePermissionProfile': {'id': 'graphtraj_checker', 'extends': ':workspace'}}


def test_checker_profile_enables_managed_network_on_main_profile(host: tuple[Path, Path]) -> None:
    """The fork extends Main's profile with managed network and Main's socket entry."""
    root, binding = host
    (root / 'options.json').write_text(json.dumps({
        'configuration': MAIN_WORKSPACE, 'fork_configuration': CHECKER_WORKSPACE,
    }))
    assert 'Completion Check · completed' in stop(binding)['systemMessage']
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    fork = next(message['params'] for message in wire if message['method'] == 'thread/fork')
    assert fork['permissions'] == 'graphtraj_checker' and 'sandbox' not in fork
    socket = os.path.realpath(root / 'app-server-control' / 'app-server-control.sock')
    assert fork['config']['permissions'] == {'graphtraj_checker': {
        'extends': ':workspace', 'network': {'enabled': True, 'unix_sockets': {socket: 'allow'}},
    }}
    evidence = yaml.safe_load(next(binding.parent.glob('checks/*/execution.yml')).read_text())
    assert evidence['authorized_difference'] == {
        'permission_profile': {'id': 'graphtraj_checker', 'extends': ':workspace'},
        'unix_socket': socket, 'network_access': {'main': False, 'checker': True},
    }


def test_symlinked_control_socket_is_allowed_and_connected_as_its_target(tmp_path: Path) -> None:
    """The proxy connects to the same resolved socket the checker is allowed."""
    target = tmp_path / 'daemon' / 'opaque'
    target.parent.mkdir()
    target.touch()
    published = tmp_path / 'home' / 'app-server-control' / 'app-server-control.sock'
    published.parent.mkdir(parents=True)
    published.symlink_to(target)
    home = str(tmp_path / 'home')
    assert finalize.control_socket(home) == os.path.realpath(target)
    server = finalize.proxy({'session': 'main', 'codex_home': home})
    assert server._command[1:] == ('app-server', 'proxy', '--sock', os.path.realpath(target))


@pytest.mark.parametrize('fork', [
    {**CHECKER_WORKSPACE, 'activePermissionProfile': {'id': ':workspace', 'extends': None}},
    {**CHECKER_WORKSPACE, 'sandbox': {'type': 'dangerFullAccess'}},
    {**CHECKER_WORKSPACE, 'sandbox': {'type': 'workspaceWrite', 'writableRoots': ['/'], 'networkAccess': True}},
])
def test_checker_profile_must_be_applied_without_other_widening(
    host: tuple[Path, Path], fork: dict,
) -> None:
    """A fork that ignores the socket profile or widens anything else never starts."""
    root, binding = host
    (root / 'options.json').write_text(json.dumps({
        'configuration': MAIN_WORKSPACE, 'fork_configuration': fork,
    }))
    result = stop(binding)
    assert result['continue'] is False and 'Completion Check · error' in result['stopReason']
    assert 'turn/start' not in wire(root)


def test_fork_uses_current_turn_collaboration_settings(host: tuple[Path, Path]) -> None:
    """The checker receives the current mode and instructions, not an old turn's mode."""
    root, binding = host
    rollout(root)
    records = [json.loads(line) for line in (root / 'rollout.jsonl').read_text().splitlines()]
    collaboration = {'mode': 'plan', 'settings': {
        'model': 'actual-model', 'reasoning_effort': 'high',
        'developer_instructions': 'Current custom mode instruction',
    }}
    records[-1]['payload']['collaboration_mode'] = collaboration
    (root / 'rollout.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in records))
    native_hook(root)
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    start = next(message['params'] for message in wire if message['method'] == 'turn/start')
    assert start['collaborationMode'] == collaboration


def test_rollout_response_ids_deduplicate_token_count_representations(host: tuple[Path, Path]) -> None:
    """Available persisted response IDs win over their duplicate cumulative events."""
    root, binding = host
    record = {'type': 'token_usage_record', 'payload': {
        'thread_id': 'checker', 'turn_id': 'check-turn', 'response_id': 'response-one',
        'usage': {'input_tokens': 100, 'cached_input_tokens': 0, 'output_tokens': 20,
                  'reasoning_output_tokens': 5},
    }}
    records = check_records([token_record(input_tokens=900000)], [
        record, record, token_record(input_tokens=900100), token_record(input_tokens=900100),
    ])
    (root / 'options.json').write_text(json.dumps({'records': records}))
    stop(binding)
    evidence = yaml.safe_load(next(binding.parent.glob('checks/*/execution.yml')).read_text())
    assert evidence['usage']['model_requests'] == 1
    assert evidence['usage']['input_tokens'] == 100
    assert evidence['usage']['cached_input_tokens'] == 0


@pytest.mark.parametrize('with_baseline', [True, False])
def test_consecutive_native_checks_attribute_all_counters_to_current_checker(
    host: tuple[Path, Path], with_baseline: bool,
) -> None:
    """Two public Stop calls exclude nonzero Main history and earlier check usage."""
    root, binding = host
    fields = ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens')
    native = ('inputTokens', 'cachedInputTokens', 'outputTokens', 'reasoningOutputTokens')
    rounds = [((71000, 62000, 900, 300), (120, 90, 25, 10), (230, 150, 35, 15)),
              ((85000, 73000, 1200, 500), (75, 50, 12, 4), (125, 100, 28, 8))]
    for index, (history, first, second) in enumerate(rounds):
        child = f'checker-{index}'
        if index == 0:
            rollout(root)
        if index:
            with (root / 'rollout.jsonl').open('a') as stream:
                stream.write(json.dumps({'type': 'response_item', 'payload': {
                    'type': 'message', 'role': 'user', 'content': 'Check the next task.',
                }}) + '\n')
        if with_baseline:
            with (root / 'rollout.jsonl').open('a') as stream:
                stream.write(json.dumps(token_record(**dict(zip(fields, history)))) + '\n')
        notices = []
        total = list(history)
        for item_id, increment in [('tool', first), ('answer', second)]:
            notices.append({'method': 'item/completed', 'params': {
                'threadId': child, 'turnId': 'check-turn',
                        'item': {'id': item_id, 'type': 'commandExecution' if item_id == 'tool' else 'agentMessage',
                         'text': json.dumps({'status': 'completed',
                                             'conclusion': 'Main may end this turn.',
                                             'reason': 'Task complete.', 'nodes': []})},
                    }})
            if item_id == 'tool':
                # Main's last usage can replay even after new checker output.
                notices.append({'method': 'thread/tokenUsage/updated', 'params': {
                    'threadId': child, 'turnId': 'check-turn', 'tokenUsage': {
                        'total': dict(zip(native, history)), 'last': dict(zip(native, history)),
                    },
                }})
            total = [value + delta for value, delta in zip(total, increment)]
            update = {'method': 'thread/tokenUsage/updated', 'params': {
                'threadId': child, 'turnId': 'check-turn', 'tokenUsage': {
                    'total': dict(zip(native, total)), 'last': dict(zip(native, increment)),
                },
            }}
            notices.extend([update, update])
        (root / 'options.json').write_text(json.dumps({'child': child, 'notifications': notices}))
        result = native_hook(root)
        assert set(result) == {'systemMessage'}
        evidence = next(yaml.safe_load(path.read_text())
                        for path in binding.parent.glob('checks/*/execution.yml')
                        if yaml.safe_load(path.read_text())['session'] == child)
        for field, left, right in zip(
            ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_tokens'), first, second,
        ):
            assert evidence['usage'][field] == (left + right if with_baseline else None)
        assert evidence['usage']['tool_calls'] == 1
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    assert [row['params']['threadId'] for row in wire if row['method'] == 'turn/start'] == [
        'checker-0', 'checker-1',
    ]
    assert len(list(binding.parent.glob('checks/*/execution.yml'))) == 2


def test_check_usage_summary_groups_large_counters() -> None:
    """One compact English line keeps counters readable and units distinct."""
    usage = CheckUsage(input_tokens=1234567, cached_input_tokens=1000000,
                       output_tokens=2345, reasoning_tokens=1234, tool_calls=6)
    summary = usage.summary()
    assert 'Input 1,234,567' in summary
    assert 'Cached 1,000,000 (81.0%)' in summary
    assert 'Output 2,345 (Reasoning 1,234)' in summary
    assert 'Tools 6' in summary
    assert '\n' not in summary
    assert 'reasoning_tokens' not in summary and 'cache_hit_ratio' not in summary


def test_check_usage_summary_keeps_unknowns_unknown() -> None:
    """A missing counter or an underivable hit rate is never shown as zero."""
    empty = CheckUsage().summary()
    assert 'Input unknown' in empty and 'Cached unknown' in empty and 'Tools unknown' in empty
    assert 'Output unknown (Reasoning unknown)' in empty
    # A known cache count without a usable input baseline keeps the rate unknown.
    assert 'Cached 5 (unknown)' in CheckUsage(cached_input_tokens=5).summary()
    assert 'Cached 0 (unknown)' in CheckUsage(input_tokens=0, cached_input_tokens=0).summary()


@pytest.mark.parametrize('history_mode', ['paginated', None])
def test_ephemeral_fork_excluded_history_is_unknown_not_an_empty_seed(
    host: tuple[Path, Path], history_mode: str | None,
) -> None:
    """A valid checker can run without claiming the excluded inherited prefix."""
    from graphtraj.sessions.protocol import native_record
    from graphtraj.sessions.storage import SessionStore, session_path

    root, binding = host
    binding.unlink()
    (root / 'options.json').write_text(json.dumps({'history_mode': history_mode}))
    rollout(root)
    native_hook(root, 'SessionStart', source='startup')
    result = native_hook(root)
    assert 'Completion Check · completed' in result['systemMessage']
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    fork = next(item['params'] for item in wire if item['method'] == 'thread/fork')
    assert fork['excludeTurns'] is True and fork['ephemeral'] is True
    state = root / '.graphtraj/state'
    archive = JsonlSessionStore(archive_path(swarm_root(root), 'codex:checker'))
    assert archive.header['isSeeded'] is False
    assert archive.header['parentSession'] == 'codex:main'
    assert any(item['path'] == 'history' and item['reason']
               for item in archive.header['graphtraj']['missing'])
    events = archive.page()['events']
    assert not any(event['type'] == 'session/end-seed' for event in events)
    assert native_record(events[0])['pages'][0]['data'] == []  # backfill is off
    assert native_record(events[-1])['pages'][0]['data'][0]['item']['id'] == 'checker-answer'
    with pytest.raises(ValueError, match='opaque-native|incomplete'):
        archive.messages()
    with SessionStore(session_path(state, 'codex:main')) as archive:
        assert [native_record(event) for event in archive.page()['events']] == [
            json.loads(line) for line in (root / 'rollout.jsonl').read_text().splitlines()
        ]



def stale_check(binding: Path, child: str = 'stale-checker') -> tuple[Path, Path]:
    """Leave the records a Stop hook leaves when it exits before recording its check."""
    import hashlib
    import tempfile

    directory = binding.parent / 'checks' / hashlib.sha256(child.encode()).hexdigest()
    directory.mkdir(parents=True)
    (directory / 'session.yml').write_text(yaml.safe_dump({'runtime': 'codex', 'session': child, 'parent': 'main'}))
    pending = Path(tempfile.mkdtemp(prefix='pending-', dir=binding.parent))
    (pending / 'turn').write_text('earlier-main-turn\n')
    return directory, pending


@pytest.mark.parametrize('turns', [[{'id': 'old', 'status': 'completed'}], []])
def test_unrecorded_finished_check_is_recorded_as_unknown_error(host: tuple[Path, Path], turns: list) -> None:
    """An idle or terminal stale checker is never called cancelled; pending is removed."""
    root, binding = host
    directory, pending = stale_check(binding)
    (root / 'options.json').write_text(json.dumps({'stale_turns': {'stale-checker': turns}}))
    stop(binding)
    record = yaml.safe_load((directory / 'execution.yml').read_text())
    assert record == {'session': 'stale-checker', 'outcome': 'error', 'error': main_finalize.STALE_CHECK_ERROR}
    assert (directory / 'session.yml').exists() and not pending.exists()
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    assert not any(message['method'] == 'turn/interrupt' and message['params']['threadId'] == 'stale-checker'
                   for message in wire)


@pytest.mark.parametrize('confirmed', [True, False])
def test_running_stale_checker_is_cancelled_only_when_confirmed(
    host: tuple[Path, Path], confirmed: bool,
) -> None:
    """This recovery interrupts a still-running stale checker; only confirmation records cancelled."""
    root, binding = host
    directory, _ = stale_check(binding)
    (root / 'options.json').write_text(json.dumps({
        'stale_turns': {'stale-checker': [{'id': 'stale-turn', 'status': 'inProgress'}]},
        'ignore_stale_interrupt': not confirmed}))
    stop(binding)
    record = yaml.safe_load((directory / 'execution.yml').read_text())
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    assert any(message['method'] == 'turn/interrupt' and message['params'] == {
        'threadId': 'stale-checker', 'turnId': 'stale-turn'} for message in wire)
    if confirmed:
        assert record['outcome'] == 'cancelled' and record['cancellation']['interrupted_turn'] == 'stale-turn'
    else:
        assert record == {'session': 'stale-checker', 'outcome': 'error', 'error': main_finalize.STALE_CHECK_ERROR}


def test_check_owned_by_a_live_process_is_untouched(host: tuple[Path, Path]) -> None:
    """A record whose owner still holds its lock is left as it is."""
    import os

    from graphtraj import file_lock

    root, binding = host
    directory, pending = stale_check(binding)
    (root / 'options.json').write_text(json.dumps({'stale_turns': {'stale-checker': []}}))
    held = [os.open(directory, os.O_RDONLY), os.open(pending, os.O_RDONLY)]
    try:
        for descriptor in held:
            file_lock.flock(descriptor, file_lock.LOCK_EX)
        stop(binding)
    finally:
        for descriptor in held:
            os.close(descriptor)
    assert not (directory / 'execution.yml').exists() and pending.exists()



def test_stale_check_read_failure_is_recorded_with_its_cause(host: tuple[Path, Path]) -> None:
    """A failed native read keeps the unknown-cause error and shows the real failure."""
    root, binding = host
    directory, pending = stale_check(binding)
    (root / 'options.json').write_text(json.dumps({
        'stale_turns': {'stale-checker': []}, 'stale_read_fails': True}))
    stop(binding)
    record = yaml.safe_load((directory / 'execution.yml').read_text())
    assert record['outcome'] == 'error' and record['error'].startswith(main_finalize.STALE_CHECK_ERROR)
    assert 'stale thread unavailable' in record['error'] and not pending.exists()


KILLED_HOOK = r"""
import sys
from pathlib import Path
from graphtraj.runtimes.codex import finalize
from graphtraj.runtimes.codex.app_server import CodexAppServer
from graphtraj.runtimes.codex.stop_hook import main

root, peer = Path(sys.argv[1]), Path(sys.argv[2])
finalize.proxy = lambda connection, on_request=None: CodexAppServer(
    cwd=root, command=(sys.executable, str(peer)), experimental_api=True, on_request=on_request)
main(['--binding', sys.argv[3], '--hook-session', 'shared-native-session'])
"""


def test_killed_real_hook_leaves_a_check_the_next_stop_records(host: tuple[Path, Path]) -> None:
    """The real Stop hook, killed mid-check, releases its locks; the next Stop records the check."""
    import os
    import signal
    import subprocess
    import time

    root, binding = host
    (root / 'options.json').write_text(json.dumps({
        'hold_check': 60, 'stale_turns': {'checker': [{'id': 'check-turn', 'status': 'completed'}]}}))
    event = {'hook_event_name': 'Stop', 'session_id': 'shared-native-session', 'turn_id': 'main-turn',
             'stop_hook_active': False, 'model': 'actual-model'}
    hook = subprocess.Popen([sys.executable, '-c', KILLED_HOOK, str(root), str(root / 'peer.py'), str(binding)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True, env={**os.environ, 'FINALIZE_TEST_ROOT': str(root)})
    hook.stdin.write(json.dumps(event))
    hook.stdin.close()
    deadline = time.monotonic() + 20
    while not (root / 'checker-running').exists():
        assert time.monotonic() < deadline and hook.poll() is None, hook.stderr.read()
        time.sleep(0.05)
    os.kill(hook.pid, signal.SIGKILL)  # only the hook process
    hook.wait(timeout=5)
    checks = list((binding.parent / 'checks').glob('*'))
    assert len(checks) == 1 and (checks[0] / 'session.yml').exists()
    assert not (checks[0] / 'execution.yml').exists()
    assert list(binding.parent.glob('pending-*/turn'))
    (root / 'options.json').write_text(json.dumps({
        'stale_turns': {'checker': [{'id': 'check-turn', 'status': 'completed'}]}}))
    stop(binding)
    record = yaml.safe_load((checks[0] / 'execution.yml').read_text())
    assert record == {'session': 'checker', 'outcome': 'error', 'error': main_finalize.STALE_CHECK_ERROR}
    assert not list(binding.parent.glob('pending-*'))


@pytest.mark.parametrize('status', ['waiting', 'completed', 'actionable'])
def test_repeated_native_stop_reuses_one_checker(host: tuple[Path, Path], status: str) -> None:
    """Repeated Stop consumes one real fork/start result, without repeating a release."""
    root, _ = host
    rollout(root)
    (root / 'options.json').write_text(json.dumps({'output': json.dumps({
        'status': status, 'conclusion': 'Checked.', 'reason': 'Current tasks checked.', 'nodes': ['237'],
    })}))
    first = native_hook(root)
    options = json.loads((root / 'options.json').read_text())
    (root / 'options.json').write_text(json.dumps({**options, 'child': 'second-checker'}))
    second = native_hook(root)
    assert wire(root).count('thread/fork') == 1
    assert wire(root).count('turn/start') == 1
    assert first
    if status == 'actionable':
        assert second['decision'] == 'block'
    else:
        assert second == {}


def test_concurrent_stops_share_one_checker(host: tuple[Path, Path]) -> None:
    """Two independent Stop processes wait for one retained fork/model execution."""
    import subprocess

    root, binding = host
    rollout(root)
    (root / 'options.json').write_text(json.dumps({'hold_check': 0.3, 'unique_child': True}))
    # Each process uses the production command hook and Adapter, replacing only
    # the native transport with the same existing wire peer as other tests.
    command = '''
import sys
from pathlib import Path
from graphtraj.runtimes.codex import finalize
from graphtraj.runtimes.codex.app_server import CodexAppServer
from graphtraj.runtimes.codex.stop_hook import main
root = Path(sys.argv[1])
finalize.proxy = lambda connection, on_request=None: CodexAppServer(
    cwd=root, command=(sys.executable, str(root / 'peer.py')),
    experimental_api=True, on_request=on_request)
sys.argv = [sys.argv[0], '--binding', sys.argv[2], '--hook-session', 'shared-native-session']
main()
'''
    event = json.dumps({'hook_event_name': 'Stop', 'session_id': 'shared-native-session',
                       'turn_id': 'main-turn', 'model': 'actual-model', 'stop_hook_active': False,
                       'transcript_path': str(root / 'rollout.jsonl')})
    environment = {**os.environ, 'PYTHONPATH': str(Path(main_finalize.__file__).parents[2])}
    processes = [subprocess.Popen([sys.executable, '-c', command, str(root), str(binding)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, env=environment) for _ in range(2)]
    for process in processes:
        process.stdin.write(event)
        process.stdin.close()
        process.stdin = None
    replies = []
    for process in processes:
        output, errors = process.communicate(timeout=15)
        assert process.returncode == 0, errors
        replies.append(json.loads(output))
    assert wire(root).count('thread/fork') == 1
    assert wire(root).count('turn/start') == 1
    assert sum(bool(reply) for reply in replies) == 1


@pytest.mark.parametrize('change', ['input', 'compacted', 'task-result', 'approval'])
def test_new_facts_invalidate_waiting(host: tuple[Path, Path], change: str) -> None:
    """Same-turn input, compaction, submitted work and requests cannot hide behind waiting."""
    root, _ = host
    rollout(root)
    (root / 'options.json').write_text(json.dumps({'output': json.dumps({
        'status': 'waiting', 'conclusion': 'May end.', 'reason': 'Child running.', 'nodes': ['237'],
    })}))
    assert 'waiting' in native_hook(root)['systemMessage']
    (root / 'options.json').write_text(json.dumps({'child': 'next-checker', 'output': json.dumps({
        'status': 'actionable', 'conclusion': 'Continue.', 'reason': 'New work.', 'nodes': ['237'],
    })}))
    if change in ('input', 'compacted'):
        record = {'type': 'response_item' if change == 'input' else 'compacted',
                  'payload': {'type': 'message', 'role': 'user', 'content': 'New task input.'}}
        with (root / 'rollout.jsonl').open('a') as stream:
            stream.write(json.dumps(record) + '\n')
        reply = native_hook(root)
        assert wire(root).count('thread/fork') == 2
        assert wire(root).count('turn/start') == 2
    elif change == 'task-result':
        submitted_result(root)
        with owned_child(root, [], alias='research@x1', task_id='148'):
            reply = native_hook(root)
        assert wire(root).count('thread/fork') == 1
    else:
        with owned_child(root, [{'request_id': 'permission-1', 'method': 'claude/can_use_tool'}]):
            reply = native_hook(root)
        assert wire(root).count('thread/fork') == 1
    assert reply['decision'] == 'block'


def test_task_state_change_requires_new_checker(host: tuple[Path, Path]) -> None:
    """Task facts changing without a Main message invalidate a previous release."""
    root, _ = host
    rollout(root)
    assert native_hook(root)['systemMessage']
    submitted_result(root)
    (root / 'options.json').write_text(json.dumps({'child': 'next-checker'}))
    assert native_hook(root)['systemMessage']
    assert wire(root).count('thread/fork') == 2
    assert wire(root).count('turn/start') == 2


def test_native_cancel_is_silent_and_next_stop_checks(host: tuple[Path, Path]) -> None:
    """The automatic hook does not replace silent cancellation with skipped chatter."""
    root, binding = host
    rollout(root)
    (root / 'options.json').write_text(json.dumps({'interrupt_during_check': True}))
    assert native_hook(root) == {}
    evidence = yaml.safe_load(next(binding.parent.glob('checks/*/execution.yml')).read_text())
    assert evidence['outcome'] == 'cancelled'
    (root / 'options.json').write_text(json.dumps({'child': 'next-checker'}))
    assert native_hook(root)['systemMessage']
    assert wire(root).count('turn/start') == 2


def test_usage_telemetry_does_not_start_another_checker(host: tuple[Path, Path]) -> None:
    """A usage-only update is not new Main input or a new completion boundary."""
    root, _ = host
    rollout(root)
    assert native_hook(root)['systemMessage']
    with (root / 'rollout.jsonl').open('a') as stream:
        stream.write(json.dumps(token_record(input_tokens=100, cached_input_tokens=50,
                                             output_tokens=20, reasoning_output_tokens=10)) + '\n')
    assert native_hook(root) == {}
    assert wire(root).count('thread/fork') == wire(root).count('turn/start') == 1


def test_new_native_input_during_check_discards_old_verdict(host: tuple[Path, Path]) -> None:
    """Accepted same-turn native input cannot return or cache the older waiting verdict."""
    import threading
    from conftest import wait_for_file

    root, binding = host
    rollout(root)
    (root / 'options.json').write_text(json.dumps({'hold_check': 0.3}))

    def receive_input() -> None:
        """Append the native input while the checker is already running."""
        wait_for_file(root / 'checker-running')
        with (root / 'rollout.jsonl').open('a') as stream:
            stream.write(json.dumps({'type': 'response_item', 'payload': {
                'type': 'message', 'role': 'user', 'content': 'Continue with the new task.',
            }}) + '\n')

    sender = threading.Thread(target=receive_input)
    sender.start()
    assert native_hook(root) == {}
    sender.join(timeout=5)
    assert not sender.is_alive()
    evidence = yaml.safe_load(next(binding.parent.glob('checks/*/execution.yml')).read_text())
    assert evidence['outcome'] == 'cancelled' and evidence['cancellation']
    (root / 'options.json').write_text(json.dumps({'child': 'next-checker'}))
    assert native_hook(root)['systemMessage']
    assert wire(root).count('thread/fork') == wire(root).count('turn/start') == 2


@pytest.mark.parametrize('outcome', ['completed', 'runtime-error'])
@pytest.mark.parametrize('terminal_record', [False, True])
def test_execution_activity_invalidates_waiting_without_task_or_input_change(
    host: tuple[Path, Path], outcome: str, terminal_record: bool,
) -> None:
    """A child ending changes reuse validity before any Task event or notification."""
    from test_generic_members import _register_research_team
    from graphtraj.graph.task_index import read_index

    root, _ = host
    configuration = root / '.graphtraj/config.yml'
    document = yaml.safe_load(configuration.read_text())
    document['paths']['state'] = 'state'
    configuration.write_text(yaml.safe_dump(document))
    _register_research_team(root, multiple=False)
    rollout(root)
    transcript = (root / 'rollout.jsonl').read_bytes()
    index = read_index(root / 'state')
    activity = {'activity': 'running'}
    (root / 'options.json').write_text(json.dumps({'output': json.dumps({
        'status': 'waiting', 'conclusion': 'May end.', 'reason': 'Child running.', 'nodes': ['148'],
    })}))
    with owned_child(root, [], alias='research@x1', task_id='148', activity=activity):
        assert 'waiting' in native_hook(root)['systemMessage']
        assert native_hook(root) == {}
        assert wire(root).count('thread/fork') == wire(root).count('turn/start') == 1
        activity.update(activity='idle', last_outcome=outcome)
        if terminal_record:
            (root / '.graphtraj/runner/sessions/research@x1/execution.yml').write_text(
                yaml.safe_dump({'outcome': outcome}))
        (root / 'options.json').write_text(json.dumps({'child': 'next-checker', 'output': json.dumps({
            'status': 'actionable', 'conclusion': 'Continue.', 'reason': 'Handle the ended child.',
            'nodes': ['148'],
        })}))
        assert native_hook(root)['decision'] == 'block'
    assert (root / 'rollout.jsonl').read_bytes() == transcript
    assert read_index(root / 'state') == index
    assert wire(root).count('thread/fork') == wire(root).count('turn/start') == 2


def test_continued_flag_reuses_but_new_turn_still_checks(host: tuple[Path, Path]) -> None:
    """Carrier reentry alone reuses a release; a real later native turn still checks."""
    root, _ = host
    rollout(root)
    assert native_hook(root)['systemMessage']
    (root / 'options.json').write_text(json.dumps({'child': 'carrier-checker'}))
    assert native_hook(root, stop_hook_active=True) == {}
    assert wire(root).count('thread/fork') == wire(root).count('turn/start') == 1
    with (root / 'rollout.jsonl').open('a') as stream:
        stream.write(json.dumps({'type': 'turn_context', 'payload': {
            'turn_id': 'next-main-turn', 'model': 'actual-model', 'effort': 'high',
        }}) + '\n')
    (root / 'options.json').write_text(json.dumps({'child': 'next-checker', 'current_turn': 'next-main-turn'}))
    assert native_hook(root, turn_id='next-main-turn')['systemMessage']
    assert wire(root).count('thread/fork') == wire(root).count('turn/start') == 2
