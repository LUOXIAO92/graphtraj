"""Codex auto-review outcomes reach the direct parent and its one answer reaches the child (385)."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

from agent_swarm import AgentControl, Caller, bind
from agent_swarm.codex.driver import CodexDriver


@pytest.fixture
def native_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Run the controlled app-server peer and record what the client sends it."""
    peer = tmp_path / 'codex'
    peer.write_text('#!' + sys.executable + '\n' + Path(__file__).with_name('codex_stdio_peer.py').read_text())
    peer.chmod(0o755)
    monkeypatch.setenv('PYTHONPATH', str(Path(__file__).resolve().parents[1] / 'src'))
    monkeypatch.setenv('PEER_PROTOCOL_LOG', str(tmp_path / 'protocol.jsonl'))
    return {'adapter_request': {
        'arguments': [str(peer)], 'worktree_path': str(tmp_path),
        'session_parameters': {'cwd': str(tmp_path), 'model': 'chosen-model',
            'developerInstructions': 'Retain native settings.',
            'config': {'default_permissions': 'chosen', 'permissions': {
                'chosen': {'extends': ':workspace', 'filesystem': {str(tmp_path): 'write'}},
            }}},
    }}


@pytest.fixture
def invoke(tmp_path: Path, native_settings: dict):
    """Call the public agents entry as the child's direct parent."""
    control = AgentControl(tmp_path / 'agents', {'codex': CodexDriver(native_settings)})
    call = bind(control, Caller('controlled-host', 'actual-parent', 'parent-session', 'codex'))

    def invoke(action: str, **arguments: object) -> dict:
        """Fail at the public result rather than inspecting driver internals."""
        result = call({'action': action, **arguments})
        assert not result.failed, result.document
        return result.document

    yield invoke
    for owned in control.interrupt_owned():
        invoke('wait', agent=owned, timeout_seconds=10)


def sent(tmp_path: Path, method: str) -> list[dict]:
    """Return the client requests of one method the peer received."""
    lines = (tmp_path / 'protocol.jsonl').read_text().splitlines()
    return [message for message in map(json.loads, lines) if message.get('method') == method]


def relayed(invoke, instruction: str) -> tuple[str, dict]:
    """Create a child whose auto review reports one outcome; return its parent-visible request."""
    agent = invoke('create', runtime='codex', instruction=instruction)['agent']
    assert invoke('wait', agent=agent, timeout_seconds=10)['result']['pending_requests'] == 1
    [request] = invoke('requests', agent=agent)['result']['requests']
    assert request['method'] == 'item/autoApprovalReview/completed'
    assert request['request_id'].startswith('auto-review:review-')
    return agent, request


def test_denial_is_relayed_and_accept_records_one_native_retry(tmp_path: Path, invoke) -> None:
    """A denial waits for the parent; accept is applied once, through Codex's own retry record."""
    agent, request = relayed(invoke, 'review:denied')
    assert request['params']['review']['status'] == 'denied'

    receipt = invoke('reply', agent=agent, request=request, response={'decision': 'accept'})['result']
    again = invoke('reply', agent=agent, request=request, response={'decision': 'accept'})['result']
    assert receipt['reply_status'] == 'submitted' and again['duplicate'] is True

    done = invoke('wait', agent=agent, timeout_seconds=10)['result']
    assert 'may retry that action once' in done['last_result']['last_message']
    assert 'still goes through automatic approval review' in done['last_result']['last_message']
    [approval] = sent(tmp_path, 'thread/approveGuardianDeniedAction')
    event = approval['params']['event']
    assert (event['id'], event['status'], event['turn_id']) == ('review-1', 'denied', request['execution_id'])
    assert event['action'] == {'type': 'command', 'command': 'touch /outside', 'cwd': '/work',
                               'source': 'unifiedExec'}
    assert len(sent(tmp_path, 'turn/steer')) == 1


