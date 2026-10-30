"""Independent native control through the same bound public Agents interface."""
from pathlib import Path
from uuid import uuid4

import pytest

from agent_swarm import AgentControl, Caller, bind
from agent_swarm.claude import ClaudeDriver
from agent_swarm.claude.host import IndependentCalls
from test_claude_runtime import claude_environment  # noqa: F401


def test_standalone_claude_lifecycle(tmp_path: Path, claude_environment: None) -> None:
    """No project, Git or archive is needed for control, notifications or memory."""
    cwd = tmp_path / 'scratch'
    cwd.mkdir()
    notices = []
    control = AgentControl(tmp_path / 'agents', {'claude': ClaudeDriver(cwd, {})},
                           event_receiver=lambda event: notices.append(event) or True)
    call = bind(control, Caller('controlled-native-host', None, str(uuid4()), 'claude'))

    def execute(action: str, **fields: object) -> dict:
        """Check the public result before reading its lifecycle facts."""
        answer = call({'action': action, **fields})
        assert not answer.failed, answer.document
        return answer.document

    first = execute('create', runtime='claude', instruction='wait-first')
    agent, session = first['agent'], first['session']
    execute('send', agent=agent, message='go')
    done = execute('wait', agent=agent, timeout_seconds=20)
    assert done['result']['last_result']['outcome'] == 'completed'
    assert notices[-1]['body'] == 'wait-first|go'
    waiting = execute('send', agent=agent, message='wait-second')
    assert waiting['session'] == session
    execute('interrupt', agent=agent)
    stopped = execute('wait', agent=agent, timeout_seconds=20)
    assert stopped['result']['last_result']['outcome'] == 'interrupted'
    assert execute('resume', agent=agent, message='recall')['session'] == session
    done = execute('wait', agent=agent, timeout_seconds=20)
    assert notices[-1]['body'] == 'wait-first|go|wait-second|recall'
    assert done['result']['last_result']['notification'] == 'delivered'
    execute('retire', agent=agent)
    assert not execute('status')['result']['agents']
    assert not (tmp_path / 'agents/sessions').exists()


@pytest.mark.parametrize('behavior', ['allow', 'deny'])
def test_standalone_native_permission(tmp_path: Path, claude_environment: None, behavior: str) -> None:
    """Native requests remain explicit and one reply ends the original invocation."""
    control = AgentControl(tmp_path / 'agents', {'claude': ClaudeDriver(tmp_path, {})})
    call = bind(control, Caller('controlled-native-host', None, str(uuid4()), 'claude'))
    created = call({'action': 'create', 'runtime': 'claude', 'instruction': 'permission'})
    assert not created.failed, created.document
    agent = created.document['agent']
    waited = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 20})
    assert waited.document['result']['pending_requests'] == 1
    request = call({'action': 'requests', 'agent': agent}).document['result']['requests'][0]
    replied = call({'action': 'reply', 'agent': agent, 'request': request, 'response': {'behavior': behavior}})
    assert not replied.failed, replied.document
    done = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 20})
    assert done.document['result']['last_result']['outcome'] == 'completed'


