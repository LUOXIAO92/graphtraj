"""Configured role groups resolve references and reach real launches."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, run_process
from graphtraj.configuration.project_roles import (
    ProjectRolesError,
    default_roles_content,
    load_project_roles,
)
from graphtraj.execution.runner_batch import read_batch
from runner_fixtures import configure_harness


# One normal coding group, one expert group, one extra top-level preset. The
# expert group repeats the Engineer name with its own Runtime settings.
TWO_GROUPS = """\
roles:
  coding_team:
    team_leader:
      runtime: codex
      model: gpt-5.6-sol
      allow_runtime_swarm: true
    engineer:
      runtime: codex
      model: gpt-5.6-sol
    standards_reviewer:
      runtime: codex
      model: gpt-5.6-sol
    spec_reviewer:
      runtime: codex
      model: gpt-5.6-sol
  coding_team_expert:
    engineer:
      runtime: codex
      model: gpt-6-astra
      reasoning_effort: middle
      base_url: https://astra.example/v1
      api_key_env: ASTRA_API_KEY
    data_engineer:
      runtime: codex
      model: gpt-6-astra
  delivery_state:
    runtime: codex
    model: gpt-5.6-luna
"""

DUPLICATE_ROLE = """\
roles:
  coding_team:
    engineer:
      runtime: codex
      model: gpt-5.6-sol
  engineer:
    runtime: codex
    model: gpt-6-astra
"""


def _write_roles(harness_root: Path, content: str) -> Path:
    """Write one roles.yml without touching any other project input."""
    path = harness_root / ".graphtraj" / "roles.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _batch_task(harness_root: Path, role: str) -> Path:
    """Write one single-task Batch that selects a role reference."""
    batch = harness_root / "batch.yml"
    batch.write_text(
        "tasks:\n"
        '  - ticket_id: "143"\n'
        "    ticket_name: configurable-role-dispatch\n"
        "    role: " + role + "\n",
        encoding="utf-8",
    )
    return batch


def test_two_groups_select_different_settings_for_one_role_name(
    tmp_path: Path,
) -> None:
    """A group selects Runtime settings without replacing the role name."""
    _write_roles(tmp_path, TWO_GROUPS)

    roles = load_project_roles(tmp_path)
    normal = roles.presets["coding_team.engineer"]
    expert = roles.presets["coding_team_expert.engineer"]

    assert (normal.model, normal.reasoning_effort) == ("gpt-5.6-sol", None)
    assert (expert.model, expert.reasoning_effort) == ("gpt-6-astra", "middle")
    assert (expert.base_url, expert.api_key_env) == (
        "https://astra.example/v1",
        "ASTRA_API_KEY",
    )

    task = read_batch(_batch_task(tmp_path, "coding_team_expert.engineer"), tmp_path).tasks[0]

    # The launched identity stays the role name; the reference keeps the group.
    assert task.role == "engineer"
    assert task.role_reference == "coding_team_expert.engineer"
    assert roles.preset(task.role_reference) == expert
    assert roles.preset("coding_team.engineer") == normal


def test_unconfigured_and_ambiguous_references_are_rejected(tmp_path: Path) -> None:
    """An unconfigured or duplicated reference never selects another group."""
    _write_roles(tmp_path, TWO_GROUPS)
    roles = load_project_roles(tmp_path)

    with pytest.raises(ProjectRolesError) as absent:
        roles.preset("coding_team_security.engineer")

    assert "coding_team_security.engineer" in str(absent.value)
    assert "is not a configured preset reference." in str(absent.value)

    # A bare name two groups declare names both groups instead of picking one.
    with pytest.raises(ProjectRolesError) as ambiguous:
        roles.preset("engineer")

    message = str(ambiguous.value)
    assert "coding_team.engineer" in message
    assert "coding_team_expert.engineer" in message

    # One group declaring a bare name, and one top-level preset, still resolve.
    assert roles.resolve("data_engineer") == "coding_team_expert.data_engineer"
    assert roles.preset("delivery_state").model == "gpt-5.6-luna"

    task = read_batch(_batch_task(tmp_path, "coding_team_security.engineer"), tmp_path).tasks[0]

    assert task.role_reference == "coding_team_security.engineer"
    assert task.role == "engineer"
    with pytest.raises(ProjectRolesError):
        roles.preset(task.role_reference)


def test_a_role_defined_twice_is_rejected(tmp_path: Path) -> None:
    """A top-level preset cannot repeat a role name one group already defines."""
    _write_roles(tmp_path, DUPLICATE_ROLE)

    with pytest.raises(ProjectRolesError) as error:
        load_project_roles(tmp_path)

    assert "engineer preset is defined more than once." in str(error.value)


def test_a_group_cannot_repeat_one_role_name(tmp_path: Path) -> None:
    """A repeated YAML key stays invalid configuration."""
    repeated = default_roles_content().replace(
        "    engineer:", "    engineer:\n      runtime: codex\n      model: gpt-6-astra\n    engineer:"
    )
    _write_roles(tmp_path, repeated)

    with pytest.raises(ProjectRolesError) as error:
        load_project_roles(tmp_path)

    assert "roles.yml is not readable valid YAML." in str(error.value)


def test_a_configured_group_reaches_a_real_launch(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """The extra group's model and effort reach the launched Session records."""
    harness_root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path
    )
    from test_ticket_graph import _change_status, _register, _ticket

    _register(installed_commands, harness_root, _ticket("143", "configurable-role-dispatch"))
    _change_status(installed_commands, harness_root, "143", "ready")

    document = yaml.safe_load(default_roles_content())
    document["roles"]["coding_team_experiment"] = {
        "team_leader": {
            "runtime": "codex",
            "model": "gpt-6-venus",
            "reasoning_effort": "low",
            "allow_runtime_swarm": False,
        },
    }
    _write_roles(harness_root, yaml.safe_dump(document, sort_keys=False))

    batch = _batch_task(harness_root, "coding_team_experiment.team_leader")
    environment.update(
        {
            "FAKE_CODEX_LIFECYCLE_ACTION": "complete-team-round",
            "FAKE_CODEX_CAPTURE_ROLE": "1",
            "FAKE_CODEX_APPEND_LOG": "1",
            "GRAPHTRAJ_AGENT_RUNNER": str(installed_commands.runner),
        }
    )

    launched = run_process(
        [str(installed_commands.runner), "--swarm-input", str(batch)],
        cwd=harness_root,
        env=environment,
        timeout=30,
    )

    assert launched.returncode == 0, launched.stderr
    records = [json.loads(line) for line in fake_codex.log_file.read_text().splitlines()]
    leaders = [record for record in records if record["role"] == "team-leader"]
    assert leaders
    assert all(
        record["argv"][record["argv"].index("--model") + 1] == "gpt-6-venus"
        for record in leaders
    )
    assert all(
        any(
            argument == "-c"
            and record["argv"][index + 1] == 'model_reasoning_effort="low"'
            for index, argument in enumerate(record["argv"][:-1])
        )
        for record in leaders
    )

    leader_alias = "143-configurable_role_dispatch-handover0-team_leader@team_leader"
    launch = yaml.safe_load(
        (
            harness_root / ".graphtraj/runner/sessions" / leader_alias / "launch.yml"
        ).read_text(encoding="utf-8")
    )
    assert launch["mapping"]["role"] == "team-leader"
    assert launch["mapping"]["role_reference"] == "coding_team_experiment.team_leader"
    assert launch["context_evidence"]["model"] == "gpt-6-venus"
    assert launch["context_evidence"]["model_reasoning_effort"] == "low"
