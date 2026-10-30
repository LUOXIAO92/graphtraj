"""The Claude Code and Codex hosts run Task-free Pi children (408).

Each test drives one real host through its public seam, with the real PiDriver
and execution against the controlled Pi peer (pi_rpc_fixture.py). No network,
no real Pi, no real sandbox.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from uuid import uuid4

import pytest
import yaml

from agent_swarm import AgentControl, AgentsError, Caller, bind
import agent_swarm.control
from agent_swarm.claude.host import IndependentCalls, adoption_material, write_adoption
from agent_swarm.codex.host import CodexHost
from agent_swarm.pi import host as pi_host
from agent_swarm.pi.driver import PiDriver
from test_claude_host_cross_runtime import claimed, main_call
from test_codex_host_cross_runtime import Running, events, until
from test_codex_independent_control import native_settings  # noqa: F401 - pytest fixture
from test_pi_runtime import pi_environment  # noqa: F401 - pytest fixture


def install_node(directory: Path) -> None:
    """Put a stand-in ``node`` in ``directory``; only its presence is checked."""
    node = directory / 'node'
    node.write_text('#!/bin/sh\n')
    node.chmod(0o755)


@pytest.fixture
def project(tmp_path: Path, native_settings: dict, pi_environment: dict,
            monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project with a data root beside it, Pi's defaults resolving to the fixtures only."""
    worktree = tmp_path / 'project'
    worktree.mkdir()
    install_node(tmp_path / 'bin')
    # The default home must never reach this machine's real ~/.pi.
    monkeypatch.setenv('PI_CODING_AGENT_DIR', str(tmp_path / 'user-agent'))
    return worktree


# provider and model are all an entry needs; everything else takes its default.
ENTRY = {'provider': 'deepseek', 'model': 'deepseek-flash'}


class ClaudeMain:
    """The Claude Code host seen from its verified Main Session."""

    def __init__(self, project: Path, root: Path, entry: dict, log: Path) -> None:
        """Build the host; a refused entry raises from here as it does at start."""
        self.root = root
        self.host = IndependentCalls(root, project, {}, {'pi': entry})
        self.invoke, self.raw, self.session, self.shown = main_call(self.host, project)

    def attempt(self, feature: str, **arguments: object):
        """Return the raw result of one call, failed or not."""
        return self.raw('agents', {'action': 'execute', 'feature': feature, 'arguments': arguments})

    def call(self, feature: str, **arguments: object) -> dict:
        """Call one feature and require success."""
        return self.invoke(feature, **arguments)

    def notices(self, count: int) -> list[tuple]:
        """Return (alias, event, message) of the first ``count`` notices the mod claims."""
        return [(item['event']['alias'], item['event']['event'], item['event']['message'])
                for item in claimed(self.host, self.session, count, self.shown)]

    def close(self) -> None:
        """Stop what this host still runs."""
        for owned in self.host.control.interrupt_owned():
            deadline = time.monotonic() + 10
            while self.host.control.owns_running(owned) and time.monotonic() < deadline:
                time.sleep(0.05)


class CodexMain:
    """The Codex host seen from its running parent turn."""

    def __init__(self, project: Path, root: Path, entry: dict, log: Path) -> None:
        """Build the host; a refused entry raises from here as it does at start."""
        self.root = root
        self.log = log
        self.running = Running(CodexHost(codex_settings(project, entry), root, 'hold'))

    def attempt(self, feature: str, **arguments: object):
        """Return the raw result of one call, failed or not."""
        return self.running.host._call_agents({'action': feature, **arguments})

    def call(self, feature: str, **arguments: object) -> dict:
        """Call one feature and require success."""
        return self.running.call(feature, **arguments)

    def notices(self, count: int) -> list[tuple]:
        """Return (alias, event, message) of the first ``count`` host events the parent received."""
        deadline = time.monotonic() + 20
        while len(events(self.log)) < count and time.monotonic() < deadline:
            time.sleep(0.02)
        return [(event['alias'], event['event'], event['message']) for event in events(self.log)]

    def close(self) -> None:
        """End the parent turn; the host stops only the children it still runs."""
        self.running.stop()


