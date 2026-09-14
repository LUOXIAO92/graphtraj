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
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, TextIO

import yaml

from graphtraj.configuration.project_configuration import (
    ProjectConfigurationError,
    load_project_configuration,
)
from graphtraj.execution.runner_status import status_aliases
from graphtraj.graph.ticket_graph import (
    read_graph,
    register_ticket,
    revise_tickets,
    update_ticket_state,
)


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
    handler: Callable[[Mapping[str, Any]], ToolResult]


TOOLS: dict[str, Tool] = {}


def register_tool(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    handler: Callable[[Mapping[str, Any]], ToolResult],
) -> None:
    """Register one host-callable operation on the MCP server.

    Later tickets extend this seam with new tools; the server lists whatever is
    registered under ``TOOLS`` and adds no separate dispatch table.
    """
    TOOLS[name] = Tool(name, description, input_schema, handler)


def read_current_graph(arguments: Mapping[str, Any]) -> ToolResult:
    """Return the current Ticket DAG and readiness view for the project."""

    configuration = load_project_configuration(Path.cwd())
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


def read_alias_status(arguments: Mapping[str, Any]) -> ToolResult:
    """Report the requested Session aliases; never discover a Run."""

    aliases = arguments.get("aliases")
    if not isinstance(aliases, list) or not all(
        isinstance(alias, str) for alias in aliases
    ):
        raise ValueError("aliases must be a list of Session alias strings")
    response = status_aliases(
        aliases,
        Path.cwd(),
        operation_total=bool(arguments.get("operation_total", False)),
        baseline=arguments.get("baseline"),
        candidate=arguments.get("candidate"),
    )
    return ToolResult(response.document, failed=not response.succeeded)


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
    "activity and last outcome. Equivalent to `agent-runner status`.",
    {
        "type": "object",
        "properties": {
            "aliases":         {"type": "array", "items": {"type": "string"}},
            "operation_total": {"type": "boolean"},
            "baseline":        {"type": ["string", "null"]},
            "candidate":       {"type": ["string", "null"]},
        },
        "required":             ["aliases"],
        "additionalProperties": False,
    },
    read_alias_status,
)


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
        result = tool.handler(arguments)
    except (
        OSError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
        ProjectConfigurationError,
    ) as error:
        # A rejected operation is a tool failure, not a protocol failure, so the
        # host receives the same message the CLI reports for the same input.
        return _result_response(
            request_id,
            {"content": [{"type": "text", "text": str(error)}], "isError": True},
        )
    return _result_response(
        request_id,
        {
            # The text is the CLI's YAML rendering of the same document.
            "content":           [
                {"type": "text", "text": yaml.safe_dump(result.document, sort_keys=False)}
            ],
            "structuredContent": result.document,
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
