"""Task 477: status, wait and retire always show the child's last message; a reply a
parent's wait returned is not pushed to it again; an un-waited reply is pushed once.

Paths: a GraphTraj Task member on graphtraj-gateway (``_main_notice`` pushes to the
member's Session), a root Agent of a host receiver (the claude-native Main shape),
with and without ``hold_notices``, and a native parent receiver.
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from graftling import AgentControl, Binding, Caller, bind
from graphtraj.interfaces.agents import swarm_root
from test_member_child_end_notice_446 import GATEWAY, MEMBER, Driver, project  # noqa: F401  (fixture)


def _record(root: Path, agent: str) -> dict:
    return json.loads((root / 'control' / 'agents' / f'{agent}.json').read_text(encoding='utf-8'))


def _until(predicate, seconds: float = 5.0) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, 'condition not reached'
        time.sleep(0.01)


def _waiting(root: Path, agent: str) -> bool:
    return bool(_record(root, agent)['executions'][-1].get('waiters'))


def _wait_in_thread(call, timeout: float = 10.0) -> tuple[threading.Thread, list]:
    out: list = []
    thread = threading.Thread(target=lambda: out.append(call(timeout)))
    thread.start()
    return thread, out


# -- graphtraj-gateway: a Task member's child ---------------------------------

def _member_child(project, running: bool = False):
    root, member, agents, sent, send, child = project
    if running:  # mid-turn: the member's Session has no terminal record
        from graphtraj.configuration.project_configuration import runner_directory
        (runner_directory(root) / 'sessions' / MEMBER / 'execution.yml').unlink()
    driver = Driver({})
    agents.control = AgentControl(swarm_root(root), {'claude': driver}, event_receiver=agents._main_notice,
                                  request_notices='decisions')
    binding = Binding(Caller(GATEWAY, MEMBER))
    reference = agents.operate('create', {'runtime': 'claude', 'instruction': 'probe'}, binding).result['agent']
    return root, agents, sent, binding, reference, driver.run


def test_gateway_create_then_wait_returns_the_reply_once_and_pushes_nothing(project) -> None:
    root, agents, sent, binding, reference, run = _member_child(project, running=True)
    thread, out = _wait_in_thread(lambda timeout: agents.operate(
        'wait', {'agent': reference, 'timeout_seconds': timeout}, binding).result)
    _until(lambda: _waiting(swarm_root(root), reference))
    run.events.finished('completed', last_message='PONG-477')
    thread.join(10)
    [waited] = out
    assert waited['timed_out'] is False
    assert waited['last_result']['last_message'] == 'PONG-477'
    assert waited['last_result']['notification'] == 'delivered'
    assert sent == []
    status = agents.operate('status', {'agent': reference}, binding).result
    assert status['last_result']['last_message'] == 'PONG-477'
    assert status['last_result']['notification'] == 'delivered'
    retired = agents.operate('retire', {'agent': reference}, binding).result
    assert retired['last_result']['last_message'] == 'PONG-477'
    assert sent == []
    assert 'waiters' not in _record(swarm_root(root), reference)['executions'][-1]


def test_gateway_without_wait_pushes_once_and_reads_show_the_body(project) -> None:
    root, agents, sent, binding, reference, run = _member_child(project)
    run.events.finished('completed', last_message='PONG-477')
    assert [item[1]['message'] for item in sent] == ['PONG-477']
    for action in ('status', 'wait', 'retire'):
        arguments = {'agent': reference, **({'timeout_seconds': 0} if action == 'wait' else {})}
        result = agents.operate(action, arguments, binding).result
        assert result['last_result']['last_message'] == 'PONG-477'
        assert result['last_result']['notification'] == 'delivered'
    assert len(sent) == 1


def test_gateway_wait_that_timed_out_leaves_the_end_to_the_push(project) -> None:
    root, agents, sent, binding, reference, run = _member_child(project)
    waited = agents.operate('wait', {'agent': reference, 'timeout_seconds': 0.1}, binding).result
    assert waited['timed_out'] is True
    assert 'waiters' not in _record(swarm_root(root), reference)['executions'][-1]
    run.events.finished('completed', last_message='PONG-477')
    assert [item[1]['message'] for item in sent] == ['PONG-477']


# -- Correction 1: the real order on a real host --------------------------------
# A model calls wait seconds after create, so a quick child ends BEFORE the wait
# starts (real host a2195eca: the wait saw 'queueing' and the member got the notice).
# The 446 fixture's member has no terminal record (execution.yml): it is mid-turn.

def _member_turn_ends(root: Path) -> None:
    from graphtraj.configuration.project_configuration import runner_directory
    (runner_directory(root) / 'sessions' / MEMBER / 'execution.yml').write_text(
        'outcome: completed\nterminal_confirmed: true\n', encoding='utf-8')


def _end_in_thread(run, **end) -> threading.Thread:
    thread = threading.Thread(target=lambda: run.events.finished('completed', **end))
    thread.start()
    return thread


def test_gateway_member_waiting_after_its_child_ended_gets_the_reply_once_without_a_push(project) -> None:
    root, agents, sent, binding, reference, run = _member_child(project, running=True)
    ender = _end_in_thread(run, last_message='PONG-477')
    _until(lambda: _record(swarm_root(root), reference)['executions'][-1].get('state') == 'ended')
    waited = agents.operate('wait', {'agent': reference, 'timeout_seconds': 5}, binding).result
    _member_turn_ends(root)
    ender.join(10)
    assert not ender.is_alive()
    assert (waited['last_result']['last_message'], waited['last_result']['notification']) == ('PONG-477', 'delivered')
    assert sent == []
    assert _record(swarm_root(root), reference)['executions'][-1]['notification'] == 'delivered'


def test_gateway_member_that_never_waits_gets_one_push_when_its_turn_ends(project) -> None:
    root, agents, sent, binding, reference, run = _member_child(project, running=True)
    ender = _end_in_thread(run, last_message='PONG-477')
    _until(lambda: _record(swarm_root(root), reference)['executions'][-1].get('state') == 'ended')
    time.sleep(0.3)
    assert sent == []  # held for the member while its turn runs
    _member_turn_ends(root)
    ender.join(10)
    assert [item[1]['message'] for item in sent] == ['PONG-477']
    assert _record(swarm_root(root), reference)['executions'][-1]['notification'] == 'delivered'


# -- A host receiver's root Agent (the claude-native Main shape) ---------------

class Run:
    """A driver that keeps each run so the test ends it."""

    def __init__(self) -> None:
        self.runs: dict = {}

    def prepare(self, runtime: str, caller: Caller) -> dict:
        return {}

    def start(self, run) -> None:
        self.runs[run.agent] = run
        run.events.session('native-' + run.agent)


@pytest.mark.parametrize('hold', [False, True])
def test_host_receiver_create_then_wait_returns_once_and_pushes_nothing(tmp_path: Path, hold: bool) -> None:
    driver, pushed = Run(), []
    control = AgentControl(tmp_path, {'controlled': driver}, hold_notices=hold,
                           event_receiver=lambda notice: pushed.append(notice) or True)
    main = bind(control, Caller('claude-native', None, 'main', 'claude'))
    agent = main({'action': 'create', 'runtime': 'controlled', 'instruction': 'x'}).document['agent']
    thread, out = _wait_in_thread(lambda timeout: main(
        {'action': 'wait', 'agent': agent, 'timeout_seconds': timeout}).document['result'])
    _until(lambda: _waiting(tmp_path, agent))
    driver.runs[agent].events.finished('completed', last_message='PONG-LASTMSG')
    thread.join(10)
    [waited] = out
    assert (waited['last_result']['last_message'], waited['last_result']['notification']) == (
        'PONG-LASTMSG', 'delivered')
    assert pushed == []
    for request in ({'action': 'status', 'agent': agent}, {'action': 'retire', 'agent': agent}):
        assert main(request).document['result']['last_result']['last_message'] == 'PONG-LASTMSG'
    assert pushed == []


@pytest.mark.parametrize('hold', [False, True])
def test_host_receiver_without_wait_pushes_once(tmp_path: Path, hold: bool) -> None:
    driver, pushed = Run(), []
    control = AgentControl(tmp_path, {'controlled': driver}, hold_notices=hold,
                           event_receiver=lambda notice: pushed.append(notice) or True)
    main = bind(control, Caller('claude-native', None, 'main', 'claude'))
    agent = main({'action': 'create', 'runtime': 'controlled', 'instruction': 'x'}).document['agent']
    driver.runs[agent].events.finished('completed', last_message='PONG-LASTMSG')
    assert [notice['body'] for notice in pushed] == ['PONG-LASTMSG']
    waited = main({'action': 'wait', 'agent': agent, 'timeout_seconds': 1}).document['result']
    assert waited['last_result']['last_message'] == 'PONG-LASTMSG'
    assert waited['last_result']['notification'] == 'delivered'
    assert len(pushed) == 1


def test_a_native_parent_waiting_receives_the_reply_in_its_wait_only(tmp_path: Path) -> None:
    driver, notices = Run(), []
    control = AgentControl(tmp_path, {'controlled': driver})
    root = bind(control, Caller('test', None))
    parent = root({'action': 'create', 'runtime': 'controlled', 'instruction': 'parent'}).document['agent']
    parent_run = driver.runs[parent]
    parent_run.events.receive_children(lambda notice: notices.append(notice) or True)
    child = parent_run.call({'action': 'create', 'runtime': 'controlled', 'instruction': 'c'}).document['agent']
    thread, out = _wait_in_thread(lambda timeout: parent_run.call(
        {'action': 'wait', 'agent': child, 'timeout_seconds': timeout}).document['result'])
    _until(lambda: _waiting(tmp_path, child))
    driver.runs[child].events.finished('completed', last_message='body')
    thread.join(10)
    assert out[0]['last_result']['last_message'] == 'body'
    assert notices == []


def test_an_ancestor_waiting_on_a_grandchild_does_not_take_the_parents_reply(tmp_path: Path) -> None:
    driver, notices = Run(), []
    control = AgentControl(tmp_path, {'controlled': driver})
    root = bind(control, Caller('test', None))
    parent = root({'action': 'create', 'runtime': 'controlled', 'instruction': 'parent'}).document['agent']
    parent_run = driver.runs[parent]
    parent_run.events.receive_children(lambda notice: notices.append(notice) or True)
    child = parent_run.call({'action': 'create', 'runtime': 'controlled', 'instruction': 'c'}).document['agent']
    thread, out = _wait_in_thread(lambda timeout: root(
        {'action': 'wait', 'agent': child, 'timeout_seconds': timeout}).document['result'])
    time.sleep(0.2)
    assert not _waiting(tmp_path, child)
    driver.runs[child].events.finished('completed', last_message='body')
    thread.join(10)
    assert out[0]['last_result']['last_message'] == 'body'
    assert [notice['body'] for notice in notices] == ['body']


# -- A reservation whose wait is gone is pushed once ---------------------------

def _reserved(tmp_path: Path, pid: int):
    """End a host receiver's root Agent while a wait of ``pid`` is recorded on it."""
    driver, pushed = Run(), []
    control = AgentControl(tmp_path, {'controlled': driver},
                           event_receiver=lambda notice: pushed.append(notice) or True)
    main = bind(control, Caller('claude-native', None, 'main', 'claude'))
    agent = main({'action': 'create', 'runtime': 'controlled', 'instruction': 'x'}).document['agent']
    with control._locked(agent) as record:
        record['executions'][-1]['waiters'] = {'gone': pid}
    driver.runs[agent].events.finished('completed', last_message='kept')
    return control, main, agent, pushed


