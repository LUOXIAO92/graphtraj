"""Native lifecycle carriers preserve source and per-Session associations."""

import json
import os
from pathlib import Path
import shutil
import subprocess

from click.testing import CliRunner
import pytest

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.execution.main_finalize import session_binding
from graphtraj.execution.runner_status import caller_alias
from graphtraj.runtimes import replacement
from graphtraj.runtimes.native_entry import main
from graphtraj.workspace.runner_project import discover_runner_directory


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Configure a real temporary Harness for public native event calls."""
    configuration = tmp_path / '.graphtraj/config.yml'
    configuration.parent.mkdir()
    configuration.write_text(default_configuration_content(tmp_path, tmp_path))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def native(runtime: str, event: dict) -> dict:
    """Invoke the shipped lifecycle command using a native callback envelope."""
    result = CliRunner().invoke(main, [runtime], input=json.dumps(event))
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def pi_session(root: Path, monkeypatch: pytest.MonkeyPatch, session: str, entries: list[dict]) -> dict:
    """Supply a native persisted Session and its per-call locator."""
    header = {'type': 'session', 'version': 3, 'id': session, 'cwd': str(root)}
    path = root / f'{session}.jsonl'
    path.write_text(''.join(json.dumps(row) + '\n' for row in [header, *entries]))
    monkeypatch.setenv('GRAPHTRAJ_NATIVE_RUNTIME', 'pi')
    monkeypatch.setenv('GRAPHTRAJ_NATIVE_SESSION', session)
    monkeypatch.setenv('GRAPHTRAJ_NATIVE_SESSION_FILE', str(path))
    monkeypatch.setattr(replacement, 'caller_runtime', lambda: 'pi')
    return {'event': 'session_start', 'reason': 'startup', 'header': header, 'entries': entries}


@pytest.mark.parametrize('plugin', ['nicobailon', 'mjakl', 'durable', 'checker'])
def test_pi_children_do_not_replace_main(
    project: Path, monkeypatch: pytest.MonkeyPatch, plugin: str,
) -> None:
    """Recursive plugin markers and checker purpose win over inherited Main locators."""
    root = pi_session(project, monkeypatch, 'main', [])
    assert native('pi', root) == {'source': 'main'}
    assert native('pi', {**root, 'reason': 'resume'}) == {'source': 'main'}
    binding = session_binding(project, 'pi', 'main')
    before = binding.read_bytes()
    entries = []
    if plugin == 'nicobailon':
        monkeypatch.setenv('PI_SUBAGENT_CHILD', '1')
    elif plugin == 'mjakl':
        monkeypatch.setenv('PI_SUBAGENT_DEPTH', '3')
    elif plugin == 'durable':
        entries = [{'type': 'custom', 'customType': 'pi-subagent:delegation',
                    'data': {'version': 1, 'childSessionId': 'child', 'parentSessionId': 'actual-parent'}}]
    else:
        entries = [{'type': 'custom', 'customType': 'graphtraj:completion-checker',
                    'data': {'session': 'child', 'parent': 'main'}}]
    event = pi_session(project, monkeypatch, 'child', entries)
    monkeypatch.setenv('CODEX_THREAD_ID', 'inherited-other-runtime-main')
    assert native('pi', event) == {'source': 'child'}
    assert caller_alias(discover_runner_directory(project)) == 'child'
    assert binding.read_bytes() == before


def test_pi_copied_delegation_does_not_relabel_user_fork(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only metadata whose childSessionId matches this native header assigns origin."""
    event = pi_session(project, monkeypatch, 'user-fork', [{
        'type': 'custom', 'customType': 'pi-subagent:delegation',
        'data': {'version': 1, 'childSessionId': 'old-child', 'parentSessionId': 'old-parent'},
    }])
    event['header']['parentSession'] = '/native/old-session.jsonl'
    assert native('pi', event) == {'source': 'main'}
    assert caller_alias(discover_runner_directory(project)) is None
    monkeypatch.setenv('GRAPHTRAJ_NATIVE_SESSION', 'stale-main')
    with pytest.raises(ValueError, match='stale'):
        caller_alias(discover_runner_directory(project))


