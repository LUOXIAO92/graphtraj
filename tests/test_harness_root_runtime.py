from __future__ import annotations

import json
import os
import shutil
import shlex
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
def test_installed_hook_allows_only_reads_of_enabled_external_skills(
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
    harness_skill.parent.mkdir(parents=True)
    shutil.move(user_skills / 'implement' / 'SKILL.md', harness_skill)
    unselected = harness_skill.parent.parent / 'unselected' / 'SKILL.md'
    unselected.parent.mkdir()
    unselected.write_text('---\nname: unselected\ndescription: Unselected.\n---\n')
    with engineer_probe(installed_commands, harness, fake_codex, environment) as (alias, worktree, _):
        records = [json.loads(line) for line in fake_codex.log_file.read_text().splitlines()]
        arguments = next(record['argv'] for record in records if record['role'].startswith('engineer-'))
    task = {'worktree_path': str(worktree), 'alias': alias}
    hooks = tomllib.loads(next(arg for arg in arguments if arg.startswith('hooks=')))['hooks']
    hook = shlex.split(hooks['PreToolUse'][0]['hooks'][0]['command'])
    for path, allowed in ((harness_skill, True), (user_skills / 'ponytail' / 'SKILL.md', True), (unselected, False)):
        for verb in ('cat', 'touch'):
            checked = subprocess.run(
                hook, cwd=task['worktree_path'], env=environment,
                input=json.dumps({'hook_event_name': 'PreToolUse', 'tool_name': 'Bash',
                                  'tool_input': {'command': verb + ' ' + shlex.quote(str(path))}}),
                text=True, capture_output=True, check=True,
            )
            assert (not checked.stdout) is (allowed and verb == 'cat'), checked.stdout


def _runtime_executable(tmp_path: Path) -> Path:
    executable = tmp_path / "codex"
    executable.write_text(
        "#!/bin/sh\necho --sandbox --dangerously-bypass-hook-trust\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def test_setup_creates_a_root_owned_runtime_and_runner_discovers_it(
    monkeypatch,
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "src")
    )
    from you_are_a_product_architect.project_initialization import plan_project_setup
    from you_are_a_product_architect.runner_models import RunnerError
    from you_are_a_product_architect.runner_project import discover_project

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
    assert plan.apply() == "Created Integration Worktree on dev."

    project = discover_project(harness_root)
    assert project.harness_root == harness_root.resolve()
    assert project.runner_directory == harness_root / ".graphtraj" / "runner"
    assert project.integration_worktree == integration.resolve()
    assert (runtime_store / "config.toml").is_file()
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


