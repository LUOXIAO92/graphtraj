"""Any host starts a DSH child without GraphTraj (383).

The Claude Code host and the Codex host register DshDriver from their
``runtimes`` tables. A controlled DshService (dsh_standalone_peer.py) stands in
for the native service; no network, model or real DSH process is used except
where the installed DSH and Node are required and said so.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from typing import Callable, Sequence
from uuid import uuid4

import pytest
import yaml

from agent_swarm import AgentsError, Caller, bind
from agent_swarm.claude.host import IndependentCalls
from agent_swarm.codex.host import CodexHost
from agent_swarm.dsh import execution
from agent_swarm.dsh.settings import prepare
from dsh_standalone_peer import FakeDshService, install_dsh
from test_codex_independent_control import native_settings  # noqa: F401 - pytest fixture

ROOT = Path(__file__).resolve().parents[1]
KEY = 'never-shown-383-key'
AMBIENT = {'DEEPSEEK_BASE_URL': 'https://ambient.invalid', 'DEEPSEEK_SEARCH_BASE_URL': 'https://ambient-search.invalid'}
OFFICIAL = 'https://api.deepseek.com/anthropic'
DECLARED = 'https://declared.invalid/anthropic'
CONFIG = """connections:
  work-dsh:
    runtime: dsh
    home: {home}
    api_key_env: DSH_383_KEY
    models:
      - id: deepseek-v5
        supported_efforts: [low, high]