def codex_settings(project: Path, entry: dict) -> dict:
    """Codex host settings whose worktree is ``project``, with the Pi entry."""
    peer = project.parent / 'codex'
    return {'adapter_request': {
        'arguments': [str(peer)], 'worktree_path': str(project),
        'session_parameters': {'cwd': str(project), 'model': 'chosen-model',
                               'developerInstructions': 'Retain native settings.', 'config': {
            'default_permissions': 'chosen',
            'permissions': {'chosen': {'extends': ':workspace', 'filesystem': {str(project): 'write'}}},
        }},
    }, 'runtimes': {'pi': entry}}


@pytest.fixture(params=[ClaudeMain, CodexMain], ids=['claude', 'codex'])
def main(request: pytest.FixtureRequest, project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Each host with a default Pi entry and a data root outside the project."""
    log = tmp_path / 'host-events.jsonl'
    monkeypatch.setenv('PEER_HOST_EVENTS', str(log))
    made = request.param(project, tmp_path / 'data', dict(ENTRY), log)
    yield made
    made.close()


def ran_with(root: Path, agent: str) -> dict:
    """Return the provider and model the native Pi child actually reported."""
    return yaml.safe_load((root / 'native' / agent / 'session.yml').read_text())['model']


def sent(main, agent: str, message: str) -> dict:
    """Send once the child accepted its first prompt."""
    def attempt() -> dict | None:
        """Return the accepted send's document, or nothing while Pi is still starting."""
        result = main.attempt('send', agent=agent, message=message)
        return None if result.failed else result.document

    return until(attempt)


def test_message_round_trip_and_one_end_notice(main) -> None:
    """Instruction and send reach the same Session; each end reaches the Main once."""
    created = main.call('create', runtime='pi', instruction='wait-hold')
    agent, session = created['agent'], created['session']
    assert created['result']['runtime'] == 'pi' and session

    sent(main, agent, 'finish')
    assert main.notices(1) == [(agent, 'completed', 'wait-hold|finish')]
    # Nothing else arrives for that end; the next one is the next round's.
    continued = main.call('send', agent=agent, message='continue')
    assert continued['session'] == session
    notices = main.notices(2)
    assert len(notices) == 2 and notices[1][:2] == (agent, 'completed')
    assert notices[1][2].endswith('|continue')


@pytest.mark.parametrize('selection, expected', [
    ({}, {'provider': 'deepseek', 'id': 'deepseek-flash'}),
    ({'model': 'other-model', 'reasoning_effort': 'high'}, {'provider': 'openrouter', 'id': 'other-model'}),
])
def test_model_is_chosen_per_child(
    main, monkeypatch: pytest.MonkeyPatch, selection: dict, expected: dict,
) -> None:
    """A create's model and provider replace the entry's for that child only."""
    def discover(connection: dict) -> dict:
        """Stand in for Pi's catalog, which this peer does not list without a selection."""
        return {'runtime': 'pi', 'status': 'available', 'message': 'fake catalog',
                'models': [{'id': 'other-model', 'alias': 'Other', 'provider': 'openrouter',
                            'supported_efforts': None}]}

    monkeypatch.setattr(agent_swarm.control, '_discover_models', discover)
    created = main.call('create', runtime='pi', instruction='answer', **selection)
    assert created['result']['model'] == selection.get('model')
    assert ran_with(main.root, created['agent']) == expected
    argv = json.loads((main.root / 'native' / created['agent'] / 'pi-process.json').read_text())['argv']
    assert ('--thinking' in argv) == ('reasoning_effort' in selection)
    main.notices(1)


def test_declared_connection_and_preset_choose_per_child(project: Path, tmp_path: Path) -> None:
    """config.yml under the moved root selects the child's provider, model and home."""
    home = tmp_path / 'pi-home'
    home.mkdir()
    (home / 'auth.json').write_text('{}')  # existence only; never read
    root = tmp_path / 'data'
    root.mkdir()
    (root / 'config.yml').write_text(
        f'connections:\n  work-pi:\n    runtime: pi\n    home: {home}\n    provider: openrouter\n'
        '    models: [declared-model]\n'
        'presets:\n  reviewer:\n    connection: work-pi\n    model: declared-model\n')
    main = ClaudeMain(project, root, dict(ENTRY), tmp_path / 'unused')
    try:
        main.host.control.require_connections()
        created = main.call('create', runtime='pi', instruction='answer', preset='reviewer')
        assert (created['result']['connection'], created['result']['model']) == ('work-pi', 'declared-model')
        assert ran_with(root, created['agent']) == {'provider': 'openrouter', 'id': 'declared-model'}
        main.notices(1)
    finally:
        main.close()


def test_permission_request_reaches_the_main_once(main) -> None:
    """A native Pi dialog notifies once and is answered through reply; the child then ends."""
    agent = main.call('create', runtime='pi', instruction='dialog')['agent']
    [(alias, event, message)] = main.notices(1)
    assert (alias, event) == (agent, 'request') and 'pi/confirm' in message
    assert main.call('status', agent=agent)['result']['pending_requests'] == 1
    [request] = main.call('requests', agent=agent)['result']['requests']
    main.call('reply', agent=agent, request=request, response={'confirmed': True})
    notices = main.notices(2)
    assert [item[1] for item in notices] == ['request', 'completed']


def test_system_exception_reaches_the_main_once(main) -> None:
    """A provider failure ends the child failed and names the reason to the Main."""
    agent = main.call('create', runtime='pi', instruction='provider-error')['agent']
    assert main.notices(1) == [(agent, 'failed', 'fixture provider rejected request')]


def test_interrupt_and_resume_keep_the_native_session(main) -> None:
    """A stopped child ends interrupted; resume continues its same native Session and history."""
    created = main.call('create', runtime='pi', instruction='wait-first')
    agent, session = created['agent'], created['session']
    until(lambda: not main.attempt('interrupt', agent=agent).failed)
    [(alias, event, _)] = main.notices(1)
    assert (alias, event) == (agent, 'interrupted')

    resumed = main.call('resume', agent=agent, message='second')
    assert resumed['session'] == session
    notices = main.notices(2)
    assert notices[1][:2] == (agent, 'completed')
    assert notices[1][2].startswith('wait-first|') and notices[1][2].endswith('|second')
    records = (main.root / 'native' / agent).rglob('session.jsonl')
    [header] = [json.loads(next(iter(path.open()))) for path in records]
    assert header['id'] == session


def test_a_pi_child_stopped_with_the_claude_host_reaches_the_next_run_once(project: Path, tmp_path: Path) -> None:
    """The end the host's own stop causes is held, then the same Session's next process gets it once."""
    root = tmp_path / 'data'
    first = ClaudeMain(project, root, dict(ENTRY), tmp_path / 'unused')
    agent = first.call('create', runtime='pi', instruction='wait-first')['agent']
    first.close()
    assert first.shown == []

    def run() -> list:
        """One result of the same Session in a new host process."""
        host = IndependentCalls(root, project, {}, {'pi': dict(ENTRY)})
        return host.make_call(first.session, project)('agents', {'action': 'status'}).document.get('main_notices', [])

    [notice] = run()
    assert (notice['event']['alias'], notice['event']['event']) == (agent, 'interrupted')
    assert run() == []


def test_a_pi_child_stopped_with_the_codex_host_reaches_the_next_resume_once(
        project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The end the host's own stop causes is held, then the resumed parent gets one host event."""
    root, log = tmp_path / 'data', tmp_path / 'host-events.jsonl'
    monkeypatch.setenv('PEER_HOST_EVENTS', str(log))
    running = Running(CodexHost(codex_settings(project, dict(ENTRY)), root, 'hold'))
    agent = running.call('create', runtime='pi', instruction='wait-first')['agent']
    running.stop()
    assert events(log) == []

    running = Running(CodexHost(codex_settings(project, dict(ENTRY)), root, 'hold', resume=True))
    [event] = until(lambda: events(log))
    assert (event['alias'], event['event']) == (agent, 'interrupted')
    running.stop()
    running = Running(CodexHost(codex_settings(project, dict(ENTRY)), root, 'hold', resume=True))
    time.sleep(0.2)
    running.stop()
    assert len(events(log)) == 1


def test_default_claude_layout_fails_on_the_real_driver(project: Path, pi_environment: dict) -> None:
    """Why the host refuses it: a data root inside the worktree fails every Pi child at create."""
    root = project / '.agents-control'
    request = pi_host.pi_request(ENTRY, project, {**os.environ, 'AGENT_SWARM_PI_ENTRY': str(
        project.parent / 'bin' / 'pi')})
    call = bind(AgentControl(root, {'pi': PiDriver(request)}), Caller('standalone-host', None))
    created = call({'action': 'create', 'runtime': 'pi', 'instruction': 'answer'})
    assert created.failed, created.document
    error = created.document['result']['last_result']['error']
    assert error['code'] == 'ROLE_CONFIG_UNSUPPORTED', error
    assert str(root.resolve()) in error['message']


def serve_claude_host(config: Path, project: Path) -> str:
    """Run the real ``serve`` under a launcher standing in for Claude; return the first tool answer's text."""
    messages = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                 'params': {'name': 'agents', 'arguments': {'action': 'discover'}}}]
    launcher = ('import subprocess, sys\n'
                'done = subprocess.run([sys.executable, "-m", "agent_swarm.claude.host", "serve", "--config",'
                ' sys.argv[1]], input=sys.stdin.read(), capture_output=True, text=True, timeout=30)\n'
                'sys.stdout.write(done.stdout)\n')
    finished = subprocess.run([sys.executable, '-c', launcher, str(config)], cwd=project, capture_output=True,
                              input=''.join(json.dumps(message) + '\n' for message in messages),
                              text=True, timeout=60)
    return json.loads(finished.stdout.splitlines()[1])['result']['content'][0]['text']


