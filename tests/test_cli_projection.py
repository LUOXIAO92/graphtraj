"""Shared material and schema changes reach public CLI help and real inputs."""

from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import subprocess
from typing import Any

import pytest
import yaml
from click.testing import CliRunner

from graphtraj.interfaces import gateway, tools
from graphtraj.interfaces.cli import agent_runner, graphtraj


@pytest.mark.parametrize("feature", [name for name, tool in tools.TOOLS.items() if tool.cli_path])
def test_every_operation_help_uses_selected_gateway_material(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, feature: str,
) -> None:
    """All 25 operations read current material without executing or opening recovery."""
    monkeypatch.chdir(tmp_path)
    manual = tmp_path / "manual.txt"
    manual.write_text(f"Selected material for {feature}")

    def forbidden(*args: Any, **kwargs: Any) -> None:
        """Fail if help attempts to run an operation or enter Runner resources."""
        pytest.fail("Help attempted execution")

    monkeypatch.setattr(agent_runner, "_budget_notices", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    tool = tools.TOOLS[feature]
    monkeypatch.setitem(tools.TOOLS, feature, replace(
        tool, description=f"Shared description for {feature}", manual_ref=str(manual),
        examples=({"sample": "shared-example"},), handler=forbidden,
    ))
    command = graphtraj.main if tool.cli_path[0] == "graphtraj" else agent_runner.main
    args = list(tool.cli_path[1:])
    if feature == "swarm":
        args.append("unread-launch.yml")
    for revision in ("first", "second"):
        manual.write_text(f"Selected material {revision} for {feature}")
        described = gateway.handle_request({"action": "describe", "feature": feature})
        selected_args = (
            ["--swarm-input=unread-launch.yml"]
            if feature == "swarm" and revision == "second" else args
        )
        result = CliRunner().invoke(command, [*selected_args, "--help"])
        assert result.exit_code == 0, result.output
        assert described.document["description"] in result.output
        assert Path(described.document["manual_ref"]).read_text(encoding="utf-8") in result.output
        assert "shared-example" in result.output
        for name in tool.input_schema.get("properties", {}):
            assert name in result.output
    assert list(tmp_path.iterdir()) == [manual]


def test_top_level_help_is_an_overview_and_directs_to_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Root help lists directions without loading any manual or parameter catalog."""
    monkeypatch.chdir(tmp_path)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        """Root discovery must not read material or open recovery."""
        pytest.fail("Overview opened a resource")

    monkeypatch.setattr(agent_runner, "_budget_notices", forbidden)
    with monkeypatch.context() as root_help:
        root_help.setattr(Path, "read_text", forbidden)
        for command in (graphtraj.main, agent_runner.main):
            result = CliRunner().invoke(command, ["--help"])
            assert result.exit_code == 0, result.output
            assert "agent-runner" in result.output
            assert "send" in result.output
            assert "input_schema" not in result.output

    manual = tmp_path / "manual.txt"
    manual.write_text("Selected Main material")
    monkeypatch.setitem(tools.TOOLS, "main", replace(
        tools.TOOLS["main"], manual_ref=str(manual),
    ))
    result = CliRunner().invoke(agent_runner.main, ["main", "--help"])
    assert result.exit_code == 0, result.output
    assert manual.read_text() in result.output


def test_schema_change_updates_help_describe_and_scalar_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Required/type/default/enum changes affect existing flags without redecorating."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(agent_runner, "_budget_notices", nullcontext)
    calls = []

    def handler(arguments: dict[str, Any], **context: Any) -> tools.ToolResult:
        """Capture successfully decoded public CLI arguments."""
        calls.append(arguments)
        return tools.ToolResult({"received": arguments})

    original = tools.TOOLS["alias_status"]
    for choices, default in (([7, 9], 7), ([11, 13], 13)):
        schema = deepcopy(original.input_schema)
        schema["properties"]["baseline"] = {
            "type": "integer", "enum": choices, "default": default,
            "description": "Controlled baseline parameter",
        }
        schema["required"] = ["candidate"]
        monkeypatch.setitem(tools.TOOLS, "alias_status", replace(
            original, input_schema=schema, handler=handler,
        ))
        described = gateway.handle_request({"action": "describe", "feature": "alias_status", "schema": True})
        assert described.document["input_schema"] == schema
        help_result = CliRunner().invoke(agent_runner.main, ["status", "--help"])
        assert help_result.exit_code == 0, help_result.output
        assert "Controlled baseline parameter" in help_result.output
        assert str(default) in help_result.output
        assert "integer" in help_result.output
        for extra in ([], ["--candidate", "head", "--baseline", "text"],
                      ["--candidate", "head", "--baseline", "99"]):
            rejected = CliRunner().invoke(agent_runner.main, ["status", *extra])
            assert rejected.exit_code == 2, rejected.output
        assert not calls
        for extra, expected in (([], default), (["--baseline", str(choices[0])], choices[0])):
            accepted = CliRunner().invoke(agent_runner.main, ["status", "--candidate", "head", *extra])
            assert accepted.exit_code == 0, accepted.output
            assert calls[-1]["baseline"] == expected
            assert calls[-1]["candidate"] == "head"
        calls.clear()


def test_file_content_uses_same_nested_schema_as_gateway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whole-document file inputs enforce shared constraints before side effects."""
    monkeypatch.chdir(tmp_path)
    calls = []

    def handler(arguments: dict[str, Any]) -> tools.ToolResult:
        """Capture valid ticket input without registering a Ticket."""
        calls.append(arguments)
        return tools.ToolResult({"ticket_directory": "registered"})

    original = tools.TOOLS["ticket_register"]
    schema = deepcopy(original.input_schema)
    schema["properties"]["ticket_id"] = {"type": "integer", "enum": [210]}
    monkeypatch.setitem(tools.TOOLS, "ticket_register", replace(original, input_schema=schema, handler=handler))
    document = {"ticket_id": 210, "ticket_name": "fixture", "source": "source", "title": "title",
                "body": "body", "dependencies": []}
    path = tmp_path / "ticket.yml"
    for value in ("210", 211, 210):
        arguments = {**document, "ticket_id": value}
        path.write_text(yaml.safe_dump(arguments))
        described = gateway.handle_request({"action": "describe", "feature": "ticket_register", "schema": True})
        assert described.document["input_schema"] == schema
        result = CliRunner().invoke(graphtraj.main, ["ticket", "register", "--ticket-file", str(path)])
        assert result.exit_code == (0 if value == 210 else 2), result.output
    assert calls == [document]
    path.write_text("ticket_id: 210\n")
    result = CliRunner().invoke(graphtraj.main, ["ticket", "register", "--ticket-file", str(path)])
    assert result.exit_code == 2
    assert "required" in result.output
    assert calls == [document]


def test_swarm_keeps_original_file_and_validates_before_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid file launches retain the original path; invalid task shapes never launch."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(agent_runner, "_budget_notices", nullcontext)
    calls = []

    def handler(arguments: dict[str, Any], **context: Any) -> tools.ToolResult:
        """Capture the preserved file input without starting any Runtime."""
        calls.append((arguments, context["input_file"].read_text()))
        return tools.ToolResult({"tasks": []})

    monkeypatch.setitem(tools.TOOLS, "swarm", replace(tools.TOOLS["swarm"], handler=handler))
    path = tmp_path / "swarm.yml"
    path.write_text("tasks:\n- role: 9\n")
    assert CliRunner().invoke(agent_runner.main, ["--swarm-input", str(path)]).exit_code == 2
    assert not calls
    content = "# retained comment\ntasks:\n- role: engineer\n"
    path.write_text(content)
    result = CliRunner().invoke(agent_runner.main, ["--swarm-input", str(path)])
    assert result.exit_code == 0, result.output
    assert calls == [({"tasks": [{"role": "engineer"}]}, content)]


def test_report_command_uses_shared_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    """The existing report operation is available in the CLI without state shortcuts."""
    monkeypatch.setattr(agent_runner, "_budget_notices", nullcontext)
    calls = []

    def handler(arguments: dict[str, Any], **context: Any) -> tools.ToolResult:
        """Capture the assigned report operation invocation."""
        calls.append(arguments)
        return tools.ToolResult({"written": True})

    monkeypatch.setitem(tools.TOOLS, "submit_report", replace(tools.TOOLS["submit_report"], handler=handler))
    result = CliRunner().invoke(agent_runner.main, ["submit-report", "--name", "report.md", "--text", "evidence"])
    assert result.exit_code == 0, result.output
    assert calls == [{"name": "report.md", "text": "evidence"}]


def test_integration_preserves_unprocessed_words_and_inline_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validation argv stays positional and inline YAML remains structured input."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(agent_runner, "_budget_notices", nullcontext)
    calls = []

    def handler(arguments: dict[str, Any]) -> tools.ToolResult:
        """Record transport decoding without integrating or dispatching anything."""
        calls.append(arguments)
        return tools.ToolResult({"status": "integrated"})

    monkeypatch.setitem(tools.TOOLS, "ticket_integrate", replace(
        tools.TOOLS["ticket_integrate"], handler=handler,
    ))
    result = CliRunner().invoke(graphtraj.main, [
        "ticket", "integrate", "--ticket-id", "210", "--role", "{name: fixer}",
        "--confirm-resolution", "commit", "--resolve-conflict", "diagnosis",
        "--", "python", "-c", "print('unchanged words')",
    ])
    assert result.exit_code == 0, result.output
    assert calls == [{
        "ticket_id": "210", "role": {"name": "fixer"}, "confirmed_commit": "commit",
        "resolve_conflict": "diagnosis", "validation_command": ["python", "-c", "print('unchanged words')"],
    }]
    rejected = CliRunner().invoke(graphtraj.main, [
        "ticket", "integrate", "--ticket-id", "210", "--role", "[wrong]", "--", "true",
    ])
    assert rejected.exit_code == 2
    assert len(calls) == 1


def test_changed_enum_replaces_existing_click_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    """An existing Choice cannot freeze the registry's enum at import time."""
    monkeypatch.setattr(agent_runner, "_budget_notices", nullcontext)
    original = tools.TOOLS["decide_result"]
    schema = deepcopy(original.input_schema)
    schema["properties"]["decision"]["enum"] = ["fixture-decision"]
    calls = []

    def handler(arguments: dict[str, Any], **context: Any) -> tools.ToolResult:
        """Capture the new enum value without recording any decision."""
        calls.append(arguments["decision"])
        return tools.ToolResult({"decision": arguments["decision"]})

    monkeypatch.setitem(tools.TOOLS, "decide_result", replace(original, input_schema=schema, handler=handler))
    command = ["decide-result", "--submission-id", "submission", "--commit", "commit",
               "--reason", "reason", "--evidence-ref", "evidence"]
    described = gateway.handle_request({"action": "describe", "feature": "decide_result", "schema": True})
    assert described.document["input_schema"]["properties"]["decision"]["enum"] == ["fixture-decision"]
    for choice, code in (("accepted", 2), ("fixture-decision", 0)):
        result = CliRunner().invoke(agent_runner.main, [*command, "--decision", choice])
        assert result.exit_code == code, result.output
    assert calls == ["fixture-decision"]


def test_literal_help_value_keeps_execution_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    """A value spelling --help is data, so real execution retains its notice context."""
    from contextlib import contextmanager
    from collections.abc import Iterator

    active = []

    @contextmanager
    def notices() -> Iterator[None]:
        """Observe the resource lifetime without connecting to a Runtime."""
        active.append(True)
        try:
            yield
        finally:
            active.pop()

    def handler(arguments: dict[str, Any], **context: Any) -> tools.ToolResult:
        """Assert that Click parsed the literal value under normal execution context."""
        assert active == [True]
        assert arguments["instruction"] == "--help"
        return tools.ToolResult({"sent": True})

    monkeypatch.setattr(agent_runner, "_budget_notices", notices)
    monkeypatch.setitem(tools.TOOLS, "send_instruction", replace(
        tools.TOOLS["send_instruction"], handler=handler,
    ))
    result = CliRunner().invoke(agent_runner.main, ["send", "child", "--instruction", "--help"])
    assert result.exit_code == 0, result.output
    assert not active



def test_native_recovery_command_reuses_shared_help_without_raw_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Native execution help follows the same mutable definition as recovery."""
    manual = tmp_path / 'recovery.md'
    original = tools.TOOLS['approved_recovery']
    monkeypatch.setitem(tools.TOOLS, 'approved_recovery', replace(
        original, description='Shared recovery description', manual_ref=str(manual),
        examples=({'sample': 'shared-recovery-example'},),
    ))
    for revision in ('first', 'second'):
        manual.write_text(f'Recovery instructions {revision}')
        described = gateway.handle_request({'action': 'describe', 'feature': 'approved_recovery'})
        result = CliRunner().invoke(agent_runner.main, ['recover', '--help'])
        assert result.exit_code == 0, result.output
        assert described.document['description'] in result.output
        assert Path(described.document['manual_ref']).read_text(encoding='utf-8') in result.output
        assert 'shared-recovery-example' in result.output
        assert '--retry-event-id' in result.output
        for name in original.input_schema['properties']:
            assert name in result.output
    discovered = gateway.handle_request({'action': 'discover'})
    assert 'apply_approved_recovery' not in {item['feature'] for item in discovered.document['features']}
