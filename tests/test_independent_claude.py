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


def test_native_print_result_delivers_queued_notice_once(tmp_path: Path) -> None:
    """A print host receives the body through its next result even without idle push."""
    host = IndependentCalls(tmp_path / 'agents', tmp_path, {})
    session = str(uuid4())
    call = host.make_call(session, tmp_path)
    host.queue[session] = [{'event': {'alias': 'child', 'message': 'remembered352'}}]
    result = call('agents', {'action': 'execute', 'feature': 'status', 'arguments': {}})
    assert result.document['main_notices'][0]['event']['message'] == 'remembered352'
    assert 'main_notices' not in call('agents', {'action': 'discover'}).document
    assert host.context({'operation': 'notices', 'session': session})['notices'] == []
