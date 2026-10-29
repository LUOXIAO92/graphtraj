"""A child's native permission request notifies its parent once (381, D3).

Fake drivers report requests through the public ``ExecutionEvents``; nothing
here starts a Runtime.
"""

from __future__ import annotations

import threading

from agent_swarm import AgentControl, Caller, bind


MAIN = Caller('test-host', None, 'main-session', 'claude')
SECRET = 'sk-test-0123456789'


class RequestingDriver:
    """Reports native requests, then ends when told; a ``hold`` run stays running."""

    def __init__(self) -> None:
        self.runs: dict[str, object] = {}
        self.release = threading.Event()

    def prepare(self, runtime, caller, *, configuration=None, selection=None):
        return {'runtime': runtime}

    def start(self, run):
        run.events.session('native-' + run.agent[-6:])
        self.runs[run.agent] = run
        if run.message == 'ask':
            command = {'tool_name': 'Bash', 'input': {'command': f'curl -H "Authorization: {SECRET}"'}}
            first = {'request_token': 'tok-1', 'request_id': 1, 'method': 'claude/can_use_tool',
                     'params': command}
            run.events.request(first)
            # The Runtime retries delivery of the same request: no second notice.
            run.events.request(dict(first))
            run.events.request({'request_token': 'tok-2', 'request_id': 2,
                                'method': 'item/commandExecution/requestApproval', 'params': {}})
            run.events.finished('completed', last_message='answered')

    def deliver(self, run, message):
        raise AssertionError('not used')

    def interrupt(self, run):
        return False

    def requests(self, run):
        return []

    def reply(self, run, request, response):
        raise AssertionError('not used')


def test_root_request_notifies_the_host_once_per_request(tmp_path) -> None:
    """Two distinct requests give two notices; a repeated report gives none; ends are unchanged."""
    notices: list[dict] = []
    control = AgentControl(tmp_path, {'codex': RequestingDriver()}, request_notices=True,
                           event_receiver=lambda notice: notices.append(notice) or True)
    created = bind(control, MAIN)({'action': 'create', 'runtime': 'codex', 'instruction': 'ask'})
    assert not created.failed, created.document
    agent = created.document['agent']

    requests = [notice for notice in notices if notice['outcome'] == 'request']
    assert [notice['request'] for notice in requests] == ['tok-1', 'tok-2']
    first = requests[0]
    assert first['parent'] is None and first['agent'] == agent
    assert first['creator'] == {'host': 'test-host', 'agent': None, 'session': 'main-session'}
    assert first['session'] == 'native-' + agent[-6:] and first['error'] is None
    assert 'claude/can_use_tool for Bash' in first['body'] and 'reply' in first['body']
    # The request input may carry credentials; the notice never repeats it.
    assert all(SECRET not in str(notice) for notice in requests)
    assert [notice['outcome'] for notice in notices] == ['request', 'request', 'completed']
    # The retained requests are not duplicated either.
    status = bind(control, MAIN)({'action': 'status', 'agent': agent}).document['result']
    assert status['last_result']['outcome'] == 'completed'


def test_without_request_notices_only_ends_reach_the_host(tmp_path) -> None:
    """The default keeps existing hosts (and GraphTraj) unchanged."""
    notices: list[dict] = []
    control = AgentControl(tmp_path, {'codex': RequestingDriver()},
                           event_receiver=lambda notice: notices.append(notice) or True)
    assert not bind(control, MAIN)({'action': 'create', 'runtime': 'codex', 'instruction': 'ask'}).failed
    assert [notice['outcome'] for notice in notices] == ['completed']


def test_a_failing_receiver_leaves_the_request_readable(tmp_path) -> None:
    """A receiver error is not raised into the Runtime; the end still notifies."""
    seen: list[str] = []

    def receiver(notice):
        seen.append(notice['outcome'])
        if notice['outcome'] == 'request':
            raise OSError('host gone')
        return True

    control = AgentControl(tmp_path, {'codex': RequestingDriver()}, request_notices=True,
                           event_receiver=receiver)
    assert not bind(control, MAIN)({'action': 'create', 'runtime': 'codex', 'instruction': 'ask'}).failed
    assert seen == ['request', 'request', 'completed']


def test_a_parent_agents_native_receiver_gets_the_request(tmp_path) -> None:
    """A child of an Agent notifies that Agent's bound receiver, not the host."""
    host_notices: list[dict] = []
    parent_notices: list[dict] = []
    driver = RequestingDriver()
    control = AgentControl(tmp_path, {'codex': driver}, request_notices=True,
                           event_receiver=lambda notice: host_notices.append(notice) or True)
    parent = bind(control, MAIN)({'action': 'create', 'runtime': 'codex', 'instruction': 'hold'})
    assert not parent.failed, parent.document
    parent_agent = parent.document['agent']
    driver.runs[parent_agent].events.receive_children(lambda notice: parent_notices.append(notice) or True)

    as_parent = bind(control, Caller('test-host', parent_agent, 'native-' + parent_agent[-6:], 'codex'))
    child = as_parent({'action': 'create', 'runtime': 'codex', 'instruction': 'ask'})
    assert not child.failed, child.document
    assert [(notice['outcome'], notice['parent']) for notice in parent_notices] == [
        ('request', parent_agent), ('request', parent_agent), ('completed', parent_agent)]
    assert 'creator' not in parent_notices[0]
    assert host_notices == []
