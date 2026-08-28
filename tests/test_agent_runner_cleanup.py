from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from conftest import (
    PROJECT_ROOT,
    FakeCodex,
    InstalledCommands,
    run_process,
)
from test_agent_runner_launch import wait_for_file
from test_project_setup import (
    common_git_directory,
    git_output,
    install_user_skills,
    run_setup,
)


@pytest.fixture
def installed_cleanup_commands(tmp_path: Path) -> InstalledCommands:
    """Install the current package without requiring network access."""

    environment = tmp_path / "installed-cleanup-environment"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "venv",
            "--system-site-packages",
            str(environment),
        ],
        check=True,
        cwd=PROJECT_ROOT,
    )
    python = environment / "bin" / "python"
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-build-isolation",
            "--no-deps",
            str(PROJECT_ROOT),
        ],
        check=True,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    return InstalledCommands(
        product=environment / "bin" / "you-are-a-product-architect",
        runner=environment / "bin" / "agent-runner",
    )


@dataclass(frozen=True)
class LaunchedTicket:
    harness_root: Path
    primary: Path
    integration: Path
    worktree: Path
    branch: str
    ticket_file: Path
    batch_file: Path
    run_id: str
    ticket_id: str
    alias: str
    session_directory: Path
    environment: dict[str, str]


def launch_ticket(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    *,
    run_id: str = "20260813-cleanup-ticket",
    runtime_environment: dict[str, str] | None = None,
    wait_until_idle: bool = True,
) -> LaunchedTicket:
    harness_root = temporary_git_repository.parent
    primary = temporary_git_repository
    integration = harness_root / ".agent-worktrees" / "integration"
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    setup_result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(primary.name),
    )
    assert setup_result.returncode == 0, setup_result.stderr

    ticket_file = harness_root / "tickets" / "14-cleanup.md"
    ticket_file.parent.mkdir()
    ticket_file.write_text("# Clean up integrated Ticket Worktrees\n", encoding="utf-8")
    batch_file = harness_root / "launch-batch.yml"
    batch_file.write_text(
        yaml.safe_dump(
            {
                "run_id": run_id,
                "runtime": "codex",
                "tasks": [
                    {
                        "ticket_id": "14",
                        "ticket_name": "cleanup-integrated-worktrees",
                        "role": "engineer-expert",
                        "ticket_file": str(ticket_file),
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(user_home),
            "FAKE_CODEX_LOG": str(fake_codex.log_file),
        }
    )
    if runtime_environment is not None:
        environment.update(runtime_environment)
    launch = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch_file)],
        cwd=harness_root,
        env=environment,
    )
    assert launch.returncode == 0, launch.stderr
    task = yaml.safe_load(launch.stdout)["tasks"][0]
    worktree = Path(task["worktree_path"])
    branch = git_output(worktree, "branch", "--show-current")
    alias = task["alias"]
    session_directory = harness_root / ".codex" / "agent-runner" / "sessions" / alias
    if wait_until_idle:
        wait_for_file(session_directory / "turn.yml")
    return LaunchedTicket(
        harness_root=harness_root,
        primary=primary,
        integration=integration,
        worktree=worktree,
        branch=branch,
        ticket_file=ticket_file,
        batch_file=batch_file,
        run_id=run_id,
        ticket_id="14",
        alias=alias,
        session_directory=session_directory,
        environment=environment,
    )


def cleanup_ticket(
    installed_commands: InstalledCommands,
    launched: LaunchedTicket,
) -> subprocess.CompletedProcess[str]:
    return run_process(
        [
            str(installed_commands.runner),
            "cleanup",
            "--run-id",
            launched.run_id,
            "--ticket-id",
            launched.ticket_id,
        ],
        cwd=launched.harness_root,
        env=launched.environment,
    )


def send_instruction(
    installed_commands: InstalledCommands,
    launched: LaunchedTicket,
    instruction: str,
) -> subprocess.CompletedProcess[str]:
    return run_process(
        [
            str(installed_commands.runner),
            "send",
            launched.alias,
            "--instruction",
            instruction,
            "--caused-by-worldline-seq",
            "1",
        ],
        cwd=launched.harness_root,
        env=launched.environment,
    )


def interrupt_ticket(
    installed_commands: InstalledCommands,
    launched: LaunchedTicket,
) -> subprocess.CompletedProcess[str]:
    return run_process(
        [str(installed_commands.runner), "interrupt", launched.alias],
        cwd=launched.harness_root,
        env=launched.environment,
    )


def test_alias_removal_preserves_a_final_diagnostic_path_replacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_ROOT / "src"))
    from you_are_a_product_architect import runner_cleanup

    sessions = tmp_path / "sessions"
    alias_directory = sessions / "2-14-cleanup-integrated-worktrees@e1"
    alias_directory.mkdir(parents=True)
    diagnostic = alias_directory / "mapping.yml"
    original = b"mapping: original\n"
    replacement = b"mapping: replacement\n"
    diagnostic.write_bytes(original)
    flags = runner_cleanup.directory_open_flags()
    descriptor = os.open(str(alias_directory), flags)
    try:
        identity = os.fstat(descriptor)
        entries = runner_cleanup._capture_alias_entries(descriptor)
    finally:
        os.close(descriptor)
    session_identity = sessions.stat()
    bound = runner_cleanup.BoundAlias(
        path=alias_directory,
        device=identity.st_dev,
        inode=identity.st_ino,
        entries=entries,
        turn=1,
    )
    snapshot = runner_cleanup.SessionSnapshot(
        path=sessions,
        device=session_identity.st_dev,
        inode=session_identity.st_ino,
        names=(alias_directory.name,),
    )
    real_stat = os.stat
    real_rename = os.rename
    diagnostic_stats = 0

    def replace_after_validation(
        path: str,
        *args: object,
        **kwargs: object,
    ) -> os.stat_result:
        nonlocal diagnostic_stats
        current = real_stat(path, *args, **kwargs)
        if path == "mapping.yml":
            diagnostic_stats += 1
            if diagnostic_stats == 2:
                directory_descriptor = kwargs["dir_fd"]
                real_rename(
                    "mapping.yml",
                    "retained-original.yml",
                    src_dir_fd=directory_descriptor,
                    dst_dir_fd=directory_descriptor,
                )
                replacement_descriptor = os.open(
                    "mapping.yml",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=directory_descriptor,
                )
                try:
                    os.write(replacement_descriptor, replacement)
                    os.fsync(replacement_descriptor)
                finally:
                    os.close(replacement_descriptor)
        return current

    monkeypatch.setattr(runner_cleanup.os, "stat", replace_after_validation)

    with pytest.raises(OSError):
        runner_cleanup._remove_aliases([bound], snapshot)

    preserved = [path.read_bytes() for path in alias_directory.iterdir()]
    assert original in preserved
    assert replacement in preserved


