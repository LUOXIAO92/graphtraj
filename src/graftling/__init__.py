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
__version__ = "0.5.0"

from importlib import import_module


def _lazy_names(names: dict[str, tuple[str, str]]):
    """Return a module ``__getattr__`` that loads each public name on first use.

    ``names`` maps a public name to its defining module and attribute. Loading
    late keeps ``import graftling`` from starting the Runtime packages, and
    lets ``python -m graftling.mcp`` run without importing that module twice.
    """

    def load(name: str) -> object:
        """Import the module that defines one public name."""
        if name not in names:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        module, attribute = names[name]
        return getattr(import_module(module), attribute)

    return load


from graftling.config import (
    CONFIG_DEFAULTS,
    default_config,
    explicit_choices,
    read_config,
    read_connections,
    write_config,
)
from graftling.models import discover_models
from graftling.control import (
    ACTIVE,
    STANDBY,
    AgentControl,
    ExecutionEvents,
    Run,
    RuntimeDriver,
)
from graftling.tool import (
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
from graftling.sessions.archive import read_session
from graftling.sessions.protocol import validate_extra_fields

__getattr__ = _lazy_names({
    # Requests a child makes of its parent.
    "DECISION_METHOD": ("graftling.approval", "DECISION_METHOD"),
    # Workspaces.
    "within_workspace": ("graftling.control", "within_workspace"),
    # Native Session files.
    "native_session_files": ("graftling.sessions.archive", "native_session_files"),
    # Stoppable calls.
    "CallCancelled": ("graftling.calls", "CallCancelled"),
    "on_discard": ("graftling.calls", "on_discard"),
    "pause": ("graftling.calls", "pause"),
    "run_stoppable": ("graftling.calls", "run_stoppable"),
    "stop_requested": ("graftling.calls", "stop_requested"),
    # The owner connection.
    "client_native_context": ("graftling.connection", "client_native_context"),
    "connection_operation": ("graftling.connection", "connection_operation"),
    "record_lock_owner": ("graftling.connection", "record_lock_owner"),
    "verify_native_context": ("graftling.connection", "verify_native_context"),
    "worker_connection": ("graftling.connection", "worker_connection"),
    # The progressive envelope.
    "ENVELOPE_SCHEMA": ("graftling.discovery", "INPUT_SCHEMA"),
    "handle_request": ("graftling.discovery", "handle_request"),
    "validate_envelope": ("graftling.discovery", "validate_envelope"),
    "validate_schema": ("graftling.schema", "validate"),
    # MCP server parts.
    "ClientGone": ("graftling.mcp", "ClientGone"),
    "ConcurrentServer": ("graftling.mcp", "ConcurrentServer"),
    "mcp_error_response": ("graftling.mcp", "error_response"),
    "mcp_respond": ("graftling.mcp", "respond"),
    "mcp_result_response": ("graftling.mcp", "result_response"),
    "mcp_serve": ("graftling.mcp", "serve"),
    "mcp_tool_documents": ("graftling.mcp", "tool_documents"),
    # Notices.
    "END_EVENTS": ("graftling.notices", "END_EVENTS"),
    "needs_parent": ("graftling.notices", "needs_parent"),
    "notice_id": ("graftling.notices", "notice_id"),
    # Processes and locks.
    "exclusive_lock": ("graftling.locks", "exclusive"),
    "stop_owned": ("graftling.shutdown", "stop_owned"),
    "exit_if_owned_unconfirmed": ("graftling.shutdown", "exit_if_owned_unconfirmed"),
    "process_ancestors": ("graftling.process", "process_ancestors"),
    "process_arguments": ("graftling.process", "process_arguments"),
    "process_executable": ("graftling.process", "process_executable"),
    # Runtime executions.
    "RuntimeAdapterError": ("graftling.runtime", "RuntimeAdapterError"),
    "RuntimeContext": ("graftling.runtime", "RuntimeContext"),
    "RuntimeExecutionResult": ("graftling.runtime", "RuntimeExecutionResult"),
    "RuntimeTurn": ("graftling.runtime", "RuntimeTurn"),
    "SessionStarted": ("graftling.runtime", "SessionStarted"),
    "credential_environment": ("graftling.runtime", "credential_environment"),
    "child_environment": ("graftling.child_env", "child_environment"),
    "is_credential_name": ("graftling.child_env", "is_credential_name"),
    "CODEX_SHELL_EXCLUDE": ("graftling.child_env", "CODEX_SHELL_EXCLUDE"),
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
    "exclusive_lock", "stop_owned", "exit_if_owned_unconfirmed", "process_ancestors", "process_arguments", "process_executable",
    "RuntimeAdapterError", "RuntimeContext", "RuntimeExecutionResult", "RuntimeTurn",
    "SessionStarted", "credential_environment", "child_environment", "is_credential_name", "CODEX_SHELL_EXCLUDE",
]
