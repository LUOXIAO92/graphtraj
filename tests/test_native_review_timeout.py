"""A native review the user never answers ends within its bound and applies nothing."""

import json
import os
import queue
import threading
import time
from io import TextIOBase
from pathlib import Path

import pytest

from agent_swarm import AgentsResult
from graphtraj.execution.approved_recovery import review_proposal
from graphtraj.execution.runner_models import RunnerError
from graphtraj.interfaces import mcp
from graphtraj.runtimes.claude.mcp import serve


BOUND  = 0.5
MARGIN = 3.0
ALIAS  = '376-dev_full_suite_baseline_failures-handover0-team_leader@team_leader'
# The 2026-10-29 13:42 call: a reviewed budget increment for a completed Leader.
REQUEST  = {'alias': ALIAS, 'additional_minutes': 15, 'resume': True, 'restore_active': False}
PROPOSAL = {'request': REQUEST, 'before': {'budget': {'approved_minutes': 90}},
            'after': {'budget': {'approved_minutes': 105}}, 'authority': []}
ACCEPT   = {'action': 'accept', 'content': {}}


class Output(TextIOBase):
    """Collect the server's messages for a client reading them concurrently."""

    def __init__(self) -> None:
        self.messages: queue.Queue = queue.Queue()

    def write(self, text: str) -> int:
        """Record each complete frame."""
        for line in text.splitlines():
            if line.strip():
                self.messages.put(json.loads(line))
        return len(text)

    def next(self, timeout: float = BOUND + MARGIN) -> dict:
        """Return the next message, failing instead of hanging."""
        try:
            return self.messages.get(timeout=timeout)
        except queue.Empty:
            pytest.fail(f'no server message within {timeout} s')


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    """An open client connection that answers only what the test sends."""
    monkeypatch.setattr(mcp, 'NATIVE_REVIEW_TIMEOUT', BOUND, raising=False)
    read, write = os.pipe()
    source, sink = os.fdopen(read, 'r'), os.fdopen(write, 'w')
    yield source, sink
    if not sink.closed:
        sink.close()


def test_unanswered_review_times_out_and_cancels_its_dialog(client) -> None:
    """The dialog is cancelled and the caller learns why within the bound."""
    source, sink = client
    output  = Output()
    outcome = {}

    def run() -> None:
        try:
            outcome['decision'] = mcp.elicit_review(source, output, PROPOSAL, 2, 'approved_recovery',
                                                    lambda result: True)
        except RunnerError as error:
            outcome['error'] = error

    started = time.monotonic()
    thread  = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(BOUND + MARGIN)
    elapsed, waiting = time.monotonic() - started, thread.is_alive()
    # EOF releases a review that never stops waiting by itself.
    sink.close()
    thread.join(MARGIN)
    assert not waiting, f'review still waiting after {elapsed:.1f} s'
    error = outcome['error']
    assert error.code == 'native-approval-timeout', error.message
    assert f'{BOUND:g} s' in error.message and 'native review dialog' in error.message
    assert 'nothing was applied' in error.message and 'shows the dialog again' in error.message
    request, cancel = output.next(), output.next()
    assert request['method'] == 'elicitation/create'
    assert cancel['method'] == 'notifications/cancelled'
    assert cancel['params']['requestId'] == request['id']


def test_claude_main_ignores_late_answer_and_serves_later_calls(client, tmp_path: Path) -> None:
    """A timed-out call applies nothing; its late answer neither replies nor decides later reviews."""
    source, sink = client
    output  = Output()
    applied = []

    def native_call(request: dict, tool: str = 'agents') -> AgentsResult:
        """Review and apply as approved_recovery does with a bound host reviewer."""
        if review_proposal(PROPOSAL, tmp_path, tmp_path) != {'decision': 'accept'}:
            return AgentsResult({'recovery_status': 'denied'}, failed=True)
        applied.append(request)
        return AgentsResult({'recovery_status': 'applied'})

    def send(message: dict) -> None:
        sink.write(json.dumps({'jsonrpc': '2.0', **message}) + '\n')
        sink.flush()

    call   = {'name': 'tasks', 'arguments': {'action': 'execute', 'feature': 'approved_recovery',
                                             'arguments': REQUEST}}
    server = threading.Thread(target=serve, args=(source, output, tmp_path),
                              kwargs={'native_call': native_call}, daemon=True)
    server.start()
    try:
        send({'id': 1, 'method': 'initialize', 'params': {'capabilities': {'elicitation': {}}}})
        assert output.next()['id'] == 1
        send({'id': 2, 'method': 'tools/call', 'params': call})
        first = output.next()
        assert first['method'] == 'elicitation/create'
        started = time.monotonic()
        cancel  = output.next()
        assert cancel['method'] == 'notifications/cancelled'
        assert cancel['params']['requestId'] == first['id']
        result = output.next()
        assert time.monotonic() - started < BOUND + MARGIN
        assert result['id'] == 2 and result['result']['isError']
        assert result['result']['structuredContent']['error']['code'] == 'native-approval-timeout'
        assert applied == []

        # The user answers the dismissed dialog late: no reply, nothing applied.
        send({'id': first['id'], 'result': ACCEPT})
        send({'id': 3, 'method': 'ping'})
        assert output.next() == {'jsonrpc': '2.0', 'id': 3, 'result': {}}
        assert applied == []

        # Repeating the call shows the dialog again; a stale answer cannot decide it.
        send({'id': 4, 'method': 'tools/call', 'params': call})
        second = output.next()
        assert second['method'] == 'elicitation/create' and second['id'] != first['id']
        send({'id': first['id'], 'result': ACCEPT})
        send({'id': second['id'], 'result': ACCEPT})
        result = output.next()
        assert result['id'] == 4 and not result['result']['isError'], result
        assert len(applied) == 1
    finally:
        sink.close()
        server.join(MARGIN)
    assert not server.is_alive()