def test_installed_cleanup_refuses_a_ticket_branch_not_merged_into_dev(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    delivered_file = launched.worktree / "delivered.txt"
    delivered_file.write_text("reviewed ticket result\n", encoding="utf-8")
    run_process(["git", "add", "delivered.txt"], cwd=launched.worktree).check_returncode()
    run_process(
        ["git", "commit", "-m", "Deliver cleanup ticket"],
        cwd=launched.worktree,
    ).check_returncode()
    ticket_commit = git_output(launched.worktree, "rev-parse", "HEAD")
    integration_commit = git_output(launched.integration, "rev-parse", "HEAD")

    result = cleanup_ticket(installed_cleanup_commands, launched)

    message = "The Ticket branch is not merged into registered dev."
    assert result.returncode == 1
    assert yaml.safe_load(result.stdout) == {
        "run_id": launched.run_id,
        "ticket_id": launched.ticket_id,
        "cleanup_status": "refused",
        "worktree_path": str(launched.worktree),
        "branch": launched.branch,
        "error": {"code": "cleanup-not-merged", "message": message},
        "evidence": {
            "integration_branch": "dev",
            "integration_commit": integration_commit,
            "ticket_commit": ticket_commit,
        },
    }
    assert result.stderr == message + "\n"
    assert launched.worktree.is_dir()
    assert git_output(launched.primary, "rev-parse", launched.branch) == ticket_commit
    assert launched.session_directory.is_dir()


def test_installed_cleanup_refuses_a_symbolic_ticket_branch(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    dev_commit = git_output(launched.integration, "rev-parse", "HEAD")
    run_process(
        ["git", "worktree", "remove", str(launched.worktree)],
        cwd=launched.integration,
    ).check_returncode()
    branch_ref = "refs/heads/{0}".format(launched.branch)
    run_process(
        ["git", "update-ref", "-d", branch_ref],
        cwd=launched.integration,
    ).check_returncode()
    run_process(
        ["git", "symbolic-ref", branch_ref, "refs/heads/dev"],
        cwd=launched.integration,
    ).check_returncode()

    result = cleanup_ticket(installed_cleanup_commands, launched)

    message = (
        "The registered Ticket Worktree does not belong to the supplied "
        "run and ticket identities."
    )
    assert result.returncode == 1
    assert yaml.safe_load(result.stdout)["error"] == {
        "code": "cleanup-ownership-mismatch",
        "message": message,
    }
    assert yaml.safe_load(result.stdout)["evidence"] == {
        "ownership_mismatches": ["ticket-branch-symbolic"]
    }
    assert result.stderr == message + "\n"
    assert git_output(launched.integration, "rev-parse", "dev") == dev_commit
    assert git_output(
        launched.integration, "symbolic-ref", branch_ref
    ) == "refs/heads/dev"
    assert launched.session_directory.is_dir()


def test_installed_cleanup_refuses_a_dirty_ticket_worktree(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    dirty_file = launched.worktree / "unfinished.txt"
    dirty_file.write_text("uncommitted Engineer work\n", encoding="utf-8")

    result = cleanup_ticket(installed_cleanup_commands, launched)

    message = "The Ticket Worktree is not clean."
    assert result.returncode == 1
    assert yaml.safe_load(result.stdout) == {
        "run_id": launched.run_id,
        "ticket_id": launched.ticket_id,
        "cleanup_status": "refused",
        "worktree_path": str(launched.worktree),
        "branch": launched.branch,
        "error": {"code": "cleanup-dirty", "message": message},
        "evidence": {"worktree_status": ["?? unfinished.txt"]},
    }
    assert result.stderr == message + "\n"
    assert dirty_file.read_text(encoding="utf-8") == "uncommitted Engineer work\n"
    assert launched.session_directory.is_dir()


@pytest.mark.parametrize("invalid_trace", ("missing", "redirected", "empty"))
def test_installed_cleanup_refuses_an_invalid_required_turn_trace(
    invalid_trace: str,
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    trace = (
        launched.harness_root
        / "state"
        / "task-delivery"
        / launched.run_id
        / "tickets"
        / launched.worktree.name
        / "traces"
        / launched.alias
        / "turn-1"
        / "events.jsonl"
    )
    if invalid_trace == "missing":
        trace.unlink()
    elif invalid_trace == "redirected":
        trace.unlink()
        trace.symlink_to(launched.session_directory / "events.jsonl")
    else:
        trace.write_bytes(b"")

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 1
    assert yaml.safe_load(result.stdout)["evidence"] == {
        "ownership_mismatches": ["persistent-evidence-invalid"]
    }
    assert launched.worktree.is_dir()
    assert launched.session_directory.is_dir()


def test_installed_cleanup_refuses_an_empty_trace_from_a_resume_without_a_session_event(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    launched.environment["FAKE_CODEX_EVENTS"] = "[]"

    resumed = send_instruction(
        installed_cleanup_commands,
        launched,
        "Resume without reporting a Runtime Session event.",
    )

    assert resumed.returncode == 1
    cleanup = cleanup_ticket(installed_cleanup_commands, launched)
    assert cleanup.returncode == 1
    assert yaml.safe_load(cleanup.stdout)["evidence"] == {
        "ownership_mismatches": ["persistent-evidence-invalid"]
    }
    trace = (
        launched.harness_root
        / "state"
        / "task-delivery"
        / launched.run_id
        / "tickets"
        / launched.worktree.name
        / "traces"
        / launched.alias
        / "turn-2"
        / "events.jsonl"
    )
    assert trace.is_file() and trace.stat().st_size == 0
    assert launched.worktree.is_dir()
    assert launched.session_directory.is_dir()


def test_installed_cleanup_refuses_an_active_engineer_turn(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    release_file = tmp_path / "allow-engineer-turn-to-finish"
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
        runtime_environment={"FAKE_CODEX_RELEASE_FILE": str(release_file)},
        wait_until_idle=False,
    )

    try:
        result = cleanup_ticket(installed_cleanup_commands, launched)

        message = "The Ticket Worktree has an active Engineer turn."
        assert result.returncode == 1
        assert yaml.safe_load(result.stdout) == {
            "run_id": launched.run_id,
            "ticket_id": launched.ticket_id,
            "cleanup_status": "refused",
            "worktree_path": str(launched.worktree),
            "branch": launched.branch,
            "error": {"code": "worktree-busy", "message": message},
            "evidence": {
                "active_turn": {
                    "activity": "running",
                    "alias": launched.alias,
                    "worktree_path": str(launched.worktree),
                }
            },
        }
        assert result.stderr == message + "\n"
        assert launched.worktree.is_dir()
        assert launched.session_directory.is_dir()
    finally:
        release_file.touch()
        wait_for_file(launched.session_directory / "turn.yml")


def test_installed_cleanup_allows_an_active_different_ticket_in_the_same_run(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    other_ticket_id = "99"
    other_reservation = (
        launched.harness_root
        / ".codex"
        / "agent-runner"
        / "active-worktrees"
        / hashlib.sha256(other_ticket_id.encode("ascii")).hexdigest()
    )
    other_reservation.write_text(
        yaml.safe_dump(
            {
                "activity": "running",
                "run_id": launched.run_id,
                "ticket_id": other_ticket_id,
                "worktree_path": str(
                    launched.worktree.parent / "2-99-other-ticket"
                ),
                "alias": "2-99-other-ticket@e1",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(result.stdout)["cleanup_status"] == "cleaned"
    assert other_reservation.is_file()
    assert not launched.worktree.exists()
    assert not launched.session_directory.exists()


def test_installed_cleanup_refuses_a_noncanonical_other_turn_worktree_path(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    other_ticket_id = "99"
    reservation = (
        launched.harness_root
        / ".codex"
        / "agent-runner"
        / "active-worktrees"
        / hashlib.sha256(other_ticket_id.encode("ascii")).hexdigest()
    )
    ambiguous_worktree = str(
        launched.worktree.parent
        / "2-99-other-ticket"
        / ".."
        / launched.worktree.name
    )
    reservation.write_text(
        yaml.safe_dump(
            {
                "activity": "running",
                "run_id": launched.run_id,
                "ticket_id": other_ticket_id,
                "worktree_path": ambiguous_worktree,
                "alias": "2-99-other-ticket@e1",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = cleanup_ticket(installed_cleanup_commands, launched)

    message = "The active-turn reservation cannot be attributed safely."
    assert result.returncode == 1
    assert yaml.safe_load(result.stdout)["error"] == {
        "code": "cleanup-ownership-mismatch",
        "message": message,
    }
    assert yaml.safe_load(result.stdout)["evidence"] == {
        "active_turn": "invalid"
    }
    assert result.stderr == message + "\n"
    assert launched.worktree.is_dir()
    assert launched.session_directory.is_dir()


def test_installed_cleanup_refuses_an_alias_mapping_owned_by_another_run(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    mapping_file = launched.session_directory / "mapping.yml"
    mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
    mapping["run_id"] = "20260813-another-run"
    mapping_file.write_text(
        yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8"
    )

    result = cleanup_ticket(installed_cleanup_commands, launched)

    message = (
        "The registered Ticket Worktree does not belong to the supplied "
        "run and ticket identities."
    )
    assert result.returncode == 1
    assert yaml.safe_load(result.stdout) == {
        "run_id": launched.run_id,
        "ticket_id": launched.ticket_id,
        "cleanup_status": "refused",
        "worktree_path": str(launched.worktree),
        "branch": launched.branch,
        "error": {"code": "cleanup-ownership-mismatch", "message": message},
        "evidence": {"ownership_mismatches": ["alias-run-mismatch"]},
    }
    assert result.stderr == message + "\n"
    assert launched.worktree.is_dir()
    assert mapping_file.is_file()


def test_installed_cleanup_refuses_a_ticket_worktree_at_a_noncanonical_path(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    moved_worktree = launched.worktree.parent / "moved-by-operator"
    run_process(
        ["git", "worktree", "move", str(launched.worktree), str(moved_worktree)],
        cwd=launched.primary,
    ).check_returncode()

    result = cleanup_ticket(installed_cleanup_commands, launched)

    message = (
        "The registered Ticket Worktree does not belong to the supplied "
        "run and ticket identities."
    )
    assert result.returncode == 1
    assert yaml.safe_load(result.stdout) == {
        "run_id": launched.run_id,
        "ticket_id": launched.ticket_id,
        "cleanup_status": "refused",
        "worktree_path": str(launched.worktree),
        "branch": launched.branch,
        "error": {"code": "cleanup-ownership-mismatch", "message": message},
        "evidence": {
            "ownership_mismatches": [
                "canonical-worktree-not-registered",
                "ticket-branch-registered-at-noncanonical-path",
            ]
        },
    }
    assert result.stderr == message + "\n"
    assert moved_worktree.is_dir()
    assert git_output(moved_worktree, "branch", "--show-current") == launched.branch
    assert launched.session_directory.is_dir()


def test_installed_cleanup_refuses_unexpected_nested_alias_diagnostics(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    unexpected = launched.session_directory / "unexpected-directory"
    unexpected.mkdir()
    marker = unexpected / "operator-data.txt"
    marker.write_text("do not remove\n", encoding="utf-8")

    result = cleanup_ticket(installed_cleanup_commands, launched)

    message = "The bound alias diagnostics cannot be removed safely."
    assert result.returncode == 1
    assert yaml.safe_load(result.stdout) == {
        "run_id": launched.run_id,
        "ticket_id": launched.ticket_id,
        "cleanup_status": "refused",
        "worktree_path": str(launched.worktree),
        "branch": launched.branch,
        "error": {"code": "cleanup-failed", "message": message},
        "evidence": {
            "unsafe_alias_entries": [
                "{0}/unexpected-directory".format(launched.alias)
            ]
        },
    }
    assert result.stderr == message + "\n"
    assert marker.read_text(encoding="utf-8") == "do not remove\n"
    assert launched.worktree.is_dir()
    assert launched.session_directory.is_dir()


def test_installed_cleanup_removes_a_successfully_resumed_alias(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )

    sent = send_instruction(
        installed_cleanup_commands,
        launched,
        "Finish the final integration validation.",
    )

    assert sent.returncode == 0, sent.stderr
    assert yaml.safe_load(sent.stdout) == {
        "alias": launched.alias,
        "send_status": "sent",
    }
    wait_for_file(launched.session_directory / "turn.yml")
    assert (launched.session_directory / "resume.yml").is_file()

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(result.stdout)["cleanup_status"] == "cleaned"
    assert not launched.worktree.exists()
    assert not launched.session_directory.exists()


def test_installed_cleanup_removes_an_interrupted_alias_after_a_replacement_turn(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    release_file = tmp_path / "allow-replacement-turn-to-finish"
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
        runtime_environment={"FAKE_CODEX_RELEASE_FILE": str(release_file)},
        wait_until_idle=False,
    )

    interrupted = interrupt_ticket(installed_cleanup_commands, launched)

    assert interrupted.returncode == 0, interrupted.stderr
    assert yaml.safe_load(interrupted.stdout) == {
        "alias": launched.alias,
        "interrupt_status": "interrupted",
    }
    assert yaml.safe_load(
        (launched.session_directory / "turn.yml").read_text(encoding="utf-8")
    )["outcome"] == "interrupted"

    release_file.touch()
    replacement = run_process(
        [
            str(installed_cleanup_commands.runner),
            "--batch-input",
            str(launched.batch_file),
        ],
        cwd=launched.harness_root,
        env=launched.environment,
    )
    assert replacement.returncode == 0, replacement.stderr
    replacement_alias = yaml.safe_load(replacement.stdout)["tasks"][0]["alias"]
    assert replacement_alias != launched.alias
    replacement_session = launched.session_directory.parent / replacement_alias
    wait_for_file(replacement_session / "turn.yml")

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(result.stdout)["aliases_removed"] == [
        launched.alias,
        replacement_alias,
    ]
    assert not launched.worktree.exists()
    assert not launched.session_directory.exists()
    assert not replacement_session.exists()


def test_installed_cleanup_removes_only_integrated_disposable_state(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    second_batch = launched.harness_root / "second-launch-batch.yml"
    second_document = yaml.safe_load(
        launched.batch_file.read_text(encoding="utf-8")
    )
    second_document["tasks"][0]["instruction"] = "Use a refreshed exact batch."
    second_batch.write_text(
        yaml.safe_dump(second_document, sort_keys=False), encoding="utf-8"
    )
    second_launch = run_process(
        [
            str(installed_cleanup_commands.runner),
            "--batch-input",
            str(second_batch),
        ],
        cwd=launched.harness_root,
        env=launched.environment,
    )
    assert second_launch.returncode == 0, second_launch.stderr
    second_alias = yaml.safe_load(second_launch.stdout)["tasks"][0]["alias"]
    assert second_alias == "2-14-cleanup-integrated-worktrees@e2"
    second_session = launched.session_directory.parent / second_alias
    wait_for_file(second_session / "turn.yml")

    delivered_file = launched.worktree / "delivered.txt"
    delivered_file.write_text("validated cleanup implementation\n", encoding="utf-8")
    run_process(["git", "add", "delivered.txt"], cwd=launched.worktree).check_returncode()
    run_process(
        ["git", "commit", "-m", "Deliver cleanup ticket"],
        cwd=launched.worktree,
    ).check_returncode()
    ticket_commit = git_output(launched.worktree, "rev-parse", "HEAD")
    run_process(
        ["git", "merge", "--no-ff", "--no-edit", launched.branch],
        cwd=launched.integration,
    ).check_returncode()
    integration_commit = git_output(launched.integration, "rev-parse", "HEAD")

    run_state = (
        launched.harness_root
        / "state"
        / "task-delivery"
        / launched.run_id
    )
    evidence = run_state / "tickets" / "2-14-cleanup-integrated-worktrees"
    reviews = evidence / "reviews"
    reviews.mkdir()
    retained_files = {
        launched.ticket_file: launched.ticket_file.read_bytes(),
        run_state / "batch.yml": (run_state / "batch.yml").read_bytes(),
        run_state / "worldline.jsonl": b'{"worldline_seq":1}\n',
        run_state / "ledger.yml": b"run_id: cleanup-test\ntrajectory: []\n",
        run_state / "task-map.mmd": b"graph TD\n  T14[Ticket 14]\n",
        evidence / "result.md": b"# Engineer result\nCandidate ready.\n",
        evidence / "validation.md": b"# Validation\nReal Git tests passed.\n",
        reviews
        / "2-14-cleanup-integrated-worktrees@e1-r1-standards.md": b"No standards findings.\n",
        reviews
        / "2-14-cleanup-integrated-worktrees@e1-r1-spec.md": b"No spec findings.\n",
        reviews
        / "2-14-cleanup-integrated-worktrees@e2-r2-standards.md": b"No standards findings.\n",
        reviews
        / "2-14-cleanup-integrated-worktrees@e2-r2-spec.md": b"No spec findings.\n",
    }
    for path, content in retained_files.items():
        if not path.exists():
            path.write_bytes(content)
    retained_files[evidence / "metadata.yml"] = (
        evidence / "metadata.yml"
    ).read_bytes()
    retained_before = {
        path: path.read_bytes() for path in retained_files
    }

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert yaml.safe_load(result.stdout) == {
        "run_id": launched.run_id,
        "ticket_id": launched.ticket_id,
        "cleanup_status": "cleaned",
        "worktree_path": str(launched.worktree),
        "branch": launched.branch,
        "aliases_removed": [launched.alias, second_alias],
        "evidence": {
            "integration_branch": "dev",
            "integration_commit": integration_commit,
            "ticket_commit": ticket_commit,
        },
    }
    assert not launched.worktree.exists()
    assert run_process(
        [
            "git",
            "show-ref",
            "--verify",
            "--quiet",
            "refs/heads/{0}".format(launched.branch),
        ],
        cwd=launched.integration,
    ).returncode == 1
    assert not launched.session_directory.exists()
    assert not second_session.exists()
    assert {
        path: path.read_bytes() for path in retained_files
    } == retained_before
    assert launched.ticket_file.read_bytes() == retained_before[launched.ticket_file]
    assert launched.integration.is_dir()
    assert launched.primary.is_dir()


def test_installed_cleanup_succeeds_idempotently_after_disposable_state_is_gone(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    evidence = (
        launched.harness_root
        / "state"
        / "task-delivery"
        / launched.run_id
        / "tickets"
        / "2-14-cleanup-integrated-worktrees"
    )
    metadata_before = (evidence / "metadata.yml").read_bytes()
    first = cleanup_ticket(installed_cleanup_commands, launched)
    assert first.returncode == 0, first.stderr

    repeated = cleanup_ticket(installed_cleanup_commands, launched)

    assert repeated.returncode == 0, repeated.stderr
    assert repeated.stderr == ""
    assert yaml.safe_load(repeated.stdout) == {
        "run_id": launched.run_id,
        "ticket_id": launched.ticket_id,
        "cleanup_status": "already-cleaned",
        "worktree_path": str(launched.worktree),
        "branch": launched.branch,
        "aliases_removed": [],
        "evidence": {"disposable_state": "absent"},
    }
    assert not launched.worktree.exists()
    assert not launched.session_directory.exists()
    assert (evidence / "metadata.yml").read_bytes() == metadata_before


def test_retired_alias_text_is_reusable_without_losing_run_scoped_history(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    old_evidence = (
        launched.harness_root
        / "state"
        / "task-delivery"
        / launched.run_id
        / "tickets"
        / "2-14-cleanup-integrated-worktrees"
    )
    old_reviews = old_evidence / "reviews"
    old_reviews.mkdir()
    historical_report = (
        old_reviews / "{0}-r1-spec.md".format(launched.alias)
    )
    historical_report.write_text("Retained old-run review.\n", encoding="utf-8")
    old_metadata = (old_evidence / "metadata.yml").read_bytes()
    first_cleanup = cleanup_ticket(installed_cleanup_commands, launched)
    assert first_cleanup.returncode == 0, first_cleanup.stderr

    later_run = "20260813-later-cleanup-run"
    later_batch = launched.harness_root / "later-launch-batch.yml"
    later_batch.write_text(
        yaml.safe_dump(
            {
                "run_id": later_run,
                "runtime": "codex",
                "tasks": [
                    {
                        "ticket_id": launched.ticket_id,
                        "ticket_name": "cleanup-integrated-worktrees",
                        "role": "engineer-expert",
                        "ticket_file": str(launched.ticket_file),
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    later_release = tmp_path / "allow-later-run-to-finish"
    later_environment = dict(launched.environment)
    later_environment["FAKE_CODEX_RELEASE_FILE"] = str(later_release)
    later_launch = run_process(
        [
            str(installed_cleanup_commands.runner),
            "--batch-input",
            str(later_batch),
        ],
        cwd=launched.harness_root,
        env=later_environment,
    )
    assert later_launch.returncode == 0, later_launch.stderr
    later_task = yaml.safe_load(later_launch.stdout)["tasks"][0]
    assert later_task["alias"] == launched.alias
    later_worktree = Path(later_task["worktree_path"])
    later_session = launched.session_directory.parent / later_task["alias"]

    try:
        repeated_old_cleanup = cleanup_ticket(installed_cleanup_commands, launched)

        assert repeated_old_cleanup.returncode == 0, repeated_old_cleanup.stderr
        assert yaml.safe_load(repeated_old_cleanup.stdout)["cleanup_status"] == (
            "already-cleaned"
        )
        assert later_worktree.is_dir()
        assert later_session.is_dir()
        later_mapping = yaml.safe_load(
            (later_session / "mapping.yml").read_text(encoding="utf-8")
        )
        assert later_mapping["run_id"] == later_run
        assert later_mapping["ticket_id"] == launched.ticket_id
        assert historical_report.read_text(encoding="utf-8") == (
            "Retained old-run review.\n"
        )
        assert (old_evidence / "metadata.yml").read_bytes() == old_metadata
    finally:
        later_release.touch()
        wait_for_file(later_session / "turn.yml")


def test_same_run_relaunch_after_cleanup_allocates_a_new_historical_alias(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    first_cleanup = cleanup_ticket(installed_cleanup_commands, launched)
    assert first_cleanup.returncode == 0, first_cleanup.stderr

    relaunched = run_process(
        [
            str(installed_cleanup_commands.runner),
            "--batch-input",
            str(launched.batch_file),
        ],
        cwd=launched.harness_root,
        env=launched.environment,
    )

    assert relaunched.returncode == 0, relaunched.stderr
    task = yaml.safe_load(relaunched.stdout)["tasks"][0]
    assert task["alias"] == "2-14-cleanup-integrated-worktrees@e2"
    session = launched.session_directory.parent / task["alias"]
    wait_for_file(session / "turn.yml")
    metadata = yaml.safe_load(
        (
            launched.harness_root
            / "state"
            / "task-delivery"
            / launched.run_id
            / "tickets"
            / "2-14-cleanup-integrated-worktrees"
            / "metadata.yml"
        ).read_text(encoding="utf-8")
    )
    assert metadata["aliases"] == [
        launched.alias,
        "2-14-cleanup-integrated-worktrees@e2",
    ]


def test_installed_cleanup_refuses_an_unregistered_supplied_ticket_identity(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )

    result = run_process(
        [
            str(installed_cleanup_commands.runner),
            "cleanup",
            "--run-id",
            launched.run_id,
            "--ticket-id",
            "99",
        ],
        cwd=launched.harness_root,
        env=launched.environment,
    )

    message = "No canonical ticket registration belongs to the supplied identities."
    assert result.returncode == 1
    assert yaml.safe_load(result.stdout) == {
        "run_id": launched.run_id,
        "ticket_id": "99",
        "cleanup_status": "refused",
        "error": {"code": "cleanup-ownership-mismatch", "message": message},
        "evidence": {"registration": "not-found"},
    }
    assert result.stderr == message + "\n"
    assert launched.worktree.is_dir()
    assert launched.session_directory.is_dir()


def test_installed_cleanup_refuses_a_consistently_forged_overlong_ticket_name(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    ticket_name = "a" * 65
    stem = "2-14-{0}".format(ticket_name)
    branch = "agent/{0}/{1}".format(launched.run_id, stem)
    worktree = launched.worktree.parent / stem
    run_process(
        ["git", "worktree", "move", str(launched.worktree), str(worktree)],
        cwd=launched.primary,
    ).check_returncode()
    run_process(["git", "branch", "-m", branch], cwd=worktree).check_returncode()

    ticket_root = (
        launched.harness_root
        / "state"
        / "task-delivery"
        / launched.run_id
        / "tickets"
    )
    old_evidence = ticket_root / launched.worktree.name
    evidence = ticket_root / stem
    old_evidence.rename(evidence)
    alias = "{0}@e1".format(stem)
    session = launched.session_directory.parent / alias
    launched.session_directory.rename(session)
    metadata_file = evidence / "metadata.yml"
    metadata = yaml.safe_load(metadata_file.read_text(encoding="utf-8"))
    metadata.update(
        {
            "ticket_name": ticket_name,
            "branch": branch,
            "worktree_path": str(worktree),
            "alias": alias,
        }
    )
    metadata_file.write_text(
        yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8"
    )
    mapping_file = session / "mapping.yml"
    mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
    mapping.update(
        {
            "alias": alias,
            "ticket_name": ticket_name,
            "branch": branch,
            "worktree_path": str(worktree),
            "evidence_path": str(evidence),
        }
    )
    mapping_file.write_text(
        yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8"
    )

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 1
    assert yaml.safe_load(result.stdout)["error"]["code"] == (
        "cleanup-ownership-mismatch"
    )
    assert yaml.safe_load(result.stdout)["evidence"] == {
        "registration": "invalid"
    }
    assert worktree.is_dir()
    assert session.is_dir()
    assert metadata_file.is_file()


def test_installed_cleanup_resumes_after_the_worktree_was_already_removed(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    ticket_commit = git_output(launched.worktree, "rev-parse", "HEAD")
    integration_commit = git_output(launched.integration, "rev-parse", "HEAD")
    run_process(
        ["git", "worktree", "remove", str(launched.worktree)],
        cwd=launched.integration,
    ).check_returncode()
    assert not launched.worktree.exists()

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(result.stdout) == {
        "run_id": launched.run_id,
        "ticket_id": launched.ticket_id,
        "cleanup_status": "cleaned",
        "worktree_path": str(launched.worktree),
        "branch": launched.branch,
        "aliases_removed": [launched.alias],
        "evidence": {
            "integration_branch": "dev",
            "integration_commit": integration_commit,
            "ticket_commit": ticket_commit,
        },
    }
    assert not launched.session_directory.exists()
    assert run_process(
        [
            "git",
            "show-ref",
            "--verify",
            "--quiet",
            "refs/heads/{0}".format(launched.branch),
        ],
        cwd=launched.integration,
    ).returncode == 1


def test_installed_cleanup_refuses_a_new_alias_during_branch_only_recovery(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    ticket_commit = git_output(launched.worktree, "rev-parse", "HEAD")
    retained_alias = tmp_path / "retained-alias-diagnostics"
    shutil.copytree(launched.session_directory, retained_alias)
    shutil.rmtree(launched.session_directory)
    run_process(
        ["git", "worktree", "remove", str(launched.worktree)],
        cwd=launched.integration,
    ).check_returncode()
    hook_started = tmp_path / "branch-only-merge-check-started"
    hook_release = tmp_path / "branch-only-merge-check-release"
    real_git = shutil.which("git")
    assert real_git is not None
    wrapper_directory = tmp_path / "branch-only-race-git"
    wrapper_directory.mkdir()
    wrapper = wrapper_directory / "git"
    wrapper.write_text(
        "#!{0}\n".format(sys.executable)
        + "import os\n"
        + "import sys\n"
        + "import time\n"
        + "from pathlib import Path\n"
        + "if sys.argv[1:3] == ['merge-base', '--is-ancestor']:\n"
        + "    Path(os.environ['CLEANUP_TEST_HOOK_STARTED']).touch()\n"
        + "    release = Path(os.environ['CLEANUP_TEST_HOOK_RELEASE'])\n"
        + "    while not release.exists():\n"
        + "        time.sleep(0.01)\n"
        + "os.execv({0!r}, [{0!r}, *sys.argv[1:]])\n".format(real_git),
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    environment = dict(launched.environment)
    environment.update(
        {
            "CLEANUP_TEST_HOOK_STARTED": str(hook_started),
            "CLEANUP_TEST_HOOK_RELEASE": str(hook_release),
            "PATH": "{0}{1}{2}".format(
                wrapper_directory, os.pathsep, environment["PATH"]
            ),
        }
    )
    cleanup_process = subprocess.Popen(
        [
            str(installed_cleanup_commands.runner),
            "cleanup",
            "--run-id",
            launched.run_id,
            "--ticket-id",
            launched.ticket_id,
        ],
        cwd=launched.harness_root,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        wait_for_file(hook_started)
        shutil.copytree(retained_alias, launched.session_directory)
    finally:
        hook_release.touch()

    cleanup_stdout, cleanup_stderr = cleanup_process.communicate(timeout=10)
    assert cleanup_process.returncode == 1
    assert yaml.safe_load(cleanup_stdout)["evidence"] == {
        "completed_actions": []
    }
    assert cleanup_stderr.endswith("\n")
    assert launched.session_directory.is_dir()
    assert git_output(launched.primary, "rev-parse", launched.branch) == ticket_commit


def test_installed_cleanup_refuses_alias_removal_without_live_git_integration_proof(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    integration_commit = git_output(launched.integration, "rev-parse", "HEAD")
    run_process(
        ["git", "worktree", "remove", str(launched.worktree)],
        cwd=launched.integration,
    ).check_returncode()
    run_process(
        ["git", "branch", "-d", launched.branch],
        cwd=launched.integration,
    ).check_returncode()

    result = cleanup_ticket(installed_cleanup_commands, launched)

    message = (
        "The Ticket branch is unavailable, so integration cannot be verified."
    )
    assert result.returncode == 1
    assert yaml.safe_load(result.stdout) == {
        "run_id": launched.run_id,
        "ticket_id": launched.ticket_id,
        "cleanup_status": "refused",
        "worktree_path": str(launched.worktree),
        "branch": launched.branch,
        "error": {"code": "cleanup-not-merged", "message": message},
        "evidence": {
            "integration_branch": "dev",
            "integration_commit": integration_commit,
            "ticket_branch": "absent",
            "worktree": "absent",
        },
    }
    assert result.stderr == message + "\n"
    assert launched.session_directory.is_dir()


def test_installed_cleanup_reservation_blocks_a_concurrent_ticket_launch(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    hook_started = tmp_path / "cleanup-reference-transaction-started"
    hook_release = tmp_path / "cleanup-reference-transaction-release"
    hook = common_git_directory(launched.primary) / "hooks" / "reference-transaction"
    hook.write_text(
        "#!{0}\n".format(sys.executable)
        + "import os\n"
        + "import sys\n"
        + "import time\n"
        + "from pathlib import Path\n"
        + "updates = sys.stdin.read()\n"
        + "target = os.environ.get('CLEANUP_TEST_BRANCH_REF')\n"
        + "if sys.argv[1] == 'prepared' and target and target in updates:\n"
        + "    Path(os.environ['CLEANUP_TEST_HOOK_STARTED']).touch()\n"
        + "    release = Path(os.environ['CLEANUP_TEST_HOOK_RELEASE'])\n"
        + "    while not release.exists():\n"
        + "        time.sleep(0.01)\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)
    cleanup_environment = dict(launched.environment)
    cleanup_environment.update(
        {
            "CLEANUP_TEST_BRANCH_REF": "refs/heads/{0}".format(launched.branch),
            "CLEANUP_TEST_HOOK_STARTED": str(hook_started),
            "CLEANUP_TEST_HOOK_RELEASE": str(hook_release),
        }
    )
    cleanup_command = [
        str(installed_cleanup_commands.runner),
        "cleanup",
        "--run-id",
        launched.run_id,
        "--ticket-id",
        launched.ticket_id,
    ]
    cleanup_process = subprocess.Popen(
        cleanup_command,
        cwd=launched.harness_root,
        env=cleanup_environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        wait_for_file(hook_started)
        concurrent_launch = run_process(
            [
                str(installed_cleanup_commands.runner),
                "--batch-input",
                str(launched.batch_file),
            ],
            cwd=launched.harness_root,
            env=launched.environment,
        )

        assert concurrent_launch.returncode == 1
        assert yaml.safe_load(concurrent_launch.stdout) == {
            "error": {
                "code": "worktree-busy",
                "message": "The Ticket Worktree already has an active Engineer turn.",
            }
        }
    finally:
        hook_release.touch()

    cleanup_stdout, cleanup_stderr = cleanup_process.communicate(timeout=10)
    assert cleanup_process.returncode == 0, cleanup_stderr
    assert yaml.safe_load(cleanup_stdout)["cleanup_status"] == "cleaned"


@pytest.mark.parametrize("replacement", ("symlink", "rename-only"))
def test_installed_cleanup_refuses_a_replaced_reservation_identity(
    replacement: str,
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    hook_started = tmp_path / "cleanup-worktree-removal-started"
    hook_release = tmp_path / "cleanup-worktree-removal-release"
    real_git = shutil.which("git")
    assert real_git is not None
    wrapper_directory = tmp_path / "reservation-race-git"
    wrapper_directory.mkdir()
    wrapper = wrapper_directory / "git"
    wrapper.write_text(
        "#!{0}\n".format(sys.executable)
        + "import os\n"
        + "import sys\n"
        + "import time\n"
        + "from pathlib import Path\n"
        + "if sys.argv[1:3] == ['worktree', 'remove']:\n"
        + "    Path(os.environ['CLEANUP_TEST_HOOK_STARTED']).touch()\n"
        + "    release = Path(os.environ['CLEANUP_TEST_HOOK_RELEASE'])\n"
        + "    while not release.exists():\n"
        + "        time.sleep(0.01)\n"
        + "os.execv({0!r}, [{0!r}, *sys.argv[1:]])\n".format(real_git),
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    environment = dict(launched.environment)
    environment.update(
        {
            "CLEANUP_TEST_HOOK_STARTED": str(hook_started),
            "CLEANUP_TEST_HOOK_RELEASE": str(hook_release),
            "PATH": "{0}{1}{2}".format(
                wrapper_directory, os.pathsep, environment["PATH"]
            ),
        }
    )
    cleanup_process = subprocess.Popen(
        [
            str(installed_cleanup_commands.runner),
            "cleanup",
            "--run-id",
            launched.run_id,
            "--ticket-id",
            launched.ticket_id,
        ],
        cwd=launched.harness_root,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    active_root = (
        launched.harness_root
        / ".codex"
        / "agent-runner"
        / "active-worktrees"
    )
    reservation = active_root / hashlib.sha256(b"14").hexdigest()
    retained_reservation = active_root / "retained-reservation"
    external = tmp_path / "external-reservation"
    external.write_text("external: preserve\n", encoding="utf-8")
    try:
        wait_for_file(hook_started)
        reservation.rename(retained_reservation)
        if replacement == "symlink":
            reservation.symlink_to(external)
    finally:
        hook_release.touch()

    cleanup_stdout, cleanup_stderr = cleanup_process.communicate(timeout=10)
    assert cleanup_process.returncode == 1
    assert yaml.safe_load(cleanup_stdout)["evidence"] == {
        "reservation": "release-failed"
    }
    assert cleanup_stderr.endswith("\n")
    assert external.read_text(encoding="utf-8") == "external: preserve\n"
    assert retained_reservation.is_file()
    if replacement == "symlink":
        assert reservation.is_symlink()
    else:
        assert not os.path.lexists(str(reservation))
        repeated = cleanup_ticket(installed_cleanup_commands, launched)
        assert repeated.returncode == 1
        repeated_document = yaml.safe_load(repeated.stdout)
        assert repeated_document["cleanup_status"] == "refused"
        assert repeated_document["error"]["code"] == (
            "cleanup-ownership-mismatch"
        )
        assert repeated_document["evidence"] == {
            "active_turn": "orphaned"
        }
        assert retained_reservation.is_file()


def test_installed_cleanup_refuses_a_replaced_bound_alias_identity(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    hook_started = tmp_path / "alias-replacement-worktree-removal-started"
    hook_release = tmp_path / "alias-replacement-worktree-removal-release"
    real_git = shutil.which("git")
    assert real_git is not None
    wrapper_directory = tmp_path / "alias-race-git"
    wrapper_directory.mkdir()
    wrapper = wrapper_directory / "git"
    wrapper.write_text(
        "#!{0}\n".format(sys.executable)
        + "import os\n"
        + "import sys\n"
        + "import time\n"
        + "from pathlib import Path\n"
        + "if sys.argv[1:3] == ['worktree', 'remove']:\n"
        + "    Path(os.environ['CLEANUP_TEST_HOOK_STARTED']).touch()\n"
        + "    release = Path(os.environ['CLEANUP_TEST_HOOK_RELEASE'])\n"
        + "    while not release.exists():\n"
        + "        time.sleep(0.01)\n"
        + "os.execv({0!r}, [{0!r}, *sys.argv[1:]])\n".format(real_git),
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    environment = dict(launched.environment)
    environment.update(
        {
            "CLEANUP_TEST_HOOK_STARTED": str(hook_started),
            "CLEANUP_TEST_HOOK_RELEASE": str(hook_release),
            "PATH": "{0}{1}{2}".format(
                wrapper_directory, os.pathsep, environment["PATH"]
            ),
        }
    )
    cleanup_process = subprocess.Popen(
        [
            str(installed_cleanup_commands.runner),
            "cleanup",
            "--run-id",
            launched.run_id,
            "--ticket-id",
            launched.ticket_id,
        ],
        cwd=launched.harness_root,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    retained_alias = launched.session_directory.with_name(
        launched.alias + "-retained"
    )
    try:
        wait_for_file(hook_started)
        launched.session_directory.rename(retained_alias)
        launched.session_directory.mkdir()
        for diagnostic in retained_alias.iterdir():
            if diagnostic.is_file():
                shutil.copy2(diagnostic, launched.session_directory / diagnostic.name)
    finally:
        hook_release.touch()

    cleanup_stdout, cleanup_stderr = cleanup_process.communicate(timeout=10)
    assert cleanup_process.returncode == 1
    document = yaml.safe_load(cleanup_stdout)
    assert document["error"]["code"] == "cleanup-failed"
    assert document["evidence"] == {
        "completed_actions": ["worktree-removed"]
    }
    assert cleanup_stderr.endswith("\n")
    assert retained_alias.is_dir()
    assert launched.session_directory.is_dir()
    assert (launched.session_directory / "mapping.yml").is_file()
    assert git_output(launched.primary, "rev-parse", launched.branch)


def test_installed_cleanup_refuses_a_new_bound_alias_after_inspection(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    hook_started = tmp_path / "new-alias-worktree-removal-started"
    hook_release = tmp_path / "new-alias-worktree-removal-release"
    real_git = shutil.which("git")
    assert real_git is not None
    wrapper_directory = tmp_path / "new-alias-race-git"
    wrapper_directory.mkdir()
    wrapper = wrapper_directory / "git"
    wrapper.write_text(
        "#!{0}\n".format(sys.executable)
        + "import os\n"
        + "import sys\n"
        + "import time\n"
        + "from pathlib import Path\n"
        + "if sys.argv[1:3] == ['worktree', 'remove']:\n"
        + "    Path(os.environ['CLEANUP_TEST_HOOK_STARTED']).touch()\n"
        + "    release = Path(os.environ['CLEANUP_TEST_HOOK_RELEASE'])\n"
        + "    while not release.exists():\n"
        + "        time.sleep(0.01)\n"
        + "os.execv({0!r}, [{0!r}, *sys.argv[1:]])\n".format(real_git),
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    environment = dict(launched.environment)
    environment.update(
        {
            "CLEANUP_TEST_HOOK_STARTED": str(hook_started),
            "CLEANUP_TEST_HOOK_RELEASE": str(hook_release),
            "PATH": "{0}{1}{2}".format(
                wrapper_directory, os.pathsep, environment["PATH"]
            ),
        }
    )
    cleanup_process = subprocess.Popen(
        [
            str(installed_cleanup_commands.runner),
            "cleanup",
            "--run-id",
            launched.run_id,
            "--ticket-id",
            launched.ticket_id,
        ],
        cwd=launched.harness_root,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    added_alias = launched.session_directory.with_name(
        launched.worktree.name + "@e2"
    )
    try:
        wait_for_file(hook_started)
        shutil.copytree(launched.session_directory, added_alias)
        mapping_file = added_alias / "mapping.yml"
        mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
        mapping["alias"] = added_alias.name
        mapping_file.write_text(
            yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8"
        )
    finally:
        hook_release.touch()

    cleanup_stdout, cleanup_stderr = cleanup_process.communicate(timeout=10)
    assert cleanup_process.returncode == 1
    assert yaml.safe_load(cleanup_stdout)["evidence"] == {
        "completed_actions": ["worktree-removed"]
    }
    assert cleanup_stderr.endswith("\n")
    assert launched.session_directory.is_dir()
    assert added_alias.is_dir()
    assert git_output(launched.primary, "rev-parse", launched.branch)


def test_installed_cleanup_refuses_an_in_place_mapping_rewrite_after_inspection(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    hook_started = tmp_path / "mapping-rewrite-worktree-removal-started"
    hook_release = tmp_path / "mapping-rewrite-worktree-removal-release"
    real_git = shutil.which("git")
    assert real_git is not None
    wrapper_directory = tmp_path / "mapping-rewrite-race-git"
    wrapper_directory.mkdir()
    wrapper = wrapper_directory / "git"
    wrapper.write_text(
        "#!{0}\n".format(sys.executable)
        + "import os\n"
        + "import sys\n"
        + "import time\n"
        + "from pathlib import Path\n"
        + "if sys.argv[1:3] == ['worktree', 'remove']:\n"
        + "    Path(os.environ['CLEANUP_TEST_HOOK_STARTED']).touch()\n"
        + "    release = Path(os.environ['CLEANUP_TEST_HOOK_RELEASE'])\n"
        + "    while not release.exists():\n"
        + "        time.sleep(0.01)\n"
        + "os.execv({0!r}, [{0!r}, *sys.argv[1:]])\n".format(real_git),
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    environment = dict(launched.environment)
    environment.update(
        {
            "CLEANUP_TEST_HOOK_STARTED": str(hook_started),
            "CLEANUP_TEST_HOOK_RELEASE": str(hook_release),
            "PATH": "{0}{1}{2}".format(
                wrapper_directory, os.pathsep, environment["PATH"]
            ),
        }
    )
    cleanup_process = subprocess.Popen(
        [
            str(installed_cleanup_commands.runner),
            "cleanup",
            "--run-id",
            launched.run_id,
            "--ticket-id",
            launched.ticket_id,
        ],
        cwd=launched.harness_root,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    mapping_file = launched.session_directory / "mapping.yml"
    before = mapping_file.stat()
    original = mapping_file.read_bytes()
    rewritten = original.replace(b"run_id:", b"bad_id:", 1)
    assert len(rewritten) == len(original)
    try:
        wait_for_file(hook_started)
        mapping_file.write_bytes(rewritten)
        os.utime(
            mapping_file,
            ns=(before.st_atime_ns, before.st_mtime_ns),
        )
    finally:
        hook_release.touch()

    cleanup_stdout, cleanup_stderr = cleanup_process.communicate(timeout=10)
    assert cleanup_process.returncode == 1
    assert yaml.safe_load(cleanup_stdout)["evidence"] == {
        "completed_actions": ["worktree-removed"]
    }
    assert cleanup_stderr.endswith("\n")
    assert mapping_file.read_bytes() == rewritten
    assert git_output(launched.primary, "rev-parse", launched.branch)


def test_installed_cleanup_does_not_require_a_clean_integration_worktree(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    integration_note = launched.integration / "main-coordination-note.txt"
    integration_note.write_text("Main still owns this change.\n", encoding="utf-8")

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(result.stdout)["cleanup_status"] == "cleaned"
    assert integration_note.read_text(encoding="utf-8") == (
        "Main still owns this change.\n"
    )
    assert not launched.worktree.exists()
    assert not launched.session_directory.exists()


def test_installed_cleanup_does_not_require_the_runtime_executable(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    fake_codex.executable.unlink()

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(result.stdout)["cleanup_status"] == "cleaned"
    assert not launched.worktree.exists()
    assert not launched.session_directory.exists()


def test_installed_cleanup_reports_a_cyclic_runtime_path_as_one_yaml_error(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    cyclic_runtime = tmp_path / "cyclic-runtime"
    cyclic_runtime.symlink_to(cyclic_runtime)
    config_file = launched.harness_root / ".codex" / "agent-runner" / "config.yml"
    config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    config["runtimes"]["codex"]["executable"] = str(cyclic_runtime)
    config_file.write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )

    result = cleanup_ticket(installed_cleanup_commands, launched)

    message = "Project Runner Config contains invalid project or Codex settings."
    assert result.returncode == 1
    assert yaml.safe_load(result.stdout) == {
        "error": {"code": "invalid-config", "message": message}
    }
    assert result.stderr == message + "\n"
    assert "Traceback" not in result.stderr
    assert launched.worktree.is_dir()
    assert launched.session_directory.is_dir()


def test_installed_cleanup_rejects_a_lexical_state_root_symlink(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    state_root = launched.harness_root / "state"
    retained_state = launched.harness_root / "state-retained"
    state_root.rename(retained_state)
    state_root.symlink_to(retained_state, target_is_directory=True)
    evidence = (
        retained_state
        / "task-delivery"
        / launched.run_id
        / "tickets"
        / launched.worktree.name
    )
    mapping_file = launched.session_directory / "mapping.yml"
    mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
    mapping["evidence_path"] = str(evidence)
    mapping_file.write_text(
        yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8"
    )
    metadata_file = evidence / "metadata.yml"
    evidence_before = metadata_file.read_bytes()

    result = cleanup_ticket(installed_cleanup_commands, launched)

    message = "Project Runner Config contains invalid project or Codex settings."
    assert result.returncode == 1
    assert yaml.safe_load(result.stdout) == {
        "error": {"code": "invalid-config", "message": message}
    }
    assert result.stderr == message + "\n"
    assert metadata_file.read_bytes() == evidence_before
    assert launched.worktree.is_dir()
    assert launched.session_directory.is_dir()


def test_installed_cleanup_reports_missing_identities_as_one_yaml_error(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    result = run_process(
        [str(installed_cleanup_commands.runner), "cleanup"],
        cwd=temporary_git_repository,
    )

    message = "Cleanup requires --run-id and --ticket-id."
    assert result.returncode == 1
    assert yaml.safe_load(result.stdout) == {
        "error": {"code": "invalid-input", "message": message}
    }
    assert result.stderr == message + "\n"
    assert "Usage:" not in result.stderr


def test_installed_cleanup_refuses_a_bound_mapping_in_a_renamed_alias_directory(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    renamed_session = launched.session_directory.parent / "renamed-session"
    launched.session_directory.rename(renamed_session)

    result = cleanup_ticket(installed_cleanup_commands, launched)

    message = (
        "The registered Ticket Worktree does not belong to the supplied "
        "run and ticket identities."
    )
    assert result.returncode == 1
    assert yaml.safe_load(result.stdout)["error"] == {
        "code": "cleanup-ownership-mismatch",
        "message": message,
    }
    assert yaml.safe_load(result.stdout)["evidence"] == {
        "ownership_mismatches": ["alias-name-mismatch"]
    }
    assert launched.worktree.is_dir()
    assert renamed_session.is_dir()


def test_installed_cleanup_refuses_an_unattributable_turn_reservation(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    reservation_key = hashlib.sha256(
        launched.ticket_id.encode("ascii")
    ).hexdigest()
    reservation = (
        launched.harness_root
        / ".codex"
        / "agent-runner"
        / "active-worktrees"
        / reservation_key
    )
    reservation.write_text("- invalid\n", encoding="utf-8")

    result = cleanup_ticket(installed_cleanup_commands, launched)

    message = "The active-turn reservation cannot be attributed safely."
    assert result.returncode == 1
    assert yaml.safe_load(result.stdout) == {
        "run_id": launched.run_id,
        "ticket_id": launched.ticket_id,
        "cleanup_status": "refused",
        "worktree_path": str(launched.worktree),
        "branch": launched.branch,
        "error": {"code": "cleanup-ownership-mismatch", "message": message},
        "evidence": {"active_turn": "invalid"},
    }
    assert result.stderr == message + "\n"
    assert launched.worktree.is_dir()
    assert launched.session_directory.is_dir()


def test_installed_cleanup_removes_aliases_from_every_engineer_tier(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    senior_batch = launched.harness_root / "senior-launch-batch.yml"
    senior_batch.write_text(
        yaml.safe_dump(
            {
                "run_id": launched.run_id,
                "runtime": "codex",
                "tasks": [
                    {
                        "ticket_id": launched.ticket_id,
                        "ticket_name": "cleanup-integrated-worktrees",
                        "role": "engineer-senior",
                        "ticket_file": str(launched.ticket_file),
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    senior_launch = run_process(
        [
            str(installed_cleanup_commands.runner),
            "--batch-input",
            str(senior_batch),
        ],
        cwd=launched.harness_root,
        env=launched.environment,
    )
    assert senior_launch.returncode == 0, senior_launch.stderr
    senior_alias = yaml.safe_load(senior_launch.stdout)["tasks"][0]["alias"]
    assert senior_alias == "2-14-cleanup-integrated-worktrees@s1"
    senior_session = launched.session_directory.parent / senior_alias
    wait_for_file(senior_session / "turn.yml")

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(result.stdout)["aliases_removed"] == [
        launched.alias,
        senior_alias,
    ]
    assert not launched.session_directory.exists()
    assert not senior_session.exists()


def test_installed_cleanup_removes_failed_alias_diagnostics_with_a_valid_launch_mapping(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    failed_environment = dict(launched.environment)
    failed_environment["FAKE_CODEX_EVENTS"] = '[{"type": "turn.started"}]'
    failed_launch = run_process(
        [
            str(installed_cleanup_commands.runner),
            "--batch-input",
            str(launched.batch_file),
        ],
        cwd=launched.harness_root,
        env=failed_environment,
    )
    assert failed_launch.returncode == 1
    failed_alias = "2-14-cleanup-integrated-worktrees@e2"
    failed_session = launched.session_directory.parent / failed_alias
    assert (failed_session / "launch.yml").is_file()
    assert (failed_session / "launch-error.yml").is_file()
    assert not (failed_session / "mapping.yml").exists()

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(result.stdout)["aliases_removed"] == [
        launched.alias,
        failed_alias,
    ]
    assert not launched.session_directory.exists()
    assert not failed_session.exists()


def test_terminal_turn_is_durable_before_the_worker_releases_ownership(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_ROOT / "src"))
    from you_are_a_product_architect import runner_worker

    session = tmp_path / "agent-runner" / "sessions" / "ticket@e1"
    session.mkdir(parents=True)
    launch_file = session / "launch.yml"
    launch_file.write_text(
        yaml.safe_dump(
            {
                "active_turn_key": "a" * 64,
                "active_turn_device": session.stat().st_dev,
                "active_turn_inode": session.stat().st_ino,
                "runtime": "codex",
                "adapter_request": {},
                "mapping": {
                    "alias": "ticket@e1",
                    "run_id": "20260829-terminal-order",
                    "ticket_id": "61",
                    "role": "engineer-senior",
                    "evidence_path": str(
                        tmp_path
                        / "20260829-terminal-order"
                        / "tickets"
                        / "2-61-terminal-order"
                    ),
                    "turn": 1,
                },
            }
        ),
        encoding="utf-8",
    )

    class CompletedTurn:
        def run(self) -> dict[str, object]:
            return {"outcome": "completed", "runtime_exit_code": 0}

        def terminate(self) -> bool:
            return True

        def terminate_until_terminal(self) -> None:
            return None

    def create_turn(
        request: object,
        prompt: str,
        session_directory: Path,
        record_session: object,
    ) -> CompletedTurn:
        record_session("thread-terminal-order", 1234)  # type: ignore[operator]
        return CompletedTurn()

    release_observations: list[bool] = []
    monkeypatch.setitem(runner_worker.ADAPTERS, "codex", create_turn)
    monkeypatch.setattr(sys, "stdin", io.StringIO("ticket prompt"))
    monkeypatch.setattr(
        runner_worker,
        "write_active_turn_owner",
        lambda runner_directory, reservation, owner: None,
    )
    monkeypatch.setattr(
        runner_worker,
        "release_active_turn",
        lambda runner_directory, key: release_observations.append(
            (session / "turn.yml").is_file()
        ),
    )

    assert runner_worker.run(launch_file) == 0
    assert release_observations == [True]


def test_installed_cleanup_refuses_a_broken_session_root_symlink(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    session_root = launched.session_directory.parent
    retained_sessions = session_root.with_name("sessions-retained-for-test")
    session_root.rename(retained_sessions)
    session_root.symlink_to(session_root.with_name("missing-sessions"), target_is_directory=True)

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 1
    document = yaml.safe_load(result.stdout)
    assert document["error"]["code"] == "cleanup-ownership-mismatch"
    assert document["evidence"] == {
        "ownership_mismatches": ["session-root-invalid"]
    }
    assert launched.worktree.is_dir()
    assert (retained_sessions / launched.alias).is_dir()


def test_installed_cleanup_refuses_a_missing_live_session_root(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    session_root = launched.session_directory.parent
    retained_sessions = session_root.with_name("sessions-retained")
    session_root.rename(retained_sessions)
    retained_alias = retained_sessions / launched.alias

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 1
    document = yaml.safe_load(result.stdout)
    assert document["error"]["code"] == "cleanup-ownership-mismatch"
    assert document["evidence"] == {
        "ownership_mismatches": ["session-root-missing"]
    }
    assert launched.worktree.is_dir()
    assert retained_alias.is_dir()


def test_installed_cleanup_refuses_a_missing_metadata_registered_alias(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    retained_alias = launched.session_directory.parent.parent / "retained-alias"
    launched.session_directory.rename(retained_alias)
    assert launched.session_directory.parent.is_dir()

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 1
    document = yaml.safe_load(result.stdout)
    assert document["error"]["code"] == "cleanup-ownership-mismatch"
    assert document["evidence"] == {
        "ownership_mismatches": ["registered-alias-missing"]
    }
    assert launched.worktree.is_dir()
    assert retained_alias.is_dir()
    assert (retained_alias / "mapping.yml").is_file()
    assert (retained_alias / "turn.yml").is_file()


def test_installed_cleanup_refuses_an_unknown_regular_alias_file(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    operator_file = launched.session_directory / "operator-note.txt"
    operator_file.write_text("not Runner transport state\n", encoding="utf-8")

    result = cleanup_ticket(installed_cleanup_commands, launched)

    message = "The bound alias diagnostics cannot be removed safely."
    assert result.returncode == 1
    assert yaml.safe_load(result.stdout)["error"] == {
        "code": "cleanup-failed",
        "message": message,
    }
    assert yaml.safe_load(result.stdout)["evidence"] == {
        "unsafe_alias_entries": [
            "{0}/operator-note.txt".format(launched.alias)
        ]
    }
    assert operator_file.read_text(encoding="utf-8") == (
        "not Runner transport state\n"
    )
    assert launched.worktree.is_dir()


def test_installed_cleanup_refuses_a_corrupt_renamed_alias_mapping(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    renamed_session = launched.session_directory.parent / "renamed-session"
    launched.session_directory.rename(renamed_session)
    (renamed_session / "mapping.yml").write_text("- corrupt\n", encoding="utf-8")

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 1
    document = yaml.safe_load(result.stdout)
    assert document["error"]["code"] == "cleanup-ownership-mismatch"
    assert document["evidence"] == {
        "ownership_mismatches": ["alias-mapping-invalid"]
    }
    assert launched.worktree.is_dir()
    assert renamed_session.is_dir()


def test_installed_cleanup_reports_early_git_inspection_failure_with_identity_evidence(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    run_process(
        ["git", "worktree", "remove", str(launched.worktree)],
        cwd=launched.integration,
    ).check_returncode()
    run_process(
        ["git", "branch", "-d", launched.branch],
        cwd=launched.integration,
    ).check_returncode()
    real_git = shutil.which("git")
    assert real_git is not None
    wrapper_directory = tmp_path / "failing-git"
    wrapper_directory.mkdir()
    wrapper = wrapper_directory / "git"
    wrapper.write_text(
        "#!{0}\n".format(sys.executable)
        + "import os\n"
        + "import sys\n"
        + "if sys.argv[1:4] == ['show-ref', '--verify', '--quiet']:\n"
        + "    raise SystemExit(73)\n"
        + "os.execv({0!r}, [{0!r}, *sys.argv[1:]])\n".format(real_git),
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    environment = dict(launched.environment)
    environment["PATH"] = "{0}{1}{2}".format(
        wrapper_directory, os.pathsep, environment["PATH"]
    )

    result = run_process(
        [
            str(installed_cleanup_commands.runner),
            "cleanup",
            "--run-id",
            launched.run_id,
            "--ticket-id",
            launched.ticket_id,
        ],
        cwd=launched.harness_root,
        env=environment,
    )

    message = "A required cleanup operation could not be verified."
    assert result.returncode == 1
    assert yaml.safe_load(result.stdout) == {
        "run_id": launched.run_id,
        "ticket_id": launched.ticket_id,
        "cleanup_status": "refused",
        "worktree_path": str(launched.worktree),
        "branch": launched.branch,
        "error": {"code": "cleanup-failed", "message": message},
        "evidence": {"cause": "operation-failed"},
    }
    assert result.stderr == message + "\n"
    assert not launched.worktree.exists()
    assert launched.session_directory.is_dir()


@pytest.mark.parametrize(
    "ticket_location",
    ("worktree", "alias", "git-common", "sibling-worktree"),
)
def test_installed_cleanup_never_deletes_a_registered_canonical_ticket(
    ticket_location: str,
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    if ticket_location == "worktree":
        ticket_file = launched.worktree / "ignored-canonical-ticket.md"
        exclude_file = Path(
            git_output(launched.worktree, "rev-parse", "--git-path", "info/exclude")
        )
        if not exclude_file.is_absolute():
            exclude_file = launched.worktree / exclude_file
        exclude_file.write_text(
            exclude_file.read_text(encoding="utf-8")
            + "\nignored-canonical-ticket.md\n",
            encoding="utf-8",
        )
        ticket_file.write_text("# Canonical ticket\n", encoding="utf-8")
        assert git_output(launched.worktree, "status", "--porcelain") == ""
    elif ticket_location == "alias":
        ticket_file = launched.session_directory / "turn.yml"
    elif ticket_location == "git-common":
        ticket_file = (
            common_git_directory(launched.primary)
            / "refs"
            / "heads"
            / Path(launched.branch)
        )
        assert ticket_file.is_file()
    else:
        ticket_file = launched.worktree.parent / "sibling-worktree" / "ticket.md"
        ticket_file.parent.mkdir()
        ticket_file.write_text("# Canonical ticket\n", encoding="utf-8")
    ticket_before = ticket_file.read_bytes()

    evidence = (
        launched.harness_root
        / "state"
        / "task-delivery"
        / launched.run_id
        / "tickets"
        / "2-14-cleanup-integrated-worktrees"
    )
    metadata_file = evidence / "metadata.yml"
    metadata = yaml.safe_load(metadata_file.read_text(encoding="utf-8"))
    metadata["ticket_file"] = str(ticket_file)
    metadata_file.write_text(
        yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8"
    )
    mapping_file = launched.session_directory / "mapping.yml"
    mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
    mapping["ticket_file"] = str(ticket_file)
    mapping_file.write_text(
        yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8"
    )

    result = cleanup_ticket(installed_cleanup_commands, launched)

    message = "The canonical ticket registration is invalid."
    assert result.returncode == 1
    assert yaml.safe_load(result.stdout) == {
        "run_id": launched.run_id,
        "ticket_id": launched.ticket_id,
        "cleanup_status": "refused",
        "error": {
            "code": "cleanup-ownership-mismatch",
            "message": message,
        },
        "evidence": {"registration": "invalid"},
    }
    assert result.stderr == message + "\n"
    assert ticket_file.read_bytes() == ticket_before
    assert launched.worktree.is_dir()
    assert launched.session_directory.is_dir()


def test_installed_cleanup_refuses_persistent_evidence_redirected_into_the_worktree(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    hidden_result = launched.worktree / "retained-result.md"
    exclude_file = Path(
        git_output(launched.worktree, "rev-parse", "--git-path", "info/exclude")
    )
    if not exclude_file.is_absolute():
        exclude_file = launched.worktree / exclude_file
    exclude_file.write_text(
        exclude_file.read_text(encoding="utf-8") + "\nretained-result.md\n",
        encoding="utf-8",
    )
    hidden_result.write_text("# Engineer result\n", encoding="utf-8")
    evidence = (
        launched.harness_root
        / "state"
        / "task-delivery"
        / launched.run_id
        / "tickets"
        / "2-14-cleanup-integrated-worktrees"
    )
    result_link = evidence / "result.md"
    result_link.symlink_to(hidden_result)

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 1
    document = yaml.safe_load(result.stdout)
    assert document["error"]["code"] == "cleanup-ownership-mismatch"
    assert document["evidence"] == {
        "ownership_mismatches": ["persistent-evidence-invalid"]
    }
    assert hidden_result.read_text(encoding="utf-8") == "# Engineer result\n"
    assert result_link.is_symlink()
    assert launched.worktree.is_dir()


def test_installed_cleanup_refuses_a_later_retained_batch_redirected_into_the_worktree(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    second_batch = launched.harness_root / "second-launch-batch.yml"
    second_document = yaml.safe_load(
        launched.batch_file.read_text(encoding="utf-8")
    )
    second_document["tasks"][0]["instruction"] = "Use a refreshed exact batch."
    second_batch.write_text(
        yaml.safe_dump(second_document, sort_keys=False), encoding="utf-8"
    )
    second_launch = run_process(
        [
            str(installed_cleanup_commands.runner),
            "--batch-input",
            str(second_batch),
        ],
        cwd=launched.harness_root,
        env=launched.environment,
    )
    assert second_launch.returncode == 0, second_launch.stderr
    second_alias = yaml.safe_load(second_launch.stdout)["tasks"][0]["alias"]
    wait_for_file(launched.session_directory.parent / second_alias / "turn.yml")
    run_root = (
        launched.harness_root
        / "state"
        / "task-delivery"
        / launched.run_id
    )
    retained_batch = run_root / "batch-2.yml"
    assert retained_batch.is_file()
    retained_content = retained_batch.read_bytes()
    hidden_batch = launched.worktree / "retained-batch.yml"
    exclude_file = Path(
        git_output(launched.worktree, "rev-parse", "--git-path", "info/exclude")
    )
    if not exclude_file.is_absolute():
        exclude_file = launched.worktree / exclude_file
    exclude_file.write_text(
        exclude_file.read_text(encoding="utf-8") + "\nretained-batch.yml\n",
        encoding="utf-8",
    )
    hidden_batch.write_bytes(retained_content)
    retained_batch.unlink()
    retained_batch.symlink_to(hidden_batch)

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 1
    assert yaml.safe_load(result.stdout)["evidence"] == {
        "ownership_mismatches": ["persistent-evidence-invalid"]
    }
    assert hidden_batch.read_bytes() == retained_content
    assert retained_batch.is_symlink()
    assert launched.worktree.is_dir()


def test_installed_cleanup_refuses_a_state_root_redirected_into_the_worktree(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    state_root = launched.harness_root / "state"
    run_root = state_root / "task-delivery" / launched.run_id
    evidence = run_root / "tickets" / "2-14-cleanup-integrated-worktrees"
    reviews = evidence / "reviews"
    reviews.mkdir()
    retained_files = {
        run_root / "batch.yml": (run_root / "batch.yml").read_bytes(),
        run_root / "worldline.jsonl": b'{"worldline_seq":1}\n',
        run_root / "ledger.yml": b"run_id: cleanup-test\ntrajectory: []\n",
        run_root / "task-map.mmd": b"graph TD\n  T14[Ticket 14]\n",
        evidence / "metadata.yml": (evidence / "metadata.yml").read_bytes(),
        evidence / "result.md": b"# Engineer result\nCandidate ready.\n",
        evidence / "validation.md": b"# Validation\nReal Git tests passed.\n",
        reviews
        / "2-14-cleanup-integrated-worktrees@e1-r1-standards.md": b"Standards report\n",
        reviews
        / "2-14-cleanup-integrated-worktrees@e1-r1-spec.md": b"Spec report\n",
    }
    for path, content in retained_files.items():
        path.write_bytes(content)

    hidden_state = launched.worktree / ".retained-state"
    exclude_file = Path(
        git_output(launched.worktree, "rev-parse", "--git-path", "info/exclude")
    )
    if not exclude_file.is_absolute():
        exclude_file = launched.worktree / exclude_file
    exclude_file.write_text(
        exclude_file.read_text(encoding="utf-8") + "\n/.retained-state/\n",
        encoding="utf-8",
    )
    state_root.rename(hidden_state)
    state_root.symlink_to(hidden_state, target_is_directory=True)
    hidden_evidence = (
        hidden_state
        / "task-delivery"
        / launched.run_id
        / "tickets"
        / "2-14-cleanup-integrated-worktrees"
    )
    mapping_file = launched.session_directory / "mapping.yml"
    mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
    mapping["evidence_path"] = str(hidden_evidence)
    mapping_file.write_text(
        yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8"
    )
    assert git_output(launched.worktree, "status", "--porcelain") == ""
    retained_before = {
        path.relative_to(state_root): path.read_bytes()
        for path in retained_files
    }

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 1
    document = yaml.safe_load(result.stdout)
    assert document["error"]["code"] == "invalid-config"
    assert launched.worktree.is_dir()
    assert {
        path: (state_root / path).read_bytes() for path in retained_before
    } == retained_before


def test_installed_cleanup_refuses_a_duplicate_ticket_branch_checkout(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    duplicate = launched.worktree.parent / "duplicate-checkout"
    duplicate_result = run_process(
        [
            "git",
            "worktree",
            "add",
            "--force",
            str(duplicate),
            launched.branch,
        ],
        cwd=launched.integration,
    )
    assert duplicate_result.returncode == 0, duplicate_result.stderr

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 1
    document = yaml.safe_load(result.stdout)
    assert document["error"]["code"] == "cleanup-ownership-mismatch"
    assert "ticket-branch-registered-at-noncanonical-path" in document["evidence"][
        "ownership_mismatches"
    ]
    assert launched.worktree.is_dir()
    assert duplicate.is_dir()


@pytest.mark.parametrize(
    "turn_document",
    (
        {"outcome": "completed", "runtime_exit_code": 1},
        {"outcome": "runtime-error", "runtime_exit_code": 0},
    ),
)
def test_installed_cleanup_refuses_inconsistent_terminal_outcome_evidence(
    turn_document: dict[str, object],
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    (launched.session_directory / "turn.yml").write_text(
        yaml.safe_dump(turn_document, sort_keys=False), encoding="utf-8"
    )

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 1
    assert yaml.safe_load(result.stdout)["evidence"] == {
        "ownership_mismatches": ["alias-terminal-outcome-missing"]
    }
    assert launched.worktree.is_dir()


def test_installed_cleanup_returns_structured_refusal_for_a_session_symlink_loop(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    session_root = launched.session_directory.parent
    retained = session_root.with_name("sessions-retained")
    session_root.rename(retained)
    session_root.symlink_to(session_root, target_is_directory=True)

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 1
    document = yaml.safe_load(result.stdout)
    assert document["cleanup_status"] == "refused"
    assert document["error"]["code"] == "cleanup-ownership-mismatch"
    assert document["evidence"] == {
        "ownership_mismatches": ["session-root-invalid"]
    }
    assert result.stderr.endswith("\n")
    assert launched.worktree.is_dir()


def test_installed_cleanup_returns_structured_refusal_for_a_worktree_symlink_loop(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    cyclic_worktree = tmp_path / "cyclic-ticket-worktree"
    cyclic_worktree.symlink_to(cyclic_worktree, target_is_directory=True)
    real_git = shutil.which("git")
    assert real_git is not None
    wrapper_directory = tmp_path / "cyclic-worktree-git"
    wrapper_directory.mkdir()
    wrapper = wrapper_directory / "git"
    wrapper.write_text(
        "#!{0}\n".format(sys.executable)
        + "import os\n"
        + "import subprocess\n"
        + "import sys\n"
        + "if sys.argv[1:] == ['worktree', 'list', '--porcelain']:\n"
        + "    result = subprocess.run([{0!r}, *sys.argv[1:]], check=False, "
        "capture_output=True, text=True)\n".format(real_git)
        + "    output = result.stdout.replace({0!r}, {1!r})\n".format(
            "worktree {0}\n".format(launched.worktree),
            "worktree {0}\n".format(cyclic_worktree),
        )
        + "    sys.stdout.write(output)\n"
        + "    raise SystemExit(result.returncode)\n"
        + "os.execv({0!r}, [{0!r}, *sys.argv[1:]])\n".format(real_git),
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    environment = dict(launched.environment)
    environment["PATH"] = "{0}{1}{2}".format(
        wrapper_directory, os.pathsep, environment["PATH"]
    )

    result = run_process(
        [
            str(installed_cleanup_commands.runner),
            "cleanup",
            "--run-id",
            launched.run_id,
            "--ticket-id",
            launched.ticket_id,
        ],
        cwd=launched.harness_root,
        env=environment,
    )

    assert result.returncode == 1
    message = "A required cleanup operation could not be verified."
    assert yaml.safe_load(result.stdout) == {
        "run_id": launched.run_id,
        "ticket_id": launched.ticket_id,
        "cleanup_status": "refused",
        "worktree_path": str(launched.worktree),
        "branch": launched.branch,
        "error": {"code": "cleanup-failed", "message": message},
        "evidence": {"cause": "operation-failed"},
    }
    assert result.stderr == message + "\n"
    assert launched.worktree.is_dir()
    assert cyclic_worktree.is_symlink()
    assert launched.session_directory.is_dir()


def test_installed_cleanup_refuses_if_dev_moves_before_branch_deletion(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    old_dev = git_output(launched.integration, "rev-parse", "HEAD")
    run_process(
        ["git", "commit", "--allow-empty", "-m", "Validated integration"],
        cwd=launched.integration,
    ).check_returncode()
    new_dev = git_output(launched.integration, "rev-parse", "HEAD")
    assert new_dev != old_dev
    ticket_commit = git_output(launched.worktree, "rev-parse", "HEAD")
    hook_started = tmp_path / "cleanup-transaction-started"
    hook_release = tmp_path / "cleanup-transaction-release"
    real_git = shutil.which("git")
    assert real_git is not None
    wrapper_directory = tmp_path / "transaction-git"
    wrapper_directory.mkdir()
    wrapper = wrapper_directory / "git"
    wrapper.write_text(
        "#!{0}\n".format(sys.executable)
        + "import os\n"
        + "import sys\n"
        + "import time\n"
        + "from pathlib import Path\n"
        + "if sys.argv[1:] == ['update-ref', '--stdin']:\n"
        + "    Path(os.environ['CLEANUP_TEST_HOOK_STARTED']).touch()\n"
        + "    release = Path(os.environ['CLEANUP_TEST_HOOK_RELEASE'])\n"
        + "    while not release.exists():\n"
        + "        time.sleep(0.01)\n"
        + "os.execv({0!r}, [{0!r}, *sys.argv[1:]])\n".format(real_git),
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    environment = dict(launched.environment)
    environment.update(
        {
            "CLEANUP_TEST_HOOK_STARTED": str(hook_started),
            "CLEANUP_TEST_HOOK_RELEASE": str(hook_release),
            "PATH": "{0}{1}{2}".format(
                wrapper_directory, os.pathsep, environment["PATH"]
            ),
        }
    )
    cleanup_process = subprocess.Popen(
        [
            str(installed_cleanup_commands.runner),
            "cleanup",
            "--run-id",
            launched.run_id,
            "--ticket-id",
            launched.ticket_id,
        ],
        cwd=launched.harness_root,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        wait_for_file(hook_started)
        run_process(
            ["git", "update-ref", "refs/heads/dev", old_dev, new_dev],
            cwd=launched.primary,
        ).check_returncode()
    finally:
        hook_release.touch()

    cleanup_stdout, cleanup_stderr = cleanup_process.communicate(timeout=10)
    assert cleanup_process.returncode == 1
    document = yaml.safe_load(cleanup_stdout)
    assert document["error"]["code"] == "cleanup-failed"
    assert cleanup_stderr.endswith("\n")
    assert git_output(launched.primary, "rev-parse", launched.branch) == ticket_commit


def test_installed_cleanup_refuses_a_nonterminal_alias_without_a_reservation(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    (launched.session_directory / "turn.yml").unlink()

    result = cleanup_ticket(installed_cleanup_commands, launched)

    message = (
        "The registered Ticket Worktree does not belong to the supplied "
        "run and ticket identities."
    )
    assert result.returncode == 1
    assert yaml.safe_load(result.stdout)["error"] == {
        "code": "cleanup-ownership-mismatch",
        "message": message,
    }
    assert yaml.safe_load(result.stdout)["evidence"] == {
        "ownership_mismatches": ["alias-terminal-outcome-missing"]
    }
    assert launched.worktree.is_dir()
    assert launched.session_directory.is_dir()


def test_installed_cleanup_accepts_bound_aliases_with_distinct_safe_ticket_snapshots(
    installed_cleanup_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    launched = launch_ticket(
        installed_cleanup_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    first_ticket = launched.harness_root / "tickets" / "14-original.md"
    second_ticket = launched.harness_root / "tickets" / "14-refreshed.md"
    first_ticket.write_text("# Original tracker snapshot\n", encoding="utf-8")
    second_ticket.write_text("# Refreshed tracker snapshot\n", encoding="utf-8")
    first_mapping_file = launched.session_directory / "mapping.yml"
    first_mapping = yaml.safe_load(first_mapping_file.read_text(encoding="utf-8"))
    first_mapping["ticket_file"] = str(first_ticket)
    first_mapping_file.write_text(
        yaml.safe_dump(first_mapping, sort_keys=False), encoding="utf-8"
    )

    second_launch = run_process(
        [
            str(installed_cleanup_commands.runner),
            "--batch-input",
            str(launched.batch_file),
        ],
        cwd=launched.harness_root,
        env=launched.environment,
    )
    assert second_launch.returncode == 0, second_launch.stderr
    second_alias = yaml.safe_load(second_launch.stdout)["tasks"][0]["alias"]
    second_session = launched.session_directory.parent / second_alias
    wait_for_file(second_session / "turn.yml")
    second_mapping_file = second_session / "mapping.yml"
    second_mapping = yaml.safe_load(second_mapping_file.read_text(encoding="utf-8"))
    second_mapping["ticket_file"] = str(second_ticket)
    second_mapping_file.write_text(
        yaml.safe_dump(second_mapping, sort_keys=False), encoding="utf-8"
    )
    evidence = (
        launched.harness_root
        / "state"
        / "task-delivery"
        / launched.run_id
        / "tickets"
        / "2-14-cleanup-integrated-worktrees"
    )
    metadata_file = evidence / "metadata.yml"
    metadata = yaml.safe_load(metadata_file.read_text(encoding="utf-8"))
    metadata["ticket_file"] = str(second_ticket)
    metadata_file.write_text(
        yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8"
    )

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(result.stdout)["aliases_removed"] == [
        launched.alias,
        second_alias,
    ]
    assert first_ticket.read_text(encoding="utf-8") == (
        "# Original tracker snapshot\n"
    )
    assert second_ticket.read_text(encoding="utf-8") == (
        "# Refreshed tracker snapshot\n"
    )
