"""Managed Adapter identity and control through the actual Session Worker."""

import io
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml

from graphtraj.execution import runner_worker
from graphtraj.execution.runner_connection import session_operation
from graphtraj.execution.runner_heartbeat import ownership_is_held
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError, SessionStarted


class AlternativeExecution:
    """A controlled owner with opaque IDs and no Codex execution object."""

    def __init__(
        self,
        directory: Path,
        created: SessionStarted,
        started: SessionStarted,
        session: str,
        identifier: str,
    ) -> None:
        """Retain callbacks without starting work during construction."""
        self.directory = directory
        self.created = created
        self.started = started
        self.session = session
        self.identifier = identifier
        self.execution_id: str | None = None
        self.ready = threading.Event()
        self.finished = threading.Event()
        self.outcome = 'completed'
        self.inputs: list[str] = []

    def run(self) -> dict:
        """Publish creation before execution; wait for real Worker control."""
        self.created(self.session, os.getpid())
        mapping = yaml.safe_load((self.directory / 'mapping.yml').read_text())
        assert mapping['session'] == self.session
        assert 'execution_id' not in mapping
        assert ownership_is_held(self.directory, os.getpid())
        self.execution_id = self.identifier
        self.started(self.session, os.getpid())
        self.ready.set()
        assert self.finished.wait(5), 'Worker control never reached the Adapter'
        return {
            'session_id': self.session, 'execution_id': self.execution_id,
            'outcome': self.outcome, 'last_agent_message': 'alternative result',
        }

    def operate(self, request: dict) -> dict:
        """Require the exact published identities for every active operation."""
        if (request['session'], request['execution_id']) != (self.session, self.execution_id):
            raise RuntimeAdapterError('operation-failed', 'Wrong execution identity')
        if request['operation'] == 'send':
            self.inputs.append(request['instruction'])
            self.finished.set()
        elif request['operation'] == 'interrupt':
            self.terminate()
        else:
            return {'activity': 'running'}
        return {}

    def terminate(self) -> bool:
        """Finish the controlled invocation as interrupted."""
        self.outcome = 'interrupted'
        self.finished.set()
        return True


def test_worker_uses_selected_adapter_for_launch_control_and_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fresh owners retain the entity and parent while publishing new execution IDs."""
    directory = tmp_path / 'runner/sessions/child@e1'
    directory.mkdir(parents=True)
    base = {
        'alias': directory.name, 'runtime': 'alternative', 'parent': 'parent@l1',
        'ticket_id': '214', 'team_generation': 1, 'role': 'engineer',
        'worktree_path': str(tmp_path), 'trace_file': str(directory / 'trace.jsonl'),
        'retained_batch_file': str(tmp_path / 'batch.yml'),
    }
    parent = directory.with_name('parent@l1')
    parent.mkdir()
    write_yaml_durably(parent / 'mapping.yml', {
        **base, 'alias': parent.name, 'parent': None, 'session': 'parent-session',
        'execution_id': 'parent-execution', 'worker_pid': os.getpid(), 'runtime_pid': os.getpid(),
    })
    owners = []

    class AlternativeAdapter:
        """Supply the same managed construction boundary selected for Codex."""

        def managed_execution(
            self,
            request: dict,
            prompt: str,
            session_directory: Path,
            session_started: SessionStarted,
            context_evidence: dict,
            *,
            trace_file: Path,
            expected_session: str | None,
            session_created: SessionStarted,
        ) -> AlternativeExecution:
            """Consume opaque retained configuration and resume the supplied Session."""
            assert request == {'conversation': 'opaque-session'}
            assert context_evidence == {'alternative': True}
            assert prompt == 'Continue the assigned work.'
            assert trace_file == Path(base['trace_file'])
            owner = AlternativeExecution(
                session_directory, session_created, session_started,
                expected_session or request['conversation'], f'opaque-execution-{len(owners)}',
            )
            owners.append(owner)
            return owner

    def select(runtime: str) -> AlternativeAdapter:
        """Inject only at the existing Runtime selection boundary."""
        assert runtime == 'alternative'
        return AlternativeAdapter()

    monkeypatch.setattr(runner_worker, 'select_runtime_adapter', select)
    mapping = base
    for operation, control, outcome in [
        ('launch', 'send', 'completed'), ('resume', 'interrupt', 'interrupted'),
    ]:
        job = {
            'operation': operation, 'runtime': 'alternative', 'mapping': mapping,
            'adapter_request': {'conversation': 'opaque-session'},
            'context_evidence': {'alternative': True},
        }
        if operation == 'resume':
            job['expected_session'] = mapping['session']
        job_file = directory / f'{operation}.yml'
        write_yaml_durably(job_file, job)
        monkeypatch.setattr('sys.stdin', io.StringIO('Continue the assigned work.'))

        def control_owner() -> dict:
            """Reach the Adapter through the Worker's actual control channel."""
            from conftest import wait_for_file

            wait_for_file(directory / 'mapping.yml')
            # Creation is published before execution; wait for the current owner.
            deadline = time.monotonic() + 5
            while not owners or not owners[-1].ready.is_set():
                assert time.monotonic() < deadline
                time.sleep(0.01)
            current = yaml.safe_load((directory / 'mapping.yml').read_text())
            assert current['parent'] == 'parent@l1'
            assert current['session'] == 'opaque-session'
            assert current['execution_id'] == owners[-1].identifier
            assert session_operation(current, 'status') == {'activity': 'running'}
            assert session_operation(current, control, instruction='finish') == {}
            return current

        # Discard the prior readiness before starting the next Worker invocation.
        if owners:
            owners[-1].ready.clear()
        with ThreadPoolExecutor(max_workers=1) as executor:
            controlled = executor.submit(control_owner)
            assert runner_worker.run(job_file) == 0
            mapping = controlled.result(timeout=5)
        terminal = yaml.safe_load((directory / 'execution.yml').read_text())
        assert terminal == {
            'session_id': 'opaque-session', 'execution_id': owners[-1].identifier,
            'outcome': outcome, 'last_agent_message': 'alternative result',
        }
        assert not ownership_is_held(directory, os.getpid())
    assert owners[0].inputs == ['finish']
    assert owners[0].execution_id != owners[1].execution_id
