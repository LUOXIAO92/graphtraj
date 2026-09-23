"""Host-callable GraphTraj operations over MCP stdio JSON-RPC.

The installed ``graphtraj-mcp`` entry point answers the MCP methods a host
needs to discover and run tools: ``initialize``, ``notifications/initialized``,
``tools/list``, ``tools/call`` and ``ping``. Every tool takes structured input
and calls the same Python operation as the CLI, so a host receives the same
document instead of reconstructing it from terminal output.

The server speaks newline-delimited JSON-RPC 2.0 over stdin/stdout and uses
only the standard library, so no MCP SDK dependency is required. It reads the
Harness Project Root from its own working directory, exactly like the CLI.
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, TextIO

import yaml

from graphtraj.configuration.project_configuration import (
    ProjectConfigurationError,
    load_project_configuration,
)
from graphtraj.execution.execution_budget import budget_notice_output, caller_notice_fd
from graphtraj.execution.runner_control import (
    interrupt_session,
    pending_requests,
    reply_to_request,
    read_session_reports,
    submit_session_report,
    send_instruction,
)
from graphtraj.execution.runner_launch import launch_swarm
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import status_aliases, status_tree
from graphtraj.graph.ticket_graph import (
    read_graph,
    register_ticket,
    revise_tickets,
    update_ticket_state,
)
from graphtraj.runtimes.codex.app_server import CodexMainRecovery
from graphtraj.runtimes.codex.codex_adapter import CodexAdapterError


JSONRPC_VERSION = "2.0"
PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO      = {"name": "graphtraj", "version": "0.1.0"}

PARSE_ERROR      = -32700
INVALID_REQUEST  = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS   = -32602

_ISSUE_PROPERTIES = {
    "ticket_id":         {"type": "string"},
    "ticket_name":       {"type": "string"},
    "source":            {"type": "string"},
    "title":             {"type": "string"},
    "body":              {"type": "string"},
    "dependencies":      {"type": "array", "items": {"type": "string"}},
}
_ISSUE_SCHEMA = {
    "type":                 "object",
    "properties":           _ISSUE_PROPERTIES,
    "required":             sorted(_ISSUE_PROPERTIES),
    "additionalProperties": False,
}
_REVISED_TICKET_SCHEMA = {
    "type": "object",
    "properties": {
        **_ISSUE_PROPERTIES,
        "active":      {"type": "boolean"},
        "replaced_by": {"type": "array", "items": {"type": "string"}},
    },
    "required":             sorted({*_ISSUE_PROPERTIES, "active", "replaced_by"}),
    "additionalProperties": False,
}
_REVISION_SCHEMA = {
    "type": "object",
    "properties": {
        "product_preserving":  {"const": True},
        "caused_by_event_ids": {"type": "array", "items": {"type": "string"}},
        "evidence_refs":       {"type": "array", "items": {"type": "string"}},
        "tickets":             {"type": "array", "items": _REVISED_TICKET_SCHEMA},
    },
    "required":             [
        "product_preserving", "caused_by_event_ids", "evidence_refs", "tickets",
    ],
    "additionalProperties": False,
}
_STATE_CHANGE_SCHEMA = {
    "type": "object",
    "properties": {
        "ticket_id":           {"type": "string"},
        "status":              {"type": "string"},
        "active_team_ordinal": {"type": ["integer", "null"]},
        "worktree":            {"type": ["string", "null"]},
        "branch":              {"type": ["string", "null"]},
        "current_candidate":   {"type": ["string", "null"]},
        "caused_by_event_ids": {"type": "array", "items": {"type": "string"}},
        "evidence_refs":       {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "ticket_id", "status", "active_team_ordinal", "worktree", "branch",
        "current_candidate", "caused_by_event_ids", "evidence_refs",
    ],
    "additionalProperties": False,
}
_EMPTY_SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}
_ALIAS_SCHEMA = {
    "type": "object",
    "properties": {"alias": {"type": "string"}},
    "required":             ["alias"],
    "additionalProperties": False,
}
_SWARM_TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "ticket_id":   {"type": "string"},
        "ticket_name": {"type": "string"},
        "role":        {"type": ["string", "object"]},
        "instruction": {"type": "string"},
        "skills":      {"type": "array", "items": {"type": "string"}},
    },
    "required":             ["role"],
    "additionalProperties": False,
}
_SWARM_SCHEMA = {
    "type": "object",
    "properties": {"tasks": {"type": "array", "items": _SWARM_TASK_SCHEMA}},
    "required":             ["tasks"],
    "additionalProperties": False,
}
_SEND_SCHEMA = {
    "type": "object",
    "properties": {
        "alias":               {"type": "string"},
        "instruction":         {"type": "string"},
        "caused_by_event_ids": {"type": "array", "items": {"type": "string"}},
        "reports_only":        {"type": "boolean"},
    },
    "required":             ["alias", "instruction"],
    "additionalProperties": False,
}
_CONTINUE_SCHEMA = {
    "type": "object",
    "properties": {
        "ticket_id":           {"type": "string"},
        "caused_by_event_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required":             ["ticket_id", "caused_by_event_ids"],
    "additionalProperties": False,
}
_REQUESTS_SCHEMA = {
    "type": "object",
    "properties": {
        "alias":        {"type": "string"},
        "execution_id": {"type": ["string", "null"]},
    },
    "required":             ["alias"],
    "additionalProperties": False,
}
_REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "alias":    {"type": "string"},
        "request":  {"type": "object"},
        "response": {"type": "object"},
    },
    "required":             ["alias", "request", "response"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class ToolResult:
    """One tool's structured document and whether the operation failed."""

    document: dict[str, Any]
    failed: bool = False


