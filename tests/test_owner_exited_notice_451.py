"""Task 451: an end found by reconciliation (owner-exited) reaches the parent once."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import graftling
from graftling import AgentControl, Caller
from test_agent_control import ScriptedDriver

MESSAGE = 'The process owning this execution exited before reporting its end.'


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / 'data-root'


def call(control, caller, **request):
    result = graftling.bind(control, caller)(request)
    return result.document, result.failed


def dead_pid() -> int:
    """A real process that has already exited."""
    process = subprocess.Popen([sys.executable, '-c', 'pass'])
    process.wait()
    return process.pid


def lose_owner(root: Path, agent: str) -> str:
    """Point the running execution at a dead owner and Runtime; return its ID."""
    path = root / 'control/agents' / f'{agent}.json'
    record = json.loads(path.read_text())
    record['executions'][-1]['process'].update(worker_pid=dead_pid(), runtime_pid=dead_pid())
    path.write_text(json.dumps(record))
    return record['executions'][-1]['id']


def parent_and_child(root: Path) -> tuple[Caller, str]:
    """A lead Agent and its running child, created by a control with no receiver."""
    control = AgentControl(root, {'scripted': ScriptedDriver()})
    lead, _ = call(control, Caller('test-host', None), action='create', runtime='scripted', instruction='lead')
    caller = Caller('test-host', lead['agent'])
    child, _ = call(control, caller, action='create', runtime='scripted', instruction='work')
    return caller, child['agent']


def test_a_receiver_bearing_control_delivers_a_reconciled_end_once(root: Path) -> None:
    caller, child = parent_and_child(root)
    execution = lose_owner(root, child)
    notices, unlocked = [], []

    def receiver(notice: dict) -> bool:
        # The record lock is released: another control can take it now.
        reader = threading.Thread(target=AgentControl(root, {}).unconfirmed_ends, args=(child,), daemon=True)
        reader.start()
        reader.join(5)
        unlocked.append(not reader.is_alive())
        notices.append(notice)
        return True

    control = AgentControl(root, {'scripted': ScriptedDriver()}, event_receiver=receiver)
    status, _ = call(control, caller, action='status', agent=child)
    assert status['result']['state'] == 'standby'
    assert len(notices) == 1 and unlocked == [True]
    notice = notices[0]
    assert (notice['agent'], notice['parent'], notice['execution'], notice['outcome']) == (
        child, caller.agent, execution, 'failed')
    assert notice['body'] == MESSAGE

    again, _ = call(control, caller, action='status', agent=child)
    waited, _ = call(control, caller, action='wait', agent=child, timeout_seconds=1)
    assert len(notices) == 1
    last = again['result']['last_result']
    assert (last['id'], last['error']['code'], last['notification']) == (execution, 'owner-exited', 'delivered')
    assert waited['result']['last_result']['notification'] == 'delivered'


def test_a_receiverless_control_reconciling_first_loses_nothing(root: Path) -> None:
    caller, child = parent_and_child(root)
    execution = lose_owner(root, child)

    first, _ = call(AgentControl(root, {'scripted': ScriptedDriver()}), caller, action='status', agent=child)
    assert first['result']['last_result']['notification'] == 'held'

    notices = []
    control = AgentControl(root, {'scripted': ScriptedDriver()},
                           event_receiver=lambda notice: notices.append(notice) or True)
    for _ in range(3):
        call(control, caller, action='status', agent=child)
    assert [(notice['execution'], notice['outcome']) for notice in notices] == [(execution, 'failed')]


def test_a_root_agents_reconciled_end_reaches_its_host_receiver_with_the_error(root: Path) -> None:
    main = Caller('test-host', None)
    created, _ = call(AgentControl(root, {'scripted': ScriptedDriver()}), main,
                      action='create', runtime='scripted', instruction='go')
    execution = lose_owner(root, created['agent'])
    notices = []
    control = AgentControl(root, {'scripted': ScriptedDriver()},
                           event_receiver=lambda notice: notices.append(notice) or 'queued')
    found, _ = call(control, main, action='status', agent=created['agent'])
    # The call that found it reports it on its way; the next read shows it settled.
    assert found['result']['last_result']['notification'] == 'queueing'
    assert len(notices) == 1 and notices[0]['execution'] == execution
    assert notices[0]['error'] == {'code': 'owner-exited', 'message': MESSAGE}
    status, _ = call(control, main, action='status', agent=created['agent'])
    assert status['result']['last_result']['notification'] == 'queued' and len(notices) == 1


def test_hold_notices_still_holds_a_reconciled_end_without_calling_a_receiver(root: Path) -> None:
    caller, child = parent_and_child(root)
    lose_owner(root, child)
    notices = []
    control = AgentControl(root, {'scripted': ScriptedDriver()}, hold_notices=True,
                           event_receiver=lambda notice: notices.append(notice) or True)
    status, _ = call(control, caller, action='status', agent=child)
    assert notices == [] and status['result']['last_result']['notification'] == 'held'


# -- GraphTraj: a running Task member's sweep ---------------------------------

MEMBER = 'research@x1'


class Driver:
    """A driver that starts nothing native; its execution stays running."""

    def __init__(self, settings: dict) -> None:
        self.settings = settings

    def prepare(self, runtime: str, caller: Caller, **options: object) -> dict:
        return dict(self.settings)

    def start(self, run) -> None:
        pass

    def interrupt(self, run) -> bool:
        return True


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A Runner project whose member MEMBER has a core record, and the recorded notice path."""
    from graftling import Binding
    from graphtraj.execution import runner_control
    from graphtraj.execution.task_agents import TASK_HOST
    from graphtraj.interfaces.agents import GraphTrajAgents, swarm_root
    from test_result_submission import result_project

    root = tmp_path / 'project'
    root.mkdir()
    result_project(root)
    member = AgentControl(swarm_root(root), {'claude': Driver({'alias': MEMBER})}).create(
        'claude', 'lead', Binding(Caller(TASK_HOST, None)), name=MEMBER).result['agent']
    sent: list = []

    def send(alias, message, directory, mapping, caused, cwd, **options):
        sent.append((alias, json.loads(message), options))
        return {'session': mapping['session'], 'execution_id': 'x'}

    monkeypatch.setattr(runner_control, '_send_session', send)
    monkeypatch.setattr('graphtraj.execution.runner_process.OPERATION_TIMEOUT_SECONDS', 0.0)

    def backend(project_root: Path) -> GraphTrajAgents:
        """GraphTraj's backend with its receiver, as 446's tests build it (no Runtime drivers)."""
        agents = GraphTrajAgents.__new__(GraphTrajAgents)
        agents.root = project_root
        agents.control = AgentControl(swarm_root(project_root), {}, event_receiver=agents._main_notice,
                                      request_notices='decisions')
        return agents

    monkeypatch.setattr('graphtraj.interfaces.agents.GraphTrajAgents', backend)
    return root, member, sent


