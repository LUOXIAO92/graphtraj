"""Controlled model work behind the existing Runner-launched native stdio peer.

This fixture never runs a real model. It writes only its own Runtime rollout;
the public Runner registers membership and retains the Trace itself.
"""

import json
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
from datetime import datetime, timezone
from uuid import uuid4


def records(turn: str, output: str) -> list[dict]:
    """Return explicit controlled Codex fields, with reasoning inside output."""
    tokens = {'input_tokens': 1000, 'cached_input_tokens': 600,
              'output_tokens': 80, 'reasoning_output_tokens': 20}
    return [
        {'type': 'turn_context', 'payload': {'model': 'gpt-5.3-codex', 'turn_id': turn}},
        {'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant',
         'content': [{'type': 'output_text', 'text': 'GraphTraj GUI controlled message'}]}},
        {'type': 'response_item', 'payload': {'type': 'function_call', 'call_id': 'controlled-echo',
         'name': 'exec', 'arguments': json.dumps({'cmd': 'echo controlled tool output'})}},
        {'type': 'response_item', 'payload': {'type': 'function_call_output',
         'call_id': 'controlled-echo', 'output': output}},
        {'type': 'event_msg', 'payload': {'type': 'token_count',
         'info': {'last_token_usage': tokens, 'total_token_usage': tokens}}},
    ]


def main() -> None:
    """Serve the fixture protocol or execute the deterministic assigned work."""
    if sys.argv[1:] == ['exec', '--help']:
        print('--config --json --sandbox')
        return
    if sys.argv[1:2] == ['app-server']:
        session = str(uuid4())
        # This is the existing peer's Runtime-owned path, not GraphTraj state.
        native = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
        os.environ['LINUX_ADOPTION_ROLLOUT'] = str(native / 'sessions/fake' / f'rollout-{session}.jsonl')
        runpy.run_path(str(Path(__file__).with_name('runner_codex_peer.py')),
                       init_globals={'scenario': __file__, 'session_name': session})
        return

    sys.stdin.read()
    native = Path(os.environ['LINUX_ADOPTION_ROLLOUT'])
    # The existing peer wrote this context from the Adapter's actual turn/start.
    context = json.loads(native.read_text().splitlines()[-1])['payload']
    output = subprocess.check_output(['/bin/echo', 'controlled tool output'], text=True).strip()
    with native.open('a') as stream:
        for record in records(context['execution_id'], output):
            stream.write(json.dumps({'timestamp': datetime.now(timezone.utc).isoformat(), **record}) + '\n')
    # A test-only socket holds model work active during GUI exit/crash checks.
    # It neither observes nor edits Runner state and uses no polling loop.
    with socket.socket(socket.AF_UNIX) as connection:
        connection.connect(os.environ['LINUX_ADOPTION_CONTROL'])
        connection.sendall(b'controlled records ready\n')
        assert connection.recv(32) == b'finish', 'Fixture release was not received'
    print(json.dumps({'type': 'item.completed', 'item': {
        'type': 'agent_message', 'text': 'Controlled Linux adoption work completed; no model call.'}}))


if __name__ == '__main__':
    main()
