"""Public native preparation uses task-path hints, real transport and retained identity."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from graphtraj.execution.host_adoption import external_main
from graphtraj.interfaces.cli.graphtraj import main
from test_host_adoption import external
from test_main_finalize import host


PEER = r'''
import json, os, sys
from pathlib import Path
root=Path(os.environ['FINALIZE_TEST_ROOT'])
options=json.loads((root/'native-options.json').read_text())
child=options.get('child')
for line in sys.stdin:
    request=json.loads(line)
    with (root/'prepared-wire.jsonl').open('a') as stream: stream.write(json.dumps(request)+'\n')
    method=request['method']; p=request.get('params',{})
    if method=='initialized': continue
    result={}
    if method=='thread/read':
        result={'thread':{'id':p['threadId'],'sessionId':'shared-native-session','model':'actual-model',
                         'modelProvider':'actual-provider','status':{'type':
                         'idle' if p['threadId']=='main' and options.get('main_stopped') else 'active'}}}
    elif method=='thread/list':
        result={'data':[child] if child is not None and p.get('archived',False)==options.get('archived',False) else [],'nextCursor':None}
    elif method=='thread/turns/list':
        parent=p['threadId']=='main'
        state='inProgress' if parent else options.get('child_status','completed')
        if not parent and (root/'native-interrupted').exists(): state='interrupted'
        result={'data':[{'id':options.get('main_turn','main-turn') if parent else 'child-turn',
                         'status':state,'items':[]}]}
    elif method=='thread/items/list':
        if p['threadId']=='main':
            items=options.get('spawn_items',[])
            start=int(p.get('cursor',0)); end=start+options.get('main_page_size',100)
            result={'data':items[start:end],'nextCursor':str(end) if end<len(items) else None}
        else:
            result={'data':[{'turnId':'child-turn','item':{'type':'agentMessage','id':'answer',
                    'phase':'final_answer','text':options.get('output',json.dumps({'status':'waiting',
                    'reason':'Fresh authorization required.','nodes':['272']}))}}],'nextCursor':None}
    elif method=='turn/interrupt':
        (root/'native-interrupted').write_text(p['threadId'])
    print(json.dumps({'id':request['id'],'result':result}),flush=True)
'''


@pytest.fixture
def prepared_external(external: tuple):
    """Replace native responses only, retaining public owner, tool and CLI transport."""
    root, _, _ = external
    (root/'peer.py').write_text(PEER)
    (root/'native-options.json').write_text('{}')
    yield external


def call(ready: dict, action: str, **arguments: object):
    """Invoke the real approved external Main command, not an internal helper."""
    result=CliRunner().invoke(main, ['main-operation','--binding',ready['operation_binding'],
        '--request',json.dumps({'action':'execute','feature':'finish_check',
                               'arguments':{'action':action,**arguments}})])
    document=json.loads(result.stdout) if result.stdout.strip() else {'error':result.stderr}
    return result, document.get('document',document)


def native_child(root: Path, prepared: dict, **changes: object) -> str:
    """Publish controlled native fork metadata and its checked-turn spawn item."""
    path='/root/'+prepared['native_action']['arguments']['task_name']
    options={'child':{'id':'actual-child','parentThreadId':'main','forkedFromId':'main',
                     'model':'actual-model','modelProvider':'actual-provider','reasoningEffort':'high',
                     'source':{'subAgent':{'thread_spawn':{'parent_thread_id':'main','agent_path':path}}}},
             'spawn_items':[{'turnId':'main-turn','item':{'id':'spawn-call','type':'collabAgentToolCall',
                'tool':'spawnAgent','senderThreadId':'main','receiverThreadIds':['actual-child'],
                'status':'completed'}}],**changes}
    (root/'native-options.json').write_text(json.dumps(options))
    return path


def test_prepare_correlate_and_read_native_result(prepared_external: tuple) -> None:
    """The task-path result resolves to native evidence; incomplete config never passes."""
    root, _, delivered = prepared_external
    with external_main(root) as ready:
        result, prepared=call(ready,'prepare')
        assert result.exit_code==0, result.output
        assert prepared['status']=='prepared'
        arguments=prepared['native_action']['arguments']
        assert set(arguments)=={'task_name','message','fork_turns'} and arguments['fork_turns']=='all'
        _, repeated=call(ready,'prepare')
        assert repeated['checker_alias']==prepared['checker_alias']
        path=native_child(root,prepared)
        result, observed=call(ready,'collect',checker_alias=prepared['checker_alias'],task_name=path,
                              wait_seconds=30)
        assert result.exit_code!=0
        assert observed['native_observation']['session']=='actual-child'
        assert 'Fresh authorization' in observed['native_observation']['output']
        assert observed['status']=='failed' and observed['result']['status']=='error'
        assert 'output schema' in observed['result']['reason']
        assert observed['hook_response']['continue'] is False
        assert not delivered


@pytest.mark.parametrize('duration', [-1, 31, float('nan'), float('inf')])
def test_public_collect_rejects_invalid_wait_without_changing_preparation(
    prepared_external: tuple, duration: float,
) -> None:
    """The public gateway accepts bounded numbers and refuses invalid waits visibly."""
    root, _, _ = prepared_external
    with external_main(root) as ready:
        _, prepared = call(ready, 'prepare')
        record = root / '.graphtraj/runner/sessions' / prepared['checker_alias'] / 'execution.yml'
        before = record.read_bytes()
        result, response = call(ready, 'collect', checker_alias=prepared['checker_alias'],
                                wait_seconds=duration)
        assert result.exit_code != 0
        assert 'wait_seconds' in response['systemMessage']
        assert record.read_bytes() == before


@pytest.mark.parametrize('change', ['path','parent','fork','turn','missing_spawn'])
def test_untrusted_return_requires_preparation_correlation(prepared_external: tuple, change: str) -> None:
    """A matching parent or model-supplied path is insufficient for checker adoption."""
    root, _, _=prepared_external
    with external_main(root) as ready:
        _, prepared=call(ready,'prepare')
        path=native_child(root,prepared)
        options=json.loads((root/'native-options.json').read_text())
        if change=='path': path='/root/other-check'
        if change=='parent': options['child']['parentThreadId']='other'
        if change=='fork': options['child']['forkedFromId']='other'
        if change=='turn': options['spawn_items'][0]['turnId']='old-turn'
        if change=='missing_spawn': options['spawn_items']=[]
        (root/'native-options.json').write_text(json.dumps(options))
        result,_=call(ready,'collect',checker_alias=prepared['checker_alias'],task_name=path)
        assert result.exit_code!=0
        directory=root/'.graphtraj/runner/sessions'/prepared['checker_alias']
        assert not (directory/'native.yml').exists()
        # Restore genuine fixture metadata so normal owner cleanup can cancel it.
        native_child(root,prepared)


def test_running_child_wait_cancel_and_stale_turn(prepared_external: tuple) -> None:
    """Interrupt the proven external child through native operations, retaining its record."""
    root, _, _=prepared_external
    with external_main(root) as ready:
        _, prepared=call(ready,'prepare')
        path=native_child(root,prepared,child_status='inProgress')
        result, running=call(ready,'collect',checker_alias=prepared['checker_alias'],task_name=path)
        assert result.exit_code==0 and running['status']=='running'
        native_child(root,prepared,child_status='inProgress',main_turn='later-turn')
        result,cancelled=call(ready,'collect',checker_alias=prepared['checker_alias'],task_name=path)
        assert result.exit_code==0 and cancelled['status']=='cancelled'
        assert (root/'native-interrupted').read_text()=='actual-child'
        assert (root/'.graphtraj/runner/sessions'/prepared['checker_alias']/'native.yml').exists()


def test_owner_close_cancels_prepared_native_execution(prepared_external: tuple) -> None:
    """Normal owner closure interrupts a verified live child and preserves history."""
    root, _, _=prepared_external
    with external_main(root) as ready:
        _, prepared=call(ready,'prepare')
        native_child(root,prepared,child_status='inProgress')
    assert (root/'native-interrupted').read_text()=='actual-child'
    assert (root/'.graphtraj/runner/sessions'/prepared['checker_alias']/'execution.yml').exists()


def test_hook_requests_preparation_without_claiming_checker_verdict(prepared_external: tuple) -> None:
    """The actual fixed handler requests only its exact prepared native action."""
    from test_host_adoption import EVENT, invoke_hook

    root, _, delivered=prepared_external
    with external_main(root) as ready:
        result=invoke_hook(ready,EVENT)
        assert result.returncode==0
        assert '[GraphTraj hook: finish-check] start:' in result.stderr
        response=json.loads(result.stdout)
        assert response['decision']=='block' and 'preparation required' in response['reason']
        prepared=json.loads(response['reason'][response['reason'].index('{'):])
        assert prepared['status']=='prepared'
        assert prepared['native_action']['tool']=='collaboration.spawn_agent'
        assert 'prepare:' in response['systemMessage'] and not delivered
        _, repeated=call(ready,'prepare')
        assert repeated['checker_alias']==prepared['checker_alias']


def test_registered_native_checker_hook_is_excluded(prepared_external: tuple) -> None:
    """Association established by collection gives the real child a no-recursion identity."""
    from test_host_adoption import EVENT, invoke_hook

    root, _, delivered=prepared_external
    with external_main(root) as ready:
        _, prepared=call(ready,'prepare')
        path=native_child(root,prepared,child_status='inProgress')
        result,_=call(ready,'collect',checker_alias=prepared['checker_alias'],task_name=path)
        assert result.exit_code==0
        response=invoke_hook(ready,{**EVENT,'turn_id':'child-turn'})
        assert 'GraphTraj checker' in json.loads(response.stdout)['systemMessage']
        assert not delivered


def test_no_main_transcribed_verdict_is_accepted(prepared_external: tuple) -> None:
    """The public schema refuses a caller's substitute result even for its own check."""
    root, _, _=prepared_external
    with external_main(root) as ready:
        _, prepared=call(ready,'prepare')
        result,_=call(ready,'collect',checker_alias=prepared['checker_alias'],
                      result={'status':'completed','reason':'caller claim','nodes':[]})
        assert result.exit_code!=0


