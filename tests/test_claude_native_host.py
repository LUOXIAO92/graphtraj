"""Current-context binding boundaries without launching a real Runtime."""
from io import StringIO
import json
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
