"""Equivalent Python and CLI inputs use the same supported operations."""

import json
import shutil
from contextlib import nullcontext
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from conftest import FakeCodex, InstalledCommands
from graphtraj.interfaces.cli.graphtraj import main
from test_ticket_graph import _configure, _ticket, _write


def test_python_and_cli_register_validate_and_read_the_same_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """A mapping can be registered without CLI context, including its validation."""
    from graphtraj.graph.ticket_graph import read_graph, register_ticket

    roots = [tmp_path / name for name in ("python", "cli")]
    for root in roots:
        root.mkdir()
        _configure(root)
    python_root, cli_root = roots
    state = python_root / ".graphtraj/state"
    issue = _ticket("73", "shared-graph")
    directory = register_ticket(state, python_root, issue)
    assert directory == state / "tickets/73-shared-graph"
    assert capsys.readouterr() == ("", "")

    monkeypatch.chdir(cli_root)
    runner = CliRunner()
    result = runner.invoke(main, ["ticket", "register", "--ticket-file", str(_write(cli_root / "issue.yml", issue))])
    assert result.exit_code == 0, result.output
    assert Path(result.stdout.strip()).relative_to(cli_root) == directory.relative_to(python_root)
    graph = runner.invoke(main, ["ticket", "graph"])
    assert graph.exit_code == 0, graph.output
    assert yaml.safe_load(graph.stdout) == read_graph(state) == {"tickets": [{
        "ticket_id": "73", "ticket_name": "shared-graph", "status": "pending",
        "active": True, "ready": True, "dependencies": [], "replaced_by": [],
    }]}

    for invalid in (issue, {**issue, "ticket_id": "../escape"}):
        before = read_graph(state)
        with pytest.raises(ValueError) as error:
            register_ticket(state, python_root, invalid)
        failed = runner.invoke(main, ["ticket", "register", "--ticket-file", str(_write(cli_root / "issue.yml", invalid))])
        assert failed.exit_code == 1
        assert str(error.value) in failed.stderr
        assert read_graph(state) == before
        assert yaml.safe_load(runner.invoke(main, ["ticket", "graph"]).stdout) == before


@pytest.mark.parametrize("separated", [False, True])
def test_python_setup_returns_actions_and_doctor_reports_without_a_terminal(
    temporary_git_repository: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    separated: bool,
) -> None:
    """The existing Setup plan supplies structured completion and diagnostics."""
    from graphtraj.configuration.skill_check import diagnose_project
    from graphtraj.workspace.project_initialization import plan_project_setup

    repository = temporary_git_repository
    root = repository.parent if separated else repository
    user_skills = tmp_path / "user/.agents/skills"
    plan = plan_project_setup(root, repository)
    preview = plan.preflight(install_missing_skills=True)
    assert preview.actions
    assert not (root / ".graphtraj/config.yml").exists()
    result = plan.apply(install_missing_skills=True)
    assert result.integration_worktree == plan.configuration.integration_worktree
    assert result.integration_action == "created"
    assert result.completed_actions
    assert capsys.readouterr() == ("", "")

    diagnosis = diagnose_project(root, user_skills)
    assert diagnosis.succeeded
    assert diagnosis.roles_checked and not diagnosis.role_diagnostics
    assert all(status.discovered for status in diagnosis.skills)
    monkeypatch.chdir(root)
    monkeypatch.setenv("HOME", str(user_skills.parent.parent))
    runner = CliRunner()
    doctor = runner.invoke(main, ["doctor"])
    assert doctor.exit_code == 0, doctor.output
    assert dict(line.split(": ") for line in doctor.stdout.splitlines()) == {
        **{status.name: "OK" for status in diagnosis.skills}, "roles": "OK",
    }
    repeat = plan_project_setup(root).apply()
    assert repeat.integration_action == "reused"
    config_before = (root / ".graphtraj/config.yml").read_bytes()
    setup = runner.invoke(main, ["setup"])
    assert setup.exit_code == 0, setup.output
    assert (root / ".graphtraj/config.yml").read_bytes() == config_before
    assert repeat.integration_worktree.is_dir()