"""


@pytest.fixture
def dsh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """A stand-in DSH 0.2.2-alpha.2 install, a key, no GRAPHTRAJ_* variable and the fake service."""
    for name in [name for name in os.environ if name.startswith('GRAPHTRAJ_')]:
        monkeypatch.delenv(name)
    monkeypatch.setenv('DSH_383_KEY', KEY)
    monkeypatch.setattr(execution.DshExecution, 'service_type', FakeDshService)
    FakeDshService.instances = []
    executable = install_dsh(tmp_path / 'dsh')
    return {'executable': str(executable), 'model': 'deepseek-flash', 'sandbox': 'workspace-write'}


def declare(root: Path, tmp_path: Path) -> Path:
    """Declare one DSH connection with its own home, key variable and models."""
    home = tmp_path / 'dsh-connection-home'
    home.mkdir()
    root.mkdir(parents=True, exist_ok=True)
    (root / 'config.yml').write_text(CONFIG.format(home=home))
    return home


def until(check, timeout: float = 20):
    deadline = time.monotonic() + timeout
    while not (value := check()):
        assert time.monotonic() < deadline, 'condition not reached'
        time.sleep(0.02)
    return value


def selected(service: FakeDshService) -> dict:
    """The session/selectModel body the native service received."""
    return next(body for method, body in service.calls if method == 'session/selectModel')


def prompts(service: FakeDshService) -> list[str]:
    return [body['content'][0]['text'] for method, body in service.calls if method == 'session/prompt']


def answered(invoke: Callable, agent: str, shown: Sequence[dict] = ()) -> dict:
    """Wait for an end and return it with the body the Main got, which it must get exactly once.

    The wait shows it, unless an earlier result already carried it as a notice: a
    quick child can end before its own create, send or resume returns.
    """
    last    = invoke('wait', agent=agent, timeout_seconds=10)['result']['last_result']
    carried = [notice['event']['message'] for notice in shown
               if (notice['event']['execution'], notice['event']['event']) == (last['id'], last['outcome'])]
    bodies  = carried + ([last['last_message']] if last['last_message'] is not None else [])
    assert len(bodies) == 1, (last, carried)
    return {**last, 'last_message': bodies[0]}


def check_round_trip(invoke: Callable, shown: Sequence[dict] = ()) -> None:
    """Create with connection, model and effort; answer; continue the same native Session."""
    created = invoke('create', runtime='dsh', instruction='first task', model='deepseek-v5',
                     reasoning_effort='high')
    agent = created['agent']
    assert (created['result']['runtime'], created['result']['connection'], created['result']['model'],
            created['result']['reasoning_effort']) == ('dsh', 'work-dsh', 'deepseek-v5', 'high')
    done = answered(invoke, agent, shown)
    assert (done['outcome'], done['last_message']) == ('completed', 'dsh answer: first task')
    [first] = FakeDshService.instances
    assert selected(first) == {'sessionId': first.session, 'provider': 'deepseek-official',
                               'model': 'deepseek-v5', 'reasoningEffort': 'high'}

    invoke('send', agent=agent, message='second task')
    assert answered(invoke, agent, shown)['last_message'] == 'dsh answer: second task'
    invoke('resume', agent=agent, message='third task')
    assert answered(invoke, agent, shown)['last_message'] == 'dsh answer: third task'
    # Each continuation asked DSH for the same native Session and kept the child's choice.
    first_service, *continued = FakeDshService.instances
    assert len(continued) == 2
    for service in continued:
        # DSH after 0.2.0-rc.2 resumes the stored Session by address, not by session/create.
        assert service.session == first_service.session
        assert not [call for call in service.calls if call[0] == 'session/create']
        assert selected(service)['model'] == 'deepseek-v5'
    assert [prompts(service) for service in FakeDshService.instances] == [
        ['first task'], ['second task'], ['third task']]
    [node] = invoke('status')['result']['agents']
    assert (node['agent'], node['runtime'], node['parent'], node['state']) == (agent, 'dsh', None, 'standby')
    assert KEY not in json.dumps(invoke('status', agent=agent))


@pytest.mark.parametrize('version', ['0.2.0-rc.2', '0.2.1-alpha.5', '0.2.2-alpha.2'])
def test_send_and_resume_continue_the_same_dsh_session(tmp_path: Path, dsh: dict, version: str) -> None:
    """rc.2 resumes through session/create; later DSH mints there, so the driver addresses the Session."""
    dsh = {**dsh, 'executable': str(install_dsh(tmp_path / f'dsh-{version}', version))}
    host = IndependentCalls(tmp_path / 'agents', tmp_path, {}, {'dsh': dsh})
    invoke, _, _ = claude_main(host, tmp_path)
    try:
        agent = invoke('create', runtime='dsh', instruction='one')['agent']
        answered(invoke, agent, invoke.shown)
        invoke('send', agent=agent, message='two')
        assert answered(invoke, agent, invoke.shown)['last_message'] == 'dsh answer: two'
        invoke('resume', agent=agent, message='three')
        last = answered(invoke, agent, invoke.shown)
        assert (last['outcome'], last['last_message']) == ('completed', 'dsh answer: three')
        first, *continued = FakeDshService.instances
        assert [service.session for service in continued] == [first.session, first.session]
        creates = [[body for method, body in service.calls if method == 'session/create'] for service in continued]
        expected = {'cwd': str(tmp_path), 'sessionId': first.session}
        assert creates == ([[expected], [expected]] if version == '0.2.0-rc.2' else [[], []])
        assert invoke('status', agent=agent)['result']['session'] == first.session
    finally:
        stop_owned(host.control)


def test_a_missing_stored_dsh_session_is_not_resumable(tmp_path: Path, dsh: dict) -> None:
    """Newer DSH answers session/not-found; the child reports RUNTIME_SESSION_NOT_RESUMABLE."""
    host = IndependentCalls(tmp_path / 'agents', tmp_path, {}, {'dsh': dsh})
    invoke, call, _ = claude_main(host, tmp_path)
    agent = invoke('create', runtime='dsh', instruction='one')['agent']
    invoke('wait', agent=agent, timeout_seconds=10)
    for log in (FakeDshService.instances[0].logs / 'workspace').rglob('v4.jsonl'):
        log.unlink()
    result = call('agents', {'action': 'execute', 'feature': 'resume', 'arguments': {'agent': agent, 'message': 'two'}})
    assert result.failed
    error = json.dumps(result.document)
    assert 'RUNTIME_SESSION_NOT_RESUMABLE' in error and 'session/not-found' in error, error
    assert not [call for call in FakeDshService.instances[1].calls if call[0] == 'session/prompt']


def check_connection_launch(service: FakeDshService, home: Path) -> None:
    """The connection's home, key variable and declared model reach the native launch."""
    assert service.environment['DSH_HOME'] == str(home)
    assert service.environment['DSH_383_KEY'] == KEY
    llm = next(row['config'] for row in service.patches if row.get('id') == 'llm-deepseek')
    assert llm == {'apiKeyEnv': 'DSH_383_KEY', 'models': [{'id': 'deepseek-v5'}], 'reasoningEffort': 'high'}


def claude_main(host: IndependentCalls, cwd: Path):
    session = str(uuid4())
    call = host.make_call(session, cwd)

    def invoke(feature: str, **arguments) -> dict:
        """Call as the Main; ``invoke.shown`` keeps the notices its results carried."""
        result = call('agents', {'action': 'execute', 'feature': feature, 'arguments': arguments})
        assert not result.failed, result.document
        invoke.shown.extend(result.document.get('main_notices', []))
        return result.document

    invoke.shown = []
    return invoke, call, session


def stop_owned(control) -> None:
    for owned in control.interrupt_owned():
        deadline = time.monotonic() + 10
        while control.owns_running(owned) and time.monotonic() < deadline:
            time.sleep(0.05)


