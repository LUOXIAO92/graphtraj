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
        def call(request: dict) -> AgentsResult:
            invocations.append((session, cwd, request))
            return AgentsResult({'native': session})
        return call

    host = NativeCalls(bind, tmp_path)
    request = {'action': 'execute', 'feature': 'status', 'arguments': {}}
    with pytest.raises(AgentsError, match='No matching'):
        host.call(request)
    first, second = str(uuid4()), str(uuid4())
    context = {'operation': 'prepare', 'session': first, 'cwd': str(tmp_path),
               'agent': None, 'request': request}
    host.context(context)
    assert host.call(request).document == {'native': first}
    with pytest.raises(AgentsError, match='No matching'):
        host.call(request)
    host.context({**context, 'session': second})
    assert host.call(request).document == {'native': second}
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
    assert len(invocations) == 2

    output = StringIO()
    serve(StringIO(json.dumps({'id': 1, 'method': 'tools/list'}) + '\n'), output,
          tmp_path, native_call=host.call)
    tools = json.loads(output.getvalue())['result']['tools']
    assert [tool['name'] for tool in tools] == ['agents']
    assert tools[0]['inputSchema']['properties']['action']['enum'] == ['discover', 'describe', 'execute']
    assert 'runtime' not in tools[0]['inputSchema']['properties']


def test_native_host_does_not_trust_session_environment(tmp_path: Path, monkeypatch) -> None:
    """A shell-launched client with invented native env is not a Claude parent."""
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', str(uuid4()))
    with pytest.raises(AgentsError, match='directly'):
        native_parent(tmp_path / 'not-claude')
