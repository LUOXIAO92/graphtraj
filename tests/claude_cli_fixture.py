"""Controlled official CLI peer: no model, sandbox or authentication is simulated as real."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone


def emit(value: dict) -> None:
    """Send one native protocol record."""
    global parent_uuid
    if value.get('type') in {'user', 'assistant'}:
        value.setdefault('uuid', str(uuid.uuid4()))
        value.setdefault('timestamp', datetime.now(timezone.utc).isoformat())
        if value['type'] == 'assistant':
            value['message'].setdefault('id', 'api-' + value['uuid'])
            value['message'].setdefault('model', model)
        native = {**value, 'sessionId': session, 'parentUuid': parent_uuid}
        with transcript.open('a') as stream:
            stream.write(json.dumps(native) + '\n')
        parent_uuid = value['uuid']
    print(json.dumps(value), flush=True)


if '--version' in sys.argv:
    print('2.1.299 (Claude Code)')
    raise SystemExit
if os.environ.get('CLAUDE_FIXTURE_FAIL'):
    print('controlled startup failure', file=sys.stderr)
    raise SystemExit(17)
if os.environ.get('CLAUDE_FIXTURE_DIAGNOSTICS'):
    print('Warning: auto mode unavailable; token=sk-diagnosticsecret; email=private@example.invalid', file=sys.stderr)
    print('Permission mode forced to default — CLAUDE_CODE_SUBPROCESS_ENV_SCRUB is set '
          '(allowed_non_write_users hardening). Declare allowedTools explicitly, or set '
          'CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=0 to opt out.', file=sys.stderr)
args = sys.argv
session = args[args.index('--resume' if '--resume' in args else '--session-id') + 1]
model = args[args.index('--model') + 1]
permission_mode = args[args.index('--permission-mode') + 1] if '--permission-mode' in args else None
Path(os.environ['CLAUDE_FIXTURE_HOME'], 'native-permissions.json').write_text(json.dumps({
    'model': model,
    'effort': args[args.index('--effort') + 1] if '--effort' in args else None,
    'mode': permission_mode, 'settings': json.loads(args[args.index('--settings') + 1]),
    'restricted': '--restricted' in args, 'cwd': os.getcwd(),
    'add_dirs': [args[i + 1] for i, item in enumerate(args) if item == '--add-dir'],
    'scrub': os.environ.get('CLAUDE_CODE_SUBPROCESS_ENV_SCRUB'),
    'permission_handler': args[args.index('--permission-prompt-tool') + 1],
}))
history = Path(os.environ['CLAUDE_FIXTURE_HOME']) / (session + '.json')
transcript = history.with_suffix('.jsonl')
parent_uuid = os.environ.get('CLAUDE_FIXTURE_PARENT_UUID') or (
    json.loads(transcript.read_text().splitlines()[-1])['uuid'] if transcript.exists() else None)
Path(os.environ['CLAUDE_FIXTURE_HOME'], 'native-selection.json').write_text(json.dumps({
    'model': model, 'effort': args[args.index('--effort') + 1] if '--effort' in args else None,
    'environment_effort': os.environ.get('CLAUDE_CODE_EFFORT_LEVEL'),
}))
messages = json.loads(history.read_text()) if history.exists() else []
Path(os.environ['CLAUDE_FIXTURE_HOME'], 'native-endpoint.json').write_text(
    json.dumps(os.environ.get('ANTHROPIC_BASE_URL')))
started = False
startup_sent = False
sdk_ready = False
waiting = []
merging = []
absorbing = []
late = []
sdk_create_results = []
sdk_request_arguments = {'action': 'execute', 'feature': 'status', 'arguments': {}}
sdk_display = False
sdk_display_reply = None
# As the real CLI does, a later prompt runs its UserPromptSubmit hook and is
# dropped when the host does not answer within the hook timeout.
later_hook_timeout = float(os.environ.get('CLAUDE_FIXTURE_LATER_HOOK_TIMEOUT', '0'))
prompt_hooks = {}


def later_prompt(message: dict) -> None:
    """Hold a later prompt until the host answers its native hook."""
    identity = 'prompt-' + str(uuid.uuid4())
    prompt_hooks[identity] = message

    def expire() -> None:
        """Drop the prompt as the CLI reports its hook timeout."""
        if prompt_hooks.pop(identity, None) is not None:
            with open(os.environ['CLAUDE_FIXTURE_HOOK_LOG'], 'a') as log:
                log.write(f'UserPromptSubmit hook callback timed out after {int(later_hook_timeout * 1000)}ms\n')

    timer = threading.Timer(later_hook_timeout, expire)
    timer.daemon = True
    timer.start()
    emit({'type': 'control_request', 'request_id': identity, 'request': {
        'subtype': 'hook_callback', 'callback_id': 'graphtraj_start', 'input': {
            'hook_event_name': 'UserPromptSubmit', 'session_id': session,
            'transcript_path': str(transcript), 'prompt': message['message']['content']}}})


def write_transcript(record: dict) -> None:
    """Append one native transcript record that has no stream counterpart."""
    global parent_uuid
    if 'uuid' in record:
        record['parentUuid'] = parent_uuid
        parent_uuid = record['uuid']
    with transcript.open('a') as stream:
        stream.write(json.dumps(record) + '\n')


def result(text: str, error: bool = False, queued: int | None = 0, idle: bool = True) -> None:
    """Emit distinct result and quiescence records with native usage."""
    usage = {'input_tokens': 11, 'cache_read_input_tokens': 7,
             'cache_creation_input_tokens': 2, 'output_tokens': 5}
    emit({'type': 'assistant', 'session_id': session, 'message': {
        'role': 'assistant', 'content': [{'type': 'text', 'text': text}], 'usage': usage}})
    emit({'type': 'result', 'session_id': session, 'uuid': str(uuid.uuid4()),
          'is_error': error, 'result': text, 'usage': {
              'input_tokens': 11, 'cache_read_input_tokens': 7,
              'cache_creation_input_tokens': 2, 'output_tokens': 5},
          **({'queued_turn_count': queued} if queued is not None else {})})
    if idle:
        emit({'type': 'system', 'subtype': 'session_state_changed', 'state': 'idle'})



def ask_bridge(feature: str, arguments: dict) -> str:
    """Call a public tool through the owned stdio MCP subprocess; return its answer line.

    As a stdio client does, this keeps the input open until the answer is read:
    input EOF means the client went away and ends the call's waits.
    """
    command = json.loads(args[args.index('--mcp-config') + 1])['mcpServers']['agents']
    query = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
        'name': 'tasks', 'arguments': {'action': 'execute', 'feature': feature, 'arguments': arguments}}}
    with tempfile.TemporaryFile('w+') as errors, subprocess.Popen(
            [command['command'], *command['args']], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
            text=True, env={**os.environ, **command['env']}) as bridge:
        bridge.stdin.write(json.dumps(query) + '\n')
        bridge.stdin.flush()
        answer = bridge.stdout.readline()
        bridge.stdin.close()
        bridge.wait()
        errors.seek(0)
        return answer or errors.read()


def call(feature: str, arguments: dict) -> dict:
    """Return an actual public tool's MCP result."""
    return json.loads(ask_bridge(feature, arguments))['result']


