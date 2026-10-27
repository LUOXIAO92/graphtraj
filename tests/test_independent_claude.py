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
    assert wait.document['result']['last_result']['last_message'] == 'hello'
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
    # The wait returned the end, so the queued notice is not delivered again (367 result 2).
    notices = [notice for reply in replies for notice in reply.get('main_notices', [])]
    shown = [reply['result']['last_result']['last_message'] for reply in replies
             if reply.get('result', {}).get('last_result')]
    assert notices == [] and shown[0] == 'remembered352'
    assert 'main_notices' not in call('agents', {'action': 'discover'}).document
    assert host.context({'operation': 'notices', 'session': session})['notices'] == []
