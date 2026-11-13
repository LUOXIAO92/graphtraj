"""The direct parent continues a Session whose owner was killed (Task 456).

When a Session's Worker and Runtime are both gone and only the unclosed
execution record remains, the direct parent's continue first lets the Runner's
abnormal answer reconcile that record (owner-exit record, Runtime termination
confirmation, one parent notice) and then starts the next execution normally.
A running owner and an execution whose end cannot be confirmed stay protected.

The fake Codex Runtime has no native termination confirmation, so each caller
process gets one that confirms exactly when the recorded Runtime process is
gone - the fact the real Adapters establish from their own process records.
"""

import os
import shutil
import signal
import time
from pathlib import Path

import pytest
import yaml

import test_managed_sessions
from test_abnormal_response import (
    _abnormal_responses, _await_released_ownership, _session_directory, _session_mapping,
)
from test_managed_sessions import ManagedProject, launch_document, managed_project, observe

CONFIRM = """
import os as _os
from graphtraj.runtimes import runtime_adapter as _runtime_adapter

def _confirm_termination(self, directory, mapping, request):
    try:
        _os.kill(mapping['runtime_pid'], 0)
    except ProcessLookupError:
        return {'runtime_exited': True}
    raise _runtime_adapter.RuntimeAdapterError(
        'termination-unconfirmed', 'The recorded Runtime process is still present.',
        terminal_confirmed=False)

type(_runtime_adapter.select_runtime_adapter('codex')).confirm_termination = _confirm_termination
"""


@pytest.fixture
def confirming_project(
    managed_project: ManagedProject, monkeypatch: pytest.MonkeyPatch,
) -> ManagedProject:
    """Give every caller process a Codex termination confirmation."""
    monkeypatch.setattr(test_managed_sessions, 'CALL', CONFIRM + test_managed_sessions.CALL)
    return managed_project


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def _kill_owner(directory: Path, mapping: dict, *, runtime: bool) -> None:
    """Kill the Worker (and optionally its Runtime) the way the 451 probe did."""
    os.kill(mapping['worker_pid'], signal.SIGKILL)
    _await_released_ownership(directory, mapping['worker_pid'])
    if runtime:
        os.kill(mapping['runtime_pid'], signal.SIGKILL)
        deadline = time.monotonic() + 15
        while not _gone(mapping['runtime_pid']):
            assert time.monotonic() < deadline, 'the killed Runtime is still present'
            time.sleep(0.02)
    # The killed owner's control channel is left behind; removing it makes the
    # lost contact immediate instead of waiting out the control timeout.
    for leftover in directory.glob('control-*'):
        shutil.rmtree(leftover, ignore_errors=True)


@pytest.mark.parametrize('answered_first', [False, True], ids=['answer-on-resume', 'answered-earlier'])
def test_killed_owner_is_reconciled_and_the_session_resumes(
    confirming_project: ManagedProject, answered_first: bool,
) -> None:
    root, cause, call, _ = confirming_project
    alias = call('launch', launch_document())['tasks'][0]['alias']
    observe(call, alias, 'running')
    before = _session_mapping(root, alias)
    directory = _session_directory(root, alias)
    _kill_owner(directory, before, runtime=True)

    if answered_first:
        # A status read made the judgment and its answer before any resume.
        judged = call('status', [alias], timeout=40)['aliases'][0]
        assert judged['activity'] == 'abnormal', judged
        assert (directory / 'abnormal-response.yml').is_file()
        assert yaml.safe_load((directory / 'stop.yml').read_text()) == {
            'alias': alias, 'kind': 'abnormal', 'execution_id': before['execution_id']}

    sent = call('send', [alias, 'continue after the lost owner', [cause]], timeout=60)
    after = _session_mapping(root, alias)
    assert sent['session'] == before['session']
    assert sent['execution_id'] == after['execution_id'] != before['execution_id']
    assert after['worker_pid'] != before['worker_pid']
    observe(call, alias, 'running')

    # The killed execution's end stays recorded as an unconfirmed owner exit,
    # with the Runtime's termination confirmation retained beside it.
    receipt = yaml.safe_load(
        (directory / f"terminal-confirmation-{before['execution_id']}.yml").read_text())
    assert receipt['terminal_confirmed'] is True
    assert receipt['original_execution']['error']['code'] == 'owner-exited'
    assert receipt['original_execution']['terminal_confirmed'] is False
    assert yaml.safe_load((directory / 'stop.yml').read_text()) == {
        'alias': alias, 'kind': 'abnormal', 'execution_id': before['execution_id'], 'resumed': True}
    assert (directory / f"abnormal-response-{before['execution_id']}.yml").is_file()
    assert not (directory / 'abnormal-response.yml').exists()
    # The direct parent heard about the abnormality exactly once.
    record, = _abnormal_responses(root, alias)
    assert {item['alias']: item['interrupt_status'] for item in record['identity']['members']} == {
        alias: 'stopped'}


def test_unconfirmed_termination_keeps_the_session_stopped(confirming_project: ManagedProject) -> None:
    """A Runtime still alive after its Worker died cannot be confirmed ended."""
    root, cause, call, _ = confirming_project
    alias = call('launch', launch_document())['tasks'][0]['alias']
    observe(call, alias, 'running')
    before = _session_mapping(root, alias)
    directory = _session_directory(root, alias)
    _kill_owner(directory, before, runtime=False)
    try:
        for _ in range(2):  # the answer, then a later retry, both refuse
            refused = call('send', [alias, 'continue', [cause]], timeout=60, returncode=1)
            assert refused['error']['code'] in {'subtree-stopped', 'operation-failed'}, refused
        assert _session_mapping(root, alias) == before
        assert yaml.safe_load((directory / 'stop.yml').read_text()) == {
            'alias': alias, 'kind': 'abnormal', 'execution_id': before['execution_id']}
        assert not (directory / f"terminal-confirmation-{before['execution_id']}.yml").exists()
        assert len(_abnormal_responses(root, alias)) == 1
    finally:
        os.kill(before['runtime_pid'], signal.SIGKILL)


def test_running_owner_receives_the_input_without_a_second_execution(
    confirming_project: ManagedProject,
) -> None:
    root, cause, call, _ = confirming_project
    alias = call('launch', launch_document())['tasks'][0]['alias']
    observe(call, alias, 'running')
    before = _session_mapping(root, alias)
    sent = call('send', [alias, 'finish normally', [cause]])
    assert sent['send_status'] == 'sent' and sent['execution_id'] == before['execution_id']
    observe(call, alias, 'idle', 'completed')
    assert _session_mapping(root, alias)['worker_pid'] == before['worker_pid']
    directory = _session_directory(root, alias)
    assert not (directory / 'stop.yml').exists()
    assert not (directory / 'abnormal-response.yml').exists()
