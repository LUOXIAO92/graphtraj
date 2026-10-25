"""Pi and DSH Main continue the project's Main through their public host entries."""

from io import StringIO
import json
from pathlib import Path

import pytest

from agent_swarm import Caller, bind
from graphtraj.configuration.project_configuration import runner_directory
from graphtraj.execution.main_continuity import claim_main, claims, current_main, route_notice
from graphtraj.execution.runner_connection import connection_operation
from graphtraj.interfaces.agents import GraphTrajAgents
from test_agent_control import ScriptedDriver
from test_external_session_entry import dsh_session, native, pi_session, project  # noqa: F401


CODEX = {'runtime': 'codex', 'session': 'codex-main', 'codex_home': '/home/.codex', 'hook_session': 'hook'}


def mcp(*calls: tuple[str, dict]) -> list[dict]:
    """Serve the given tool calls on the shipped MCP entry, as the host launched it."""
    from graphtraj.interfaces.mcp import serve

    requests = [{'jsonrpc': '2.0', 'id': index, 'method': 'tools/call',
                 'params': {'name': tool, 'arguments': arguments}}
                for index, (tool, arguments) in enumerate(calls)]
    output = StringIO()
    serve(StringIO('\n'.join(json.dumps(request) for request in requests)), output)
    return [json.loads(line)['result'] for line in output.getvalue().splitlines()]


def agents(feature: str, **arguments: object) -> tuple[str, dict]:
    """Return one public ``agents`` call."""
    return 'agents', {'action': 'execute', 'feature': feature, 'arguments': arguments}


def as_pi(project: Path, monkeypatch: pytest.MonkeyPatch, session: str) -> dict:
    """Use the per-call association Pi's extension gives its MCP server and shell."""
    for name in ('DSH_SESSION_ID', 'DSH_AGENT_SOURCE', 'DSH_GRAPHTRAJ_SESSION', 'DSH_GRAPHTRAJ_SOURCE'):
        monkeypatch.delenv(name, raising=False)
    return pi_session(project, monkeypatch, session, [])


def as_dsh_mcp(monkeypatch: pytest.MonkeyPatch, session: str) -> None:
    """Use the environment the DSH agents plugin gives its MCP server."""
    for name in ('GRAPHTRAJ_NATIVE_RUNTIME', 'DSH_GRAPHTRAJ_SESSION', 'DSH_GRAPHTRAJ_SOURCE'):
        monkeypatch.delenv(name, raising=False)
    dsh_session(monkeypatch, session)
    monkeypatch.delenv('DSH_GRAPHTRAJ_SESSION')
    monkeypatch.delenv('DSH_GRAPHTRAJ_SOURCE')
    monkeypatch.setenv('DSH_AGENT_SOURCE', 'main')


def released(driver: ScriptedDriver) -> None:
    """Let every scripted execution finish."""
    for release in list(driver.releases.values()):
        release.set()


