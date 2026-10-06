"""Protected public Main operations retain native caller and ownership boundaries."""
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from graphtraj.execution import host_adoption
from graphtraj.execution.runner_connection import connection_operation
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import runtime_caller
from graphtraj.interfaces.cli.graphtraj import main
from test_host_adoption import external
from test_main_finalize import host
from test_host_adoption_allocations import worker_attempt


def test_public_main_operation_and_legacy_parent(external: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the exact registered former host owns a legacy root child's controls."""
    root, _, _ = external
    child = worker_attempt(root, '272-fixture-handover0-engineer@child', monkeypatch,
                           fail=False, parent_connection={'runtime': 'codex', 'session': 'main', 'codex_home': str(root)})
    before = (child / 'mapping.yml').read_bytes()
    with host_adoption.external_main(root) as prepared:
        binding = prepared['operation_binding']
        def call(feature: str, arguments: dict | None = None):
            """Run the supported public command with one reviewable exact request."""
            return CliRunner().invoke(main, ['main-operation', '--binding', binding, '--request',
                json.dumps({'action': 'execute', 'feature': feature, 'arguments': arguments or {}})])
        identity = call('agent_identity')
        assert identity.exit_code == 0, identity.output
        assert json.loads(identity.output)['document']['alias'] == prepared['alias']
        tree = call('alias_status')
        assert tree.exit_code == 0, tree.output
        records = json.loads(tree.output)['document']['agents']
        assert next(item for item in records if item['alias'] == child.name)['parent'] == prepared['alias']
        pending = call('pending_requests', {'alias': child.name})
        assert pending.exit_code == 0, pending.output
        assert json.loads(pending.output)['document']['requests'] == []
        # The hook's old credential never authorizes ordinary operations.
        hook_capability = json.loads(Path(binding).with_name('finish-hook.json').read_text())
        with pytest.raises(RunnerError, match='not authenticated'):
            connection_operation(hook_capability['address'], {'credential': hook_capability['credential'],
                'request': {'action': 'execute', 'feature': 'agent_identity', 'arguments': {}}})
        with runtime_caller(root / '.graphtraj/runner', child.name):
            denied = call('agent_identity')
            assert denied.exit_code != 0
        foreign = CliRunner().invoke(main, ['main-operation', '--binding', str(root / 'other/main-operation.json'),
            '--request', json.dumps({'action': 'execute', 'feature': 'agent_identity', 'arguments': {}})])
        assert foreign.exit_code != 0
    assert (child / 'mapping.yml').read_bytes() == before
    assert not Path(binding).exists()