@dataclass(frozen=True)
class Tool:
    """One host-callable operation with its structured input schema."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., ToolResult]


TOOLS: dict[str, Tool] = {}

# The Runtime callback reuses these public handlers and argument schemas.
# Ticket state mutation and arbitrary file operations are not Runtime tools.
NATIVE_RUNNER_TOOLS = {
    'graphtraj_status': 'alias_status',
    'graphtraj_swarm': 'swarm',
    'graphtraj_send': 'send_instruction',
    'graphtraj_interrupt': 'interrupt',
    'graphtraj_requests': 'pending_requests',
    'graphtraj_reply': 'reply_to_request',
    'graphtraj_reports': 'session_reports',
    'graphtraj_submit_report': 'submit_report',
    'graphtraj_ticket_graph': 'ticket_graph',
}


def native_runner_tools() -> list[dict[str, Any]]:
    """Describe existing Runner operations for the native callback transport."""
    return [
        {'type': 'function', 'name': name, 'description': TOOLS[key].description,
         'inputSchema': TOOLS[key].input_schema}
        for name, key in NATIVE_RUNNER_TOOLS.items()
    ]


def register_tool(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    handler: Callable[..., ToolResult],
) -> None:
    """Register one host-callable operation on the MCP server.

    Later tickets extend this seam with new tools; the server lists whatever is
    registered under ``TOOLS`` and adds no separate dispatch table.
    """
    TOOLS[name] = Tool(name, description, input_schema, handler)


def read_current_graph(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> ToolResult:
    """Return the current Ticket DAG and readiness view for the project."""

    configuration = load_project_configuration(cwd or Path.cwd())
    return ToolResult(read_graph(configuration.state))


def register_current_ticket(arguments: Mapping[str, Any]) -> ToolResult:
    """Register one accepted Ticket definition in the project graph."""

    configuration = load_project_configuration(Path.cwd())
    directory = register_ticket(
        configuration.state, configuration.harness_root, dict(arguments)
    )
    return ToolResult({"ticket_directory": str(directory)})


def revise_current_tickets(arguments: Mapping[str, Any]) -> ToolResult:
    """Apply one validated product-preserving Task Graph revision."""

    configuration = load_project_configuration(Path.cwd())
    recorded = revise_tickets(
        configuration.state, configuration.harness_root, dict(arguments)
    )
    return ToolResult(recorded)


def update_current_ticket_state(arguments: Mapping[str, Any]) -> ToolResult:
    """Apply one evidence-backed current Ticket state transition."""

    configuration = load_project_configuration(Path.cwd())
    recorded = update_ticket_state(
        configuration.state, configuration.harness_root, dict(arguments)
    )
    return ToolResult(recorded)


def read_alias_status(
    arguments: Mapping[str, Any], *, cwd: Path | None = None,
) -> ToolResult:
    """Report the requested Session aliases, or the visible Session tree."""

    aliases = arguments.get("aliases")
    operation_total = bool(arguments.get("operation_total", False))
    baseline = arguments.get("baseline")
    candidate = arguments.get("candidate")
    if aliases is None:
        response = status_tree(
            cwd or Path.cwd(),
            operation_total=operation_total,
            baseline=baseline,
            candidate=candidate,
        )
    else:
        if not isinstance(aliases, list) or not all(
            isinstance(alias, str) for alias in aliases
        ):
            raise ValueError("aliases must be a list of Session alias strings")
        response = status_aliases(
            aliases,
            cwd or Path.cwd(),
            operation_total=operation_total,
            baseline=baseline,
            candidate=candidate,
        )
    return ToolResult(response.document, failed=not response.succeeded)


def _string_argument(arguments: Mapping[str, Any], name: str) -> str:
    """Return one required string argument without restating the operation."""

    value = arguments.get(name)
    if not isinstance(value, str):
        raise ValueError("{0} must be a string".format(name))
    return value


def _optional_string_argument(
    arguments: Mapping[str, Any], name: str
) -> str | None:
    """Return one optional string argument, or None when it was not supplied."""

    value = arguments.get(name)
    if value is not None and not isinstance(value, str):
        raise ValueError("{0} must be a string".format(name))
    return value


def _string_list_argument(
    arguments: Mapping[str, Any], name: str
) -> tuple[str, ...]:
    """Return one optional list of strings; the operation owns its own rules."""

    value = arguments.get(name, [])
    if not isinstance(value, list) or any(
        not isinstance(item, str) for item in value
    ):
        raise ValueError("{0} must be a list of strings".format(name))
    return tuple(value)


def _boolean_argument(arguments: Mapping[str, Any], name: str) -> bool:
    """Return one optional flag, defaulting to the operation's plain behavior."""

    value = arguments.get(name, False)
    if not isinstance(value, bool):
        raise ValueError("{0} must be a boolean".format(name))
    return value