@pytest.mark.parametrize('layout', ['legacy', 'core'])
def test_pi_and_dsh_main_continue_control_and_receive_notices(
    project: Path, monkeypatch: pytest.MonkeyPatch, layout: str,  # noqa: F811
) -> None:
    """Codex seeds a root; Pi, then DSH continue it, control it and receive notices.

    The core layout keeps every Main record under ``.graphtraj/core/runner``.
    """
    if layout == 'core':
        (project / '.graphtraj/core').mkdir()
        (project / '.graphtraj/config.yml').rename(project / '.graphtraj/core/config.yml')
    runner = runner_directory(project)
    assert runner == project / ('.graphtraj/core/runner' if layout == 'core' else '.graphtraj/runner')
    driver = ScriptedDriver()
    monkeypatch.setattr('graphtraj.execution.agent_driver.AdapterDriver', lambda root, cwd: driver)
    claim_main(runner, CODEX, 'codex:SessionStart:startup')
    codex = bind(GraphTrajAgents(project).control, Caller('graphtraj-gateway', None, 'codex-main', 'codex'))
    agent = codex({'action': 'create', 'runtime': 'claude', 'instruction': 'seed'}).document['agent']
    released(driver)
    codex({'action': 'wait', 'agent': agent, 'timeout_seconds': 5})

    # Pi session_start continues Main; its MCP entry shows the existing member.
    assert native('pi', as_pi(project, monkeypatch, 'pi-main')) == {'source': 'main'}
    assert current_main(runner)['entry'] == 'pi:session_start:startup'
    status, graph = mcp(agents('status'), ('tasks', {'action': 'execute', 'feature': 'task_graph', 'arguments': {}}))
    assert [item['agent'] for item in status['structuredContent']['result']['agents']] == [agent]
    assert not graph['isError']
    sent, = mcp(agents('send', agent=agent, message='from-pi'))
    assert not sent['isError'], sent
    released(driver)
    done, = mcp(agents('wait', agent=agent, timeout_seconds=5))
    assert 'from-pi' in done['structuredContent']['result']['last_result']['last_message']
    refused = codex({'action': 'send', 'agent': agent, 'message': 'old-main'})
    assert refused.document['error']['code'] == 'main-continued'

    # A notice for the earlier Main's root reaches the Pi Main's host entry.
    connection_operation(route_notice(runner, CODEX), {'alias': 'leader@l1', 'event': 'completed', 'message': 'done-1'})
    pending = native('pi', {'event': 'notices'})
    assert pending['notices'] == 1 and 'leader@l1' in pending['text'] and 'done-1' in pending['text']
    assert native('pi', {'event': 'notices_ack', 'position': pending['position']}) == {'acknowledged': True}
    assert native('pi', {'event': 'notices'})['notices'] == 0
    connection_operation(route_notice(runner, CODEX), {'alias': 'leader@l1', 'event': 'completed', 'message': 'done-2'})

    # DSH agent/created continues Main; the undelivered Pi notice moves with it.
    dsh_session(monkeypatch, 'dsh-main')
    header = {'version': 4, 'id': 'dsh-main', 'isSeeded': False}
    assert native('dsh', {'event': 'agent/created', 'source': 'startup', 'header': header}) == {'source': 'main'}
    pending = native('dsh', {'event': 'notices'})
    assert pending['notices'] == 1 and 'done-2' in pending['text']
    native('dsh', {'event': 'notices_ack', 'position': pending['position']})
    as_dsh_mcp(monkeypatch, 'dsh-main')
    status, sent = mcp(agents('status'), agents('send', agent=agent, message='from-dsh'))
    assert [item['agent'] for item in status['structuredContent']['result']['agents']] == [agent]
    assert not sent['isError'], sent
    released(driver)
    mcp(agents('wait', agent=agent, timeout_seconds=5))

    # The superseded Pi Main still reads but its control is refused.
    as_pi(project, monkeypatch, 'pi-main')
    status, refused = mcp(agents('status'), agents('send', agent=agent, message='stale-pi'))
    assert [item['agent'] for item in status['structuredContent']['result']['agents']] == [agent]
    assert refused['structuredContent']['error']['code'] == 'main-continued'

    # Native children never continue Main; the record is append-only.
    dsh_session(monkeypatch, 'dsh-child', 'child')
    child = {**header, 'id': 'dsh-child', 'origin': 'subagent', 'parentSession': 'dsh-main', 'delegationDepth': 1}
    assert native('dsh', {'event': 'agent/created', 'source': 'startup', 'header': child}) == {'source': 'child'}
    monkeypatch.setenv('PI_SUBAGENT_CHILD', '1')
    assert native('pi', as_pi(project, monkeypatch, 'pi-child')) == {'source': 'child'}
    assert [(item['runtime'], item['session']) for item in claims(runner)] == [
        ('codex', 'codex-main'), ('pi', 'pi-main'), ('dsh', 'dsh-main')]
    assert len(driver.started) == 3
    assert (runner / 'main-sessions/continuity.jsonl').is_file()
    assert not (project / '.graphtraj/runner').exists() or layout == 'legacy'


def test_dsh_mcp_source_must_be_known(monkeypatch: pytest.MonkeyPatch) -> None:
    """The agents plugin's unknown source, or a stale shell namespace, is refused."""
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.runtimes.dsh.session_entry import current_connection

    monkeypatch.setenv('DSH_SESSION_ID', 'dsh-main')
    monkeypatch.setenv('DSH_AGENT_SOURCE', 'unknown')
    with pytest.raises(RunnerError, match='Unknown DSH Session source'):
        current_connection()
    monkeypatch.setenv('DSH_AGENT_SOURCE', 'main')
    assert current_connection() == {'runtime': 'dsh', 'session': 'dsh-main', 'source': 'main'}
    monkeypatch.setenv('DSH_GRAPHTRAJ_SESSION', 'other')
    with pytest.raises(RunnerError, match='stale'):
        current_connection()


