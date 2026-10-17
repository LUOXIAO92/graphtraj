"""Small JSON Schema validator shared by registered tool descriptions.

Only the vocabulary used by the registered schemas is supported, so an
unsupported constraint fails closed instead of silently weakening a schema.
"""

from __future__ import annotations

from typing import Any, Mapping


def validate(value: Any, schema: Mapping[str, Any], path: str) -> None:
    """Validate ``value`` against the supported JSON Schema vocabulary.

    Parameters
    ----------
    value
        Decoded JSON value supplied by a model or host.
    schema
        Schema using only ``type``, ``properties``, ``required``,
        ``additionalProperties``, ``items``, ``enum``, ``const``, ``minItems``,
        ``anyOf`` and annotation keywords.
    path
        Dotted location used in error messages, for example ``"request"``.

    Raises
    ------
    ValueError
        Naming one local field; schemas are never dumped into the message.
    """
    supported = {
        "type", "properties", "required", "additionalProperties", "items",
        "enum", "const", "minItems", "description", "title", "default",
        "examples", "$schema", "$comment", "anyOf",
    }
    if set(schema) - supported:
        raise ValueError(f"{path}: unsupported schema constraint")

    if "anyOf" in schema:
        errors = []
        for alternative in schema["anyOf"]:
            try:
                validate(value, alternative, path)
                break
            except ValueError as error:
                errors.append(str(error))
        else:
            raise ValueError(f"{path}: incompatible definition; " + "; ".join(errors))

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
        """Compare the scalar enum/const values used by registered schemas."""
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
                validate(item, properties[name], f"{path}.{name}")
            elif additional is False:
                raise ValueError(f"{path}.{name}: unexpected parameter")
            elif isinstance(additional, dict):
                validate(item, additional, f"{path}.{name}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ValueError(f"{path}: expected at least {schema['minItems']} items")
        for index, item in enumerate(value):
            validate(item, schema.get("items", {}), f"{path}[{index}]")
