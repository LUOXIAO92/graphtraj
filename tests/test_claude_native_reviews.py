"""A verified Claude Main's reviewed changes are decided by Claude Code's own dialog."""

from collections import deque
from io import TextIOBase
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from agent_swarm import AgentsResult

from graphtraj.execution import approved_recovery, runner_retirement, runner_status
from graphtraj.execution.runner_status import runtime_caller
from graphtraj.interfaces.gateway import handle_request as handle_task
from graphtraj.runtimes.claude.mcp import serve
from test_native_replacement import _record_direct_session
from test_role_organization import project, roles_path


def converse(
    root: Path, request: dict, decision: str, check: callable, tool: str = 'tasks',
) -> tuple[list[dict], dict]:
    """Serve one Claude ``tool`` call as Main and answer its dialog with ``decision``.

    Returns the elicitations observed and the call's structured result.
    ``check(params)`` runs while the dialog is open, before any answer.
    """
    class ClientInput(TextIOBase):
        """Send the call; the dialog answer follows the observed elicitation."""
        def __init__(self) -> None:
            self.messages = deque(json.dumps(message) + '\n' for message in [
                {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                 'params': {'capabilities': {'elicitation': {}}}},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                 'params': {'name': tool, 'arguments': request}},
            ])

        def readline(self, size: int = -1) -> str:
            """Return one complete transport frame."""
            return self.messages.popleft() if self.messages else ''

    source   = ClientInput()
    observed = []

    class ClientOutput(TextIOBase):
        """Answer the elicitation as Claude Code's dialog would."""
        def write(self, text: str) -> int:
            message = json.loads(text)
            observed.append(message)
            if message.get('method') == 'elicitation/create':
                check(message['params'])
                if decision == 'cancel':
                    reply = {'jsonrpc': '2.0', 'method': 'notifications/cancelled',
                             'params': {'requestId': 2}}
                else:
                    reply = {'jsonrpc': '2.0', 'id': message['id'],
                             'result': {'action': decision, 'content': {}}}
                source.messages.append(json.dumps(reply) + '\n')
            return len(text)

    def native_call(arguments: dict, tool: str = 'agents') -> object:
        """Run the call as the verified Main host does: Runner caller ``None``."""
        with runtime_caller(root / '.graphtraj/runner', None):
            if tool == 'agents':
                # A Task member's agents retire uses the Runner retirement.
                return AgentsResult(runner_retirement.retire_session(arguments['arguments']['agent'], root))
            return handle_task(arguments, cwd=root)

    serve(source, ClientOutput(), root, native_call=native_call)
    elicitations = [message for message in observed if message.get('method') == 'elicitation/create']
    result       = next(message for message in observed if message.get('id') == 2)['result']
    return elicitations, result


@pytest.mark.parametrize('decision', ['accept', 'decline', 'cancel'])
def test_claude_main_role_organization_uses_claude_dialog(
    project: Path, monkeypatch: pytest.MonkeyPatch, decision: str,
) -> None:
    """Only Claude Code's accept saves the reviewed role change."""
    monkeypatch.chdir(project)
    path   = roles_path(project)
    before = path.read_bytes()
    change = {'set_presets': {'coding_team.engineer': {'codex': {'unix_sockets': {str(project): ['/tmp/a.sock']}}}}}

    def check(params: dict) -> None:
        """The dialog names the role change while nothing is written."""
        assert path.read_bytes() == before
        assert 'roles.coding_team.engineer.codex' in params['message'].rsplit('\n', 1)[0]

    elicitations, result = converse(
        project, {'action': 'execute', 'feature': 'role_organization', 'arguments': {'change': change}},
        decision, check)
    assert len(elicitations) == 1
    assert result['isError'] is (decision != 'accept'), result
    if decision == 'accept':
        assert yaml.safe_load(path.read_text())['roles']['coding_team']['engineer']['codex'] == {
            'unix_sockets': {str(project): ['/tmp/a.sock']}}
    else:
        assert path.read_bytes() == before


