"""GraphTraj's own MCP server is ``graphtraj`` on every Runtime; agents alone keeps graftling's (514)."""

from __future__ import annotations

from importlib import import_module

import pytest


@pytest.mark.parametrize('module, cls, flag', [
    ('graphtraj.runtimes.claude.execution', 'ClaudeExecution', 'independent'),
    ('graphtraj.runtimes.dsh.execution', 'DshExecution', 'agents_only'),
])
def test_a_member_tells_graftling_the_graphtraj_server(module: str, cls: str, flag: str) -> None:
    """graftling's review exemption and display follow the name the execution registers."""
    execution = object.__new__(getattr(import_module(module), cls))
    setattr(execution, flag, False)
    assert execution.mcp_server == 'graphtraj'
    # Since 551 an agents child registers GraphTraj's name too, so it sees mcp__graphtraj__tasks.
    setattr(execution, flag, True)
    assert execution.mcp_server == 'graphtraj'
