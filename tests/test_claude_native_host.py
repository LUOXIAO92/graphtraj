"""Current-context binding boundaries without launching a real Runtime."""
from io import StringIO
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from agent_swarm import AgentsError, AgentsResult
from graphtraj.runtimes.claude.host import NativeCalls, native_parent
from graphtraj.runtimes.claude.mcp import serve


def test_progressive_mcp_consumes_current_context_once(tmp_path: Path) -> None:
    """MCP payloads cannot pick callers, replay a grant, or reuse stale Session facts."""
    invocations = []

    def bind(session: str, cwd: Path):
        """Record only the caller established outside the model request."""
        def call(tool: str, request: dict) -> AgentsResult:
            invocations.append((tool, session, cwd, request))
            return AgentsResult({'native': session, 'tool': tool})
        return call

    host = NativeCalls(bind, tmp_path)
    request = {'action': 'execute', 'feature': 'status', 'arguments': {}}
    with pytest.raises(AgentsError, match='No matching'):
        host.call(request)
    first, second = str(uuid4()), str(uuid4())
    context = {'operation': 'prepare', 'tool': 'agents', 'session': first, 'cwd': str(tmp_path),
               'agent': None, 'request': request}
    host.context(context)
    assert host.call(request).document == {'native': first, 'tool': 'agents'}
    with pytest.raises(AgentsError, match='No matching'):
        host.call(request)
    host.context({**context, 'session': second})
    assert host.call(request).document == {'native': second, 'tool': 'agents'}
    # One association serves only the entry it was prepared for.
    host.context({**context, 'tool': 'tasks'})
    with pytest.raises(AgentsError, match='No matching'):
        host.call(request)
    host.context({**context, 'tool': 'tasks'})
    assert host.call(request, 'tasks').document == {'native': first, 'tool': 'tasks'}
    with pytest.raises(AgentsError, match='agents or tasks'):
        host.context({**context, 'tool': 'other'})
    host.context(context)
    with pytest.raises(AgentsError, match='No matching'):
        host.call({**request, 'arguments': {'caller': first}})
    with pytest.raises(AgentsError, match='subagent'):
        host.context({**context, 'agent': 'native-child'})
    with pytest.raises(AgentsError, match='cwd'):
        host.context({**context, 'cwd': str(tmp_path / 'elsewhere')})
    host.context(context)
    host.context({'operation': 'end'})
    with pytest.raises(AgentsError, match='No matching'):
        host.call(request)
    assert len(invocations) == 3

    output = StringIO()
    serve(StringIO(json.dumps({'id': 1, 'method': 'tools/list'}) + '\n'), output,
          tmp_path, native_call=host.call)
    tools = json.loads(output.getvalue())['result']['tools']
    assert [tool['name'] for tool in tools] == ['agents', 'tasks']
    assert tools[0]['inputSchema']['properties']['action']['enum'] == ['discover', 'describe', 'execute']
    assert 'runtime' not in tools[0]['inputSchema']['properties']


def test_call_queued_behind_a_running_call_keeps_its_own_association(tmp_path: Path) -> None:
    """A call whose native call ended while an earlier one ran is still served as itself."""
    import threading

    release, invocations = threading.Event(), []

    def bind(session: str, cwd: Path):
        """Hold the first request open like a long agents wait."""
        def call(tool: str, request: dict) -> AgentsResult:
            invocations.append((session, request['feature']))
            if request['feature'] == 'wait':
                release.wait(10)
            return AgentsResult({'native': session})
        return call

    host = NativeCalls(bind, tmp_path)
    session, other = str(uuid4()), str(uuid4())

    def prepare(feature: str, native: str = session) -> dict:
        """Prepare one native call as the mod does during Claude's permission check."""
        request = {'action': 'execute', 'feature': feature, 'arguments': {}}
        host.context({'operation': 'prepare', 'tool': 'agents', 'session': native,
                      'cwd': str(tmp_path), 'agent': None, 'request': request})
        return request

    waiting = prepare('wait')
    running = threading.Thread(target=host.call, args=(waiting,))
    running.start()
    while not invocations:
        pass
    # Claude ends the next call's native window before the MCP entry reads it.
    queued = prepare('status')
    host.context({'operation': 'end'})
    release.set()
    running.join()
    assert host.call(queued).document == {'native': session}

    # Another Session's preparation drops an association it does not own.
    release.clear()
    running = threading.Thread(target=host.call, args=(prepare('wait'),))
    running.start()
    while len(invocations) < 3:
        pass
    queued = prepare('status')
    host.context({'operation': 'end'})
    prepare('requests', other)
    release.set()
    running.join()
    with pytest.raises(AgentsError, match='No matching'):
        host.call(queued)
    assert invocations == [(session, 'wait'), (session, 'status'), (session, 'wait')]