def tool(feature: str, arguments: dict) -> dict:
    """Return a public tool's structured result, failing on its error."""
    value = call(feature, arguments)
    if value['isError']:
        raise RuntimeError(value)
    return value['structuredContent']


def prompt(message: dict) -> None:
    """Process fixture input only after Runner releases the startup hook."""
    global sdk_request_arguments, sdk_display
    text = message['message']['content']
    messages.append(text)
    history.write_text(json.dumps(messages))
    if absorbing:
        # As a 2.1.302 transcript recorded: input joining a running turn is a
        # queued_command attachment plus its absorbed_mid_turn queue removal.
        # Its stream echo and the result's queued-turn count were not retained,
        # so this peer emits neither.
        write_transcript({'type': 'queue-operation', 'operation': 'enqueue', 'sessionId': session})
        write_transcript({'type': 'attachment', 'uuid': str(uuid.uuid4()), 'sessionId': session,
                          'attachment': {'type': 'queued_command', 'prompt': text,
                                         'source_uuid': message['uuid'], 'delivery_id': 'delivery-1'}})
        write_transcript({'type': 'queue-operation', 'operation': 'remove', 'reason': 'absorbed_mid_turn',
                          'sessionId': session, 'commandUuid': message['uuid'], 'deliveryId': 'delivery-1'})
        absorbing.clear()
        result('|'.join(messages), queued=None)
        return
    emit({'type': 'system', 'subtype': 'session_state_changed', 'state': 'running'})
    if '--replay-user-messages' in args:
        # As observed: the echo is emitted when input joins the running turn.
        emit({'type': 'user', 'isReplay': True, 'session_id': session, 'message': message['message'],
              'uuid': message.get('uuid') or str(uuid.uuid4())})
    if late:
        # The earlier turn's idle arrives only after this later input's echo.
        emit({'type': 'system', 'subtype': 'session_state_changed', 'state': 'idle'})
        late.clear()
    if merging:
        # Input delivered during this turn joins it and shares its one result.
        if merging[0] == 'merge-late':
            late.append(text)
        result('|'.join(merging + [text]), idle=not late)
        merging.clear()
    elif text in ('merge', 'merge-late'):
        merging.append(text)
    elif text == 'absorb':
        absorbing.append(text)
    elif text == 'garbage':
        print('not json secret-token', flush=True)
    elif text == 'permission':
        emit({'type': 'control_request', 'request_id': 'permission-1', 'request': {
            'subtype': 'can_use_tool', 'tool_name': 'Bash', 'input': {'command': 'echo approved'},
            'tool_use_id': 'tool-1'}})
    elif text in {'sdk-agents-status', 'sdk-agents-create-twice', 'sdk-agents-display'}:
        assert 'agents' in sdk_servers
        if text in {'sdk-agents-create-twice', 'sdk-agents-display'}:
            sdk_request_arguments = {'action': 'execute', 'feature': 'create',
                                     'arguments': {'runtime': 'claude', 'instruction': 'child'}}
        sdk_display = text == 'sdk-agents-display'
        emit({'type': 'control_request', 'request_id': 'sdk-list', 'request': {
            'subtype': 'mcp_message', 'server_name': 'agents',
            'message': {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}}})
    elif text == 'mcp':
        result(ask_bridge('session_reports', {'alias': 'research@x1'}))
    elif text == 'deliver':
        Path('claude-result.md').write_text('Controlled Claude task result\n')
        subprocess.run(['git', 'add', 'claude-result.md'], check=True, capture_output=True)
        subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.com',
                        'commit', '-m', 'Controlled Claude result'], check=True, capture_output=True)
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
        report_request = {'name': 'evidence.md', 'text': 'Controlled process evidence'}
        report = tool('submit_report', report_request)
        assert tool('submit_report', report_request) == report
        submission = {'commit': commit, 'result_refs': ['claude-result.md'],
                      'evidence_refs': [report['report']], 'completion': 'Controlled result', 'unresolved': []}
        submitted = tool('submit_result', submission)
        assert tool('submit_result', submission) == submitted
        result(json.dumps(submitted))
    elif text.startswith('fallback'):
        # A native model fallback, with or without the Runtime's explanation. Field names
        # follow the native transcript record of a real fallback (system/model_refusal_fallback).
        if text == 'fallback':
            emit({'type': 'system', 'subtype': 'model_refusal_fallback', 'session_id': session,
                  'content': "Opus 5.5's safeguards flagged this session. Opus 4.8 is answering instead.",
                  'trigger': 'refusal', 'originalModel': model, 'fallbackModel': 'claude-opus-4-8',
                  'apiRefusalCategory': 'cyber'})
        emit({'type': 'assistant', 'session_id': session, 'message': {
            'role': 'assistant', 'model': 'claude-opus-4-8', 'content': [{'type': 'text', 'text': 'fallback'}]}})
        result('fallback')
    elif text.startswith('register'):
        # Register one direct helper child, then answer with the tool outcome.
        result(json.dumps(call('swarm', {'tasks': [{'role': 'helper'}]})), text == 'register-error')
    elif text.startswith('wait') or (
            os.environ.get('CLAUDE_FIXTURE_HOLD_FILE') and Path(os.environ['CLAUDE_FIXTURE_HOLD_FILE']).exists()
            and 'Direct child execution results' not in text):
        if text == 'wait-stream':
            # A long streamed answer the host collects fragment by fragment.
            emit({'type': 'stream_event', 'session_id': session, 'parent_tool_use_id': None,
                  'uuid': str(uuid.uuid4()), 'event': {'type': 'message_start', 'message': {
                      'id': 'api-stream', 'model': model, 'role': 'assistant', 'content': []}}})
            for _ in range(int(os.environ.get('CLAUDE_FIXTURE_STREAM_FRAGMENTS', '0'))):
                emit({'type': 'stream_event', 'session_id': session, 'parent_tool_use_id': None,
                      'uuid': str(uuid.uuid4()), 'event': {'type': 'content_block_delta', 'index': 0,
                                                           'delta': {'type': 'text_delta', 'text': 'x'}}})
        waiting.append(text)
    else:
        while waiting:
            # The rest of the held inputs and this input still await their own turns.
            result(waiting.pop(0), queued=len(waiting) + 1)
        result(str(Path.cwd()) if text == 'child' and os.environ.get('CLAUDE_FIXTURE_REPORT_CWD')
               else '|'.join(messages), text == 'provider-error')


