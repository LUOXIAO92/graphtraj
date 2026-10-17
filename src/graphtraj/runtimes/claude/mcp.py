"""Claude stdio registration of agents over the existing verified gateway.

Run with ``python -m graphtraj.runtimes.claude.mcp`` and name the MCP server
``agents``. Registration does not grant authority: every call still requires
the gateway's native callback/process association. In particular, a startup
CLAUDE_CODE_SESSION_ID is not accepted as proof of the current Main Session.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import TextIO

from agent_swarm import tool_descriptor
from graphtraj.execution.runner_models import RunnerError
from graphtraj.interfaces.gateway import handle_request
from graphtraj.interfaces.hosted_cli import forward_request
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


def serve(input_stream: TextIO, output_stream: TextIO, cwd: Path) -> None:
    """Register the real function and route calls through existing authorization.

    The host chooses cwd; model arguments cannot select it or their identity.
    A failed associated channel never falls back to an anonymous root caller.
    """
    for line in input_stream:
        if not line.strip():
            continue
        identity = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError('Expected a JSON-RPC object.')
            identity = request.get('id')
            if 'id' not in request:
                continue
            params = request.get('params', {})
            if not isinstance(params, dict):
                raise ValueError('Expected object parameters.')
            method = request.get('method')
            if method == 'initialize':
                result = {'protocolVersion': params.get('protocolVersion', '2025-06-18'),
                          'capabilities': {'tools': {}},
                          'serverInfo': {'name': 'agents', 'version': '1'}}
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                descriptor = tool_descriptor()
                result = {'tools': [{'name': descriptor['name'], 'description': descriptor['description'],
                                    'inputSchema': descriptor['input_schema']}]}
            elif method == 'tools/call':
                if params.get('name') != 'agents' or not isinstance(params.get('arguments', {}), dict):
                    raise ValueError('Expected the agents tool and object arguments.')
                envelope = {'action': 'execute', 'feature': 'agents', 'arguments': params.get('arguments', {})}
                try:
                    answer = forward_request(envelope, cwd)
                    if answer is None:
                        answer = handle_request(envelope, cwd=cwd)
                    result = {'content': [{'type': 'text', 'text': json.dumps(answer.document, ensure_ascii=False)}],
                              'structuredContent': answer.document, 'isError': answer.failed}
                except (RunnerError, RuntimeAdapterError) as error:
                    document = {'action': params.get('arguments', {}).get('action'),
                                'error': {'code': error.code, 'message': error.message}}
                    result = {'content': [{'type': 'text', 'text': json.dumps(document)}],
                              'structuredContent': document, 'isError': True}
            else:
                reply = {'jsonrpc': '2.0', 'id': identity,
                         'error': {'code': -32601, 'message': 'Unsupported MCP method.'}}
                output_stream.write(json.dumps(reply) + '\n')
                output_stream.flush()
                continue
            reply = {'jsonrpc': '2.0', 'id': identity, 'result': result}
        except json.JSONDecodeError:
            reply = {'jsonrpc': '2.0', 'id': None,
                     'error': {'code': -32700, 'message': 'Invalid JSON.'}}
        except (ValueError, TypeError):
            reply = {'jsonrpc': '2.0', 'id': identity,
                     'error': {'code': -32602, 'message': 'Invalid MCP request.'}}
        output_stream.write(json.dumps(reply, ensure_ascii=False) + '\n')
        output_stream.flush()


def main() -> None:
    """Serve the configured native stdio pipe without accepting caller flags."""
    serve(sys.stdin, sys.stdout, Path.cwd())


if __name__ == '__main__':
    main()
