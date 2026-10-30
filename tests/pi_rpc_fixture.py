"""Controlled Pi RPC peer; never claims real model or filesystem isolation."""

import json
import os
import stat
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid


def main() -> None:
    """Serve documented Pi commands over real pipes with retained native history."""
    if '--version' in sys.argv:
        print('1.0.0-fixture')
        return
    if '--no-session' in sys.argv:
        # Controlled public metadata boundary; actual Pi catalog evidence lives
        # in the opt-in Runtime connection tests and does not use this peer.
        provider = sys.argv[sys.argv.index('--provider') + 1]
        model = sys.argv[sys.argv.index('--model') + 1]
        domain = {'deepseek': 'api.deepseek.com', 'openrouter': 'openrouter.ai',
                  'openai': 'api.openai.com'}.get(provider, 'custom.invalid')
        for line in sys.stdin:
            request = json.loads(line)
            assert request['type'] == 'get_available_models'
            print(json.dumps({'id': request['id'], 'success': True, 'data': {'models': [{
                'provider': provider, 'id': model, 'baseUrl': 'https://' + domain,
            }]}}), flush=True)
        return
    if os.environ.get('PI_FIXTURE_PIPE_STDERR') and not stat.S_ISFIFO(os.fstat(2).st_mode):
        print('fixture refuses private regular-file stderr', file=sys.stderr)
        raise SystemExit(71)
    if os.environ.get('PI_FIXTURE_STARTUP_FAILURE'):
        print('PermissionError: fixture startup resource denied; Bearer fixture-token', file=sys.stderr)
        print(os.environ.get('DEEPSEEK_API_KEY', ''), file=sys.stderr)
        raise SystemExit(71)
    session_file = Path(sys.argv[sys.argv.index('--session') + 1])
    provider = sys.argv[sys.argv.index('--provider') + 1]
    model = sys.argv[sys.argv.index('--model') + 1]
    records = [json.loads(line) for line in session_file.read_text().splitlines()] if session_file.exists() else []
    session = records[0]['id'] if records else str(uuid.uuid4())
    history = [x.get('message', {}).get('content', '') for x in records[1:]]
    if not records and not os.environ.get('PI_FIXTURE_UNESTABLISHED'):
        session_file.write_text(json.dumps({'type': 'session', 'id': session, 'version': 3}) + '\n')
    output_lock = threading.Lock()
    entries_lock = threading.Lock()
    entries = records[1:]
    traffic = {'bytes': 0, 'records': 0}
    active = False
    queued = []
    stop = threading.Event()
    dialog = threading.Event()
    answers: list[dict] = []
    if os.environ.get('PI_FIXTURE_KEY_PROBE'):
        # Which named variables reached this process, never their values.
        target, _, names = os.environ['PI_FIXTURE_KEY_PROBE'].partition(':')
        Path(target).write_text(json.dumps({name: name in os.environ for name in names.split(',')}))

    def log_kind(kind: str) -> None:
        """Keep the order of received commands for tests that require one first."""
        if os.environ.get('PI_FIXTURE_COMMANDS'):
            with open(os.environ['PI_FIXTURE_COMMANDS'], 'a') as stream:
                stream.write(kind + '\n')

    def emit(document: dict) -> None:
        """Keep interleaved asynchronous events valid JSONL."""
        with output_lock:
            encoded = json.dumps(document)
            traffic['bytes'] += len(encoded.encode()) + 1
            traffic['records'] += 1
            print(encoded, flush=True)

    def record(message: dict) -> None:
        """Append native message records as a real Session would."""
        with entries_lock:
            entry = {'type': 'message', 'id': uuid.uuid4().hex,
                     'parentId': entries[-1]['id'] if entries else None, 'message': message}
            with session_file.open('a') as stream:
                stream.write(json.dumps(entry) + '\n')
            entries.append(entry)

    def streamed(text: str) -> dict:
        """Send equal semantic content with controlled real stdout fragmentation."""
        size = int(os.environ.get('PI_FIXTURE_CHUNK', '512'))
        answer = 'hello世界 ' * 1024
        message = {'role': 'assistant', 'content': [], 'provider': provider, 'model': model,
                   'api': 'fixture', 'timestamp': 1791936000000, 'stopReason': 'stop',
                   'usage': {'input': 17, 'output': 4096, 'cacheRead': 3, 'cacheWrite': 0}}
        emit({'type': 'message_start', 'message': message})
        for index, (kind, body) in enumerate([('thinking', 'private summary'), ('text', answer),
                                             ('toolcall', '{"path":"/tmp/result"}')]):
            block = ({'type': 'thinking', 'thinking': '', 'thinkingSignature': 'cipher:sig'} if kind == 'thinking'
                     else {'type': 'text', 'text': ''} if kind == 'text'
                     else {'type': 'toolCall', 'id': 'call-1', 'name': 'read', 'arguments': {}})
            message['content'].append(block)
            emit({'type': 'message_update', 'message': message,
                  'assistantMessageEvent': {'type': kind + '_start', 'contentIndex': index, 'partial': message}})
            for start in range(0, len(body), size):
                delta = body[start:start + size]
                if kind != 'toolcall':
                    block['thinking' if kind == 'thinking' else 'text'] += delta
                update = {'type': kind + '_delta', 'contentIndex': index, 'delta': delta, 'partial': message}
                emit({'type': 'message_update', 'message': message, 'assistantMessageEvent': update})
            if kind == 'toolcall':
                block['arguments'] = json.loads(body)
            emit({'type': 'message_update', 'message': message, 'assistantMessageEvent': {
                'type': kind + '_end', 'contentIndex': index, 'partial': message,
                **({'toolCall': block} if kind == 'toolcall' else {'content': body}),
            }})
        emit({'type': 'fixture_probability', 'requestId': 'request-1', 'model': model,
              'tokenizer': 'fixture-tokenizer', 'logprobs': [{'position': 0, 'logprob': -0.25}]})
        emit({'type': 'fixture_opaque', 'ciphertext': 'cipher:payload', 'unknown': {'keep': True}})
        if text == 'stream-crash':
            (session_file.parent / 'traffic.json').write_text(json.dumps(traffic))
            os._exit(7)
        message['stopReason'] = {'stream-error': 'error', 'stream-abort': 'aborted'}.get(text, 'stop')
        if text == 'stream-error':
            message['errorMessage'] = 'fixture failed after partial output'
        return message

    def finish(text: str) -> None:
        """Run asynchronously so steer/abort and ACK/settled races are observable."""
        nonlocal active
        if text == 'dialog':
            emit({'type': 'extension_ui_request', 'id': 'question', 'method': 'confirm', 'message': 'Continue?'})
            dialog.wait(5)
        reviewed = None
        if text.startswith(('review:', 'unreserved:')):
            # What the real tool_call handler does (extension.mjs): the call waits on
            # one dialog, and only a confirmed answer lets it run, once.
            kind, _, target = text.partition(':')
            dialog.clear()
            answers.clear()
            emit({'type': 'extension_ui_request', 'id': 'native-dialog-1', 'method': 'confirm',
                  'title': os.environ.get('AGENT_SWARM_PI_REVIEW', '') if kind == 'review' else 'Allow?',
                  'message': json.dumps({'tool': 'write', 'call_id': 'call-1', 'input': {'path': target}})})
            dialog.wait(30)
            reviewed = 'blocked'
            if answers and answers[0].get('confirmed') is True:
                with open(target, 'a') as stream:
                    stream.write('ran\n')
                reviewed = 'ran'
        if text.startswith('wait'):
            stop.wait(5)
        else:
            time.sleep(0.04)
        answer = reviewed or '|'.join(str(x) for x in history + queued)
        if text == 'cli':
            env = {**os.environ, 'GRAPHTRAJ_CALLER_ALIAS': 'research@x2', 'GRAPHTRAJ_ROLE': 'main'}
            # The restricted Session's own directory is its Worktree, never the
            # unreadable Harness Project Root.
            worktree = os.path.join(os.environ['PI_FIXTURE_ROOT'], 'worktrees', 'research')
            authorized = subprocess.run([sys.executable, '-c',
                                        'from graphtraj.interfaces.cli.agent_runner import main; main()',
                                        'submit-report', '--name', 'researcher-x1.md', '--text', 'Pi hosted evidence'],
                                       cwd=worktree, env=env,
                                       capture_output=True, text=True, timeout=15)
            child = subprocess.run([sys.executable, '-c',
                                    'from graphtraj.interfaces.cli.agent_runner import main; main()',
                                    'reports', 'research@x2'], cwd=worktree,
                                   env=env, capture_output=True, text=True, timeout=15)
            answer = json.dumps({'authorized_exit': authorized.returncode, 'authorized': authorized.stdout,
                                 'refused_exit': child.returncode, 'refused': child.stdout})
        message = {'role': 'assistant', 'content': [{'type': 'text', 'text': answer}],
                   'stopReason': 'error' if text == 'provider-error' else 'stop'}
        if text == 'provider-error':
            message['errorMessage'] = 'fixture provider rejected request'
        if text.startswith('stream-'):
            message = streamed(text)
        record(message)
        emit({'type': 'message_end', 'message': message})
        if text == 'stream-ok':
            emit({'type': 'tool_execution_start', 'toolCallId': 'call-1', 'toolName': 'read', 'args': {'path': '/tmp/result'}})
            tool = {'role': 'toolResult', 'toolCallId': 'call-1', 'toolName': 'read',
                    'content': [{'type': 'text', 'text': 'tool result'}], 'isError': False, 'timestamp': 1791936000001}
            record(tool)
            emit({'type': 'tool_execution_end', 'toolCallId': 'call-1', 'toolName': 'read', 'result': tool, 'isError': False})
            emit({'type': 'message_start', 'message': tool})
            emit({'type': 'message_end', 'message': tool})
        queued.clear()
        active = False
        if text == 'settled-race':
            # Delay delivery of the prior settlement until the next command;
            # native steer queues even when no run remains to consume it.
            (session_file.parent / 'idle-marker').touch()
            return
        emit({'type': 'agent_settled'})

    emit({'type': 'extension_ui_request', 'id': 'status', 'method': 'setStatus', 'statusText': 'sandboxed'})
    for line in sys.stdin:
        request = json.loads(line)
        kind = request['type']
        log_kind(kind)
        response = {'type': 'response', 'id': request.get('id'), 'command': kind, 'success': True}
        if kind == 'get_state':
            response['data'] = {'sessionId': session, 'sessionFile': str(session_file),
                                'model': {'provider': provider, 'id': model},
                                'isStreaming': active, 'isCompacting': False,
                                'pendingMessageCount': len(queued)}
            if os.environ.get('PI_FIXTURE_UNESTABLISHED'):
                response['data']['sessionId'] = None
                if os.environ.get('PI_FIXTURE_STARTUP_READY') and not stop.is_set():
                    Path(os.environ['PI_FIXTURE_STARTUP_READY']).touch()

                    def delayed_state(reply: dict = response) -> None:
                        """Keep servicing native abort while Session creation waits."""
                        stop.wait(10)
                        emit(reply)

                    threading.Thread(target=delayed_state, daemon=True).start()
                    continue
        elif kind == 'get_entries':
            with entries_lock:
                response['data'] = {'entries': list(entries),
                                    'leafId': entries[-1]['id'] if entries else None}
        elif kind == 'prompt':
            if active and request.get('streamingBehavior') == 'steer':
                queued.append(request['message'])
                if request['message'] == 'finish':
                    stop.set()
                response['data'] = {'disposition': 'queued'}
                emit(response)
                continue
            stop.clear()
            active = True
            text = request['message']
            history.append(text)
            record({'role': 'user', 'content': text})
            response['data'] = {'disposition': 'started'}
            emit(response)
            threading.Thread(target=finish, args=(text,), daemon=True).start()
            continue
        elif kind == 'steer':
            queued.append(request['message'])
            if not active:
                emit({'type': 'agent_settled'})
            if request['message'] == 'finish':
                stop.set()
            response['data'] = {'disposition': 'queued'}
        elif kind == 'clear_queue':
            response['data'] = {'steering': list(queued), 'followUp': []}
            queued.clear()
        elif kind == 'abort':
            # Deliberately acknowledge before settlement to catch ACK-only stops.
            emit(response)
            time.sleep(0.08)
            stop.set()
            dialog.set()
            continue
        elif kind == 'extension_ui_response':
            answers.append(request)
            dialog.set()
            continue
        elif kind == 'get_commands':
            hook = (os.environ.get('AGENT_SWARM_PI_REVIEW') and '--extension' in sys.argv
                    and not os.environ.get('PI_FIXTURE_NO_REVIEW_HOOK'))
            response['data'] = {'commands': [{
                'name': 'agents-review-hook', 'source': 'extension',
                'sourceInfo': {'path': sys.argv[sys.argv.index('--extension') + 1]},
            }] if hook else []}
        emit(response)
    (session_file.parent / 'traffic.json').write_text(json.dumps(traffic))


if __name__ == '__main__':
    main()