def launch_swarm_tool(
    arguments: Mapping[str, Any], *, cwd: Path | None = None,
) -> ToolResult:
    """Activate one swarm input; the returned identity stays owned.

    The calling Session's Ticket and the registered Ticket state supply the
    identity each task does not repeat.
    """

    response = launch_swarm(dict(arguments), cwd or Path.cwd())
    return ToolResult(response.document, failed=not response.succeeded)


def send_session_instruction(
    arguments: Mapping[str, Any], *, cwd: Path | None = None,
) -> ToolResult:
    """Steer an active execution or continue an idle mapped Session.

    ``reports_only`` resumes the Session to return evidence it already holds
    without sampling the Ticket budget, so a report collection cannot repeat a
    sampled stop or deliver another retro instruction.
    """

    return ToolResult(
        send_instruction(
            _string_argument(arguments, "alias"),
            _string_argument(arguments, "instruction"),
            cwd or Path.cwd(),
            _string_list_argument(arguments, "caused_by_event_ids"),
            reports_only=_boolean_argument(arguments, "reports_only"),
        )
    )


def interrupt_session_execution(
    arguments: Mapping[str, Any], *, cwd: Path | None = None,
) -> ToolResult:
    """Stop a descendant subtree and return each member confirmation."""

    return ToolResult(
        interrupt_session(_string_argument(arguments, "alias"), cwd or Path.cwd())
    )


def continue_ticket_execution(arguments: Mapping[str, Any]) -> ToolResult:
    """Continue one stopped current Team through the D.3 stop/continue path."""

    from graphtraj.teams.coding.team_round import continue_stopped_ticket

    return ToolResult(
        continue_stopped_ticket(
            _string_argument(arguments, "ticket_id"),
            _string_list_argument(arguments, "caused_by_event_ids"),
            Path.cwd(),
        )
    )


def read_pending_requests(
    arguments: Mapping[str, Any], *, cwd: Path | None = None,
) -> ToolResult:
    """Query the mapped execution's native requests without consuming them."""

    return ToolResult(
        pending_requests(
            _string_argument(arguments, "alias"),
            cwd or Path.cwd(),
            execution_id=_optional_string_argument(arguments, "execution_id"),
        )
    )


def answer_pending_request(
    arguments: Mapping[str, Any], *, cwd: Path | None = None,
) -> ToolResult:
    """Submit an explicit reply to one request returned by the query path."""

    request = arguments.get("request")
    response = arguments.get("response")
    if not isinstance(request, dict) or not isinstance(response, dict):
        raise ValueError("request and response must be JSON objects")
    return ToolResult(
        reply_to_request(
            _string_argument(arguments, "alias"), request, response, cwd or Path.cwd()
        )
    )


