from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import tomllib
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, run_process, wait_for_file
from runner_fixtures import engineer_probe
from test_project_setup import (
    CORE_SKILL_NAMES,
    install_skills,
    supported_skill_contents,
    tree_contents,
    run_ready_setup,
)


def wait_for_probe_completion(commands, alias, harness_root, environment):
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        result = run_process(
            [str(commands.runner), 'status', alias],
            cwd=harness_root, env=environment, timeout=15,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        status = yaml.safe_load(result.stdout)['aliases'][0]
        if status['activity'] == 'idle':
            assert status['last_outcome'] == 'completed', status
            return
        time.sleep(1)
    interrupted = run_process(
        [str(commands.runner), 'interrupt', alias],
        cwd=harness_root, env=environment, timeout=30,
    )
    raise AssertionError('Probe timed out; Runner interruption: ' + interrupted.stdout + interrupted.stderr)


def wait_for_probe_artifacts(commands, alias, harness_root, environment, proofs, timeout=300):
    deadline = time.monotonic() + timeout
    while not all(path.is_file() for path in proofs) and time.monotonic() < deadline:
        time.sleep(1)
    result = run_process(
        [str(commands.runner), 'status', alias],
        cwd=harness_root, env=environment, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    if yaml.safe_load(result.stdout)['aliases'][0]['activity'] != 'idle':
        interrupted = run_process(
            [str(commands.runner), 'interrupt', alias],
            cwd=harness_root, env=environment, timeout=30,
        )
        assert interrupted.returncode == 0, interrupted.stdout + interrupted.stderr
    assert all(path.is_file() for path in proofs), 'Missing probe proofs: ' + ', '.join(
        str(path) for path in proofs if not path.is_file()
    )


@pytest.mark.parametrize('missing_proof', (False, True))
def test_probe_artifact_boundary_interrupts_running_runtime(
    installed_commands, temporary_git_repository, fake_codex, tmp_path, missing_proof,
):
    from runner_fixtures import configure_harness

    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    # The live probe starts with a Runtime environment without fake log settings.
    environment.pop('FAKE_CODEX_LOG', None)
    environment['FAKE_CODEX_RELEASE_FILE'] = str(tmp_path / 'hold-runtime')
    with engineer_probe(installed_commands, harness, fake_codex, environment) as (alias, _, env):
        proofs = [fake_codex.log_file, tmp_path / 'missing'] if missing_proof else [fake_codex.log_file]
        if missing_proof:
            with pytest.raises(AssertionError, match='Missing probe proofs'):
                wait_for_probe_artifacts(installed_commands, alias, harness, env, proofs, timeout=0)
        else:
            wait_for_probe_artifacts(installed_commands, alias, harness, env, proofs)
        status = run_process(
            [str(installed_commands.runner), 'status', alias], cwd=harness, env=env,
        )
        assert status.returncode == 0, status.stderr
        assert yaml.safe_load(status.stdout)['aliases'][0]['last_outcome'] == 'interrupted'


@pytest.mark.parametrize('same_root', (False, True))
def test_installed_runtime_projects_enabled_external_skill_directories(
    installed_commands, temporary_git_repository, fake_codex, tmp_path, same_root,
):
    harness = temporary_git_repository if same_root else temporary_git_repository.parent
    user_home = tmp_path / 'operator-home'
    install_skills(user_home / '.agents' / 'skills', CORE_SKILL_NAMES)
    setup = run_ready_setup(
        installed_commands, harness_root=harness, user_home=user_home,
        fake_codex=fake_codex, answers='y\n',
    )
    assert setup.returncode == 0, setup.stderr
    environment = dict(os.environ, HOME=str(user_home), FAKE_CODEX_LOG=str(fake_codex.log_file))
    environment['PATH'] = str(fake_codex.executable.parent) + os.pathsep + environment['PATH']
    user_skills = Path(environment['HOME']) / '.agents' / 'skills'
    harness_skill = harness / '.agents' / 'skills' / 'implement' / 'SKILL.md'
    assert harness_skill.is_file()
    unselected = harness_skill.parent.parent / 'unselected' / 'SKILL.md'
    unselected.parent.mkdir()
    unselected.write_text('---\nname: unselected\ndescription: Unselected.\n---\n')
    reference = harness_skill.parent.parent / 'ponytail' / 'tests.md'
    with engineer_probe(installed_commands, harness, fake_codex, environment):
        records = [json.loads(line) for line in fake_codex.log_file.read_text().splitlines()]
        arguments = next(record['argv'] for record in records if record['role'] == 'engineer')
    settings = {}
    for index, argument in enumerate(arguments[:-1]):
        if argument == '-c':
            settings.update(tomllib.loads(arguments[index + 1]))
    filesystem = settings['permissions'][settings['default_permissions']]['filesystem']
    selected_directories = {
        str(Path(skill['path']).parent)
        for skill in settings['skills']['config']
        if skill['enabled']
    }
    assert str(harness_skill.parent) in selected_directories
    assert str(reference.parent) in selected_directories
    assert all(filesystem[directory] == 'read' for directory in selected_directories)
    assert str(unselected.parent) not in filesystem
    assert str(user_skills / 'ponytail') not in filesystem
    assert '--dangerously-bypass-hook-trust' not in arguments
    assert not any(argument.startswith('hooks=') for argument in arguments)


def _engineer_role(
    model: str = "gpt-5.6-sol", reasoning_effort: str | None = None
):
    from graphtraj.configuration.project_roles import RolePreset
    from graphtraj.configuration.role_definitions import resolve_child_role

    return resolve_child_role(
        "engineer",
        RolePreset("codex", model, None, None, reasoning_effort=reasoning_effort),
    )


def _role_with_required_skill(name: str):
    from graphtraj.configuration.project_roles import RolePreset
    from graphtraj.configuration.role_definitions import ResolvedChildRole

    return ResolvedChildRole(
        name="standards-reviewer",
        instructions="Use ${0}.".format(name),
        required_skills=(name,),
        settings=RolePreset("codex", "gpt-5.6-sol", None, None),
    )


def _runtime_executable(tmp_path: Path) -> Path:
    executable = tmp_path / "codex"
    executable.write_text(
        "#!/bin/sh\necho --sandbox\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def test_preflight_selects_the_first_duplicate_harness_skill(
    monkeypatch: pytest.MonkeyPatch,
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "src"))
    from graphtraj.runtimes.codex.codex_adapter import preflight_runtime_context

    harness_root = tmp_path / "harness-project"
    skill_root = harness_root / ".agents" / "skills"
    first = skill_root / "a-first" / "SKILL.md"
    second = skill_root / "z-second" / "SKILL.md"
    for skill in (first, second):
        skill.parent.mkdir(parents=True)
        skill.write_text(
            "---\nname: role-only\ndescription: Test Skill.\n---\n",
            encoding="utf-8",
        )
    user_home = tmp_path / "runtime-user"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    worktree = tmp_path / "ticket-worktree"
    evidence = tmp_path / "evidence"
    worktree.mkdir()
    evidence.mkdir()

    context = preflight_runtime_context(
        runtime_store=harness_root / ".codex",
        executable=_runtime_executable(tmp_path),
        git_common_directory=temporary_git_repository / ".git",
        role=_role_with_required_skill("role-only"),
        worktree=worktree,
        evidence=evidence,
        repository_skill_source=temporary_git_repository,
        requested_skills=(),
    ).finalize()

    assert context.evidence_document()["effective_skills"] == [
        {
            "name": "role-only",
            "path": str(first.resolve()),
            "enabled": True,
            "source": "harness",
        }
    ]


@pytest.mark.parametrize("link_kind", ("directory", "skill-file"))
def test_preflight_projects_a_linked_harness_skill_at_its_canonical_path(
    monkeypatch: pytest.MonkeyPatch,
    temporary_git_repository: Path,
    tmp_path: Path,
    link_kind: str,
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "src"))
    from graphtraj.runtimes.codex.codex_adapter import preflight_runtime_context

    harness_root = tmp_path / "harness-project"
    skill_root = harness_root / ".agents" / "skills"
    target = tmp_path / "external-skill"
    target.mkdir()
    target_skill = target / "SKILL.md"
    target_skill.write_text(
        "---\nname: role-only\ndescription: Test Skill.\n---\n",
        encoding="utf-8",
    )
    reference = target / "references" / "native.md"
    reference.parent.mkdir()
    reference.write_text("reference\n", encoding="utf-8")
    if link_kind == "directory":
        skill_root.mkdir(parents=True)
        (skill_root / "linked-skill").symlink_to(target, target_is_directory=True)
    else:
        linked_skill = skill_root / "linked-skill" / "SKILL.md"
        linked_skill.parent.mkdir(parents=True)
        linked_skill.symlink_to(target_skill)
    user_home = tmp_path / "runtime-user"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    worktree = tmp_path / "ticket-worktree"
    evidence = tmp_path / "evidence"
    worktree.mkdir()
    evidence.mkdir()

    context = preflight_runtime_context(
        runtime_store=harness_root / ".codex",
        executable=_runtime_executable(tmp_path),
        git_common_directory=temporary_git_repository / ".git",
        role=_role_with_required_skill("role-only"),
        worktree=worktree,
        evidence=evidence,
        repository_skill_source=temporary_git_repository,
        requested_skills=(),
    ).finalize()

    expected_skill = target_skill.resolve()
    arguments = context.launch_document()["adapter_request"]["arguments"]
    settings = {}
    for index, argument in enumerate(arguments[:-1]):
        if argument == "-c":
            settings.update(tomllib.loads(arguments[index + 1]))
    filesystem = settings["permissions"][settings["default_permissions"]][
        "filesystem"
    ]
    assert settings["skills"]["config"] == [
        {"path": str(expected_skill), "enabled": True}
    ]
    assert filesystem[str(expected_skill.parent)] == "read"
    assert reference.is_relative_to(expected_skill.parent)
    assert context.evidence_document()["effective_skills"] == [
        {
            "name": "role-only",
            "path": str(expected_skill),
            "enabled": True,
            "source": "harness",
        }
    ]


