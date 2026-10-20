"""Claude's single progressive MCP entry using shared stdio framing.

An external native host supplies its per-call binding through ``host.main``.
Managed callers continue using their existing authenticated gateway channel.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Callable, TextIO

from agent_swarm import AgentsError, AgentsResult
from agent_swarm.discovery import handle_request as discover_agents
from agent_swarm.mcp import error_response, respond, result_response, serve as serve_stdio, tool_documents
from graphtraj.execution.runner_models import RunnerError
from graphtraj.interfaces.gateway import handle_request, INPUT_SCHEMA
from graphtraj.interfaces.hosted_cli import agents_dispatch, forward_request
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


def serve(
    input_stream: TextIO,
    output_stream: TextIO,
    cwd: Path,
    native_call: Callable[[dict], AgentsResult] | None = None,
) -> None:
    """Expose one lightweight entry; the actual host retains caller authority."""
    def tasks(request: dict) -> AgentsResult:
        """Reuse Task authority through its existing hosted channel."""
        if request.get('feature') == 'agents':
            raise AgentsError('invalid-input', 'Use the agents entry for Agent controls.')
        answer = forward_request(request, cwd)
        answer = answer if answer is not None else handle_request(request, cwd=cwd)
        if request.get('action') == 'discover' and 'features' in answer.document:
            return AgentsResult({**answer.document, 'features': [item for item in answer.document['features']
                                if item['feature'] != 'agents']}, failed=answer.failed)
        return answer

    def descriptors() -> list[dict]:
        """Independent hosts expose agents; GraphTraj hosts also expose tasks."""
        return tool_documents() + ([] if native_call is not None else [{
            'name': 'tasks', 'description': 'Discover, describe, or execute Task features.',
            'inputSchema': INPUT_SCHEMA,
        }])

    def dispatch(request: dict) -> AgentsResult:
        """Use the already-bound gateway; never manufacture an anonymous Main."""
        return agents_dispatch(request, cwd)

    def call(identity: object, params: dict) -> dict:
        """Return shared discovery or execution without expanding the tool list."""
        if params.get('name') not in [item['name'] for item in descriptors()] or not isinstance(params.get('arguments', {}), dict):
            return error_response(identity, -32602, 'Expected agents and object arguments.')
        try:
            arguments = params.get('arguments', {})
            result = (tasks(arguments) if params['name'] == 'tasks' else
                      native_call(arguments) if native_call is not None else discover_agents(arguments, dispatch))
        except (AgentsError, RunnerError, RuntimeAdapterError) as error:
            result = AgentsResult({'error': {'code': error.code, 'message': error.message}}, failed=True)
        return result_response(identity, {
            'content': [{'type': 'text', 'text': json.dumps(result.document, ensure_ascii=False)}],
            'structuredContent': result.document, 'isError': result.failed,
        })

    serve_stdio(input_stream, output_stream, lambda message: respond(
        message, descriptors, call, {'name': 'agents', 'version': '1'}))


def main() -> None:
    """Serve only an existing host association, with no caller flags."""
    serve(sys.stdin, sys.stdout, Path.cwd())


if __name__ == '__main__':
    main()