def test_native_main_notice_is_scoped_and_acknowledged(tmp_path: Path, claude_environment: None) -> None:
    """A root's end is shown once: by the creating Session's wait, never pushed again.

    Task 367 result 2: an end that a wait already returned is not also pushed.
    Without a wait the mod claims it once; another Session never sees it.
    """
    host = IndependentCalls(tmp_path / 'agents', tmp_path, {})
    session = str(uuid4())
    request = {'action': 'execute', 'feature': 'create',
               'arguments': {'runtime': 'claude', 'instruction': 'hello'}}
    host.context({'operation': 'prepare', 'tool': 'agents', 'session': session,
                  'cwd': str(tmp_path), 'agent': None, 'request': request})
    created = host.call(request)
    assert not created.failed, created.document
    wait = host.make_call(session, tmp_path)('agents', {'action': 'execute', 'feature': 'wait',
        'arguments': {'agent': created.document['agent'], 'timeout_seconds': 20}})
    assert not wait.failed
    # Once: by this wait, or by the create result when the child ended before it returned.
    carried = [notice['event']['message'] for notice in created.document.get('main_notices', [])]
    message = wait.document['result']['last_result']['last_message']
    assert carried + ([message] if message is not None else []) == ['hello']
    pending = host.context({'operation': 'notices', 'session': session})
    assert wait.document.get('main_notices', []) + pending['notices'] == []
    assert host.context({'operation': 'notices', 'session': str(uuid4())})['notices'] == []

    second = {**request, 'arguments': {'runtime': 'claude', 'instruction': 'again'}}
    host.context({'operation': 'prepare', 'tool': 'agents', 'session': session,
                  'cwd': str(tmp_path), 'agent': None, 'request': second})
    assert not host.call(second).failed
    import time
    deadline, claimed = time.monotonic() + 20, []
    while not claimed and time.monotonic() < deadline:
        claimed = host.context({'operation': 'notices', 'session': session})['notices']
        time.sleep(0.05)
    assert [item['event']['message'] for item in claimed] == ['again']
    assert host.context({'operation': 'notices', 'session': str(uuid4())})['notices'] == []
    assert host.context({'operation': 'notices', 'session': session})['notices'] == []


def test_native_print_result_delivers_queued_notice_once(tmp_path: Path, claude_environment: None) -> None:
    """A print host receives real child output once without polling the mod channel."""
    import time

    host = IndependentCalls(tmp_path / 'agents', tmp_path, {})
    session = str(uuid4())
    call = host.make_call(session, tmp_path)
    created = call('agents', {'action': 'execute', 'feature': 'create',
        'arguments': {'runtime': 'claude', 'instruction': 'remembered352'}})
    assert not created.failed, created.document
    agent = created.document['agent']
    replies = [call('agents', {'action': 'execute', 'feature': 'wait',
        'arguments': {'agent': agent, 'timeout_seconds': 20}}).document]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline - 4.5:
        replies.append(call('agents', {'action': 'execute', 'feature': 'status',
                                      'arguments': {'agent': agent}}).document)
        time.sleep(0.01)
    # The body reached the Main once, by the wait or by the create result, never both (367 result 2).
    notices = [notice['event']['message'] for reply in [created.document, *replies]
               for notice in reply.get('main_notices', [])]
    shown = [reply['result']['last_result']['last_message'] for reply in replies
             if reply.get('result', {}).get('last_result')]
    assert notices + [message for message in shown if message is not None] == ['remembered352']
    assert 'main_notices' not in call('agents', {'action': 'discover'}).document
    assert host.context({'operation': 'notices', 'session': session})['notices'] == []


@pytest.mark.parametrize('instruction, reason', [
    ('fallback', "Runtime reason: model_refusal_fallback: Opus 5.5's safeguards flagged this session."),
    ('fallback-unexplained', 'Runtime reason: not provided in the native stream.'),
])
def test_model_change_failure_names_both_models_and_reason(
        tmp_path: Path, claude_environment: None, instruction: str, reason: str) -> None:
    """The unchanged strict model check states what was requested, observed and why."""
    import json

    notices = []
    control = AgentControl(tmp_path / 'agents', {'claude': ClaudeDriver(tmp_path, {})},
                           event_receiver=lambda event: notices.append(event) or True)
    call = bind(control, Caller('controlled-native-host', None, str(uuid4()), 'claude'))
    created = call({'action': 'create', 'runtime': 'claude', 'instruction': instruction})
    assert not created.failed, created.document
    done = call({'action': 'wait', 'agent': created.document['agent'], 'timeout_seconds': 20})
    last = done.document['result']['last_result']
    assert last['outcome'] == 'failed'
    assert last['error']['code'] == 'RUNTIME_REQUEST_FAILED'
    message = last['error']['message']
    assert message.startswith('Claude changed the configured model: requested model ')
    assert 'observed model claude-opus-4-8' in message
    assert reason in message
    if instruction == 'fallback':
        assert 'fallbackModel=claude-opus-4-8' in message
    # The persisted execution error is the one any later notice is built from.
    record = json.loads((tmp_path / 'agents' / 'control' / 'agents'
                         / f"{created.document['agent']}.json").read_text())
    assert record['executions'][-1]['error'] == last['error']
    # A failure needs the parent even without a last message (Task 367 result 3(d)):
    # the host receives one notice carrying the persisted error.
    assert [(notice['outcome'], notice['body'], notice['error']) for notice in notices] == [
        ('failed', None, last['error'])]
    assert record['executions'][-1]['notification'] == 'delivered'