def test_claude_host_routes_a_dsh_child_with_its_own_choices(tmp_path: Path, dsh: dict) -> None:
    """create runtime=dsh reaches DshDriver with the child's connection, model and effort."""
    home = declare(tmp_path / 'agents', tmp_path)
    host = IndependentCalls(tmp_path / 'agents', tmp_path, {}, {'dsh': dsh})
    host.control.require_connections()
    invoke, _, _ = claude_main(host, tmp_path)
    try:
        check_round_trip(invoke, invoke.shown)
        check_connection_launch(FakeDshService.instances[0], home)
    finally:
        stop_owned(host.control)


def test_a_dsh_childs_end_reaches_the_claude_main_once(tmp_path: Path, dsh: dict) -> None:
    """Without a wait the Claude mod claims the DSH child's answer once, or create's own result carried it."""
    host = IndependentCalls(tmp_path / 'agents', tmp_path, {}, {'dsh': dsh})
    invoke, call, session = claude_main(host, tmp_path)
    agent = invoke('create', runtime='dsh', instruction='report back')['agent']
    notices = until(lambda: invoke.shown or host.context({'operation': 'notices', 'session': session})['notices'])
    assert [(n['event']['alias'], n['event']['event'], n['event']['message']) for n in notices] == [
        (agent, 'completed', 'dsh answer: report back')]
    assert host.context({'operation': 'notices', 'session': session})['notices'] == []
    # Without a choice the host's own DSH settings apply.
    [service] = FakeDshService.instances
    assert (selected(service)['model'], 'reasoningEffort' in selected(service)) == ('deepseek-flash', False)


def test_codex_host_routes_a_dsh_child_with_its_own_choices(
        tmp_path: Path, native_settings: dict, dsh: dict) -> None:
    """The Codex host's runtimes.dsh entry runs DSH children in its worktree."""
    home = declare(tmp_path / 'host', tmp_path)
    host = CodexHost({**native_settings, 'runtimes': {'dsh': dsh}}, tmp_path / 'host', 'unused')
    call = bind(host.control, Caller('codex', None, 'parent-session', 'codex'))

    def invoke(feature: str, **arguments) -> dict:
        result = call({'action': feature, **arguments})
        assert not result.failed, result.document
        return result.document

    try:
        check_round_trip(invoke)
        service = FakeDshService.instances[0]
        check_connection_launch(service, home)
        assert service.cwd == Path(native_settings['adapter_request']['worktree_path'])
    finally:
        stop_owned(host.control)


def test_dsh_child_launch_needs_no_graphtraj_setting(tmp_path: Path, dsh: dict) -> None:
    """The MCP command, connection variable, package and plugin all come from agents."""
    host = IndependentCalls(tmp_path / 'agents', tmp_path, {}, {'dsh': dsh})
    invoke, _, _ = claude_main(host, tmp_path)
    agent = invoke('create', runtime='dsh', instruction='x')['agent']
    invoke('wait', agent=agent, timeout_seconds=10)
    [service] = FakeDshService.instances
    environment = service.environment
    assert not [name for name in environment if name.startswith('GRAPHTRAJ_')]
    assert environment['DSH_AGENT_PACKAGE'] == str(Path(dsh['executable']).resolve().parent.parent / 'package.json')
    assert environment['AGENT_SWARM_CONNECTION'].startswith(str(tmp_path / '.scratch'))
    [plugin] = [row['insert'][0] for row in service.patches
                if 'insert' in row and row['insert'][0]['id'] == 'agents-mcp']
    assert Path(plugin['name']) == ROOT / 'src/agent_swarm/dsh/plugin.mjs'
    assert plugin['config'] == {'mcpCommand': str(Path(sys.executable).absolute()),
                                'mcpArgs': ['-I', '-m', 'agent_swarm.mcp']}


def refusal_cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dsh: dict) -> list[tuple]:
    """DSH settings each host refuses at start, with the code and text it reports."""
    empty = tmp_path / 'no-dsh-here'
    empty.mkdir()
    monkeypatch.setenv('PATH', str(empty))
    old = install_dsh(tmp_path / 'old-dsh', '0.2.0-rc.1')
    return [
        ({'model': 'deepseek-flash', 'sandbox': 'workspace-write'}, 'RUNTIME_UNAVAILABLE', 'Install the native DSH'),
        ({**dsh, 'executable': str(old)}, 'RUNTIME_UNSUPPORTED',
         'DSH 0.2.0-rc.2 or later is required (installed 0.2.0-rc.1).'),
        ({**dsh, 'model': ''}, 'ROLE_CONFIG_INVALID', 'model'),
        ({**dsh, 'api_key_env': 'DSH_383_UNSET'}, 'RUNTIME_CREDENTIAL_MISSING', 'api_key_env'),
    ]