def test_setup_creates_a_root_owned_runtime_and_runner_discovers_it(
    monkeypatch,
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "src")
    )
    from graphtraj.workspace.project_initialization import plan_project_setup
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.workspace.runner_project import discover_project

    harness_root = temporary_git_repository.parent
    primary = temporary_git_repository
    integration = harness_root / ".graphtraj" / ".agent-worktrees" / "dev"
    runtime_store = harness_root / ".codex"
    user_home = tmp_path / "runtime-user"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    source_config = primary / ".codex" / "config.toml"
    source_config.parent.mkdir()
    source_config.write_text("model = \"source-owned\"\n", encoding="utf-8")
    run_process(["git", "add", ".codex"], cwd=primary).check_returncode()
    run_process(
        ["git", "commit", "-m", "Add source Runtime fixtures"], cwd=primary
    ).check_returncode()
    source_before = source_config.read_bytes()

    runtime = _runtime_executable(tmp_path)
    monkeypatch.setenv(
        "PATH", os.pathsep.join((str(runtime.parent), os.environ.get("PATH", "")))
    )
    install_skills(user_home / ".agents" / "skills", ("implement", "ponytail", "tdd"))
    plan = plan_project_setup(harness_root, primary)
    assert plan.apply().integration_action == "created"

    project = discover_project(harness_root)
    assert project.harness_root == harness_root.resolve()
    assert project.runner_directory == harness_root / ".graphtraj" / "runner"
    assert project.integration_worktree == integration.resolve()
    assert not (runtime_store / "config.toml").exists()
    assert (harness_root / ".graphtraj" / "runner").is_dir()
    assert not (runtime_store / "agent-runner" / "config.yml").exists()
    assert not (harness_root / ".agents").exists()
    assert source_config.read_bytes() == source_before
    assert (integration / ".state").resolve() == (
        harness_root / ".graphtraj" / "state"
    ).resolve()
    with pytest.raises(RunnerError) as non_root:
        discover_project(integration)
    assert non_root.value.code == "PROJECT_CONFIG_MISMATCH"


