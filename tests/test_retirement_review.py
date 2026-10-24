"""Selected host review stays inside public retirement and its shared callers."""

from pathlib import Path
import sys

import pytest
import yaml

from conftest import InstalledCommands, run_process
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_retirement import retire_session
from graphtraj.execution.runner_status import read_alias_mapping
from graphtraj.graph.delivery_worldline import read_worldline
from graphtraj.interfaces import local_tool
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError, recovery_review
from test_task_integration import accepted_task


@pytest.mark.parametrize('operation', ['retire', 'replace'])
@pytest.mark.parametrize('decision', ['accept', 'decline', 'error'])
def test_public_retirement_review(
    accepted_task: tuple,
    operation: str,
    decision: str,
) -> None:
    """Shared callers apply only the selected host's approval, never an actor flag."""
    root, _, state, _ = accepted_task
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

    def operate() -> dict:
        """Exercise retirement's shared Runner API or the public Task replacement."""
        if operation == 'retire':
            with recovery_review(review):
                return retire_session(alias, root)
        return call(request).document

    if decision == 'accept':
        result = operate()
        assert result.get('retire_status') == 'retired' or result.get('completed_actions') == ['retired']
        assert not directory.exists()
        retained, record_directory = read_alias_mapping(runner, alias)
        assert retained == child
        assert yaml.safe_load((record_directory / 'session.yml').read_text())['retirement']
    else:
        with pytest.raises(RunnerError):
            operate()
        assert (directory / 'mapping.yml').read_bytes() == before
        assert not yaml.safe_load((directory / 'session.yml').read_text()).get('retirement')
    assert len(observed) == 1


def test_cleanup_preserves_members_after_root_retirement(
    accepted_task: tuple,
    installed_commands: InstalledCommands,
) -> None:
    """Task cleanup preserves members and does not request their separate retirement."""
    root, worktrees, state, _ = accepted_task
    integrated = run_process([
        str(installed_commands.product), 'task', 'integrate', '--task-id', '83',
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
    assert retire_session(parent['alias'], root)['retire_status'] == 'retired'
    assert seen == []
    request = {'action': 'execute', 'feature': 'cleanup', 'arguments': {'task_id': '83'}}
    assert call(request).document['cleanup_status'] == 'cleaned'
    assert seen == []
    assert not (worktrees / '83-integration').exists()
    assert call(request).document['cleanup_status'] == 'already-cleaned'
    for mapping in mappings:
        retained, directory = read_alias_mapping(runner, mapping['alias'])
        assert retained == mapping
        assert Path(mapping['trace_file']).read_bytes() == history[mapping['alias']]
        assert bool(yaml.safe_load((directory / 'session.yml').read_text()).get('retirement')) == (mapping == parent)
        if mapping != parent:
            assert directory == runner / 'sessions' / mapping['alias']
