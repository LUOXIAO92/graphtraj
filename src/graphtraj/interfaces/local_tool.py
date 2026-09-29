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
) -> Callable[[Mapping[str, Any]], ToolResult]:
    """Return the tool callback bound to one trusted host launch context.

    The returned callable takes the model-supplied request object only. ``cwd``
    and ``allowed_features`` come from the host, never from the request.
    """
    return partial(gateway.handle_request, cwd=cwd, allowed_features=allowed_features)


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
        result = gateway.handle_request(
            request, cwd=cwd, allowed_features=allowed_features
        )
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
    parser.add_argument(
        "--allowed-features",
        help="Comma-separated feature names this host exposes; default exposes all.",
    )
    options = parser.parse_args()
    allowed = tuple(name for name in (options.allowed_features or "").split(",") if name)

    serve(
        sys.stdin,
        sys.stdout,
        cwd=Path.cwd(),
        allowed_features=allowed or None,
    )
