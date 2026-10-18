"""Completion delivery is outside locks and cannot duplicate wait results."""

import threading
from pathlib import Path

import pytest

from agent_swarm import AgentControl, Caller, bind


class Driver:
    """Retain controlled executions without a Runtime or background work."""

    def __init__(self) -> None:
        self.runs = {}

    def prepare(self, runtime: str, caller: Caller) -> dict:
        """Use explicit settings without project discovery."""
        return {}

    def start(self, run) -> None:
        """Publish a distinct native Session and retain the real core callback."""
        self.runs[run.agent] = run
        run.events.session('native-' + run.agent)


@pytest.mark.parametrize('delivered', [True, False])
def test_completion_once_outside_lock_and_no_duplicate_body(tmp_path: Path, delivered: bool) -> None:
    """Concurrent wait sees no duplicate body while the relay owns delivery."""
    driver = Driver()
    control = AgentControl(tmp_path, {'controlled': driver})
    root = bind(control, Caller('test', None))
    parent = root({'action': 'create', 'runtime': 'controlled', 'instruction': 'parent'}).document
    parent_run = driver.runs[parent['agent']]
    entered, release = threading.Event(), threading.Event()
    notices = []

    def receive(event: dict) -> bool:
        """Re-enter public control to prove no child record lock spans delivery."""
        status = parent_run.call({'action': 'status', 'agent': event['agent']})
        assert not status.failed
        assert status.document['result']['last_result']['last_message'] is None
        notices.append(event)
        entered.set()
        assert release.wait(3)
        return delivered

    parent_run.events.receive_children(receive)
    child = parent_run.call({'action': 'create', 'runtime': 'controlled', 'instruction': 'child'}).document
    child_run = driver.runs[child['agent']]
    thread = threading.Thread(target=lambda: child_run.events.finished('completed', last_message='actual body'))
    thread.start()
    try:
        assert entered.wait(3)
        waiting = parent_run.call({'action': 'wait', 'agent': child['agent'], 'timeout_seconds': 1})
        assert waiting.document['result']['last_result']['last_message'] is None
    finally:
        release.set()
        thread.join(3)
    assert notices == [{'parent': parent['agent'], 'agent': child['agent'],
                        'session': child['session'], 'execution': child['execution'],
                        'body': 'actual body', 'outcome': 'completed'}]
    child_run.events.finished('completed', last_message='duplicate')
    assert len(notices) == 1
    status = parent_run.call({'action': 'status', 'agent': child['agent']}).document['result']
    assert status['last_result']['notification'] == ('delivered' if delivered else 'unavailable')
    assert status['last_result']['last_message'] == (None if delivered else 'actual body')
    assert child_run.call({'action': 'status'}).failed
