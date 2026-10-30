"""Current-context binding boundaries without launching a real Runtime."""
import fcntl
from io import StringIO
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from uuid import uuid4

import pytest

from agent_swarm import AgentsError, AgentsResult
from conftest import HeldInput
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
    monkeypatch.setattr('agent_swarm.claude.host.host_alive', lambda address: True)
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


def test_mod_notice_operations_claim_then_requeue(tmp_path: Path) -> None:
    """The mod claims pending Main notices once and queues back the ones it could not submit.

    Since 3a6f351 ``notices`` is an atomic claim, so a second reader gets
    nothing; ``acknowledge`` from an earlier mod is accepted and changes nothing.
    """
    from graphtraj.execution.main_continuity import queue_notice

    session = str(uuid4())
    host = NativeCalls(lambda session, cwd: None, tmp_path, tmp_path)
    queue_notice(tmp_path, {'runtime': 'claude', 'session': session}, {'alias': 'leader@l1'})
    pending = host.context({'operation': 'notices', 'session': session})
    assert [item['event']['alias'] for item in pending['notices']] == ['leader@l1']
    assert host.context({'operation': 'notices', 'session': session})['notices'] == []
    assert host.context({'operation': 'acknowledge', 'session': session,
                         'position': pending['position']}) == {'acknowledged': True}
    assert host.context({'operation': 'notices', 'session': session})['notices'] == []
    ids = [item['id'] for item in pending['notices']]
    assert host.context({'operation': 'requeue', 'session': session, 'ids': ids}) == {'requeued': 1}
    assert host.context({'operation': 'requeue', 'session': session, 'ids': ids}) == {'requeued': 0}
    again = host.context({'operation': 'notices', 'session': session})['notices']
    assert [(item['id'], item['event']) for item in again] == [
        (item['id'], item['event']) for item in pending['notices']]
    assert host.context({'operation': 'notices', 'session': session})['notices'] == []
    with pytest.raises(AgentsError):
        host.context({'operation': 'acknowledge', 'session': session, 'position': '1'})
    with pytest.raises(AgentsError):
        host.context({'operation': 'requeue', 'session': session, 'ids': 'not-a-list'})
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
    monkeypatch.setattr(native, 'host_alive', lambda address: True)
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
    lock = threading.Lock()

    def call(request: dict, tool: str = 'agents') -> AgentsResult:
        """Fail twice, then answer, like a Task write followed by a status read."""
        with lock:
            failure = next(failures, None)
        if failure is not None:
            raise failure
        return AgentsResult({'ok': tool})

    request = {'action': 'execute', 'feature': 'task_register', 'arguments': {}}
    lines = [json.dumps({'jsonrpc': '2.0', 'id': index, 'method': 'tools/call',
                         'params': {'name': 'tasks', 'arguments': request}}) + '\n'
             for index in range(3)]
    output = StringIO()
    serve(HeldInput(lines, lambda: output.getvalue().count('\n') >= 3), output, tmp_path, native_call=call)
    documents = [json.loads(line)['result']['structuredContent'] for line in output.getvalue().splitlines()]
    assert sorted(document.get('error', {}).get('code', 'ok') for document in documents) == [
        'internal-error', 'ok', 'operation-failed']
    assert {'code': 'operation-failed', 'message': 'Task 901 is already registered'} in [
        document.get('error') for document in documents]
    assert {'ok': 'tasks'} in documents


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


@pytest.fixture
def hold_control():
    """Hold a control directory's lock as a live host does, for this test's duration."""
    held = []

    def hold(directory: Path) -> Path:
        """Lock ``directory``, creating it first."""
        directory.mkdir(parents=True)
        held.append(os.open(directory, os.O_RDONLY | os.O_DIRECTORY))
        fcntl.flock(held[-1], fcntl.LOCK_EX)
        return directory

    yield hold
    for descriptor in held:
        os.close(descriptor)


