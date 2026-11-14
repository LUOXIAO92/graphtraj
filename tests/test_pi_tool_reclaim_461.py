"""461: a Pi child's tool processes are stopped after its owner dies and after a normal end.

Pi 1.4.0 starts its bash tool ``detached`` (its own session, outside the
Runtime group) with ``/bin/bash``, a platform binary whose environment macOS
hides. It kills those shells only on SIGTERM/SIGHUP or a tool abort, not on
the stdin EOF a killed owner causes. The stand-in Runtime here is the real
launch chain (launch.py -> srt stand-in -> bash -> Pi RPC fixture) whose
``tool-shell`` turn starts real ``/bin/sh`` and ``/bin/sleep`` in their own
session, plus two readable processes of other executions.

Every test stops only processes it started, after checking pid and start time.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import uuid

import pytest

from graftling import AgentControl, Caller, bind
from graftling.pi import PiDriver
from graftling.tool_descendants import Identity, identity, read_sidecar
from test_pi_generic_execution import generic
from test_pi_runtime import pi_environment  # noqa: F401
from test_tool_descendants_459 import bystander, is_alive, stop_own, wait_for

pytestmark = pytest.mark.skipif(not (sys.platform == 'darwin' or sys.platform.startswith('linux')),
                                reason='macOS and Linux process tables')

# The owner: AgentControl with a PiDriver in its own process, as a Worker or host.
OWNER = r'''
import json, sys, threading
from graftling import AgentControl, Caller, bind
from graftling.pi import PiDriver
request, data, instruction = json.loads(sys.argv[1]), sys.argv[2], sys.argv[3]
call = bind(AgentControl(data, {"pi": PiDriver(request)}), Caller("standalone-host", None))
print(json.dumps(call({"action": "create", "runtime": "pi", "instruction": instruction}).document), flush=True)
threading.Event().wait()
'''


def execution(data: Path, agent: str) -> dict:
    return json.loads((data / 'control/agents' / f'{agent}.json').read_text())['executions'][-1]


def started_by_turn(record: Path) -> tuple[Identity, Identity, list[Identity]]:
    """The tool shell, its /bin/sleep, and the other executions' processes with their sleeps."""
    shell_pid = int(wait_for(lambda: record.exists() and record.read_text().strip()))
    from graftling.tool_descendants import _table

    def found():
        table = _table()
        sleeps = [item for item in table.values() if item.ppid == shell_pid]
        others = [table[pid] for pid in json.loads(Path(f'{record}.others').read_text()) if pid in table]
        others += [item for item in table.values() if item.ppid in {other.pid for other in others}]
        return (table.get(shell_pid), sleeps, others) if sleeps and len(others) == 4 else None

    shell, sleeps, others = wait_for(found, 10)
    return shell, sleeps[0], others


def test_owner_killed_then_reconciliation_stops_the_pi_tool_shell_and_sleep(
        tmp_path: Path, pi_environment: dict) -> None:
    data, record = tmp_path / 'data', tmp_path / 'shell.pid'
    request = generic(tmp_path, pi_environment)
    owner = subprocess.Popen([sys.executable, '-c', OWNER, json.dumps(request), str(data), f'tool-shell {record}'],
                             env={**os.environ, 'PI_FIXTURE_TOOL_SECONDS': '120'},
                             stdout=subprocess.PIPE, text=True)
    user = bystander()
    started: list[Identity] = []
    try:
        created = json.loads(owner.stdout.readline())
        agent = created['agent']
        shell, sleep, others = started_by_turn(record)
        started = [shell, sleep, *others]
        process = execution(data, agent)['process']
        print('process facts:', json.dumps(process))
        sidecar = process.get('tool_descendants')
        recorded = wait_for(lambda: sidecar and {shell.pid, sleep.pid} <= {
            entry['pid'] for entry in read_sidecar(sidecar)}, 10)
        print('sidecar:', Path(sidecar).read_text() if sidecar else None)

        owner.send_signal(signal.SIGKILL)
        owner.wait(5)
        runtime = process['runtime_pid']
        # The Runtime reads stdin EOF and exits without stopping its detached tool, as Pi does.
        assert wait_for(lambda: identity(runtime) is None, 15), 'the Runtime outlived its owner'
        assert is_alive(shell) and is_alive(sleep), 'the tool shell outlived its owner, as on the real host'

        call = bind(AgentControl(data, {'pi': PiDriver(request)}), Caller('standalone-host', None))
        status = call({'action': 'status', 'agent': agent}).document
        report = execution(data, agent).get('escaped_processes')
        print('escaped_processes:', json.dumps(report))
        assert status['result']['last_result']['error']['code'] == 'owner-exited'
        assert not is_alive(shell) and not is_alive(sleep), 'the reconciling read left the tool shell running'
        assert recorded, 'the owner recorded the tool shell and its sleep'
        assert process['tool_marker'] and sidecar == str(Path(sidecar).resolve())
        assert {shell.pid, sleep.pid} <= {item['pid'] for item in report['stopped']}
        assert report['remaining'] == [] and 'error' not in report
        assert all(is_alive(item) for item in others), 'other executions are untouched'
        assert user.poll() is None, "the user's own /bin/sleep is untouched"

        # A later read changes nothing and signals nothing.
        call({'action': 'status', 'agent': agent})
        assert execution(data, agent)['escaped_processes'] == report
        assert all(is_alive(item) for item in others) and user.poll() is None
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(5)
        stop_own(started)
        user.kill()
        user.wait(5)


