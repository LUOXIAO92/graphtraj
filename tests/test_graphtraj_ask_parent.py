"""A Task member asks its direct parent through the real Worker's request path."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import threading
import time
from uuid import uuid4

import pytest
import yaml

from graphtraj.configuration.project_configuration import runner_directory
from graphtraj.execution import main_continuity
from graphtraj.execution.runner_status import read_alias_mapping, runtime_caller
from graphtraj.interfaces.gateway import handle_request
from graphtraj.runtimes.codex import finalize
from test_managed_sessions import ManagedProject, launch_document, managed_project, observe  # noqa: F401


def ask(root: Path, alias: str | None, timeout: float, kind: str = 'decision', question: str = 'A or B?') -> dict:
    """Call ask_parent through the gateway every member's agents call enters."""
    arguments = {'action': 'ask_parent', 'kind': kind, 'question': question, 'timeout_seconds': timeout}
    with runtime_caller(runner_directory(root), alias):
        return handle_request({'action': 'execute', 'feature': 'agents', 'arguments': arguments}, cwd=root).document


class Asking:
    """One member's ask_parent running while the test acts as its parent."""

    def __init__(self, root: Path, alias: str, timeout: float = 30, **options: str) -> None:
        """Start the asking call on its own thread."""
        self.answer: dict = {}
        self.thread = threading.Thread(
            target=lambda: self.answer.update(ask(root, alias, timeout, **options)), daemon=True)
        self.thread.start()

    def result(self) -> dict:
        """Return the finished call's document."""
        self.thread.join(20)
        assert not self.thread.is_alive(), 'ask_parent did not return'
        return self.answer


def pending(call, alias: str, count: int = 1) -> list[dict]:
    """Wait until the parent can read ``count`` requests of ``alias``."""
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        requests = call('agents', ['requests', {'agent': alias}, 'main-a'])['result']['requests']
        if len(requests) == count:
            return requests
        time.sleep(0.1)
    raise AssertionError(f'{alias} did not show {count} requests: {requests}')


def launched(call) -> tuple[str, dict]:
    """Launch one member that keeps its turn running."""
    member = call('launch', launch_document('hold'))['tasks'][0]
    observe(call, member['alias'], 'running')
    return member['alias'], member


@pytest.mark.parametrize('kind', ['decision', 'resources'])
def test_a_members_question_is_answered_by_its_parent(managed_project: ManagedProject, kind: str) -> None:
    """The parent's wait ends early, it reads the request and its one answer reaches the member."""
    root, _, call, _ = managed_project
    alias, _ = launched(call)
    runner = root / '.graphtraj/runner'
    mapping = read_alias_mapping(runner, alias)[0]
    question = f'{kind} question?'
    asking = Asking(root, alias, kind=kind, question=question)

    request, = pending(call, alias)
    assert request['method'] == 'agents/decision' and request['params'] == {'kind': kind, 'question': question}
    assert (request['session'], request['execution_id']) == (mapping['session'], mapping['execution_id'])
    assert call('agents', ['wait', {'agent': alias, 'timeout_seconds': 10}, 'main-a'])['result']['timed_out'] is False
    assert call('status', [alias])['aliases'][0]['pending_requests'] == 1

    invalid = call('agents', ['reply', {'agent': alias, 'request': request, 'response': {'decision': 'accept'}}, 'main-a'],
                   returncode=1)
    assert invalid['error']['code'] == 'invalid-input'
    assert pending(call, alias) == [request]

    reply = call('agents', ['reply', {'agent': alias, 'request': request, 'response': {'answer': 'Use B.'}}, 'main-a'])
    assert reply['result']['reply_status'] == 'answered' and reply['result']['answer'] == 'Use B.'

    document = asking.result()
    assert document['action'] == 'ask_parent' and document['agent'] == mapping['agent']
    assert document['result']['answer'] == 'Use B.' and document['result']['timed_out'] is False
    assert document['result']['request']['params'] == {'kind': kind, 'question': question}
    assert call('agents', ['requests', {'agent': alias}, 'main-a'])['result']['requests'] == []
    assert 'pending_requests' not in call('status', [alias])['aliases'][0]

    repeat = call('agents', ['reply', {'agent': alias, 'request': request, 'response': {'answer': 'Other.'}}, 'main-a'])
    assert repeat['result']['duplicate'] is True and repeat['result']['answer'] == 'Use B.'