def test_unknown_pi_entry_does_not_register_main(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The marker-free no-session example has no automatic Main authority."""
    event = pi_session(project, monkeypatch, 'unknown', [])
    event['header'] = None
    assert 'error' in native('pi', event)
    assert not session_binding(project, 'pi', 'unknown').exists()


def test_unverifiable_native_runtime_does_not_become_human_cli(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A denied source lookup must not turn an inherited locator into Main."""
    from graphtraj.execution.runner_models import RunnerError

    monkeypatch.setattr(replacement, 'caller_runtime', lambda: None)
    monkeypatch.setenv('GRAPHTRAJ_NATIVE_RUNTIME', 'pi')
    with pytest.raises(RunnerError, match='cannot be verified'):
        caller_alias(discover_runner_directory(project))
    monkeypatch.delenv('GRAPHTRAJ_NATIVE_RUNTIME')
    assert caller_alias(discover_runner_directory(project)) is None


def test_unverifiable_caller_returns_mcp_error_without_closing_server(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A native source failure is visible while the host transport stays usable."""
    from io import StringIO
    from graphtraj.interfaces.mcp import serve

    monkeypatch.setattr(replacement, 'caller_runtime', lambda: None)
    monkeypatch.setenv('GRAPHTRAJ_NATIVE_RUNTIME', 'pi')
    requests = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
            'name': 'graphtraj', 'arguments': {
                'action': 'execute', 'feature': 'alias_status', 'arguments': {},
            },
        }},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'ping'},
    ]
    output = StringIO()
    serve(StringIO('\n'.join(json.dumps(request) for request in requests)), output)
    failed, alive = [json.loads(line) for line in output.getvalue().splitlines()]
    assert failed['result']['isError'] is True
    assert 'cannot be verified' in failed['result']['content'][0]['text']
    assert alive == {'jsonrpc': '2.0', 'id': 2, 'result': {}}


def dsh_session(monkeypatch: pytest.MonkeyPatch, session: str, source: str = 'main') -> None:
    """Supply DSH's native per-execution rebuilt namespace."""
    monkeypatch.setenv('DSH_SESSION_ID', session)
    monkeypatch.setenv('DSH_GRAPHTRAJ_SESSION', session)
    monkeypatch.setenv('DSH_GRAPHTRAJ_SOURCE', source)
    monkeypatch.setattr(replacement, 'caller_runtime', lambda: 'dsh')


def test_dsh_start_resume_child_and_stale_context(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Actual DSH origin/depth stay separate from historical fork lineage."""
    dsh_session(monkeypatch, 'main')
    header = {'version': 4, 'id': 'main', 'isSeeded': True, 'parentSession': 'history-source'}
    for source in ('startup', 'resume'):
        assert native('dsh', {'event': 'agent/created', 'source': source, 'header': header}) == {'source': 'main'}
    binding = session_binding(project, 'dsh', 'main')
    before = binding.read_bytes()
    dsh_session(monkeypatch, 'child', 'child')
    assert native('dsh', {'event': 'agent/created', 'source': 'startup', 'header': {
        **header, 'id': 'child', 'origin': 'subagent', 'parentSession': 'main', 'delegationDepth': 2,
    }}) == {'source': 'child'}
    monkeypatch.setenv('GRAPHTRAJ_NATIVE_RUNTIME', 'pi')
    monkeypatch.setenv('GRAPHTRAJ_NATIVE_SESSION', 'inherited-pi-main')
    assert caller_alias(discover_runner_directory(project)) == 'child'
    assert binding.read_bytes() == before
    monkeypatch.setenv('DSH_SESSION_ID', 'another-child')
    with pytest.raises(Exception, match='stale'):
        caller_alias(discover_runner_directory(project))


def test_pi_adapter_owns_checker_result_without_main_tool_calls(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Native extension plumbing binds and collects a distinct checker directly."""
    assert native('pi', pi_session(project, monkeypatch, 'main', [])) == {'source': 'main'}
    assert native('pi', {'event': 'check_context'})['prompt']
    assert native('pi', {'event': 'checker_created', 'session': 'checker'}) == {'session': 'checker'}
    result = {'status': 'waiting', 'reason': 'Native approval pending.', 'nodes': ['276']}
    assert native('pi', {'event': 'check_result', 'session': 'checker', 'output': json.dumps(result)}) == result
    assert 'error' in native('pi', {'event': 'check_result', 'session': 'unowned', 'output': json.dumps(result)})


def test_pi_shared_process_environment_is_per_session(project: Path) -> None:
    """The native extension captures child startup env without changing its parent."""
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is not installed')
    extension = Path(__file__).resolve().parents[1] / 'src/graphtraj/runtimes/pi/extension.mjs'
    # Load the exact module bytes without asking Node to inspect denied parents
    # of an otherwise readable isolated Worktree.
    extension = Path(shutil.copy2(extension, project / 'extension.mjs'))
    script = '''
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const { sessionEnvironment } = await import(pathToFileURL(process.argv[1]).href);
const context = id => ({ sessionManager: { getSessionId: () => id, getSessionFile: () => '/native/' + id } });
const inherited = { PI_SUBAGENT_CHILD: '', PI_SUBAGENT_DEPTH: '0' };
const main = sessionEnvironment(context('main'), inherited);
inherited.PI_SUBAGENT_CHILD = '1';
const child = sessionEnvironment(context('child'), inherited);
inherited.PI_SUBAGENT_CHILD = '';
assert.equal(main.PI_SUBAGENT_CHILD, '');
assert.equal(child.PI_SUBAGENT_CHILD, '1');
assert.equal(main.GRAPHTRAJ_NATIVE_SESSION, 'main');
assert.equal(child.GRAPHTRAJ_NATIVE_SESSION, 'child');
'''
    result = subprocess.run([node, '--input-type=module', '-e', script, str(extension)],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('runtime', ['pi', 'dsh'])
def test_installed_native_session_apis(project: Path, runtime: str) -> None:
    """Check real installed Session libraries without launching any model Agent."""
    node, executable = shutil.which('node'), shutil.which(runtime)
    if node is None or executable is None:
        pytest.skip(f'{runtime} native library is not installed')
    package = Path(__file__).resolve().parents[1] / 'src/graphtraj/runtimes'
    module = package / runtime / ('extension.mjs' if runtime == 'pi' else 'tool.mjs')
    module = Path(shutil.copy2(module, project / module.name))
    environment = {**os.environ, 'GRAPHTRAJ_DSH_PACKAGE': str(Path(executable).resolve())}
    script = '''
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
const require = createRequire(process.argv[2]);
const load = name => import(pathToFileURL(require.resolve(name)).href);
const { sessionEnvironment, loadHostSdk } = await import(pathToFileURL(process.argv[1]).href);
if (process.argv[3] === 'pi') {
  const { SessionManager, SettingsManager, DefaultResourceLoader } = await loadHostSdk(process.argv[2]);
  const manager = SessionManager.create(process.cwd(), process.cwd() + '/sessions');
  const env = sessionEnvironment({ sessionManager: manager }, {});
  assert.equal(env.GRAPHTRAJ_NATIVE_SESSION, manager.getHeader().id);
  assert.equal(manager.getHeader().version, 3);
  assert.equal(SettingsManager.inMemory({ defaultThinkingLevel: 'high' }).getSettings().defaultThinkingLevel, 'high');
  assert.equal(typeof DefaultResourceLoader, 'function');
} else {
  const { Session, buildForkSeed, SessionLogOffset } = await load('@deepseek-ai/dsh-session');
  const { createUserMessage } = await load('@deepseek-ai/dsh-llm');
  const parent = Session.create('native-parent');
  parent.append('turn/start', { turn: 0 });
  parent.append('step/start', { turn: 0, step: 0 });
  parent.append('user/message', createUserMessage({ content: [{ type: 'text', text: 'current-task-sentinel' }], source: { kind: 'user' } }), { surfaceOp: 'append' });
  const original = parent.snapshotEvents();
  const seed = buildForkSeed(original, original.at(-1).seq);
  const header = { ...parent.header, id: 'native-child', isSeeded: true,
    origin: 'subagent', parentSession: parent.id, delegationDepth: 1 };
  const child = Session.create('native-child', seed, header, SessionLogOffset(original.length));
  assert.deepEqual(parent.snapshotEvents(), original);
  assert.ok(JSON.stringify(child.deriveMessages()).includes('current-task-sentinel'));
  assert.equal(sessionEnvironment({ session: parent }).DSH_GRAPHTRAJ_SOURCE, 'main');
  assert.equal(sessionEnvironment({ session: child }).DSH_GRAPHTRAJ_SOURCE, 'child');
}
'''
    result = subprocess.run([
        node, '--input-type=module', '-e', script, str(module), str(Path(executable).resolve()), runtime,
    ], cwd=project, env=environment, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
