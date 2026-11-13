"""457: reconciling an owner-exited Claude child stops the tools it left behind.

A Claude Code Bash tool shell runs in its own session, outside the Runtime's
process group. Only the owning Worker's finally stopped processes carrying the
execution's GRAFTLING_MEMBER_RUN marker; a SIGKILLed owner never ran it. The
driver now records that marker as the ``tool_marker`` process fact, and the
call that writes ``owner-exited`` stops exactly those processes.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

import graftling
from graftling import AgentControl, Caller, Run
from graftling.member_processes import MEMBER_RUN_ENV
from test_agent_control import ScriptedDriver
from test_owner_exited_notice_451 import dead_pid

pytestmark = pytest.mark.skipif(os.name == 'nt', reason='POSIX process scan')


class MarkedDriver(ScriptedDriver):
    """Records a tool marker with the Runtime pid, as the Claude drivers do."""

    def __init__(self, marker: str | None) -> None:
        super().__init__()
        self.marker = marker

    def start(self, run):
        super().start(run)
        if self.marker is not None:
            run.events.process(tool_marker=self.marker)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / 'data-root'


def call(control, caller, **request):
    return graftling.bind(control, caller)(request).document


def child_with_marker(root: Path, marker: str | None) -> tuple[Caller, str, AgentControl]:
    control = AgentControl(root, {'scripted': MarkedDriver(marker)})
    lead = call(control, Caller('test-host', None), action='create', runtime='scripted', instruction='lead')
    caller = Caller('test-host', lead['agent'])
    child = call(control, caller, action='create', runtime='scripted', instruction='work')
    return caller, child['agent'], control


def record_of(root: Path, agent: str) -> dict:
    return json.loads((root / 'control/agents' / f'{agent}.json').read_text())


def set_owner(root: Path, agent: str, *, runtime_pid: int | None = None) -> None:
    """Point the running execution at a dead owner and the given (default dead) Runtime."""
    path = root / 'control/agents' / f'{agent}.json'
    record = json.loads(path.read_text())
    record['executions'][-1]['process'].update(
        worker_pid=dead_pid(), runtime_pid=runtime_pid if runtime_pid is not None else dead_pid())
    path.write_text(json.dumps(record))


def sleeper(marker: str | None) -> subprocess.Popen:
    """A detached process in its own session, like a Bash tool shell.

    It inherits PYTEST_GRAPHTRAJ_RUN, so 454's session reclaim covers it too.
    """
    environment = {key: value for key, value in os.environ.items() if key != MEMBER_RUN_ENV}
    if marker is not None:
        environment[MEMBER_RUN_ENV] = marker
    process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'],
                               env=environment, start_new_session=True)
    # Wait until its environment is readable as the scanner reads it.
    deadline = time.monotonic() + 5
    from graftling.member_processes import _process_view
    while _process_view(process.pid) is None and time.monotonic() < deadline:
        time.sleep(0.02)
    return process


def stop(*processes: subprocess.Popen) -> None:
    for process in processes:
        if process.poll() is None:
            process.kill()
        process.wait(5)


def test_reconciliation_stops_only_the_execution_marked_tools(root: Path) -> None:
    marker = uuid.uuid4().hex
    caller, child, control = child_with_marker(root, marker)
    escaped, other, unmarked = sleeper(marker), sleeper(uuid.uuid4().hex), sleeper(None)
    try:
        set_owner(root, child)
        status = call(control, caller, action='status', agent=child)
        # Read and print the report first, so a failure under load shows what was found (459).
        execution = record_of(root, child)['executions'][-1]
        report = execution.get('escaped_processes')
        print('escaped_processes:', json.dumps(report), '| pids: escaped', escaped.pid,
              'other', other.pid, 'unmarked', unmarked.pid)
        assert status['result']['last_result']['error']['code'] == 'owner-exited'

        assert escaped.poll() is not None, 'the escaped tool process survived reconciliation'
        assert other.poll() is None and unmarked.poll() is None
        assert execution['process']['tool_marker'] == marker
        assert [item['pid'] for item in report['found']] == [escaped.pid]
        assert [item['pid'] for item in report['stopped']] == [escaped.pid]
        assert report['remaining'] == []

        # A later read changes nothing and signals nothing.
        call(control, caller, action='status', agent=child)
        assert record_of(root, child)['executions'][-1]['escaped_processes'] == report
        assert other.poll() is None and unmarked.poll() is None
    finally:
        stop(escaped, other, unmarked)


def test_a_record_without_a_marker_reconciles_as_before(root: Path) -> None:
    caller, child, control = child_with_marker(root, None)
    bystander = sleeper(uuid.uuid4().hex)
    try:
        set_owner(root, child)
        status = call(control, caller, action='status', agent=child)
        assert status['result']['last_result']['error']['code'] == 'owner-exited'
        execution = record_of(root, child)['executions'][-1]
        assert 'tool_marker' not in execution['process']
        assert 'escaped_processes' not in execution
        assert execution['notification'] == 'held'
        assert bystander.poll() is None
    finally:
        stop(bystander)


def test_a_live_runtime_keeps_its_tools(root: Path) -> None:
    """The Runtime-still-alive branch only adds its diagnostic, as before."""
    marker = uuid.uuid4().hex
    caller, child, control = child_with_marker(root, marker)
    runtime, tool = sleeper(marker), sleeper(marker)
    try:
        set_owner(root, child, runtime_pid=runtime.pid)
        status = call(control, caller, action='status', agent=child)
        assert status['result']['state'] == 'active'
        execution = record_of(root, child)['executions'][-1]
        assert execution['diagnostic'] == 'owner-exited; the Runtime process is still running'
        assert 'escaped_processes' not in execution
        assert runtime.poll() is None and tool.poll() is None
    finally:
        stop(runtime, tool)


class Events:
    def __init__(self) -> None:
        self.facts: dict = {}
        self.ended = threading.Event()

    def session(self, session): pass
    def request(self, details): pass
    def receive_children(self, receive): pass
    def process(self, **facts): self.facts.update(facts)
    def finished(self, outcome, **fields): self.ended.set()


def test_the_claude_driver_records_the_marker(tmp_path: Path, monkeypatch) -> None:
    import graftling.claude.binding as binding
    import graftling.claude.driver as module

    turns = []

    class Turn:
        def __init__(self, *args, **kwargs):
            self.ready, self.created = args[3], args[4]
            self.member_marker = uuid.uuid4().hex
            self.unseen, self.archive = [], None
            turns.append(self)

        def take_unseen(self):
            return []

        def run(self):
            self.created('session-457', 4242)
            self.ready('session-457', 4242)
            return {'outcome': 'completed'}

    monkeypatch.setattr(binding, 'bind_run', lambda turn, run: None)
    monkeypatch.setattr(module, 'ClaudeExecution', Turn)
    events = Events()
    run = Run(agent='child', execution='e457', runtime='claude', settings={'adapter_request': {}},
              message='hi', session=None, directory=tmp_path, archive=None, events=events)
    module.ClaudeDriver(tmp_path, {}).start(run)
    assert events.ended.wait(10)
    assert events.facts == {'runtime_pid': 4242, 'tool_marker': turns[0].member_marker}


def test_graphtrajs_agents_driver_records_the_claude_marker(tmp_path: Path, monkeypatch) -> None:
    import graphtraj.execution.agent_driver as module

    turns = []

    class Turn:
        def __init__(self, request, message, directory, ready, evidence, *, session_created, **kwargs):
            self.request, self.directory = request, directory
            self.ready, self.created = ready, session_created
            self.native_id = 'session-457'
            self.member_marker = uuid.uuid4().hex
            turns.append(self)

        def configure_independent(self, **kwargs):
            pass

        def run(self):
            self.created('session-457', 4343)
            self.ready('session-457', 4343)
            return {'outcome': 'completed'}

    class Adapter:
        managed_execution = Turn

    monkeypatch.setattr(module, 'select_runtime_adapter', lambda runtime: Adapter())
    events = Events()
    run = Run(agent='child', execution='e457', runtime='claude',
              settings={'adapter_request': {'harness_root': str(tmp_path)}, 'evidence': {},
                        'cwd': str(tmp_path)},
              message='hi', session=None, directory=tmp_path, archive=None, events=events)
    module.AdapterDriver(tmp_path, tmp_path).start(run)
    assert events.ended.wait(10)
    assert events.facts['tool_marker'] == turns[0].member_marker