def test_setup_installs_project_core_skills_even_with_user_copies(
    monkeypatch,
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "src")
    )
    from graphtraj.runtimes.codex.codex_adapter import (
        preflight_runtime_context,
    )
    from graphtraj.workspace.project_initialization import plan_project_setup

    harness_root = temporary_git_repository.parent
    user_home = tmp_path / "runtime-user"
    install_skills(user_home / ".agents" / "skills", CORE_SKILL_NAMES)
    monkeypatch.setenv("HOME", str(user_home))

    plan = plan_project_setup(harness_root, temporary_git_repository)
    assert plan.apply(install_missing_skills=True).integration_action == "created"

    runtime_store = harness_root / ".codex"
    assert not (runtime_store / "config.toml").exists()
    for name in CORE_SKILL_NAMES:
        assert (harness_root / ".agents/skills" / name / "SKILL.md").is_file()
        assert (user_home / ".agents/skills" / name / "SKILL.md").is_file()
    preflight_runtime_context(
        runtime_store=runtime_store,
        executable=_runtime_executable(tmp_path),
        git_common_directory=temporary_git_repository / ".git",
        role=_engineer_role(),
        worktree=tmp_path / "ticket-worktree",
        evidence=tmp_path / "evidence",
        repository_skill_source=(
            harness_root / ".graphtraj" / ".agent-worktrees" / "dev"
        ),
        requested_skills=(),
    )


