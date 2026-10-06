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
                         'modelProvider':'actual-provider','status':{'type':'active'}}}
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
            result={'data': options.get('spawn_items',[]),'nextCursor':None}
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
        result, observed=call(ready,'collect',checker_alias=prepared['checker_alias'],task_name=path)
        assert result.exit_code!=0
        assert observed['native_observation']['session']=='actual-child'
        assert 'Fresh authorization' in observed['native_observation']['output']
        assert observed['status']=='failed' and observed['result']['status']=='error'
        assert 'output schema' in observed['result']['reason']
        assert observed['hook_response']['continue'] is False
        assert not delivered


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
