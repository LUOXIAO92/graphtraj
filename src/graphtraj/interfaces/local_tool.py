"""Independent local GraphTraj tool binding and a thin structured stdio bridge.

A host registers one ``graphtraj`` custom tool from :func:`tool_descriptor` and
binds :func:`bind` to its own launch context: the working directory and, when
chosen, the feature names it exposes. A host that needs a process boundary
starts the ``graphtraj-tool`` command instead and exchanges newline-delimited
JSON over stdin/stdout. Both paths forward the model-supplied request object to
the shared gateway, so descriptions, schemas and behavior stay single-sourced
and no MCP server or protocol is involved.

Trusted context never travels in the request or on the wire. Identity comes
from the host launch boundary the same way it does for the CLI and the MCP
entry: the process working directory, the launch option, and whatever caller
binding the business handler already uses. A request that tries to carry
identity fields is rejected by the shared schema.
"""

from __future__ import annotations

import argparse
import json
import sys
from functools import partial
from pathlib import Path
from typing import Any, Callable, Collection, Mapping, TextIO

from graphtraj.execution.runner_connection import parent_connection, worker_connection
from graphtraj.execution.runner_models import RunnerError
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError
from graphtraj.workspace.runner_project import discover_runner_directory
from graphtraj.interfaces import gateway
from graphtraj.interfaces.tools import ToolResult


TOOL_NAME = "graphtraj"

TOOL_DESCRIPTION = (
    "Discover, describe and execute GraphTraj operations for the project in the "
    "host's working directory. Send action discover, describe or execute with "
    "the request fields the shared tool schema defines."
)


def tool_descriptor() -> dict[str, Any]:
    """Return the single custom-tool descriptor a local host registers.

    The descriptor reuses ``gateway.INPUT_SCHEMA`` by reference, so a change to
    the shared request schema changes every host that registers this tool.
    """
    return {
        "name":         TOOL_NAME,
        "description":  TOOL_DESCRIPTION,
        "input_schema": gateway.INPUT_SCHEMA,
    }


def bind(
    cwd: Path | None = None,
    allowed_features: Collection[str] | None = None,
    *,
    event_receiver: Callable[[dict[str, str]], None] | None = None,
    recovery_reviewer: Callable[[dict], dict] | None = None,
    desktop_observer: bool = False,
) -> Callable[[Mapping[str, Any]], ToolResult]:
    """Return the tool callback bound to one trusted host launch context.

    The returned callable takes the model-supplied request object only. ``cwd``
    and ``allowed_features`` come from the host, never from the request.
    With ``event_receiver``, the returned HostTool retains the host callback
    across tool calls until explicitly closed. The callback uses the host's
    existing client; its return acknowledges forwarding, not Agent processing.
    ``desktop_observer`` selects the read-only human activity surface and cannot
    be combined with Agent event/control callbacks; verified Agents retain self-only access.
    ``recovery_reviewer`` must invoke that host's actual selected reviewer and
    return its accept/decline decision; it is never a model-supplied argument.
    """
    if desktop_observer:
        if event_receiver is not None or recovery_reviewer is not None:
            raise ValueError('The desktop observer cannot bind Agent control callbacks.')

        def observe(request: Mapping[str, Any]) -> ToolResult:
            """Bind read-only human access outside native Agent tool callbacks."""
            from graphtraj.execution.desktop_activity import human_observer

            token = human_observer.set(True)
            try:
                allowed = ('desktop_activity',) if allowed_features is None or 'desktop_activity' in allowed_features else ()
                return gateway.handle_request(request, cwd=cwd, allowed_features=allowed)
            finally:
                human_observer.reset(token)

        return observe
    if event_receiver is not None:
        return HostTool(cwd or Path.cwd(), allowed_features, event_receiver, recovery_reviewer)
    callback = partial(gateway.handle_request, cwd=cwd, allowed_features=allowed_features)
    if recovery_reviewer is None:
        return callback

    def review_bound(request: Mapping[str, Any]) -> ToolResult:
        """Use the host's actual reviewer without exposing a model approval flag."""
        from graphtraj.runtimes.runtime_adapter import recovery_review

        with recovery_review(recovery_reviewer):
            return callback(request)

    return review_bound


