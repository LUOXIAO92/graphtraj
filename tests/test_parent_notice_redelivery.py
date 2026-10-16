"""A parent notice whose receipt arrives after the ordinary deadline."""
import json
import time
from pathlib import Path

import yaml

from graphtraj.execution import runner_connection, runner_control
from test_task_budget_control import monitor_at, sample_stop


def test_accepted_parent_notice_is_not_forwarded_twice(tmp_path: Path, monkeypatch) -> None:
    monitor = monitor_at(tmp_path / 'task')
    monitor.record_session('researcher', 'researcher')
    sample_stop(monitor, monkeypatch)
    forwarded = []

    def parent(request: dict) -> dict:
        """Forward to the parent, then acknowledge too late for the caller."""
        forwarded.append(request.get('message', ''))
        time.sleep(0.6)
        return {}

    real = runner_connection.connection_operation
    monkeypatch.setattr(runner_control, 'connection_operation',
                        lambda address, document, **kw: real(address, document, **{**kw, 'response_timeout': 0.2}))
    with runner_connection.worker_connection(tmp_path, parent) as address:
        session = tmp_path / 'runner/sessions/research@x1'
        session.mkdir(parents=True)
        (session / 'launch.yml').write_text(yaml.safe_dump({'operation': 'launch', 'mapping': {
            'alias': session.name, 'task_id': '153', 'parent': None, 'parent_connection': address}}))
        pending = [notice['key'] for notice in monitor.pending_parent_notices()]
        monitor.deliver_parent_notices(session)      # production entry, first attempt
        time.sleep(len(pending) * 0.7 + 0.5)
        still = [notice['key'] for notice in monitor.pending_parent_notices()]
        monitor.deliver_parent_notices(session)      # the monitor's next retry
        time.sleep(len(still) * 0.7 + 0.5)
    print('pending', len(pending), 'still', len(still), 'forwarded', len(forwarded), 'distinct', len(set(forwarded)), [forwarded.count(m) for m in dict.fromkeys(forwarded)])
    # Each notice reaches the parent exactly once and is then acknowledged.
    assert len(forwarded) == len(set(forwarded)) == len(pending)
    assert still == [] and monitor.pending_parent_notices() == []
