"""Protocol-neutral discovery, help and execution over the shared tool registry."""

from __future__ import annotations

import sysconfig
from inspect import signature
from pathlib import Path
from typing import Any, Collection

from graftling import (ENVELOPE_SCHEMA as INPUT_SCHEMA, ValidationErrors, read_envelope_arguments, schema_errors,
                       validate_envelope, validate_schema as _validate)

from graphtraj.interfaces.tools import TOOLS, ToolResult


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


# GraphTraj's own records below a caller's directory; never readable as arguments.
PRIVATE_STATE = ".graphtraj"

ARGUMENTS_FILE_USAGE = (
    "execute also accepts arguments_file instead of or beside arguments: the path of a UTF-8 JSON "
    "file holding the arguments object (at most 1 MiB), inside your workspace (the project for Main, "
    "your Worktree for a member; a relative path starts there) and outside .graphtraj. Inline "
    "arguments replace the file's top-level fields. Every input problem is returned at once as "
    "error.errors [{path, reason}]; fix the file and call again."
)


def invalid_input(errors: list[dict[str, str]], **document: Any) -> ToolResult:
    """Return every input problem in one failed result.

    The ``error`` is ``{"code": "invalid-input", "message", "errors"}``, where
    ``errors`` lists each ``{"path", "reason"}`` and ``message`` joins them.
    """
    return ToolResult({**document, "error": {
        "code": "invalid-input", "message": str(ValidationErrors(errors)), "errors": errors,
    }}, failed=True)


def read_arguments_file(request: Any, files: Path) -> Any:
    """Return the request with its ``arguments_file`` read into ``arguments``.

    ``files`` is the trusted directory this caller may read: the serving
    process's own workspace (the project for Main, a member's Worktree). The
    file follows graftling's rules (inside ``files`` after links are
    followed, a regular UTF-8 JSON object of at most 1 MiB; inline
    ``arguments`` replace its top-level fields), and may not lie in GraphTraj's
    private ``.graphtraj`` records below ``files``. A request without a file is
    returned unchanged, so later hosts and the gateway see inline arguments only.

    Raises
    ------
    ValidationErrors
        The envelope's problems, or one ``request.arguments_file`` problem.
    """
    if not isinstance(request, dict) or "arguments_file" not in request:
        return request
    validate_envelope(request, files=files)

    # Refuse private records before graftling opens anything there.
    named = request["arguments_file"]
    root  = files.resolve()
    path  = (root / named).resolve()
    if path.is_relative_to(root) and PRIVATE_STATE in path.relative_to(root).parts:
        raise ValidationErrors([{"path": "request.arguments_file",
                                 "reason": f"{named} is in GraphTraj private state ({PRIVATE_STATE})"}])

    arguments = read_envelope_arguments(request, files)
    request   = {key: value for key, value in request.items() if key != "arguments_file"}
    return {**request, "arguments": arguments}


def argument_errors(feature: str, arguments: Any) -> list[dict[str, str]]:
    """Return every schema and feature-level problem of one feature's arguments."""
    tool = TOOLS[feature]
    errors = schema_errors(arguments, tool.input_schema, "arguments")
    return errors + (tool.check(arguments) if tool.check is not None else [])


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
    reading material. An ``arguments_file`` is read by the serving entry
    (:func:`read_arguments_file`), so here it is refused. Every envelope,
    schema and feature-level input problem is returned at once (556). Execution needs no
    prior help request or material. Handlers accepting ``cwd`` receive it; older
    ambient-directory handlers keep their existing calling convention. Business
    exceptions remain host-owned.
    """
    try:
        action = validate_envelope(request)
    except ValidationErrors as error:
        return invalid_input(error.errors)

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
            "arguments_file": ARGUMENTS_FILE_USAGE,
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
    # Schema and feature-level problems come back together; the controller
    # check and the handler's authorization run only on valid arguments.
    errors = argument_errors(feature, request["arguments"])
    if errors:
        return invalid_input(errors, feature=feature)

    # One shared single-Main-controller check for every CLI/MCP host.
    from graphtraj.execution.main_continuity import require_feature_control

    require_feature_control(feature, cwd)
    if "cwd" in signature(tool.handler).parameters:
        return tool.handler(request["arguments"], cwd=cwd)
    return tool.handler(request["arguments"])