class HostTool:
    """Keep an owning host's event receiver alive across individual tool returns.

    The host forwards events using its already-owned Session/client, and closes
    this binding only when it stops receiving child events. No Session, model,
    permission or caller identity is created here. Use as a context manager or
    call ``close``; asynchronous hosts should close off their client event loop.
    """

    def __init__(
        self,
        cwd: Path,
        allowed_features: Collection[str] | None,
        receiver: Callable[[dict[str, str]], None],
        recovery_reviewer: Callable[[dict], dict] | None = None,
    ) -> None:
        """Open the existing private control transport for this trusted callback."""
        self.cwd = cwd
        self.recovery_reviewer = recovery_reviewer
        self.allowed_features = allowed_features
        self.closed = False
        directory = discover_runner_directory(cwd)
        directory.mkdir(parents=True, exist_ok=True)

        def receive(message: dict) -> dict:
            """Forward only a four-field event; failures remain retryable by its producer."""
            if (set(message) != {'source', 'alias', 'event', 'message'}
                    or message['source'] != 'graphtraj'
                    or any(not isinstance(value, str) or not value for value in message.values())):
                raise ValueError('Invalid parent event')
            try:
                receiver(message)
            except Exception as error:
                raise RuntimeAdapterError('operation-failed', str(error)) from error
            return {}

        self.connection = worker_connection(directory, receive)
        self.address = self.connection.__enter__()

    def __call__(self, request: Mapping[str, Any]) -> ToolResult:
        """Run one ordinary tool request without shortening the receiver lifetime."""
        if self.closed:
            raise RunnerError('operation-failed', 'The owning host event binding is closed.')
        from graphtraj.runtimes.runtime_adapter import recovery_review

        with parent_connection(self.address), recovery_review(self.recovery_reviewer):
            return gateway.handle_request(request, cwd=self.cwd, allowed_features=self.allowed_features)

    def close(self) -> None:
        """Release this host connection; later delivery must report a failure."""
        if not self.closed:
            self.closed = True
            self.connection.__exit__(None, None, None)

    def __enter__(self) -> HostTool:
        """Retain this binding until its owning host leaves the scope."""
        return self

    def __exit__(self, *exception: object) -> None:
        """Close without suppressing host exceptions."""
        self.close()


def answer(
    request: Any,
    *,
    cwd: Path | None = None,
    allowed_features: Collection[str] | None = None,
    desktop_observer: bool = False,
) -> dict[str, Any]:
    """Answer one decoded request with the bridge's structured wire document.

    A validation or business rejection is a normal answer and keeps the loop
    serving later requests. The wire document is either
    ``{"failed": false, "result": {...}}`` or ``{"failed": true, "error": "..."}``.
    """
    if not isinstance(request, dict):
        return {"failed": True, "error": "Invalid request"}
    try:
        from graphtraj.interfaces.hosted_cli import forward_request

        result = None
        if request.get('action') == 'execute' and (
            allowed_features is None or request.get('feature') in allowed_features
        ):
            result = forward_request(request, cwd or Path.cwd())
        if result is None:
            result = bind(cwd, allowed_features, desktop_observer=desktop_observer)(request)
    except Exception as error:
        # Business rejections stay host-owned; the bridge reports them instead
        # of ending the session, so a call after a rejection still works.
        return {"failed": True, "error": str(error)}
    return {"failed": result.failed, "result": result.document}


def serve(
    input_stream: TextIO,
    output_stream: TextIO,
    *,
    cwd: Path | None = None,
    allowed_features: Collection[str] | None = None,
    desktop_observer: bool = False,
) -> None:
    """Answer newline-delimited requests until the host closes input.

    The whole line is the shared request object; the working directory and any
    feature restriction come from this launch boundary. A blank, unparseable or
    invalid line is answered and does not stop later requests.
    """
    for line in input_stream:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            reply = {"failed": True, "error": "Parse error"}
        else:
            reply = answer(request, cwd=cwd, allowed_features=allowed_features, desktop_observer=desktop_observer)
        output_stream.write(json.dumps(reply) + "\n")
        output_stream.flush()


def main() -> None:
    """Run the stdio bridge installed as the ``graphtraj-tool`` command.

    The process working directory is the host's project location. The optional
    ``--allowed-features`` launch option restricts the features this host
    exposes; it is not read from the request.
    """
    parser = argparse.ArgumentParser(prog="graphtraj-tool", description=TOOL_DESCRIPTION)
    boundary = parser.add_mutually_exclusive_group()
    boundary.add_argument(
        "--desktop-settings", action="store_true",
        help="Serve one human desktop settings read/save with native host review over the owned pipe.",
    )
    boundary.add_argument(
        "--allowed-features",
        help="Comma-separated feature names this host exposes; default exposes all.",
    )
    parser.add_argument(
        "--desktop-observer", action="store_true",
        help="Bind the read-only activity observer; verified Agents retain self-only access.",
    )
    options = parser.parse_args()
    if options.desktop_settings:
        from graphtraj.interfaces.desktop_settings import serve as serve_settings

        serve_settings(sys.stdin, sys.stdout, Path.cwd())
        return
    allowed = tuple(name for name in (options.allowed_features or "").split(",") if name)

    serve(
        sys.stdin,
        sys.stdout,
        cwd=Path.cwd(),
        allowed_features=allowed or None,
        desktop_observer=options.desktop_observer,
    )
