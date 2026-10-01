"""Project shared operation material and constraints onto existing Click forms."""

from __future__ import annotations

from copy import copy
import json
from typing import Any

import click
import yaml

from graphtraj.interfaces.gateway import _validate, handle_request
from graphtraj.interfaces.tools import TOOLS, ToolResult


def invoke_tool(feature: str, arguments: dict[str, Any], **context: Any) -> ToolResult:
    """Validate decoded CLI arguments before invoking the existing business handler.

    Host-only inputs (Main transport and retained swarm files) remain outside
    the schema. Missing manual material never prevents execution.
    """
    if feature == "swarm" and "input_file" in context:
        try:
            arguments = yaml.safe_load(context["input_file"].read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as error:
            raise click.BadParameter(str(error), param_hint="--swarm-input") from error
    try:
        _validate(arguments, TOOLS[feature].input_schema, "arguments")
    except ValueError as error:
        raise click.UsageError(str(error)) from error
    return TOOLS[feature].handler(arguments, **context)


class SchemaType(click.ParamType):
    """Keep Click conversion while enforcing the shared scalar constraints."""

    def __init__(self, schema: dict[str, Any], original: click.ParamType) -> None:
        """Select native scalar conversion, preserving unprocessed command words."""
        self.schema = schema
        kind = schema.get("type")
        if isinstance(kind, list):
            kind = next((item for item in kind if item != "null"), None)
        self.base = original if original is click.UNPROCESSED else {
            "string": click.STRING, "integer": click.INT,
            "number": click.FLOAT, "boolean": click.BOOL,
        }.get(kind, original)
        self.name = (
            "|".join(str(item) for item in schema["enum"] if item is not None)
            if "enum" in schema else self.base.name
        )

    def convert(self, value: Any, param: click.Parameter | None, ctx: click.Context | None) -> Any:
        """Convert one CLI scalar and reject values outside the shared schema."""
        converted = self.base.convert(value, param, ctx)
        try:
            _validate(converted, self.schema, param.name if param else "argument")
        except ValueError as error:
            self.fail(str(error), param, ctx)
        return converted


class OperationCommand(click.Command):
    """Render and parse one operation using its current shared definition."""

    def __init__(self, *args: Any, feature: str, **kwargs: Any) -> None:
        """Bind a stable feature identifier without snapshotting its schema."""
        self.feature = feature
        super().__init__(*args, **kwargs)
        self.name = TOOLS[feature].cli_path[-1]

    def invoke(self, ctx: click.Context) -> Any:
        """Open Runner resources only after Click has handled help and parsing."""
        tool = TOOLS[self.feature]
        if tool.cli_path[0] == "agent-runner" and self.feature not in {
            "alias_status", "parent_status", "pending_requests", "session_reports",
        }:
            from graphtraj.interfaces.cli.agent_runner import _budget_notices

            ctx.with_resource(_budget_notices())
        return super().invoke(ctx)

    def get_short_help_str(self, limit: int = 45) -> str:
        """Use the common short description in parent command listings."""
        return click.utils.make_default_short_help(TOOLS[self.feature].description, limit)

    def get_params(self, ctx: click.Context) -> list[click.Parameter]:
        """Project constraints while retaining file, positional and repeated forms."""
        tool = TOOLS[self.feature]
        properties = tool.input_schema.get("properties", {})
        required = tool.input_schema.get("required", [])
        parameters = []
        for original in super().get_params(ctx):
            parameter = copy(original)
            name, encoding = tool.cli_parameters.get(parameter.name, (parameter.name, "value"))
            schema = properties.get(name, {})
            if parameter.name == "help":
                parameters.append(parameter)
                continue
            if encoding == "value":
                parameter.required = name in required
                if "default" in schema:
                    parameter.default = schema["default"]
                scalar = (
                    schema.get("items", {})
                    if parameter.multiple or parameter.nargs == -1 else schema
                )
                parameter.type = SchemaType(scalar, parameter.type)
            elif name:
                parameter.required = name in required
            if isinstance(parameter, click.Option):
                parameter.help = schema.get("description", "")
                parameter.show_default = True
            parameters.append(parameter)
        return parameters

    def format_help_text(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        """Read the same selected manual, examples and schema as gateway describe."""
        document = handle_request({"action": "describe", "feature": self.feature}).document
        formatter.write_paragraph()
        formatter.write_text(document["description"])
        if document.get("manual"):
            formatter.write_paragraph()
            formatter.write_text(document["manual"])
        if document.get("error"):
            formatter.write_paragraph()
            formatter.write_text(document["error"])
        tool = TOOLS[self.feature]
        with formatter.section("Parameters"):
            for parameter in self.get_params(ctx):
                if parameter.name == "help":
                    continue
                name, encoding = tool.cli_parameters.get(parameter.name, (parameter.name, "value"))
                form = ", ".join(parameter.opts)
                formatter.write_text(f"{form}: {name or '$'} ({encoding})")
            formatter.write_text("\b\n" + json.dumps(document["input_schema"], ensure_ascii=False, indent=2))
        if document["examples"]:
            with formatter.section("Examples"):
                for example in document["examples"]:
                    formatter.write_text(json.dumps(example, ensure_ascii=False))


class OperationGroup(click.Group):
    """Keep parent help an overview and child help free of execution resources."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        """Select swarm details when the existing file option is present."""
        ctx.meta["swarm_help"] = any(
            argument == "--swarm-input" or argument.startswith("--swarm-input=")
            for argument in args
        )
        return super().parse_args(ctx, args)

    def format_help_text(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        """Show only selected swarm details; ordinary root help stays an overview."""
        super().format_help_text(ctx, formatter)
        if self.name == "main" and "swarm_input" in {p.name for p in self.params}:
            if ctx.meta.get("swarm_help"):
                OperationCommand(
                    "swarm", feature="swarm", params=self.params,
                ).format_help_text(ctx, formatter)
            else:
                formatter.write_paragraph()
                formatter.write_text(TOOLS["swarm"].description)
        elif self.name == "main":
            with formatter.section("agent-runner"):
                formatter.write_text(", ".join(
                    " ".join(tool.cli_path[1:]) for tool in TOOLS.values()
                    if tool.cli_path and tool.cli_path[0] == "agent-runner"
                ))
