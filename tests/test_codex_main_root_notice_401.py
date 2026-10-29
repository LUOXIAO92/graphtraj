"""Task 401: a Main-created root Agent's end reaches a Codex Main once."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from graphtraj.configuration.project_configuration import runner_directory
from graphtraj.execution import main_continuity as mc
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


SESSION = 'codex-main'


def _codex(tmp_path: Path, session: str = SESSION) -> dict:
    return {'runtime': 'codex', 'session': session, 'codex_home': str(tmp_path / 'codex-home')}


@pytest.fixture
def sent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list:
    """Replace only the Codex transport; send_event keeps its own event validation."""
    from graphtraj.runtimes.codex import app_server
    from graphtraj.workspace import runner_project

    class Sent(list):
        transport: type

    events = Sent()

    class Transport:
        failure: RuntimeAdapterError | None = None

        def __init__(self, *, environment: dict, **_: object) -> None:
            self.home = environment['CODEX_HOME']

        async def __aenter__(self) -> 'Transport':
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def send_host_event(self, session: str, event: dict) -> dict:
            if Transport.failure is not None:
                raise Transport.failure
            events.append((self.home, session, event))
            return {'turn': {'id': 'turn-1'}}

    monkeypatch.setattr(app_server, 'CodexAppServer', Transport)
    monkeypatch.setattr(runner_project, 'runtime_executable', lambda name: Path(name))
    monkeypatch.chdir(tmp_path)
    events.transport = Transport
    return events


def _agents(root: Path):
    from graphtraj.interfaces.agents import GraphTrajAgents

    agents = GraphTrajAgents.__new__(GraphTrajAgents)
    agents.root = root
    return agents


def _notice(creator: str = SESSION) -> dict:
    return {'parent': None, 'agent': 'agent-probe', 'execution': 'e1', 'session': 's',
            'outcome': 'completed', 'body': 'PONG', 'error': None,
            'creator': {'host': 'graphtraj', 'agent': None, 'session': creator}}


def _inboxes(runner: Path) -> list[Path]:
    return sorted(path for path in runner.rglob('*') if path.parent.name == 'inbox')


def test_a_root_end_is_pushed_once_to_the_codex_main(tmp_path: Path, sent: list) -> None:
    runner = runner_directory(tmp_path)
    mc.claim_main(runner, _codex(tmp_path), 'codex:SessionStart:startup')
    assert _agents(tmp_path)._main_notice(_notice()) is True
    assert sent == [(str(tmp_path / 'codex-home'), SESSION, {
        'source': 'graphtraj', 'alias': 'agent-probe', 'event': 'completed', 'message': 'PONG'})]
    # Nothing waits in a pull-only Main queue as well.
    assert _inboxes(runner) == []
    for runtime in mc.QUEUED_RUNTIMES:
        assert mc.claim_notices(runner, runtime, SESSION) == []


def test_a_root_end_after_claude_to_codex_handover_goes_only_to_codex(tmp_path: Path, sent: list) -> None:
    runner = runner_directory(tmp_path)
    claude = {'runtime': 'claude', 'session': 'claude-main', 'runner': str(runner)}
    mc.claim_main(runner, claude, 'claude:first-control')
    mc.claim_main(runner, _codex(tmp_path), 'codex:SessionStart:resume')
    assert _agents(tmp_path)._main_notice(_notice('claude-main')) is True
    assert [(session, event['alias']) for _, session, event in sent] == [(SESSION, 'agent-probe')]
    assert mc.claim_notices(runner, 'claude', 'claude-main') == []


@pytest.mark.parametrize(('failure', 'expected'), [
    (RuntimeAdapterError('operation-failed', 'lost'), 'unconfirmed'),
    (RuntimeAdapterError('operation-failed', 'refused'), 'raises'),
])
def test_a_failed_codex_push_is_named(tmp_path: Path, sent: list, failure, expected) -> None:
    if expected == 'unconfirmed':
        failure.request_written = True  # send_event names this 'delivery-unconfirmed'
    sent.transport.failure = failure
    runner = runner_directory(tmp_path)
    mc.claim_main(runner, _codex(tmp_path), 'codex:SessionStart:startup')
    if expected == 'raises':
        with pytest.raises(RuntimeAdapterError):
            _agents(tmp_path)._main_notice(_notice())
    else:
        assert _agents(tmp_path)._main_notice(_notice()) == expected


def _finish(tmp_path: Path) -> dict:
    """End one Main-created root through the core and return its status document."""
    from agent_swarm import AgentControl
    from agent_swarm.control import ExecutionEvents

    control = AgentControl(tmp_path / 'swarm', {}, event_receiver=_agents(tmp_path)._main_notice)
    record = {'agent': 'agent-probe', 'name': 'probe', 'runtime': 'claude', 'host': 'graphtraj',
              'parent': None, 'creator': {'host': 'graphtraj', 'agent': None, 'session': SESSION},
              'session': 'n', 'sessions': ['n'], 'settings': {}, 'created_at': 0.0, 'retired_at': None,
              'executions': [{'id': 'e1', 'state': 'running', 'session': 'n', 'requests': [],
                              'process': {'worker_pid': os.getpid()}, 'replies': {}}]}
    path = tmp_path / 'swarm' / 'control' / 'agents' / 'agent-probe.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record))
    ExecutionEvents(control, 'agent-probe', 'e1').finished('completed', last_message='PONG')
    return control._document(json.loads(path.read_text()))['last_result']


def test_the_core_records_a_codex_push_as_delivered(tmp_path: Path, sent: list) -> None:
    mc.claim_main(runner_directory(tmp_path), _codex(tmp_path), 'codex:SessionStart:startup')
    result = _finish(tmp_path)
    assert result['notification'] == 'delivered'
    assert result['last_message'] is None
    assert len(sent) == 1


def test_a_refused_codex_push_keeps_the_end_readable(tmp_path: Path, sent: list) -> None:
    sent.transport.failure = RuntimeAdapterError('operation-failed', 'refused')
    mc.claim_main(runner_directory(tmp_path), _codex(tmp_path), 'codex:SessionStart:startup')
    result = _finish(tmp_path)
    assert result['notification'] == 'unavailable'
    assert result['last_message'] == 'PONG'
