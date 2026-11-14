"""The Runner reclaims a killed member's tool processes (Task 460).

A Task member's owner stops its Runtime's tool processes at its own end (459).
A killed Worker never reaches that end, so once the Worker and the Runtime are
gone and the Runner confirms the Runtime's end, the Runner reads the Worker's
record (marker and descendants sidecar) and stops what is still alive.

The fake Codex Runtime keeps no descendants record, so each test writes the
record a Claude Worker writes, naming real /bin/sh and /bin/sleep processes the
test itself started. Every process is identified by pid and start time, and
the tests stop only what they started.
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from graftling.tool_descendants import identity, write_sidecar
from test_abnormal_response import _session_directory, _session_mapping
from test_managed_sessions import launch_document, managed_project, observe  # noqa: F401 (fixture)
from test_resume_after_owner_exit import _kill_owner, confirming_project  # noqa: F401 (fixture)

pytestmark = pytest.mark.skipif(sys.platform != 'darwin' and not sys.platform.startswith('linux'),
                                reason='descendant records need macOS or Linux')

MARKER_ENV = 'GRAFTLING_MEMBER_RUN'


class Started:
    """Processes this test started, each with its identity at start."""

    def __init__(self) -> None:
        self.items: dict[str, tuple[int, int]] = {}
        self.popens: list[subprocess.Popen] = []

    def spawn(self, name: str, argv: list[str], marker: str | None) -> int:
        environment = {key: value for key, value in os.environ.items() if key != MARKER_ENV}
        if marker is not None:
            environment[MARKER_ENV] = marker
        process = subprocess.Popen(argv, env=environment, start_new_session=True,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        self.popens.append(process)
        self.items[name] = (process.pid, _start(process.pid))
        return process.pid

    def child(self, name: str, parent: str) -> int:
        """Record the one child of an earlier process (the shell's /bin/sleep)."""
        from graftling.tool_descendants import _table

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            found = [item for item in _table().values() if item.ppid == self.items[parent][0]]
            if found:
                self.items[name] = (found[0].pid, found[0].start)
                return found[0].pid
            time.sleep(0.02)
        raise AssertionError(f'{parent} started no child')

    def alive(self, name: str) -> bool:
        pid, start = self.items[name]
        now = identity(pid)
        return now is not None and now.start == start

    def entry(self, name: str) -> dict:
        found = identity(self.items[name][0])
        assert found is not None and found.start == self.items[name][1]
        return {'pid': found.pid, 'ppid': found.ppid, 'pgid': found.pgid, 'uid': found.uid,
                'start': found.start, 'argv': name}

    def stop_all(self) -> None:
        """Stop only what is still alive with the start time it had."""
        for name in self.items:
            if self.alive(name):
                os.kill(self.items[name][0], signal.SIGKILL)
        for process in self.popens:
            process.wait(timeout=10)


def _start(pid: int) -> int:
    found = identity(pid)
    assert found is not None
    return found.start


def _record(directory: Path, execution_id: str, marker: str, entries: list[dict]) -> Path:
    """Write what a Claude Worker records before its Runtime starts, and its sampler's sidecar."""
    sidecar = directory / f'tool-descendants-{execution_id}.json'
    write_sidecar(sidecar, 4242, entries)
    record = directory / f'tool-processes-{execution_id}.yml'
    record.write_text(yaml.safe_dump({'execution_id': execution_id, 'tool_marker': marker,
                                      'tool_descendants': str(sidecar.resolve())}))
    return record


def _tool_and_bystanders(started: Started, marker: str) -> None:
    started.spawn('shell', ['/bin/sh', '-c', '/bin/sleep 460; :'], marker)
    started.child('sleep', 'shell')
    hold = [sys.executable, '-c', 'import time; time.sleep(120)']
    started.spawn('other-marker', hold, 'another-execution-marker')
    started.spawn('no-marker', hold, None)
    started.spawn('own-sleep', ['/bin/sleep', '901'], None)


def test_killed_member_tool_processes_are_stopped_by_the_runner_reconcile(confirming_project) -> None:
    root, cause, call, _ = confirming_project
    alias = call('launch', launch_document())['tasks'][0]['alias']
    observe(call, alias, 'running')
    before = _session_mapping(root, alias)
    directory = _session_directory(root, alias)
    started = Started()
    try:
        marker = 'marker-460-' + before['execution_id']
        _tool_and_bystanders(started, marker)
        record = _record(directory, before['execution_id'], marker,
                         [started.entry('shell'), started.entry('sleep')])
        _kill_owner(directory, before, runtime=True)

        sent = call('send', [alias, 'continue after the lost owner', [cause]], timeout=60)
        assert sent['execution_id'] != before['execution_id']

        receipt = yaml.safe_load(
            (directory / f"terminal-confirmation-{before['execution_id']}.yml").read_text())
        reclaimed = receipt['tool_processes']
        tools = {started.items['shell'][0], started.items['sleep'][0]}
        assert {item['pid'] for item in reclaimed['found']} == tools
        assert {item['pid'] for item in reclaimed['stopped']} == tools
        assert reclaimed['remaining'] == [] and 'error' not in reclaimed
        assert not started.alive('shell') and not started.alive('sleep')
        for name in ('other-marker', 'no-marker', 'own-sleep'):
            assert started.alive(name), name
        retained = yaml.safe_load(record.read_text())
        assert retained['reclaims'] == [reclaimed]
    finally:
        started.stop_all()


def test_running_member_tool_processes_are_not_touched(confirming_project) -> None:
    """A held owner lock refuses the confirmation, so nothing is signalled."""
    from graphtraj.execution.runner_control import _confirm_termination
    from graphtraj.execution.runner_models import RunnerError

    root, cause, call, _ = confirming_project
    alias = call('launch', launch_document())['tasks'][0]['alias']
    observe(call, alias, 'running')
    before = _session_mapping(root, alias)
    directory = _session_directory(root, alias)
    started = Started()
    try:
        marker = 'marker-460-' + before['execution_id']
        started.spawn('shell', ['/bin/sh', '-c', '/bin/sleep 460; :'], marker)
        started.child('sleep', 'shell')
        record = _record(directory, before['execution_id'], marker,
                         [started.entry('shell'), started.entry('sleep')])
        with pytest.raises(RunnerError) as refused:
            _confirm_termination(alias, directory, before)
        assert refused.value.code == 'termination-unconfirmed'
        assert started.alive('shell') and started.alive('sleep')
        assert 'reclaims' not in yaml.safe_load(record.read_text())
        assert not (directory / f"terminal-confirmation-{before['execution_id']}.yml").exists()
    finally:
        started.stop_all()
    call('send', [alias, 'finish normally', [cause]])
    observe(call, alias, 'idle', 'completed')


def test_worker_records_marker_and_sidecar_before_the_runtime_starts(tmp_path: Path) -> None:
    from graphtraj.execution.runner_worker import record_tool_processes

    class Handle:
        execution_id = 'e460'
        member_marker = 'm460'
        tool_descendants = tmp_path / 'tool-descendants-e460.json'

    record_tool_processes(tmp_path, Handle())
    assert yaml.safe_load((tmp_path / 'tool-processes-e460.yml').read_text()) == {
        'execution_id': 'e460', 'tool_marker': 'm460',
        'tool_descendants': str((tmp_path / 'tool-descendants-e460.json').resolve())}

    class Unsampled:  # a Runtime owner without a descendants record writes nothing
        execution_id = 'e461'
        member_marker = 'm461'

    record_tool_processes(tmp_path, Unsampled())
    assert not (tmp_path / 'tool-processes-e461.yml').exists()