def wait_for(condition, seconds: float = 5.0) -> None:
    import time

    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.02)


def test_a_running_members_sweep_brings_a_lost_child_end_once(project) -> None:
    import time

    from graftling import Binding
    from graphtraj.execution.task_agents import watch_member_children
    from graphtraj.interfaces.agents import swarm_root

    root, member, sent = project
    # The member's agents call binds its Runner alias, so the child records it as parent.
    child = AgentControl(swarm_root(root), {'claude': Driver({})}).create(
        'claude', 'probe', Binding(Caller('graphtraj-gateway', MEMBER))).result['agent']
    execution = lose_owner(swarm_root(root), child)

    close = watch_member_children(root, MEMBER, member, interval=0.05)
    try:
        wait_for(lambda: sent)
        time.sleep(0.3)  # several more sweeps: none repeats it
    finally:
        close()
    assert sent == [(MEMBER, {'source': 'graphtraj', 'alias': child, 'event': 'failed',
                              'message': MESSAGE, 'execution': execution}, {'system_notice': True})]
    record = json.loads((swarm_root(root) / 'control/agents' / f'{child}.json').read_text())
    assert record['executions'][-1]['notification'] == 'delivered'


def test_a_task_members_own_lost_end_is_left_to_the_runner(project) -> None:
    from graftling import Binding
    from graphtraj.execution.task_agents import TASK_HOST
    from graphtraj.interfaces import agents
    from graphtraj.interfaces.agents import swarm_root

    root, member, sent = project
    # A Task member under MEMBER: the Runner, not the core, reports its end to MEMBER.
    sub = AgentControl(swarm_root(root), {'claude': Driver({'alias': 'sub@x1'})}).create(
        'claude', 'work', Binding(Caller(TASK_HOST, member)), name='sub@x1').result['agent']
    lose_owner(swarm_root(root), sub)
    agents.GraphTrajAgents(root).reconcile_children({member})
    assert sent == []
    record = json.loads((swarm_root(root) / 'control/agents' / f'{sub}.json').read_text())
    assert record['executions'][-1]['notification'] == 'unavailable'