def test_native_host_does_not_trust_session_environment(tmp_path: Path, monkeypatch) -> None:
    """A shell-launched client with invented native env is not a Claude parent."""
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', str(uuid4()))
    with pytest.raises(AgentsError, match='directly'):
        native_parent(tmp_path / 'not-claude')


def test_context_uses_owner_executable_when_launcher_updates(tmp_path: Path, monkeypatch, capsys) -> None:
    """The public context entry keeps the same native parent after a symlink update."""
    import os
    from graphtraj.runtimes.claude import host

    original, updated = tmp_path / '2.1.299', tmp_path / '2.1.302'
    original.touch()
    updated.touch()
    launcher = tmp_path / 'claude'
    launcher.symlink_to(original)
    endpoint = tmp_path / 'endpoint.json'
    config = tmp_path / 'host.json'
    config.write_text(json.dumps({'root': str(tmp_path), 'cwd': str(tmp_path),
                                 'claude': str(launcher), 'channel_file': str(endpoint)}))
    monkeypatch.setattr(host, 'process_executable', lambda pid: original)
    parent = host.native_parent(launcher)
    endpoint.write_text(json.dumps({'parent': parent, 'executable': str(launcher.resolve()),
                                    'address': 'owned-channel'}))
    launcher.unlink()
    launcher.symlink_to(updated)
    # This is exactly the old per-helper comparison: it rejects the still-live
    # original process when the installer changes the launcher's target.
    with pytest.raises(AgentsError, match='expected_executable.*2.1.302'):
        host.native_parent(launcher, stage='context')
    received = []

    def exchange(address: str, document: dict, *, authenticate: bool) -> dict:
        """Observe the authenticated existing transport, not a replacement identity."""
        received.append((address, document, authenticate))
        return {'ended': True}

    monkeypatch.setattr(host, 'connection_operation', exchange)
    monkeypatch.setattr('sys.argv', ['host', 'context', '--config', str(config)])
    monkeypatch.setattr('sys.stdin', StringIO('{"operation":"end"}'))
    host.main()
    assert json.loads(capsys.readouterr().out) == {'ended': True}
    assert received == [('owned-channel', {'operation': 'end'}, True)]
    assert parent == os.getppid()

    # An unrelated direct parent still fails, even though the launcher now
    # selects its executable. No arbitrary ancestor or new version is allowed.
    monkeypatch.setattr(host, 'process_executable', lambda pid: updated)
    monkeypatch.setattr('sys.stdin', StringIO('{"operation":"end"}'))
    with pytest.raises(AgentsError, match='observed_executable.*2.1.302'):
        host.main()
    assert len(received) == 1


def test_mod_notice_operations_read_then_acknowledge(tmp_path: Path) -> None:
    """The mod reads pending Main notices and acknowledges a position it was given."""
    from graphtraj.execution.main_continuity import queue_notice

    session = str(uuid4())
    host = NativeCalls(lambda session, cwd: None, tmp_path, tmp_path)
    queue_notice(tmp_path, {'runtime': 'claude', 'session': session}, {'alias': 'leader@l1'})
    pending = host.context({'operation': 'notices', 'session': session})
    assert [item['event']['alias'] for item in pending['notices']] == ['leader@l1']
    assert host.context({'operation': 'notices', 'session': session})['notices'] == pending['notices']
    host.context({'operation': 'acknowledge', 'session': session, 'position': pending['position']})
    assert host.context({'operation': 'notices', 'session': session})['notices'] == []
    with pytest.raises(AgentsError):
        host.context({'operation': 'acknowledge', 'session': session, 'position': '1'})
    with pytest.raises(ValueError):
        host.context({'operation': 'notices', 'session': 'not-a-uuid'})