@pytest.mark.parametrize('changed', [False, True])
def test_native_spawn_without_optional_fork_origin_keeps_turn_protection(
    prepared_external: tuple, changed: bool,
) -> None:
    """Real spawn correlation permits null origin, but steering invalidates its result."""
    root, _, _ = prepared_external
    with external_main(root) as ready:
        _, prepared = call(ready, 'prepare')
        path = native_child(root, prepared)
        options = json.loads((root / 'native-options.json').read_text())
        options['child']['forkedFromId'] = None
        if changed:
            options['spawn_items'].append({'turnId': 'main-turn', 'item': {
                'type': 'userMessage', 'id': 'later-input', 'content': [],
            }})
        (root / 'native-options.json').write_text(json.dumps(options))
        result, response = call(ready, 'collect', checker_alias=prepared['checker_alias'],
                                task_name=path, wait_seconds=30)
        assert response['native_observation']['session'] == 'actual-child'
        if changed:
            assert result.exit_code == 0 and response['status'] == 'cancelled'
            assert 'result' not in response
        else:
            assert response['native_observation']['state'] == 'completed'
            assert result.exit_code != 0 and response['result']['status'] == 'error'
            assert 'configuration_error' in response['native_observation']


@pytest.mark.parametrize('changes', [{'child_status':'failed'}, {'output':'not a checker verdict'}])
def test_native_execution_and_result_failure_are_visible(prepared_external: tuple, changes: dict) -> None:
    """Native failure or unreadable output cannot become a completed/waiting verdict."""
    root, _, _=prepared_external
    with external_main(root) as ready:
        _, prepared=call(ready,'prepare')
        path=native_child(root,prepared,**changes)
        result, response=call(ready,'collect',checker_alias=prepared['checker_alias'],task_name=path)
        assert result.exit_code!=0 and response['status']=='failed'
        assert response['result']['status']=='error'
        assert 'failure:' in response['hook_response']['systemMessage']


