"""GraphTraj's own driver: create's workspace, and ask_parent of a Task-free Agent."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_swarm import AgentControl, AgentsResult, Binding, Caller, bind
from graphtraj.configuration.project_configuration import runner_directory
from graphtraj.execution import agent_driver, main_continuity, runner_status
from graphtraj.execution.agent_driver import AdapterDriver
from graphtraj.interfaces.agents import GraphTrajAgents, swarm_root
from graphtraj.workspace import runner_project

RUNTIMES = ['claude', 'codex', 'dsh', 'pi']
MAIN = Caller('test-host', None)


class RecordingAdapter:
    """Keep what the driver asks a Runtime Adapter to prepare."""

    def __init__(self) -> None:
        """Start with no preparation."""
        self.prepared: list[dict] = []

    def preflight_runtime_context(self, **facts) -> SimpleNamespace:
        """Return the settings every Adapter's finalized context provides."""
        self.prepared.append(facts)
        document = {'adapter_request': {'worktree_path': str(facts['worktree'])}, 'connection': {}}
        context = SimpleNamespace(launch_document=lambda: document, evidence_document=lambda: {})
        return SimpleNamespace(finalize=lambda: context)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """A driver over a project whose role and Adapter selection are recorded."""
    from graphtraj.configuration import project_roles, role_definitions

    root = tmp_path / 'project'
    (root / 'inner/deep').mkdir(parents=True)
    (tmp_path / 'outside').mkdir()
    (root / 'link-out').symlink_to(tmp_path / 'outside')
    adapter = RecordingAdapter()

    def presets(project_root: Path) -> SimpleNamespace:
        return SimpleNamespace(presets={name: SimpleNamespace(runtime=name, connection=None) for name in RUNTIMES},
                               resolve=lambda name: name)

    monkeypatch.setattr(project_roles, 'load_project_roles', presets)
    monkeypatch.setattr(project_roles, 'resolve_preset', lambda preset: preset)
    monkeypatch.setattr(role_definitions, 'resolve_child_role', lambda name, preset, base: name)
    monkeypatch.setattr(agent_driver, 'select_runtime_adapter', lambda runtime: adapter)
    driver = AdapterDriver(root, root)
    monkeypatch.setattr(driver, 'start', lambda run: None)
    return SimpleNamespace(root=root, outside=tmp_path / 'outside', adapter=adapter, driver=driver,
                           control=AgentControl(tmp_path / 'data', {name: driver for name in RUNTIMES}))


def create(project: SimpleNamespace, runtime: str = 'claude', caller: Caller = MAIN, **arguments) -> AgentsResult:
    """Create one Agent through the public bound function."""
    return bind(project.control, caller)({'action': 'create', 'runtime': runtime, 'instruction': 'w', **arguments})


@pytest.mark.parametrize('runtime', RUNTIMES)
def test_workspace_replaces_only_the_working_directory(project: SimpleNamespace, runtime: str) -> None:
    """Every Runtime's Adapter prepares for the assigned directory, with the same role."""
    inner = project.root / 'inner'
    created = create(project, runtime, workspace=str(inner))
    assert not created.failed, created.document
    assert created.document['result']['workspace'] == str(inner.resolve())
    facts = project.adapter.prepared[-1]
    assert facts['worktree'] == inner.resolve()
    assert facts['role'] == runtime and facts['harness_root'] == project.root and facts['evidence'] == project.root


@pytest.mark.parametrize('runtime', RUNTIMES)
def test_without_workspace_the_host_directory_stays(project: SimpleNamespace, runtime: str) -> None:
    """A create that assigns nothing is prepared exactly as before."""
    created = create(project, runtime)
    assert not created.failed and created.document['result']['workspace'] is None
    assert project.adapter.prepared[-1]['worktree'] == project.root


@pytest.mark.parametrize(('value', 'code'), [
    ('{outside}', 'workspace-denied'), ('{root}/link-out', 'workspace-denied'),
    ('{root}/missing', 'invalid-input'), ('inner', 'invalid-input'),
])
@pytest.mark.parametrize('runtime', RUNTIMES)
def test_a_workspace_outside_is_refused_before_any_preparation(
    project: SimpleNamespace, runtime: str, value: str, code: str,
) -> None:
    """Links resolve first; nothing reaches the Adapter or the records."""
    refused = create(project, runtime, workspace=value.format(outside=project.outside, root=project.root))
    assert refused.failed and refused.document['error']['code'] == code
    assert project.adapter.prepared == []
    assert bind(project.control, MAIN)({'action': 'status'}).document['result']['agents'] == []


def test_a_grandchild_inherits_or_narrows_and_never_widens(project: SimpleNamespace) -> None:
    """The core's rule holds with GraphTraj's driver."""
    inner = project.root / 'inner'
    parent = create(project, workspace=str(inner)).document['agent']
    caller = Caller('runtime-mcp', parent)
    assert create(project, caller=caller).document['result']['workspace'] == str(inner.resolve())
    deep = create(project, caller=caller, workspace=str(inner / 'deep'))
    assert deep.document['result']['workspace'] == str((inner / 'deep').resolve())
    wider = create(project, caller=caller, workspace=str(project.root))
    assert wider.document['error']['code'] == 'workspace-denied'