def test_adoption_material_is_the_plugin_layout_and_keeps_settings(tmp_path: Path) -> None:
    """configuration --write produces the plugin directory and merges existing JSON settings."""
    from graphtraj.runtimes.claude.host import adoption_material, write_adoption

    (tmp_path / '.claude').mkdir()
    (tmp_path / '.claude/settings.local.json').write_text(json.dumps({'env': {'KEEP': '1'}, 'permissions': {'allow': []}}))
    material = adoption_material(tmp_path, tmp_path / 'claude')
    write_adoption(material)
    plugin = tmp_path / '.claude/skills/graphtraj-claude-host'
    assert json.loads((plugin / 'hooks/hooks.json').read_text()) == {'modules': ['./host_context.mjs']}
    assert json.loads((plugin / '.claude-plugin/plugin.json').read_text())['name'] == 'graphtraj-claude-host'
    assert 'export function register' in (plugin / 'hooks/host_context.mjs').read_text()
    settings = json.loads((tmp_path / '.claude/settings.local.json').read_text())
    assert settings['env']['KEEP'] == '1' and 'GRAPHTRAJ_CLAUDE_HOST_CONFIG' in settings['env']
    assert settings['permissions'] == {'allow': []}
    assert list(json.loads((tmp_path / '.mcp.json').read_text())['mcpServers']) == ['agents']


def test_generated_hook_context_accepts_the_project_host_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """The written hook's agent_swarm context entry reaches the project host's own channel."""
    from agent_swarm.claude import host as native
    from graphtraj.runtimes.claude.host import adoption_material, write_adoption

    write_adoption(adoption_material(tmp_path, tmp_path / 'claude'))
    hook = (tmp_path / '.claude/skills/graphtraj-claude-host/hooks/host_context.mjs').read_text()
    assert "'-m', 'agent_swarm.claude.host'" in hook
    config = tmp_path / '.graphtraj/claude-host/config.json'
    endpoint = Path(json.loads(config.read_text())['channel_file'])
    endpoint.parent.mkdir(parents=True)
    endpoint.write_text(json.dumps({'parent': os.getppid(), 'executable': str(tmp_path / 'claude'),
                                    'address': 'project-host-channel'}))
    received = []
    monkeypatch.setattr(native, 'native_parent', lambda executable, stage: os.getppid())
    monkeypatch.setattr(native, 'connection_operation', lambda address, document, *, authenticate:
                        received.append((address, document, authenticate)) or {'ended': True})
    monkeypatch.setattr('sys.argv', ['host', 'context', '--config', str(config)])
    monkeypatch.setattr('sys.stdin', StringIO('{"operation":"end"}'))
    native.main()
    assert json.loads(capsys.readouterr().out) == {'ended': True}
    assert received == [('project-host-channel', {'operation': 'end'}, True)]


def test_configured_launcher_survives_a_claude_update(tmp_path: Path, monkeypatch) -> None:
    """The stored launcher is resolved at check time; other parents stay refused."""
    from graphtraj.runtimes.claude import host

    old, new, other = tmp_path / '2.1.306', tmp_path / '2.1.307', tmp_path / 'other-cli'
    for path in (old, new, other):
        path.touch()
    launcher = tmp_path / 'claude'
    launcher.symlink_to(old)
    stored = Path(host.adoption_material(tmp_path, launcher)[str(tmp_path / '.graphtraj/claude-host/config.json')]['claude'])
    assert stored == launcher

    launcher.unlink()
    launcher.symlink_to(new)  # Claude Code updated itself after configuration.
    monkeypatch.setattr(host, 'process_executable', lambda pid: new)
    assert host.native_parent(stored) > 1
    monkeypatch.setattr(host, 'process_executable', lambda pid: other)
    with pytest.raises(AgentsError, match='observed_executable.*other-cli'):
        host.native_parent(stored)


def test_host_survives_failing_task_operations(tmp_path: Path) -> None:
    """A rejected or crashing operation is a tool error; later calls are still served."""
    failures = iter([ValueError('Task 901 is already registered'), RuntimeError('boom')])

    def call(request: dict, tool: str = 'agents') -> AgentsResult:
        """Fail twice, then answer, like a Task write followed by a status read."""
        failure = next(failures, None)
        if failure is not None:
            raise failure
        return AgentsResult({'ok': tool})

    request = {'action': 'execute', 'feature': 'task_register', 'arguments': {}}
    lines = ''.join(json.dumps({'jsonrpc': '2.0', 'id': index, 'method': 'tools/call',
                                'params': {'name': 'tasks', 'arguments': request}}) + '\n'
                    for index in range(3))
    output = StringIO()
    serve(StringIO(lines), output, tmp_path, native_call=call)
    replies = [json.loads(line)['result'] for line in output.getvalue().splitlines()]
    assert [reply['isError'] for reply in replies] == [True, True, False]
    assert replies[0]['structuredContent']['error'] == {'code': 'operation-failed',
                                                       'message': 'Task 901 is already registered'}
    assert replies[1]['structuredContent']['error']['code'] == 'internal-error'
    assert replies[2]['structuredContent'] == {'ok': 'tasks'}