@pytest.mark.parametrize('case', ['elsewhere', 'archive'])
def test_refused_host_start_is_readable_in_calls_and_log(tmp_path: Path, case: str) -> None:
    """A refused start completes the MCP handshake and reports why; it binds no control.

    ``archive``: ``save_normalized_sessions: true`` is accepted since 384.
    """
    import json
    import os
    import subprocess
    import sys

    import agent_swarm

    project, elsewhere = tmp_path / 'project', tmp_path / 'elsewhere'
    root = project / '.agents-control'
    root.mkdir(parents=True)
    elsewhere.mkdir()
    config = root / 'claude-host.json'
    # The verified native parent is this launcher, so it is the configured CLI.
    config.write_text(json.dumps({'root': str(root), 'cwd': str(project), 'claude': sys.executable,
                                  'channel_file': str(root / 'live' / 'channel.json'), 'settings': {}}))
    if case == 'archive':
        (root / 'config.yml').write_text('save_normalized_sessions: true\n')
    messages = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                 'params': {'name': 'agents', 'arguments': {'action': 'discover'}}}]
    launcher = ('import subprocess, sys\n'
                'done = subprocess.run([sys.executable, "-m", "agent_swarm.claude.host", "serve", "--config",'
                ' sys.argv[1]], input=sys.stdin.read(), capture_output=True, text=True, timeout=30)\n'
                'sys.stdout.write(done.stdout); sys.stderr.write(done.stderr)\n')
    source = str(Path(agent_swarm.__file__).parents[1])
    finished = subprocess.run(
        [sys.executable, '-c', launcher, str(config)], cwd=elsewhere if case == 'elsewhere' else project,
        input=''.join(json.dumps(message) + '\n' for message in messages), capture_output=True, text=True,
        timeout=60, env={**os.environ, 'PYTHONPATH': source + os.pathsep + os.environ.get('PYTHONPATH', '')})
    replies = [json.loads(line) for line in finished.stdout.splitlines()]
    assert replies[0]['result']['serverInfo']['name'] == 'agents'
    called = replies[1]['result']
    if case == 'archive':
        # 384: archiving on no longer refuses the host at start. (This bare
        # launcher has no native caller context, so the call itself is refused.)
        text = json.dumps(called)
        assert 'archive-unavailable' not in text and 'host-unavailable' not in text, called
        assert 'did not start' not in (root / 'host.log').read_text()
        return
    assert called['isError'] is True
    error = called['structuredContent']['error']
    assert error['code'] == 'host-unavailable'
    assert f'started in {elsewhere.resolve()}' in error['message']
    assert f'configured for {project.resolve()}' in error['message']
    assert error['message'] in finished.stderr
    assert error['message'] in (root / 'host.log').read_text()
    assert not (root / 'control').exists() and not (root / 'live').exists()