def test_claude_configuration_with_root_moved_starts_and_rewriting_it_refuses(
    project: Path, tmp_path: Path,
) -> None:
    """Only ``root`` has to move; ``configuration --write`` puts it back and the host refuses again."""
    material = adoption_material(project, Path(sys.executable))
    write_adoption(material)
    config = project / '.agents-control' / 'claude-host.json'
    document = json.loads(config.read_text())
    assert document['root'] == str(project.resolve() / '.agents-control')
    document.update(root=str(tmp_path / 'data'), runtimes={'pi': dict(ENTRY)})
    config.write_text(json.dumps(document))

    answer = serve_claude_host(config, project)
    assert 'did not start' not in answer, answer
    assert not (project / '.agents-control' / 'host-refusal.json').exists()

    write_adoption(material)
    answer = json.loads(serve_claude_host(config, project))['error']
    assert answer['code'] == 'invalid-config' and str(project.resolve()) in answer['message'], answer


def build(kind: str, project: Path, root: Path, entry: dict) -> None:
    """Start one host's construction, which raises its start refusal."""
    if kind == 'claude':
        IndependentCalls(root, project, {}, {'pi': entry})
    else:
        CodexHost(codex_settings(project, entry), root, 'never runs')


@pytest.fixture(params=['claude', 'codex'])
def kind(request: pytest.FixtureRequest) -> str:
    """The host under test."""
    return request.param


