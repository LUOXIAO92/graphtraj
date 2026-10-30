"""Approval layers combined with request notices and create's extra_fields (385 with 381 and 384)."""
from __future__ import annotations

import json
from pathlib import Path

from agent_swarm import AgentControl, Caller, bind
from agent_swarm.codex.driver import CodexDriver

from test_approval_layers import MAIN, Scripted, call
from test_codex_review_relay import native_settings  # noqa: F401 (fixture)


def test_ask_parent_notifies_the_parent_once_when_the_host_enables_request_notices(tmp_path):
    """A decision request reaches the parent like a native one, without its question."""
    notices = []
    control = AgentControl(tmp_path / 'data', {'scripted': Scripted()}, request_notices=True,
                           event_receiver=lambda notice: notices.append(notice) or True)
    created, _ = call(control, MAIN, action='create', runtime='scripted', instruction='work')
    child = Caller('runtime-mcp', created['agent'])
    for _ in range(2):
        document, failed = call(control, child, action='ask_parent', kind='decision',
                                question='Secret option A or B?', timeout_seconds=0.1)
        assert not failed and document['result']['timed_out'] is True
    [notice] = [item for item in notices if item['outcome'] == 'request']
    assert notice['agent'] == created['agent'] and notice['request'] == document['result']['request']['request_token']
    assert 'agents/decision' in notice['body'] and 'Secret' not in notice['body']


def test_create_keeps_both_workspace_and_extra_fields(tmp_path):
    """Layer 1's workspace and the Session header container are independent create arguments."""
    driver = Scripted()
    control = AgentControl(tmp_path / 'data', {'scripted': driver})
    workspace = tmp_path / 'narrow'
    workspace.mkdir()
    created, failed = call(control, MAIN, action='create', runtime='scripted', instruction='work',
                           workspace=str(workspace), extra_fields={'myapp': {'run': 1}})
    assert not failed, created
    record = json.loads((tmp_path / 'data' / 'control' / 'agents' / f"{created['agent']}.json").read_text())
    assert record['workspace'] == str(workspace.resolve()) and record['extra_fields'] == {'myapp': {'run': 1}}


def test_relayed_review_notifies_the_parent_once_under_request_notices(tmp_path: Path, native_settings: dict) -> None:  # noqa: F811
    """A relay is a permission request, so a host with request notices is told about it once (381)."""
    notices: list[dict] = []
    control = AgentControl(tmp_path / 'agents', {'codex': CodexDriver(native_settings)}, request_notices=True,
                           event_receiver=lambda notice: notices.append(notice) or True)
    call_agents = bind(control, Caller('controlled-host', None, 'parent-session', 'codex'))
    agent = call_agents({'action': 'create', 'runtime': 'codex', 'instruction': 'review:denied'}).document['agent']
    assert call_agents({'action': 'wait', 'agent': agent, 'timeout_seconds': 10}).document['result']['pending_requests'] == 1
    assert [notice['outcome'] for notice in notices] == ['request']
    assert 'item/autoApprovalReview/completed' in notices[0]['body']
    for owned in control.interrupt_owned():
        call_agents({'action': 'wait', 'agent': owned, 'timeout_seconds': 10})