@pytest.mark.parametrize('case', ['elsewhere', 'bound-child', 'live-occupant', 'bad-config'])
def test_refused_graphtraj_host_answers_both_tools_with_the_reason(tmp_path: Path, case: str, hold_control) -> None:
    """A refused start completes the handshake and every agents and tasks call names why; no Main is bound."""
    import subprocess
    import sys

    project, elsewhere, config = _host_project(tmp_path)
    host = config.parent
    channel = host / 'live' / 'channel.json'
    occupied = ''
    if case == 'live-occupant':
        occupied = json.dumps({'parent': 4242, 'executable': sys.executable,
                               'address': str(hold_control(channel.parent / 'control-held'))})
        channel.write_text(occupied)
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
                'live-occupant': ('host-busy', [str(channel), 'another agents host', 'Claude Code pid 4242',
                                                'Close that Claude Code session']),
                'bad-config': ('host-unavailable', [str(config), 'Expected root, cwd, claude and channel_file'])}
    code, parts = expected[case]
    assert error['code'] == code and all(part in error['message'] for part in parts), error
    assert 'delete' not in error['message']
    assert error['message'] in finished.stderr
    log = (host / 'host.log').read_text()
    assert error['message'] in log and 'Traceback' not in log
    # No control, channel, archive configuration or Main claim was made.
    assert not (project / '.graphtraj' / 'swarm').exists()
    assert not list(project.rglob('main-sessions')) and not (host / 'host-refusal.json').exists()
    assert sorted(path.name for path in (host / 'live').glob('*')) == (
        ['channel.json', 'control-held'] if case == 'live-occupant' else [])
    if case == 'live-occupant':
        assert channel.read_text() == occupied