@pytest.mark.parametrize('entry, named', [
    ({'model': 'm'}, 'provider'),
    ({'provider': 'p'}, 'model'),
    ({**ENTRY, 'colour': 'blue'}, 'colour'),
    ({**ENTRY, 'worktree_path': '/elsewhere'}, 'worktree_path'),
    ({**ENTRY, 'instructions': 3}, 'instructions'),
    ({**ENTRY, 'read_paths': 'docs'}, 'read_paths'),
    ({**ENTRY, 'allowed_domains': 'mirror.example'}, 'allowed_domains'),
    ({**ENTRY, 'base_url': 'https://models.example/v1'}, 'provider_api'),
    ({**ENTRY, 'worktree_access': 'admin'}, 'worktree_access'),
    ({**ENTRY, 'worktree_access': 'write'}, 'git_common_directory'),
])
def test_wrong_settings_are_refused_at_start(
    kind: str, project: Path, tmp_path: Path, entry: dict, named: str,
) -> None:
    """A wrong entry fails the start with invalid-config naming the field."""
    with pytest.raises(AgentsError) as refused:
        build(kind, project, tmp_path / 'data', entry)
    assert refused.value.code == 'invalid-config', refused.value
    assert named in str(refused.value)


def test_data_root_inside_the_worktree_is_refused_at_start(kind: str, project: Path) -> None:
    """Resolved paths decide, so a link does not hide the data root; both paths are named."""
    (project / 'inner').mkdir()
    (project.parent / 'link').symlink_to(project / 'inner')
    for root in (project / '.agents-control', project.parent / 'link', project):
        with pytest.raises(AgentsError) as refused:
            build(kind, project, root, dict(ENTRY))
        assert refused.value.code == 'invalid-config', refused.value
        assert str(root.resolve()) in str(refused.value) and str(project.resolve()) in str(refused.value)


