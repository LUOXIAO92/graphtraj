"""A Task member's child starts in the member's Worktree, through the real Adapters' preparation."""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from agent_swarm import Caller, bind
from graphtraj.configuration import project_roles, role_definitions
from graphtraj.configuration.project_configuration import runner_directory
from graphtraj.execution import agent_driver, main_continuity, runner_status
from graphtraj.execution.runner_status import runtime_caller
from graphtraj.interfaces.agents import GraphTrajAgents, swarm_root
from graphtraj.interfaces.gateway import handle_request
from graphtraj.interfaces.hosted_cli import agents_dispatch
from graphtraj.runtimes import runtime_adapter
from graphtraj.runtimes.codex import codex_adapter
from test_pi_runtime import pi_environment  # noqa: F401 - the real Pi preparation's native fixtures
from test_result_submission import result_project

RUNTIMES = ['claude', 'codex', 'dsh', 'pi']
MEMBER = 'research@x1'
GATEWAY = 'graphtraj-gateway'


class RecordingTurn:
    """A native owner that keeps what the driver would start the Runtime with."""

    # Set by the fixture for one test.
    started: list[RecordingTurn] = []
    release = threading.Event()

    def __init__(self, request, prompt, directory, started, evidence, **options) -> None:
        """Confirm the native Session as a real owner does before any model work."""
        self.request, self.directory, self.options = request, Path(directory), options
        self.native_id = 'native-' + self.directory.name
        self.agent_call = options.get('agent_call')
        self.extra_fields = None
        type(self).started.append(self)
        options['session_created'](self.native_id, os.getpid())
        started(self.native_id, os.getpid())

    def configure_independent(self, *, agents_callback, extra_fields, **options) -> None:
        """Keep the agents function and archive fields of a Claude Agent."""
        self.agent_call, self.extra_fields = agents_callback, extra_fields

    def run(self) -> dict:
        """Stay running until the test lets it end."""
        type(self).release.wait(20)
        return {'outcome': 'completed'}


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pi_environment: dict) -> SimpleNamespace:  # noqa: F811
    """A project with a real member record and every Adapter's real preparation."""
    root = tmp_path / 'project'
    root.mkdir()
    runner, _, _ = result_project(root)
    worktree = root / 'worktrees/research'
    (worktree / 'sub').mkdir()
    bin_directory = tmp_path / 'bin'

    (bin_directory / 'codex').write_text('#!/bin/sh\nexit 0\n')
    (bin_directory / 'codex').chmod(0o755)
    (bin_directory / 'graphtraj-session').write_text('#!/bin/sh\nexit 0\n')
    (bin_directory / 'graphtraj-session').chmod(0o755)
    package = tmp_path / 'dsh-package'
    (package / 'lib').mkdir(parents=True)
    (package / 'package.json').write_text('{"version": "0.2.2-alpha.2"}')
    (package / 'lib/bin.js').write_text('#!/bin/sh\nexit 0\n')
    (package / 'lib/bin.js').chmod(0o755)
    (bin_directory / 'dsh').symlink_to(package / 'lib/bin.js')
    monkeypatch.setenv('DSH_TEST_KEY', 'set')
    monkeypatch.setattr(codex_adapter, '_require_codex_permissions', lambda executable: None)
    monkeypatch.setattr('graphtraj.runtimes.claude.adapter.current_cli', lambda: ('/installed/claude', '2.0'))

    presets = {name: project_roles.parse_inline_role({name: fields})[1] for name, fields in {
        'claude': {'runtime': 'claude', 'model': 'claude-opus-5-5'},
        'codex': {'runtime': 'codex', 'model': 'chosen-model', 'reasoning_effort': 'low'},
        'dsh': {'runtime': 'dsh', 'model': 'deepseek-official/deepseek-flash', 'api_key_env': 'DSH_TEST_KEY'},
        'pi': {'runtime': 'pi', 'model': 'deepseek/deepseek-flash', 'pi': pi_environment},
    }.items()}
    roles = {name: role_definitions.resolve_child_role(name, preset, root) for name, preset in presets.items()}
    monkeypatch.setattr(project_roles, 'load_project_roles', lambda project: SimpleNamespace(
        presets={name: SimpleNamespace(runtime=name, connection=None) for name in RUNTIMES},
        resolve=lambda name: name))
    monkeypatch.setattr(project_roles, 'resolve_preset', lambda preset: preset)
    monkeypatch.setattr(role_definitions, 'resolve_child_role', lambda name, preset, base: roles[name])

    # The real Adapter prepares; only its native owner is recorded.
    real_select = runtime_adapter.select_runtime_adapter

    def select(name: str) -> SimpleNamespace:
        adapter = real_select(name)
        return SimpleNamespace(preflight_runtime_context=adapter.preflight_runtime_context,
                               managed_execution=RecordingTurn)

    monkeypatch.setattr(agent_driver, 'select_runtime_adapter', select)
    monkeypatch.setattr('graphtraj.runtimes.codex.managed_session.CodexManagedExecution', RecordingTurn)

    from graphtraj.runtimes.dsh import driver as dsh_driver

    bind_agents = dsh_driver.bind_agents

    def bound_dsh(turn, run, driver) -> None:
        """Keep the same call the DSH connection serves."""
        turn.agent_call = run.call
        bind_agents(turn, run, driver)

    monkeypatch.setattr(dsh_driver, 'bind_agents', bound_dsh)
    RecordingTurn.started, RecordingTurn.release = [], threading.Event()
    yield SimpleNamespace(root=root, runner=runner, worktree=worktree.resolve(), tmp=tmp_path)
    RecordingTurn.release.set()
    for thread in threading.enumerate():
        if thread.name.startswith(('agents-', 'codex-')):
            thread.join(20)


