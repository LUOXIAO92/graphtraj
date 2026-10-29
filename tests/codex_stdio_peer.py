"""Controlled external stdio peer for public Codex Adapter behavior checks."""

import json
import os
import signal
import subprocess
import threading
import sys
import time
from pathlib import Path
from types import FrameType
from websockets.server import ServerProtocol
from websockets.http11 import Request
from websockets.frames import Frame, Opcode


socket = ServerProtocol() if sys.argv[1:3] == ['app-server', 'proxy'] else None


def flush_socket() -> None:
    """Write native proxy transport output without replacing JSON-RPC semantics."""
    for data in socket.data_to_send():
        if data:
            sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def incoming():
    """Serve the owning proxy's real WebSocket framing or ordinary stdio."""
    if socket is None:
        yield from sys.stdin
        return
    while data := sys.stdin.buffer.read1(65536):
        socket.receive_data(data)
        for event in socket.events_received():
            if isinstance(event, Request):
                socket.send_response(socket.accept(event))
            elif isinstance(event, Frame) and event.opcode is Opcode.TEXT:
                yield event.data.decode()
        flush_socket()


def emit(message: dict) -> None:
    """Write one native protocol message."""
    if socket is None:
        print(json.dumps(message), flush=True)
    else:
        socket.send_text(json.dumps(message).encode())
        flush_socket()


def record(message: dict) -> None:
    """Retain received client wire messages when a controlled test requests it."""
    path = os.environ.get('PEER_PROTOCOL_LOG')
    if path:
        with Path(path).open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(message) + '\n')


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


def native_rollout(thread_id: str) -> Path | None:
    """Return the controlled native rollout only for the trace retention check."""
    root = os.environ.get('PEER_NATIVE_ROLLOUT')
    return Path(root) / ('rollout-' + thread_id + '.jsonl') if root else None


def write_native_prefix(rollout: Path) -> None:
    """Create delayed complete records and one incomplete native trailing record."""
    if rollout.exists():
        return
    time.sleep(0.05)
    rollout.parent.mkdir(parents=True, exist_ok=True)
    trailing = json.dumps({
        'timestamp': 'native-3', 'type': 'turn_context', 'payload': {'cwd': 'kept'},
    }, separators=(',', ':'))
    records = [
        json.dumps({
            'timestamp': 'native-1', 'type': 'session_meta',
            'payload': {'id': 'thread-1', 'base_instructions': {'text': 'original'}},
        }, separators=(',', ':')),
        json.dumps({
            'timestamp': 'native-2', 'type': 'response_item',
            'payload': {'type': 'reasoning', 'encrypted_content': 'opaque'},
        }, separators=(',', ':')),
        json.dumps({
            'timestamp': 'native-call', 'type': 'response_item',
            'payload': {'type': 'custom_tool_call', 'call_id': 'native-call'},
        }, separators=(',', ':')),
    ]
    split = len(trailing) // 2
    with rollout.open('wb') as stream:
        stream.write(('\n'.join(records) + '\n' + trailing[:split]).encode())
        stream.flush()
        os.fsync(stream.fileno())
    time.sleep(0.1)
    with rollout.open('ab') as stream:
        stream.write((trailing[split:] + '\n').encode())
        stream.flush()
        os.fsync(stream.fileno())


def write_native_result(rollout: Path, text: str) -> None:
    """Append the native terminal record after its control notification."""
    timestamp = (
        'native-4'
        if not rollout.read_bytes().count(b'"type":"task_complete"')
        else 'native-5'
    )
    with rollout.open('ab') as stream:
        stream.write((json.dumps({
            'timestamp': timestamp, 'type': 'event_msg',
            'payload': {'type': 'task_complete', 'last_agent_message': text},
        }, separators=(',', ':')) + '\n').encode())
        stream.flush()
        os.fsync(stream.fileno())


if sys.argv[1:] == ['exec', '--help']:
    print('--sandbox')
    raise SystemExit(0)