def test_normal_end_stops_the_pi_tool_shell_that_left_the_group(
        tmp_path: Path, pi_environment: dict) -> None:
    data, record = tmp_path / 'data', tmp_path / 'shell.pid'
    request = generic(tmp_path, pi_environment)
    call = bind(AgentControl(data, {'pi': PiDriver(request)}), Caller('standalone-host', None))
    user = bystander()
    started: list[Identity] = []
    try:
        created = call({'action': 'create', 'runtime': 'pi', 'instruction': f'tool-shell {record}'})
        assert not created.failed, created.document
        agent = created.document['agent']
        shell, sleep, others = started_by_turn(record)
        started = [shell, sleep, *others]
        done = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 30})
        assert not done.failed, done.document
        current = execution(data, agent)
        process = current['process']
        report = process['runtime_exit'].get('escaped_processes')
        print('process facts:', json.dumps(process))
        assert done.document['result']['last_result']['outcome'] == 'completed'
        assert not is_alive(shell) and not is_alive(sleep), "the owner's finally left the tool shell running"
        assert {shell.pid, sleep.pid} <= {entry['pid'] for entry in read_sidecar(process['tool_descendants'])}
        assert report is not None, 'the owner reported the tool processes it stopped'
        assert {shell.pid, sleep.pid} <= {item['pid'] for item in report['stopped']}
        assert report['remaining'] == [] and 'error' not in report
        assert all(is_alive(item) for item in others), 'other executions are untouched'
        assert user.poll() is None, "the user's own /bin/sleep is untouched"
    finally:
        stop_own(started)
        user.kill()
        user.wait(5)


def test_the_pi_driver_records_the_sidecar_path(tmp_path: Path, monkeypatch) -> None:
    import graftling.pi.driver as module
    from graftling import Run
    from test_reconcile_escaped_tools_457 import Events

    class Turn:
        def __init__(self, *args, **kwargs):
            self.ready, self.created = args[3], args[4]
            self.member_marker = uuid.uuid4().hex
            self.tool_descendants = tmp_path / 'sub' / '..' / 'tool-descendants-p.json'
            self.unseen, self.accepted = [], threading.Event()

        def take_unseen(self):
            return []

        def run(self):
            self.created('session-461', 4646)
            self.ready('session-461', 4646)
            return {'outcome': 'completed'}

    monkeypatch.setattr(module, 'PiExecution', Turn)
    events = Events()
    run = Run(agent='child', execution='e461', runtime='pi', settings={'adapter_request': {}},
              message='hi', session=None, directory=tmp_path, archive=None, events=events)
    module.PiDriver({}).start(run)
    assert events.ended.wait(10)
    assert events.facts['tool_marker']
    assert events.facts['tool_descendants'] == str((tmp_path / 'tool-descendants-p.json').resolve())


def test_graphtrajs_agents_driver_records_the_pi_sidecar_path(tmp_path: Path, monkeypatch) -> None:
    import graphtraj.execution.agent_driver as module
    from graftling import Run
    from test_reconcile_escaped_tools_457 import Events

    class Turn:
        def __init__(self, request, message, directory, ready, evidence, *, session_created, **kwargs):
            self.request, self.directory = request, directory
            self.ready, self.created = ready, session_created
            self.native_id = 'session-461'
            self.member_marker = uuid.uuid4().hex
            self.tool_descendants = directory / 'tool-descendants-q.json'

        def configure_independent(self, **kwargs):
            pass

        def run(self):
            self.created('session-461', 4747)
            self.ready('session-461', 4747)
            return {'outcome': 'completed'}

    class Adapter:
        managed_execution = Turn

    monkeypatch.setattr(module, 'select_runtime_adapter', lambda runtime: Adapter())
    events = Events()
    run = Run(agent='child', execution='e461', runtime='pi',
              settings={'adapter_request': {'harness_root': str(tmp_path)}, 'evidence': {},
                        'cwd': str(tmp_path)},
              message='hi', session=None, directory=tmp_path, archive=None, events=events)
    module.AdapterDriver(tmp_path, tmp_path).start(run)
    assert events.ended.wait(10)
    assert events.facts['tool_marker']
    assert events.facts['tool_descendants'] == str((tmp_path / 'tool-descendants-q.json').resolve())


def test_graphtrajs_pi_owner_inherits_the_sampler() -> None:
    from graphtraj.runtimes.pi.managed_session import PiManagedExecution
    from graftling.pi.execution import PiExecution

    assert issubclass(PiManagedExecution, PiExecution)
