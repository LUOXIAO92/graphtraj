"""Native synchronous hook output; these checks do not claim a client screenshot."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

from agent_swarm.claude.display import display_response


def event(action: str, text: str, execution: str = 'execution') -> dict:
    """Supply the native PostToolUse shape for a successful agents exchange."""
    request = {'action': action, 'agent': 'agent-child'}
    if action == 'send':
        request['message'] = text
    return {'hook_event_name': 'PostToolUse', 'tool_name': 'mcp__agents__agents',
            'session_id': 'native-parent', 'tool_use_id': 'tool-' + action,
            'tool_input': request, 'tool_response': {'structuredContent': {
                'action': action, 'agent': 'agent-child', 'result': {
                    'last_result': None if action == 'send' else {'id': execution, 'last_message': text}}}}}


def test_bidirectional_readable_content_is_only_native_display_output() -> None:
    """Tool facts stay unchanged and framing is never returned as model context."""
    seen = set()
    sent, received = event('send', 'Please check the file.'), event('wait', 'The file is valid.')
    originals = deepcopy([sent, received])
    outgoing, incoming = display_response(sent, seen), display_response(received, seen)
    assert set(outgoing) == set(incoming) == {'systemMessage'}
    assert 'native-parent → agent-child' in outgoing['systemMessage']
    assert 'Please check the file.' in outgoing['systemMessage']
    assert 'agent-child → native-parent' in incoming['systemMessage']
    assert 'The file is valid.' in incoming['systemMessage']
    assert [sent, received] == originals
    assert display_response(sent, seen) == display_response(received, seen) == {}
    assert display_response(event('wait', 'The file is valid.', 'another-execution'), seen)


def test_noop_resume_does_not_claim_to_have_sent_text() -> None:
    """An already-active resume is a status response, not a new delivery."""
    request = event('send', 'not sent')
    request['tool_input']['action'] = 'resume'
    request['tool_response']['structuredContent']['result']['resumed'] = False
    assert display_response(request) == {}


def test_command_hook_uses_the_same_native_output_and_bounds_display() -> None:
    """The installable command returns native hook JSON, never a CLI print UI."""
    original = event('wait', 'x' * 20000)
    environment = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
    result = subprocess.run([sys.executable, '-m', 'agent_swarm.claude.display'],
                            input=json.dumps(original), text=True, capture_output=True,
                            check=True, env=environment)
    display = json.loads(result.stdout)
    assert set(display) == {'systemMessage'}
    assert len(display['systemMessage']) < 10000
    assert len(original['tool_response']['structuredContent']['result']['last_result']['last_message']) == 20000
