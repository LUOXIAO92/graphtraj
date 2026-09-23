"""Temporary activation uses the invoking Runner, without another Team driver."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.execution.runner_launch import launch_swarm
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import read_alias_mapping, runtime_caller
from graphtraj.graph.ticket_graph import register_ticket
from graphtraj.teams.coding import team_round


@pytest.mark.parametrize('parent_role', ['team-leader', 'engineer'])
def test_temporary_activation_uses_current_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, parent_role: str,
) -> None:
    """An authorized parent gets a launched child; a member cannot dispatch it."""
    runner = tmp_path / '.graphtraj/runner'
    parent_directory = runner / 'sessions/parent@l1'
    parent_directory.mkdir(parents=True)
    (tmp_path / '.graphtraj/config.yml').write_text(default_configuration_content(tmp_path, tmp_path))
    state = tmp_path / '.graphtraj/state'
    register_ticket(state, tmp_path, {
        'ticket_id': '133', 'ticket_name': 'activation', 'title': 'Activation',
        'body': 'Read-only activation check.', 'dependencies': [],
        'source': 'https://github.com/example/project/issues/133',
    })
    parent = {
        'alias': 'parent@l1', 'runtime': 'codex', 'session': 'parent-native',
        'ticket_id': '133', 'team_generation': 1, 'role': parent_role,
        'parent': None, 'retained_batch_file': 'unused', 'worktree_path': str(tmp_path),
        'trace_file': 'unused', 'worker_pid': 1, 'runtime_pid': 1,
    }
    (parent_directory / 'mapping.yml').write_text(yaml.safe_dump(parent))
    project = SimpleNamespace(harness_root=tmp_path, state_directory=state,
                              runner_directory=runner, max_concurrency=2)
    monkeypatch.setattr(team_round, 'discover_project', lambda *args, **kwargs: project)
    launches = []

    def launch(*args: object, **kwargs: object) -> tuple[str, str]:
        """Substitute only the Agent execution beyond the real public activation."""
        launches.append((args, kwargs))
        mapping = {**parent, 'alias': 'child@e1', 'session': 'child-native',
                   'execution_id': 'child-turn', 'parent': args[9], 'role': 'probe'}
        directory = runner / 'sessions/child@e1'
        directory.mkdir()
        (directory / 'mapping.yml').write_text(yaml.safe_dump(mapping))
        return 'child@e1', 'child-native'

    monkeypatch.setattr(team_round, '_run_agent', launch)
    swarm = {'tasks': [{'role': {'probe': {'runtime': 'codex', 'model': 'configured-model'}},
                        'instruction': 'Read-only check.'}]}
    with runtime_caller(runner, 'parent@l1'):
        if parent_role != 'team-leader':
            with pytest.raises(RunnerError) as error:
                launch_swarm(swarm, tmp_path)
            assert error.value.code == 'authority-denied'
            assert not launches
            return
        response = launch_swarm(swarm, tmp_path)

    assert response.document['tasks'][0]['launch_status'] == 'launched'
    assert response.document['tasks'][0]['session'] == 'child-native'
    assert read_alias_mapping(runner, 'child@e1')[0]['parent'] == 'parent@l1'
    assert not (parent_directory / 'child-registration.yml').exists()
    assert not (state / 'tickets/133-activation/teams/1/team.yml').exists()
