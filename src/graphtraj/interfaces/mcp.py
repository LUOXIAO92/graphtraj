"""Host-callable GraphTraj operations over MCP stdio JSON-RPC.

The installed ``graphtraj-mcp`` entry point answers the MCP methods a host
needs to discover and run tools: ``initialize``, ``notifications/initialized``,
``tools/list``, ``tools/call`` and ``ping``. The ``graphtraj`` tool forwards
discover/describe/execute requests to the shared gateway. Pi exposes only
``agents`` and ``tasks`` as progressive entries into that same gateway.

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


def _tool_documents() -> list[dict[str, Any]]:
    """Keep Pi's initial list small without duplicating its model entry."""
    if os.environ.get('GRAPHTRAJ_NATIVE_RUNTIME') == 'pi':
        return [
            {'name': name, 'description': f'Discover, describe, or execute {name} features.',
             'inputSchema': gateway.INPUT_SCHEMA}
            for name in ('agents', 'tasks')
        ]
    return [_tool_document()]


def _result_response(request_id: Any, result: Mapping[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id":      request_id,
        "error":   {"code": code, "message": message},
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
    """Forward a registered function request and return its MCP tool result.

    The request's outer arguments are the gateway's discover/describe/execute
    envelope. The server's own working directory is the trusted project
    location; model arguments cannot supply it. Business failures keep the
    shared document and the CLI's message instead of stopping the server.
    """

    name = params.get("name")
    pi_entry = os.environ.get('GRAPHTRAJ_NATIVE_RUNTIME') == 'pi'
    names = ('agents', 'tasks') if pi_entry else (MCP_TOOL_NAME,)
    if name not in names:
        return _error_response(
            request_id, INVALID_PARAMS, "Unknown tool: {0}".format(name)
        )
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        return _error_response(
            request_id, INVALID_PARAMS, "Tool arguments must be an object."
        )
    try:
        # Keep the selected entry's scope before forwarding into the already
        # authenticated host. The host still owns feature authorization.
        if pi_entry and name == 'tasks' and arguments.get('action') != 'discover':
            if arguments.get('feature') == 'agents':
                raise ValueError('Feature does not belong to this MCP entry.')
        from graphtraj.runtimes.codex.host_events import calling_session

        metadata = params.get('_meta', {})
        session = metadata.get('threadId') if isinstance(metadata, dict) else None
        if session is not None and (not isinstance(session, str) or not session):
            raise ValueError('Invalid native MCP Session metadata.')
        with calling_session(session), _caller_notices(params) as recovery:
            from graphtraj.interfaces.hosted_cli import forward_request

            def dispatch(request: dict) -> Any:
                """Keep the existing host binding and shared business gateway."""
                result = forward_request(request, Path.cwd())
                return result if result is not None else gateway.handle_request(request, cwd=Path.cwd())

            if pi_entry and name == 'agents':
                from agent_swarm.discovery import handle_request

                result = handle_request(arguments, lambda request: dispatch({
                    'action': 'execute', 'feature': 'agents', 'arguments': request,
                }))
            else:
                result = dispatch(arguments)
            document = (
                recovery.attach_stop_deliveries(result.document)
                if recovery is not None
                else result.document
            )
            if pi_entry and name == 'tasks' and arguments.get('action') == 'discover' and 'features' in document:
                document = {**document, 'features': [
                    feature for feature in document['features']
                    if (feature['feature'] == 'agents') == (name == 'agents')
                ]}
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
    """Use the shared MCP dispatcher with this host's existing caller binding."""
    from agent_swarm.mcp import respond

    return respond(message, _tool_documents, _tool_call_response, SERVER_INFO)


def serve(input_stream: TextIO, output_stream: TextIO) -> None:
    """Use the same framing as independent MCP, preserving the public host seam."""
    from agent_swarm.mcp import serve as serve_stdio

    serve_stdio(input_stream, output_stream, _respond)


def main() -> None:
    """Run the MCP stdio server installed as the ``graphtraj-mcp`` command."""

    serve(sys.stdin, sys.stdout)


if __name__ == '__main__':
    main()
