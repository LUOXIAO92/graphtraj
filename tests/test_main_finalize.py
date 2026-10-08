"""Main completion checks through public host entry and a controlled native peer."""

from __future__ import annotations

import json
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


def test_binding_description_delivers_manual(tmp_path: Path) -> None:
    """Describe the binding without Main authority or executing a native hook."""
    result = bind(tmp_path)({'action': 'describe', 'feature': 'bind_main_finalize'})

    assert not result.failed
    assert Path(result.document['manual_ref']).read_text(encoding='utf-8')
    parameters = bind(tmp_path)({'action': 'describe', 'feature': 'bind_main_finalize', 'schema': True})
    assert parameters.document['input_schema']['required'] == ['summary_issue']


PEER = r'''
import json, os, sys
from pathlib import Path
root = Path(os.environ['FINALIZE_TEST_ROOT'])
options = json.loads((root / 'options.json').read_text())

def send(message):
    print(json.dumps(message), flush=True)

def main_thread():
    return {'id':'main', 'sessionId':'shared-native-session', 'model':'configured-model', 'modelProvider':'actual-provider',
            'source':options.get('source','appServer'), 'parentThreadId':options.get('parent'),
            'status':{'type':'active' if not options.get('stopped') else 'idle'}}

for line in sys.stdin:
    request = json.loads(line)
    with (root / 'wire.jsonl').open('a') as stream:
        stream.write(json.dumps(request) + '\n')
    method, params = request['method'], request.get('params', {})
    if method == 'initialized': continue
    result = {}
    if method == 'thread/read':
        result = {'thread':main_thread()}
        if options.get('read_id_from_request'): result['thread']['id'] = params['threadId']
    elif method == 'thread/resume':
        result = {'thread':main_thread()}
        if options.get('parent_approval'):
            send({'id':'parent-approval','method':'item/commandExecution/requestApproval',
                  'params':{'threadId':'main','turnId':'main-turn','itemId':'parent-command',
                            'command':'read approved source','cwd':str(root)}})
    elif method == 'thread/turns/list':
        result = {'data':[{'id':options.get('current_turn','main-turn'), 'status':'inProgress'}]}
    elif method == 'thread/fork':
        if options.get('fork_error'):
            send({'id':request['id'],'error':{'code':-32600,'message':'fork unavailable'}})
            continue
        # The peer owns context inheritance; the caller supplies no history.
        parent_context = ['original developer instructions','private context sentinel']
        child = {'id':options.get('child','checker'),'forkedFromId':'main'}
        (root / 'child-context.json').write_text(json.dumps(parent_context))
        result = {'thread':child, 'model':options.get('fork_model','actual-model'),
                  'modelProvider':'actual-provider', 'reasoningEffort':params.get('config',{}).get('model_reasoning_effort')}
    elif method == 'turn/start':
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
            reply = json.loads(sys.stdin.readline())
            (root / 'approval-reply.json').write_text(json.dumps(reply))
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
        text = options.get('output',json.dumps({'status':'completed','reason':'All required tickets integrated.','nodes':[]}))
        send({'method':'item/completed','params':{'threadId':params['threadId'],'turnId':'check-turn',
              'item':{'id':'answer','type':'agentMessage','text':text}}})
        turn['status'] = 'completed'
        send({'method':'turn/completed','params':{'threadId':params['threadId'],'turn':turn}})
        if options.get('interrupt_during_check'): options['stopped'] = True
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
    ('completed', 'All required tickets integrated.', []),
    ('waiting', 'Required child execution remains running.', ['237']),
    ('waiting', 'User approval pending; no other actionable node.', ['238']),
    ('waiting', 'External event pending; no other actionable node.', ['239']),
    ('actionable', '237 has authorized unfinished work; implement the checker.', ['237']),
])
def test_main_end_decision(
    host: tuple[Path, Path], status: str, reason: str, nodes: list[str],
) -> None:
    """Only actionable nodes block Stop; all checks use a native context fork."""
    root, binding = host
    (root / 'options.json').write_text(json.dumps({'output':json.dumps({
        'status':status, 'reason':reason, 'nodes':nodes,
    })}))
    result = stop(binding)
    if status == 'actionable':
        assert result['decision'] == 'block' and result['reason'] == reason + '\n237'
        assert result['systemMessage']
    else:
        assert result['systemMessage']
        assert 'decision' not in result
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    fork = next(item['params'] for item in wire if item['method'] == 'thread/fork')
    assert fork == {'threadId':'main', 'model':'actual-model', 'modelProvider':'actual-provider',
                    'excludeTurns':True}
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
    {'output':json.dumps({'status':'actionable', 'reason':'Unfinished', 'nodes':[]})},
    {'output':json.dumps({'status':'error', 'reason':'Referenced Issue unavailable', 'nodes':['237']})},
])
def test_checker_failures_are_visible_and_bounded(host: tuple[Path, Path], options: dict) -> None:
    """An error is returned once to Main and cannot generate endless error turns."""
    root, binding = host
    (root / 'options.json').write_text(json.dumps(options))
    first = stop(binding)
    assert first['continue'] is False and first['systemMessage']
    assert 'decision' not in first
    # A fresh native checker Session is still required on the continued Stop.
    if options.get('child') != 'main':
        options['child'] = 'checker-two'
    (root / 'options.json').write_text(json.dumps(options))
    second = stop(binding, stop_hook_active = True)
    assert second['continue'] is False and second['systemMessage']


@pytest.mark.parametrize('options', [{'stopped':True}, {'current_turn':'another-turn'},
                                     {'interrupt_during_check':True}])
def test_stopped_or_changed_main_is_not_continued(host: tuple[Path, Path], options: dict) -> None:
    """A stale Stop cannot wake a stopped Main, including interruption mid-check."""
    root, binding = host
    options['output'] = json.dumps({'status':'actionable', 'reason':'unfinished', 'nodes':['237']})
    (root / 'options.json').write_text(json.dumps(options))
    assert stop(binding) == {}


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
            return {'session': 'actual-child', 'output': json.dumps({
                'status': 'waiting', 'reason': 'Approval pending', 'nodes': ['237'],
            })}

        def finalize_response(self, result: dict | None, continued: bool) -> dict:
            """Return this host's end decision without Codex hook fields."""
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


@pytest.mark.parametrize('feature,allowed', [('ticket_graph', True), ('send_instruction', False)])
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
    assert 'completed' in result['systemMessage']
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    assert not any(item.get('id') == 'parent-approval' for item in wire)


def test_checker_reports_missing_native_approval_interface(host: tuple[Path, Path]) -> None:
    """Unavailable user approval is an explicit error and never an implicit grant."""
    root, binding = host
    (root / 'options.json').write_text(json.dumps({'approval_request': True}))
    result = stop(binding)
    assert result['continue'] is False
    assert 'no bound user approval interface' in result['systemMessage']
    reply = json.loads((root / 'approval-reply.json').read_text())
    assert 'error' in reply and 'result' not in reply


def test_only_observed_cache_usage_is_retained(host: tuple[Path, Path]) -> None:
    """Preserve native token accounting without inventing cache hits or thresholds."""
    root, binding = host
    usage = {'last': {'inputTokens': 113, 'cachedInputTokens': 0, 'outputTokens': 19}}
    (root / 'options.json').write_text(json.dumps({'usage': usage}))
    assert stop(binding)['systemMessage']
    evidence = next(binding.parent.glob('checks/*/execution.yml'))
    assert yaml.safe_load(evidence.read_text())['usage'] == usage


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
    assert 'completed' in result['systemMessage']
    assert 'decision' not in result and 'continue' not in result
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    forks = [r['params'] for r in wire if r['method'] == 'thread/fork']
    assert len(forks) == 1
    assert forks[0]['config']['model_reasoning_effort'] == 'high'
    assert [r['params']['threadId'] for r in wire if r['method'] == 'turn/start'] == ['checker']


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
    assert native_hook(root) == {}
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
    assert native_hook(root) == {}
    rollout(root)
    result = native_hook(root, turn_id='missing-turn')
    assert result['continue'] is False and 'settings' in result['systemMessage']


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


def test_hook_configuration_is_only_adoption_material(tmp_path: Path) -> None:
    """Producing configuration does not activate hooks or require identity input."""
    reply = CliRunner().invoke(stop_hook, ['--configuration'])
    assert reply.exit_code == 0
    configuration = json.loads(reply.output)
    assert set(configuration['hooks']) == {'SessionStart', 'Stop'}
    assert not list(tmp_path.iterdir())