def test_a_wait_that_leaves_untaken_releases_its_reservation_to_one_push(tmp_path: Path) -> None:
    control, main, agent, pushed = _reserved(tmp_path, __import__('os').getpid())
    assert _record(tmp_path, agent)['executions'][-1]['notification'] == 'waiting'
    assert pushed == []
    control._release_wait(agent, 'gone')
    assert [notice['body'] for notice in pushed] == ['kept']
    status = main({'action': 'status', 'agent': agent}).document['result']['last_result']
    assert (status['notification'], status['last_message']) == ('delivered', 'kept')
    main({'action': 'status', 'agent': agent})
    assert len(pushed) == 1


def test_a_dead_waiters_reservation_is_pushed_once_on_the_next_read(tmp_path: Path) -> None:
    dead = subprocess.run([sys.executable, '-c', 'import os; print(os.getpid())'],
                          capture_output=True, text=True, check=True)
    control, main, agent, pushed = _reserved(tmp_path, int(dead.stdout))
    # The dead waiter never counted: the end went to the ordinary push at once.
    assert [notice['body'] for notice in pushed] == ['kept']
    main({'action': 'status', 'agent': agent})
    assert len(pushed) == 1


def test_a_reservation_whose_waiter_died_later_is_pushed_once(tmp_path: Path) -> None:
    control, main, agent, pushed = _reserved(tmp_path, __import__('os').getpid())
    dead = subprocess.run([sys.executable, '-c', 'import os; print(os.getpid())'],
                          capture_output=True, text=True, check=True)
    path = tmp_path / 'control' / 'agents' / f'{agent}.json'
    record = json.loads(path.read_text(encoding='utf-8'))
    record['executions'][-1]['waiters'] = {'gone': int(dead.stdout)}
    path.write_text(json.dumps(record), encoding='utf-8')
    status = main({'action': 'status', 'agent': agent}).document['result']['last_result']
    assert [notice['body'] for notice in pushed] == ['kept']
    assert (status['last_message'], len(pushed)) == ('kept', 1)


