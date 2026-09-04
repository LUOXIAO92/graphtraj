from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from conftest import FakeCodex, InstalledCommands, run_process


CORE_SKILL_NAMES = (
    "setup-matt-pocock-skills",
    "grill-with-docs",
    "grilling",
    "domain-modeling",
    "to-spec",
    "to-tickets",
    "task-delivery",
    "implement",
    "ponytail",
    "tdd",
    "code-review",
    "resolving-merge-conflicts",
)


def install_skills(skill_root: Path, names: Iterable[str]) -> None:
    for name in names:
        skill_directory = skill_root / name
        skill_directory.mkdir(parents=True)
        (skill_directory / "SKILL.md").write_text(
            "---\nname: {0}\ndescription: Test Skill.\n---\n".format(name),
            encoding="utf-8",
        )


def install_user_skills(user_home: Path) -> None:
    install_skills(user_home / ".agents" / "skills", CORE_SKILL_NAMES)


def tree_contents(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def supported_skill_contents(name: str) -> dict[str, bytes]:
    package_root = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "you_are_a_product_architect"
        / "resources"
    )
    root = (
        package_root / "skills" / name
        if name == "task-delivery"
        else package_root / "codex" / "skills" / name
    )
    return tree_contents(root)


def setup_environment(user_home: Path, fake_codex: FakeCodex) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(user_home),
            "PATH": os.pathsep.join(
                (str(fake_codex.executable.parent), environment.get("PATH", ""))
            ),
            "FAKE_CODEX_LOG": str(fake_codex.log_file),
        }
    )
    return environment


def run_setup(
    installed_commands: InstalledCommands,
    *,
    harness_root: Path,
    user_home: Path,
    fake_codex: FakeCodex,
    answers: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(installed_commands.product), "setup"],
        cwd=harness_root,
        env=setup_environment(user_home, fake_codex),
        input=answers,
        check=False,
        text=True,
        capture_output=True,
    )


def run_ready_setup(
    installed_commands: InstalledCommands,
    *,
    harness_root: Path,
    user_home: Path,
    fake_codex: FakeCodex,
    answers: str,
) -> subprocess.CompletedProcess[str]:
    return run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers=answers,
    )


def git_output(repository: Path, *arguments: str) -> str:
    result = run_process(["git", *arguments], cwd=repository)
    result.check_returncode()
    return result.stdout.strip()


def commit_dev_files_without_leaving_dev_checked_out(
    primary: Path,
    seed_worktree: Path,
    files: dict[str, str],
) -> None:
    run_process(["git", "branch", "dev"], cwd=primary).check_returncode()
    run_process(
        ["git", "worktree", "add", str(seed_worktree), "dev"], cwd=primary
    ).check_returncode()
    for relative_path, content in files.items():
        target = seed_worktree / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    run_process(["git", "add", "."], cwd=seed_worktree).check_returncode()
    run_process(
        ["git", "commit", "-m", "Seed conflicting dev resources"],
        cwd=seed_worktree,
    ).check_returncode()
    run_process(
        ["git", "worktree", "remove", str(seed_worktree)], cwd=primary
    ).check_returncode()


def test_setup_refuses_missing_core_skills_without_mutating_either_scope(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    user_home = tmp_path / "operator-home"
    user_home.mkdir()
    (user_home / "operator-note.txt").write_text(
        "leave the Runtime-user scope alone\n",
        encoding="utf-8",
    )
    user_before = tree_contents(user_home)
    worktrees_before = git_output(
        temporary_git_repository, "worktree", "list", "--porcelain"
    )

    result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="n\n",
    )

    assert result.returncode == 1
    assert "Missing required core Skills:" in result.stdout
    assert "implement" in result.stdout
    assert "Setup stopped before any setup mutation." in result.stderr
    assert not (harness_root / ".graphtraj").exists()
    assert not (harness_root / ".codex").exists()
    assert not (harness_root / ".agents").exists()
    assert tree_contents(user_home) == user_before
    assert git_output(
        temporary_git_repository, "worktree", "list", "--porcelain"
    ) == worktrees_before


def test_setup_installs_only_missing_core_skills_at_the_harness_root(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    harness_skills = harness_root / ".agents" / "skills"
    install_skills(harness_skills, ("grilling",))
    existing_grilling = harness_skills / "grilling" / "SKILL.md"
    existing_grilling.write_text(
        "---\nname: grilling\ndescription: Operator Skill.\n---\n",
        encoding="utf-8",
    )
    grilling_before = existing_grilling.read_bytes()
    user_home = tmp_path / "operator-home"
    install_skills(user_home / ".agents" / "skills", ("tdd",))
    user_before = tree_contents(user_home)

    result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="y\ny\n",
    )

    assert result.returncode == 0, result.stderr
    assert existing_grilling.read_bytes() == grilling_before
    for name in CORE_SKILL_NAMES:
        target = harness_skills / name
        if name == "grilling":
            assert target.joinpath("SKILL.md").read_bytes() == grilling_before
        elif name == "tdd":
            assert not target.exists()
        else:
            assert tree_contents(target) == supported_skill_contents(name)
    assert tree_contents(user_home) == user_before
    assert not (
        harness_root / ".codex" / "agent-runner" / "config.yml"
    ).exists()


