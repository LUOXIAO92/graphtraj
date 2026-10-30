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
__version__ = "0.2.2"

from importlib import import_module


def _lazy_names(names: dict[str, tuple[str, str]]):
    """Return a module ``__getattr__`` that loads each public name on first use.

    ``names`` maps a public name to its defining module and attribute. Loading
    late keeps ``import agent_swarm`` from starting the Runtime packages, and
    lets ``python -m agent_swarm.mcp`` run without importing that module twice.
    """

    def load(name: str) -> object:
        """Import the module that defines one public name."""
        if name not in names:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        module, attribute = names[name]
        return getattr(import_module(module), attribute)

    return load


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

__getattr__ = _lazy_names({
    # Requests a child makes of its parent.
    "DECISION_METHOD": ("agent_swarm.approval", "DECISION_METHOD"),
    # Workspaces.
    "within_workspace": ("agent_swarm.control", "within_workspace"),
    # Native Session files.
    "native_session_files": ("agent_swarm.sessions.archive", "native_session_files"),
    # Stoppable calls.
    "CallCancelled": ("agent_swarm.calls", "CallCancelled"),
    "on_discard": ("agent_swarm.calls", "on_discard"),
    "pause": ("agent_swarm.calls", "pause"),
    "run_stoppable": ("agent_swarm.calls", "run_stoppable"),
    "stop_requested": ("agent_swarm.calls", "stop_requested"),
    # The owner connection.
    "client_native_context": ("agent_swarm.connection", "client_native_context"),
    "connection_operation": ("agent_swarm.connection", "connection_operation"),
    "record_lock_owner": ("agent_swarm.connection", "record_lock_owner"),
    "verify_native_context": ("agent_swarm.connection", "verify_native_context"),
    "worker_connection": ("agent_swarm.connection", "worker_connection"),
    # The progressive envelope.
    "ENVELOPE_SCHEMA": ("agent_swarm.discovery", "INPUT_SCHEMA"),
    "handle_request": ("agent_swarm.discovery", "handle_request"),
    "validate_envelope": ("agent_swarm.discovery", "validate_envelope"),
    "validate_schema": ("agent_swarm.schema", "validate"),
    # MCP server parts.
    "ClientGone": ("agent_swarm.mcp", "ClientGone"),
    "ConcurrentServer": ("agent_swarm.mcp", "ConcurrentServer"),
    "mcp_error_response": ("agent_swarm.mcp", "error_response"),
    "mcp_respond": ("agent_swarm.mcp", "respond"),
    "mcp_result_response": ("agent_swarm.mcp", "result_response"),
    "mcp_serve": ("agent_swarm.mcp", "serve"),
    "mcp_tool_documents": ("agent_swarm.mcp", "tool_documents"),
    # Notices.
    "END_EVENTS": ("agent_swarm.notices", "END_EVENTS"),
    "needs_parent": ("agent_swarm.notices", "needs_parent"),
    "notice_id": ("agent_swarm.notices", "notice_id"),
    # Processes and locks.
    "exclusive_lock": ("agent_swarm.locks", "exclusive"),
    "process_ancestors": ("agent_swarm.process", "process_ancestors"),
    "process_arguments": ("agent_swarm.process", "process_arguments"),
    "process_executable": ("agent_swarm.process", "process_executable"),
    # Runtime executions.
    "RuntimeAdapterError": ("agent_swarm.runtime", "RuntimeAdapterError"),
    "RuntimeContext": ("agent_swarm.runtime", "RuntimeContext"),
    "RuntimeExecutionResult": ("agent_swarm.runtime", "RuntimeExecutionResult"),
    "RuntimeTurn": ("agent_swarm.runtime", "RuntimeTurn"),
    "SessionStarted": ("agent_swarm.runtime", "SessionStarted"),
    "credential_environment": ("agent_swarm.runtime", "credential_environment"),
})

__all__ = [
    "__version__",
    "ACTION_FIELDS", "INPUT_SCHEMA", "TOOL_NAME",
    "AgentsError", "AgentsResult", "Backend", "Binding", "Caller", "Outcome",
    "SessionArchive", "bind", "tool_descriptor", "unavailable", "validate_request",
    "ACTIVE", "STANDBY", "AgentControl", "ExecutionEvents", "Run", "RuntimeDriver",
    "CONFIG_DEFAULTS", "default_config", "explicit_choices", "read_config", "write_config",
    "discover_models", "read_connections",
    "read_session", "validate_extra_fields", "DECISION_METHOD", "within_workspace", "native_session_files",
    "CallCancelled", "on_discard", "pause", "run_stoppable", "stop_requested",
    "client_native_context", "connection_operation", "record_lock_owner",
    "verify_native_context", "worker_connection",
    "ENVELOPE_SCHEMA", "handle_request", "validate_envelope", "validate_schema",
    "ClientGone", "ConcurrentServer", "mcp_error_response", "mcp_respond",
    "mcp_result_response", "mcp_serve", "mcp_tool_documents",
    "END_EVENTS", "needs_parent", "notice_id",
    "exclusive_lock", "process_ancestors", "process_arguments", "process_executable",
    "RuntimeAdapterError", "RuntimeContext", "RuntimeExecutionResult", "RuntimeTurn",
    "SessionStarted", "credential_environment",
]