def only(tmp_path: Path, tool: str) -> str:
    """Return a sandbox_path directory holding ``tool`` alone."""
    directory = tmp_path / ('only-' + tool)
    directory.mkdir()
    target = directory / tool
    target.write_text('#!/bin/sh\n')
    target.chmod(0o755)
    return str(directory)


@pytest.mark.parametrize('missing, setting', [('srt', 'sandbox_path'), ('node', 'sandbox_path')])
def test_missing_sandbox_tool_is_refused_at_start(
    kind: str, project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str, setting: str,
) -> None:
    """srt and node are looked for on the PATH the child gets; no credential reaches the message."""
    if shutil.which(missing, path=str(Path(sys.executable).parent)):
        pytest.skip(f"{missing} sits beside this Python, which is always on the child's PATH")
    monkeypatch.setenv('AGENTS_408_KEY', 'fixture-secret-408')
    present = 'node' if missing == 'srt' else 'srt'
    entry = {**ENTRY, 'api_key_env': 'AGENTS_408_KEY', 'sandbox_path': only(tmp_path, present)}
    with pytest.raises(AgentsError) as refused:
        build(kind, project, tmp_path / 'data', entry)
    assert refused.value.code == 'runtime-unavailable', refused.value
    assert missing in str(refused.value) and setting in str(refused.value)
    assert 'fixture-secret-408' not in str(refused.value)


def test_default_pi_executable_missing_is_refused_at_start(
    kind: str, project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ``pi`` on the host's PATH, and no setting naming another."""
    (tmp_path / 'bin/pi').unlink()
    monkeypatch.setenv('PATH', str(tmp_path / 'bin'))
    with pytest.raises(AgentsError) as refused:
        build(kind, project, tmp_path / 'data', dict(ENTRY))
    assert refused.value.code == 'runtime-unavailable', refused.value
    assert 'executable' in str(refused.value)


def test_configured_pi_executable_missing_is_refused_at_start(kind: str, project: Path, tmp_path: Path) -> None:
    """A named executable that does not exist fails the start, naming it and the setting."""
    with pytest.raises(AgentsError) as refused:
        build(kind, project, tmp_path / 'data', {**ENTRY, 'executable': str(tmp_path / 'no-pi')})
    assert refused.value.code == 'runtime-unavailable', refused.value
    assert 'no-pi' in str(refused.value) and 'executable' in str(refused.value)


@pytest.mark.parametrize('broken', ['no-import', 'no-python'])
def test_sandbox_python_without_agent_sandbox_is_refused_at_start(
    kind: str, project: Path, tmp_path: Path, broken: str,
) -> None:
    """The Python must run and import agent_sandbox, as launch.py will."""
    entry = dict(ENTRY)
    if broken == 'no-import':
        (tmp_path / 'agent_sandbox/__init__.py').write_text('raise ImportError("not installed")\n')
    else:
        entry['sandbox_python'] = str(tmp_path / 'no-python')
    with pytest.raises(AgentsError) as refused:
        build(kind, project, tmp_path / 'data', entry)
    assert refused.value.code == 'runtime-unavailable', refused.value
    assert 'agent_sandbox' in str(refused.value) and 'sandbox_python' in str(refused.value)


def test_unset_api_key_env_is_refused_at_start(
    kind: str, project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A named key variable must be set; its name and the setting are reported."""
    monkeypatch.delenv('AGENTS_408_UNSET_KEY', raising=False)
    with pytest.raises(AgentsError) as refused:
        build(kind, project, tmp_path / 'data', {**ENTRY, 'api_key_env': 'AGENTS_408_UNSET_KEY'})
    assert refused.value.code == 'runtime-unavailable', refused.value
    assert 'AGENTS_408_UNSET_KEY' in str(refused.value) and 'api_key_env' in str(refused.value)


def test_no_login_or_catalog_is_checked_at_start(kind: str, project: Path, tmp_path: Path) -> None:
    """A Pi with no login file and no catalog still starts the host; those fail at create."""
    (tmp_path / 'bin/pi').write_text('#!/bin/sh\nexit 9\n')
    build(kind, project, tmp_path / 'data', dict(ENTRY))