def test_setup_uses_runtime_user_core_skills_without_root_skill_config(
    monkeypatch,
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "src")
    )
    from you_are_a_product_architect.codex_adapter import (
        preflight_engineer_runtime_context,
    )
    from you_are_a_product_architect.project_initialization import plan_project_setup

    harness_root = temporary_git_repository.parent
    user_home = tmp_path / "runtime-user"
    install_skills(user_home / ".agents" / "skills", CORE_SKILL_NAMES)
    monkeypatch.setenv("HOME", str(user_home))

    plan = plan_project_setup(harness_root, temporary_git_repository)
    assert plan.apply() == "Created Integration Worktree on dev."

    runtime_store = harness_root / ".codex"
    runtime_config = runtime_store / "config.toml"
    assert runtime_config.read_bytes() == plan.codex_files.resources_by_path[
        "config.toml"
    ]
    assert not (harness_root / ".agents").exists()
    preflight_engineer_runtime_context(
        runtime_store=runtime_store,
        executable=_runtime_executable(tmp_path),
        git_common_directory=temporary_git_repository / ".git",
        role="engineer-expert",
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
    from you_are_a_product_architect.codex_adapter import (
        CodexAdapterError,
        preflight_engineer_runtime_context,
    )
    from you_are_a_product_architect.project_initialization import plan_project_setup

    harness_root = temporary_git_repository.parent
    user_home = tmp_path / "runtime-user"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    install_skills(user_home / ".agents" / "skills", ("implement", "ponytail", "tdd"))
    plan = plan_project_setup(harness_root, temporary_git_repository)
    plan.apply()

    runtime_store = harness_root / ".codex"
    (runtime_store / "config.toml").unlink()
    target_worktree = tmp_path / "ticket-worktree"
    evidence = tmp_path / "evidence"
    user_config = user_home / ".codex" / "config.toml"
    user_config.parent.mkdir()
    user_config.write_text('sandbox_mode = "workspace-write"\n', encoding="utf-8")

    with pytest.raises(CodexAdapterError) as legacy_sandbox:
        preflight_engineer_runtime_context(
            runtime_store=runtime_store,
            executable=fake_codex.executable,
            git_common_directory=temporary_git_repository / ".git",
            role="engineer-expert",
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
    preflight_engineer_runtime_context(
        runtime_store=runtime_store,
        executable=fake_codex.executable,
        git_common_directory=temporary_git_repository / ".git",
        role="engineer-expert",
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
        preflight_engineer_runtime_context(
            runtime_store=runtime_store,
            executable=fake_codex.executable,
            git_common_directory=temporary_git_repository / ".git",
            role="engineer-expert",
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
    from you_are_a_product_architect.codex_adapter import preflight_engineer_runtime_context
    from you_are_a_product_architect.project_initialization import plan_project_setup

    harness_root = temporary_git_repository.parent
    user_home = tmp_path / "runtime-user"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    install_skills(user_home / ".agents" / "skills", ("implement", "ponytail", "tdd"))
    plan = plan_project_setup(harness_root, temporary_git_repository)
    plan.apply()
    runtime_store = harness_root / ".codex"
    role_path = runtime_store / "agents" / "engineer-expert.toml"
    role_path.parent.mkdir()
    role_path.write_text(
        "name = 'engineer-expert'\nmodel = 'legacy-projection-model'\n",
        encoding="utf-8",
    )

    def preflight():
        return preflight_engineer_runtime_context(
            runtime_store=runtime_store,
            executable=fake_codex.executable,
            git_common_directory=temporary_git_repository / ".git",
            role="engineer-expert",
            model="project-engineer",
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
    from you_are_a_product_architect.codex_adapter import (
        CodexAdapterError,
        preflight_engineer_runtime_context,
    )
    from you_are_a_product_architect.project_initialization import plan_project_setup

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
        preflight_engineer_runtime_context(
            runtime_store=harness_root / ".codex",
            executable=fake_codex.executable,
            git_common_directory=temporary_git_repository / ".git",
            role="engineer-expert",
            worktree=worktree,
            evidence=evidence,
            repository_skill_source=source,
            requested_skills=(requested_skill,),
        )

    assert raised.value.code == expected_code
    assert not worktree.exists()
    assert not evidence.exists()
    assert not fake_codex.log_file.exists()


def test_engineer_runtime_context_finalizes_worktree_facts_once(
    monkeypatch,
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "src")
    )
    from you_are_a_product_architect.codex_adapter import (
        preflight_engineer_runtime_context,
    )
    from you_are_a_product_architect.project_initialization import plan_project_setup

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
    preflight = preflight_engineer_runtime_context(
        runtime_store=runtime_store,
        executable=_runtime_executable(tmp_path),
        worktree=ticket,
        evidence=evidence,
        git_common_directory=git_common,
        role="engineer-expert",
        repository_skill_source=source,
        requested_skills=("repo-selected",),
    )

    context = preflight.finalize()
    launch = context.launch_document()
    evidence_document = context.evidence_document()

    assert launch["runtime"] == "codex"
    assert launch["adapter_request"]["worktree_path"] == str(ticket)
    assert evidence_document["runtime"] == "codex"
    assert evidence_document["effective_role"] == "engineer-expert"
    assert evidence_document["model"] == "gpt-5.6-sol"
    assert evidence_document["model_reasoning_effort"] == "max"
    assert {
        skill["name"]
        for skill in evidence_document["effective_skills"]
        if skill["source"] == "runtime-user"
    } == {"implement", "ponytail", "tdd"}
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
    launch["adapter_request"].clear()
    assert context.launch_document()["adapter_request"]["worktree_path"] == str(
        ticket
    )
    evidence_document["effective_skills"].clear()
    assert {
        skill["name"]
        for skill in context.evidence_document()["effective_skills"]
        if skill["source"] == "runtime-user"
    } == {"implement", "ponytail", "tdd"}


def test_installed_runner_uses_runtime_user_core_skill_when_source_tracks_it(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    repository = temporary_git_repository
    source_skill = repository / ".agents" / "skills" / "implement" / "SKILL.md"
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
        input="y\n",
        check=False,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert setup.returncode == 0, setup.stderr

    with engineer_probe(installed_commands, repository, fake_codex, environment) as (alias, worktree, _):
        records = [json.loads(line) for line in fake_codex.log_file.read_text().splitlines()]
        arguments = next(record["argv"] for record in records if record["role"].startswith("engineer-"))
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
        / "implement"
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
    source_skill = repository / ".agents" / "skills" / "implement" / "SKILL.md"
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
        input="",
        check=False,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert setup.returncode == 0, setup.stderr

    with engineer_probe(installed_commands, repository, fake_codex, environment) as (alias, worktree, _):
        records = [json.loads(line) for line in fake_codex.log_file.read_text().splitlines()]
        arguments = next(record["argv"] for record in records if record["role"].startswith("engineer-"))
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
def test_real_codex_uses_harness_hook_and_explicit_skill_configuration(
    mutable_installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """Exercise source Runtime isolation against a real installed Codex process."""

    harness_root = temporary_git_repository.parent
    primary = temporary_git_repository
    source_hook_marker = tmp_path / "source-hook-ran"
    harness_hook_marker = tmp_path / "harness-hook-ran"
    source_hook = primary / ".codex" / "source_hook.py"
    source_hook.parent.mkdir()
    source_hook.write_text(
        "from pathlib import Path\n"
        + "Path({0!r}).touch()\n".format(str(source_hook_marker)),
        encoding="utf-8",
    )
    source_config = primary / ".codex" / "config.toml"
    source_config.write_text(
        "[[hooks.PreToolUse]]\n"
        + 'matcher = "Bash"\n\n'
        + "[[hooks.PreToolUse.hooks]]\n"
        + 'type = "command"\n'
        + "command = {0}\n".format(
            json.dumps("python3 {0}".format(source_hook))
        )
        + "timeout = 5\n",
        encoding="utf-8",
    )
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
        ["git", "add", ".codex", ".agents"], cwd=primary
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
    harness_skill.write_text(
        "---\n"
        "name: implement\n"
        "description: Creates its proof file for the Harness Skill acceptance probe.\n"
        "---\n\n"
        "When asked to perform the Harness Skill acceptance probe, use "
        "apply_patch to create `.harness-skill-proof` containing "
        "`implement`. Then use Bash to attempt these commands separately, "
        "continuing after the first two are denied: "
        "`echo forbidden > README.md`; "
        "`echo forbidden > .agents/skills/repository-selected/SKILL.md`; "
        "`touch .native-code-write-proof`; "
        "`touch .state/native-evidence-write-proof`.\n",
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

    package_hook = subprocess.run(
        [
            str(mutable_installed_commands.product.parent / "python"),
            "-c",
            (
                "from importlib.resources import files; "
                "print(files('you_are_a_product_architect.resources')."
                "joinpath('codex', 'hooks', 'worktree_guard.py'))"
            ),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    installed_guard = Path(package_hook.stdout.strip())
    harness_guard = harness_root / ".codex" / "hooks" / "worktree_guard.py"
    instrumented_guard = installed_guard.read_text().replace(
        "def main() -> int:\n",
        "def main() -> int:\n    Path({0!r}).touch()\n".format(str(harness_hook_marker)),
    )
    installed_guard.write_text(instrumented_guard, encoding="utf-8")
    harness_guard.write_text(instrumented_guard, encoding="utf-8")

    ticket_file = harness_root / "tickets" / "real-codex.md"
    ticket_file.parent.mkdir()
    ticket_file.write_text(
        "# Real Codex Runtime isolation\n\n"
        "This is only the Harness Skill acceptance probe. Read enabled Skill "
        "files with Bash cat using their supplied paths; do not use sed. "
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
                ticket_worktree / '.repository-selected-skill-proof',
                ticket_worktree / '.native-code-write-proof',
                ticket_worktree / '.state' / 'native-evidence-write-proof',
                harness_hook_marker,
            ],
        )
    assert (ticket_worktree / ".harness-skill-proof").read_text(
        encoding="utf-8"
    ).strip() == "implement"
    assert (ticket_worktree / ".repository-selected-skill-proof").read_text().strip() == "repository-selected"
    assert not (ticket_worktree / ".repository-disabled-skill-proof").exists()
    assert (ticket_worktree / "README.md").read_text(encoding="utf-8") == (
        "# Target project\n"
    )
    assert (
        ticket_worktree
        / ".agents"
        / "skills"
        / "repository-selected"
        / "SKILL.md"
    ).read_bytes() == project_skill_before
    assert (ticket_worktree / ".native-code-write-proof").is_file()
    assert (
        ticket_worktree / ".state" / "native-evidence-write-proof"
    ).is_file()
    assert harness_hook_marker.is_file()
    assert not source_hook_marker.exists()