def test_claude_host_refuses_missing_or_unsupported_dsh_at_start(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dsh: dict) -> None:
    for entry, code, text in refusal_cases(tmp_path, monkeypatch, dsh):
        with pytest.raises(AgentsError) as refused:
            IndependentCalls(tmp_path / 'agents', tmp_path, {}, {'dsh': entry})
        assert (refused.value.code, text in str(refused.value)) == (code, True), refused.value


def test_codex_host_refuses_missing_or_unsupported_dsh_at_start(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, native_settings: dict, dsh: dict) -> None:
    for entry, code, text in refusal_cases(tmp_path, monkeypatch, dsh):
        with pytest.raises(AgentsError) as refused:
            CodexHost({**native_settings, 'runtimes': {'dsh': entry}}, tmp_path / 'host', 'never runs')
        assert (refused.value.code, text in str(refused.value)) == (code, True), refused.value
        assert not (tmp_path / 'host/host/session.yml').exists()
    assert FakeDshService.instances == []


def test_codex_host_cli_reports_an_unsupported_dsh(tmp_path: Path, native_settings: dict, dsh: dict) -> None:
    """The command prints the startup error document and exits 1."""
    old = install_dsh(tmp_path / 'old-dsh', '0.1.9')
    settings = tmp_path / 'settings.json'
    settings.write_text(json.dumps({**native_settings, 'runtimes': {'dsh': {**dsh, 'executable': str(old)}}}))
    result = subprocess.run([sys.executable, '-m', 'agent_swarm.codex.host', '--settings', str(settings),
                             '--directory', str(tmp_path / 'host'), 'never runs'],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads(result.stdout)['error'] == {
        'code': 'RUNTIME_UNSUPPORTED', 'message': 'DSH 0.2.0-rc.2 or later is required (installed 0.1.9).'}


def test_require_connections_covers_a_declared_dsh_connection(tmp_path: Path, dsh: dict,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """A declared DSH connection whose key is unset refuses the host's start."""
    declare(tmp_path / 'agents', tmp_path)
    host = IndependentCalls(tmp_path / 'agents', tmp_path, {}, {'dsh': dsh})
    monkeypatch.delenv('DSH_383_KEY')
    with pytest.raises(AgentsError) as refused:
        host.control.require_connections()
    assert refused.value.code == 'runtime-unavailable'
    (tmp_path / 'bare').mkdir()
    (tmp_path / 'bare/config.yml').write_text(CONFIG.format(home=tmp_path))
    without = IndependentCalls(tmp_path / 'bare', tmp_path, {})
    with pytest.raises(AgentsError) as refused:
        without.control.require_connections()
    assert refused.value.code == 'unsupported-runtime'


@pytest.mark.parametrize(('version', 'accepted'), [
    ('0.1.9', False), ('0.2.0-beta.4', False), ('0.2.0-rc.1', False),
    ('0.2.0-rc.2', True), ('0.2.0-rc.10', True), ('0.2.0', True),
    ('0.2.1-alpha.5', True), ('0.2.2-alpha.2', True), ('1.0.0', True),
])
def test_the_standalone_dsh_gate_is_a_floor(tmp_path: Path, version: str, accepted: bool) -> None:
    """0.2.0-rc.2 or later in semver order; GraphTraj's own DSH members follow the same rule."""
    executable = install_dsh(tmp_path / 'dsh', version)
    settings = {'executable': str(executable), 'model': 'm', 'sandbox': 'read-only'}
    if accepted:
        assert prepare(settings, tmp_path)['package'] == str(tmp_path / 'dsh/package.json')
    else:
        with pytest.raises(AgentsError) as refused:
            prepare(settings, tmp_path)
        assert (refused.value.code, str(refused.value)) == (
            'RUNTIME_UNSUPPORTED', f'DSH 0.2.0-rc.2 or later is required (installed {version}).')


@pytest.mark.parametrize(('package', 'installed'), [
    (None, 'unknown'), ('not json', 'unknown'), ('{}', 'unknown'),
    ('{"version": 2}', '2'), ('{"version": "latest"}', 'latest'),
])
def test_an_unreadable_dsh_version_is_refused(tmp_path: Path, package: str | None, installed: str) -> None:
    executable = install_dsh(tmp_path / 'dsh')
    if package is None:
        (tmp_path / 'dsh/package.json').unlink()
    else:
        (tmp_path / 'dsh/package.json').write_text(package)
    with pytest.raises(AgentsError) as refused:
        prepare({'executable': str(executable), 'model': 'm', 'sandbox': 'read-only'}, tmp_path)
    assert (refused.value.code, str(refused.value)) == (
        'RUNTIME_UNSUPPORTED', f'DSH 0.2.0-rc.2 or later is required (installed {installed}).')


STANDALONE = r'''
import json, os, sys, time
from pathlib import Path
from uuid import uuid4
source, tests, work = sys.argv[1:4]
sys.path[:0] = [source, tests]

class NoGraphTraj:
    """Make GraphTraj unimportable even though this venv also installs it."""
    def find_spec(self, name, path=None, target=None):
        if name == 'graphtraj' or name.startswith('graphtraj.'):
            raise ModuleNotFoundError(f'No module named {name!r} (blocked)')

sys.meta_path.insert(0, NoGraphTraj())
assert not [name for name in os.environ if name.startswith('GRAPHTRAJ_')]
from dsh_standalone_peer import FakeDshService, install_dsh
from agent_swarm.dsh import execution
from agent_swarm.claude.host import IndependentCalls
from agent_swarm.codex.host import runtime_drivers
from agent_swarm.dsh.driver import DshDriver

execution.DshExecution.service_type = FakeDshService
work = Path(work)
settings = {'executable': str(install_dsh(work / 'dsh')), 'model': 'deepseek-flash', 'sandbox': 'read-only'}
assert isinstance(runtime_drivers({'adapter_request': {'worktree_path': str(work)},
                                   'runtimes': {'dsh': dict(settings)}}, work / 'agents')['dsh'], DshDriver)
host = IndependentCalls(work / 'agents', work, {}, {'dsh': settings})
host.control.require_connections()
call = host.make_call(str(uuid4()), work)
shown = []

def run(feature, **arguments):
    document = call('agents', {'action': 'execute', 'feature': feature, 'arguments': arguments}).document
    shown.extend(document.get('main_notices', []))
    return document

def answered(agent):
    # The wait shows the body, unless an earlier result already carried it: once either way.
    last = run('wait', agent=agent, timeout_seconds=10)['result']['last_result']
    bodies = [notice['event']['message'] for notice in shown if notice['event']['execution'] == last['id']]
    bodies += [last['last_message']] if last['last_message'] is not None else []
    assert len(bodies) == 1, (last, bodies)
    return bodies[0]

agent = run('create', runtime='dsh', instruction='hello')['agent']
assert answered(agent) == 'dsh answer: hello'
run('resume', agent=agent, message='again')
assert answered(agent) == 'dsh answer: again'
first, second = FakeDshService.instances
assert second.session == first.session
plugin = next(row['insert'][0] for row in first.patches if 'insert' in row)
print(json.dumps({
    'graphtraj_modules': sorted(name for name in sys.modules if name.split('.')[0] == 'graphtraj'),
    'environment': sorted(name for name in first.environment
                          if name.startswith(('GRAPHTRAJ_', 'DSH_AGENT_PACKAGE', 'AGENT_SWARM_CONNECTION'))),
    'plugin': plugin,
}))
'''


def test_dsh_child_runs_with_graphtraj_unimportable(tmp_path: Path) -> None:
    """Both hosts' DSH entries, a round trip and a resume, with GraphTraj blocked and no GRAPHTRAJ_*."""
    environment = {name: value for name, value in os.environ.items()
                   if not name.startswith('GRAPHTRAJ_') and name != 'PYTHONPATH'}
    result = subprocess.run([sys.executable, '-I', '-c', STANDALONE, str(ROOT / 'src'), str(ROOT / 'tests'),
                             str(tmp_path)], capture_output=True, text=True, timeout=60, env=environment)
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(result.stdout.splitlines()[-1])
    assert evidence['graphtraj_modules'] == []
    assert evidence['environment'] == ['AGENT_SWARM_CONNECTION', 'DSH_AGENT_PACKAGE']
    assert evidence['plugin']['name'] == str(ROOT / 'src/agent_swarm/dsh/plugin.mjs')
    assert evidence['plugin']['config']['mcpArgs'] == ['-I', '-m', 'agent_swarm.mcp']


def test_the_dsh_mcp_command_serves_without_graphtraj(tmp_path: Path) -> None:
    """The child's MCP command (python -I -m agent_swarm.mcp) answers with GraphTraj blocked."""
    program = ('import runpy, sys\n'
               'class NoGraphTraj:\n'
               '    def find_spec(self, name, path=None, target=None):\n'
               "        if name.split('.')[0] == 'graphtraj': raise ModuleNotFoundError(name)\n"
               'sys.meta_path.insert(0, NoGraphTraj())\n'
               f'sys.path.insert(0, {str(ROOT / "src")!r})\n'
               "runpy.run_module('agent_swarm.mcp', run_name='__main__')\n")
    messages = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}}]
    environment = {name: value for name, value in os.environ.items()
                   if not name.startswith(('GRAPHTRAJ_', 'AGENT_SWARM_')) and name != 'PYTHONPATH'}
    result = subprocess.run([sys.executable, '-I', '-c', program], cwd=tmp_path, env=environment,
                            input=''.join(json.dumps(message) + '\n' for message in messages),
                            capture_output=True, text=True, timeout=30)
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    assert replies[0]['result']['serverInfo']['name'] == 'agents', result.stderr
    assert [tool['name'] for tool in replies[1]['result']['tools']] == ['agents']


