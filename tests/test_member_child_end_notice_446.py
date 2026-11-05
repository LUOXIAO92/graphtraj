"""Task 446: a Task member's agents-tool child end reaches the member under section 4's rules."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from graftling import AgentControl, Binding, Caller
from graphtraj.configuration.project_configuration import runner_directory
from graphtraj.execution import main_continuity as mc
from graphtraj.execution import runner_control
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.task_agents import TASK_HOST
from graphtraj.interfaces.agents import GraphTrajAgents, swarm_root
from test_result_submission import result_project

MEMBER = 'research@x1'


class Driver:
    """A driver that starts nothing native and retains the bound execution."""

    def __init__(self, settings: dict) -> None:
        self.settings, self.run = settings, None

    def prepare(self, runtime: str, caller: Caller, **options: object) -> dict:
        return dict(self.settings)

    def start(self, run) -> None:
        self.run = run

    def interrupt(self, run) -> bool:
        return True


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A Runner mapping for the member, its core record under TASK_HOST, and the recorded send path."""
    root = tmp_path / 'project'
    root.mkdir()
    result_project(root)
    member_driver = Driver({'alias': MEMBER})
    member = AgentControl(swarm_root(root), {'claude': member_driver}).create(
        'claude', 'lead', Binding(Caller(TASK_HOST, None)), name=MEMBER).result['agent']
    agents = GraphTrajAgents.__new__(GraphTrajAgents)
    agents.root = root
    sent: list = []

    def send(alias, message, directory, mapping, caused, cwd, **options):
        sent.append((alias, json.loads(message), directory.name, mapping['alias'], options))
        if send.failure is not None:
            raise send.failure
        return {'session': mapping['session'], 'execution_id': 'x'}

    send.failure = None
    monkeypatch.setattr(runner_control, '_send_session', send)
    monkeypatch.setattr('graphtraj.execution.runner_process.OPERATION_TIMEOUT_SECONDS', 0.0)

    def child(outcome: str, *, members: int = 0, repeat: bool = False, **end: object) -> dict:
        """Create the member's child through a control bound to GraphTraj's receiver and end it.

        ``members`` grandchildren the child creates stay running; ``repeat``
        reports the same end a second time.
        """
        driver = Driver({})
        control = AgentControl(swarm_root(root), {'claude': driver}, event_receiver=agents._main_notice,
                               request_notices='decisions')
        binding = Binding(Caller('claude', member))
        reference = control.create('claude', 'probe', binding).result['agent']
        run = driver.run
        for _ in range(members):
            control.create('claude', 'grandchild', Binding(Caller('claude', reference)))
        run.events.finished(outcome, **end)
        if repeat:
            run.events.finished(outcome, **end)
        status = control.operate('status', {'agent': reference}, binding).result
        waited = control.operate('wait', {'agent': reference, 'timeout_seconds': 0}, binding).result
        return status | {'agent': reference, 'waited': waited}

    return root, member, agents, sent, send, child


@pytest.mark.parametrize(('outcome', 'end', 'text'), [
    ('failed', {'error': {'code': 'X', 'message': 'broke'}}, 'broke'),
    ('interrupted', {}, 'interrupted'),
])
def test_a_member_child_failed_or_interrupted_end_reaches_the_member_once(project, outcome, end, text) -> None:
    root, member, agents, sent, send, child = project
    status = child(outcome, **end)
    assert sent == [(MEMBER, {'source': 'graphtraj', 'alias': status['agent'], 'event': outcome,
                              'message': text}, MEMBER, MEMBER, {'system_notice': True})]
    assert status['last_result']['notification'] == 'delivered'


def test_a_member_child_end_keeps_its_last_message_as_the_notice(project) -> None:
    *_, sent, send, child = project
    child('failed', last_message='partial work', error={'code': 'X', 'message': 'broke'})
    assert sent[0][1]['message'] == 'partial work'


def test_a_member_child_completed_round_without_members_brings_its_final_answer_once(project) -> None:
    *_, sent, send, child = project
    status = child('completed', last_message='the final answer')
    assert sent == [(MEMBER, {'source': 'graphtraj', 'alias': status['agent'], 'event': 'completed',
                              'message': 'the final answer'}, MEMBER, MEMBER, {'system_notice': True})]
    assert status['last_result']['notification'] == 'delivered'
    # Delivered once: the member's own status and wait do not repeat the body.
    assert status['last_result']['last_message'] is None
    assert status['waited']['last_result']['last_message'] is None


def test_a_member_child_completed_round_without_a_body_names_the_outcome(project) -> None:
    *_, sent, send, child = project
    child('completed')
    assert [item[1]['message'] for item in sent] == ['completed']


def test_a_completed_round_while_the_child_has_running_members_is_recorded_not_pushed(project) -> None:
    *_, sent, send, child = project
    status = child('completed', members=1, last_message='round one')
    assert sent == []
    assert 'notification' not in status['last_result']
    assert status['last_result']['outcome'] == 'completed'
    assert status['last_result']['last_message'] == 'round one'


@pytest.mark.parametrize(('outcome', 'end'), [
    ('failed', {'error': {'code': 'X', 'message': 'broke'}}), ('interrupted', {}),
])
def test_a_failed_or_interrupted_end_notifies_even_with_running_members(project, outcome, end) -> None:
    *_, sent, send, child = project
    status = child(outcome, members=1, **end)
    assert [item[1]['event'] for item in sent] == [outcome]
    assert status['last_result']['notification'] == 'delivered'


@pytest.mark.parametrize('outcome', ['completed', 'failed', 'interrupted'])
def test_a_repeated_end_is_not_sent_again(project, outcome) -> None:
    *_, sent, send, child = project
    status = child(outcome, repeat=True, last_message='once')
    assert len(sent) == 1
    assert status['last_result']['notification'] == 'delivered'


def test_an_undelivered_member_notice_is_unavailable_and_readable(project) -> None:
    *_, sent, send, child = project
    send.failure = RunnerError('operation-failed', 'The parent Session input lock is busy; retry this notice.')
    status = child('failed', error={'code': 'X', 'message': 'broke'})
    assert len(sent) == 1
    assert status['last_result']['notification'] == 'unavailable'
    assert status['last_result']['outcome'] == 'failed'


def test_a_busy_member_input_is_retried_within_the_operation_window(project, monkeypatch) -> None:
    *_, sent, send, child = project
    monkeypatch.setattr('graphtraj.execution.runner_process.OPERATION_TIMEOUT_SECONDS', 5.0)
    monkeypatch.setattr('time.sleep', lambda seconds: setattr(send, 'failure', None))
    send.failure = RunnerError('operation-failed', 'The parent Session input lock is busy; retry this notice.')
    status = child('interrupted')
    assert len(sent) == 2
    assert status['last_result']['notification'] == 'delivered'


def test_a_non_member_parent_and_the_main_path_are_unchanged(project) -> None:
    root, member, agents, sent, send, child = project
    notice = {'parent': 'agent-other', 'agent': 'agent-probe', 'execution': 'e1', 'session': 's',
              'outcome': 'failed', 'body': None, 'error': {'code': 'X', 'message': 'broke'},
              'creator': {'host': 'claude-native', 'agent': None, 'session': 'main'}}
    assert agents._main_notice(notice) is False
    runner = runner_directory(root)
    mc.claim_main(runner, {'runtime': 'claude', 'session': 'main', 'runner': str(runner)}, 'claude:first-control')
    assert agents._main_notice({**notice, 'parent': None}) == 'queued'
    assert sent == []