def test_same_turn_new_user_input_invalidates_result(prepared_external: tuple) -> None:
    """A steered goal cannot receive the prepared checker verdict for earlier input."""
    root, _, _=prepared_external
    with external_main(root) as ready:
        _, prepared=call(ready,'prepare')
        path=native_child(root,prepared)
        options=json.loads((root/'native-options.json').read_text())
        options['spawn_items'].append({'turnId':'main-turn','item':{
            'type':'userMessage','id':'new-user-input','content':[{'type':'text','text':'Changed goal'}]}})
        (root/'native-options.json').write_text(json.dumps(options))
        result,response=call(ready,'collect',checker_alias=prepared['checker_alias'],task_name=path)
        assert result.exit_code==0 and response['status']=='cancelled'
        assert 'result' not in response


@pytest.mark.parametrize('running', [False, True])
def test_v2_native_function_output_correlates_and_cancels_steered_check(
    prepared_external: tuple, running: bool,
) -> None:
    """Native v2 output links the child; new Main input cancels even a live child."""
    root, _, _ = prepared_external
    with external_main(root) as ready:
        _, prepared = call(ready, 'prepare')
        path = native_child(root, prepared, child_status='inProgress' if running else 'completed')
        options = json.loads((root / 'native-options.json').read_text())
        options['child']['forkedFromId'] = None
        options['main_page_size'] = 1
        options['spawn_items'] = [
            {'turnId': 'main-turn', 'item': {'id': 'earlier-item', 'type': 'agentMessage'}},
            {'turnId': 'main-turn', 'item': {
                'id': 'native-spawn-output', 'type': 'functionCallOutput',
                'namespace': 'collaboration', 'name': 'spawn_agent',
                'output': json.dumps({'task_name': path}),
            }},
            {'turnId': 'main-turn', 'item': {'id': 'steering', 'type': 'userMessage'}},
        ]
        (root / 'native-options.json').write_text(json.dumps(options))
        result, response = call(ready, 'collect', checker_alias=prepared['checker_alias'],
                                task_name=path, wait_seconds=0)
        assert result.exit_code == 0, result.output
        assert response['status'] == 'cancelled' and 'result' not in response
        assert response['native_observation']['spawn_call'] == 'native-spawn-output'
        if running:
            assert (root / 'native-interrupted').read_text() == 'actual-child'


