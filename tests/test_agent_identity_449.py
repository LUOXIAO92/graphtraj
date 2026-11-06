"""Task 449: notices, task_sessions and swarm results name the Agent and execution they concern."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from graftling import AgentControl, Binding, Caller
from graphtraj.execution import runner_control
from graphtraj.execution.runner_status import StatusResponse
from graphtraj.execution.task_agents import TASK_HOST
from graphtraj.interfaces.agents import GraphTrajAgents, _list_agent_children, swarm_root
from test_member_child_end_notice_446 import Driver
from test_result_submission import result_project

MEMBER = 'research@x1'
GATEWAY = 'graphtraj-gateway'


@pytest.fixture
def member(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A Task member with a core record and GraphTraj's agents backend; sends are recorded."""
    root = tmp_path / 'project'
    root.mkdir()
    result_project(root)
    AgentControl(swarm_root(root), {'claude': Driver({'alias': MEMBER})}).create(
        'claude', 'lead', Binding(Caller(TASK_HOST, None)), name=MEMBER)
    agents = GraphTrajAgents.__new__(GraphTrajAgents)
    agents.root = root
    driver = Driver({})
    agents.control = AgentControl(swarm_root(root), {'claude': driver}, event_receiver=agents._main_notice,
                                  request_notices='decisions')
    sent: list = []

    def send(alias, message, directory, mapping, caused, cwd, **options):
        sent.append((alias, json.loads(message)))
        return {'session': mapping['session'], 'execution_id': 'x'}

    monkeypatch.setattr(runner_control, '_send_session', send)
    monkeypatch.setattr('graphtraj.execution.runner_process.OPERATION_TIMEOUT_SECONDS', 0.0)
    return agents, driver, sent


def test_each_end_notice_of_one_child_names_its_own_execution_once(member) -> None:
    """create, then send: two executions of one child, two notices, each naming its execution."""
    agents, driver, sent = member
    binding = Binding(Caller(GATEWAY, MEMBER))
    created = agents.operate('create', {'runtime': 'claude', 'instruction': 'one'}, binding)
    reference = created.result['agent']
    driver.run.events.session('native-1')
    driver.run.events.finished('completed', last_message='first')
    first = agents.operate('status', {'agent': reference}, binding).result['last_result']

    resent = agents.operate('send', {'agent': reference, 'message': 'two'}, binding)
    assert resent.execution != first['id']
    driver.run.events.finished('completed', last_message='second')
    driver.run.events.finished('completed', last_message='second')  # A repeated report adds nothing.
    second = agents.operate('wait', {'agent': reference, 'timeout_seconds': 0}, binding).result['last_result']

    assert [notice for _, notice in sent] == [
        {'source': 'graphtraj', 'alias': reference, 'event': 'completed', 'message': 'first',
         'execution': first['id']},
        {'source': 'graphtraj', 'alias': reference, 'event': 'completed', 'message': 'second',
         'execution': second['id']},
    ]
    assert first['id'] == created.execution and second['id'] == resent.execution
    assert {alias for alias, _ in sent} == {MEMBER}


def test_a_runner_parent_notice_names_the_reported_execution(tmp_path: Path, monkeypatch) -> None:
    """A Task member's end notice and its retained receipt carry ``execution``."""
    directory = tmp_path / 'runner' / 'sessions' / 'child@x1'
    directory.mkdir(parents=True)
    # A root member with no recorded parent: the notice is built and recorded, not sent.
    monkeypatch.setattr(runner_control, 'read_alias_mapping', lambda runner, alias: (
        {'alias': alias, 'session': 's', 'execution_id': 'e7'}, runner / 'sessions' / alias))
    identity = {'type': 'completed', 'session': 's', 'execution_id': 'e7'}
    retained = runner_control.retain_parent_receipt(directory, 'body', identity)
    assert json.loads(retained['notice']) == {'source': 'graphtraj', 'alias': 'child@x1',
                                              'event': 'completed', 'message': 'body', 'execution': 'e7'}
    delivered = runner_control.notify_direct_parent(directory, 'body', identity)
    assert json.loads(delivered['notice'])['execution'] == 'e7'
    # A notice whose producer names no execution keeps the four fields.
    plain = runner_control.notify_direct_parent(directory, 'body', {'type': 'completed'})
    assert set(json.loads(plain['notice'])) == {'source', 'alias', 'event', 'message'}


