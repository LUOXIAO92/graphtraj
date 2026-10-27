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
    """The mod consumes one root's completion; another Session sees no notice."""
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
    pending = host.context({'operation': 'notices', 'session': session})
    delivered = wait.document.get('main_notices', []) + pending['notices']
    assert [item['event']['message'] for item in delivered] == ['hello']
    assert host.context({'operation': 'notices', 'session': str(uuid4())})['notices'] == []
    host.context({'operation': 'acknowledge', 'session': session, 'position': pending['position']})
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
    while not any(reply.get('main_notices') for reply in replies) and time.monotonic() < deadline:
        replies.append(call('agents', {'action': 'execute', 'feature': 'status',
                                      'arguments': {'agent': agent}}).document)
        time.sleep(0.01)
    notices = [notice for reply in replies for notice in reply.get('main_notices', [])]
    assert [notice['event']['message'] for notice in notices] == ['remembered352']
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
    # Today a failure without a last message sends no notice (control.py finished).
    assert notices == [] and record['executions'][-1].get('notification') is None


@pytest.mark.parametrize('case', ['elsewhere', 'archive'])
def test_refused_host_start_is_readable_in_calls_and_log(tmp_path: Path, case: str) -> None:
    """A refused start completes the MCP handshake and reports why; it binds no control."""
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
    assert called['isError'] is True
    error = called['structuredContent']['error']
    if case == 'elsewhere':
        assert error['code'] == 'host-unavailable'
        assert f'started in {elsewhere.resolve()}' in error['message']
        assert f'configured for {project.resolve()}' in error['message']
    else:
        assert error['code'] == 'archive-unavailable'
        assert 'save_normalized_sessions: true is not available here' in error['message']
        assert 'set it to false' in error['message'].lower()
    assert error['message'] in finished.stderr
    assert error['message'] in (root / 'host.log').read_text()
    assert not (root / 'control').exists() and not (root / 'live').exists()
