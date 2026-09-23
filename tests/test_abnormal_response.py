"""The Runner's answer to a Session it judged abnormal.

The judgment itself is the existing status behavior: a recorded owner that is
gone and published no terminal record reports ``abnormal``. This file verifies
what that judgment now sets off, through the public entries only - the direct
parent receives the notice in the execution it already owns, and the abnormal
Session's subtree stops.
"""

import json
import os
import shutil
import signal
import time
from pathlib import Path

import yaml

from graphtraj.execution.runner_heartbeat import ownership_is_held
from test_managed_sessions import ManagedProject, launch_document, managed_project, observe


def _session_mapping(root: Path, alias: str) -> dict:
    """Read the identity the Runner retained for one managed Session."""
    return yaml.safe_load(
        (root / '.graphtraj/runner/sessions' / alias / 'mapping.yml').read_text()
    )


def _session_directory(root: Path, alias: str) -> Path:
    """Return the Runner's own directory for one Session."""
    return root / '.graphtraj/runner/sessions' / alias


def _notices(root: Path, alias: str) -> list[dict]:
    """Read every notice record retained for one Session, oldest first."""
    path = _session_directory(root, alias) / 'parent-notices.jsonl'
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _abnormal_responses(root: Path, alias: str) -> list[dict]:
    """Return the notice records that answer an abnormal judgment."""
    return [
        item for item in _notices(root, alias)
        if item.get('identity', {}).get('activity') == 'abnormal'
    ]


def _await_released_ownership(directory: Path, worker_pid: int) -> None:
    """Wait until the killed owner no longer holds the Session's lock.

    A killed Worker's lock is released when the process ends, and a status read
    waits for an answer from a control channel that no longer has an owner, so
    the test waits for the recorded fact instead of guessing a delay.
    """
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if not ownership_is_held(directory, worker_pid):
            return
        time.sleep(0.02)
    raise AssertionError('the killed owner still holds {}'.format(directory))


def test_judged_abnormality_notifies_the_parent_and_stops_the_subtree(
    managed_project: ManagedProject,
) -> None:
    """A lost owner without a terminal record reaches its parent and stops its subtree."""
    root, _, call, _ = managed_project
    parent = call('launch', launch_document())['tasks'][0]['alias']
    child = call('child', [parent, 'descendant@e1'])['alias']
    grandchild = call('child', [child, 'descendant@e2'])['alias']
    observe(call, parent, 'running')
    observe(call, grandchild, 'running')
    parent_before = _session_mapping(root, parent)
    child_before = _session_mapping(root, child)
    child_directory = _session_directory(root, child)
    assert _abnormal_responses(root, child) == []

    # The recorded owner is gone with no terminal record, which is the judgment
    # the Runner already made: the Agent did not report anything itself.
    os.kill(child_before['worker_pid'], signal.SIGKILL)
    _await_released_ownership(child_directory, child_before['worker_pid'])
    # The killed owner left the control channel it served behind. Removing that
    # leftover only makes the lost contact immediate instead of waiting out the
    # control timeout; both report the same unconfirmed interaction.
    for leftover in child_directory.glob('control-*'):
        shutil.rmtree(leftover, ignore_errors=True)

    judged = call('status', [child], timeout=40)['aliases'][0]
    assert judged['activity'] == 'abnormal', judged
    assert 'last_outcome' not in judged

    # The direct parent's own execution received the notice: the delivery, the
    # Session and the execution it reached are the ones that parent recorded.
    record, = _notices(root, child)
    assert record['delivery'] == 'received', record
    assert record['parent'] == parent
    assert record['parent_session'] == parent_before['session']
    assert record['parent_execution_id'] == parent_before['execution_id']
    assert record['identity']['activity'] == 'abnormal'
    assert record['identity']['heartbeat_at'] > 0
    assert {
        item['alias']: item['interrupt_status'] for item in record['identity']['members']
    } == {child: 'unconfirmed', grandchild: 'interrupted'}

    # What the parent received also names every member the Runner stopped or
    # could not confirm.
    for item in record['identity']['members']:
        assert item['alias'] in record['notice']

    # The stopped member is stopped in its own record, the abnormal Session
    # keeps its judgment instead of a terminal outcome, and the stop still
    # prohibits new work in the subtree.
    observe(call, grandchild, 'idle', 'interrupted')
    assert (child_directory / 'stop.yml').is_file()
    assert (child_directory / 'abnormal-response.yml').is_file()
    assert call('status', [child], timeout=40)['aliases'][0]['activity'] == 'abnormal'
    denied = call('child', [grandchild, 'descendant@e3'], returncode=1)
    assert denied['error']['code'] == 'subtree-stopped'

    # The answer ran once: the later reads left exactly one notice.
    assert len(_abnormal_responses(root, child)) == 1

    # The parent's own execution consumed the notice once it reached it.
    trace = Path(parent_before['trace_file'])
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and record['notice'] not in trace.read_text(
        errors='replace'
    ):
        time.sleep(0.05)
    assert record['notice'] in trace.read_text(errors='replace')


def test_normal_waits_and_unconfirmed_owners_do_not_answer(
    managed_project: ManagedProject,
) -> None:
    """Normal waits, completion and an unconfirmable owner leave the subtree alone."""
    root, cause, call, _ = managed_project
    waiting = call('launch', launch_document('request:approval'))['tasks'][0]['alias']
    call('child', [waiting, 'descendant@e1'])
    observe(call, waiting, 'running', waiting_for='runtime-request')
    held = call('launch', launch_document())['tasks'][0]['alias']
    observe(call, held, 'running')

    # A permission wait and an Agent holding its own work are normal waits, not
    # abnormalities: reading them answers nothing.
    for alias in (waiting, held):
        assert call('status', [alias])['aliases'][0]['activity'] == 'running'
        assert _abnormal_responses(root, alias) == []
        assert not (_session_directory(root, alias) / 'abnormal-response.yml').exists()
        assert not (_session_directory(root, alias) / 'stop.yml').exists()

    # A frozen Worker still holds its ownership lock, so its execution cannot be
    # confirmed either way and is reported as unreachable, not abnormal.
    owner = _session_mapping(root, held)
    os.kill(owner['worker_pid'], signal.SIGSTOP)
    try:
        unreachable = call('status', [held], timeout=40)['aliases'][0]
        assert unreachable['activity'] == 'unreachable', unreachable
    finally:
        os.kill(owner['worker_pid'], signal.SIGCONT)
    assert _abnormal_responses(root, held) == []
    assert not (_session_directory(root, held) / 'abnormal-response.yml').exists()
    assert not (_session_directory(root, held) / 'stop.yml').exists()

    # A completed execution is finished, not abnormal.
    done = call('launch', launch_document())['tasks'][0]['alias']
    call('send', [done, 'finish normally', [cause]])
    observe(call, done, 'idle', 'completed')
    assert call('status', [done])['aliases'][0]['activity'] == 'idle'
    assert _abnormal_responses(root, done) == []
    assert not (_session_directory(root, done) / 'abnormal-response.yml').exists()