def test_engineer_runtime_context_preflight_validates_without_launch_artifacts(
    monkeypatch,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "src")
    )
    from graphtraj.runtimes.codex.codex_adapter import (
        CodexAdapterError,
        preflight_runtime_context,
    )
    from graphtraj.workspace.project_initialization import plan_project_setup

    harness_root = temporary_git_repository.parent
    user_home = tmp_path / "runtime-user"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    install_skills(user_home / ".agents" / "skills", ("implement", "ponytail", "tdd"))
    plan = plan_project_setup(harness_root, temporary_git_repository)
    plan.apply()

    runtime_store = harness_root / ".codex"
    target_worktree = tmp_path / "ticket-worktree"
    evidence = tmp_path / "evidence"
    user_config = user_home / ".codex" / "config.toml"
    user_config.parent.mkdir()
    user_config.write_text('sandbox_mode = "workspace-write"\n', encoding="utf-8")

    with pytest.raises(CodexAdapterError) as legacy_sandbox:
        preflight_runtime_context(
            runtime_store=runtime_store,
            executable=fake_codex.executable,
            git_common_directory=temporary_git_repository / ".git",
            role=_engineer_role(),
            worktree=target_worktree,
            evidence=evidence,
            repository_skill_source=(
                harness_root / ".graphtraj" / ".agent-worktrees" / "dev"
            ),
            requested_skills=(),
        )
    assert legacy_sandbox.value.code == "LEGACY_SANDBOX_CONFIG_CONFLICT"
    assert not target_worktree.exists()
    assert not evidence.exists()
    assert not fake_codex.log_file.exists()

    user_config.unlink()
    preflight_runtime_context(
        runtime_store=runtime_store,
        executable=fake_codex.executable,
        git_common_directory=temporary_git_repository / ".git",
        role=_engineer_role(),
        worktree=target_worktree,
        evidence=evidence,
        repository_skill_source=(
            harness_root / ".graphtraj" / ".agent-worktrees" / "dev"
        ),
        requested_skills=(),
    )
    assert not target_worktree.exists()
    assert not evidence.exists()
    assert not fake_codex.log_file.exists()

    (user_home / ".agents" / "skills" / "implement" / "SKILL.md").unlink()

    with pytest.raises(CodexAdapterError) as unavailable:
        preflight_runtime_context(
            runtime_store=runtime_store,
            executable=fake_codex.executable,
            git_common_directory=temporary_git_repository / ".git",
            role=_engineer_role(),
            worktree=target_worktree,
            evidence=evidence,
            repository_skill_source=(
                harness_root / ".graphtraj" / ".agent-worktrees" / "dev"
            ),
            requested_skills=(),
        )
    assert unavailable.value.code == "HARNESS_SKILL_NOT_FOUND"
    assert not target_worktree.exists()
    assert not evidence.exists()
    assert not fake_codex.log_file.exists()


def test_runtime_preflight_uses_fixed_policy_and_selected_model(
    monkeypatch,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "src")
    )
    from graphtraj.runtimes.codex.codex_adapter import preflight_runtime_context
    from graphtraj.workspace.project_initialization import plan_project_setup

    harness_root = temporary_git_repository.parent
    user_home = tmp_path / "runtime-user"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    install_skills(user_home / ".agents" / "skills", ("implement", "ponytail", "tdd"))
    plan = plan_project_setup(harness_root, temporary_git_repository)
    plan.apply()
    runtime_store = harness_root / ".codex"
    role_path = runtime_store / "agents" / "engineer.toml"
    role_path.parent.mkdir()
    role_path.write_text(
        "name = 'engineer'\nmodel = 'legacy-projection-model'\n",
        encoding="utf-8",
    )

    def preflight():
        return preflight_runtime_context(
            runtime_store=runtime_store,
            executable=fake_codex.executable,
            git_common_directory=temporary_git_repository / ".git",
            role=_engineer_role("project-engineer"),
            worktree=tmp_path / "ticket-worktree",
            evidence=tmp_path / "evidence",
            repository_skill_source=(
                harness_root / ".graphtraj" / ".agent-worktrees" / "dev"
            ),
            requested_skills=(),
        )

    arguments = preflight().finalize().launch_document()["adapter_request"][
        "arguments"
    ]
    assert "project-engineer" in arguments