def test_denial_declined_after_turn_end_keeps_refusal(tmp_path: Path, invoke) -> None:
    """The execution stays open for the answer; decline neither approves nor restarts work."""
    agent, request = relayed(invoke, 'review-end:denied')
    assert invoke('status', agent=agent)['result']['state'] == 'active'

    invoke('reply', agent=agent, request=request, response={'decision': 'decline'})
    done = invoke('wait', agent=agent, timeout_seconds=10)['result']
    assert done['state'] == 'standby'
    assert done['last_result']['last_message'] == 'turn ended after review'
    assert sent(tmp_path, 'thread/approveGuardianDeniedAction') == []
    assert len(sent(tmp_path, 'turn/start')) == 1


@pytest.mark.parametrize('status', ['timedOut', 'aborted'])
def test_reviewer_failure_is_relayed_and_accept_starts_one_follow_up(
    tmp_path: Path,
    invoke,
    status: str,
) -> None:
    """A reviewer failure is not a denial: accept only tells the child it may retry under review."""
    agent, request = relayed(invoke, 'review-end:' + status)
    assert request['params']['review']['status'] == status

    invoke('reply', agent=agent, request=request, response={'decision': 'accept'})
    done = invoke('wait', agent=agent, timeout_seconds=10)['result']
    assert 'could not complete' in done['last_result']['last_message']
    assert 'may retry that action once' in done['last_result']['last_message']
    assert sent(tmp_path, 'thread/approveGuardianDeniedAction') == []
    assert len(sent(tmp_path, 'turn/start')) == 2


def test_parent_answer_must_be_accept_or_decline(invoke) -> None:
    """A relayed review takes no native-shaped or broader answer."""
    agent, request = relayed(invoke, 'review:denied')
    for response in ({'decision': 'acceptForSession'}, {'decision': 'accept', 'scope': 'all'}):
        assert invoke('requests', agent=agent)['result']['requests'] == [request]
        with pytest.raises(AssertionError, match='invalid-input'):
            invoke('reply', agent=agent, request=request, response=response)
    invoke('reply', agent=agent, request=request, response={'decision': 'decline'})
    assert 'do not retry' in invoke('wait', agent=agent, timeout_seconds=10)['result']['last_result']['last_message']


def test_approved_review_is_not_relayed(tmp_path: Path, invoke) -> None:
    """Only refusals and failures reach the parent; native approvals stay native."""
    agent = invoke('create', runtime='codex', instruction='review-end:approved')['agent']
    done = invoke('wait', agent=agent, timeout_seconds=10)['result']
    assert done['state'] == 'standby' and 'pending_requests' not in done
    assert done['last_result']['last_message'] == 'turn ended after review'


def test_escalated_native_request_is_held_for_the_parent(invoke) -> None:
    """A request Codex hands to the client under auto review is never answered by agents itself."""
    agent = invoke('create', runtime='codex', instruction='request:item/permissions/requestApproval')['agent']
    assert invoke('wait', agent=agent, timeout_seconds=10)['result']['pending_requests'] == 1
    [request] = invoke('requests', agent=agent)['result']['requests']
    assert request['method'] == 'item/permissions/requestApproval'
    invoke('reply', agent=agent, request=request, response={'decision': 'accept'})
    assert invoke('wait', agent=agent, timeout_seconds=10)['result']['last_result']['last_message'] == 'request accepted'


def test_generated_configuration_keeps_native_limits(native_settings: dict) -> None:
    """Prepare only adds the auto-review default and its feature; it loosens nothing."""
    config = native_settings['adapter_request']['session_parameters']['config']
    config.update(approval_policy='on-request', sandbox_mode='workspace-writable',
                  sandbox_workspace_write={'network_access': False, 'writable_roots': []})
    original = deepcopy(config)
    caller = Caller('controlled-host', 'actual-parent', 'parent-session', 'codex')

    prepared = CodexDriver(native_settings).prepare('codex', caller)
    generated = prepared['adapter_request']['session_parameters']['config']
    assert generated.pop('approvals_reviewer') == 'auto_review'
    assert generated.pop('features') == {'exec_permission_approvals': True}
    assert generated == original

    config['approvals_reviewer'] = 'user'
    kept = CodexDriver(native_settings).prepare('codex', caller)['adapter_request']['session_parameters']['config']
    assert kept['approvals_reviewer'] == 'user'
