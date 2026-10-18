"""Shared stdio MCP framing and the independent authenticated agents client."""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable, Mapping, TextIO

from agent_swarm.connection import CONNECTION_ENV, call_owner, client_native_context
from agent_swarm.discovery import INPUT_SCHEMA
from agent_swarm.tool import AgentsError

PROTOCOL_VERSION = '2025-06-18'


def result_response(request_id: Any, result: Mapping) -> dict:
    """Wrap a successful MCP protocol response."""
    return {'jsonrpc': '2.0', 'id': request_id, 'result': result}


def error_response(request_id: Any, code: int, message: str) -> dict:
    """Wrap a protocol error without pretending it is a business result."""
    return {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': code, 'message': message}}


def respond(
    message: Mapping,
    tools: Callable[[], list[dict]],
    call: Callable[[Any, Mapping], dict],
    server_info: dict,
) -> dict | None:
    """Dispatch standard MCP methods; the host retains business authorization."""
    method = message.get('method')
    if not isinstance(method, str) or 'id' not in message:
        return None
    request_id = message['id']
    params = message.get('params')
    if not isinstance(params, dict):
        params = {}
    if method == 'initialize':
        requested = params.get('protocolVersion')
        return result_response(request_id, {
            'protocolVersion': requested if isinstance(requested, str) else PROTOCOL_VERSION,
            'capabilities': {'tools': {}}, 'serverInfo': server_info,
        })
    if method == 'tools/list':
        return result_response(request_id, {'tools': tools()})
    if method == 'tools/call':
        return call(request_id, params)
    if method == 'ping':
        return result_response(request_id, {})
    return error_response(request_id, -32601, f'Unsupported method: {method}')


def serve(input_stream: TextIO, output_stream: TextIO, responder: Callable[[Mapping], dict | None]) -> None:
    """Serve newline-delimited MCP JSON-RPC using the supplied host dispatcher."""
    for line in input_stream:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            reply = error_response(None, -32700, 'Parse error')
        else:
            reply = (responder(message) if isinstance(message, dict)
                     else error_response(None, -32600, 'Invalid request'))
        if reply is not None:
            output_stream.write(json.dumps(reply) + '\n')
            output_stream.flush()


def tool_documents() -> list[dict]:
    """Expose only the lightweight agents entry in a Task-free host."""
    return [{'name': 'agents', 'description': 'Discover, describe, or execute an Agent feature.',
             'inputSchema': INPUT_SCHEMA}]


def call(request_id: Any, params: Mapping) -> dict:
    """Forward over the owning Runtime's authenticated channel; never fall back."""
    if params.get('name') != 'agents':
        return error_response(request_id, -32602, f"Unknown tool: {params.get('name')}")
    request = params.get('arguments', {})
    if not isinstance(request, dict):
        return error_response(request_id, -32602, 'Tool arguments must be an object.')
    try:
        result = call_owner(request, metadata=params.get('_meta'))
        document, failed = result.document, result.failed
    except AgentsError as error:
        document = {'error': {'code': error.code, 'message': error.message}}
        failed = True
    return result_response(request_id, {'content': [{'type': 'text', 'text': json.dumps(document)}],
                                         'structuredContent': document, 'isError': failed})


def main() -> None:
    """Run one stdio MCP entry for the one host connection actually supplied."""
    if CONNECTION_ENV not in os.environ and 'GRAPHTRAJ_CLI_CONNECTION' in os.environ:
        # This is the existing authenticated Task host, not an independent
        # controller or a fallback after an independent channel fails.
        from graphtraj.interfaces.mcp import main as hosted_main

        native = client_native_context()
        if native is not None and native['runtime'] == 'dsh':
            os.environ['GRAPHTRAJ_NATIVE_RUNTIME'] = 'dsh'
        hosted_main()
        return
    serve(sys.stdin, sys.stdout, lambda message: respond(
        message, tool_documents, call, {'name': 'agents', 'version': '0.1.0'}))


if __name__ == '__main__':
    main()
