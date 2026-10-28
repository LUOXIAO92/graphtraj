"""Task 373: every pending request of one execution reaches a pull-only Main once."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from graphtraj.configuration.project_configuration import runner_directory
from graphtraj.execution import main_continuity as mc
from graphtraj.execution import runner_control


SESSION = str(uuid4())
EXECUTION = 'e-leader'


@pytest.fixture
def leader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """A Task Leader whose direct parent is an external Claude Main."""
    runner = runner_directory(tmp_path)
    directory = runner / 'sessions' / 'leader'
    directory.mkdir(parents=True)
    mapping = {'alias': 'leader', 'parent': None,
               'parent_connection': {'runtime': 'claude', 'session': SESSION}}
    monkeypatch.setattr(runner_control, 'read_alias_mapping', lambda *_: (mapping, directory))
    return runner, directory


def _request(request_id: str) -> dict:
    return {'session': 's-leader', 'execution_id': EXECUTION, 'request_id': request_id,
            'request_token': uuid4().hex, 'method': 'claude/can_use_tool', 'params': {}}


def _deliveries(directory: Path) -> list[str]:
    lines = (directory / 'parent-notices.jsonl').read_text().splitlines()
    return [json.loads(line)['delivery'] for line in lines]


def test_two_requests_of_one_execution_each_reach_main_once(leader: tuple[Path, Path]) -> None:
    runner, directory = leader
    for request_id in ('r1', 'r2'):
        runner_control.deliver_parent_event(directory, 'waits for ' + request_id, _request(request_id))
    claimed = mc.claim_notices(runner, 'claude', SESSION)
    assert [(item['event']['event'], item['event']['request_id']) for item in claimed] == [
        ('claude/can_use_tool', 'r1'), ('claude/can_use_tool', 'r2')]
    assert len({item['id'] for item in claimed}) == 2
    assert mc.claim_notices(runner, 'claude', SESSION) == []
    assert _deliveries(directory) == ['received', 'received']


def test_a_retried_request_delivery_is_queued_once(leader: tuple[Path, Path]) -> None:
    runner, directory = leader
    request = _request('r1')
    runner_control.deliver_parent_event(directory, 'waits for r1', request)
    runner_control.deliver_parent_event(directory, 'waits for r1', request)
    assert len(mc.claim_notices(runner, 'claude', SESSION)) == 1


def test_budget_and_end_beside_requests_queue_once_each(leader: tuple[Path, Path]) -> None:
    runner, directory = leader
    end = {'type': 'completed', 'session': 's-leader', 'execution_id': EXECUTION}
    runner_control.deliver_parent_event(directory, 'waits for r1', _request('r1'))
    runner_control.deliver_parent_event(directory, 'budget', {'type': 'execution-budget-exceeded'})
    runner_control.deliver_parent_event(directory, 'waits for r2', _request('r2'))
    runner_control.deliver_parent_event(directory, 'ended', end)
    runner_control.deliver_parent_event(directory, 'ended', end)      # a retried end
    claimed = mc.claim_notices(runner, 'claude', SESSION)
    assert [item['event']['event'] for item in claimed] == [
        'claude/can_use_tool', 'execution-budget-exceeded', 'claude/can_use_tool', 'completed']
    assert claimed[-1]['id'] == f'{EXECUTION}:completed'
    assert _deliveries(directory) == ['received'] * 5


def test_an_end_main_already_saw_is_still_skipped(leader: tuple[Path, Path]) -> None:
    runner, directory = leader
    mc.acknowledge_ends(runner, 'claude', SESSION, [EXECUTION])
    runner_control.deliver_parent_event(directory, 'waits for r1', _request('r1'))
    runner_control.deliver_parent_event(
        directory, 'ended', {'type': 'completed', 'session': 's-leader', 'execution_id': EXECUTION})
    assert [item['event']['event'] for item in mc.claim_notices(runner, 'claude', SESSION)] == [
        'claude/can_use_tool']


def test_requeued_and_transferred_requests_keep_their_identity(leader: tuple[Path, Path]) -> None:
    runner, directory = leader
    for request_id in ('r1', 'r2'):
        runner_control.deliver_parent_event(directory, 'waits for ' + request_id, _request(request_id))
    claimed = mc.claim_notices(runner, 'claude', SESSION)
    identities = [item['id'] for item in claimed]
    assert mc.requeue_notices(runner, 'claude', SESSION, identities) == 2
    successor = {'runtime': 'claude', 'session': str(uuid4()), 'runner': str(runner)}
    mc._transfer_notices(runner, {'runtime': 'claude', 'session': SESSION}, successor)
    assert [item['id'] for item in mc.claim_notices(runner, 'claude', successor['session'])] == identities