def test_an_answer_to_a_resources_request_grants_nothing(managed_project: ManagedProject) -> None:
    """Budget, Round, Worldline and the member's permissions are unchanged by an answer."""
    root, _, call, _ = managed_project
    alias, _ = launched(call)
    runner = root / '.graphtraj/runner'
    records = [root / '.graphtraj/state/worldline.jsonl', runner / 'sessions' / alias / 'launch.yml',
               *sorted((root / '.graphtraj/state/tasks').rglob('*.yml'))]
    before = {path: path.read_bytes() for path in records if path.is_file()}
    mapping = read_alias_mapping(runner, alias)[0]

    asking = Asking(root, alias, kind='resources', question='Two more hours?')
    request, = pending(call, alias)
    call('agents', ['reply', {'agent': alias, 'request': request, 'response': {'answer': 'Yes, take them.'}}, 'main-a'])
    assert asking.result()['result']['answer'] == 'Yes, take them.'

    assert {path: path.read_bytes() for path in before} == before
    after = read_alias_mapping(runner, alias)[0]
    assert {name: after.get(name) for name in mapping} == mapping
    assert observe(call, alias, 'running')['execution_id'] == mapping['execution_id']


def test_no_answer_in_time_is_an_explicit_no_answer_and_stays_pending(managed_project: ManagedProject) -> None:
    """A timeout approves nothing; asking the same again continues the same request."""
    root, _, call, _ = managed_project
    alias, _ = launched(call)
    first = ask(root, alias, 0.2)
    assert first['result']['answer'] is None and first['result']['timed_out'] is True
    request, = pending(call, alias)
    assert request['request_token'] == first['result']['request']['request_token']

    again = Asking(root, alias)
    time.sleep(0.3)
    assert pending(call, alias) == [request]
    call('agents', ['reply', {'agent': alias, 'request': request, 'response': {'answer': 'Late.'}}, 'main-a'])
    assert again.result()['result']['answer'] == 'Late.'
    assert ask(root, alias, 0.2)['result']['answer'] == 'Late.'


def test_a_caller_without_a_reference_or_execution_is_refused(managed_project: ManagedProject) -> None:
    """Main has nothing to ask; an unknown caller and an ended execution are refused too."""
    root, _, call, _ = managed_project
    alias, _ = launched(call)
    main = call('agents', ['ask_parent', {'kind': 'decision', 'question': '?', 'timeout_seconds': 1}, 'main-a'],
                returncode=1)
    assert main['error']['code'] == 'authority-denied'

    from agent_swarm import Binding, Caller
    from graphtraj.interfaces.agents import GraphTrajAgents

    unknown = Binding(Caller('graphtraj-gateway', 'no-such-member'))
    with pytest.raises(Exception) as refused:
        GraphTrajAgents(root).operate('ask_parent', {'kind': 'decision', 'question': '?', 'timeout_seconds': 1}, unknown)
    assert refused.value.code == 'authority-denied'

    call('interrupt', [alias])
    observe(call, alias, 'idle', 'interrupted')
    wait_for(lambda: call('status', [alias])['aliases'][0]['state'] == 'standby')
    assert ask(root, alias, 1)['error']['code'] == 'not-running'


def test_a_member_cannot_answer_its_own_question(managed_project: ManagedProject) -> None:
    """Only the direct parent answers; the member's own reply leaves the request pending."""
    from agent_swarm import Binding, Caller
    from graphtraj.interfaces.agents import GraphTrajAgents

    root, _, call, _ = managed_project
    alias, _ = launched(call)
    asking = Asking(root, alias)
    request, = pending(call, alias)
    arguments = {'agent': alias, 'request': request, 'response': {'answer': 'Me.'}}
    with runtime_caller(runner_directory(root), alias), pytest.raises(Exception) as refused:
        GraphTrajAgents(root).operate('reply', arguments, Binding(Caller('graphtraj-gateway', alias)))
    assert refused.value.code == 'authority-denied'
    assert pending(call, alias) == [request]
    call('agents', ['reply', {**arguments, 'response': {'answer': 'Parent.'}}, 'main-a'])
    assert asking.result()['result']['answer'] == 'Parent.'


def test_the_execution_ending_withdraws_the_request(managed_project: ManagedProject) -> None:
    """The asking call fails with stale-execution rather than waiting out its timeout."""
    root, _, call, _ = managed_project
    alias, _ = launched(call)
    asking = Asking(root, alias)
    pending(call, alias)
    call('interrupt', [alias])
    observe(call, alias, 'idle', 'interrupted')
    assert asking.result()['error']['code'] == 'stale-execution'