@pytest.mark.parametrize('change', ['namespace', 'name', 'output', 'path', 'turn', 'duplicate'])
def test_v2_output_requires_unique_native_spawn_for_prepared_turn(
    prepared_external: tuple, change: str,
) -> None:
    """Lookalike results and stale or duplicated native outputs cannot establish identity."""
    root, _, _ = prepared_external
    with external_main(root) as ready:
        _, prepared = call(ready, 'prepare')
        path = native_child(root, prepared)
        options = json.loads((root / 'native-options.json').read_text())
        item = {'id': 'native-spawn-output', 'type': 'functionCallOutput',
                'namespace': 'collaboration', 'name': 'spawn_agent',
                'output': json.dumps({'task_name': path})}
        entry = {'turnId': 'main-turn', 'item': item}
        if change in ('namespace', 'name', 'output'):
            item[change] = 'unrelated'
        if change == 'path':
            item['output'] = json.dumps({'task_name': '/root/other'})
        if change == 'turn':
            entry['turnId'] = 'old-turn'
        options['spawn_items'] = [entry, entry] if change == 'duplicate' else [entry]
        (root / 'native-options.json').write_text(json.dumps(options))
        result, _ = call(ready, 'collect', checker_alias=prepared['checker_alias'], task_name=path)
        assert result.exit_code != 0
        assert not (root / '.graphtraj/runner/sessions' / prepared['checker_alias'] / 'native.yml').exists()
        native_child(root, prepared)