def test_a_task_member_narrows_only_its_own_worktree(
    project: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A member's boundary is its recorded Worktree, not the project holding other Worktrees."""
    own, other = project.root / 'inner', project.root / 'other'
    other.mkdir()
    mappings = {'member': {'worktree_path': str(own)}, 'bare': {}}
    monkeypatch.setattr(runner_status, 'read_alias_mapping', lambda runner, alias: (mappings[alias], Path()))
    monkeypatch.setattr(runner_project, 'discover_runner_directory', lambda root: root)
    member = Caller('graphtraj-gateway', 'member')
    assert not create(project, caller=member, workspace=str(own / 'deep')).failed
    assert create(project, caller=member, workspace=str(other)).document['error']['code'] == 'workspace-denied'
    assert create(project, caller=member, workspace=str(project.root)).document['error']['code'] == 'workspace-denied'
    assert (create(project, caller=Caller('graphtraj-gateway', 'bare'), workspace=str(own))
            .document['error']['code']) == 'workspace-denied'


def test_the_dsh_member_request_carries_the_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real DSH Adapter turns it into the directory its sandbox policy uses."""
    import shutil

    from graphtraj.configuration.project_roles import RolePreset
    from graphtraj.configuration.role_definitions import ResolvedChildRole
    from graphtraj.runtimes.runtime_adapter import select_runtime_adapter

    package = tmp_path / 'dsh'
    (package / 'lib').mkdir(parents=True)
    (package / 'package.json').write_text('{"version": "0.2.2-alpha.2"}')
    monkeypatch.setattr(shutil, 'which', lambda name: str(package / 'lib/bin.js')
                        if name == 'dsh' else '/installed/graphtraj-session')
    monkeypatch.setenv('DSH_TEST_KEY', 'set')
    role = ResolvedChildRole('author', 'Task responsibility', RolePreset(
        runtime='dsh', model='deepseek-official/deepseek-flash', base_url=None, api_key_env='DSH_TEST_KEY',
        worktree_access='read'))
    monkeypatch.setattr(agent_driver, 'select_runtime_adapter', lambda runtime: select_runtime_adapter(runtime))
    from graphtraj.configuration import project_roles, role_definitions

    monkeypatch.setattr(project_roles, 'load_project_roles', lambda root: SimpleNamespace(
        presets={'dsh': SimpleNamespace(runtime='dsh', connection=None)}, resolve=lambda name: name))
    monkeypatch.setattr(project_roles, 'resolve_preset', lambda preset: preset)
    monkeypatch.setattr(role_definitions, 'resolve_child_role', lambda name, preset, base: role)
    root = tmp_path / 'project'
    (root / 'part').mkdir(parents=True)
    settings = AdapterDriver(root, root).prepare('dsh', MAIN, workspace=root / 'part')
    assert settings['adapter_request']['worktree_path'] == str((root / 'part').resolve())
    assert settings['cwd'] == str((root / 'part').resolve())
    assert settings['adapter_request']['sandbox'] == 'read-only'


class OwnedTurn:
    """The parts of a native owner ``AdapterDriver.start`` configures."""

    def __init__(self, directory: Path) -> None:
        """Hold the fields the driver reads."""
        self.request = {'worktree_path': '/w', 'harness_root': '/w'}
        self.directory = directory
        self.native_id = 'native'
        self.callback = None

    def configure_independent(self, *, agents_callback, **options) -> None:
        """Keep the agents function the Runtime would call."""
        self.callback = agents_callback

    def run(self) -> dict:
        """End at once."""
        return {'outcome': 'completed'}


def start_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runtime: str, call) -> OwnedTurn:
    """Start one execution on a recorded native owner and return it."""
    turn = OwnedTurn(tmp_path)

    def owner(request, message, directory, started, evidence, **options):
        started('native', 1)
        return turn

    monkeypatch.setattr(agent_driver, 'select_runtime_adapter',
                        lambda name: SimpleNamespace(managed_execution=owner))
    driver = AdapterDriver(tmp_path, tmp_path)
    run = SimpleNamespace(
        agent='agent-1', execution='e1', runtime=runtime, settings={'adapter_request': {}, 'evidence': {}, 'cwd': str(tmp_path)},
        message='m', session=None, directory=tmp_path / 'native', archive=None, extra_fields=None, call=call,
        events=SimpleNamespace(session=lambda *a: None, process=lambda **k: None, finished=lambda *a, **k: None,
                               request=lambda details: None))
    run.directory.mkdir()
    driver.start(run)
    return turn


def test_a_claude_agent_asks_through_the_control_holding_its_parents_receiver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Its other actions keep the Claude Agent's own bound control."""
    asked = []

    def call(request: dict) -> AgentsResult:
        asked.append(request)
        return AgentsResult({'asked': True})

    turn = start_run(tmp_path, monkeypatch, 'claude', call)
    request = {'action': 'ask_parent', 'kind': 'decision', 'question': '?', 'timeout_seconds': 1}
    assert turn.callback(request).document == {'asked': True} and asked == [request]
    assert 'asked' not in turn.callback({'action': 'status'}).document and asked == [request]


def test_a_pi_agent_uses_the_same_owning_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pi's ask_parent reaches the same core call as its other actions."""
    from agent_swarm import default_config

    call = lambda request: AgentsResult({})  # noqa: E731
    default_config(tmp_path)
    (tmp_path / 'one').mkdir()
    turn = start_run(tmp_path / 'one', monkeypatch, 'pi', call)
    assert turn.agent_call is call


class Scripted:
    """A driver whose execution stays running and reports what the test says."""

    def __init__(self) -> None:
        """Start with no run."""
        self.run = None

    def prepare(self, runtime: str, caller: Caller) -> dict:
        """Take no settings."""
        return {}

    def start(self, run) -> None:
        """Hold the running execution."""
        self.run = run
        run.events.session('session-1')
        run.events.process(worker_pid=__import__('os').getpid())

    def requests(self, run) -> list:
        """Report no native request."""
        return []


def graphtraj_agents(root: Path, driver: Scripted) -> GraphTrajAgents:
    """GraphTraj's backend with its real control options over a scripted Runtime."""
    agents = GraphTrajAgents(root, root)
    agents.control.drivers = {'scripted': driver}
    return agents


def test_a_root_agents_question_reaches_the_main_once_and_native_requests_stay_silent(tmp_path: Path) -> None:
    """GraphTraj notifies Main of ask_parent only; a native request keeps its old path."""
    root = tmp_path.resolve()
    runner = runner_directory(root)
    session = '11111111-1111-4111-8111-111111111111'
    connection = {'runtime': 'claude', 'session': session, 'runner': str(runner)}
    main_continuity.claim_main(runner, connection, 'claude:first-control')
    driver = Scripted()
    agents = graphtraj_agents(root, driver)
    caller = Caller('claude-native', None, session, 'claude')
    created = bind(agents, caller)({'action': 'create', 'runtime': 'scripted', 'instruction': 'w'}).document
    assert 'error' not in created, created

    driver.run.events.request({'session': 's', 'execution_id': 'e', 'request_id': 7, 'request_token': 'native',
                               'method': 'native/approval', 'params': {}})
    assert main_continuity.claim_notices(runner, 'claude', session) == []

    child = Caller('runtime-mcp', created['agent'])
    question = {'action': 'ask_parent', 'kind': 'decision', 'question': 'Secret option?', 'timeout_seconds': 0.1}
    first = bind(agents, child)(question).document
    assert first['result']['timed_out'] is True
    assert bind(agents, child)(question).document['result']['timed_out'] is True
    notice, = main_continuity.claim_notices(runner, 'claude', session)
    assert notice['id'] == f"{created['execution']}:request:{first['result']['request']['request_token']}"
    assert notice['event']['alias'] == created['agent'] and 'Secret option' not in str(notice)

    pending = bind(agents, caller)({'action': 'requests', 'agent': created['agent']}).document['result']['requests']
    token = first['result']['request']['request_token']
    request = next(item for item in pending if item.get('request_token') == token)
    reply = bind(agents, caller)({'action': 'reply', 'agent': created['agent'], 'request': request,
                                  'response': {'answer': 'B'}})
    assert reply.document['result']['reply_status'] == 'answered'
    assert bind(agents, child)(question).document['result']['answer'] == 'B'
    assert (swarm_root(root) / 'config.yml').exists()


def test_a_root_caller_is_refused_by_graphtraj_without_a_control_check(tmp_path: Path) -> None:
    """authority-denied holds for Main even where its control policy would refuse differently."""
    from agent_swarm import AgentsError

    agents = graphtraj_agents(tmp_path.resolve(), Scripted())
    with pytest.raises(AgentsError) as refused:
        agents.operate('ask_parent', {'kind': 'decision', 'question': '?', 'timeout_seconds': 1},
                       Binding(Caller('claude-native', None, 'other-session', 'claude')))
    assert refused.value.code == 'authority-denied'


def test_the_public_registration_read_never_raises_for_a_bad_record(tmp_path: Path) -> None:
    """GraphTraj reads a Task member's host and alias through it, missing or unreadable as None."""
    driver = Scripted()
    control = AgentControl(tmp_path, {'scripted': driver})
    agent = bind(control, MAIN)({'action': 'create', 'runtime': 'scripted', 'instruction': 'w'}).document['agent']
    assert control.registration(agent) == {'host': 'test-host', 'parent': None, 'settings': {}}
    assert control.registration('agent-missing') is None
    for text in ('not json', '[]'):
        (tmp_path / 'control/agents/agent-bad.json').write_text(text)
        assert control.registration('agent-bad') is None
    (tmp_path / 'control/agents/agent-bad.json').write_bytes(b'\xff')
    assert control.registration('agent-bad') is None
