"""Host-callable GraphTraj operations over MCP stdio JSON-RPC.

The installed ``graphtraj-mcp`` entry point answers the MCP methods a host
needs to discover and run tools: ``initialize``, ``notifications/initialized``,
``tools/list``, ``tools/call`` and ``ping``. It exposes one ``graphtraj`` tool
whose fixed outer schema forwards discover/describe/execute requests to the
shared gateway, so a host reaches the same operations and documents as the CLI.

The server speaks newline-delimited JSON-RPC 2.0 over stdin/stdout and uses
only the standard library, so no MCP SDK dependency is required. It reads the
Harness Project Root from its own working directory, exactly like the CLI.
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, TextIO

import yaml

from graphtraj.configuration.project_configuration import ProjectConfigurationError
from graphtraj.execution.execution_budget import budget_notice_output, caller_notice_fd
from graphtraj.execution.runner_models import RunnerError
from graphtraj.interfaces import gateway
from graphtraj.runtimes.codex.app_server import CodexMainRecovery
from graphtraj.runtimes.codex.codex_adapter import CodexAdapterError


JSONRPC_VERSION = "2.0"
PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO      = {"name": "graphtraj", "version": "0.1.0"}

MCP_TOOL_NAME        = "graphtraj"
MCP_TOOL_DESCRIPTION = (
    "Discover, describe, or run a GraphTraj feature. Send "
    "action=discover to list features, action=describe for one feature's "
    "guide reference (schema=true requests only its parameters), and action=execute to run it."
)

PARSE_ERROR      = -32700
INVALID_REQUEST  = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS   = -32602

def _tool_document() -> dict[str, Any]:
    """Render the single ``graphtraj`` entry the host discovers.

    The outer schema is the gateway's fixed request structure, so new features
    never expand the registered tool list or add another top-level tool.
    """

    return {
        "name":        MCP_TOOL_NAME,
        "description": MCP_TOOL_DESCRIPTION,
        "inputSchema": gateway.INPUT_SCHEMA,
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
            params.get("_meta")
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
    """Forward one ``graphtraj`` request and return its MCP tool result.

    The request's outer arguments are the gateway's discover/describe/execute
    envelope. The server's own working directory is the trusted project
    location; model arguments cannot supply it. Business failures keep the
    shared document and the CLI's message instead of stopping the server.
    """

    name = params.get("name")
    if name != MCP_TOOL_NAME:
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
            result = gateway.handle_request(arguments, cwd=Path.cwd())
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
        return _result_response(request_id, {"tools": [_tool_document()]})
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