@pytest.mark.parametrize('runtime', ['pi', 'dsh'])
def test_host_integration_delivers_then_acknowledges(
    project: Path, monkeypatch: pytest.MonkeyPatch, runtime: str,  # noqa: F811
) -> None:
    """The shipped Pi extension / DSH plugin put queued notices into the Main once."""
    import os
    import shutil
    import subprocess
    import sys

    node = shutil.which('node')
    if node is None or (runtime == 'dsh' and shutil.which('dsh') is None):
        pytest.skip(f'Node and the installed {runtime} are required')
    runner = project / '.graphtraj/runner'
    if runtime == 'pi':
        assert native('pi', as_pi(project, monkeypatch, 'pi-main')) == {'source': 'main'}
        module = 'src/graphtraj/runtimes/pi/extension.mjs'
    else:
        dsh_session(monkeypatch, 'dsh-main')
        header = {'version': 4, 'id': 'dsh-main', 'isSeeded': False, 'cwd': str(project)}
        assert native('dsh', {'event': 'agent/created', 'source': 'startup', 'header': header}) == {'source': 'main'}
        module = 'src/graphtraj/runtimes/dsh/tool.mjs'
    connection_operation(route_notice(runner, current_main(runner)['connection'] | {'runtime': runtime}),
                         {'alias': 'leader@l1', 'event': 'completed', 'message': 'done-host'})
    script = '''
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const [module, runtime, cwd] = process.argv.slice(1);
const { deliverNotices } = await import(pathToFileURL(module).href);
const delivered = [];
if (runtime === 'pi') {
  const pi = { sendMessage: (message, options) => delivered.push({ message, options }) };
  const ctx = { cwd };
  const environment = { GRAPHTRAJ_NATIVE_RUNTIME: 'pi', GRAPHTRAJ_NATIVE_SESSION: process.env.GRAPHTRAJ_NATIVE_SESSION,
    GRAPHTRAJ_NATIVE_SESSION_FILE: process.env.GRAPHTRAJ_NATIVE_SESSION_FILE };
  // A fresh Pi Session has no file until its first conversation message:
  // nothing is delivered and no error is raised; the notice stays queued.
  const { renameSync } = await import('node:fs');
  const file = environment.GRAPHTRAJ_NATIVE_SESSION_FILE;
  renameSync(file, file + '.unwritten');
  assert.equal(await deliverNotices(pi, ctx, environment), 0);
  assert.equal(delivered.length, 0);
  renameSync(file + '.unwritten', file);
  assert.equal(await deliverNotices(pi, ctx, environment), 1);
  assert.equal(await deliverNotices(pi, ctx, environment), 0);
  assert.equal(delivered[0].options.triggerTurn, true);
  assert.match(delivered[0].message.content, /leader@l1[\\s\\S]*done-host/);
} else {
  const { spawn } = await import('node:child_process');
  const agent = { session: { id: 'dsh-main', header: { cwd } },
    send: (message, queue, wake) => delivered.push({ message, queue, wake }) };
  // The same native entry the plugin's apply() closes over.
  const entry = (agent, event) => new Promise((resolve, reject) => {
    const child = spawn('graphtraj-session', ['dsh'], { cwd, env: { ...process.env,
      DSH_SESSION_ID: agent.session.id, DSH_GRAPHTRAJ_SESSION: agent.session.id, DSH_GRAPHTRAJ_SOURCE: 'main' } });
    let output = '';
    child.stdout.on('data', value => { output += value; });
    child.on('close', () => { const result = JSON.parse(output); result.error ? reject(new Error(result.error)) : resolve(result); });
    child.stdin.end(JSON.stringify(event));
  });
  assert.equal(await deliverNotices(agent, entry), 1);
  assert.equal(await deliverNotices(agent, entry), 0);
  assert.equal(delivered[0].queue, 'next-step');
  assert.equal(delivered[0].message.source.kind, 'agent-message');
  assert.match(delivered[0].message.content[0].text, /leader@l1[\\s\\S]*done-host/);
}
'''
    root = Path(__file__).resolve().parents[1]
    environment = {**os.environ, 'PATH': f'{Path(sys.executable).parent}{os.pathsep}{os.environ["PATH"]}',
                   'GRAPHTRAJ_DSH_PACKAGE': str(Path(shutil.which('dsh') or node).resolve())}
    result = subprocess.run([node, '--input-type=module', '-e', script, str(root / module), runtime, str(project)],
                            cwd=project, env=environment, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('arguments', ['pi', 'pi       ', 'pi-rpc'])
def test_pi_titled_node_process_is_the_pi_runtime(monkeypatch: pytest.MonkeyPatch, arguments: str) -> None:
    """Pi 1.3's process.title replaces its kernel argv; the Pi Main is still recognized."""
    from graphtraj.runtimes import replacement

    monkeypatch.setattr(replacement, 'process_ancestors', lambda pid: [pid, 700])
    monkeypatch.setattr(replacement, 'process_executable', lambda pid: Path('/opt/homebrew/bin/node'))
    monkeypatch.setattr(replacement.sys, 'platform', 'darwin')
    monkeypatch.setattr(replacement.subprocess, 'check_output', lambda *args, **kwargs: arguments)
    assert replacement.caller_runtime() == 'pi'
    monkeypatch.setattr(replacement.subprocess, 'check_output', lambda *args, **kwargs: 'pi other-script.js')
    assert replacement.caller_runtime() is None
