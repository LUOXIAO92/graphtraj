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
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Collection, Mapping, TextIO

from graphtraj.execution.runner_connection import parent_connection, worker_connection
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import (
    caller_alias, runtime_caller, require_execution_allowed, read_alias_mapping,
)
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
) -> Callable[[Mapping[str, Any]], ToolResult]:
    """Return the tool callback bound to one trusted host launch context.

    The returned callable takes the model-supplied request object only. ``cwd``
    and ``allowed_features`` come from the host, never from the request.
    With ``event_receiver``, the returned HostTool retains the host callback
    across tool calls until explicitly closed. The callback uses the host's
    existing client; its return acknowledges forwarding, not Agent processing.
    ``recovery_reviewer`` must invoke that host's actual selected reviewer and
    return its accept/decline decision; it is never a model-supplied argument.
    """
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
    this binding only when it stops receiving child events. ``adopt_main``
    registers the existing host after user authorization; it launches no native
    Session and changes no model or permission settings. Use as a context manager
    or call ``close`` off an asynchronous host's client event loop.
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
        self.alias = None
        self.owner = None
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

        runner = discover_runner_directory(self.cwd)
        if self.alias:
            mapping, _ = read_alias_mapping(runner, self.alias)
            require_execution_allowed(runner, self.alias, mapping)
        with parent_connection(self.address), recovery_review(self.recovery_reviewer):
            if self.alias:
                with runtime_caller(runner, self.alias):
                    return gateway.handle_request(request, cwd=self.cwd, allowed_features=self.allowed_features)
            with runtime_caller(runner, 'unregistered'):
                return gateway.handle_request(request, cwd=self.cwd, allowed_features=self.allowed_features)

    def adopt_main(
        self, runtime: str, *, resume: str | None = None, replaces: str | None = None,
    ) -> str:
        """Bind this existing host after its owning user approves the exact adoption.

        Called by the host integration, never exposed as a model request. The
        host must supply its actual native reviewer when constructing this tool.
        """
        from graphtraj.execution.agent_identity import adopt_host_agent

        if self.closed or self.alias is not None or self.recovery_reviewer is None:
            raise RunnerError('authority-denied', 'An unbound owning host and native approval are required.')
        mapping, self.owner = adopt_host_agent(
            self.cwd, runtime, self.recovery_reviewer, resume=resume, replaces=replaces,
        )
        self.alias = mapping['alias']
        try:
            self._record_connection()
        except BaseException:
            self.close()
            raise
        return self.alias

    def register_checker(
        self, receiver: Callable[[dict], None], *, resume: str | None = None, replaces: str | None = None,
    ) -> HostTool:
        """Register a fresh checker before its Adapter starts using the callback."""
        from graphtraj.execution.agent_identity import adopt_host_agent

        if self.closed or not self.alias:
            raise RunnerError('authority-denied', 'The parent host is not bound.')
        runner = discover_runner_directory(self.cwd)
        parent, _ = read_alias_mapping(runner, self.alias)
        child = HostTool(self.cwd, self.allowed_features, receiver, self.recovery_reviewer)
        try:
            mapping, child.owner = adopt_host_agent(
                self.cwd, parent['runtime'], lambda proposal: {'decision': 'accept'}, parent=self.alias,
                resume=resume, replaces=replaces,
            )
            child.alias = mapping['alias']
            child._record_connection()
            return child
        except BaseException:
            child.close()
            raise

    def _record_connection(self) -> None:
        """Keep the current receiver on the existing Agent mapping for child notices."""
        from graphtraj.execution.runner_io import write_yaml_durably

        runner = discover_runner_directory(self.cwd)
        mapping, directory = read_alias_mapping(runner, self.alias)
        write_yaml_durably(directory / 'mapping.yml', {**mapping, 'host_connection': self.address})

    @contextmanager
    def cli_channel(self, authenticate: Callable[[int], None]):
        """Expose this binding to CLI processes verified by the owning host.

        The host must verify each kernel-observed writer against this Agent's
        isolated execution, including when several Agents share a host process.
        An environment address alone never supplies caller authority.
        """
        from graphtraj.interfaces.hosted_cli import cli_connection
        from graphtraj.interfaces.tools import TOOLS

        if self.closed or not self.alias:
            raise RunnerError('authority-denied', 'The host has no registered Agent.')
        with cli_connection(self.cwd, self.alias, TOOLS if self.allowed_features is None else self.allowed_features,
                            self.recovery_reviewer, authenticate=authenticate) as address:
            yield address

    def close(self) -> None:
        """Release this host connection; later delivery must report a failure."""
        if not self.closed:
            self.closed = True
            try:
                self.connection.__exit__(None, None, None)
            finally:
                if self.owner is not None:
                    self.owner.close()

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
            if request.get('action') == 'execute':
                runner = discover_runner_directory(cwd or Path.cwd())
                with runtime_caller(runner, caller_alias(runner) or 'unregistered'):
                    result = gateway.handle_request(request, cwd=cwd, allowed_features=allowed_features)
            else:
                result = gateway.handle_request(request, cwd=cwd, allowed_features=allowed_features)
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
            reply = answer(request, cwd=cwd, allowed_features=allowed_features)
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
    )
