"""Task-free DSH and Pi children get GraphTraj's ``tasks`` entry beside ``agents`` (551).

The binding is checked at GraphTraj's seam: the tools reach the child's own
authenticated channel (graftling's ``agents_connection``) bound to the child's
own Agent ID. No model or real Runtime starts.
"""
from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

import graftling.dsh.binding as binding
from graftling import AgentsResult
from graphtraj.execution.agent_driver import AdapterDriver
from graphtraj.runtimes.dsh.driver import bind_agents


class Events:
    def receive_children(self, receive) -> None:
        pass


def test_dsh_child_channel_serves_tasks_bound_to_the_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """bind_agents gives the DSH child's channel GraphTraj's tasks tool, served as that child."""
    calls: list[dict] = []

    def record(*args, **options):
        calls.append(options)
        return nullcontext('/fake/address')

    monkeypatch.setattr(binding, 'agents_connection', record)
    served: list[tuple] = []
    monkeypatch.setattr('graphtraj.interfaces.task_free.serve_task_free',
                        lambda root, agent, request: served.append((root, agent, request)) or AgentsResult({'ok': True}))
    turn = SimpleNamespace(request={}, native_header=None, service=None)
    run = SimpleNamespace(call=lambda request: AgentsResult({}), settings={}, agent='agent-551child', events=Events(),
                          archive=None, session=None, extra_fields=None)
    bind_agents(turn, run, AdapterDriver(tmp_path, tmp_path))
    with turn.host_connection(tmp_path) as address:
        assert address == '/fake/address'
    (descriptor, callback), = calls[0]['extra_tools']
    assert descriptor['name'] == 'tasks'
    assert callback({'action': 'discover'}).document == {'ok': True}
    assert served == [(tmp_path, 'agent-551child', {'action': 'discover'})]
    # The child's agents entry is unchanged: graftling's own MCP server on the same channel.
    assert turn.request['mcp']['args'] == ['-I', '-m', 'graftling.mcp']
