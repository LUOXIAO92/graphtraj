"""Controlled official CLI peer: no model, sandbox or authentication is simulated as real."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


def emit(value: dict) -> None:
    """Send one native protocol record."""
    print(json.dumps(value), flush=True)


if '--version' in sys.argv:
    print('2.1.299 (Claude Code)')
    raise SystemExit
if os.environ.get('CLAUDE_FIXTURE_FAIL'):
    print('controlled startup failure', file=sys.stderr)
    raise SystemExit(17)
if os.environ.get('CLAUDE_FIXTURE_DIAGNOSTICS'):
    print('Warning: auto mode unavailable; token=sk-diagnosticsecret; email=private@example.invalid', file=sys.stderr)
args = sys.argv
session = args[args.index('--resume' if '--resume' in args else '--session-id') + 1]
model = args[args.index('--model') + 1]
permission_mode = args[args.index('--permission-mode') + 1] if '--permission-mode' in args else None
Path(os.environ['CLAUDE_FIXTURE_HOME'], 'native-permissions.json').write_text(json.dumps({
    'mode': permission_mode, 'settings': json.loads(args[args.index('--settings') + 1]),
    'restricted': '--restricted' in args,
    'permission_handler': args[args.index('--permission-prompt-tool') + 1],
}))
history = Path(os.environ['CLAUDE_FIXTURE_HOME']) / (session + '.json')
Path(os.environ['CLAUDE_FIXTURE_HOME'], 'native-selection.json').write_text(json.dumps({
    'model': model, 'effort': args[args.index('--effort') + 1] if '--effort' in args else None,
    'environment_effort': os.environ.get('CLAUDE_CODE_EFFORT_LEVEL'),
}))
messages = json.loads(history.read_text()) if history.exists() else []
Path(os.environ['CLAUDE_FIXTURE_HOME'], 'native-endpoint.json').write_text(
    json.dumps(os.environ.get('ANTHROPIC_BASE_URL')))
started = False
waiting = []


def result(text: str, error: bool = False) -> None:
    """Emit distinct result and quiescence records with native usage."""
    emit({'type': 'assistant', 'session_id': session, 'message': {
        'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}})
    emit({'type': 'result', 'session_id': session, 'uuid': str(uuid.uuid4()),
          'is_error': error, 'result': text, 'usage': {
              'input_tokens': 11, 'cache_read_input_tokens': 7,
              'cache_creation_input_tokens': 2, 'output_tokens': 5}})
    emit({'type': 'system', 'subtype': 'session_state_changed', 'state': 'idle'})



def tool(feature: str, arguments: dict) -> dict:
    """Call an actual public tool through the owned stdio MCP subprocess."""
    command = json.loads(args[args.index('--mcp-config') + 1])['mcpServers']['graphtraj']
    query = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
        'name': 'graphtraj', 'arguments': {'action': 'execute', 'feature': feature, 'arguments': arguments}}}
    response = subprocess.run([command['command'], *command['args']], input=json.dumps(query) + '\n',
                              text=True, capture_output=True, env={**os.environ, **command['env']})
    value = json.loads(response.stdout)['result']
    if value['isError']:
        raise RuntimeError(value)
    return value['structuredContent']


def prompt(message: dict) -> None:
    """Process fixture input only after Runner releases the startup hook."""
    text = message['message']['content']
    messages.append(text)
    history.write_text(json.dumps(messages))
    emit({'type': 'system', 'subtype': 'session_state_changed', 'state': 'running'})
    if text == 'permission':
        emit({'type': 'control_request', 'request_id': 'permission-1', 'request': {
            'subtype': 'can_use_tool', 'tool_name': 'Bash', 'input': {'command': 'echo approved'},
            'tool_use_id': 'tool-1'}})
    elif text == 'mcp':
        command = json.loads(args[args.index('--mcp-config') + 1])['mcpServers']['graphtraj']
        query = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
            'name': 'graphtraj', 'arguments': {'action': 'execute', 'feature': 'alias_status', 'arguments': {}}}}
        response = subprocess.run([command['command'], *command['args']], input=json.dumps(query) + '\n',
                                  text=True, capture_output=True, env={**os.environ, **command['env']})
        result(response.stdout or response.stderr)
    elif text == 'deliver':
        Path('claude-result.md').write_text('Controlled Claude task result\n')
        subprocess.run(['git', 'add', 'claude-result.md'], check=True, capture_output=True)
        subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.com',
                        'commit', '-m', 'Controlled Claude result'], check=True, capture_output=True)
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
        report = tool('submit_report', {'name': 'evidence.md', 'text': 'Controlled process evidence'})
        submitted = tool('submit_result', {'commit': commit, 'result_refs': ['claude-result.md'],
                                         'evidence_refs': [report['report']], 'completion': 'Controlled result',
                                         'unresolved': []})
        result(json.dumps(submitted))
    elif text.startswith('wait'):
        waiting.append(text)
    else:
        while waiting:
            result(waiting.pop(0))
        result('|'.join(messages), text == 'provider-error')


for line in sys.stdin:
    event = json.loads(line)
    if event['type'] == 'control_request':
        request = event['request']
        initialized = {'hooks_applied': True}
        if os.environ.get('CLAUDE_FIXTURE_DIAGNOSTICS'):
            initialized.update(autoModeAvailable=False, permissionMode='default',
                               reason='private-unknown-reason', account={'email': 'private@example.invalid'})
        emit({'type': 'control_response', 'response': {'subtype': 'success',
              'request_id': event['request_id'], 'response': initialized}})
        if request['subtype'] == 'initialize':
            emit({'type': 'control_request', 'request_id': 'startup', 'request': {
                'subtype': 'hook_callback', 'callback_id': 'graphtraj_start', 'input': {
                    'hook_event_name': 'UserPromptSubmit', 'session_id': session,
                    'source': 'resume' if '--resume' in args else 'startup', 'transcript_path': str(history)}}})
        elif request['subtype'] == 'interrupt':
            if os.environ.get('CLAUDE_FIXTURE_NO_SETTLE'):
                continue
            time.sleep(float(os.environ.get('CLAUDE_FIXTURE_STOP_DELAY', '0')))
            result('interrupted')
    elif event['type'] == 'control_response':
        response = event['response']
        if response['request_id'] == 'startup':
            started = True
            init = {'type': 'system', 'subtype': 'init', 'session_id': session, 'model': model}
            observed_mode = os.environ.get('CLAUDE_FIXTURE_PERMISSION_MODE', permission_mode)
            if observed_mode is not None:
                init['permissionMode'] = observed_mode
            emit(init)
        elif response['request_id'] == 'permission-1':
            result(json.dumps(response['response']))
    elif event['type'] == 'user':
        # The real CLI may receive the prompt while the startup hook is pending;
        # it must not execute it until the host releases that hook.
        if not started:
            waiting.append(event)
        else:
            prompt(event)
    if started and waiting and isinstance(waiting[0], dict):
        prompt(waiting.pop(0))