def test_doctor_python_result_matches_missing_skills_roles_and_root_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Diagnostics are data; the CLI alone translates failure and usage exits."""
    from graphtraj.configuration.skill_check import diagnose_project, DoctorError

    _configure(tmp_path)
    user = tmp_path / "user"
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.chdir(tmp_path)
    diagnosis = diagnose_project(tmp_path, user / ".agents/skills")
    assert not diagnosis.succeeded
    assert diagnosis.roles_checked and diagnosis.role_diagnostics
    result = CliRunner().invoke(main, ["doctor"])
    assert result.exit_code == 1
    for status in diagnosis.skills:
        assert not status.discovered
        assert f"{status.name}: MISSING" in result.stdout
    for diagnostic in diagnosis.role_diagnostics:
        assert diagnostic in result.stdout
    child = tmp_path / "child"
    child.mkdir()
    with pytest.raises(DoctorError) as error:
        diagnose_project(child, user / ".agents/skills")
    monkeypatch.chdir(child)
    result = CliRunner().invoke(main, ["doctor"])
    assert result.exit_code == 2
    assert str(error.value) in result.stderr


def test_python_and_cli_revise_and_transition_with_the_same_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revision and state mapping validation protect both entry points."""
    from graphtraj.graph.ticket_graph import (
        read_graph, register_ticket, revise_tickets, update_ticket_state,
    )
    from graphtraj.graph.delivery_worldline import read_worldline

    python_root, cli_root = tmp_path / "python", tmp_path / "cli"
    python_root.mkdir()
    state = _configure(python_root)
    issue = _ticket("73", "shared-graph")
    register_ticket(state, python_root, issue)
    (python_root / "evidence.md").write_text("Main confirmed the revision and readiness.\n")
    shutil.copytree(python_root, cli_root)
    monkeypatch.chdir(cli_root)
    runner = CliRunner()
    revision = {
        "product_preserving": True, "caused_by_event_ids": [],
        "evidence_refs": ["evidence.md"],
        "tickets": [{**issue, "body": "Deliver the revised definition.", "active": True, "replaced_by": []}],
    }
    change = {
        "ticket_id": "73", "status": "ready", "active_team_ordinal": None,
        "worktree": None, "branch": None, "current_candidate": None,
        "caused_by_event_ids": [], "evidence_refs": ["evidence.md"],
    }
    for operation, command, option, document in (
        (revise_tickets, "revise", "--revision-file", revision),
        (update_ticket_state, "update", "--state-file", change),
    ):
        recorded = operation(state, python_root, document)
        result = runner.invoke(main, ["ticket", command, option, str(_write(cli_root / "input.yml", document))])
        assert result.exit_code == 0, result.output
        rendered = yaml.safe_load(result.stdout)
        assert rendered["kind"] == recorded["kind"]
        assert rendered["evidence_refs"][:1] == recorded["evidence_refs"][:1] == ["evidence.md"]
        assert read_worldline(state, python_root)[-1] == recorded
        assert read_worldline(cli_root / ".graphtraj/state", cli_root)[-1] == rendered
        assert yaml.safe_load(runner.invoke(main, ["ticket", "graph"]).stdout) == read_graph(state)
        before = read_worldline(state, python_root)
        for invalid in ({}, {**document, "evidence_refs": []}):
            with pytest.raises(ValueError) as error:
                operation(state, python_root, invalid)
            failed = runner.invoke(main, ["ticket", command, option, str(_write(cli_root / "input.yml", invalid))])
            assert failed.exit_code == 1
            assert str(error.value) in failed.stderr
            assert read_worldline(state, python_root) == before
    assert read_graph(state)["tickets"][0]["status"] == "ready"