def test_stray_output_never_reaches_the_mcp_channel(tmp_path: Path) -> None:
    """Prints, subprocess output and stdin readers cannot touch the reserved MCP stdio."""
    import subprocess
    import sys

    program = (
        'import os, sys; from pathlib import Path\n'
        'from graphtraj.runtimes.claude.host import isolate_stdio\n'
        'mcp_in, mcp_out = isolate_stdio(Path(sys.argv[1]))\n'
        'print("stray print"); os.system("echo stray subprocess; cat > /dev/null")\n'
        'mcp_out.write(mcp_in.readline().upper()); mcp_out.flush()\n'
    )
    log = tmp_path / 'claude-host/host.log'
    result = subprocess.run([sys.executable, '-c', program, str(log)], input='{"id": 1}\n',
                            capture_output=True, text=True, timeout=20,
                            env={**__import__('os').environ, 'PYTHONPATH': 'src'})
    assert result.returncode == 0, result.stderr
    assert result.stdout == '{"ID": 1}\n'
    assert 'stray print' in log.read_text() and 'stray subprocess' in log.read_text()


def _host_project(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Write a GraphTraj host configuration whose verified CLI is this Python's launcher."""
    import sys

    project, elsewhere = tmp_path / 'project', tmp_path / 'elsewhere'
    elsewhere.mkdir()
    config = project / '.graphtraj' / 'claude-host' / 'config.json'
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({'root': str(project), 'cwd': str(project), 'claude': sys.executable,
                                  'channel_file': str(config.parent / 'live' / 'channel.json')}))
    return project, elsewhere, config


def _source_env(**extra: str) -> dict:
    """Run the host from this checkout."""
    import graphtraj

    source = str(Path(graphtraj.__file__).parents[1])
    return {**os.environ, 'PYTHONPATH': source + os.pathsep + os.environ.get('PYTHONPATH', ''), **extra}


@pytest.mark.parametrize('case', ['elsewhere', 'bound-child', 'stale-channel', 'bad-config'])
def test_refused_graphtraj_host_answers_both_tools_with_the_reason(tmp_path: Path, case: str) -> None:
    """A refused start completes the handshake and every agents and tasks call names why; no Main is bound."""
    import subprocess
    import sys

    project, elsewhere, config = _host_project(tmp_path)
    host = config.parent
    channel = host / 'live' / 'channel.json'
    if case == 'stale-channel':
        channel.parent.mkdir()
        channel.write_text('{"parent": 1}')
    if case == 'bad-config':
        config.write_text(json.dumps({**json.loads(config.read_text()), 'extra': 1}))
    messages = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}},
                {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                 'params': {'name': 'agents', 'arguments': {'action': 'discover'}}},
                {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call',
                 'params': {'name': 'tasks', 'arguments': {'action': 'discover'}}}]
    launcher = ('import subprocess, sys\n'
                'done = subprocess.run([sys.executable, "-m", "graphtraj.runtimes.claude.host", "serve", "--config",'
                ' sys.argv[1]], input=sys.stdin.read(), capture_output=True, text=True, timeout=30)\n'
                'sys.stdout.write(done.stdout); sys.stderr.write(done.stderr)\n')
    env = _source_env(**({'AGENT_SWARM_CONNECTION': 'bound'} if case == 'bound-child' else {}))
    finished = subprocess.run([sys.executable, '-c', launcher, str(config)],
                              cwd=elsewhere if case == 'elsewhere' else project,
                              input=''.join(json.dumps(message) + '\n' for message in messages),
                              capture_output=True, text=True, timeout=60, env=env)
    replies = [json.loads(line) for line in finished.stdout.splitlines()]
    assert replies[0]['result']['serverInfo'] == {'name': 'agents', 'version': '1'}
    assert [tool['name'] for tool in replies[1]['result']['tools']] == ['agents', 'tasks']
    errors = []
    for reply in replies[2:]:
        assert reply['result']['isError'] is True
        errors.append(reply['result']['structuredContent']['error'])
    assert errors[0] == errors[1]
    error = errors[0]
    assert error['message'].startswith('The agents host did not start: ')
    expected = {'elsewhere': ('host-unavailable', [f'started in {elsewhere.resolve()}',
                                                   f'configured for {project.resolve()}',
                                                   f'Start or resume Claude Code from {project.resolve()}']),
                'bound-child': ('authority-denied', ['bound child']),
                'stale-channel': ('host-busy', [f'{channel} exists', 'delete the file']),
                'bad-config': ('host-unavailable', [str(config), 'Expected root, cwd, claude and channel_file'])}
    code, parts = expected[case]
    assert error['code'] == code and all(part in error['message'] for part in parts), error
    assert error['message'] in finished.stderr
    log = (host / 'host.log').read_text()
    assert error['message'] in log and 'Traceback' not in log
    # No control, channel, archive configuration or Main claim was made.
    assert not (project / '.graphtraj' / 'swarm').exists()
    assert not list(project.rglob('main-sessions')) and not (host / 'host-refusal.json').exists()
    assert sorted(path.name for path in (host / 'live').glob('*')) == (
        ['channel.json'] if case == 'stale-channel' else [])
    if case == 'stale-channel':
        assert channel.read_text() == '{"parent": 1}'


