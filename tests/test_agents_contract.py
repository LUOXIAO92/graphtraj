"""The independent agents function: isolation, validation, binding and dispatch."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import agent_swarm
from agent_swarm import AgentsError, Caller, Outcome
from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.execution.runner_status import runtime_caller
from graphtraj.interfaces import gateway


SOURCE = Path(__file__).resolve().parents[1] / 'src'


class RecordingBackend:
    """Record what the contract passes on and answer with fixed references."""

    def __init__(self) -> None:
        """Start with no recorded calls."""
        self.calls = []

    def operate(self, action, arguments, binding):
        """Return references for create and reject an unknown target."""
        self.calls.append((action, dict(arguments), binding))
        if arguments.get('agent') == 'missing':
            raise AgentsError('not-found', 'No such Agent.')
        return Outcome({'state': 'registered'}, agent='a1', session='s1', execution='e1')


def test_contract_imports_without_graphtraj() -> None:
    """The package loads with no GraphTraj module in the process."""
    code = ('import sys, agent_swarm; '
            'print(sorted(m for m in sys.modules if m.split(".")[0] == "graphtraj"))')
    output = subprocess.run(
        [sys.executable, '-c', code], check=True, capture_output=True, text=True,
        env={**os.environ, 'PYTHONPATH': str(SOURCE)},
    ).stdout
    assert json.loads(output.replace("'", '"')) == []


def test_bind_requires_the_host_verified_caller() -> None:
    """A missing or model-shaped caller cannot bind the function."""
    for caller in (None, {'host': 'codex', 'agent': 'main'}, Caller('', 'a1')):
        with pytest.raises(TypeError):
            agent_swarm.bind(RecordingBackend(), caller)


@pytest.mark.parametrize('request_document', [
    {'action': 'spawn'},
    {'action': 'send', 'agent': 'a1'},
    {'action': 'send', 'agent': 'a1', 'message': '  '},
    {'action': 'status', 'caller': 'main'},
    {'action': 'status', 'session': 'forged'},
    {'action': 'status', 'task_id': '1'},
    {'action': 'create', 'runtime': 'codex', 'instruction': 'hi', 'timeout_seconds': 5},
    {'action': 'wait', 'agent': 'a1'},
    {'action': 'wait', 'agent': 'a1', 'timeout_seconds': 0},
    {'action': 'wait', 'agent': 'a1', 'timeout_seconds': float('inf')},
    {'action': 'wait', 'agent': 'a1', 'timeout_seconds': True},
    ['status'],
])
def test_invalid_requests_never_reach_the_backend(request_document) -> None:
    """Unknown actions, identity fields and implicit or unbounded waits are rejected."""
    backend = RecordingBackend()
    result = agent_swarm.bind(backend, Caller('test-host', 'a0'))(request_document)
    assert result.failed
    assert result.document['error']['code'] == 'invalid-input'
    assert backend.calls == []


def test_valid_requests_carry_host_caller_and_references() -> None:
    """The backend sees only action fields plus the host caller; results carry references."""
    backend = RecordingBackend()
    caller  = Caller('test-host', 'a0', session='s0', runtime='codex')
    call    = agent_swarm.bind(backend, caller)

    created = call({'action': 'create', 'runtime': 'codex', 'instruction': 'Summarize.'})
    waited  = call({'action': 'wait', 'agent': 'a1', 'timeout_seconds': 1.5})
    missing = call({'action': 'status', 'agent': 'missing'})

    assert not created.failed
    assert created.document == {'action': 'create', 'agent': 'a1', 'session': 's1',
                                'execution': 'e1', 'message': None,
                                'result': {'state': 'registered'}}
    assert not waited.failed
    assert missing.failed
    assert missing.document == {'action': 'status',
                                'error': {'code': 'not-found', 'message': 'No such Agent.'}}
    assert [entry[:2] for entry in backend.calls] == [
        ('create', {'runtime': 'codex', 'instruction': 'Summarize.'}),
        ('wait', {'agent': 'a1', 'timeout_seconds': 1.5}),
        ('status', {'agent': 'missing'}),
    ]
    assert {entry[2].caller for entry in backend.calls} == {caller}
    assert {entry[2].archive for entry in backend.calls} == {None}


def test_gateway_serves_agents_through_the_core(tmp_path: Path, monkeypatch) -> None:
    """CLI/MCP/local hosts reach the same core; an undriven Runtime is named."""
    configuration = tmp_path / '.graphtraj/config.yml'
    configuration.parent.mkdir()
    configuration.write_text(default_configuration_content(tmp_path, tmp_path))
    monkeypatch.chdir(tmp_path)

    discovered = gateway.handle_request({'action': 'discover', 'query': 'agents'})
    schema     = gateway.handle_request({'action': 'describe', 'feature': 'agents', 'schema': True})
    create     = {'action': 'execute', 'feature': 'agents', 'arguments': {
        'action': 'create', 'runtime': 'codex', 'instruction': 'Summarize.',
    }}
    anonymous  = gateway.handle_request(create, cwd=tmp_path)
    with runtime_caller(tmp_path / '.graphtraj/runner', 'main-a'):
        created = gateway.handle_request(create, cwd=tmp_path)
    forged     = gateway.handle_request({'action': 'execute', 'feature': 'agents', 'arguments': {
        'action': 'status', 'caller': 'main',
    }}, cwd=tmp_path)

    assert 'agents' in {item['feature'] for item in discovered.document['features']}
    assert schema.document['input_schema'] == agent_swarm.INPUT_SCHEMA
    assert anonymous.failed and anonymous.document['error']['code'] == 'authority-unavailable'
    assert created.failed
    assert created.document['error']['code'] == 'unsupported-runtime'
    assert forged.failed

    # GraphTraj turns archiving on in the tool's own config, not in core.
    assert (tmp_path / '.graphtraj/swarm/config.yml').read_text() == 'save_normalized_sessions: true\n'
    assert 'swarm' not in configuration.read_text()