def test_python_and_cli_commit_team_state_and_worldline_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """Both interfaces enforce authoritative facts and retain the same effects."""
    from graphtraj.graph.delivery_state import apply_delivery_state_request
    from graphtraj.graph.delivery_worldline import append_project_worldline_event, read_worldline
    from graphtraj.graph.ticket_graph import read_graph, register_ticket, update_ticket_state

    python_root, cli_root = tmp_path / "python", tmp_path / "cli"
    python_root.mkdir()
    state = _configure(python_root)
    register_ticket(state, python_root, _ticket("73", "shared-state"))
    (python_root / "evidence.md").write_text("Main approved this Team.\n")
    predecessor = update_ticket_state(state, python_root, {
        "ticket_id": "73", "status": "ready", "active_team_ordinal": None,
        "worktree": None, "branch": None, "current_candidate": None,
        "caused_by_event_ids": [], "evidence_refs": ["evidence.md"],
    })
    (python_root / ".graphtraj/worktrees/73-shared-state").mkdir(parents=True)
    shutil.copytree(python_root, cli_root)
    monkeypatch.chdir(cli_root)
    runner = CliRunner()
    request = {
        "phase": "start", "ticket_id": "73",
        "caused_by_event_ids": [predecessor["event_id"]], "evidence_refs": ["evidence.md"],
        "worktree": ".graphtraj/worktrees/73-shared-state", "branch": "agent/73-shared-state",
        "members": {
            "team_leader": {"role": "team-leader", "session_ref": "73-shared-state@l1"},
            "engineer": {"role": "engineer-expert", "session_ref": None},
            "standards_reviewer": {"role": "standards-reviewer", "session_ref": None},
            "spec_reviewer": {"role": "spec-reviewer", "session_ref": None},
        },
    }
    command = ["delivery-state", "apply", "--request-file", str(_write(cli_root / "request.yml", request)),
               "--facts-file", str(_write(cli_root / "facts.yml", {**request, "ticket_id": "74"}))]
    with pytest.raises(ValueError) as error:
        apply_delivery_state_request(state, python_root, request, {**request, "ticket_id": "74"})
    rejected = runner.invoke(main, command)
    assert rejected.exit_code == 1
    assert str(error.value) in rejected.stderr
    assert read_graph(state)["tickets"][0]["status"] == "ready"

    _write(cli_root / "facts.yml", request)
    recorded = apply_delivery_state_request(state, python_root, request, request)
    result = runner.invoke(main, command)
    assert result.exit_code == 0, result.output
    rendered = yaml.safe_load(result.stdout)
    assert {k: v for k, v in recorded.items() if k not in {"event_id", "captured_at"}} == {
        k: v for k, v in rendered.items() if k not in {"event_id", "captured_at"}
    }
    assert recorded["kind"] == "team-started"
    assert yaml.safe_load(runner.invoke(main, ["ticket", "graph"]).stdout) == read_graph(state)
    assert read_graph(state)["tickets"][0]["status"] == "implementing"

    event = {"kind": "main-decision", "caused_by_event_ids": [predecessor["event_id"]],
             "evidence_refs": ["evidence.md"], "decision": "Continue the accepted work."}
    recorded = append_project_worldline_event(state, python_root, event)
    result = runner.invoke(main, ["worldline", "append", "--event-file", str(_write(cli_root / "event.yml", event))])
    assert result.exit_code == 0, result.output
    rendered = yaml.safe_load(result.stdout)
    assert {key: recorded[key] for key in event} == {key: rendered[key] for key in event} == event
    assert read_worldline(state, python_root)[-1] == recorded
    assert json.loads(runner.invoke(main, ["worldline", "read"]).stdout.splitlines()[-1]) == rendered
    assert yaml.safe_load(runner.invoke(main, ["worldline", "render"]).stdout)["trajectory"][-1] == rendered

    before = read_worldline(state, python_root)
    invalid = {**event, "caused_by_event_ids": ["unknown-event"]}
    with pytest.raises(ValueError) as error:
        append_project_worldline_event(state, python_root, invalid)
    result = runner.invoke(main, ["worldline", "append", "--event-file", str(_write(cli_root / "event.yml", invalid))])
    assert result.exit_code == 1
    assert str(error.value) in result.stderr
    assert read_worldline(state, python_root) == before
    assert capsys.readouterr() == ("", "")