def test_setup_preflights_missing_skill_targets_before_project_mutation(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    redirected_target = tmp_path / "outside-harness"
    redirected_target.mkdir()
    (redirected_target / "operator-note.txt").write_text(
        "leave this alone\n", encoding="utf-8"
    )
    harness_skills = harness_root / ".agents" / "skills"
    harness_skills.mkdir(parents=True)
    (harness_skills / "implement").symlink_to(
        redirected_target,
        target_is_directory=True,
    )
    user_home = tmp_path / "operator-home"
    user_home.mkdir()
    user_before = tree_contents(user_home)
    outside_before = tree_contents(redirected_target)
    worktrees_before = git_output(
        temporary_git_repository, "worktree", "list", "--porcelain"
    )

    result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="y\ny\n",
    )

    assert result.returncode == 1
    assert "Harness Skill target is not a real directory" in result.stderr
    assert not (harness_root / ".graphtraj").exists()
    assert not (harness_root / ".codex").exists()
    assert (harness_skills / "implement").is_symlink()
    assert tree_contents(redirected_target) == outside_before
    assert tree_contents(user_home) == user_before
    assert git_output(
        temporary_git_repository, "worktree", "list", "--porcelain"
    ) == worktrees_before


def test_setup_preflights_source_document_views_before_mutating(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    integration = harness_root / ".graphtraj" / ".agent-worktrees" / "dev"
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    commit_dev_files_without_leaving_dev_checked_out(
        temporary_git_repository,
        tmp_path / "seed-dev",
        {
            "CONTEXT.md": "Repository-owned context.\n",
            "docs/decision.md": "Repository-owned documentation.\n",
        },
    )
    worktrees_before = git_output(
        temporary_git_repository, "worktree", "list", "--porcelain"
    )

    result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="",
    )

    assert result.returncode == 1
    assert str(integration / "CONTEXT.md") in result.stderr
    assert str(integration / "docs") in result.stderr
    assert not (harness_root / ".graphtraj").exists()
    assert not (harness_root / ".codex").exists()
    assert git_output(
        temporary_git_repository, "worktree", "list", "--porcelain"
    ) == worktrees_before


def test_setup_preflights_a_dev_checkout_owned_elsewhere(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    foreign_dev = tmp_path / "operator-dev-worktree"
    run_process(["git", "branch", "dev"], cwd=temporary_git_repository).check_returncode()
    run_process(
        ["git", "worktree", "add", str(foreign_dev), "dev"],
        cwd=temporary_git_repository,
    ).check_returncode()
    before = git_output(temporary_git_repository, "worktree", "list", "--porcelain")

    result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\n".format(temporary_git_repository.name),
    )

    assert result.returncode == 1
    assert "dev is already checked out at a different Worktree" in result.stderr
    assert str(foreign_dev) in result.stderr
    assert not (harness_root / ".graphtraj").exists()
    assert git_output(temporary_git_repository, "worktree", "list", "--porcelain") == before


def test_setup_preflights_runtime_conflicts_before_creating_dev(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    runtime_store = harness_root / ".codex"
    runtime_store.mkdir()
    (runtime_store / "config.toml").write_text("unmanaged = true\n", encoding="utf-8")
    before = git_output(temporary_git_repository, "worktree", "list", "--porcelain")

    result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="",
    )

    assert result.returncode == 1
    assert "Harness Runtime resource conflicts" in result.stderr
    assert not (harness_root / ".graphtraj").exists()
    assert not (harness_root / ".codex" / "agent-runner").exists()
    assert git_output(temporary_git_repository, "worktree", "list", "--porcelain") == before


def test_setup_reports_partial_execution_and_rerun_recovers(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    real_git = shutil.which("git")
    assert real_git is not None
    failure_marker = tmp_path / "git-worktree-add-failed-once"
    git_wrapper = fake_codex.executable.parent / "git"
    git_wrapper.write_text(
        "#!{0}\n".format(sys.executable)
        + (
            "import os\n"
            "import sys\n"
            "from pathlib import Path\n"
            "real_git = {0!r}\n"
            "marker = Path({1!r})\n"
            "arguments = sys.argv[1:]\n"
            "if arguments[:2] == ['worktree', 'add'] and not marker.exists():\n"
            "    marker.write_text('failed once\\n', encoding='utf-8')\n"
            "    print('injected git worktree failure', file=sys.stderr)\n"
            "    raise SystemExit(73)\n"
            "os.execv(real_git, [real_git, *arguments])\n"
        ).format(real_git, str(failure_marker)),
        encoding="utf-8",
    )
    git_wrapper.chmod(0o755)
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)

    failed = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="y\n",
    )

    worktree_root = harness_root / ".graphtraj" / ".agent-worktrees"
    assert failed.returncode == 1
    assert "injected git worktree failure" in failed.stderr
    assert (harness_root / ".graphtraj" / "config.yml").is_file()
    assert worktree_root.is_dir()
    assert (harness_root / ".graphtraj" / "state").is_dir()
    assert not (worktree_root / "dev").exists()
    assert run_process(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/dev"],
        cwd=temporary_git_repository,
    ).returncode == 0
    assert not (harness_root / ".codex" / "agent-runner" / "config.yml").exists()

    rerun = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="",
    )

    assert rerun.returncode == 0, rerun.stderr
    assert (worktree_root / "dev").is_dir()
    assert git_output(worktree_root / "dev", "branch", "--show-current") == "dev"
    assert (harness_root / ".codex" / "agent-runner").is_dir()
    assert not (harness_root / ".codex" / "agent-runner" / "config.yml").exists()


def test_setup_registers_an_existing_dev_at_the_configured_location(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    run_process(["git", "branch", "dev"], cwd=temporary_git_repository).check_returncode()

    result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="",
    )

    integration = harness_root / ".graphtraj" / ".agent-worktrees" / "dev"
    assert result.returncode == 0, result.stderr
    assert integration.is_dir()
    assert git_output(integration, "branch", "--show-current") == "dev"
    assert (integration / ".state").resolve() == (
        harness_root / ".graphtraj" / "state"
    ).resolve()
