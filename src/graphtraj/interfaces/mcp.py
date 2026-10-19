"""Host-callable GraphTraj operations over MCP stdio JSON-RPC.

The installed ``graphtraj-mcp`` entry point answers the MCP methods a host
needs to discover and run tools: ``initialize``, ``notifications/initialized``,
``tools/list``, ``tools/call`` and ``ping``. Only ``agents`` and ``tasks`` are
published, with individual feature schemas disclosed on demand.

The server speaks newline-delimited JSON-RPC 2.0 over stdin/stdout and uses
only the standard library, so no MCP SDK dependency is required. It reads the
Harness Project Root from its own working directory, exactly like the CLI.
"""

from __future__ import annotations

import os
import sys
import hashlib
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, TextIO

import yaml

from agent_swarm.mcp import error_response as _error_response, result_response as _result_response

from graphtraj.configuration.project_configuration import ProjectConfigurationError
from graphtraj.execution.execution_budget import budget_notice_output, caller_notice_fd
from graphtraj.execution.runner_models import RunnerError
from graphtraj.interfaces import gateway
from graphtraj.runtimes.codex.app_server import CodexMainRecovery
from graphtraj.runtimes.codex.codex_adapter import CodexAdapterError


SERVER_INFO      = {"name": "graphtraj", "version": "0.1.0"}
_SERVICE = {'executable': sys.executable, 'module': __file__,
            'sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}

INVALID_PARAMS   = -32602


def _tool_documents() -> list[dict[str, Any]]:
    """Publish the two lightweight entries on every supported host."""
    return [
        {'name': name, 'description': f'Discover, describe, or execute {name} features.',
         'inputSchema': gateway.INPUT_SCHEMA}
        for name in ('agents', 'tasks')
    ]


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

    if 'GRAPHTRAJ_CLI_CONNECTION' in os.environ:
        # The authenticated owner already routes its native notices/approvals.
        yield None
        return
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
    if name not in ('agents', 'tasks'):
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
        if name == 'tasks' and arguments.get('action') != 'discover':
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
                from agent_swarm.connection import client_native_context

                result = forward_request(request, Path.cwd(), native_context=client_native_context(metadata))
                return result if result is not None else gateway.handle_request(request, cwd=Path.cwd())

            if name == 'agents':
                from agent_swarm.discovery import handle_request

                result = handle_request(arguments, lambda request: dispatch({
                    'action': 'execute', 'feature': 'agents', 'arguments': request,
                }))
            else:
                result = dispatch(arguments)
                if arguments.get('action') == 'discover' and not result.failed:
                    result.document['features'] = [item for item in result.document.get('features', [])
                                                   if item['feature'] != 'agents']
                    # Capture in the serving process, not from a caller's CLI
                    # installation. A forwarded host supplies its own stamp.
                    result.document.setdefault('service', {})['mcp'] = _SERVICE
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
                {"type": "text", "text": yaml.safe_dump(document, sort_keys=False, allow_unicode=True)}
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
    from agent_swarm.connection import client_native_context

    if 'GRAPHTRAJ_CLI_CONNECTION' in os.environ:
        # A DSH host names its native Session only through its own environment;
        # the hosted CLI binding checks that Session against this channel.
        native = client_native_context()
        if native is not None and native['runtime'] == 'dsh':
            os.environ['GRAPHTRAJ_NATIVE_RUNTIME'] = 'dsh'
    serve(sys.stdin, sys.stdout)


if __name__ == '__main__':
    main()
