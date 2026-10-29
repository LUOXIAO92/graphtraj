"""Task 390: agents discovery finds create from intent words, not only its action name."""
from __future__ import annotations

import pytest

from agent_swarm.discovery import DESCRIPTIONS, handle_request


def discovered(query: str) -> list[str]:
    """Return the features one discover query lists."""
    result = handle_request({'action': 'discover', 'query': query}, None)
    assert not result.failed, result.document
    return [item['feature'] for item in result.document['features']]


def test_graphtraj_hosts_discover_agents_through_this_matcher() -> None:
    """The Claude-native host and the GraphTraj MCP server use this same discovery."""
    from graphtraj.runtimes.claude import host, mcp

    assert host.handle_request is handle_request
    assert mcp.discover_agents is handle_request


@pytest.mark.parametrize('query', ['start an agent', 'launch a new agent', 'spawn agent', 'Start a new Agent'])
def test_intent_queries_find_create(query: str) -> None:
    """An intent phrase finds create and nothing else."""
    assert discovered(query) == ['create']


@pytest.mark.parametrize('query', ['bake a cake', 'start a cake', 'deploy kubernetes'])
def test_unrelated_queries_still_find_nothing(query: str) -> None:
    """Intent words and filler words never turn a query into match-all."""
    assert discovered(query) == []


def test_empty_and_action_name_queries_keep_their_matches() -> None:
    """An empty query lists every feature as before; action names still match."""
    assert discovered('') == list(DESCRIPTIONS)
    assert discovered('retire') == ['retire']
    assert len(discovered('agent')) < len(DESCRIPTIONS)
