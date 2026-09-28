"""Configured role groups resolve references and reach real launches."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, run_process
from graphtraj.configuration.project_roles import (
    ProjectRolesError,
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

# One group declares the same role name twice; YAML keeps only the last key,
# so the document is not readable as the operator's intended configuration.
REPEATED_GROUP_ROLE = """\
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
    _write_roles(tmp_path, REPEATED_GROUP_ROLE)

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

    document = yaml.safe_load((harness_root / ".graphtraj/roles.yml").read_text())
    document["roles"]["coding_team_experiment"] = {
        "team_leader": {
            "runtime": "codex",
            "model": "gpt-6-venus",
            "worktree_access": "read",
            "reports": ["leader.md"],
            "reasoning_effort": "low",
            "allow_runtime_swarm": False,
        },
    }
    document["role_tree"]["coding_team_experiment.team_leader"] = {
        "coding-team.engineer": {},
        "coding-team.standards-reviewer": {},
        "coding-team.spec-reviewer": {},
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


@pytest.mark.parametrize('field, value', [
    ('instructions', ''), ('instructions', None), ('instructions', 12),
    ('instructions', 'bad\x00path'), ('worktree_access', 'all'),
    ('reports', ['../foreign.md']), ('reports', ['same.md', 'same.md']),
    ('harness_skills', ['../foreign']), ('allow_runtime_swarm', 'yes'),
])
def test_explicit_role_selections_reject_invalid_configuration(
    tmp_path: Path, field: str, value: object,
) -> None:
    """Selection fields cannot escape resource/report boundaries or widen access."""
    _write_roles(tmp_path, yaml.safe_dump({'roles': {'researcher': {
        'runtime': 'codex', 'model': 'chosen', field: value,
    }}}))
    with pytest.raises(ProjectRolesError, match=field):
        load_project_roles(tmp_path)


def test_explicit_role_content_is_independent_of_identity(tmp_path: Path) -> None:
    """A custom role selects professional content and generic access independently."""
    from graphtraj.configuration.role_definitions import resolve_child_role
    from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError

    _write_roles(tmp_path, yaml.safe_dump({'roles': {'researcher': {
        'runtime': 'codex', 'model': 'chosen', 'instructions': 'role text.txt',
        'worktree_access': 'read',
        'reports': ['findings.md', 'evidence.md'], 'allow_runtime_swarm': True,
    }}, 'role_tree': {'researcher': {}}}))
    (tmp_path / 'role text.txt').write_text('External role text.\nrequired_skills: [absent]\n', encoding='utf-8')
    roles = load_project_roles(tmp_path)
    preset = roles.preset('researcher')
    resolved = resolve_child_role('researcher', preset, tmp_path)
    assert resolved.name == 'researcher'
    # The role instructions are passed through verbatim: an embedded
    # required_skills line is text, not a Skill selection.
    assert resolved.instructions.startswith('External role text.\nrequired_skills: [absent]')
    assert resolved.allow_runtime_swarm
    assert preset.worktree_access == 'read'
    assert preset.reports == ('findings.md', 'evidence.md')
    assert not roles.permits_dispatch('researcher', 'engineer')
    from dataclasses import replace
    with pytest.raises(RuntimeAdapterError, match='Cannot read UTF-8 role instructions'):
        resolve_child_role('researcher', replace(preset, instructions='missing-resource'), tmp_path)


@pytest.mark.parametrize('reference', [
    'research_team.team_leader', 'custom.engineer', 'custom.standards_reviewer',
])
def test_role_names_do_not_select_content_or_access(tmp_path: Path, reference: str) -> None:
    """Same-name professional roles resolve exactly the generic selected content."""
    from graphtraj.configuration.project_roles import parse_inline_role
    from graphtraj.configuration.role_definitions import resolve_child_role

    name, preset = parse_inline_role({reference: {'runtime': 'codex', 'model': 'chosen'}})
    _, generic = parse_inline_role({'researcher': {'runtime': 'codex', 'model': 'chosen'}})
    resolved = resolve_child_role(name, preset, tmp_path)
    assert resolved.instructions == resolve_child_role('researcher', generic, tmp_path).instructions
    assert not resolved.allow_runtime_swarm
    assert preset.worktree_access == 'write'
    assert preset.reports == ()


@pytest.mark.parametrize('field', ['skills', 'required_skills', 'harness_skills'])
def test_new_role_name_selection_directs_caller_to_native_resources(
    field: str, tmp_path: Path,
) -> None:
    """New role fields fail; retained inline input stays readable without mutation."""
    from graphtraj.configuration.project_roles import ProjectRolesError, parse_inline_role

    selection = {'author': {'runtime': 'codex', 'model': 'chosen', field: ['old-method']}}
    with pytest.raises(ProjectRolesError, match='Runtime native Skill selection'):
        parse_inline_role(selection)
    retained = tmp_path / 'retained.yml'
    content = yaml.safe_dump({'tasks': [{
        'ticket_id': '177', 'ticket_name': 'retained-inline', 'role': selection,
    }]}).encode()
    retained.write_bytes(content)
    batch = read_batch(retained, tmp_path)
    assert batch.tasks[0].inline_preset.model == 'chosen'
    assert batch.source_bytes == retained.read_bytes() == content
    assert selection['author'][field] == ['old-method']


@pytest.mark.parametrize('skills', [[], ['missing'], ['duplicate', 'duplicate']])
def test_new_swarm_rejects_name_selection_but_retained_batch_stays_readable(
    tmp_path: Path, skills: list[str],
) -> None:
    """First launch rejects retired input without rewriting valid old records."""
    from graphtraj.execution.runner_batch import parse_swarm, read_batch
    from graphtraj.execution.runner_models import RunnerError

    document = {'tasks': [{'ticket_id': '176', 'ticket_name': 'native-skills',
                          'role': 'author', 'skills': skills}]}
    with pytest.raises(RunnerError, match='Runtime native Skill selection'):
        parse_swarm(document, None, {'176': 'native-skills'})
    if len(skills) == len(set(skills)):
        retained = tmp_path / 'retained.yml'
        content = yaml.safe_dump(document).encode()
        retained.write_bytes(content)
        batch = read_batch(retained, tmp_path)
        assert batch.tasks[0].requested_skills == tuple(skills)
        assert batch.source_bytes == retained.read_bytes() == content
