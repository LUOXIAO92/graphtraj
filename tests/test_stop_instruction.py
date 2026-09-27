"""A stop's user-facing text comes from project configuration, unchanged."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from graphtraj.configuration.project_configuration import (
    DEFAULT_CONFIG_CONTENT,
    ProjectConfigurationError,
    load_project_configuration,
)
from graphtraj.execution.execution_budget import budget_notice_output, caller_notice_fd
from graphtraj.runtimes.codex.app_server import CodexMainRecovery


STOP = {
    "type": "execution-budget-exceeded",
    "occurred_at": datetime.fromtimestamp(1000.0).astimezone().isoformat(timespec="seconds"),
    "ticket": {"ticket_id": "116", "ticket_name": "session-budget-control"},
    "threshold": {"kind": "stochastic_stop", "limit": 2},
    "actual": {"elapsed_minutes": 2.011},
}
CUSTOM_TEXT = "Summarize the retained research and name the exact next owner."


def write_config(root: Path, agent_runner: dict, codex: object = None) -> None:
    """Write one supported project configuration with optional overrides."""
    directory = root / ".graphtraj"
    directory.mkdir(parents=True, exist_ok=True)
    document = yaml.safe_load(DEFAULT_CONFIG_CONTENT)
    document["agent_runner"].update(agent_runner)
    if codex is not None:
        document["codex"] = codex
    (directory / "config.yml").write_text(yaml.safe_dump(document))


def one_delivery(stop_instruction: str | None) -> dict:
    """Return the delivery produced by one stop on a bound caller channel."""
    recovery = CodexMainRecovery(stop_instruction)
    with recovery:
        with budget_notice_output(recovery.notice_fd):
            os.write(recovery.notice_fd, (json.dumps(STOP) + "\n").encode())
        document = recovery.attach_stop_deliveries({"tasks": []})
    return document["stop_deliveries"][0]


@pytest.mark.parametrize(
    "value,expected",
    [(None, None), (CUSTOM_TEXT, CUSTOM_TEXT), ("", "")],
    ids=["omitted", "custom", "empty"],
)
def test_stop_instruction_reads_omitted_custom_and_empty_text(
    tmp_path: Path, value: str | None, expected: str | None,
) -> None:
    """Omitting, customizing and explicitly emptying the setting stay distinct."""
    settings = {} if value is None else {"stop_instruction": value}
    write_config(tmp_path, settings)
    assert load_project_configuration(tmp_path).stop_instruction == expected


@pytest.mark.parametrize("value", [5, True, ["text"], {"text": "value"}])
def test_stop_instruction_rejects_present_non_text(tmp_path: Path, value: object) -> None:
    """A present setting that is not text stays an invalid configuration."""
    write_config(tmp_path, {"stop_instruction": value})
    with pytest.raises(ProjectConfigurationError):
        load_project_configuration(tmp_path)


def test_unknown_agent_runner_setting_is_still_rejected(tmp_path: Path) -> None:
    """The accepted key set stays closed around the one added setting."""
    write_config(tmp_path, {"stop_instructions": CUSTOM_TEXT})
    with pytest.raises(ProjectConfigurationError):
        load_project_configuration(tmp_path)


def test_codex_defaults_still_load_beside_the_stop_text(tmp_path: Path) -> None:
    """The added setting does not change how the project Codex defaults load."""
    codex = {"approval": {"model": "review", "base_url": "https://review.example/v1"}}
    write_config(tmp_path, {"stop_instruction": CUSTOM_TEXT}, codex)
    configuration = load_project_configuration(tmp_path)
    assert configuration.stop_instruction == CUSTOM_TEXT
    assert configuration.codex == codex


def test_omitted_stop_text_keeps_the_generic_guidance() -> None:
    """The default delivery keeps the existing non-empty generic instruction."""
    delivery = one_delivery(None)
    assert isinstance(delivery["instruction"], str) and delivery["instruction"]
    assert delivery["stop_id"] == "fd403ef4-1047-54e3-9eb3-ec71c26912eb"


def test_custom_stop_text_is_delivered_verbatim_beside_unchanged_facts() -> None:
    """A configured text travels word for word without rewriting stop facts."""
    custom = one_delivery(CUSTOM_TEXT)
    default = one_delivery(None)
    assert custom["instruction"] == CUSTOM_TEXT
    assert set(custom) == set(default)
    assert {key: value for key, value in custom.items() if key != "instruction"} == {
        key: value for key, value in default.items() if key != "instruction"
    }


def test_empty_stop_text_delivers_only_the_stop_facts() -> None:
    """An explicit empty text adds no work-method wording to the facts."""
    delivery = one_delivery("")
    assert "instruction" not in delivery
    assert set(delivery) == {
        "stop_id", "stop", "ticket", "triggered_at", "delivered_at", "elapsed",
    }


def _cli_document(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stop: bool) -> dict:
    """Drive the real CLI entry with or without a sampled stop on its channel."""
    from click.testing import CliRunner

    from graphtraj.interfaces.cli import agent_runner

    monkeypatch.setenv("CODEX_THREAD_ID", "thread-main")
    monkeypatch.delenv("GRAPHTRAJ_BUDGET_NOTICE_FD", raising=False)
    monkeypatch.delenv("GRAPHTRAJ_ROLE", raising=False)

    def operation(alias: str, cwd: Path) -> dict:
        if stop:
            descriptor, owned = caller_notice_fd()
            assert descriptor is not None
            try:
                os.write(descriptor, (json.dumps(STOP) + "\n").encode())
            finally:
                if owned:
                    os.close(descriptor)
        return {"alias": alias, "interrupt_status": "interrupted"}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(agent_runner, "interrupt_session", operation)
    result = CliRunner().invoke(agent_runner.main, ["interrupt", "engineer@e1"])
    assert result.exit_code == 0, result.output
    return yaml.safe_load(result.output)


def test_cli_delivers_the_configured_stop_text_to_its_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real CLI call returns the configured text with the stop it awaits."""
    write_config(tmp_path, {"stop_instruction": CUSTOM_TEXT})
    document = _cli_document(tmp_path, monkeypatch, stop=True)
    delivery = document["stop_deliveries"][0]
    assert delivery["instruction"] == CUSTOM_TEXT
    assert delivery["stop"] == "stochastic_stop:2"
    assert delivery["ticket"] == {"ticket_id": "116", "ticket_name": "session-budget-control"}


