"""A child's record and results name the role preset and model it ran with (455).

GraphTraj's driver resolves ``configuration`` (or the Runtime's sole preset)
into the launch request; the core records what it applied. The controlled
official-CLI peer stands in for Claude, as in test_agents_native_claude.py.
"""

import json
from pathlib import Path

import pytest
import yaml

import graftling
from graftling import AgentControl, Caller
from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.interfaces.agents import swarm_root
from test_agents_connections_presets import CONFIG, RecordingDriver, configured
from test_agents_native_claude import agents
from test_claude_runtime import claude_environment  # noqa: F401 - pytest fixture

KEYS = ('configuration', 'preset', 'model', 'reasoning_effort')


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A GraphTraj project with a default Claude role and an advisor preset."""
    root = tmp_path / 'project'
    (root / '.graphtraj').mkdir(parents=True)
    (root / '.graphtraj/config.yml').write_text(default_configuration_content(root, root))
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {
            'claude':  {'runtime': 'claude', 'model': 'claude-opus-5-5'},
            'advisor': {'runtime': 'claude', 'model': 'claude-opus-5-5', 'reasoning_effort': 'high'},
        },
        'role_tree': {'claude': {}, 'advisor': {}},
    }))
    return root


def stored(project: Path, agent: str) -> dict:
    """The Agent's record file as the core keeps it."""
    return json.loads((swarm_root(project) / 'control' / 'agents' / f'{agent}.json').read_text())


def lifecycle(project: Path, **create) -> tuple[list[dict], dict]:
    """Create, wait, status (single and tree) and retire one child; return the documents."""
    cwd = project / 'scratch'
    cwd.mkdir(exist_ok=True)
    created, failed = agents(project, cwd, 'main-a', action='create', runtime='claude',
                             instruction='hello', **create)
    assert not failed, created
    agent = created['agent']
    waited, _ = agents(project, cwd, 'main-a', action='wait', agent=agent, timeout_seconds=20)
    assert waited['result']['state'] == 'standby', waited
    single, _ = agents(project, cwd, 'main-a', action='status', agent=agent)
    tree, _ = agents(project, cwd, 'main-a', action='status')
    retired, failed = agents(project, cwd, 'main-a', action='retire', agent=agent)
    assert not failed, retired
    node = next(node for node in tree['result']['agents'] if node['agent'] == agent)
    results = [created['result'], waited['result'], single['result'], node, retired['result']]
    return results, stored(project, agent)


def test_configuration_child_records_its_preset_and_model(project: Path, claude_environment: None) -> None:
    results, record = lifecycle(project, configuration='advisor')
    expected = {'configuration': 'advisor', 'preset': None,
                'model': 'claude-opus-5-5', 'reasoning_effort': 'high'}
    for result in results:
        assert {key: result[key] for key in KEYS} == expected, result
    assert {key: record['selection'][key] for key in KEYS} == expected
    # The record keeps only launch data in settings, and it launched that model.
    assert 'applied' not in record['settings']
    assert record['settings']['adapter_request']['model'] == 'claude-opus-5-5'


def test_default_child_records_the_resolved_runtime_preset(project: Path, claude_environment: None) -> None:
    results, record = lifecycle(project)
    for result in results:
        assert (result['configuration'], result['model'], result['reasoning_effort']) != ('advisor', 'claude-opus-5-5', 'high')
        assert (result['configuration'], result['model']) == ('claude', 'claude-opus-5-5'), result
    assert record['selection']['configuration'] == 'claude'


CALLER = Caller('test-host', None, 'main-session', 'claude')


class AppliedDriver(RecordingDriver):
    """Reports what it applied, as GraphTraj's driver does."""

    def prepare(self, runtime, caller, *, configuration=None, selection=None):
        super().prepare(runtime, caller, configuration=configuration, selection=selection)
        return {'runtime': runtime, 'applied': {'configuration': configuration or 'own',
                                                'model': 'driver-model', 'reasoning_effort': 'low'}}


def run(control: AgentControl, **arguments) -> dict:
    call = graftling.bind(control, CALLER)
    created = call({'action': 'create', 'runtime': 'claude', 'instruction': 'Work.', **arguments})
    assert not created.failed, created.document
    agent = created.document['agent']
    call({'action': 'wait', 'agent': agent, 'timeout_seconds': 5})
    return call({'action': 'retire', 'agent': agent}).document['result']


def test_a_driver_that_reports_nothing_leaves_the_fields_null(tmp_path: Path) -> None:
    result = run(AgentControl(tmp_path / 'root', {'claude': RecordingDriver()}))
    assert {key: result[key] for key in KEYS} == dict.fromkeys(KEYS)


def test_an_explicit_selection_is_not_overwritten(tmp_path: Path) -> None:
    control = AgentControl(configured(tmp_path / 'root', CONFIG), {'claude': AppliedDriver()})
    result = run(control, preset='reviewer')
    # config.yml's preset chose model and effort; the driver's names only its configuration.
    assert {key: result[key] for key in KEYS} == {
        'configuration': 'own', 'preset': 'reviewer', 'model': 'claude-sonnet-5-5', 'reasoning_effort': 'high'}
    filled = run(AgentControl(tmp_path / 'other', {'claude': AppliedDriver()}), configuration='x')
    assert {key: filled[key] for key in KEYS} == {
        'configuration': 'x', 'preset': None, 'model': 'driver-model', 'reasoning_effort': 'low'}