@pytest.mark.parametrize('decision', ['accept', 'decline', 'cancel'])
def test_claude_main_connection_save_uses_claude_dialog(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, decision: str,
) -> None:
    """Only Claude Code's accept saves the reviewed user connection catalog."""
    from graphtraj.configuration import runtime_connections

    path = tmp_path / 'connections.yml'
    monkeypatch.setattr(runtime_connections, 'connections_file', lambda: path)
    revision = runtime_connections.read_catalog()[1]
    catalog  = {'version': 1, 'runtimes': {'configured': {'runtime': 'claude',
                'providers': {'anthropic': {'models': {'chosen': {'id': 'claude-opus-5-5',
                    'source': 'manual', 'supported_efforts': ['high']}}}}}}}

    def check(params: dict) -> None:
        """The dialog shows the catalog change while nothing is written."""
        assert not path.exists()
        assert str(path) in params['message'].rsplit('\n', 1)[0]
        summary = json.loads(params['message'].rsplit('\n', 1)[1])
        assert summary['request'] == {'scope': 'user', 'path': str(path)}
        assert summary['changes']

    elicitations, result = converse(
        project, {'action': 'execute', 'feature': 'runtime_connections', 'arguments': {
            'action': 'save', 'expected_revision': revision, 'catalog': catalog}},
        decision, check)
    assert len(elicitations) == 1
    assert result['isError'] is (decision != 'accept'), result
    assert path.exists() is (decision == 'accept')


@pytest.mark.parametrize('decision', ['accept', 'decline', 'cancel'])
def test_claude_main_retirement_review_uses_claude_dialog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, decision: str,
) -> None:
    """A retirement needing review applies only after Claude Code's accept."""
    runner = tmp_path / 'runner'
    parent = '359-task-handover0-team_leader@leader'
    child  = '359-task-handover0-engineer@child'
    for alias, role, owner in ((parent, 'team-leader', None), (child, 'engineer', parent)):
        _record_direct_session(runner, alias, role, owner)
        (runner / 'sessions' / alias / 'session.yml').write_text('{}\n')
        (runner / 'sessions' / alias / 'execution.yml').write_text('outcome: completed\n')
    retained = {path: path.read_bytes() for path in runner.rglob('*') if path.is_file()}
    # The caller is not the direct owner, so this retirement needs review.
    monkeypatch.setattr(runner_retirement, 'discover_project',
                        lambda *a, **k: SimpleNamespace(runner_directory=runner))
    monkeypatch.setattr(runner_retirement, 'caller_alias', lambda directory: child)
    monkeypatch.setattr(approved_recovery, 'caller_alias', lambda directory: child)
    monkeypatch.setattr(runner_status, 'session_operation', lambda *a: {'activity': 'idle'})
    retired = []
    monkeypatch.setattr(runner_retirement, '_retire_session',
                        lambda alias, cwd: retired.append(alias) or {'alias': alias, 'retired': True})

    def check(params: dict) -> None:
        """The dialog names the retirement before anything is applied."""
        assert not retired
        assert parent in params['message'].rsplit('\n', 1)[0]
        summary = json.loads(params['message'].rsplit('\n', 1)[1])
        assert summary['request'] == {'operation': 'retire', 'alias': parent}

    elicitations, result = converse(
        tmp_path, {'action': 'execute', 'feature': 'retire', 'arguments': {'agent': parent}},
        decision, check, tool='agents')
    assert len(elicitations) == 1
    assert result['isError'] is (decision != 'accept'), result
    assert retired == ([parent] if decision == 'accept' else [])
    if decision != 'accept':
        assert result['structuredContent']['error']['code'] in {'retirement-denied', 'recovery-denied'}
    assert {path: path.read_bytes() for path in runner.rglob('*') if path.is_file()} == retained