@pytest.mark.parametrize(
    ("skill_directories", "requested_skill", "expected_code"),
    (
        ((), "missing", "REPOSITORY_SKILL_NOT_FOUND"),
        (
            (("duplicate-one", "duplicate"), ("duplicate-two", "duplicate")),
            "duplicate",
            "REPOSITORY_SKILL_AMBIGUOUS",
        ),
    ),
)
def test_engineer_runtime_context_preflight_rejects_unresolved_repository_skills(
    monkeypatch,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    skill_directories: tuple[tuple[str, str], ...],
    requested_skill: str,
    expected_code: str,
) -> None:
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "src")
    )
    from graphtraj.runtimes.codex.codex_adapter import (
        CodexAdapterError,
        preflight_runtime_context,
    )
    from graphtraj.workspace.project_initialization import plan_project_setup

    harness_root = temporary_git_repository.parent
    user_home = tmp_path / "runtime-user"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    install_skills(user_home / ".agents" / "skills", ("implement", "ponytail", "tdd"))
    plan = plan_project_setup(harness_root, temporary_git_repository)
    plan.apply()
    source = harness_root / ".graphtraj" / ".agent-worktrees" / "dev"
    for directory, name in skill_directories:
        skill = source / ".agents" / "skills" / directory / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            "---\nname: {0}\ndescription: test\n---\n".format(name),
            encoding="utf-8",
        )
    worktree = tmp_path / "ticket-worktree"
    evidence = tmp_path / "evidence"

    with pytest.raises(CodexAdapterError) as raised:
        preflight_runtime_context(
            runtime_store=harness_root / ".codex",
            executable=fake_codex.executable,
            git_common_directory=temporary_git_repository / ".git",
            role=_engineer_role(),
            worktree=worktree,
            evidence=evidence,
            repository_skill_source=source,
            requested_skills=(requested_skill,),
        )

    assert raised.value.code == expected_code
    assert not worktree.exists()
    assert not evidence.exists()
    assert not fake_codex.log_file.exists()


@pytest.mark.parametrize(
    ("reasoning_effort", "expected_effort"),
    ((None, "max"), ("high", "high")),
)
def test_engineer_runtime_context_finalizes_worktree_facts_once(
    monkeypatch,
    temporary_git_repository: Path,
    tmp_path: Path,
    reasoning_effort: str | None,
    expected_effort: str,
) -> None:
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "src")
    )
    from graphtraj.runtimes.codex.codex_adapter import (
        preflight_runtime_context,
    )
    from graphtraj.workspace.project_initialization import plan_project_setup

    harness_root = temporary_git_repository.parent
    user_home = tmp_path / "runtime-user"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    install_skills(user_home / ".agents" / "skills", ("implement", "ponytail", "tdd"))
    plan = plan_project_setup(harness_root, temporary_git_repository)
    plan.apply()
    runtime_store = harness_root / ".codex"
    source = tmp_path / "integration"
    ticket = tmp_path / "ticket-worktree"
    evidence = tmp_path / "evidence"
    git_common = tmp_path / "git-common"
    for root in (source, ticket):
        selected = root / ".agents" / "skills" / "repo-selected" / "SKILL.md"
        disabled = root / ".agents" / "skills" / "repo-disabled" / "SKILL.md"
        selected.parent.mkdir(parents=True)
        disabled.parent.mkdir(parents=True)
        selected.write_text(
            "---\nname: repo-selected\ndescription: selected\n---\n",
            encoding="utf-8",
        )
        disabled.write_text(
            "---\nname: repo-disabled\ndescription: disabled\n---\n",
            encoding="utf-8",
        )
    evidence.mkdir()
    git_common.mkdir()
    preflight = preflight_runtime_context(
        runtime_store=runtime_store,
        executable=_runtime_executable(tmp_path),
        worktree=ticket,
        evidence=evidence,
        git_common_directory=git_common,
        role=_engineer_role(reasoning_effort=reasoning_effort),
        repository_skill_source=source,
        requested_skills=("repo-selected",),
    )

    context = preflight.finalize()
    launch = context.launch_document()
    evidence_document = context.evidence_document()

    assert launch["runtime"] == "codex"
    assert launch["adapter_request"]["worktree_path"] == str(ticket)
    assert evidence_document["runtime"] == "codex"
    assert evidence_document["effective_role"] == "engineer"
    assert evidence_document["model"] == "gpt-5.6-sol"
    assert evidence_document["model_reasoning_effort"] == expected_effort
    assert 'model_reasoning_effort="{0}"'.format(expected_effort) in launch[
        "adapter_request"
    ]["arguments"]
    assert {
        skill["name"]
        for skill in evidence_document["effective_skills"]
        if skill["source"] == "runtime-user"
    } == {"implement", "ponytail"}
    repository_skills = {
        skill["name"]: skill
        for skill in evidence_document["effective_skills"]
        if skill["source"] == "repository"
    }
    assert repository_skills["repo-selected"]["enabled"]
    assert not repository_skills["repo-disabled"]["enabled"]
    assert Path(repository_skills["repo-selected"]["path"]) == (
        ticket / ".agents" / "skills" / "repo-selected" / "SKILL.md"
    )
    settings = {}
    arguments = launch["adapter_request"]["arguments"]
    for index, argument in enumerate(arguments[:-1]):
        if argument == "-c":
            settings.update(tomllib.loads(arguments[index + 1]))
    filesystem = settings["permissions"][settings["default_permissions"]][
        "filesystem"
    ]
    workspace_roots = filesystem[":workspace_roots"]
    assert workspace_roots["."] == "write"
    assert workspace_roots["CONTEXT.md"] == "read"
    assert workspace_roots["docs"] == "read"
    assert "README.md" not in workspace_roots
    assert all(
        filesystem[str(Path(skill["path"]).parent)] == "read"
        for skill in settings["skills"]["config"]
        if skill["enabled"]
    )
    assert str(ticket / ".agents" / "skills" / "repo-disabled") not in filesystem
    launch["adapter_request"].clear()
    assert context.launch_document()["adapter_request"]["worktree_path"] == str(
        ticket
    )
    evidence_document["effective_skills"].clear()
    assert {
        skill["name"]
        for skill in context.evidence_document()["effective_skills"]
        if skill["source"] == "runtime-user"
    } == {"implement", "ponytail"}


