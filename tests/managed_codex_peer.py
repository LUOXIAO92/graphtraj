"""Controlled native boundary; production Runner and CodexAppServer remain real."""
import json
import os
import sys
import time
import uuid
from pathlib import Path


def emit(value: dict) -> None:
    """Write a native reply or notification."""
    print(json.dumps(value), flush=True)


if sys.argv[1:] == ['exec', '--help']:
    print('--sandbox')
    sys.exit(0)
assert sys.argv[1:] == ['app-server', '--listen', 'stdio://'], sys.argv
for line in sys.stdin:
    request = json.loads(line)
    method = request.get('method')
    params = request.get('params', {})
    if method is None:
        assert request['id'] == 'approval' and 'error' in request
        continue
    if method == 'initialize':
        result = {}
    elif method == 'initialized':
        continue
    elif method in ('thread/start', 'thread/resume'):
        session = params.get('threadId', str(uuid.uuid4()))
        parameters = params
        native = Path(os.environ['MANAGED_NATIVE_ROOT']) / ('rollout-' + session + '.jsonl')
        native.parent.mkdir(exist_ok=True)
        if not native.exists():
            native.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': session}}) + '\n')
        result = {'thread': {'id': session, 'path': str(native)}}
    elif method == 'turn/start':
        execution = str(uuid.uuid4())
        with native.open('a') as stream:
            stream.write(json.dumps({'type': 'turn_context', 'payload': {
                'execution_id': execution, 'model': parameters['model'],
                'effort': parameters['config']['model_reasoning_effort'],
                'ticket_id': os.environ['GRAPHTRAJ_TICKET_ID'],
                'role': os.environ['GRAPHTRAJ_ROLE'], 'cwd': parameters['cwd'],
            }}) + '\n')
        result = {'turn': {'id': execution, 'status': 'inProgress', 'items': []}}
    elif method == 'turn/steer':
        assert params['threadId'] == session and params['expectedTurnId'] == execution
        text = params['input'][0]['text']
        if text == 'unhandled request':
            emit({'id': 'approval', 'method': 'item/commandExecution/requestApproval',
                  'params': {'threadId': session, 'turnId': execution}})
            emit({'id': request['id'], 'result': {'turnId': execution}})
            continue

        emit({'method': 'turn/completed', 'params': {
            'threadId': session, 'turn': {'id': execution, 'status': 'failed' if text == 'fail execution' else 'completed',
                'error': {'message': 'controlled model failure'},
                'items': [{'type': 'agentMessage', 'text': text}]},
        }})
        with native.open('a') as stream:
            stream.write(json.dumps({'type': 'event_msg', 'payload': {
                'type': 'task_complete', 'last_agent_message': text,
            }}) + '\n')
        result = {'turnId': execution}
    elif method == 'turn/interrupt':
        assert params == {'threadId': session, 'turnId': execution}
        emit({'method': 'turn/completed', 'params': {
            'threadId': session, 'turn': {'id': execution, 'status': 'interrupted', 'items': []},
        }})
        result = {}
    else:
        raise AssertionError(request)
    emit({'id': request['id'], 'result': result})

time.sleep(1)
Path(os.environ['MANAGED_NATIVE_ROOT'], session + '.closed').touch()