def notices(root: Path, alias: str) -> list[dict]:
    """Return the member's retained parent notices."""
    path = root / '.graphtraj/runner/sessions' / alias / 'parent-notices.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def wait_for(condition) -> None:
    """Wait for an asynchronous delivery to be recorded."""
    deadline = time.monotonic() + 15
    while not condition():
        assert time.monotonic() < deadline, 'not delivered in time'
        time.sleep(0.1)


def test_a_child_members_notice_reaches_its_actual_parent_once(managed_project: ManagedProject) -> None:
    """A parent member gets one notice naming the method, never the question."""
    root, _, call, _ = managed_project
    parent = call('launch', launch_document('hold', 'first-probe'))['tasks'][0]['alias']
    child = call('launch', launch_document('hold', 'second-probe'))['tasks'][0]['alias']
    observe(call, parent, 'running')
    observe(call, child, 'running')
    # The Runner's record of the child's real parent is what the notice follows.
    mapping_file = root / '.graphtraj/runner/sessions' / child / 'mapping.yml'
    mapping = yaml.safe_load(mapping_file.read_text())
    mapping['parent'] = parent
    mapping_file.write_text(yaml.safe_dump(mapping))

    asking = Asking(root, child, timeout=15, question='Secret option?')
    wait_for(lambda: notices(root, child))
    time.sleep(0.5)
    record, = notices(root, child)
    assert record['delivery'] == 'received' and record['parent'] == parent
    assert record['identity']['method'] == 'agents/decision'
    assert 'Secret option' not in json.dumps(record)
    assert 'waits for your reply' in json.loads(record['notice'])['message']

    second = ask(root, child, 0.2, question='Secret option?')
    assert second['result']['request']['request_token'] == record['identity']['request_id']
    assert len(notices(root, child)) == 1
    call('interrupt', [child])
    assert asking.result()['error']['code'] == 'stale-execution'


def test_a_root_members_notice_reaches_the_queued_main_once(managed_project: ManagedProject) -> None:
    """A Claude Main gets the notice in its queue, keyed by execution and request."""
    root, _, call, _ = managed_project
    alias, _ = launched(call)
    runner = root / '.graphtraj/runner'
    session = str(uuid4())
    mapping_file = runner / 'sessions' / alias / 'mapping.yml'
    mapping = yaml.safe_load(mapping_file.read_text())
    connection = {'runtime': 'claude', 'session': session, 'runner': str(runner)}
    mapping['parent_connection'] = connection
    mapping_file.write_text(yaml.safe_dump(mapping))

    asking = Asking(root, alias, timeout=15, question='Secret option?')
    queued: list = []
    wait_for(lambda: queued.extend(main_continuity.claim_notices(runner, 'claude', session)) or queued)
    notice, = queued
    assert notice['event']['alias'] == alias and notice['event']['event'] == 'agents/decision'
    assert 'Secret option' not in json.dumps(notice)
    request, = pending(call, alias)
    assert notice['id'].endswith(request['request_token'])
    call('interrupt', [alias])
    assert asking.result()['error']['code'] == 'stale-execution'


def test_main_is_kept_going_by_a_root_members_unanswered_question(managed_project: ManagedProject) -> None:
    """Main's Stop check names the pending request by its token, also after the ask timed out."""
    root, _, call, _ = managed_project
    alias, _ = launched(call)
    runner = root / '.graphtraj/runner'
    connection = {'runtime': 'codex', 'session': 'main-native', 'codex_home': str(root)}
    mapping_file = runner / 'sessions' / alias / 'mapping.yml'
    mapping = yaml.safe_load(mapping_file.read_text())
    mapping['parent_connection'] = connection
    mapping_file.write_text(yaml.safe_dump(mapping))

    first = ask(root, alias, 0.2, question='Secret option?')
    assert first['result']['timed_out'] is True
    token = first['result']['request']['request_token']

    result = asyncio.run(finalize._owned_request_result({'cwd': str(root), 'connection': connection}))
    output = json.loads(result['output'])
    assert result['decided_before_fork'] is True and output['status'] == 'actionable'
    assert f'{alias} asks Main to answer agents/decision request {token}' in output['reason']
    assert 'requests' in output['reason'] and 'reply' in output['reason']
    assert 'native' not in output['reason'] and 'None' not in output['reason']
    assert 'Secret option' not in output['reason']

    request, = pending(call, alias)
    call('agents', ['reply', {'agent': alias, 'request': request, 'response': {'answer': 'Done.'}}, 'main-a'])
    assert asyncio.run(finalize._owned_request_result({'cwd': str(root), 'connection': connection})) is None