@pytest.mark.parametrize('case', ['refused', 'serving'])
def test_graphtraj_session_end_is_one_stop_line(tmp_path: Path, case: str) -> None:
    """Claude Code's SIGINT at session end leaves one stop line and no traceback in host.log."""
    import subprocess
    import sys

    project, elsewhere, config = _host_project(tmp_path)
    channel = config.parent / 'live' / 'channel.json'
    stale = config.parent / 'host-refusal.json'
    stale.write_text('{"code": "old", "message": "old"}')
    # Like Claude Code, the launcher starts the host with the default SIGINT
    # disposition: a suite run as a background job would otherwise pass SIGINT
    # ignored (372, as in test_independent_claude 4003528).
    launcher = ('import json, signal, subprocess, sys\n'
                'host = subprocess.Popen([sys.executable, "-m", "graphtraj.runtimes.claude.host", "serve", "--config",'
                ' sys.argv[1]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,'
                ' preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))\n'
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
    # Like Claude Code, the launcher starts the host with the default SIGINT
    # disposition: a suite run as a background job would otherwise pass SIGINT
    # ignored (372, as in test_independent_claude 4003528).
    launcher = ('import json, signal, subprocess, sys\n'
                'host = subprocess.Popen([sys.executable, "-m", "graphtraj.runtimes.claude.host", "serve", "--config",'
                ' sys.argv[1]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,'
                ' preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))\n'
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


HOST_MODULES = ['graphtraj.runtimes.claude.host', 'agent_swarm.claude.host']
REPLACED_LINE = 'agents host replaced a stale channel of a dead host'
# The verified Claude parent: it owns one host and runs the mod's context entry as its direct child.
CLAUDE_PARENT = '''
import json, signal, subprocess, sys, time
module, config = sys.argv[1:]
host = None
for line in sys.stdin:
    command = json.loads(line)
    if command['do'] == 'start':
        # Like Claude Code, with the default SIGINT disposition. With ``hold`` the host passes
        # its early check, then waits for that file, so two hosts reach the claim together.
        program = ['-m', module, 'serve', '--config', config] if 'hold' not in command else ['-c',
            'import importlib, os, pathlib, sys, time\\n'
            'host = importlib.import_module(sys.argv[1]); go = pathlib.Path(sys.argv[2]); real = host.worker_connection\\n'
            'def held(*args, **fields):\\n'
            '    go.with_name(f"passed-{os.getpid()}").touch()\\n'
            '    while not go.exists(): time.sleep(0.01)\\n'
            '    return real(*args, **fields)\\n'
            'host.worker_connection = held; sys.argv = ["host", "serve", "--config", sys.argv[3]]; host.main()\\n',
            module, command['hold'], config]
        host = subprocess.Popen([sys.executable, *program], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                text=True, preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
        answer = host.pid
    elif command['do'] == 'send':
        host.stdin.write(json.dumps(command['message']) + '\\n')
        host.stdin.flush()
        answer = json.loads(host.stdout.readline())
    elif command['do'] == 'context':
        started = time.monotonic()
        done = subprocess.run([sys.executable, '-m', module, 'context', '--config', config],
                              input=json.dumps(command['document']), capture_output=True, text=True, timeout=30)
        answer = {'code': done.returncode, 'out': done.stdout, 'err': done.stderr,
                  'seconds': time.monotonic() - started}
    elif command['do'] == 'kill':
        host.kill()
        answer = host.wait()
    print(json.dumps(answer), flush=True)
if host is not None:
    host.stdin.close()
    host.wait(timeout=30)
'''


class ClaudeParent:
    """One running verified parent, standing in for one Claude Code process."""

    def __init__(self, module: str, project: Path, config: Path) -> None:
        self.project = project
        self.process = subprocess.Popen([sys.executable, '-c', CLAUDE_PARENT, module, str(config)], cwd=project,
                                        env=_source_env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.pid = self.process.pid
        self.ids = 0

    def do(self, **command: object) -> object:
        """Run one command in the parent and return its answer."""
        self.process.stdin.write(json.dumps(command) + '\n')
        self.process.stdin.flush()
        return json.loads(self.process.stdout.readline())

    def send(self, method: str, params: dict) -> dict:
        """Exchange one MCP message with this parent's host."""
        self.ids += 1
        return self.do(do='send', message={'jsonrpc': '2.0', 'id': self.ids, 'method': method, 'params': params})

    def start(self, **hold: str) -> int:
        """Start this parent's host; a held host is greeted later by ``greet``."""
        pid = self.do(do='start', **hold)
        if not hold:
            self.greet()
        return pid

    def greet(self) -> None:
        """Complete the MCP handshake."""
        assert self.send('initialize', {})['result']['serverInfo']['name'] == 'agents'

    def context(self, document: dict | None = None) -> dict:
        """Run the mod's context entry from this parent."""
        return self.do(do='context', document={'operation': 'end'} if document is None else document)

    def discover(self) -> dict:
        """Call agents as the mod and Claude Code do: prepare the context, then the MCP call."""
        request = {'action': 'discover'}
        prepared = self.context({'operation': 'prepare', 'tool': 'agents', 'session': str(uuid4()),
                                 'cwd': str(self.project.resolve()), 'agent': None, 'request': request})
        assert prepared['code'] == 0, prepared
        return self.send('tools/call', {'name': 'agents', 'arguments': request})['result']

    def close(self) -> None:
        """End the parent; its host ends with the closed input."""
        self.process.stdin.close()
        self.process.wait(timeout=60)
        self.process.stdout.close()


@pytest.fixture
def claude_parents():
    """Create parents standing in for Claude Code; every one is closed at the end."""
    started = []

    def parent(module: str, project: Path, config: Path) -> ClaudeParent:
        started.append(ClaudeParent(module, project, config))
        return started[-1]

    yield parent
    for running in started:
        if running.process.poll() is None:
            running.close()


def _channel_of(config: Path) -> Path:
    """Return the configured channel file."""
    return Path(json.loads(config.read_text())['channel_file'])


def _assert_real_discover(result: dict) -> None:
    """Require real discover output, not a refusal."""
    assert result['isError'] is False, result
    assert result['structuredContent']['features'], result


def _assert_one_line(answer: dict, line: str) -> None:
    """Require a refused context of exactly one line, quickly and without a traceback."""
    assert answer['code'] == 1 and answer['out'] == '', answer
    assert answer['err'].splitlines() == [line], answer
    assert answer['seconds'] < 5, answer


@pytest.mark.parametrize('module', HOST_MODULES)
def test_start_replaces_the_channel_of_a_killed_host(tmp_path: Path, claude_parents, module: str) -> None:
    """A host killed with its Claude leaves its file; the next normal start serves without any cleanup."""
    project, _, config = _host_project(tmp_path)
    channel = _channel_of(config)
    first = claude_parents(module, project, config)
    first.start()
    _assert_real_discover(first.discover())
    dead = json.loads(channel.read_text())
    first.do(do='kill')
    first.close()
    assert json.loads(channel.read_text()) == dead and Path(dead['address']).is_dir()

    second = claude_parents(module, project, config)
    second.start()
    _assert_real_discover(second.discover())
    current = json.loads(channel.read_text())
    assert current['parent'] == second.pid and current['address'] != dead['address']
    assert not Path(dead['address']).exists()
    log = (config.parent / 'host.log').read_text()
    assert log.count(REPLACED_LINE) == 1
    assert 'did not start' not in log and 'Traceback' not in log
    assert not (config.parent / 'host-refusal.json').exists()


@pytest.mark.parametrize('module', HOST_MODULES)
@pytest.mark.parametrize('case', ['dead-address', 'missing-address', 'outside-address', 'parent-address',
                                  'empty', 'malformed', 'missing-keys', 'not-an-object'])
def test_start_replaces_an_unusable_channel_file(tmp_path: Path, claude_parents, module: str, case: str) -> None:
    """Power loss can leave anything here; only a live host's lock blocks a start."""
    project, _, config = _host_project(tmp_path)
    channel = _channel_of(config)
    channel.parent.mkdir()
    dead, outside = channel.parent / 'control-dead', tmp_path / 'control-outside'
    dead.mkdir()
    outside.mkdir()
    channel.write_text({
        'dead-address': json.dumps({'parent': 1, 'executable': '/old/claude', 'address': str(dead)}),
        'missing-address': json.dumps({'parent': 1, 'executable': '/old/claude',
                                       'address': str(channel.parent / 'control-gone')}),
        'outside-address': json.dumps({'parent': 1, 'executable': '/old/claude', 'address': str(outside)}),
        'parent-address': json.dumps({'parent': 1, 'executable': '/old/claude',
                                      'address': str(channel.parent) + '/..'}),
        'empty': '', 'malformed': '{"parent": 1, "addr', 'missing-keys': '{"parent": 1}', 'not-an-object': '[1]',
    }[case])
    parent = claude_parents(module, project, config)
    parent.start()
    _assert_real_discover(parent.discover())
    assert json.loads(channel.read_text())['parent'] == parent.pid
    log = (config.parent / 'host.log').read_text()
    assert log.count(REPLACED_LINE) == 1 and 'did not start' not in log and 'Traceback' not in log
    # Only the control directory a dead host named beside the channel is removed.
    assert dead.exists() == (case != 'dead-address')
    assert outside.exists() and config.exists()


@pytest.mark.parametrize('module', HOST_MODULES)
def test_context_after_the_host_alone_was_killed(tmp_path: Path, claude_parents, module: str) -> None:
    """The same Claude survives its host: context says not running, without a version error or a 10 s wait."""
    project, _, config = _host_project(tmp_path)
    parent = claude_parents(module, project, config)
    parent.start()
    _assert_real_discover(parent.discover())
    parent.do(do='kill')
    assert json.loads(_channel_of(config).read_text())['parent'] == parent.pid
    _assert_one_line(parent.context(),
                     f"The agents host for this project is not running; see {config.parent / 'host.log'}.")


@pytest.mark.parametrize('module', HOST_MODULES)
def test_second_start_is_refused_while_the_occupant_lives(tmp_path: Path, claude_parents, module: str) -> None:
    """A live host keeps the project: the second start is refused, the first is untouched."""
    project, _, config = _host_project(tmp_path)
    channel = _channel_of(config)
    first = claude_parents(module, project, config)
    first.start()
    occupied = channel.read_text()
    second = claude_parents(module, project, config)
    # Before its own host starts, the second Claude is told who owns the project.
    _assert_one_line(second.context(), f'The agents host of another Claude Code session '
                                       f'(Claude Code pid {first.pid}) owns this project.')
    second.start()
    refused = second.send('tools/call', {'name': 'agents', 'arguments': {'action': 'discover'}})['result']
    assert refused['isError'] is True
    error = refused['structuredContent']['error']
    assert error['code'] == 'host-busy' and f'Claude Code pid {first.pid}' in error['message'], error
    assert 'delete' not in error['message']
    # Its context reports the refusal, not a CLI version mismatch.
    _assert_one_line(second.context(), f"host-busy: {error['message']}")
    assert channel.read_text() == occupied
    assert sorted(path.name for path in channel.parent.iterdir()) == sorted(
        ['channel.json', Path(json.loads(occupied)['address']).name])
    _assert_real_discover(first.discover())
    second.close()
    assert channel.read_text() == occupied
    _assert_real_discover(first.discover())


@pytest.mark.parametrize('module', HOST_MODULES)
def test_concurrent_starts_over_a_stale_channel_serve_once(tmp_path: Path, claude_parents, module: str) -> None:
    """Both hosts pass the early check on a stale file; one serves, the other gets the normal refusal."""
    project, _, config = _host_project(tmp_path)
    channel = _channel_of(config)
    channel.parent.mkdir()
    channel.write_text('{"parent": 1}')
    go = tmp_path / 'go'
    parents = [claude_parents(module, project, config) for _ in range(2)]
    for parent in parents:
        parent.start(hold=str(go))
    # Both must have passed the early check before either may claim.
    deadline = time.monotonic() + 60
    while (len(list(tmp_path.glob('passed-*'))) < 2) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(list(tmp_path.glob('passed-*'))) == 2
    go.touch()
    for parent in parents:
        parent.greet()
    owner = json.loads(channel.read_text())
    winner, loser = parents if owner['parent'] == parents[0].pid else parents[::-1]
    assert owner['parent'] == winner.pid
    _assert_real_discover(winner.discover())
    refused = loser.send('tools/call', {'name': 'agents', 'arguments': {'action': 'discover'}})['result']
    error = refused['structuredContent']['error']
    assert refused['isError'] is True and error['code'] == 'host-busy', refused
    assert f'Claude Code pid {winner.pid}' in error['message']
    assert sorted(path.name for path in channel.parent.iterdir()) == sorted(
        ['channel.json', Path(owner['address']).name])
    log = (config.parent / 'host.log').read_text()
    assert log.count(REPLACED_LINE) == 1 and 'Traceback' not in log
    assert log.count('The agents host did not start') == 1
    _assert_one_line(loser.context(), f"host-busy: {error['message']}")
    assert json.loads(channel.read_text()) == owner


@pytest.mark.parametrize('module', HOST_MODULES)
@pytest.mark.parametrize('recorded', [False, True])
@pytest.mark.parametrize('own', [False, True])
def test_context_over_a_stale_file_names_the_real_cause(
        tmp_path: Path, claude_parents, module: str, recorded: bool, own: bool) -> None:
    """The incident: a stale file names an older CLI; the report is the refusal or the missing host."""
    project, _, config = _host_project(tmp_path)
    channel = _channel_of(config)
    channel.parent.mkdir()
    parent = claude_parents(module, project, config)
    channel.write_text(json.dumps({'parent': parent.pid if own else 1, 'executable': str(tmp_path / '2.1.312'),
                                   'address': str(channel.parent / 'control-dead')}))
    if recorded:
        (config.parent / 'host-refusal.json').write_text(json.dumps(
            {'code': 'host-unavailable', 'message': 'The agents host did not start: recorded'}))
    _assert_one_line(parent.context(), 'host-unavailable: The agents host did not start: recorded' if recorded
                     else f"The agents host for this project is not running; see {config.parent / 'host.log'}.")


@pytest.mark.parametrize('module', HOST_MODULES)
def test_context_from_another_claude_forwards_nothing(
        tmp_path: Path, claude_parents, hold_control, module: str) -> None:
    """Another Claude's live host is named and never reached."""
    project, _, config = _host_project(tmp_path)
    channel = _channel_of(config)
    control = hold_control(channel.parent / 'control-held')
    parent = claude_parents(module, project, config)
    channel.write_text(json.dumps({'parent': 4242, 'executable': sys.executable, 'address': str(control)}))
    _assert_one_line(parent.context(),
                     'The agents host of another Claude Code session (Claude Code pid 4242) owns this project.')
    assert list(control.iterdir()) == []


@pytest.mark.parametrize('module', HOST_MODULES)
def test_context_from_the_wrong_executable_is_still_denied(
        tmp_path: Path, claude_parents, hold_control, module: str) -> None:
    """The owner's pid running another executable gets authority-denied and reaches nothing."""
    project, _, config = _host_project(tmp_path)
    channel = _channel_of(config)
    control = hold_control(channel.parent / 'control-held')
    parent = claude_parents(module, project, config)
    channel.write_text(json.dumps({'parent': parent.pid, 'executable': str(tmp_path / 'other-cli'),
                                   'address': str(control)}))
    denied = parent.context()
    assert denied['code'] != 0 and denied['out'] == ''
    assert 'authority-denied' in denied['err'] and 'must be launched directly' in denied['err'], denied
    assert 'other-cli' in denied['err'] and denied['seconds'] < 5
    assert list(control.iterdir()) == []


def test_host_alive_reads_only_the_kernel_lock(tmp_path: Path, hold_control) -> None:
    """Gone means dead, a free lock means dead, and what cannot be observed counts as alive."""
    from agent_swarm.connection import host_alive

    assert host_alive(str(tmp_path / 'gone')) is False
    (tmp_path / 'file').touch()
    assert host_alive(str(tmp_path / 'file')) is False
    (tmp_path / 'free').mkdir()
    assert host_alive(str(tmp_path / 'free')) is False
    held = hold_control(tmp_path / 'held')
    assert host_alive(str(held)) is True
    (tmp_path / 'closed').mkdir(mode=0)
    try:
        assert host_alive(str(tmp_path / 'closed')) is True
    finally:
        (tmp_path / 'closed').chmod(0o700)


def test_killed_owner_lock_is_not_kept_by_its_children(tmp_path: Path) -> None:
    """A host's descendants outlive it (Agents, validations) but cannot keep it looking alive."""
    from agent_swarm.connection import host_alive

    address = tmp_path / 'control-owner'
    address.mkdir()
    program = ('import fcntl, os, subprocess, sys, time\n'
               'lock = os.open(sys.argv[1], os.O_RDONLY | os.O_DIRECTORY)\n'
               'fcntl.flock(lock, fcntl.LOCK_EX)\n'
               'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], close_fds=False)\n'
               'print(child.pid, flush=True)\n'
               'time.sleep(60)\n')
    owner = subprocess.Popen([sys.executable, '-c', program, str(address)], stdout=subprocess.PIPE, text=True)
    child = int(owner.stdout.readline())
    try:
        assert host_alive(str(address)) is True
        owner.send_signal(signal.SIGKILL)
        owner.wait(timeout=30)
        os.kill(child, 0)  # The child still runs.
        assert host_alive(str(address)) is False
    finally:
        owner.kill()
        owner.wait(timeout=30)
        owner.stdout.close()
        os.kill(child, signal.SIGKILL)
