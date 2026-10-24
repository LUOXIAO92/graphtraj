"""Child-role saves require the direct native MCP client's actual review."""

from collections import deque
from contextlib import nullcontext
from io import TextIOBase
import json
from pathlib import Path

import pytest
import yaml

from graphtraj.execution.runner_status import runtime_caller
from graphtraj.interfaces import mcp
from test_role_organization import project, roles_path


@pytest.mark.parametrize('decision', [
    'accept', 'decline', 'cancel', 'unmarked', 'wrong-id', 'error', 'disconnect',
    'stale', 'member', 'preview',
])
def test_role_save_uses_strict_native_review(
    project: Path, monkeypatch: pytest.MonkeyPatch, decision: str,
) -> None:
    """Only a matched native acceptance saves the unchanged reviewed role document."""
    monkeypatch.chdir(project)
    monkeypatch.delenv('GRAPHTRAJ_CLI_CONNECTION', raising=False)
    monkeypatch.delenv('AGENT_SWARM_CONNECTION', raising=False)
    monkeypatch.setattr(mcp, '_caller_notices', lambda params: nullcontext(None))
    path = roles_path(project)
    before = path.read_bytes()
    sockets = {str(project): ['/tmp/approved.sock', '/tmp/approved-target.sock']}
    arguments = {} if decision == 'preview' else {'change': {'set_presets': {
        'coding_team.engineer': {'codex': {'unix_sockets': sockets}},
    }}}

    class ClientInput(TextIOBase):
        """Return the call first and the later response after observing its proposal."""
        def __init__(self) -> None:
            self.messages = deque(json.dumps(message) + '\n' for message in [
                {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                 'params': {'capabilities': {'elicitation': {'form': {}}}}},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {
                    'name': 'tasks', '_meta': {'threadId': 'controlled-main'},
                    'arguments': {'action': 'execute', 'feature': 'role_organization',
                                  'arguments': arguments}}},
            ])

        def readline(self, size: int = -1) -> str:
            """Return one complete native transport frame."""
            return self.messages.popleft() if self.messages else ''

    source = ClientInput()
    observed = []

    class ClientOutput(TextIOBase):
        """Supply a controlled native decision without changing the saved settings."""
        def write(self, text: str) -> int:
            message = json.loads(text)
            observed.append(message)
            if message.get('method') == 'elicitation/create':
                assert decision not in {'member', 'preview'}
                assert path.read_bytes() == before
                params = message['params']
                assert params['_meta']['codex_strict_auto_review'] is True
                assert params['_meta']['codex_sensitive_action'] is True
                assert params['_meta']['tool_params'] == {
                    'action': 'execute', 'feature': 'role_organization', 'arguments': arguments,
                }
                summary = json.loads(params['message'].split('\n', 1)[1])
                assert summary['changes'] == [{
                    'field': 'roles.coding_team.engineer.codex', 'expected': None,
                    'actual': {'unix_sockets': sockets},
                }]
                reply = {'jsonrpc': '2.0', 'id': message['id'], 'result': {
                    'action': decision if decision in {'decline', 'cancel'} else 'accept',
                    'content': {}, '_meta': {'approvals_reviewer': 'auto_review'},
                }}
                if decision == 'unmarked':
                    reply['result'].pop('_meta')
                elif decision == 'wrong-id':
                    reply['id'] = 'another-request'
                elif decision == 'error':
                    reply = {'id': message['id'], 'error': {'code': -32603}}
                elif decision == 'stale':
                    path.write_bytes(before + b'\n')
                if decision != 'disconnect':
                    source.messages.append(json.dumps(reply) + '\n')
            return len(text)

        def flush(self) -> None:
            """The controlled input sees the review immediately."""

    with runtime_caller(project / '.graphtraj/runner', 'member' if decision == 'member' else None):
        mcp.serve(source, ClientOutput())
    result = observed[-1]['result']
    if decision == 'accept':
        assert not result['isError'], result
        saved = yaml.safe_load(path.read_text())
        original = yaml.safe_load(before)
        original['roles']['coding_team']['engineer']['codex'] = {'unix_sockets': sockets}
        assert saved == original
    elif decision == 'stale':
        assert result['structuredContent']['status'] == 'stale'
        assert path.read_bytes() == before + b'\n'
    else:
        assert result['isError'] is (decision != 'preview'), result
        assert path.read_bytes() == before