def test_native_association_failure_reports_only_safe_predicate_metadata(
    prepared_external: tuple,
) -> None:
    """The public failure exposes the read turn and mismatch, never native message bodies."""
    root, _, _ = prepared_external
    with external_main(root) as ready:
        _, prepared = call(ready, 'prepare')
        path = native_child(root, prepared)
        options = json.loads((root / 'native-options.json').read_text())
        options['spawn_items'] = [{'turnId': 'main-turn', 'item': {
            'id': 'native-call', 'type': 'functionCallOutput', 'namespace': 'unexpected',
            'name': 'spawn_agent', 'prompt': 'PRIVATE_PROMPT',
            'output': json.dumps({'task_name': path, 'credential': 'PRIVATE_CREDENTIAL'}),
        }}, {'turnId': 'main-turn', 'item': {
            'id': 'activity', 'type': 'subAgentActivity', 'kind': 'interacted',
            'agentThreadId': 'actual-child', 'agentPath': path,
        }}]
        (root / 'native-options.json').write_text(json.dumps(options))
        result, response = call(ready, 'collect', checker_alias=prepared['checker_alias'], task_name=path)
        assert result.exit_code != 0
        visible = json.dumps(response)
        assert 'read_turn' in visible and 'main-turn' in visible
        assert 'namespace_matches' in visible and 'unexpected' in visible
        assert 'matching_call_count' in visible and 'output_task_matches' in visible
        assert 'agentThreadId' in visible and 'actual-child' in visible and 'interacted' in visible
        assert 'PRIVATE_PROMPT' not in visible and 'PRIVATE_CREDENTIAL' not in visible
        assert not (root / '.graphtraj/runner/sessions' / prepared['checker_alias'] / 'native.yml').exists()
        native_child(root, prepared)


@pytest.mark.parametrize('scenario', [
    'current', 'stale', 'running-stale', 'interacted', 'completed',
    'path', 'child', 'turn', 'duplicate', 'missing-id', 'parent',
])
def test_observed_native_started_activity_preserves_preparation_guards(
    prepared_external: tuple, scenario: str,
) -> None:
    """Use the host-observed Started/Completed shape; only a unique exact start binds."""
    root, _, delivered = prepared_external
    with external_main(root) as ready:
        _, prepared = call(ready, 'prepare')
        path = native_child(root, prepared,
                            child_status='inProgress' if scenario == 'running-stale' else 'completed')
        options = json.loads((root / 'native-options.json').read_text())
        options['child']['forkedFromId'] = None
        item = {'type': 'subAgentActivity', 'kind': 'started', 'id': 'native-start-call',
                'agentThreadId': 'actual-child', 'agentPath': path}
        entry = {'turnId': 'main-turn', 'item': item}
        options['main_page_size'] = 1
        options['spawn_items'] = [
            {'turnId': 'main-turn', 'item': {**item, 'id': 'unrelated-call',
                                            'agentThreadId': 'another-child', 'agentPath': '/root/other'}},
            entry,
            {'turnId': 'main-turn', 'item': {**item, 'kind': 'completed', 'id': 'child-completed'}},
        ]
        if scenario in ('stale', 'running-stale'):
            options['spawn_items'].append({'turnId': 'main-turn', 'item': {
                'type': 'userMessage', 'id': 'new-main-input',
            }})
        if scenario in ('interacted', 'completed'):
            item['kind'] = scenario
        if scenario == 'path':
            item['agentPath'] = '/root/other'
        if scenario == 'child':
            item['agentThreadId'] = 'another-child'
        if scenario == 'turn':
            entry['turnId'] = 'earlier-turn'
        if scenario == 'duplicate':
            options['spawn_items'].append({'turnId': 'main-turn', 'item': {**item, 'id': 'second-start'}})
        if scenario == 'missing-id':
            item.pop('id')
        if scenario == 'parent':
            options['child']['parentThreadId'] = 'another-parent'
        (root / 'native-options.json').write_text(json.dumps(options))
        result, response = call(ready, 'collect', checker_alias=prepared['checker_alias'], task_name=path)
        if scenario in ('current', 'stale', 'running-stale'):
            assert response['native_observation']['spawn_call'] == 'native-start-call'
            if scenario == 'current':
                assert result.exit_code != 0 and response['result']['status'] == 'error'
                assert 'configuration_error' in response['native_observation']
            else:
                assert result.exit_code == 0 and response['status'] == 'cancelled'
                assert 'result' not in response
            if scenario == 'running-stale':
                assert (root / 'native-interrupted').read_text() == 'actual-child'
        else:
            assert result.exit_code != 0
            assert not (root / '.graphtraj/runner/sessions' / prepared['checker_alias'] / 'native.yml').exists()
            native_child(root, prepared)
        assert not delivered



