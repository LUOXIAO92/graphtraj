"""The native Pi root binding uses existing origin checks and the shared core."""
import io
import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from agent_swarm import AgentControl
from graphtraj.runtimes.pi.host import bind_native_main
from test_agent_control import ScriptedDriver


def native_connection(tmp_path: Path, session: str = 'native-main') -> dict:
    """Write only the selected controlled native Session, without Task metadata."""
    path = tmp_path / (session + '.jsonl')
    path.write_text(json.dumps({'type': 'session', 'version': 3, 'id': session,
                                'cwd': str(tmp_path)}) + '\n')
    return {'runtime': 'pi', 'session': session, 'session_file': str(path)}


def test_native_binding_uses_native_scope_and_common_mcp(tmp_path: Path) -> None:
    """Same native root resumes its scope; a different native root cannot see it."""
    core = AgentControl(tmp_path / 'data', {'controlled': ScriptedDriver()})
    connection = native_connection(tmp_path)
    call = bind_native_main(core, connection, tmp_path)
    created = call({'action': 'create', 'runtime': 'controlled', 'instruction': 'controlled input'})
    assert not created.failed, created.document
    agent = created.document['agent']
    try:
        restored = bind_native_main(core, connection, tmp_path)
        assert not restored({'action': 'status', 'agent': agent}).failed
        other = bind_native_main(core, native_connection(tmp_path, 'other-native'), tmp_path)
        assert other({'action': 'status', 'agent': agent}).failed
        assert not (tmp_path / '.graphtraj').exists()
    finally:
        call({'action': 'interrupt', 'agent': agent})
        call({'action': 'wait', 'agent': agent, 'timeout_seconds': 5})


@pytest.mark.parametrize('case', ['child', 'stale', 'cwd', 'forged-header', 'plugin-child', 'unknown-depth'])
def test_native_binding_rejects_wrong_source(
    tmp_path: Path, case: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Request-supplied headers cannot override the actual selected native file."""
    connection = native_connection(tmp_path)
    if case == 'plugin-child':
        monkeypatch.setenv('PI_SUBAGENT_CHILD', '1')
    if case == 'unknown-depth':
        monkeypatch.setenv('PI_SUBAGENT_DEPTH', 'unknown')
    if case == 'stale':
        connection['session'] = 'different'
    if case in {'child', 'forged-header'}:
        path = Path(connection['session_file'])
        header = json.loads(path.read_text())
        header['parentSessionId'] = 'parent'
        path.write_text(json.dumps(header) + '\n')
        if case == 'forged-header':
            connection['native_header'] = {**header, 'parentSessionId': None}
    with pytest.raises(ValueError):
        bind_native_main(AgentControl(tmp_path / 'data', {}), connection,
                         tmp_path / 'elsewhere' if case == 'cwd' else tmp_path)


def test_native_host_command_stops_owned_execution_on_pipe_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public host command preserves Session state and confirms stop at EOF."""
    from graphtraj.runtimes.pi import host

    connection = native_connection(tmp_path)
    driver = ScriptedDriver()
    config = tmp_path / 'host.json'
    config.write_text(json.dumps({'root': str(tmp_path / 'data'), 'adapter_request': {
        'worktree_path': str(tmp_path), 'provider': 'controlled', 'model': 'controlled-model',
        'executable': '/controlled/pi'}}))
    monkeypatch.chdir(tmp_path)
    for name in ('AGENT_SWARM_CONNECTION', 'GRAPHTRAJ_CLI_CONNECTION', 'PI_SUBAGENT_CHILD', 'PI_SUBAGENT_DEPTH'):
        monkeypatch.delenv(name, raising=False)
    for name, value in {'GRAPHTRAJ_NATIVE_RUNTIME': 'pi', 'GRAPHTRAJ_NATIVE_SESSION': connection['session'],
                        'GRAPHTRAJ_NATIVE_SESSION_FILE': connection['session_file'],
                        'AGENT_SWARM_PI_MODEL': 'controlled-model', 'AGENT_SWARM_PI_PROVIDER': 'controlled'}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(host, 'PiDriver', lambda request: driver)
    monkeypatch.setattr(host, 'verify_native_parent', lambda executable: None)
    monkeypatch.setattr('sys.argv', ['pi-host', '--config', str(config)])
    created = []
    original = host.agents_connection

    @contextmanager
    def connected(directory, call, authenticate):
        """Start controlled work at the public connection seam before lifecycle EOF."""
        created.append(call({'action': 'create', 'runtime': 'pi', 'instruction': 'controlled'}).document)
        with original(directory, call, authenticate) as address:
            yield address

    monkeypatch.setattr(host, 'agents_connection', connected)
    event = {'header': json.loads(Path(connection['session_file']).read_text()), 'entries': []}
    monkeypatch.setattr('sys.stdin', io.StringIO(json.dumps(event) + '\n'))
    output = io.StringIO()
    monkeypatch.setattr('sys.stdout', output)
    host.main()
    assert json.loads(output.getvalue())['connection']
    result = created[0]
    assert result['agent']
    call = bind_native_main(AgentControl(tmp_path / 'data', {'pi': driver}), connection, tmp_path)
    status = call({'action': 'status', 'agent': result['agent']})
    assert status.document['result']['state'] == 'standby'
    assert status.document['session'] == result['session']
    assert driver.max_active == 1


@pytest.mark.parametrize('case', ['native', 'native-title', 'copied-env', 'wrong-script'])
def test_native_parent_requires_process_evidence(case: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Native Session environment does not authorize a shell or another Node program."""
    from graphtraj.runtimes.pi.host import verify_native_parent

    monkeypatch.setenv('AGENT_SWARM_PI_NODE', '/selected/node')
    monkeypatch.setenv('AGENT_SWARM_PI_ENTRY', '/selected/pi')
    actual = Path('/bin/sh' if case == 'copied-env' else '/selected/node')
    script = '/unrelated/app.js' if case == 'wrong-script' else '/selected/pi'
    monkeypatch.setattr('graphtraj.execution.runner_process.process_executable', lambda pid: actual)
    monkeypatch.setattr('graphtraj.execution.runner_process._process_arguments',
                        lambda pid: ['pi'] if case == 'native-title' else [str(actual), script])
    if case in {'native', 'native-title'}:
        verify_native_parent(Path('/selected/pi'))
    else:
        with pytest.raises(ValueError, match='not owned'):
            verify_native_parent(Path('/selected/pi'))


def test_new_native_session_uses_trusted_sdk_header_before_persistence(tmp_path: Path) -> None:
    """The actual lifecycle callback binds a new Session without manufacturing its file."""
    connection = {'runtime': 'pi', 'session': 'new-native', 'session_file': str(tmp_path / 'not-yet.jsonl')}
    event = {'header': {'type': 'session', 'version': 3, 'id': 'new-native', 'cwd': str(tmp_path)}, 'entries': []}
    call = bind_native_main(AgentControl(tmp_path / 'data', {}), connection, tmp_path, event)
    assert not call({'action': 'status'}).failed
    assert not Path(connection['session_file']).exists()
    event['header']['parentSessionId'] = 'real-parent'
    with pytest.raises(ValueError):
        bind_native_main(AgentControl(tmp_path / 'data', {}), connection, tmp_path, event)
