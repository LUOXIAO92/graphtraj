"""Controlled external stdio peer for public Codex Adapter behavior checks."""

import json
import os
import signal
import sys
import time
from types import FrameType


def emit(message: dict) -> None:
    """Write one native protocol message."""
    print(json.dumps(message), flush=True)


def complete(thread_id: str, turn_id: str, text: str, status: str = 'completed') -> None:
    """Deliver final output before the control reply to exercise interleaving."""
    emit({'method': 'item/completed', 'params': {
        'threadId': thread_id, 'turnId': turn_id,
        'item': {'id': 'answer', 'type': 'agentMessage', 'text': text},
    }})
    emit({'method': 'turn/completed', 'params': {
        'threadId': thread_id,
        'turn': {'id': turn_id, 'status': status, 'items': [], 'error': None},
    }})


if sys.argv[1:] == ['exec', '--help']:
    print('--sandbox')
    raise SystemExit(0)

initialized = False
sessions = {}
active = {}
requests = {}
exchange = json.loads(os.environ.get('PEER_REQUEST_EXCHANGE', 'null'))
held_reply = None
sequence = 0
if os.environ.get('PEER_STALL_CLOSE'):
    def acknowledge_close(signum: int, frame: FrameType | None) -> None:
        """Make the external service's exit observable through its diagnostics."""
        print('close acknowledged', file=sys.stderr, flush=True)
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, acknowledge_close)
for line in sys.stdin:
    message = json.loads(line)
    method = message.get('method')
    params = message.get('params', {})
    if method is None:
        thread_id, turn_id = requests.pop(message['id'])
        if 'error' in message:
            assert message['error']['code'] in (-32601, -32603)
            if not os.environ.get('PEER_CONTINUE_AFTER_REJECTION'):
                complete(thread_id, turn_id, 'request rejected')
            continue
        assert message['result'] == (exchange['response'] if exchange else {'decision': 'accept'})
        complete(thread_id, turn_id, 'request accepted')
        continue
    if method == 'initialize':
        if os.environ.get('PEER_INITIALIZE_FAIL'):
            print('invalid native configuration', file=sys.stderr, flush=True)
            raise SystemExit(1)
        assert message['params']['clientInfo']['name']
        result = {'userAgent': 'controlled-codex'}
    elif method == 'initialized':
        initialized = True
        continue
    elif method in {'thread/start', 'thread/resume'}:
        assert initialized
        thread_id = params.get('threadId', f'thread-{len(sessions) + 1}')
        sessions[thread_id] = params
        result = {'thread': {'id': thread_id, 'path': '/native/' + thread_id + '.jsonl', 'turns': []},
                  'model': params['model'], 'cwd': params['cwd']}
        emit({'method': 'thread/started', 'params': {'thread': result['thread']}})
    elif method == 'turn/start':
        sequence += 1
        thread_id = params['threadId']
        turn_id = f'turn-{sequence}'
        result = {'turn': {'id': turn_id, 'status': 'inProgress', 'items': [], 'error': None}}
        active[thread_id] = turn_id
        prompt = params['input'][0]['text']
        if prompt == 'rpc-error':
            emit({'id': message['id'], 'error': {
                'code': -32001, 'message': 'native rejection', 'data': {'retry': False},
            }})
            continue
        if prompt == 'bad-json':
            print('not json', flush=True)
            continue
        if prompt == 'bad-shape':
            emit({'id': message['id'], 'result': []})
            continue
        if prompt == 'closed':
            raise SystemExit(0)
        if prompt == 'bad-turn':
            emit({'id': message['id'], 'result': {'turn': {'status': 'inProgress'}}})
            continue
        if prompt == 'bad-final-text':
            emit({'id': message['id'], 'result': {'turn': {
                'id': turn_id, 'status': 'completed', 'items': [{'type': 'agentMessage', 'text': 123}],
            }}})
            continue
        if prompt == 'reply-then-malformed':
            print(json.dumps({'id': message['id'], 'result': result}) + '\nnot json', flush=True)
            continue
        if prompt in ('bad-completion', 'failed-turn'):
            emit({'method': 'turn/completed', 'params': {
                'threadId': thread_id, 'turn': {'id': turn_id, 'items': [],
                    'status': 'unknown' if prompt == 'bad-completion' else 'failed',
                    'error': {'message': 'native execution failed', 'additionalDetails': 'bounded test'}},
            }})
            emit({'id': message['id'], 'result': result})
            continue
        if prompt == 'configured-request':
            request_id = 'native-request-1'
            requests[request_id] = (thread_id, turn_id)
            emit({'id': request_id, 'method': exchange['method'], 'params': exchange['params']})
        elif prompt.startswith('request:'):
            # Native server and client request IDs have separate namespaces.
            request_id = message['id']
            requests[request_id] = (thread_id, turn_id)
            emit({'id': request_id, 'method': prompt.removeprefix('request:'),
                  'params': {'threadId': thread_id, 'turnId': turn_id, 'itemId': 'command',
                             'startedAtMs': 1000, 'command': 'printf approved'}})
        elif prompt == 'large-output':
            complete(thread_id, turn_id, 'x' * 100_000)
        elif prompt == 'configuration':
            complete(thread_id, turn_id, json.dumps(sessions[thread_id]))
        elif prompt != 'hold':
            complete(thread_id, turn_id, prompt)
        if prompt == 'reverse-first':
            held_reply = {'id': message['id'], 'result': result}
            continue
        if prompt == 'reverse-second':
            emit({'id': message['id'], 'result': result})
            emit(held_reply)
            continue
    elif method == 'turn/steer':
        assert params['expectedTurnId'] == active[params['threadId']]
        result = {'turnId': params['expectedTurnId']}
        complete(params['threadId'], params['expectedTurnId'], params['input'][0]['text'])
    elif method == 'turn/interrupt':
        assert params['turnId'] == active[params['threadId']]
        result = {}
        for request_id, target in list(requests.items()):
            if target == (params['threadId'], params['turnId']):
                requests.pop(request_id)
                emit({'method': 'serverRequest/resolved', 'params': {
                    'threadId': params['threadId'], 'requestId': request_id,
                }})
        complete(params['threadId'], params['turnId'], '', 'interrupted')
    else:
        raise AssertionError(message)
    emit({'id': message['id'], 'result': result})
    if method == 'thread/start' and os.environ.get('PEER_PAUSE_INPUT'):
        time.sleep(5)

if os.environ.get('PEER_STALL_CLOSE'):
    time.sleep(10)
