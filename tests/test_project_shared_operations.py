"""Shared project definitions keep the CLI's inputs, defaults and rejections."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from graphtraj.configuration.project_configuration import ProjectConfigurationError
from graphtraj.interfaces import tools
from graphtraj.interfaces.cli.graphtraj import main
from test_delivery_worldline import _configure_project, _event_file
from test_ticket_graph import _configure, _ticket, _write


def test_project_definitions_name_the_cli_inputs() -> None:
    """Every project command exposes one schema for its CLI form."""

    setup = tools.TOOLS["project_setup"].input_schema
    assert set(setup["properties"]) == {"source_repository", "apply", "create_dev"}
    assert set(setup.get("required", ())) == set()
    assert setup["properties"]["apply"]["type"] == "boolean"

    assert set(tools.TOOLS["worldline_append"].input_schema["required"]) == {"event"}
    assert set(tools.TOOLS["delivery_state_apply"].input_schema["required"]) == {
        "request", "facts",
    }

    integrate = tools.TOOLS["ticket_integrate"].input_schema
    assert set(integrate["required"]) == {"ticket_id", "validation_command"}
    assert integrate["properties"]["validation_command"]["items"] == {"type": "string"}
    assert integrate["properties"]["role"]["type"] == ["string", "object", "null"]

    for name in ("project_doctor", "worldline_read", "worldline_render"):
        assert tools.TOOLS[name].input_schema["properties"] == {}
    assert tools.TOOLS["worldline_read"].handler is tools.TOOLS["worldline_render"].handler


def test_worldline_definition_and_cli_keep_one_event_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Append, read and render agree with the shared Worldline document."""

    project = tmp_path / "project"
    project.mkdir()
    _configure_project(project)
    evidence = project / "evidence/candidate.txt"
    evidence.parent.mkdir()
    evidence.write_text("candidate\n", encoding="utf-8")
    event = {
        "event":                "user-decision",
        "caused_by_event_ids": [],
        "evidence_refs":       ["evidence/candidate.txt"],
        "decision":            "Use the candidate.",
    }
    event_file = _event_file(project, "event.yml", event)
    monkeypatch.chdir(project)
    runner = CliRunner()

    appended = runner.invoke(main, ["worldline", "append", "--event-file", str(event_file)])
    assert appended.exit_code == 0, appended.stderr
    recorded = yaml.safe_load(appended.stdout)
    assert recorded["event"] == "user-decision"

    read = tools.TOOLS["worldline_read"].handler({}).document
    render = tools.TOOLS["worldline_render"].handler({}).document
    assert read == render
    assert read["events"][-1] == recorded
    read_output = runner.invoke(main, ["worldline", "read"])
    assert json.loads(read_output.stdout.splitlines()[-1]) == recorded
    render_output = runner.invoke(main, ["worldline", "render"])
    assert yaml.safe_load(render_output.stdout) == {"trajectory": read["events"]}


def test_project_read_outside_the_root_matches_the_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A read without a Harness Project reports the CLI's own error."""

    monkeypatch.chdir(tmp_path)
    with pytest.raises(ProjectConfigurationError) as error:
        tools.TOOLS["ticket_graph"].handler({})
    graph = CliRunner().invoke(main, ["ticket", "graph"])
    assert graph.exit_code == 1
    assert str(error.value) in graph.stderr


def test_worldline_write_rejection_matches_the_cli_without_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-mapping event is rejected before either interface writes state."""

    project = tmp_path / "project"
    project.mkdir()
    state = _configure_project(project)
    not_a_mapping = _event_file(project, "event.yml", ["not", "a", "mapping"])
    monkeypatch.chdir(project)

    with pytest.raises(ValueError) as error:
        tools.TOOLS["worldline_append"].handler({"event": None})
    result = CliRunner().invoke(main, ["worldline", "append", "--event-file", str(not_a_mapping)])
    assert result.exit_code == 1
    assert str(error.value) in result.stderr
    assert not (state / "worldline").exists()


def test_delivery_state_facts_mismatch_matches_the_cli_without_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A write whose authoritative facts differ is rejected identically."""

    project = tmp_path / "project"
    project.mkdir()
    state = _configure(project)
    request = {"phase": "start", "ticket_id": "73"}
    facts = {**request, "ticket_id": "74"}
    monkeypatch.chdir(project)

    with pytest.raises(ValueError) as error:
        tools.TOOLS["delivery_state_apply"].handler({"request": request, "facts": facts})
    request_file = _write(project / "request.yml", request)
    facts_file = _write(project / "facts.yml", facts)
    result = CliRunner().invoke(
        main, ["delivery-state", "apply", "--request-file", str(request_file),
               "--facts-file", str(facts_file)],
    )
    assert result.exit_code == 1
    assert str(error.value) in result.stderr
    assert list(state.rglob("*")) == []


def test_integrate_definition_rejects_a_command_that_is_not_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The integration command keeps its positional argv input shape."""

    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError) as error:
        tools.TOOLS["ticket_integrate"].handler(
            {"ticket_id": "73", "validation_command": "pytest"}
        )
    assert "validation_command must be a list of strings" in str(error.value)


def test_project_doctor_reports_diagnostics_without_a_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Doctor returns its diagnostics as data and only the CLI exits nonzero."""

    monkeypatch.chdir(tmp_path)
    result = tools.TOOLS["project_doctor"].handler({})
    assert result.document == {"roles_checked": False, "role_diagnostics": []}
    assert result.failed is False
    doctor = CliRunner().invoke(main, ["doctor"])
    assert doctor.exit_code == 0, doctor.stderr
    assert doctor.stdout == ""


def test_project_setup_previews_without_writing_and_fails_when_ambiguous(
    temporary_git_repository: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setup needs an explicit confirmation before it mutates the project."""

    root = temporary_git_repository
    preview = tools.TOOLS["project_setup"].handler({}, cwd=root).document
    assert preview["applied"] is False
    assert preview["proposed_base"]
    assert preview["actions"]
    assert not (root / ".graphtraj/config.yml").exists()

    with pytest.raises(ValueError) as error:
        tools.TOOLS["project_setup"].handler({"apply": True}, cwd=root)
    assert "must explicitly confirm creating dev" in str(error.value)
    assert not (root / ".graphtraj/config.yml").exists()

    ambiguous = root.parent / "no-git-here"
    ambiguous.mkdir()
    with pytest.raises(ValueError) as error:
        tools.TOOLS["project_setup"].handler({}, cwd=ambiguous)
    assert "Setup could not select a Source Repository." in str(error.value)


def test_registered_ticket_definition_matches_a_handler_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI register command returns the shared handler's ticket directory."""

    python_root, cli_root = tmp_path / "python", tmp_path / "cli"
    python_root.mkdir()
    _configure(python_root)
    issue = _ticket("73", "shared-project")
    shutil.copytree(python_root, cli_root)
    ticket_file = _write(cli_root / "issue.yml", issue)
    monkeypatch.chdir(python_root)

    directory = tools.TOOLS["ticket_register"].handler(issue).document["ticket_directory"]
    monkeypatch.chdir(cli_root)
    result = CliRunner().invoke(main, ["ticket", "register", "--ticket-file", str(ticket_file)])
    assert result.exit_code == 0, result.stderr
    assert Path(result.stdout.strip()).relative_to(cli_root) == (
        Path(directory).relative_to(python_root)
    )
