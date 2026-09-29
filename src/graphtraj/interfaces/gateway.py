"""Protocol-neutral discovery, help and execution over the shared tool registry."""

from __future__ import annotations

from inspect import signature
from pathlib import Path
from typing import Any, Collection, Mapping

from graphtraj.interfaces.tools import TOOLS, ToolResult


INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["discover", "describe", "execute"]},
        "query": {"type": "string"},
        "feature": {"type": "string"},
        "arguments": {"type": "object"},
    },
    "required": ["action"],
    "additionalProperties": False,
}


def _validate(value: Any, schema: Mapping[str, Any], path: str) -> None:
    """Validate the JSON Schema vocabulary used by registered operations.

    Unsupported constraints fail closed rather than silently weakening a newly
    registered operation. Errors identify one local field, never dump schemas.
    """
    supported = {
        "type", "properties", "required", "additionalProperties", "items",
        "enum", "const", "minItems", "description", "title", "default",
        "examples", "$schema", "$comment",
    }
    if set(schema) - supported:
        raise ValueError(f"{path}: unsupported schema constraint")

    checks = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "null": value is None,
    }
    expected = schema.get("type", [])
    types = [expected] if isinstance(expected, str) else expected
    if types and not any(checks.get(kind, False) for kind in types):
        raise ValueError(f"{path}: expected {' or '.join(types)}")

    # JSON booleans are distinct from numbers, unlike Python's True == 1.
    def equal(choice: Any) -> bool:
        """Compare the scalar enum/const values used by this registry."""
        return value == choice and isinstance(value, bool) == isinstance(choice, bool)

    if "const" in schema and not equal(schema["const"]):
        raise ValueError(f"{path}: expected {schema['const']!r}")
    if "enum" in schema and not any(equal(choice) for choice in schema["enum"]):
        raise ValueError(f"{path}: expected one of {schema['enum']!r}")

    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                raise ValueError(f"{path}.{name}: required")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for name, item in value.items():
            if name in properties:
                _validate(item, properties[name], f"{path}.{name}")
            elif additional is False:
                raise ValueError(f"{path}.{name}: unexpected parameter")
            elif isinstance(additional, dict):
                _validate(item, additional, f"{path}.{name}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ValueError(f"{path}: expected at least {schema['minItems']} items")
        for index, item in enumerate(value):
            _validate(item, schema.get("items", {}), f"{path}[{index}]")


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

    Manual references are local UTF-8 paths, absolute or relative to ``cwd``.
    Only describe reads them. Execution needs no prior help request or material.
    Handlers accepting ``cwd`` receive it; older ambient-directory handlers keep
    their existing calling convention. Business exceptions remain host-owned.
    """
    try:
        _validate(request, INPUT_SCHEMA, "request")
        action = request["action"]
        fields = {"action", "query"} if action == "discover" else {"action", "feature"}
        if action == "execute":
            fields.add("arguments")
        for name in request.keys() - fields:
            raise ValueError(f"request.{name}: not valid for {action}")
        if action != "discover" and "feature" not in request:
            raise ValueError("request.feature: required")
        if action == "execute" and "arguments" not in request:
            raise ValueError("request.arguments: required")
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
        document = {
            "feature": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
            "examples": list(tool.examples),
            "manual_ref": tool.manual_ref,
            "manual": None,
            "call": {"action": "execute", "feature": tool.name, "arguments": {}}
            if tool.handler is not None else None,
        }
        if tool.manual_ref is None:
            document["error"] = f"No manual reference for feature: {feature}"
        else:
            try:
                document["manual"] = ((cwd or Path.cwd()) / tool.manual_ref).read_text(
                    encoding="utf-8"
                )
            except (OSError, UnicodeError) as error:
                document["error"] = f"Cannot read manual {tool.manual_ref}: {error}"
        return ToolResult(document, failed="error" in document)

    if tool.handler is None:
        return ToolResult({"error": f"Feature is not executable: {feature}"}, failed=True)
    try:
        _validate(request["arguments"], tool.input_schema, "arguments")
    except ValueError as error:
        return ToolResult({"feature": feature, "error": str(error)}, failed=True)

    if "cwd" in signature(tool.handler).parameters:
        return tool.handler(request["arguments"], cwd=cwd)
    return tool.handler(request["arguments"])