def test_cli_empty_stop_text_returns_facts_without_method_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicitly empty setting reaches the caller without wording."""
    write_config(tmp_path, {"stop_instruction": ""})
    delivery = _cli_document(tmp_path, monkeypatch, stop=True)["stop_deliveries"][0]
    assert "instruction" not in delivery
    assert delivery["elapsed"] == "00:02:00"


def test_cli_ordinary_completion_carries_no_stop_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A normal result is unchanged even when a custom stop text is configured."""
    write_config(tmp_path, {"stop_instruction": CUSTOM_TEXT})
    document = _cli_document(tmp_path, monkeypatch, stop=False)
    assert document["alias"] == "engineer@e1"
    assert "stop_deliveries" not in document


def test_mcp_delivers_the_configured_stop_text_to_the_request_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The request's own Codex caller receives the configured stop text."""
    from graphtraj.interfaces import mcp

    write_config(tmp_path, {"stop_instruction": CUSTOM_TEXT})
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GRAPHTRAJ_BUDGET_NOTICE_FD", raising=False)

    def handler(arguments: dict) -> mcp.ToolResult:
        descriptor, owned = caller_notice_fd()
        assert descriptor is not None
        try:
            os.write(descriptor, (json.dumps(STOP) + "\n").encode())
        finally:
            if owned:
                os.close(descriptor)
        return mcp.ToolResult({"tasks": []})

    monkeypatch.setitem(mcp.TOOLS, "probe", mcp.Tool("probe", "probe", {}, handler))
    response = mcp._tool_call_response(1, {
        "name": "probe", "arguments": {}, "_meta": {"threadId": "existing-caller"},
    })
    delivery = response["result"]["structuredContent"]["stop_deliveries"][0]
    assert delivery["instruction"] == CUSTOM_TEXT
    assert delivery["ticket"] == {"ticket_id": "116", "ticket_name": "session-budget-control"}


def test_ordinary_caller_notice_adds_no_stop_text() -> None:
    """An ordinary budget reminder stays inert on the caller channel."""
    reminder = {**STOP, "threshold": {"kind": "estimated_minutes", "limit": 2}}
    recovery = CodexMainRecovery(CUSTOM_TEXT)
    with recovery:
        with budget_notice_output(recovery.notice_fd):
            os.write(recovery.notice_fd, (json.dumps(reminder) + "\n").encode())
        document = recovery.attach_stop_deliveries({"tasks": []})
    assert "stop_deliveries" not in document