def request(runtime: str, **arguments) -> dict:
    """One create that names no directory unless a test asks."""
    return {'action': 'create', 'runtime': runtime, 'instruction': 'w', **arguments}


def member_call(harness: SimpleNamespace, cwd: Path | None = None, alias: str = MEMBER):
    """Enter as the gateway does for a verified member caller."""
    return bind(GraphTrajAgents(harness.root, cwd or harness.root), Caller(GATEWAY, alias))


def record(harness: SimpleNamespace, agent: str) -> dict:
    """Read one Agent's retained record."""
    return json.loads((swarm_root(harness.root) / f'control/agents/{agent}.json').read_text())


def assert_starts_in(runtime: str, directory: Path) -> None:
    """The newest native owner was given ``directory`` as its working directory."""
    request_ = RecordingTurn.started[-1].request
    assert request_['worktree_path'] == str(directory)
    if runtime == 'codex':
        assert request_['session_parameters']['cwd'] == str(directory)


@pytest.mark.parametrize('runtime', RUNTIMES)
def test_a_members_child_starts_in_the_members_worktree(harness: SimpleNamespace, runtime: str) -> None:
    """Without a workspace the child's start, its result and its record all name the Worktree."""
    created = member_call(harness)(request(runtime))
    assert not created.failed, created.document
    assert_starts_in(runtime, harness.worktree)
    assert created.document['result']['workspace'] == str(harness.worktree)
    retained = record(harness, created.document['agent'])
    assert retained['workspace'] == str(harness.worktree) and retained['settings']['cwd'] == str(harness.worktree)
    assert retained['parent'] == MEMBER


@pytest.mark.parametrize('runtime', RUNTIMES)
def test_the_channel_entry_starts_the_child_in_the_worktree(harness: SimpleNamespace, runtime: str) -> None:
    """``cli_connection`` enters the gateway with ``cwd`` at the project root."""
    envelope = {'action': 'execute', 'feature': 'agents', 'arguments': request(runtime)}
    with runtime_caller(harness.runner, MEMBER):
        result = handle_request(envelope, cwd=harness.root, allowed_features={'agents'})
    assert not result.failed, result.document
    assert_starts_in(runtime, harness.worktree)