# -- Race: wait and push decided once under the record lock --------------------

@pytest.mark.parametrize('running', [False, True])
@pytest.mark.parametrize('trial', range(12))
def test_wait_and_push_racing_deliver_the_reply_exactly_once(project, trial: int, running: bool) -> None:
    """Idle member: pushed at once unless its wait was registered first. Mid-turn member
    (correction 1): its wait takes the end whenever it comes, before or after the end;
    a wait that timed out before the end leaves one push at the turn's end."""
    root, agents, sent, binding, reference, run = _member_child(project, running=running)
    rng = random.Random(trial)
    thread, out = _wait_in_thread(lambda timeout: agents.operate(
        'wait', {'agent': reference, 'timeout_seconds': timeout}, binding).result, timeout=0.01 + rng.random() * 0.15)
    time.sleep(rng.random() * 0.15)
    ender = _end_in_thread(run, last_message='RACE')
    thread.join(10)
    if running:
        late = agents.operate('wait', {'agent': reference, 'timeout_seconds': 5}, binding).result
        _member_turn_ends(root)
    ender.join(10)
    assert not ender.is_alive()
    [waited] = out
    final = _record(swarm_root(root), reference)['executions'][-1]
    assert final['notification'] == 'delivered'
    assert 'waiters' not in final and 'push_deferred' not in final
    if running:
        # The member waited again in its turn: that wait or the first one took it; nothing pushed.
        assert sent == []
        assert late['last_result']['last_message'] == 'RACE'
    elif waited['timed_out'] is False and not sent:
        # Handed over in the wait result, never pushed.
        assert waited['last_result']['last_message'] == 'RACE'
    else:
        # Pushed exactly once; the wait (if it saw the end) still shows the body.
        assert [item[1]['message'] for item in sent] == ['RACE']
        if waited['timed_out'] is False:
            assert waited['last_result']['last_message'] == 'RACE'