register_tool(
    "ticket_graph",
    "Read the current Ticket DAG, states and dependency readiness for the project "
    "in the server working directory. Equivalent to `graphtraj ticket graph`.",
    _EMPTY_SCHEMA,
    read_current_graph,
)
register_tool(
    "ticket_register",
    "Register one accepted Ticket definition with its dependencies. Equivalent to "
    "`graphtraj ticket register --ticket-file`.",
    _ISSUE_SCHEMA,
    register_current_ticket,
)
register_tool(
    "ticket_revise",
    "Apply one validated product-preserving Ticket graph revision and return its "
    "recorded causal event. Equivalent to `graphtraj ticket revise`.",
    _REVISION_SCHEMA,
    revise_current_tickets,
)
register_tool(
    "ticket_update",
    "Apply one evidence-backed Ticket state transition and return its recorded "
    "causal event. Equivalent to `graphtraj ticket update`.",
    _STATE_CHANGE_SCHEMA,
    update_current_ticket_state,
)
register_tool(
    "alias_status",
    "Read the explicitly supplied Session aliases, including their Runtime "
    "activity and last outcome, or omit `aliases` for the Session tree this "
    "caller may see. Equivalent to `agent-runner status`.",
    {
        "type": "object",
        "properties": {
            "aliases":         {"type": "array", "items": {"type": "string"}},
            "operation_total": {"type": "boolean"},
            "baseline":        {"type": ["string", "null"]},
            "candidate":       {"type": ["string", "null"]},
        },
        "additionalProperties": False,
    },
    read_alias_status,
)
register_tool(
    "swarm",
    "Activate the roles this swarm input selects and return each Agent's alias, "
    "so later calls query, steer and continue it by that alias rather than by "
    "another launch input. Equivalent to `agent-runner --swarm-input`.",
    _SWARM_SCHEMA,
    launch_swarm_tool,
)
register_tool(
    "send_instruction",
    "Steer an active execution or continue an idle mapped Session using unique "
    "causal Project Worldline event IDs. Equivalent to `agent-runner send`.",
    _SEND_SCHEMA,
    send_session_instruction,
)
register_tool(
    "interrupt",
    "Stop a descendant subtree and prevent further work while preserving its "
    "Sessions. Returns each member confirmation. Equivalent to `agent-runner interrupt`.",
    _ALIAS_SCHEMA,
    interrupt_session_execution,
)
register_tool(
    "continue",
    "Continue one stopped current Team from its retained Batch and Sessions; the "
    "existing stop, budget and accounting semantics are unchanged. Equivalent to "
    "`agent-runner continue`.",
    _CONTINUE_SCHEMA,
    continue_ticket_execution,
)
register_tool(
    "pending_requests",
    "Query the mapped execution's pending native approval or user-input requests, "
    "including the identity required to reply. Equivalent to `agent-runner "
    "requests`.",
    _REQUESTS_SCHEMA,
    read_pending_requests,
)
register_tool(
    "reply_to_request",
    "Return the explicit native reply for one request document obtained from "
    "`pending_requests`. Equivalent to `agent-runner reply`.",
    _REPLY_SCHEMA,
    answer_pending_request,
)


