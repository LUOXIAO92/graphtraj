"""Task-free Codex wiring through a controlled stdio peer, not real-host evidence."""

import asyncio
import json
from pathlib import Path

import pytest
import yaml

from agent_swarm import Caller
from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.interfaces.agents import agents_callback
from graphtraj.runtimes.codex.app_server import CodexAppServer, CodexServerRequest
from graphtraj.runtimes.codex.managed_session import run_native_operation
from test_codex_app_server import peer  # noqa: F401


def test_independent_codex_lifecycle_and_callback_cwd(
    tmp_path: Path, peer: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create, steer, stop and resume without a Task mapping or Worker environment."""
    from graphtraj.workspace import runner_project

    root = tmp_path / 'project'
    cwd = root / 'scratch'
    cwd.mkdir(parents=True)
    (root / '.graphtraj').mkdir()
    (root / '.graphtraj/config.yml').write_text(default_configuration_content(root, root))
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'codex': {'runtime': 'codex', 'model': 'fixture-model'}},
        'role_tree': {'codex': {}},
    }))
    monkeypatch.setattr(runner_project, 'runtime_executable', lambda runtime: peer)
    protocol = tmp_path / 'protocol.jsonl'
    monkeypatch.setenv('PEER_PROTOCOL_LOG', str(protocol))
    monkeypatch.setenv('PEER_NATIVE_ROLLOUT', str(tmp_path / 'native'))

    async def create() -> dict:
        """Use the actual dynamic callback with a separate host working directory."""
        async with CodexAppServer(command=[str(peer)], cwd=cwd) as adapter:
            response = await run_native_operation(
                adapter, 'owner', 'agent-owner', root,
                CodexServerRequest(1, 'item/tool/call', {
                    'threadId': 'owner', 'tool': 'agents',
                    'arguments': {'action': 'create', 'runtime': 'codex', 'instruction': 'hold'},
                }), cwd=cwd,
            )
            assert response['success'], response
            return json.loads(response['contentItems'][0]['text'])

    created = asyncio.run(create())
    call = agents_callback(root, Caller('codex-dynamic-tools', 'agent-owner'), cwd)
    agent, session = created['agent'], created['session']
    assert session and created['result']['state'] == 'active'

    sent = call({'action': 'send', 'agent': agent, 'message': 'finished'})
    assert not sent.failed, sent.document
    done = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 10})
    assert done.document['result']['last_result']['last_message'] == 'finished'

    resumed = call({'action': 'resume', 'agent': agent, 'message': 'hold'})
    assert not resumed.failed and resumed.document['session'] == session, resumed.document
    assert resumed.document['execution'] != created['execution']
    stopped = call({'action': 'interrupt', 'agent': agent})
    assert not stopped.failed, stopped.document
    done = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 10})
    assert done.document['result']['last_result']['outcome'] == 'interrupted'
    assert done.document['result']['state'] == 'standby'
    status = call({'action': 'status'})
    assert not status.failed, status.document
    assert [item['agent'] for item in status.document['result']['agents']] == [agent]

    wire = [json.loads(line) for line in protocol.read_text().splitlines()]
    sessions = [item for item in wire if item.get('method') in {'thread/start', 'thread/resume'}]
    assert [item['method'] for item in sessions] == ['thread/start', 'thread/resume']
    assert all(item['params']['cwd'] == str(cwd) for item in sessions)
    assert sessions[1]['params']['threadId'] == session
    assert not (root / '.graphtraj/state/tasks').exists()

    approved = call({'action': 'resume', 'agent': agent,
                     'message': 'request:item/commandExecution/requestApproval'})
    assert not approved.failed, approved.document
    waiting = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 10})
    assert waiting.document['result']['pending_requests'] == 1
    pending = call({'action': 'requests', 'agent': agent})
    [request] = pending.document['result']['requests']
    replied = call({'action': 'reply', 'agent': agent, 'request': request,
                    'response': {'decision': 'accept'}})
    assert not replied.failed, replied.document
    done = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 10})
    assert done.document['result']['last_result']['last_message'] == 'request accepted'
    assert done.document['result']['state'] == 'standby'
