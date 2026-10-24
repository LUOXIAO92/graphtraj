"""Claude's single progressive MCP entry using shared stdio framing.

An external native host supplies its per-call binding through ``host.main``.
Managed callers continue using their existing authenticated gateway channel.
"""
from __future__ import annotations

import functools
import json
from pathlib import Path
import sys
import traceback
from typing import Callable, TextIO

import yaml

from agent_swarm import AgentsError, AgentsResult
from agent_swarm.discovery import handle_request as discover_agents
from agent_swarm.mcp import error_response, respond, result_response, serve as serve_stdio, tool_documents
from graphtraj.execution.runner_models import RunnerError
from graphtraj.interfaces.gateway import handle_request, INPUT_SCHEMA
from graphtraj.interfaces.hosted_cli import agents_dispatch, forward_request
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError, recovery_review


def serve(
    input_stream: TextIO,
    output_stream: TextIO,
    cwd: Path,
    native_call: Callable[..., AgentsResult] | None = None,
) -> None:
    """Expose the lightweight entries; the actual host retains caller authority.

    ``native_call(request, tool)`` serves both ``agents`` and ``tasks`` for a
    verified native Main host. Every review that host's call needs (recovery,
    role organization, retirement or replacement, Runtime connection save)
    asks Claude Code itself through MCP elicitation: its own dialog shows the
    exact change, and only its accept applies it in this same call.
    """
    capabilities: dict = {}

    def review(proposal: dict, call_id: object, feature: object) -> dict:
        """Wait for Claude Code's own accept, decline or cancel of this change."""
        from graphtraj.interfaces.mcp import elicit_review

        if not isinstance(capabilities.get('elicitation'), dict):
            raise RunnerError('native-approval-unavailable',
                              'This Claude Code client offers no MCP elicitation for approval.')
        return elicit_review(input_stream, output_stream, proposal, call_id, feature,
                             lambda result: result.get('content') in (None, {}))

    def tasks(request: dict) -> AgentsResult:
        """Reuse Task authority through the native host or its existing hosted channel."""
        if request.get('feature') == 'agents':
            raise AgentsError('invalid-input', 'Use the agents entry for Agent controls.')
        if native_call is not None:
            answer = native_call(request, 'tasks')
        else:
            answer = forward_request(request, cwd)
            answer = answer if answer is not None else handle_request(request, cwd=cwd)
        if request.get('action') == 'discover' and 'features' in answer.document:
            return AgentsResult({**answer.document, 'features': [item for item in answer.document['features']
                                if item['feature'] != 'agents']}, failed=answer.failed)
        return answer

    def descriptors() -> list[dict]:
        """Expose agents and the GraphTraj tasks entry."""
        return tool_documents() + [{
            'name': 'tasks', 'description': 'Discover, describe, or execute Task features.',
            'inputSchema': INPUT_SCHEMA,
        }]

    def dispatch(request: dict) -> AgentsResult:
        """Use the already-bound gateway; never manufacture an anonymous Main."""
        return agents_dispatch(request, cwd)

    def call(identity: object, params: dict) -> dict:
        """Return shared discovery or execution without expanding the tool list."""
        if params.get('name') not in [item['name'] for item in descriptors()] or not isinstance(params.get('arguments', {}), dict):
            return error_response(identity, -32602, 'Expected agents and object arguments.')
        try:
            arguments = params.get('arguments', {})
            # Only a verified native Main host's own call reaches this reviewer;
            # an operation without review never invokes it.
            reviewer = (functools.partial(review, call_id=identity, feature=arguments.get('feature'))
                        if native_call is not None else None)
            with recovery_review(reviewer):
                result = (tasks(arguments) if params['name'] == 'tasks' else
                          native_call(arguments) if native_call is not None else discover_agents(arguments, dispatch))
        except (AgentsError, RunnerError, RuntimeAdapterError) as error:
            result = AgentsResult({'error': {'code': error.code, 'message': error.message}}, failed=True)
        except (OSError, UnicodeError, ValueError, yaml.YAMLError) as error:
            # A rejected Task operation is a tool failure, as in graphtraj-mcp;
            # it must never end the host that serves this Main's later calls.
            result = AgentsResult({'error': {'code': 'operation-failed', 'message': str(error)}}, failed=True)
        except Exception as error:
            # Keep serving; the traceback goes to the host's own diagnostics.
            traceback.print_exc(file=sys.stderr)
            result = AgentsResult({'error': {'code': 'internal-error',
                                             'message': f'{type(error).__name__}: {error}'}}, failed=True)
        return result_response(identity, {
            'content': [{'type': 'text', 'text': json.dumps(result.document, ensure_ascii=False)}],
            'structuredContent': result.document, 'isError': result.failed,
        })

    def answer(message: dict) -> dict | None:
        """Keep the client's declared capabilities for its later review."""
        params = message.get('params')
        if message.get('method') == 'initialize' and isinstance(params, dict):
            capabilities.update(params.get('capabilities') or {})
        return respond(message, descriptors, call, {'name': 'agents', 'version': '1'})

    serve_stdio(input_stream, output_stream, answer)


def main() -> None:
    """Serve only an existing host association, with no caller flags."""
    serve(sys.stdin, sys.stdout, Path.cwd())


if __name__ == '__main__':
    main()
