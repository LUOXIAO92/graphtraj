"""Shared Agent configuration and Pi binding through the controlled RPC peer."""

from pathlib import Path

import pytest
import yaml

from agent_swarm import Caller, write_config
from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.interfaces.agents import agents_callback, swarm_root
from test_pi_runtime import pi_environment  # noqa: F401


@pytest.mark.parametrize('configuration', [None, 'team.worker'])
def test_pi_shared_driver_preserves_configuration_and_resume(
    tmp_path: Path, pi_environment: dict, configuration: str | None,
) -> None:
    """Selected and default Pi presets coexist with unrelated unavailable connections."""
    project = tmp_path / 'project'
    (project / '.graphtraj').mkdir(parents=True)
    (project / '.graphtraj/config.yml').write_text(default_configuration_content(project, project))
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({'roles': {
        'team': {'worker': {'runtime': 'pi', 'model': 'deepseek/deepseek-flash',
                            'pi': pi_environment}},
        'unavailable': {'connection': 'missing/provider/model'},
    }}))
    write_config(swarm_root(project), save_normalized_sessions=False)
    cwd = project / 'worktrees/research'
    cwd.mkdir(parents=True)
    call = agents_callback(project, Caller('controlled-host', 'parent'), cwd)
    selection = {} if configuration is None else {'configuration': configuration}
    created = call({'action': 'create', 'runtime': 'pi', 'instruction': 'remember-334', **selection})
    assert not created.failed, created.document
    agent, session = created.document['agent'], created.document['session']
    done = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 10})
    assert not done.failed, done.document
    assert 'remember-334' in done.document['result']['last_result']['last_message']
    resumed = call({'action': 'resume', 'agent': agent, 'message': 'continue'})
    assert not resumed.failed, resumed.document
    assert resumed.document['session'] == session
    done = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 10})
    assert not done.failed, done.document
    assert 'remember-334' in done.document['result']['last_result']['last_message']
    assert not (swarm_root(project) / 'sessions').exists()
    assert not (project / '.graphtraj/state/tasks').exists()
