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


pending = {}


def ask(kind: str = 'approval') -> None:
    """Reuse native IDs deliberately to exercise caller identity and expiry."""
    request_id = 'approval' if kind in {'approval', 'permissions'} else 7
    if 'MANAGED_APPROVAL_REQUEST_ID' in os.environ and kind == 'approval':
        request_id = json.loads(os.environ['MANAGED_APPROVAL_REQUEST_ID'])
    pending[request_id] = kind
    emit({'id': request_id, 'method': (
        'item/commandExecution/requestApproval' if kind == 'approval'
        else 'item/permissions/requestApproval' if kind == 'permissions'
        else 'item/tool/requestUserInput'
    ), 'params': {
        'threadId': session, 'turnId': execution,
        **({'availableDecisions': json.loads(os.environ['MANAGED_APPROVAL_DECISIONS'])}
           if kind == 'approval' and 'MANAGED_APPROVAL_DECISIONS' in os.environ else {}),
        **({'command': 'printf APPROVAL_121', 'cwd': parameters['cwd']}
           if kind == 'approval' else {'permissions': {'network': {'enabled': True}}}
           if kind == 'permissions' else {'questions': [{'id': 'color', 'question': 'Choose a color.'}]}),
    }})


if sys.argv[1:] == ['exec', '--help']:
    print('--sandbox')
    sys.exit(0)
assert sys.argv[1:] == ['app-server', '--listen', 'stdio://'], sys.argv
for line in sys.stdin:
    request = json.loads(line)
    method = request.get('method')
    params = request.get('params', {})
    if method is None:
        kind = pending.pop(request['id'])
        with native.with_suffix('.replies.jsonl').open('a') as stream:
            stream.write(json.dumps(request) + '\n')
        if 'error' in request:
            continue
        if kind == 'approval':
            decision = request['result']['decision']
            assert decision in ('accept', 'decline', 'cancel')
            text = 'approval:' + decision
        else:
            text = json.dumps(request['result'], sort_keys=True)
        if pending:
            continue
        with native.open('a') as stream:
            stream.write(json.dumps({'type': 'event_msg', 'payload': {
                'type': 'task_complete', 'last_agent_message': text,
            }}) + '\n')
        emit({'method': 'turn/completed', 'params': {
            'threadId': session, 'turn': {'id': execution, 'status': (
                'interrupted' if kind == 'approval' and decision == 'cancel' else 'completed'),
                'items': [{'type': 'agentMessage', 'text': text}]},
        }})
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
            ask()
            emit({'id': request['id'], 'result': {'turnId': execution}})
            continue
        if text == 'withdraw and reissue':
            for request_id in list(pending):
                emit({'method': 'serverRequest/resolved', 'params': {'requestId': request_id}})
            pending.clear()
            ask()
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
        for request_id in list(pending):
            emit({'method': 'serverRequest/resolved', 'params': {'requestId': request_id}})
        pending.clear()
        emit({'method': 'turn/completed', 'params': {
            'threadId': session, 'turn': {'id': execution, 'status': 'interrupted', 'items': []},
        }})
        result = {}
    else:
        raise AssertionError(request)
    emit({'id': request['id'], 'result': result})
    if method == 'turn/start' and 'request:' in params['input'][0]['text']:
        prompt = params['input'][0]['text']
        if 'large-history' in prompt:
            with native.open('a') as stream:
                stream.write(json.dumps({'type': 'response_item', 'payload': {
                    'type': 'message', 'role': 'user', 'content': 'x' * 200001,
                }}) + '\n')
        if 'compacted-context' in prompt:
            records = [
                {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                    'content': [{'type': 'input_text', 'text': 'Do not delete protected.txt.'}]}},
                {'type': 'response_item', 'payload': {'type': 'function_call_output',
                    'call_id': 'old-tool', 'output': 'obsolete file listing'}},
                {'type': 'retained_context', 'payload': {'type': 'verified_answer',
                    'turn_id': execution, 'call_id': 'prior-question',
                    'questions': [{'question': 'May protected.txt change?', 'answer': 'No.'}]}},
                {'type': 'compacted', 'payload': {
                    'message': 'Native summary: only update scratch.txt.',
                    'replacement_history': [
                        {'type': 'message', 'role': 'assistant', 'content': [
                            {'type': 'output_text', 'text': 'Native current task summary.'}]},
                        {'type': 'reasoning', 'encrypted_content': 'not-visible-context'},
                    ],
                    'retained_context': {
                        'verified_answers': [], 'incomplete': False,
                        'user_messages': [{'order': 0, 'turn_id': execution, 'message_id': None,
                            'text': 'Do not delete protected.txt.', 'complete': True}],
                        'user_messages_incomplete': False, 'next_order': 1,
                    },
                }},
                {'type': 'retained_context', 'payload': {'type': 'verified_answer',
                    'turn_id': execution, 'call_id': 'question-1', 'acceptance_order': 2,
                    'questions': [{'question': 'Which file?', 'answer': 'Only scratch.txt.'}]}},
                {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                    'content': [{'type': 'input_text', 'text': 'Keep the protected file unchanged.'}]}},
            ]
            with native.open('a') as stream:
                for record in records:
                    stream.write(json.dumps(record) + '\n')
        if 'invalid-history' in prompt:
            with native.open('a') as stream:
                stream.write('invalid JSON\n')
        ask('permissions' if 'request:permissions' in prompt else 'approval')
        if 'request:multiple' in params['input'][0]['text']:
            ask('input')

time.sleep(1)
Path(os.environ['MANAGED_NATIVE_ROOT'], session + '.closed').touch()