initialized = False
sessions = {}
parent_reads = {}
active = {}
requests = {}
exchanges = iter(json.loads(os.environ.get('PEER_REQUEST_EXCHANGES', '[]')))
exchange = next(exchanges, json.loads(os.environ.get('PEER_REQUEST_EXCHANGE', 'null')))
held_reply = None
sequence = 0
queued = 0
if os.environ.get('PEER_STALL_CLOSE'):
    def acknowledge_close(signum: int, frame: FrameType | None) -> None:
        """Make the external service's exit observable through its diagnostics."""
        print('close acknowledged', file=sys.stderr, flush=True)
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, acknowledge_close)
for line in incoming():
    message = json.loads(line)
    record(message)
    method = message.get('method')
    params = message.get('params', {})
    if method is None:
        thread_id, turn_id = requests.pop(message['id'])
        if 'error' in message:
            assert message['error']['code'] in (-32601, -32603)
            if not os.environ.get('PEER_CONTINUE_AFTER_REJECTION'):
                complete(thread_id, turn_id, 'request rejected')
            continue
        if exchange and 'response_success' in exchange:
            assert message['result']['success'] is exchange['response_success']
        else:
            assert message['result'] == (exchange['response'] if exchange else {'decision': 'accept'})
        following = next(exchanges, None)
        if following is not None:
            exchange = following
            request_id = message['id'] + '-next'
            requests[request_id] = (thread_id, turn_id)
            emit({'id': request_id, 'method': exchange['method'], 'params': exchange['params']})
        else:
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
        if os.environ.get('PEER_PAUSE_BEFORE_SESSION'):
            while True:
                time.sleep(1)
        continue
    elif method == 'config/read':
        result = {'config': json.loads(os.environ.get('PEER_CONFIG', '{}')),
                  'origins': {}, 'layers': None}
    elif method in {'thread/start', 'thread/resume'}:
        assert initialized
        if os.environ.get('PEER_SESSION_DELAY'):
            emit({'method': 'thread/loading', 'params': {}})
            time.sleep(float(os.environ['PEER_SESSION_DELAY']))
        if os.environ.get('PEER_SESSION_FAILURE'):
            emit({'id': message['id'], 'error': {'code': -32000, 'message': 'Session loading failed'}})
            continue
        thread_id = params.get('threadId', f'thread-{len(sessions) + 1}')
        sessions[thread_id] = params
        rollout = native_rollout(thread_id)
        if method == 'thread/resume' and rollout and os.environ.get('PEER_RESUME_SETTINGS'):
            with rollout.open('a') as stream:
                stream.write(json.dumps({'type': 'event_msg', 'payload': {
                    'type': 'thread_settings_applied', 'thread_id': thread_id,
                    'thread_settings': {'model': params.get('model')},
                }}) + '\n')
        result = {
            'thread': {
                'id': thread_id,
                'path': str(rollout) if rollout else '/native/' + thread_id + '.jsonl',
                'turns': [],
            },
            'model': params.get('model', 'runtime-default'),
            'cwd': params['cwd'],
        }
        emit({'method': 'thread/started', 'params': {'thread': result['thread']}})
    elif method == 'thread/fork':
        thread_id = f'thread-{len(sessions) + 1}'
        sessions[thread_id] = params
        result = {'thread': {'id': thread_id, 'path': None, 'ephemeral': True,
                            'forkedFromId': params['threadId'], 'createdAt': 17,
                            'historyMode': 'paginated'},
                  'model': params['model'], 'modelProvider': params['modelProvider']}
        # A test may report native fork facts and read the request it got.
        result.update(json.loads(os.environ.get('PEER_FORK_RESULT', '{}')))
        if os.environ.get('PEER_FORK_PARAMS'):
            Path(os.environ['PEER_FORK_PARAMS']).write_text(json.dumps(params))
    elif method == 'thread/items/list':
        assert params['sortDirection'] == 'asc'
        pages = json.loads(Path(os.environ['PEER_HISTORY_PAGES']).read_text())
        if isinstance(pages, dict):
            emit({'id': message['id'], 'error': pages})
            continue
        index = int(params.get('cursor', '0'))
        result = {'data': pages[index], 'nextCursor': str(index + 1) if index + 1 < len(pages) else None}
    elif method == 'thread/read':
        assert initialized
        assert params['includeTurns'] is False
        thread_id = params['threadId']
        if thread_id in os.environ.get('PEER_MAIN_THREADS', '').split(','):
            emit({'id': message['id'], 'result': {'thread': {
                'id': thread_id, 'sessionId': thread_id + '-hook', 'source': 'appServer',
                'parentThreadId': None, 'model': 'controlled-main', 'modelProvider': 'controlled',
            }}})
            continue
        parents = json.loads(os.environ['PEER_THREAD_PARENTS'])
        parent = parents[thread_id]
        if isinstance(parent, list):
            index = parent_reads.get(thread_id, 0)
            parent_reads[thread_id] = index + 1
            parent = parent[index]
        result = {'thread': {'id': thread_id, 'parentThreadId': parent, 'turns': []}}
    elif method == 'thread/queue/add':
        assert initialized
        assert message['params']['threadId']
        assert message['params']['clientUserMessageId']
        assert len(message['params']['input']) == 2
        if os.environ.get('PEER_REJECT_QUEUE'):
            emit({'id': message['id'], 'error': {
                'code': -32001, 'message': 'queue rejected',
            }})
            continue
        if os.environ.get('PEER_PAUSE_QUEUE'):
            time.sleep(float(os.environ['PEER_PAUSE_QUEUE']))
        queued += 1
        result = {'queuedSubmission': {'id': f'queued-{queued}'}}
    elif method == 'turn/start' and os.environ.get('PEER_SILENT_TURN_START'):
        # Alive, but never replies to this submission.
        Path(os.environ['PEER_SILENT_TURN_START']).write_text(str(os.getpid()))
        continue
    elif method == 'turn/start' and 'toolOutput' in params and os.environ.get('PEER_DROP_HOST_REPLY'):
        # A child body was submitted to this native host, but its acknowledgement
        # is unavailable. The client must not present it again through status.
        raise SystemExit(0)
    elif method == 'turn/start':
        sequence += 1
        thread_id = params['threadId']
        turn_id = f'turn-{sequence}'
        result = {'turn': {'id': turn_id, 'status': 'inProgress', 'items': [], 'error': None}}
        active[thread_id] = turn_id
        if 'toolOutput' in params:
            assert params['input'] == []
            assert params['toolOutput']['name'] == 'graphtraj'
            prompt = params['toolOutput']['output']
            assert json.loads(prompt)['source'] == 'graphtraj'
        else:
            prompt = params['input'][0]['text']
        if (
            os.environ.get('PEER_REJECT_RETRO')
            and len(params['input']) == 2
            and params['input'][1].get('type') == 'skill'
            and params['input'][1].get('name') == 'retro'
        ):
            emit({'id': message['id'], 'error': {
                'code': -32001, 'message': 'retro rejected',
            }})
            continue
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
        elif prompt == 'mcp-create-child':
            def create_child(thread_id=thread_id):
                """Issue one genuine bound MCP call from the controlled native host."""
                server = sessions[thread_id]['config']['mcp_servers']['graphtraj']
                environment = {key: value for key, value in os.environ.items()
                               if key not in {'AGENT_SWARM_CONNECTION', 'GRAPHTRAJ_CLI_CONNECTION'}}
                environment.update(server['env'])
                request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
                    'name': 'agents', '_meta': {'threadId': thread_id},
                    'arguments': {'action': 'execute', 'feature': 'create', 'arguments': {
                        'runtime': 'codex', 'instruction': 'child body',
                    }},
                }}
                subprocess.run([server['command'], *server['args']], cwd=server['cwd'],
                               env=environment, text=True, capture_output=True, timeout=10,
                               input=json.dumps(request) + '\n', check=True)
            threading.Thread(target=create_child, daemon=True).start()
        elif prompt == 'mcp-requests':
            def run_mcp(thread_id=thread_id, turn_id=turn_id):
                """Keep the peer available for concurrent native identity reads."""
                server = sessions[thread_id]['config']['mcp_servers']['graphtraj']
                requests_to_send = json.loads(os.environ['PEER_MCP_REQUESTS'])
                for entry in requests_to_send:
                    if entry['method'] == 'tools/call':
                        entry['params']['_meta'] = {'threadId': os.environ.get('PEER_MCP_ISSUER', thread_id)}
                environment = {key: value for key, value in os.environ.items()
                               if key not in {'AGENT_SWARM_CONNECTION', 'GRAPHTRAJ_CLI_CONNECTION'}}
                environment.update(server['env'])
                response = subprocess.run([server['command'], *server['args']], cwd=server['cwd'],
                                          env=environment, text=True, capture_output=True, timeout=10,
                                          input=''.join(json.dumps(entry) + '\n' for entry in requests_to_send))
                assert response.returncode == 0, response.stderr
                complete(thread_id, turn_id, json.dumps([json.loads(line) for line in response.stdout.splitlines()]))
            threading.Thread(target=run_mcp, daemon=True).start()
        elif prompt == 'configuration':
            if os.environ.get('PEER_CONFIGURATION_HOME'):
                Path(os.environ['PEER_CONFIGURATION_HOME']).write_text(os.environ.get('CODEX_HOME', ''))
                rollout = native_rollout(thread_id)
                if rollout:
                    write_native_prefix(rollout)
                    write_native_result(rollout, 'configuration')
            complete(thread_id, turn_id, json.dumps(sessions[thread_id]))
        elif prompt != 'hold':
            rollout = native_rollout(thread_id)
            if rollout is not None:
                write_native_prefix(rollout)
            complete(thread_id, turn_id, prompt)
            if rollout is not None:
                write_native_result(rollout, prompt)
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