def test_python_and_cli_launch_the_same_structured_batch_and_errors(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """Runner accepts validated data, retains input and returns ordinary errors."""
    from conftest import PROJECT_ROOT
    from runner_fixtures import configure_harness
    from graphtraj.execution.runner_batch import parse_batch, read_batch
    from graphtraj.execution.runner_launch import launch_batch
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.graph.ticket_graph import register_ticket
    from graphtraj.interfaces.cli.agent_runner import main as runner_main

    root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PYTHONPATH", str(PROJECT_ROOT / "src"))
    monkeypatch.chdir(root)
    register_ticket(root / ".graphtraj/state", root, _ticket("73", "shared-runner"))
    document = {"tasks": [{
        "ticket_id": "73", "ticket_name": "shared-runner",
        "role": {"investigation-specialist": {"runtime": "codex", "model": "gpt-5.6-luna"}},
        "instruction": "Inspect the accepted Ticket.",
    }]}
    batch = parse_batch(document)
    direct = launch_batch(batch, root)
    assert direct.succeeded
    assert capsys.readouterr() == ("", "")
    path = root / "batch.yml"
    original = "# Keep the exact CLI input\n" + yaml.safe_dump(document, sort_keys=False)
    path.write_text(original)
    assert read_batch(path, root).tasks == batch.tasks
    result = CliRunner().invoke(runner_main, ["--batch-input", str(path)])
    assert result.exit_code == 0, result.output
    rendered = yaml.safe_load(result.stdout)
    for response in (direct.document, rendered):
        assert response["tasks"][0]["launch_status"] == "completed"
        assert response["tasks"][0]["role"] == "investigation-specialist"
        assert yaml.safe_load(Path(response["retained_batch_file"]).read_bytes()) == document
    assert Path(rendered["retained_batch_file"]).read_text() == original

    before = list((root / ".graphtraj/state/batches").iterdir())
    for invalid in ({"tasks": []}, {"tasks": document["tasks"] * 2}):
        with pytest.raises(RunnerError) as error:
            parse_batch(invalid)
        result = CliRunner().invoke(runner_main, ["--batch-input", str(_write(path, invalid))])
        assert result.exit_code == 1
        assert yaml.safe_load(result.stdout) == {"error": error.value.as_document()}
    assert list((root / ".graphtraj/state/batches").iterdir()) == before

    # Direct callers must use the same child-registration route as the CLI.
    monkeypatch.setenv("GRAPHTRAJ_PARENT_REGISTRATION", str(root / "registration.yml"))
    monkeypatch.setenv("GRAPHTRAJ_TICKET_ID", "74")
    with pytest.raises(RunnerError) as error:
        launch_batch(batch, root)
    result = CliRunner().invoke(runner_main, ["--batch-input", str(_write(path, document))])
    assert result.exit_code == 1
    assert yaml.safe_load(result.stdout) == {"error": error.value.as_document()}
    assert not (root / "registration.yml").exists()


@pytest.mark.parametrize("capture_notices", [False, True])
def test_python_budgeted_launch_preserves_notices_without_writing_to_terminal(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture,
    capture_notices: bool,
) -> None:
    """A complete budgeted Team can run through Python with no stdout/stderr."""
    from conftest import PROJECT_ROOT
    from runner_fixtures import configure_harness
    from test_execution_budgets import _budget_body
    from graphtraj.execution.execution_budget import budget_notice_output
    from graphtraj.execution.runner_batch import parse_batch
    from graphtraj.execution.runner_launch import launch_batch
    from graphtraj.graph.ticket_graph import register_ticket, update_ticket_state

    root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PYTHONPATH", str(PROJECT_ROOT / "src"))
    monkeypatch.setenv("FAKE_CODEX_LIFECYCLE_ACTION", "complete-team-round")
    monkeypatch.setenv("GRAPHTRAJ_AGENT_RUNNER", str(installed_commands.runner))
    state = root / ".graphtraj/state"
    directory = register_ticket(state, root, {
        **_ticket("73", "shared-budget"), "body": _budget_body(total=1000, delivery_state_sessions=0.5),
    })
    (root / "evidence.md").write_text("Main selected this Team.\n")
    update_ticket_state(state, root, {
        "ticket_id": "73", "status": "ready", "active_team_ordinal": None,
        "worktree": None, "branch": None, "current_candidate": None,
        "caused_by_event_ids": [], "evidence_refs": ["evidence.md"],
    })
    capfd.readouterr()
    notices = root / "notices.jsonl"
    with notices.open("w") as output:
        with budget_notice_output(output.fileno()) if capture_notices else nullcontext():
            response = launch_batch(parse_batch({"tasks": [{
                "ticket_id": "73", "ticket_name": "shared-budget", "role": "team-leader",
            }]}), root)
    assert response.succeeded, response.document
    assert capfd.readouterr() == ("", "")
    budget = yaml.safe_load((directory / "execution-budget.yml").read_text())
    assert budget["notifications"]
    assert budget["sessions"]["delivery_state"] == 1
    events = [json.loads(line) for line in notices.read_text().splitlines()]
    if capture_notices:
        assert len(events) == 1
        assert events[0]["type"] == "execution-budget-exceeded"
        assert events[0]["threshold"] == {"kind": "planned_sessions.delivery_state", "limit": 0.5}
    else:
        assert events == []

    from graphtraj.execution.runner_cleanup import cleanup_ticket
    from graphtraj.execution.runner_control import interrupt_session, send_instruction
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.execution.runner_status import status_aliases
    from graphtraj.interfaces.cli.agent_runner import main as runner_main
    from graphtraj.teams.coding.team_round import continue_stopped_ticket
    from graphtraj.teams.coding.team_replacement import replace_session

    monkeypatch.chdir(root)
    alias = response.document["tasks"][0]["alias"]
    runner = CliRunner()
    direct_status = status_aliases((alias,), root)
    assert direct_status.succeeded
    rendered = runner.invoke(runner_main, ["status", alias])
    assert rendered.exit_code == 0, rendered.output
    assert yaml.safe_load(rendered.stdout) == direct_status.document
    missing = status_aliases((alias, "missing@l1"), root)
    rendered = runner.invoke(runner_main, ["status", alias, "missing@l1"])
    assert rendered.exit_code == 1
    assert yaml.safe_load(rendered.stdout) == missing.document
    assert not missing.succeeded and missing.errors

    for operation, arguments, cli_arguments, identity in (
        (send_instruction, (alias, " ", root, ()), ["send", alias, "--instruction", " "], {"alias": alias}),
        (interrupt_session, (alias, root), ["interrupt", alias], {"alias": alias}),
        (continue_stopped_ticket, ("73", ("",), root), ["continue", "--ticket-id", "73", "--caused-by-event-id", ""], {"ticket_id": "73"}),
        (replace_session, (alias, "main", ("",), root), ["replace", alias, "--actor", "main", "--caused-by-event-id", ""], {"alias": alias}),
    ):
        with pytest.raises(RunnerError) as error:
            operation(*arguments)
        rendered = runner.invoke(runner_main, cli_arguments)
        assert rendered.exit_code == 1
        assert yaml.safe_load(rendered.stdout) == {**identity, "error": error.value.as_document()}
    refused = cleanup_ticket(root, "73")
    assert not refused.succeeded
    rendered = runner.invoke(runner_main, ["cleanup", "--ticket-id", "73"])
    assert rendered.exit_code == 1
    assert yaml.safe_load(rendered.stdout) == refused.document
