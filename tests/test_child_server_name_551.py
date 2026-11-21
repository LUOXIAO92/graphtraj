"""GraphTraj's agents children reach agents and tasks as mcp__graphtraj__* like members (551).

A real Claude child skipped ``mcp__graftling__tasks`` as not GraphTraj's. Every
Runtime's child now registers its owner's entry under ``graphtraj``, with the
members' tool descriptions, and never shares that name with a host server.
"""
from __future__ import annotations

from contextlib import ExitStack
import json
import queue
from pathlib import Path

import pytest

from graftling import AgentsResult
from graphtraj.interfaces.task_free import task_free_tools
from test_claude_runtime import claude_environment, execution  # noqa: F401 - pytest fixture
from test_result_submission import result_project

CHILD = 'agent-' + '0' * 32


def test_every_runtime_names_its_children_server_graphtraj() -> None:
    """Claude, Codex, Pi and DSH children use the members' server name."""
    from graphtraj.runtimes.claude.execution import ClaudeExecution
    from graphtraj.runtimes.codex.managed_session import CodexManagedExecution
    from graphtraj.runtimes.dsh.execution import DshExecution
    from graphtraj.runtimes.pi.managed_session import PiManagedExecution

    for owner in (ClaudeExecution, CodexManagedExecution, DshExecution, PiManagedExecution):
        assert owner.mcp_server == 'graphtraj', owner


def test_child_tool_descriptions_match_the_members_entry(tmp_path: Path) -> None:
    """agents and tasks carry exactly the descriptions and schemas a member's entry lists."""
    from graftling.mcp import tool_documents
    from graphtraj.runtimes.claude.mcp import descriptors

    [(tasks, _)] = task_free_tools(tmp_path, CHILD)
    assert tool_documents() + [tasks] == descriptors()


def test_pi_child_environment_names_graphtraj() -> None:
    """The Pi child's extension is told to register graphtraj."""
    from types import SimpleNamespace

    from graftling.pi import PiExecution
    from graphtraj.runtimes.pi.managed_session import PiManagedExecution

    # An independent PiManagedExecution returns graftling's environment (super()).
    child = SimpleNamespace(mcp_server=PiManagedExecution.mcp_server, extra_tools={})
    environment = PiExecution.connection_environment(child, 'addr')
    assert environment['GRAFTLING_MCP_SERVER'] == 'graphtraj'


def test_claude_child_serves_mcp_graphtraj_tools_and_loads_no_other_server(
    tmp_path: Path, claude_environment: None,
) -> None:
    """The child's in-process server is graphtraj; strict MCP config loads no host entry of that name."""
    result_project(tmp_path)
    with ExitStack() as stack:
        turn, _, _ = execution(tmp_path, stack, 'unused')
        turn.configure_independent(archive=None, agents_callback=lambda request: AgentsResult({}),
                                   extra_tools=task_free_tools(tmp_path, CHILD))
        assert turn.agents_tool == 'mcp__graphtraj__agents'
        argv, _ = turn._prepare(str(tmp_path / 'connection.sock'))
        assert '--strict-mcp-config' in argv
        assert json.loads(argv[argv.index('--mcp-config') + 1]) == {'mcpServers': {}}
        replies: queue.Queue = queue.Queue()
        turn._reply = lambda identity, response: replies.put(response)
        turn._sdk_message({'request_id': '1', 'request': {'server_name': 'graphtraj', 'message': {
            'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}}})
        listed = replies.get(timeout=5)['mcp_response']['result']['tools']
        assert [tool['name'] for tool in listed] == ['agents', 'tasks']
        with pytest.raises(Exception):
            turn._sdk_message({'request_id': '2', 'request': {'server_name': 'graftling', 'message': {
                'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}}})


@pytest.mark.parametrize('denied', [None, 'tasks', 'mcp__graphtraj__tasks'])
def test_claude_child_calls_tasks_without_asking_unless_disallowed(
    tmp_path: Path, claude_environment: None, denied: str | None,
) -> None:
    """mcp__graphtraj__tasks is allowed with no parent request (551); WebSearch still asks; a disallow removes it."""
    result_project(tmp_path)
    with ExitStack() as stack:
        turn, _, _ = execution(tmp_path, stack, 'unused')
        if denied is not None:
            turn.request['disallowed_tools'] = [denied]
        turn.configure_independent(archive=None, agents_callback=lambda request: AgentsResult({}),
                                   extra_tools=task_free_tools(tmp_path, CHILD))
        turn.session = 'session'
        replies: queue.Queue = queue.Queue()
        turn._reply = lambda identity, response: replies.put((identity, response))
        turn.parent_notice = lambda message, details: {'delivery': 'retained'}
        for identity, tool in (('one', 'mcp__graphtraj__tasks'), ('two', 'WebSearch')):
            turn._control_event({'type': 'control_request', 'request_id': identity, 'request': {
                'subtype': 'can_use_tool', 'tool_name': tool, 'input': {'action': 'discover'},
                'tool_use_id': identity}})
        asked = sorted(item['params']['tool_name'] for item in turn.pending.values())
        if denied is None:
            assert turn.exempt_tools == ['mcp__graphtraj__tasks']
            assert replies.get(timeout=5) == ('one', {'behavior': 'allow', 'updatedInput': {'action': 'discover'}})
            assert asked == ['WebSearch']
        else:
            assert turn.exempt_tools == [] and 'tasks' not in turn.extra_tools
            assert asked == ['WebSearch', 'mcp__graphtraj__tasks']


@pytest.mark.parametrize('denied', ['tasks', 'mcp__graphtraj__tasks'])
def test_codex_child_disallowing_tasks_drops_it_and_keeps_agents(denied: str) -> None:
    """A Codex create disallowing tasks succeeds; the child keeps agents and loses only tasks."""
    from types import SimpleNamespace

    from graftling.codex.driver import owner_tools_kept
    from graphtraj.execution.agent_driver import apply_child_tools
    from graphtraj.runtimes.codex.managed_session import CodexManagedExecution

    request = {'session_parameters': {'config': {}}}
    apply_child_tools('codex', request, {'tools': ['mcp__graphtraj__agents'], 'disallowed_tools': [denied]})
    assert request['session_parameters']['config'] == {'web_search': 'disabled'}
    pairs = task_free_tools(Path('/project'), CHILD)
    assert owner_tools_kept(pairs, [denied], CodexManagedExecution.mcp_server) == []
    assert owner_tools_kept(pairs, ['web_search'], CodexManagedExecution.mcp_server) == pairs
