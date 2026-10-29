"""Independent ``agents`` tool for cross-Runtime child Agents.

The package depends on no GraphTraj module. :class:`AgentControl` is the
Task-free control backend over a caller-chosen data root; Runtime drivers
supply native execution. GraphTraj imports this package in one direction and
never needs Tasks, Teams, Rounds, Worldline, budgets, reports or Worktrees
to use it.

The public interface and its version rules are in ``PUBLIC_API.md`` beside
this file; anything it does not list is internal.
"""

# The only definition of the distribution version; packaging and every
# runtime report (MCP serverInfo, Codex clientInfo) read it from here.
__version__ = "0.2.0"

from agent_swarm.config import (
    CONFIG_DEFAULTS,
    default_config,
    explicit_choices,
    read_config,
    read_connections,
    write_config,
)
from agent_swarm.models import discover_models
from agent_swarm.control import (
    ACTIVE,
    STANDBY,
    AgentControl,
    ExecutionEvents,
    Run,
    RuntimeDriver,
)
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
from agent_swarm.sessions.archive import read_session
from agent_swarm.sessions.protocol import validate_extra_fields

__all__ = [
    "__version__",
    "ACTION_FIELDS", "INPUT_SCHEMA", "TOOL_NAME",
    "AgentsError", "AgentsResult", "Backend", "Binding", "Caller", "Outcome",
    "SessionArchive", "bind", "tool_descriptor", "unavailable", "validate_request",
    "ACTIVE", "STANDBY", "AgentControl", "ExecutionEvents", "Run", "RuntimeDriver",
    "CONFIG_DEFAULTS", "default_config", "explicit_choices", "read_config", "write_config",
    "discover_models", "read_connections",
    "read_session", "validate_extra_fields",
]
