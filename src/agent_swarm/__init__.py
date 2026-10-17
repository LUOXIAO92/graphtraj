"""Independent ``agents`` tool contract for cross-Runtime child Agents.

The package depends on no GraphTraj module. GraphTraj imports it in one
direction and supplies a control backend; it never needs Tasks, Teams,
Rounds, Worldline, budgets, reports or Worktrees.
"""

from agent_swarm.tool import (
    ACTION_FIELDS,
    INPUT_SCHEMA,
    TOOL_NAME,
    AgentsError,
    AgentsResult,
    Backend,
    Binding,
    Caller,
    Outcome,
    SessionArchive,
    bind,
    tool_descriptor,
    unavailable,
    validate_request,
)

__all__ = [
    "ACTION_FIELDS", "INPUT_SCHEMA", "TOOL_NAME",
    "AgentsError", "AgentsResult", "Backend", "Binding", "Caller", "Outcome",
    "SessionArchive", "bind", "tool_descriptor", "unavailable", "validate_request",
]