@pytest.mark.parametrize('case', ['refused', 'serving'])
def test_graphtraj_session_end_is_one_stop_line(tmp_path: Path, case: str) -> None:
    """Claude Code's SIGINT at session end leaves one stop line and no traceback in host.log."""
    import subprocess
    import sys

    project, elsewhere, config = _host_project(tmp_path)
    channel = config.parent / 'live' / 'channel.json'
    stale = config.parent / 'host-refusal.json'
    stale.write_text('{"code": "old", "message": "old"}')
    launcher = ('import json, signal, subprocess, sys\n'
                'host = subprocess.Popen([sys.executable, "-m", "graphtraj.runtimes.claude.host", "serve", "--config",'
                ' sys.argv[1]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)\n'
                'host.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",'
                ' "params": {}}) + "\\n"); host.stdin.flush()\n'
                'print(host.stdout.readline().strip())\n'
                'host.send_signal(signal.SIGINT)\n'
                'print(host.wait(timeout=30))\n')
    finished = subprocess.run([sys.executable, '-c', launcher, str(config)],
                              cwd=elsewhere if case == 'refused' else project,
                              capture_output=True, text=True, timeout=60, env=_source_env())
    reply, returncode = finished.stdout.splitlines()
    assert json.loads(reply)['result']['serverInfo']['name'] == 'agents'
    assert returncode == '0', finished.stderr
    log = (config.parent / 'host.log').read_text()
    assert 'Traceback' not in log and 'KeyboardInterrupt' not in log
    assert log.count('agents host stopped: Claude Code ended the session (SIGINT).') == 1
    assert not channel.exists() and not stale.exists()
    if case == 'refused':
        assert 'The agents host did not start: Claude Code was started in' in log
    else:
        assert 'did not start' not in log


@pytest.mark.parametrize('module', ['graphtraj.runtimes.claude.host', 'agent_swarm.claude.host'])
def test_graphtraj_context_reports_a_refused_host_in_one_line(tmp_path: Path, module: str) -> None:
    """Both mod context entries report a GraphTraj host's absence or refusal in one line."""
    import subprocess
    import sys

    project, elsewhere, config = _host_project(tmp_path)
    env = _source_env()

    def context() -> subprocess.CompletedProcess:
        """Run the mod's context entry as the hook does, with one request on stdin."""
        return subprocess.run([sys.executable, '-m', module, 'context', '--config', str(config)],
                              input='{}', capture_output=True, text=True, timeout=30, env=env)

    idle = context()
    assert idle.returncode == 1 and 'Traceback' not in idle.stderr
    assert idle.stderr.splitlines() == [
        f"The agents host for this project is not running; see {config.parent / 'host.log'}."]
    launcher = ('import json, signal, subprocess, sys\n'
                'host = subprocess.Popen([sys.executable, "-m", "graphtraj.runtimes.claude.host", "serve", "--config",'
                ' sys.argv[1]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)\n'
                'host.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",'
                ' "params": {}}) + "\\n"); host.stdin.flush()\n'
                'print(host.stdout.readline().strip()); sys.stdout.flush()\n'
                'sys.stdin.readline()\n'
                'host.send_signal(signal.SIGINT)\n'
                'print(host.wait(timeout=30))\n')
    host = subprocess.Popen([sys.executable, '-c', launcher, str(config)], cwd=elsewhere, env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert json.loads(host.stdout.readline())['result']['serverInfo']['name'] == 'agents'
    refused = context()
    host.stdin.write('stop\n')
    host.stdin.flush()
    assert host.stdout.readline().strip() == '0'
    host.wait(timeout=30)
    assert refused.returncode == 1 and 'Traceback' not in refused.stderr
    [line] = refused.stderr.splitlines()
    assert line.startswith('host-unavailable: The agents host did not start: Claude Code was started in ')
    assert f'configured for {project.resolve()}' in line
    assert not (config.parent / 'host-refusal.json').exists()