def hold_start_lock() -> None:
    """Let another process hold the project startup lock across the startup hook."""
    lock = os.environ.get('CLAUDE_FIXTURE_START_LOCK')
    if not lock:
        return
    ready = Path(lock + '.held')
    subprocess.Popen([sys.executable, '-c', (
        'import fcntl,sys,time\n'
        'stream = open(sys.argv[1], "a+b")\n'
        'fcntl.flock(stream, fcntl.LOCK_EX)\n'
        'open(sys.argv[1] + ".held", "w").close()\n'
        'time.sleep(float(sys.argv[2]))\n'), lock, os.environ['CLAUDE_FIXTURE_START_LOCK_SECONDS']],
        start_new_session=True)
    deadline = time.monotonic() + 10
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.01)


def startup() -> None:
    """Attest the native Session after completing any SDK tool handshake."""
    global hook_sent
    hold_start_lock()
    gate = os.environ.get('CLAUDE_FIXTURE_HOOK_GATE')
    if gate:
        # Let the test publish a stop after process start but before the hook.
        Path(gate + '.waiting').touch()
        deadline = time.monotonic() + 60
        while not Path(gate).exists() and time.monotonic() < deadline:
            time.sleep(0.01)
    hook_sent = time.monotonic()
    emit({'type': 'control_request', 'request_id': 'startup', 'request': {
        'subtype': 'hook_callback', 'callback_id': 'graphtraj_start', 'input': {
            'hook_event_name': 'UserPromptSubmit', 'session_id': session,
            'source': 'resume' if '--resume' in args else 'startup', 'transcript_path': str(transcript)}}})