@pytest.mark.parametrize('runtime', RUNTIMES)
def test_the_entry_without_a_channel_starts_the_child_in_the_worktree(
    harness: SimpleNamespace, runtime: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A member resolved from its process tree, calling from inside its Worktree, gets the Worktree too."""
    monkeypatch.delenv('GRAPHTRAJ_CLI_CONNECTION', raising=False)
    monkeypatch.setattr(runner_status, 'process_caller_alias', lambda runner, pid: MEMBER)
    result = agents_dispatch(request(runtime), harness.worktree / 'sub')
    assert not result.failed, result.document
    assert_starts_in(runtime, harness.worktree)
    assert result.document['result']['workspace'] == str(harness.worktree)


@pytest.mark.parametrize('host', ['root', 'subdirectory', 'outside'])
@pytest.mark.parametrize('runtime', RUNTIMES)
def test_a_grandchild_starts_in_the_inherited_worktree(
    harness: SimpleNamespace, runtime: str, host: str,
) -> None:
    """The child's own call inherits the Worktree, whatever directory the host runs in."""
    if host == 'outside':
        # A configured Worktree Directory can lie outside the project.
        outside = (harness.tmp / 'elsewhere/research').resolve()
        outside.mkdir(parents=True)
        mapping_file = harness.runner / f'sessions/{MEMBER}/mapping.yml'
        mapping = yaml.safe_load(mapping_file.read_text())
        mapping_file.write_text(yaml.safe_dump({**mapping, 'worktree_path': str(outside)}))
        worktree, cwd = outside, harness.root
    else:
        worktree, cwd = harness.worktree, harness.root if host == 'root' else harness.worktree / 'sub'
    created = member_call(harness, cwd)(request(runtime))
    assert not created.failed, created.document
    child = RecordingTurn.started[-1]
    grandchild = child.agent_call(request(runtime))
    assert not grandchild.failed, grandchild.document
    assert RecordingTurn.started[-1] is not child
    assert_starts_in(runtime, worktree)
    assert grandchild.document['result']['workspace'] == str(worktree)
    # Each further level keeps it, and may still narrow it, never widen it.
    great = RecordingTurn.started[-1].agent_call(request(runtime))
    assert not great.failed, great.document
    assert_starts_in(runtime, worktree)
    wider = RecordingTurn.started[-1].agent_call(request(runtime, workspace=str(worktree.parent)))
    assert wider.document['error']['code'] == 'workspace-denied'


def test_a_claude_childs_archive_header_names_the_project(harness: SimpleNamespace) -> None:
    """``projectId`` stays the project, which the Session inventory compares it with."""
    assert not member_call(harness)(request('claude')).failed
    assert RecordingTurn.started[-1].extra_fields['graphtraj']['projectId'] == str(harness.root)


@pytest.mark.parametrize('runtime', RUNTIMES)
def test_an_explicit_workspace_of_a_member_keeps_its_check(harness: SimpleNamespace, runtime: str) -> None:
    """It may narrow the Worktree; another Task's Worktree and the project stay refused."""
    other = harness.root / 'worktrees/other'
    other.mkdir()
    call = member_call(harness)
    narrowed = call(request(runtime, workspace=str(harness.worktree / 'sub')))
    assert narrowed.document['result']['workspace'] == str(harness.worktree / 'sub')
    assert_starts_in(runtime, harness.worktree / 'sub')
    started = len(RecordingTurn.started)
    for refused in (other, harness.root):
        assert call(request(runtime, workspace=str(refused))).document['error']['code'] == 'workspace-denied'
    assert len(RecordingTurn.started) == started


def claimed_main(harness: SimpleNamespace) -> Caller:
    """A verified Main of this project."""
    session = '11111111-1111-4111-8111-111111111111'
    runner = runner_directory(harness.root)
    main_continuity.claim_main(runner, {'runtime': 'claude', 'session': session, 'runner': str(runner)},
                               'claude:first-control')
    return Caller('claude-native', None, session, 'claude')


@pytest.mark.parametrize('runtime', RUNTIMES)
def test_a_mains_child_and_its_descendants_keep_the_host_directory(
    harness: SimpleNamespace, runtime: str,
) -> None:
    """Main's children are unchanged: no recorded workspace, and the host's directory bounds them."""
    host = harness.root / 'hosted'
    host.mkdir()
    agents = GraphTrajAgents(harness.root, host)
    created = bind(agents, claimed_main(harness))(request(runtime))
    assert not created.failed, created.document
    assert created.document['result']['workspace'] is None
    assert_starts_in(runtime, host.resolve())
    child = RecordingTurn.started[-1]
    grandchild = child.agent_call(request(runtime))
    assert not grandchild.failed and grandchild.document['result']['workspace'] is None
    assert_starts_in(runtime, host.resolve())
    assert child.agent_call(request(runtime, workspace=str(harness.worktree))).document['error']['code'] == 'workspace-denied'


@pytest.mark.parametrize('runtime', RUNTIMES)
def test_a_native_identity_keeps_its_default_and_its_refusal(harness: SimpleNamespace, runtime: str) -> None:
    """A native Session or helper is no member: its default stays, as does its explicit refusal."""
    host = harness.root / 'hosted'
    host.mkdir()
    native = bind(GraphTrajAgents(harness.root, host), Caller(GATEWAY, '01a1ffff-native-thread'))
    created = native(request(runtime))
    assert not created.failed, created.document
    assert created.document['result']['workspace'] is None
    assert_starts_in(runtime, host.resolve())
    # The Agent it created is no member's descendant either.
    grandchild = RecordingTurn.started[-1].agent_call(request(runtime))
    assert not grandchild.failed, grandchild.document
    assert_starts_in(runtime, host.resolve())
    refused = native(request(runtime, workspace=str(host)))
    assert refused.document['error']['code'] == 'alias-not-found'


def test_the_gateway_reaches_create_as_a_native_identity_with_the_old_default(harness: SimpleNamespace) -> None:
    """A Codex native helper is bound by its thread ID and reaches ``create``."""
    envelope = {'action': 'execute', 'feature': 'agents', 'arguments': request('claude')}
    with runtime_caller(harness.runner, '01a1ffff-native-thread'):
        result = handle_request(envelope, cwd=harness.root, allowed_features={'agents'})
    assert not result.failed, result.document
    assert_starts_in('claude', harness.root.resolve())


@pytest.mark.parametrize('damage', ['unreadable', 'invalid', 'no-record', 'worktree-gone'])
def test_a_member_without_a_usable_worktree_is_refused_and_never_runs_wider(
    harness: SimpleNamespace, damage: str,
) -> None:
    """The refusal says what is wrong with the member's record, not with an argument it never passed."""
    alias = MEMBER
    mapping_file = harness.runner / f'sessions/{MEMBER}/mapping.yml'
    if damage == 'unreadable':
        mapping_file.write_text('{not yaml')
    elif damage == 'invalid':
        mapping = yaml.safe_load(mapping_file.read_text())
        del mapping['worktree_path']
        mapping_file.write_text(yaml.safe_dump(mapping))
    elif damage == 'no-record':
        alias = 'ghost@x9'
    else:
        shutil.rmtree(harness.worktree)
    refused = member_call(harness, alias=alias)(request('claude'))
    assert refused.failed and refused.document['error']['code'] == 'workspace-denied'
    assert alias in refused.document['error']['message']
    assert 'request.workspace' not in refused.document['error']['message']
    assert RecordingTurn.started == []
    assert list((swarm_root(harness.root) / 'control/agents').glob('*.json')) == []


def test_a_grandchild_is_refused_when_the_members_record_is_lost(harness: SimpleNamespace) -> None:
    """Its boundary cannot be read, so it does not start in the wider host directory."""
    assert not member_call(harness)(request('claude')).failed
    child = RecordingTurn.started[-1]
    shutil.rmtree(harness.runner / f'sessions/{MEMBER}')
    refused = child.agent_call(request('claude'))
    assert refused.failed and refused.document['error']['code'] == 'workspace-denied'
    assert RecordingTurn.started[-1] is child


def test_the_workers_own_member_creation_is_unchanged(harness: SimpleNamespace) -> None:
    """``begin_task_agent`` retains only the alias and records no workspace."""
    from graphtraj.execution.task_agents import begin_task_agent

    mapping = yaml.safe_load((harness.runner / f'sessions/{MEMBER}/mapping.yml').read_text())
    agent = begin_task_agent(harness.root, harness.runner, 'launch', mapping, 'p', SimpleNamespace())
    retained = record(harness, agent.run.agent)
    assert retained['workspace'] is None and retained['settings'] == {'alias': MEMBER}


def wait_until_ended(harness: SimpleNamespace, agent: str) -> None:
    """Let the running execution end so the Agent can be continued."""
    RecordingTurn.release.set()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if all(item.get('ended_at') for item in record(harness, agent)['executions']):
            RecordingTurn.release = threading.Event()
            return
        time.sleep(0.02)
    raise AssertionError('The execution did not end.')


@pytest.mark.parametrize('action', ['send', 'resume'])
@pytest.mark.parametrize('runtime', RUNTIMES)
def test_continuing_keeps_the_retained_directory(harness: SimpleNamespace, runtime: str, action: str) -> None:
    """A child recorded earlier, with no workspace and at the project root, stays there."""
    call = member_call(harness)
    agent = call(request(runtime)).document['agent']
    wait_until_ended(harness, agent)
    path = swarm_root(harness.root) / f'control/agents/{agent}.json'
    earlier = json.loads(path.read_text())
    root = str(harness.root.resolve())
    earlier['workspace'] = None
    earlier['settings']['cwd'] = earlier['settings']['adapter_request']['worktree_path'] = root
    if runtime == 'codex':
        earlier['settings']['adapter_request']['session_parameters']['cwd'] = root
    path.write_text(json.dumps(earlier))

    continued = call({'action': action, 'agent': agent, 'message': 'more'})
    assert not continued.failed, continued.document
    assert_starts_in(runtime, harness.root.resolve())
    retained = record(harness, agent)
    assert retained['workspace'] is None and retained['settings']['cwd'] == root


@pytest.mark.parametrize('runtime', RUNTIMES)
def test_continuing_a_new_child_keeps_the_worktree(harness: SimpleNamespace, runtime: str) -> None:
    """The directory chosen at creation is what every later execution uses."""
    call = member_call(harness)
    agent = call(request(runtime)).document['agent']
    wait_until_ended(harness, agent)
    assert not call({'action': 'send', 'agent': agent, 'message': 'more'}).failed
    assert_starts_in(runtime, harness.worktree)