def test_installed_runner_uses_runtime_user_core_skill_when_source_tracks_it(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    repository = temporary_git_repository
    source_skill = repository / ".agents" / "skills" / "repository-implement" / "SKILL.md"
    source_skill.parent.mkdir(parents=True)
    source_skill.write_text(
        "---\nname: implement\ndescription: Repository Skill.\n---\n",
        encoding="utf-8",
    )
    run_process(["git", "add", ".agents"], cwd=repository).check_returncode()
    run_process(
        ["git", "commit", "-m", "Add repository implement Skill"], cwd=repository
    ).check_returncode()
    runtime_user = tmp_path / "runtime-user"
    install_skills(runtime_user / ".agents" / "skills", CORE_SKILL_NAMES)
    environment = os.environ.copy()
    environment["HOME"] = str(runtime_user)
    environment["PATH"] = "{0}{1}{2}".format(
        fake_codex.executable.parent,
        os.pathsep,
        environment.get("PATH", ""),
    )
    environment["FAKE_CODEX_LOG"] = str(fake_codex.log_file)

    setup = subprocess.run(
        [str(installed_commands.product), "setup"],
        cwd=repository,
        env=environment,
        input="y\ny\n",
        check=False,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert setup.returncode == 0, setup.stderr
    # An existing project may lose its local copy; Runner still resolves the user Skill.
    shutil.rmtree(repository / ".agents/skills/implement")

    with engineer_probe(installed_commands, repository, fake_codex, environment) as (alias, worktree, _):
        records = [json.loads(line) for line in fake_codex.log_file.read_text().splitlines()]
        arguments = next(record["argv"] for record in records if record["role"] == "engineer")
    task = {"alias": alias, "worktree_path": str(worktree)}
    skills_argument = next(
        argument for argument in arguments if argument.startswith("skills=")
    )
    configured_skills = tomllib.loads(
        "value = {0}".format(skills_argument.removeprefix("skills="))
    )["value"]["config"]
    runtime_user_skill = runtime_user / ".agents" / "skills" / "implement" / "SKILL.md"
    ticket_source_skill = (
        Path(task["worktree_path"])
        / ".agents"
        / "skills"
        / "repository-implement"
        / "SKILL.md"
    )
    assert {"path": str(runtime_user_skill.resolve()), "enabled": True} in configured_skills
    assert {"path": str(ticket_source_skill.resolve()), "enabled": False} in configured_skills
    assert {"path": str(source_skill.resolve()), "enabled": True} not in configured_skills


def test_installed_runner_uses_runtime_user_skill_from_newer_primary_history(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    repository = temporary_git_repository
    run_process(["git", "branch", "dev"], cwd=repository).check_returncode()
    source_skill = repository / ".agents" / "skills" / "repository-implement" / "SKILL.md"
    source_skill.parent.mkdir(parents=True)
    source_skill.write_text(
        "---\nname: implement\ndescription: Repository Skill.\n---\n",
        encoding="utf-8",
    )
    run_process(["git", "add", ".agents"], cwd=repository).check_returncode()
    run_process(
        ["git", "commit", "-m", "Add repository implement Skill after dev"],
        cwd=repository,
    ).check_returncode()
    assert run_process(
        ["git", "rev-parse", "dev"], cwd=repository
    ).stdout.strip() != run_process(["git", "rev-parse", "HEAD"], cwd=repository).stdout.strip()
    runtime_user = tmp_path / "runtime-user"
    install_skills(runtime_user / ".agents" / "skills", CORE_SKILL_NAMES)
    environment = os.environ.copy()
    environment["HOME"] = str(runtime_user)
    environment["PATH"] = "{0}{1}{2}".format(
        fake_codex.executable.parent,
        os.pathsep,
        environment.get("PATH", ""),
    )
    environment["FAKE_CODEX_LOG"] = str(fake_codex.log_file)

    setup = subprocess.run(
        [str(installed_commands.product), "setup"],
        cwd=repository,
        env=environment,
        input="y\n",
        check=False,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert setup.returncode == 0, setup.stderr
    # An existing project may lose its local copy; Runner still resolves the user Skill.
    shutil.rmtree(repository / ".agents/skills/implement")

    with engineer_probe(installed_commands, repository, fake_codex, environment) as (alias, worktree, _):
        records = [json.loads(line) for line in fake_codex.log_file.read_text().splitlines()]
        arguments = next(record["argv"] for record in records if record["role"] == "engineer")
    task = {"alias": alias, "worktree_path": str(worktree)}
    skills_argument = next(
        argument for argument in arguments if argument.startswith("skills=")
    )
    configured_skills = tomllib.loads(
        "value = {0}".format(skills_argument.removeprefix("skills="))
    )["value"]["config"]
    runtime_user_skill = runtime_user / ".agents" / "skills" / "implement" / "SKILL.md"
    assert {"path": str(runtime_user_skill.resolve()), "enabled": True} in configured_skills
    assert {"path": str(source_skill.resolve()), "enabled": True} not in configured_skills


@pytest.mark.skipif(
    os.environ.get("CODEX_REAL_ACCEPTANCE") != "1"
    or shutil.which("codex") is None,
    reason="set CODEX_REAL_ACCEPTANCE=1 with an authenticated codex executable",
)
def test_real_codex_uses_native_permissions_and_explicit_skill_configuration(
    mutable_installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """Exercise native Runtime permissions against a real Codex process."""

    harness_root = temporary_git_repository.parent
    primary = temporary_git_repository
    for name, proof_file in (
        ("repository-selected", ".repository-selected-skill-proof"),
        ("repository-disabled", ".repository-disabled-skill-proof"),
    ):
        skill = primary / ".agents" / "skills" / name / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            "---\n"
            "name: {0}\n"
            "description: Creates its proof file for the Harness Skill acceptance probe.\n"
            "---\n\n"
            "When asked to perform the Harness Skill acceptance probe, use "
            "apply_patch to create `{1}` containing `{0}`.\n".format(
                name, proof_file
            ),
            encoding="utf-8",
        )
    run_process(
        ["git", "add", ".agents"], cwd=primary
    ).check_returncode()
    run_process(
        ["git", "commit", "-m", "Add isolated Runtime fixtures"],
        cwd=primary,
    ).check_returncode()
    project_skill_before = (
        primary
        / ".agents"
        / "skills"
        / "repository-selected"
        / "SKILL.md"
    ).read_bytes()

    runtime_user = tmp_path / "runtime-user"
    runtime_user.mkdir()
    runtime_environment = os.environ.copy()
    environment = runtime_environment.copy()
    environment["HOME"] = str(runtime_user)
    setup = subprocess.run(
        [str(mutable_installed_commands.product), "setup"],
        cwd=harness_root,
        env=environment,
        input="y\ny\n",
        check=False,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert setup.returncode == 0, setup.stderr

    harness_skill = (
        harness_root / ".agents" / "skills" / "implement" / "SKILL.md"
    )
    reference = harness_skill.parent / "references" / "native.md"
    reference.parent.mkdir()
    reference.write_text("native reference\n", encoding="utf-8")
    harness_skill.write_text(
        "---\n"
        "name: implement\n"
        "description: Creates its proof file for the Harness Skill acceptance probe.\n"
        "---\n\n"
        "When asked to perform the Harness Skill acceptance probe, first use "
        "Bash cat to read `{0}`. Then use apply_patch to create "
        "`.external-reference-proof` containing `native reference`, create "
        "`.harness-skill-proof` containing `implement`, and replace README.md "
        "with `# Native README`. Finally, separately attempt to replace "
        "`.agents/skills/repository-selected/SKILL.md`; continue if native "
        "permissions deny that write. Only after both the README change and "
        "that separate attempt, use apply_patch to create "
        "`.native-permissions-complete-proof` containing `complete`.\n".format(reference),
        encoding="utf-8",
    )
    for name in ("ponytail", "tdd", "code-review"):
        no_action_skill = (
            harness_root / ".agents" / "skills" / name / "SKILL.md"
        )
        no_action_skill.write_text(
            "---\n"
            "name: {0}\n"
            "description: Takes no action for the Harness Skill acceptance probe.\n"
            "---\n\n"
            "When asked to perform the Harness Skill acceptance probe, take no action.\n".format(
                name
            ),
            encoding="utf-8",
        )

    ticket_file = harness_root / "tickets" / "real-codex.md"
    ticket_file.parent.mkdir()
    ticket_file.write_text(
        "# Real Codex native permissions\n\n"
        "This is only the Harness Skill acceptance probe. Read enabled Skill "
        "files with Bash cat using their supplied paths. "
        "Do not explore the repository, run implementation or Review workflows, "
        "commit, or delegate. The test Skills stub those workflows. "
        "Perform the Harness Skill acceptance probe. Follow every enabled Skill "
        "that instructs you to create a proof file; use apply_patch for each "
        "requested proof file, and do not create a proof file unless an enabled "
        "Skill instructs it. Then use Bash to run `pwd` once and reply with "
        "`ROOT_RUNTIME_OK`.\n",
        encoding="utf-8",
    )
    runtime_environment["FAKE_CODEX_ENGINEER_SKILLS"] = '["repository-selected"]'
    real_codex = shutil.which("codex")
    assert real_codex is not None
    with engineer_probe(
        mutable_installed_commands, harness_root, fake_codex, runtime_environment,
        body=ticket_file.read_text(), executable=real_codex,
    ) as (alias, ticket_worktree, probe_environment):
        wait_for_probe_artifacts(
            mutable_installed_commands, alias, harness_root, probe_environment,
            [
                ticket_worktree / '.harness-skill-proof',
                ticket_worktree / '.external-reference-proof',
                ticket_worktree / '.repository-selected-skill-proof',
                ticket_worktree / '.native-permissions-complete-proof',
            ],
        )
    assert (ticket_worktree / ".harness-skill-proof").read_text(
        encoding="utf-8"
    ).strip() == "implement"
    assert (ticket_worktree / ".external-reference-proof").read_text(
        encoding="utf-8"
    ).strip() == "native reference"
    assert (ticket_worktree / ".repository-selected-skill-proof").read_text().strip() == "repository-selected"
    assert (ticket_worktree / ".native-permissions-complete-proof").read_text(
        encoding="utf-8"
    ).strip() == "complete"
    assert not (ticket_worktree / ".repository-disabled-skill-proof").exists()
    assert (ticket_worktree / "README.md").read_text(encoding="utf-8") == (
        "# Native README\n"
    )
    assert (
        ticket_worktree
        / ".agents"
        / "skills"
        / "repository-selected"
        / "SKILL.md"
    ).read_bytes() == project_skill_before
    assert not (harness_root / ".codex" / "hooks" / "worktree_guard.py").exists()


def test_role_connection_selects_native_provider_without_persisting_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both CLI and Session requests select the role's endpoint and API-key source."""
    from graphtraj.configuration.project_roles import RolePreset
    from graphtraj.configuration.role_definitions import ResolvedChildRole
    from graphtraj.runtimes.codex.codex_adapter import preflight_runtime_context

    monkeypatch.setenv("ROLE_TEST_API_KEY", "private-test-key")
    role = ResolvedChildRole("temporary-role", "Run the bounded task.", (), RolePreset(
        "codex", "deepseek-flash", "https://example.com/v1", "ROLE_TEST_API_KEY",
        reasoning_effort="high",
    ))
    context = preflight_runtime_context(
        runtime_store=tmp_path / ".codex", executable=_runtime_executable(tmp_path),
        git_common_directory=tmp_path / "git-common", role=role,
        worktree=tmp_path, evidence=tmp_path / "evidence",
        repository_skill_source=tmp_path, requested_skills=(),
    ).finalize()
    launch = context.launch_document()
    config = context.session_document()["adapter_request"]["config"]
    provider = config["model_providers"][config["model_provider"]]
    assert provider["base_url"] == "https://example.com/v1"
    assert provider["env_key"] == "ROLE_TEST_API_KEY"
    assert provider["wire_api"] == "responses"
    assert 'model_provider="graphtraj-role"' in launch["adapter_request"]["arguments"]
    assert "private-test-key" not in str(launch)