def test_delivered_plugin_loads_from_dsh_agent_package_alone(tmp_path: Path) -> None:
    """The installed DSH loads plugin.mjs through DSH_AGENT_PACKAGE with no GRAPHTRAJ_* set."""
    node, dsh = shutil.which('node'), shutil.which('dsh')
    if node is None or dsh is None:
        pytest.skip('Installed DSH and Node are required for native plugin evidence.')
    package = Path(dsh).resolve().parent.parent / 'package.json'
    environment = {name: value for name, value in os.environ.items() if not name.startswith('GRAPHTRAJ_')}
    result = subprocess.run([
        node, str(ROOT / 'tests/fixtures/dsh_mcp_plugin.mjs'), str(Path(dsh).resolve()),
        str(ROOT / 'src/agent_swarm/dsh/plugin.mjs'), sys.executable, str(ROOT / 'tests/fixtures/dsh_mcp_server.py'),
    ], cwd=tmp_path, env={**environment, 'DSH_AGENT_PACKAGE': str(package), 'PYTHONPATH': str(ROOT / 'src')},
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(result.stdout.strip().splitlines()[-1])
    assert evidence['childSourcePreserved']
    assert evidence['browserEntry'] == 'agents-dsh'


@pytest.mark.parametrize('base_url', [None, DECLARED])
def test_ambient_endpoints_do_not_route_a_dsh_child(tmp_path: Path, dsh: dict, monkeypatch: pytest.MonkeyPatch,
                                                    base_url: str | None) -> None:
    """Only the connection names the endpoint its key goes to; the parent's shell does not."""
    for name, value in AMBIENT.items():
        monkeypatch.setenv(name, value)
    home = declare(tmp_path / 'agents', tmp_path)
    if base_url is not None:
        (tmp_path / 'agents/config.yml').write_text(
            CONFIG.format(home=home).replace('    api_key_env:', f'    base_url: {base_url}\n    api_key_env:'))
    host = IndependentCalls(tmp_path / 'agents', tmp_path, {}, {'dsh': dsh})
    invoke, _, _ = claude_main(host, tmp_path)
    try:
        agent = invoke('create', runtime='dsh', instruction='one', model='deepseek-v5')['agent']
        invoke('wait', agent=agent, timeout_seconds=10)
        [service] = FakeDshService.instances
        # Names only: a failing assertion must not print the launch environment.
        inherited = [name for name in AMBIENT if name in service.environment]
        assert inherited == []
        assert 'DSH_383_KEY' in service.environment
        llm = next(row['config'] for row in service.patches if row.get('id') == 'llm-deepseek')
        assert llm.get('baseURL') == base_url
    finally:
        stop_owned(host.control)


def test_a_native_failure_reaches_the_parent_with_its_reason(tmp_path: Path, dsh: dict,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """The native error reaches wait, status and stderr.log, without the connection's key."""
    class HeldEnd(FakeDshService):
        """End the turn only once create has returned, so the failure belongs to the execution."""
        release = threading.Event()

        def receive(self, timeout: float = 1) -> dict:
            return super().receive(timeout) if self.release.wait(0.02) else {}

    monkeypatch.setattr(execution.DshExecution, 'service_type', HeldEnd)
    monkeypatch.setattr(FakeDshService, 'end_reason', {'kind': 'error', 'error': {
        'message': f'DeepSeek Messages request failed (404) for {KEY}', 'code': 'HTTP_404', 'status': 404}})
    host = IndependentCalls(tmp_path / 'agents', tmp_path, {}, {'dsh': dsh})
    invoke, _, _ = claude_main(host, tmp_path)
    try:
        agent = invoke('create', runtime='dsh', instruction='one')['agent']
        HeldEnd.release.set()
        last = invoke('wait', agent=agent, timeout_seconds=10)['result']['last_result']
        message = 'DSH turn ended with error: HTTP_404: DeepSeek Messages request failed (404) for [redacted].'
        assert (last['outcome'], last['error']) == ('failed', {'code': 'RUNTIME_EXECUTION_FAILED', 'message': message})
        status = invoke('status', agent=agent)
        assert status['result']['last_result']['error']['message'] == message
        assert KEY not in json.dumps(status)
        [log] = (tmp_path / 'agents').rglob('stderr.log')
        assert log.read_text() == f'RUNTIME_EXECUTION_FAILED: {message}\n'
    finally:
        stop_owned(host.control)


@pytest.mark.parametrize(('reason', 'message'), [
    ({'kind': 'error', 'error': {'code': 'HTTP_404'}}, 'DSH turn ended with error: HTTP_404.'),
    ({'kind': 'error', 'error': {'message': 'Stream closed'}}, 'DSH turn ended with error: Stream closed.'),
    ({'kind': 'error', 'error': 'Stream closed'}, 'DSH turn ended with error: Stream closed.'),
    ({'kind': 'error', 'error': 429}, 'DSH turn ended with error: 429.'),
    ({'kind': 'error', 'error': {}}, 'DSH turn ended with error.'),
    ({'kind': 'error'}, 'DSH turn ended with error.'),
])
def test_a_partial_native_error_still_describes_the_end(reason: dict, message: str) -> None:
    """Whatever part of the native error exists is used; describing it never raises."""
    assert execution._turn_failure(reason, {}) == message


def test_an_empty_named_key_redacts_nothing() -> None:
    """An empty value would otherwise match between every character of the text."""
    reason = {'kind': 'error', 'error': {'code': 'HTTP_401'}}
    assert execution._turn_failure(reason, {'DS_CRED': ''}, 'DS_CRED') == 'DSH turn ended with error: HTTP_401.'


def launch_patches(settings: dict, tmp_path: Path) -> tuple[dict, list[dict], Path]:
    """The environment prepare_launch returns, its patch rows and the patch file."""
    turn = execution.DshExecution(settings, 'unused', tmp_path, lambda *_: None, lambda *_: None,
                                  tmp_path / 'trace.jsonl', None)
    environment = turn.prepare_launch()
    patch = Path(environment['DSH_HOME']) / 'profiles/web/cordis.patch.yml'
    return environment, yaml.load(patch.read_text(), Loader=execution._PatchLoader), patch


@pytest.mark.parametrize(('base_url', 'key', 'root'), [
    (DECLARED, 'DEEPSEEK_API_KEY', DECLARED + '/v1'),
    (DECLARED, None, DECLARED + '/v1'),
    (DECLARED + '/', 'DEEPSEEK_API_KEY', DECLARED + '/v1'),
    ('https://declared.invalid/v1', 'DEEPSEEK_API_KEY', 'https://declared.invalid/v1'),
    ('http://127.0.0.1:1234', None, 'http://127.0.0.1:1234/v1'),
    ('http://api.deepseek.com/anthropic', 'DEEPSEEK_API_KEY', 'http://api.deepseek.com/anthropic/v1'),
    ('https://api.deepseek.com:8443/anthropic', 'DEEPSEEK_API_KEY', 'https://api.deepseek.com:8443/anthropic/v1'),
    (OFFICIAL, 'DEEPSEEK_API_KEY', None),
    (OFFICIAL, None, None),
    ('https://api.deepseek.com:443/anthropic', 'DEEPSEEK_API_KEY', None),
    ('https://API.deepseek.com/anthropic', 'DEEPSEEK_API_KEY', None),
    (DECLARED, 'DSH_383_KEY', None),
    (None, 'DEEPSEEK_API_KEY', None),
    (None, None, None),
    (None, 'DSH_383_KEY', None),
])
def test_the_default_key_searches_only_where_the_connection_says(
    tmp_path: Path, dsh: dict, monkeypatch: pytest.MonkeyPatch, base_url: str | None, key: str | None, root: str | None,
) -> None:
    """The default key's search row follows base_url; another key leaves DSH's own search alone."""
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fake-413-default-key')
    settings = prepare({**dsh, **({'base_url': base_url} if base_url else {}),
                        **({'api_key_env': key} if key else {})}, tmp_path)
    _, patches, _ = launch_patches(settings, tmp_path)
    rows = {row['id']: row for row in patches if row.get('id') in ('web-search-deepseek', 'web-deepseek-api')}
    if root is None:
        assert rows == {}
    else:
        assert rows == {'web-search-deepseek': {'id': 'web-search-deepseek', 'config': {
                            'apiKeyEnv': 'DEEPSEEK_API_KEY', 'baseURL': root}},
                        'web-deepseek-api': {'id': 'web-deepseek-api', 'disabled': True}}


@pytest.mark.parametrize(('base_url', 'key', 'destination'), [
    (DECLARED, 'DEEPSEEK_API_KEY', DECLARED + '/v1/messages'),
    ('https://declared.invalid/v1', 'DEEPSEEK_API_KEY', 'https://declared.invalid/v1/messages'),
    ('http://api.deepseek.com/anthropic', 'DEEPSEEK_API_KEY', 'http://api.deepseek.com/anthropic/v1/messages'),
    ('https://api.deepseek.com:8443/anthropic', 'DEEPSEEK_API_KEY', 'https://api.deepseek.com:8443/anthropic/v1/messages'),
    (OFFICIAL, 'DEEPSEEK_API_KEY', OFFICIAL + '/v1/messages'),
    (DECLARED, 'DSH_383_KEY', OFFICIAL + '/v1/messages'),
    (None, 'DEEPSEEK_API_KEY', OFFICIAL + '/v1/messages'),
])
def test_installed_search_sends_the_key_where_the_row_says(
    tmp_path: Path, dsh: dict, monkeypatch: pytest.MonkeyPatch, base_url: str | None, key: str, destination: str,
) -> None:
    """The installed DSH composes the patch, its search plugin picks the address; fetch is replaced."""
    node, installed = shutil.which('node'), shutil.which('dsh')
    if node is None or installed is None:
        pytest.skip('Installed DSH and Node are required for native search evidence.')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fake-413-default-key')
    settings = prepare({**dsh, 'executable': installed, 'api_key_env': key,
                        **({'base_url': base_url} if base_url else {})}, tmp_path)
    environment, _, patch = launch_patches(settings, tmp_path)
    dumped = subprocess.run([installed, '--profile', 'web', '--patch', str(patch), '--dump-config'],
                            cwd=tmp_path, env={**environment, 'DSH_HOME': str(tmp_path / 'dump-home')},
                            capture_output=True, text=True, timeout=60)
    assert dumped.returncode == 0, dumped.stderr
    rows = {row.get('id'): row for row in yaml.load(dumped.stdout, Loader=execution._PatchLoader)}
    search = subprocess.run([node, str(ROOT / 'tests/fixtures/dsh_search_request.mjs'),
                             str(Path(installed).resolve().parent.parent), json.dumps(rows['web-search-deepseek']['config'])],
                            cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=30)
    assert search.returncode == 0, search.stderr
    assert json.loads(search.stdout) == {'url': destination, 'keyed': True}
    assert rows['web-deepseek-api'].get('disabled', False) is (key == 'DEEPSEEK_API_KEY' and base_url not in (None, OFFICIAL))


@pytest.mark.parametrize(('base_url', 'expected'), [(None, OFFICIAL), (DECLARED, DECLARED)])
def test_installed_dsh_resolves_only_the_connection_endpoint(tmp_path: Path, dsh: dict, monkeypatch: pytest.MonkeyPatch,
                                                             base_url: str | None, expected: str) -> None:
    """The installed DSH's own resolver, given what prepare_launch returned; no service and no network."""
    node, installed = shutil.which('node'), shutil.which('dsh')
    if node is None or installed is None:
        pytest.skip('Installed DSH and Node are required for native endpoint evidence.')
    for name, value in AMBIENT.items():
        monkeypatch.setenv(name, value)
    settings = prepare({**dsh, 'executable': installed, 'api_key_env': 'DSH_383_KEY',
                        **({'base_url': base_url} if base_url else {})}, tmp_path)
    turn = execution.DshExecution(settings, 'unused', tmp_path, lambda *_: None, lambda *_: None,
                                  tmp_path / 'trace.jsonl', None)
    environment = turn.prepare_launch()
    patch = Path(environment['DSH_HOME']) / 'profiles/web/cordis.patch.yml'
    row = next(row['config'] for row in yaml.load(patch.read_text(), Loader=execution._PatchLoader)
               if row.get('id') == 'llm-deepseek')

    def resolved(launch: dict) -> str:
        result = subprocess.run([node, str(ROOT / 'tests/fixtures/dsh_resolve_endpoint.mjs'),
                                 str(Path(installed).resolve().parent.parent), json.dumps(row)],
                                cwd=tmp_path, env=launch, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    assert resolved(environment) == expected
    # This DSH does honour the variable when it is left in: what the removal prevents.
    assert resolved({**environment, **AMBIENT}) == (base_url or AMBIENT['DEEPSEEK_BASE_URL'])