def test_completed_archived_child_is_resolved_by_native_task_path(prepared_external: tuple) -> None:
    """A finished native task remains readable without private metadata scanning."""
    root, _, _=prepared_external
    with external_main(root) as ready:
        _, prepared=call(ready,'prepare')
        path=native_child(root,prepared,archived=True)
        _, response=call(ready,'collect',checker_alias=prepared['checker_alias'],task_name=path)
        assert response['native_observation']['session']=='actual-child'
        assert response['native_observation']['state']=='completed'
        assert response['result']['status']=='error'  # Remaining config is still unconfirmed.


def test_prepared_checker_retains_read_only_graphtraj_interface(
    prepared_external: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Public child registration keeps checker identity but refuses write operations."""
    from graphtraj.interfaces.local_tool import HostTool

    root, _, _=prepared_external
    captured=[]
    original=HostTool.register_checker

    def register(parent: HostTool, *args: object, **kwargs: object) -> HostTool:
        """Observe the actual public registration result without replacing its behavior."""
        child=original(parent,*args,**kwargs)
        captured.append(child)
        return child

    monkeypatch.setattr(HostTool,'register_checker',register)
    with external_main(root) as ready:
        result, prepared=call(ready,'prepare')
        assert result.exit_code==0
        identity=captured[0]({'action':'execute','feature':'agent_identity','arguments':{}})
        assert identity.document['alias']==prepared['checker_alias']
        assert identity.document['purpose']=='checker'
        denied=captured[0]({'action':'execute','feature':'send_instruction',
                            'arguments':{'alias':ready['alias'],'instruction':'not authorized'}})
        assert denied.failed
        assert denied.document['error']=='Unknown feature: send_instruction'


@pytest.mark.parametrize('entry', ['prepare', 'hook'])
def test_history_growth_does_not_expand_native_action_and_cancel_allows_retry(
    prepared_external: tuple, entry: str,
) -> None:
    """Public cancellation preserves the old request; history is queried, not injected."""
    from test_host_adoption import EVENT, invoke_hook

    root, _, _ = prepared_external
    with external_main(root) as ready:
        def prepare_request() -> dict:
            """Read the exact Adapter material through either supported Main entry."""
            if entry == 'prepare':
                result, document = call(ready, 'prepare')
                assert result.exit_code == 0, result.output
                return document
            result = invoke_hook(ready, EVENT)
            assert result.returncode == 0, result.stderr
            response = json.loads(result.stdout)
            return json.loads(response['reason'][response['reason'].index('{'):])

        first = prepare_request()
        result, cancelled = call(ready, 'cancel', checker_alias=first['checker_alias'])
        assert result.exit_code == 0 and cancelled['status'] == 'cancelled'
        old_directory = root / '.graphtraj/runner/sessions' / first['checker_alias']
        retained = {name: (old_directory / name).read_bytes()
                    for name in ('mapping.yml', 'execution.yml')}
        registered = CliRunner().invoke(main, ['main-operation', '--binding', ready['operation_binding'],
            '--request', json.dumps({'action': 'execute', 'feature': 'ticket_register', 'arguments': {
                'ticket_id': '88', 'ticket_name': 'historical-context',
                'source': 'https://github.com/example/project/issues/88',
                'title': 'Historical task', 'body': '历史任务内容' * 10000, 'dependencies': [],
            }})])
        assert registered.exit_code == 0, registered.output
        second = prepare_request()
        assert second['checker_alias'] != first['checker_alias']
        assert second['checked_turn'] == first['checked_turn']
        assert second['native_action']['arguments']['message'] == first['native_action']['arguments']['message']
        assert second['native_action']['arguments']['task_name'] != first['native_action']['arguments']['task_name']
        repeated = prepare_request()
        assert repeated['checker_alias'] == second['checker_alias']
        assert repeated['native_action'] == second['native_action']
        assert {name: (old_directory / name).read_bytes() for name in retained} == retained
        _, old = call(ready, 'collect', checker_alias=first['checker_alias'])
        assert old['status'] == 'cancelled'
