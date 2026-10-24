"""Protocol-neutral discovery, help and execution over the shared tool registry."""

from __future__ import annotations

import sysconfig
from inspect import signature
from pathlib import Path
from typing import Any, Collection

from agent_swarm.schema import validate as _validate

from graphtraj.interfaces.tools import TOOLS, ToolResult


from agent_swarm.discovery import INPUT_SCHEMA, validate_envelope


def delivered_manuals_root() -> Path:
    """Return the installed directory that carries the delivered method guides.

    The distribution installs ``manuals/**/*.md`` under ``share/graphtraj`` in
    the installation prefix, outside Skill discovery and outside the importable
    package. A relative ``manual_ref`` resolves here, so an installed tool finds
    the guides from any process working directory.
    """
    return Path(sysconfig.get_path("data")) / "share" / "graphtraj"


def _manual_path(reference: str) -> Path:
    """Resolve one manual reference to an absolute file path.

    An absolute reference is used as given. A relative reference names a
    delivered file below :func:`delivered_manuals_root`; it is never guessed
    from the process working directory.
    """
    path = Path(reference)
    return path if path.is_absolute() else delivered_manuals_root() / path


def handle_request(
    request: dict[str, Any],
    *,
    cwd: Path | None = None,
    allowed_features: Collection[str] | None = None,
) -> ToolResult:
    """Discover, describe or execute one registered feature.

    ``cwd`` and ``allowed_features`` are trusted host inputs, never model
    arguments. Hosts retain their existing caller and notification bindings;
    business handlers retain authorization. A host can restrict its exposed
    features with ``allowed_features`` without creating another registry.

    Manual references are local UTF-8 paths. An absolute reference is read as
    given; a relative one resolves to the distribution's delivered data
    location, never to ``cwd``. Default describe checks and returns the readable
    reference; ``schema=true`` returns only the selected input schema without
    reading material. Execution needs no
    prior help request or material. Handlers accepting ``cwd`` receive it; older
    ambient-directory handlers keep their existing calling convention. Business
    exceptions remain host-owned.
    """
    try:
        action = validate_envelope(request)
    except ValueError as error:
        return ToolResult({"error": str(error)}, failed=True)

    if action == "discover":
        terms = request.get("query", "").casefold().split()
        features = [
            {"feature": tool.name, "description": tool.description}
            for tool in TOOLS.values()
            if (allowed_features is None or tool.name in allowed_features)
            and all(term in f"{tool.name} {tool.description}".casefold() for term in terms)
        ]
        return ToolResult({
            "features": features,
            "describe": {"action": "describe", "feature": "<feature>"},
        })

    feature = request["feature"]
    tool = TOOLS.get(feature)
    if tool is None or (allowed_features is not None and feature not in allowed_features):
        return ToolResult({"error": f"Unknown feature: {feature}"}, failed=True)

    if action == "describe":
        if request.get("schema", False):
            return ToolResult({"input_schema": tool.input_schema})
        document = {
            "feature": tool.name,
            "description": tool.description,
        }
        if tool.manual_ref is None:
            document["error"] = f"No manual reference for feature: {feature}"
        else:
            try:
                path = _manual_path(tool.manual_ref).resolve()
                path.read_text(encoding="utf-8")
                document["manual_ref"] = str(path)
            except (OSError, UnicodeError) as error:
                document["error"] = f"Cannot read manual {tool.manual_ref}: {error}"
        return ToolResult(document, failed="error" in document)

    if tool.handler is None:
        return ToolResult({"error": f"Feature is not executable: {feature}"}, failed=True)
    try:
        _validate(request["arguments"], tool.input_schema, "arguments")
    except ValueError as error:
        return ToolResult({"feature": feature, "error": str(error)}, failed=True)

    # One shared single-Main-controller check for every CLI/MCP host.
    from graphtraj.execution.main_continuity import require_feature_control

    require_feature_control(feature, cwd)
    if "cwd" in signature(tool.handler).parameters:
        return tool.handler(request["arguments"], cwd=cwd)
    return tool.handler(request["arguments"])