def test_push_consumers_accept_the_execution_field() -> None:
    """The Codex Main event check, its notice recognizer and the local receiver keep working."""
    from graphtraj.runtimes.codex.finalize import _member_notice
    from graphtraj.runtimes.codex.host_events import send_event
    from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError

    event = {'source': 'graphtraj', 'alias': 'a', 'event': 'completed', 'message': 'm', 'execution': 'e1'}
    for payload in (event, {key: value for key, value in event.items() if key != 'execution'}):
        assert _member_notice({'type': 'function_call_output', 'name': 'graphtraj',
                               'output': json.dumps(payload)})
        # Past the event check, only the (absent) connection is refused.
        with pytest.raises(RuntimeAdapterError, match='connection'):
            send_event({}, payload)
    for bad in ({**event, 'execution': ''}, {**event, 'extra': 'x'}):
        with pytest.raises(RuntimeAdapterError, match='Invalid parent event'):
            send_event({}, bad)
    assert not _member_notice({'type': 'function_call_output', 'name': 'graphtraj',
                               'output': json.dumps({**event, 'extra': 'x'})})


def test_a_members_task_sessions_node_lists_its_agents_tool_children(member) -> None:
    agents, driver, sent = member
    binding = Binding(Caller(GATEWAY, MEMBER))
    references = sorted(agents.operate('create', {'runtime': 'claude', 'instruction': name}, binding).result['agent']
                        for name in ('one', 'two'))
    tree = {'agents': [{'alias': MEMBER, 'parent': None, 'children': ['engineer@x1']},
                       {'alias': 'engineer@x1', 'parent': MEMBER, 'children': []}]}
    view = agents._hierarchy_view(binding, lambda root, **options: StatusResponse(document=tree, succeeded=True, errors=()))
    assert sorted(node['agent'] for node in view.result['agents']) == references
    assert all(node['parent'] == MEMBER for node in view.result['agents'])
    nodes = {node['alias']: node for node in view.result['task_sessions']['agents']}
    assert nodes[MEMBER]['children'] == ['engineer@x1', *references]
    assert nodes['engineer@x1']['children'] == []


def test_listing_agent_children_is_idempotent_and_ignores_unrelated_nodes() -> None:
    sessions = {'agents': [{'alias': 'm@x1', 'children': ['agent-b']}]}
    agents = {'agents': [{'agent': 'agent-b', 'parent': 'm@x1', 'children': [
        {'agent': 'agent-c', 'parent': 'agent-b', 'children': []}]},
        {'agent': 'agent-a', 'parent': 'm@x1', 'children': []},
        {'agent': 'agent-z', 'parent': None, 'children': []}]}
    _list_agent_children(sessions, agents)
    assert sessions['agents'][0]['children'] == ['agent-b', 'agent-a']


def test_a_launched_swarm_result_names_the_members_agent(
    installed_commands, temporary_git_repository, fake_codex, tmp_path: Path,
) -> None:
    """``agent`` is the member's core reference; status and retire accept it."""
    from conftest import run_process
    from runner_fixtures import configure_harness
    from test_session_alias_control import _register_ready_task

    harness_root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path)
    _register_ready_task(installed_commands, harness_root)
    batch = harness_root / 'batch.yml'
    batch.write_text(yaml.safe_dump({'tasks': [
        {'task_id': '76', 'task_name': 'session-alias-control', 'role': 'team-leader'}]}))
    launched = run_process([str(installed_commands.runner), '--swarm-input', str(batch)],
                           cwd=harness_root, env=environment, timeout=15)
    assert launched.returncode == 0, launched.stdout + launched.stderr
    task = yaml.safe_load(launched.stdout)['tasks'][0]
    assert task['launch_status'] == 'launched'
    mapping = yaml.safe_load(
        (harness_root / '.graphtraj/runner/sessions' / task['alias'] / 'mapping.yml').read_text())
    assert task['agent'] == mapping['agent'] and task['agent'].startswith('agent-')
    agents = GraphTrajAgents.__new__(GraphTrajAgents)
    agents.root = harness_root
    assert agents._member_alias(task['agent']) == task['alias']