for line in sys.stdin:
    event = json.loads(line)
    if event['type'] == 'control_request':
        request = event['request']
        if request['subtype'] == 'apply_flag_settings':
            if os.environ.get('CLAUDE_FIXTURE_REJECT_RESOURCES'):
                emit({'type': 'control_response', 'response': {
                    'subtype': 'error', 'request_id': event['request_id'],
                    'error': 'Exact resource settings refused by native peer.',
                }})
                continue
            path = Path(os.environ['CLAUDE_FIXTURE_HOME'], 'native-permissions.json')
            observed = json.loads(path.read_text())
            observed['settings'].update(request['settings'])
            observed['resource_update_before_prompt'] = not messages
            path.write_text(json.dumps(observed))
        initialized = {'hooks_applied': True}
        if os.environ.get('CLAUDE_FIXTURE_DIAGNOSTICS'):
            initialized.update(autoModeAvailable=False, permissionMode='default',
                               reason='private-unknown-reason', account={'email': 'private@example.invalid'})
        emit({'type': 'control_response', 'response': {'subtype': 'success',
              'request_id': event['request_id'], 'response': initialized}})
        if request['subtype'] == 'initialize':
            sdk_servers = request.get('sdkMcpServers', [])
            if sdk_servers:
                emit({'type': 'control_request', 'request_id': 'sdk-initialize', 'request': {
                    'subtype': 'mcp_message', 'server_name': 'agents', 'message': {
                        'jsonrpc': '2.0', 'id': 10, 'method': 'initialize',
                        'params': {'protocolVersion': '2025-06-18'}}}})
            else:
                sdk_ready = True
        elif request['subtype'] == 'interrupt':
            if os.environ.get('CLAUDE_FIXTURE_ESCAPED_PIPE'):
                # A tool child outside the owned group keeps stdout open until
                # the test releases it (bounded, so it never outlives the test).
                child = subprocess.Popen([sys.executable, '-c', (
                    'import os,sys,time\n'
                    'deadline = time.monotonic() + 120\n'
                    'while not os.path.exists(sys.argv[1]) and time.monotonic() < deadline:\n'
                    '    time.sleep(0.05)\n'), os.environ['CLAUDE_FIXTURE_ESCAPED_PIPE'] + '.release'],
                    start_new_session=True)
                Path(os.environ['CLAUDE_FIXTURE_ESCAPED_PIPE']).write_text(str(child.pid))
            if os.environ.get('CLAUDE_FIXTURE_NO_SETTLE'):
                continue
            time.sleep(float(os.environ.get('CLAUDE_FIXTURE_STOP_DELAY', '0')))
            result('interrupted')
    elif event['type'] == 'control_response':
        response = event['response']
        held = prompt_hooks.pop(response['request_id'], None)
        if held is not None:
            prompt(held)
        elif response['request_id'].startswith('prompt-'):
            pass  # Answered after the CLI dropped the prompt.
        elif response['request_id'] == 'sdk-initialize':
            assert response['response']['mcp_response']['result']['protocolVersion'] == '2025-06-18'
            emit({'type': 'control_request', 'request_id': 'sdk-initial-tools', 'request': {
                'subtype': 'mcp_message', 'server_name': 'agents',
                'message': {'jsonrpc': '2.0', 'id': 11, 'method': 'tools/list'}}})
        elif response['request_id'] == 'sdk-initial-tools':
            assert response['response']['mcp_response']['result']['tools'][0]['name'] == 'agents'
            sdk_ready = True
        elif response['request_id'] == 'startup':
            started = True
            if os.environ.get('CLAUDE_FIXTURE_HOOK_LOG'):
                with open(os.environ['CLAUDE_FIXTURE_HOOK_LOG'], 'a') as log:
                    log.write(f'{time.monotonic() - hook_sent}\n')
            init = {'type': 'system', 'subtype': 'init', 'session_id': session, 'model': model}
            if sdk_servers:
                init['tools'] = ['mcp__agents__agents']
            observed_mode = os.environ.get('CLAUDE_FIXTURE_PERMISSION_MODE', permission_mode)
            if observed_mode is not None:
                init['permissionMode'] = observed_mode
            emit(init)
        elif response['request_id'] == 'permission-1':
            result(json.dumps(response['response']))
        elif response['request_id'] == 'sdk-list':
            tools = response['response']['mcp_response']['result']['tools']
            assert [tool['name'] for tool in tools] == ['agents']
            call_request = {'type': 'control_request', 'request_id': 'sdk-call', 'request': {
                'subtype': 'mcp_message', 'server_name': 'agents', 'message': {
                    'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                    'params': {'name': 'agents', 'arguments': sdk_request_arguments}}}}
            emit(call_request)
            if sdk_request_arguments['feature'] == 'create' and not sdk_display:
                emit({**call_request, 'request_id': 'sdk-call-copy'})
        elif response['request_id'] in {'sdk-call', 'sdk-call-copy'}:
            reply = response['response']['mcp_response']['result']
            if sdk_display:
                sdk_display_reply = reply
                emit({'type': 'control_request', 'request_id': 'sdk-display', 'request': {
                    'subtype': 'hook_callback', 'callback_id': 'graphtraj_agents_display', 'input': {
                        'hook_event_name': 'PostToolUse', 'session_id': session,
                        'tool_use_id': 'display-' + sdk_request_arguments['feature'],
                        'tool_name': 'mcp__agents__agents', 'tool_input': sdk_request_arguments,
                        'tool_response': reply}}})
            elif sdk_request_arguments['feature'] == 'create':
                sdk_create_results.append(reply)
                if len(sdk_create_results) == 2:
                    result(json.dumps(sdk_create_results))
            else:
                result(json.dumps(reply))
        elif response['request_id'] == 'sdk-display':
            with history.with_suffix('.display.jsonl').open('a') as display:
                display.write(json.dumps(response['response']) + '\n')
            if sdk_request_arguments['feature'] == 'create':
                sdk_request_arguments = {'action': 'execute', 'feature': 'wait',
                    'arguments': {'agent': sdk_display_reply['structuredContent']['agent'], 'timeout_seconds': 20}}
                emit({'type': 'control_request', 'request_id': 'sdk-call', 'request': {
                    'subtype': 'mcp_message', 'server_name': 'agents', 'message': {
                        'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                        'params': {'name': 'agents', 'arguments': sdk_request_arguments}}}})
            else:
                result(json.dumps(sdk_display_reply))
    elif event['type'] == 'user':
        # The real CLI may receive the prompt while the startup hook is pending;
        # it must not execute it until the host releases that hook.
        if not started:
            waiting.append(event)
        elif later_hook_timeout:
            later_prompt(event)
        else:
            prompt(event)
    # UserPromptSubmit belongs to an actual prompt, not initialize. This also
    # keeps readiness behind the initial prompt when settings are applied first.
    if waiting and sdk_ready and not startup_sent:
        startup_sent = True
        startup()
    if started and waiting and isinstance(waiting[0], dict):
        prompt(waiting.pop(0))
if os.environ.get('CLAUDE_FIXTURE_EOF_FILE'):
    Path(os.environ['CLAUDE_FIXTURE_EOF_FILE']).touch()
if os.environ.get('CLAUDE_FIXTURE_HOLD_ON_EOF'):
    # A CLI still inside its turn outlives stdin closure until signalled.
    time.sleep(60)