# -- Correction 2: a holder that dies while it holds a running member's end ----

HOLDER = '''
import sys
from pathlib import Path
from graftling import AgentControl
from graftling.control import ExecutionEvents
from graphtraj.interfaces.agents import GraphTrajAgents, swarm_root
root, agent, execution = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
agents = GraphTrajAgents.__new__(GraphTrajAgents)
agents.root = root
agents.control = AgentControl(swarm_root(root), {}, event_receiver=agents._main_notice)
# The child's owner ends it; the receiver holds the end while the member's turn runs.
ExecutionEvents(agents.control, agent, execution).finished('completed', last_message='LOST-477')
'''


def _holder_dies_holding(root: Path, reference: str, run) -> None:
    """A real separate process ends the child and holds its end; it is then killed."""
    holder = subprocess.Popen([sys.executable, '-c', HOLDER, str(root), reference, run.execution])
    try:
        _until(lambda: _record(swarm_root(root), reference)['executions'][-1].get('push_deferred') is True, 20)
    finally:
        holder.kill()
        holder.wait(10)


def test_an_end_whose_holder_died_is_pushed_once_when_the_members_turn_ends(project) -> None:
    root, agents, sent, binding, reference, run = _member_child(project, running=True)
    _holder_dies_holding(root, reference, run)
    assert sent == []
    _member_turn_ends(root)
    # The member's Worker sweeps its children after writing the terminal record.
    agents.reconcile_children({MEMBER})
    assert [item[1]['message'] for item in sent] == ['LOST-477']
    agents.reconcile_children({MEMBER})
    agents.operate('status', {'agent': reference}, binding)
    assert len(sent) == 1
    final = _record(swarm_root(root), reference)['executions'][-1]
    assert final['notification'] == 'delivered' and 'push_deferred' not in final


def test_a_live_holder_and_the_sweep_send_the_end_once(project) -> None:
    root, agents, sent, binding, reference, run = _member_child(project, running=True)
    ender = _end_in_thread(run, last_message='LIVE-477')
    _until(lambda: _record(swarm_root(root), reference)['executions'][-1].get('push_deferred') is True)
    agents.reconcile_children({MEMBER})  # the holder lives: nothing is taken from it
    assert sent == []
    _member_turn_ends(root)
    ender.join(10)
    agents.reconcile_children({MEMBER})
    assert [item[1]['message'] for item in sent] == ['LIVE-477']
