"""Native stdio peer reusing deterministic Team decision scenarios as model work.

The scenario subprocess is test data, never a real Codex executable. Session
parameters come from the production Adapter wire; model completion and process
exit deliberately have separate messages.
"""

import json
import os
import signal
import subprocess
import sys
import threading
import uuid
from pathlib import Path


def emit(message: dict) -> None:
    """Write an indivisible native message from a scenario or the control reader."""
    with output_lock:
        print(json.dumps(message), flush=True)


def toml(value: object) -> str:
    """Render received native configuration for the existing decision scenarios."""
    if isinstance(value, dict):
        return '{' + ','.join(json.dumps(k) + '=' + toml(v) for k, v in value.items()) + '}'
    if isinstance(value, list):
        return '[' + ','.join(toml(v) for v in value) + ']'
    return json.dumps(value)


def finish(turn: str, prompt: str) -> None:
    """Execute only the test scenario, then report its native terminal result."""
    global process
    config = dict(parameters['config'], developer_instructions=parameters['developerInstructions'])
    argv = [sys.executable, scenario, 'exec', '-C', parameters['cwd'], '--model', parameters['model']]
    for key, value in config.items():
        argv.extend(['-c', key + '=' + toml(value)])
    argv.append('--json')
    if resumed:
        argv.extend(['resume', session])
    argv.append('-')
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               text=True, start_new_session=True)
    ready.set()
    try:
        process.stdin.write(prompt)
        process.stdin.close()
    except BrokenPipeError:
        pass  # An interrupt can arrive before the scenario consumes its input.
    answer = None
    for line in process.stdout:
        try:
            event = json.loads(line)
        except ValueError:
            print(line, file=sys.stderr, end='')
            continue
        item = event.get('item', {})
        if item.get('type') == 'agent_message':
            answer = item.get('text')
        if event.get('type') in ('error', 'turn.failed'):
            print(line, file=sys.stderr, end='')
    code = process.wait()
    emit({'method': 'turn/completed', 'params': {'threadId': session, 'turn': {
        'id': turn, 'status': 'interrupted' if interrupted else 'failed' if code else 'completed',
        'error': {'message': 'scenario failed'} if code and not interrupted else None,
        'items': [{'type': 'agentMessage', 'text': answer}] if answer else [],
    }}})


output_lock = threading.Lock()
ready = threading.Event()
process = None
interrupted = False
resumed = False
worker = None
session = session_name
configured = os.environ.get('FAKE_CODEX_EVENTS')
if configured:
    session = next((e['thread_id'] for e in json.loads(configured)
                    if e.get('type') == 'thread.started'), session)
for line in sys.stdin:
    request = json.loads(line)
    method = request['method']
    params = request.get('params', {})
    if method == 'initialize':
        result = {}
    elif method == 'initialized':
        continue
    elif method in ('thread/start', 'thread/resume'):
        if configured and not json.loads(configured):
            emit({'id': request['id'], 'error': {'code': -32000, 'message': 'controlled startup failure'}})
            continue
        parameters = params
        resumed = method == 'thread/resume'
        if resumed and params['threadId'] != session:
            emit({'id': request['id'], 'error': {'code': -32000, 'message': 'Session mismatch'}})
            continue
        native = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')) / 'sessions/fake' / ('rollout-' + session + '.jsonl')
        native.parent.mkdir(parents=True, exist_ok=True)
        if not native.exists():
            native.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': session}}) + '\n')
        result = {'thread': {'id': session, 'path': str(native)}}
    elif method == 'turn/start':
        turn = str(uuid.uuid4())
        with native.open('a') as stream:
            stream.write(json.dumps({'type': 'turn_context', 'payload': {
                'session_id': session, 'execution_id': turn, 'cwd': parameters['cwd'],
            }}) + '\n')
        result = {'turn': {'id': turn, 'status': 'inProgress', 'items': []}}
        worker = threading.Thread(target=finish, args=(turn, params['input'][0]['text']))
        worker.start()
    elif method == 'turn/steer':
        assert params['threadId'] == session and params['expectedTurnId'] == turn
        result = {'turnId': turn}
    elif method == 'turn/interrupt':
        assert params['threadId'] == session and params['turnId'] == turn
        ready.wait(5)
        interrupted = True
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        result = {}
    else:
        raise AssertionError(request)
    emit({'id': request['id'], 'result': result})
if worker:
    worker.join()