def read_reports(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> ToolResult:
    """Read the declared reports of an authorized direct child."""
    return ToolResult(read_session_reports(_string_argument(arguments, 'alias'), cwd or Path.cwd()))


register_tool('session_reports', 'Read the declared current reports of your direct child.',
              _ALIAS_SCHEMA, read_reports)


def submit_report(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> ToolResult:
    """Submit the current Session's assigned report through the shared operation."""
    return ToolResult(submit_session_report(_string_argument(arguments, 'name'),
                                           _string_argument(arguments, 'text'), cwd or Path.cwd()))


register_tool('submit_report', 'Write your own assigned report by filename (for example engineer.md).',
              {'type': 'object', 'properties': {'name': {'type': 'string'}, 'text': {'type': 'string'}},
               'required': ['name', 'text'], 'additionalProperties': False}, submit_report)


def _tool_document(tool: Tool) -> dict[str, Any]:
    """Render one registered tool as an MCP tool descriptor."""

    return {
        "name":        tool.name,
        "description": tool.description,
        "inputSchema": tool.input_schema,
    }


def _result_response(request_id: Any, result: Mapping[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id":      request_id,
        "error":   {"code": code, "message": message},
    }


def _initialize_result(params: Mapping[str, Any]) -> dict[str, Any]:
    """Agree on the host's requested protocol version and advertise tools."""

    requested = params.get("protocolVersion")
    return {
        "protocolVersion": requested if isinstance(requested, str) else PROTOCOL_VERSION,
        "capabilities":    {"tools": {}},
        "serverInfo":      SERVER_INFO,
    }


@contextmanager
def _caller_notices(
    params: Mapping[str, Any],
) -> Iterator[CodexMainRecovery | None]:
    """Route live budget notices to the Codex Main that made this request.

    A worker's inherited channel wins. Otherwise the request's own Codex
    thread identity selects its Main through the existing recovery binding, so
    a stop produced by this operation reaches the conversation that called it.
    A request carrying no Codex caller context keeps the generic behaviour of
    no notice channel.
    """

    descriptor, owned = caller_notice_fd()
    if descriptor is None:
        recovery = CodexMainRecovery.from_request(
            Path.cwd().resolve(), params.get("_meta")
        )
        if recovery is not None:
            with recovery:
                with budget_notice_output(recovery.notice_fd):
                    yield recovery
            return
        yield None
        return
    try:
        with budget_notice_output(descriptor):
            yield None
    finally:
        if owned:
            os.close(descriptor)


def _tool_call_response(
    request_id: Any, params: Mapping[str, Any]
) -> dict[str, Any]:
    """Run one registered tool and return its document as an MCP tool result."""

    name = params.get("name")
    tool = TOOLS.get(name) if isinstance(name, str) else None
    if tool is None:
        return _error_response(
            request_id, INVALID_PARAMS, "Unknown tool: {0}".format(name)
        )
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        return _error_response(
            request_id, INVALID_PARAMS, "Tool arguments must be an object."
        )
    try:
        with _caller_notices(params) as recovery:
            result = tool.handler(arguments)
            document = (
                recovery.attach_stop_deliveries(result.document)
                if recovery is not None
                else result.document
            )
    except (
        OSError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
        ProjectConfigurationError,
        RunnerError,
        CodexAdapterError,
    ) as error:
        # A rejected operation is a tool failure, not a protocol failure, so the
        # host receives the same message the CLI reports for the same input and
        # this server keeps answering later calls. RunnerError carries the
        # shared operations' own rejections, such as a status query outside a
        # Harness Project Root or incomplete Git diagnostics arguments.
        return _result_response(
            request_id,
            {"content": [{"type": "text", "text": str(error)}], "isError": True},
        )
    return _result_response(
        request_id,
        {
            # The text is the CLI's YAML rendering of the same document.
            "content":           [
                {"type": "text", "text": yaml.safe_dump(document, sort_keys=False)}
            ],
            "structuredContent": document,
            "isError":           result.failed,
        },
    )


def _respond(message: Mapping[str, Any]) -> dict[str, Any] | None:
    """Answer one JSON-RPC message, or return None for a notification."""

    method = message.get("method")
    if not isinstance(method, str) or "id" not in message:
        # Responses and host notifications (initialized, cancelled) need no reply.
        return None
    request_id = message.get("id")
    params = message.get("params")
    if not isinstance(params, dict):
        params = {}
    if method == "initialize":
        return _result_response(request_id, _initialize_result(params))
    if method == "tools/list":
        return _result_response(
            request_id, {"tools": [_tool_document(tool) for tool in TOOLS.values()]}
        )
    if method == "tools/call":
        return _tool_call_response(request_id, params)
    if method == "ping":
        return _result_response(request_id, {})
    return _error_response(
        request_id, METHOD_NOT_FOUND, "Unsupported method: {0}".format(method)
    )


def serve(input_stream: TextIO, output_stream: TextIO) -> None:
    """Answer newline-delimited JSON-RPC requests until the host closes input."""

    for line in input_stream:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            reply = _error_response(None, PARSE_ERROR, "Parse error")
        else:
            reply = (
                _respond(message)
                if isinstance(message, dict)
                else _error_response(None, INVALID_REQUEST, "Invalid request")
            )
        if reply is None:
            continue
        output_stream.write(json.dumps(reply) + "\n")
        output_stream.flush()


def main() -> None:
    """Run the MCP stdio server installed as the ``graphtraj-mcp`` command."""

    serve(sys.stdin, sys.stdout)
