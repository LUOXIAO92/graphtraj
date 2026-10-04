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
    active = False
    queued = []
    stop = threading.Event()
    dialog = threading.Event()

    def emit(document: dict) -> None:
        """Keep interleaved asynchronous events valid JSONL."""
        with output_lock:
            print(json.dumps(document), flush=True)

    def record(message: dict) -> None:
        """Append native message records as a real Session would."""
        with session_file.open('a') as stream:
            stream.write(json.dumps({'type': 'message', 'message': message}) + '\n')

    def finish(text: str) -> None:
        """Run asynchronously so steer/abort and ACK/settled races are observable."""
        nonlocal active
        if text == 'dialog':
            emit({'type': 'extension_ui_request', 'id': 'question', 'method': 'confirm', 'message': 'Continue?'})
            dialog.wait(5)
        if text.startswith('wait'):
            stop.wait(5)
        else:
            time.sleep(0.04)
        answer = '|'.join(str(x) for x in history + queued)
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
        record(message)
        emit({'type': 'message_end', 'message': message})
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
            dialog.set()
            continue
        emit(response)


if __name__ == '__main__':
    main()