@pytest.mark.parametrize('case', ['refused', 'serving'])
def test_session_end_is_logged_as_a_stop_not_a_traceback(tmp_path: Path, case: str) -> None:
    """Claude Code ends a session with SIGINT; the log keeps one stop line and no traceback."""
    import json
    import os
    import subprocess
    import sys

    import agent_swarm

    project, elsewhere = tmp_path / 'project', tmp_path / 'elsewhere'
    root = project / '.agents-control'
    root.mkdir(parents=True)
    elsewhere.mkdir()
    channel = root / 'live' / 'channel.json'
    config = root / 'claude-host.json'
    config.write_text(json.dumps({'root': str(root), 'cwd': str(project), 'claude': sys.executable,
                                  'channel_file': str(channel), 'settings': {}}))
    # The launcher is the verified native parent; it interrupts the host like Claude Code.
    # Like Claude Code it starts the host with the default SIGINT disposition: a
    # suite run as a background job would otherwise pass SIGINT ignored (372).
    launcher = ('import json, signal, subprocess, sys\n'
                'host = subprocess.Popen([sys.executable, "-m", "agent_swarm.claude.host", "serve", "--config",'
                ' sys.argv[1]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,'
                ' preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))\n'
                'host.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",'
                ' "params": {}}) + "\\n"); host.stdin.flush()\n'
                'print(host.stdout.readline().strip())\n'
                'host.send_signal(signal.SIGINT)\n'
                'print(host.wait(timeout=30))\n')
    source = str(Path(agent_swarm.__file__).parents[1])
    finished = subprocess.run(
        [sys.executable, '-c', launcher, str(config)], cwd=elsewhere if case == 'refused' else project,
        capture_output=True, text=True, timeout=60,
        env={**os.environ, 'PYTHONPATH': source + os.pathsep + os.environ.get('PYTHONPATH', '')})
    reply, returncode = finished.stdout.splitlines()
    assert json.loads(reply)['result']['serverInfo']['name'] == 'agents'
    assert returncode == '0', finished.stderr
    log = (root / 'host.log').read_text()
    assert 'Traceback' not in log and 'KeyboardInterrupt' not in log
    assert 'agents host stopped: Claude Code ended the session (SIGINT).' in log
    if case == 'refused':
        assert 'The agents host did not start: Claude Code was started in' in log
    else:
        assert 'did not start' not in log and not channel.exists()


def test_context_reports_a_refused_host_in_one_line(tmp_path: Path) -> None:
    """The mod's context step shows the refusal reason, not a missing-channel traceback."""
    import json
    import os
    import subprocess
    import sys

    import agent_swarm

    project, elsewhere = tmp_path / 'project', tmp_path / 'elsewhere'
    root = project / '.agents-control'
    root.mkdir(parents=True)
    elsewhere.mkdir()
    config = root / 'claude-host.json'
    config.write_text(json.dumps({'root': str(root), 'cwd': str(project), 'claude': sys.executable,
                                  'channel_file': str(root / 'live' / 'channel.json'), 'settings': {}}))
    env = {**os.environ, 'PYTHONPATH': str(Path(agent_swarm.__file__).parents[1]) + os.pathsep
           + os.environ.get('PYTHONPATH', '')}

    def context() -> subprocess.CompletedProcess:
        """Run the mod's context entry as the hook does, with one request on stdin."""
        return subprocess.run([sys.executable, '-m', 'agent_swarm.claude.host', 'context', '--config', str(config)],
                              input='{}', capture_output=True, text=True, timeout=30, env=env)

    idle = context()
    assert idle.returncode == 1 and 'Traceback' not in idle.stderr
    assert idle.stderr.splitlines() == [f"The agents host for this project is not running; see {root / 'host.log'}."]
    launcher = ('import json, signal, subprocess, sys\n'
                'host = subprocess.Popen([sys.executable, "-m", "agent_swarm.claude.host", "serve", "--config",'
                ' sys.argv[1]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,'
                ' preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))\n'
                'host.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",'
                ' "params": {}}) + "\\n"); host.stdin.flush()\n'
                'print(host.stdout.readline().strip()); sys.stdout.flush()\n'
                'sys.stdin.readline()\n'
                'host.send_signal(signal.SIGINT)\n'
                'print(host.wait(timeout=30))\n')
    host = subprocess.Popen([sys.executable, '-c', launcher, str(config)], cwd=elsewhere, env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert json.loads(host.stdout.readline())['result']['serverInfo']['name'] == 'agents'
    refused = context()
    host.stdin.write('stop\n')
    host.stdin.flush()
    assert host.stdout.readline().strip() == '0'
    host.wait(timeout=30)
    assert refused.returncode == 1 and 'Traceback' not in refused.stderr
    [line] = refused.stderr.splitlines()
    assert line.startswith('host-unavailable: The agents host did not start: ')
    assert f'started in {elsewhere.resolve()}' in line
    assert not (root / 'host-refusal.json').exists() and not (root / 'live').exists()
