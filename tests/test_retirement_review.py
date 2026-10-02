"""Selected host review stays inside public retirement and its shared callers."""

from pathlib import Path
import sys

import pytest
import yaml

from conftest import InstalledCommands, run_process
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import read_alias_mapping
from graphtraj.graph.delivery_worldline import read_worldline
from graphtraj.interfaces import local_tool
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError
from test_ticket_integration import accepted_ticket


@pytest.mark.parametrize('operation', ['retire', 'replace'])
@pytest.mark.parametrize('decision', ['accept', 'decline', 'error'])
def test_public_retirement_review(
    accepted_ticket: tuple,
    operation: str,
    decision: str,
) -> None:
    """Shared callers apply only the selected host's approval, never an actor flag."""
    root, _, state, _ = accepted_ticket
    runner = root / '.graphtraj/runner'
    mappings = [yaml.safe_load(path.read_text()) for path in (runner / 'sessions').glob('*/mapping.yml')]
    child = next(mapping for mapping in mappings if mapping['parent'] is not None)
    alias = child['alias']
    directory = runner / 'sessions' / alias
    before = (directory / 'mapping.yml').read_bytes()
    observed = []

    def review(proposal: dict) -> dict:
        """Act as the selected host callback and inspect the concrete proposal."""
        assert (directory / 'mapping.yml').read_bytes() == before
        assert proposal['request']['operation'] == operation
        assert proposal['request']['alias'] == alias
        if operation == 'replace':
            registration = proposal['request']['registration']
            assert registration['role'] == child['role']
            assert registration['parent'] == child['parent']
            assert registration['replaces'] == alias
            assert registration['team_ordinal'] == child['team_generation']
            assert proposal['after']['registration'] == registration
        else:
            assert 'registration' not in proposal['request']
        assert proposal['parent'] == child['parent']
        assert proposal['caller'] is None
        observed.append(proposal)
        if decision == 'error':
            raise RuntimeAdapterError('review-failed', 'Selected reviewer unavailable')
        return {'decision': decision}

    # Registration failure makes the replacement's retirement outcome directly
    # observable without starting another model execution.
    if operation == 'replace':
        roles_file = root / '.graphtraj/roles.yml'
        roles = yaml.safe_load(roles_file.read_text())
        roles['roles']['coding_team']['engineer']['instructions'] = 'missing.txt'
        roles_file.write_text(yaml.safe_dump(roles))
    arguments = {'alias': alias}
    if operation == 'replace':
        arguments.update(actor='user', caused_by_event_ids=[read_worldline(state, root)[-1]['event_id']])
    call = local_tool.bind(root, recovery_reviewer=review)
    request = {'action': 'execute', 'feature': operation, 'arguments': arguments}
    if decision == 'accept':
        result = call(request).document
        assert result.get('retire_status') == 'retired' or result.get('completed_actions') == ['retired']
        assert not directory.exists()
        retained, record_directory = read_alias_mapping(runner, alias)
        assert retained == child
        assert yaml.safe_load((record_directory / 'session.yml').read_text())['retirement']
    else:
        with pytest.raises(RunnerError):
            call(request)
        assert (directory / 'mapping.yml').read_bytes() == before
        assert not yaml.safe_load((directory / 'session.yml').read_text()).get('retirement')
    assert len(observed) == 1


def test_cleanup_retries_after_root_retirement(
    accepted_ticket: tuple,
    installed_commands: InstalledCommands,
) -> None:
    """A refused child leaves the retired root and history intact for public retry."""
    root, worktrees, state, _ = accepted_ticket
    integrated = run_process([
        str(installed_commands.product), 'ticket', 'integrate', '--ticket-id', '83',
        '--', sys.executable, '-c', 'pass',
    ], cwd=root)
    assert integrated.returncode == 0, integrated.stdout + integrated.stderr
    runner = root / '.graphtraj/runner'
    mappings = [yaml.safe_load(path.read_text()) for path in (runner / 'sessions').glob('*/mapping.yml')]
    parent = next(mapping for mapping in mappings if mapping['parent'] is None)
    children = [mapping for mapping in mappings if mapping['parent'] is not None]
    assert children
    history = {mapping['alias']: (Path(mapping['trace_file']).read_bytes()) for mapping in mappings}
    seen = []

    def decline(proposal: dict) -> dict:
        """Refuse the first cross-level member after public root retirement."""
        seen.append(proposal['request']['alias'])
        return {'decision': 'decline'}

    call = local_tool.bind(root, recovery_reviewer=decline)
    # Root ownership needs no review. This also reproduces #243's retained root.
    assert call({'action': 'execute', 'feature': 'retire',
                 'arguments': {'alias': parent['alias']}}).document['retire_status'] == 'retired'
    assert seen == []
    request = {'action': 'execute', 'feature': 'cleanup', 'arguments': {'ticket_id': '83'}}
    refused = call(request).document
    assert refused['cleanup_status'] == 'refused'
    assert len(seen) == 1
    assert (worktrees / '83-integration').is_dir()
    assert not (runner / 'sessions' / parent['alias']).exists()

    def accept(proposal: dict) -> dict:
        """Observe unchanged parent identity while permitting each remaining member."""
        assert proposal['caller'] is None
        assert proposal['parent'] == parent['alias']
        seen.append(proposal['request']['alias'])
        return {'decision': 'accept'}

    call = local_tool.bind(root, recovery_reviewer=accept)
    assert call(request).document['cleanup_status'] == 'cleaned'
    assert not (worktrees / '83-integration').exists()
    assert call(request).document['cleanup_status'] == 'already-cleaned'
    for mapping in mappings:
        retained, directory = read_alias_mapping(runner, mapping['alias'])
        assert retained == mapping
        assert Path(mapping['trace_file']).read_bytes() == history[mapping['alias']]
        assert yaml.safe_load((directory / 'session.yml').read_text())['retirement']
