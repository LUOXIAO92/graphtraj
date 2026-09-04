from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from conftest import (
    FakeCodex,
    InstalledCommands,
    run_process,
)
from test_agent_runner_launch import wait_for_file
from test_project_setup import (
    git_output,
    install_user_skills,
    run_ready_setup as run_setup,
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

    @property
    def state_root(self) -> Path:
        return self.harness_root / ".graphtraj" / "state"


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
    integration = harness_root / ".graphtraj" / ".agent-worktrees" / "dev"
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    setup_result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="y\n",
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
            "PATH": os.pathsep.join(
                (str(fake_codex.executable.parent), os.environ.get("PATH", ""))
            ),
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
        launched.state_root
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
        launched.state_root
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
    other_ticket = launched.ticket_file.with_name("99-other-ticket.md")
    other_ticket.write_text("# Other ticket\n", encoding="utf-8")
    other_batch = yaml.safe_load(launched.batch_file.read_text(encoding="utf-8"))
    other_batch["tasks"][0].update(
        {
            "ticket_id": "99",
            "ticket_name": "other-ticket",
            "ticket_file": str(other_ticket),
        }
    )
    other_batch_file = launched.harness_root / "other-launch-batch.yml"
    other_batch_file.write_text(
        yaml.safe_dump(other_batch, sort_keys=False), encoding="utf-8"
    )
    release_file = tmp_path / "allow-other-ticket-to-finish"
    environment = dict(launched.environment)
    environment["FAKE_CODEX_RELEASE_FILE"] = str(release_file)
    other_launch = run_process(
        [str(installed_cleanup_commands.runner), "--batch-input", str(other_batch_file)],
        cwd=launched.harness_root,
        env=environment,
    )
    assert other_launch.returncode == 0, other_launch.stderr
    other_task = yaml.safe_load(other_launch.stdout)["tasks"][0]
    other_session = launched.session_directory.parent / other_task["alias"]

    try:
        result = cleanup_ticket(installed_cleanup_commands, launched)

        assert result.returncode == 0, result.stderr
        assert yaml.safe_load(result.stdout)["cleanup_status"] == "cleaned"
        assert Path(other_task["worktree_path"]).is_dir()
        assert other_session.is_dir()
        assert not launched.worktree.exists()
        assert not launched.session_directory.exists()
    finally:
        release_file.touch()
        wait_for_file(other_session / "turn.yml")


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


@pytest.mark.parametrize(
    ("entry", "unsafe_entry"),
    (
        ("unexpected-directory/operator-data.txt", "unexpected-directory"),
        ("operator-note.txt", "operator-note.txt"),
    ),
)
def test_installed_cleanup_refuses_unknown_alias_entries(
    entry: str,
    unsafe_entry: str,
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
    marker = launched.session_directory / entry
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("do not remove\n", encoding="utf-8")

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 1
    document = yaml.safe_load(result.stdout)
    assert document["error"]["code"] == "cleanup-failed"
    assert document["evidence"] == {
        "unsafe_alias_entries": [
            "{0}/{1}".format(launched.alias, unsafe_entry)
        ]
    }
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

    run_state = launched.state_root / launched.run_id
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
    assert not launched.worktree.parent.exists()
    assert not launched.worktree.parent.parent.exists()
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
        launched.state_root
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


def test_installed_cleanup_retries_ancestor_pruning_after_a_failure(
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
    runs_root = launched.worktree.parent.parent
    original_mode = runs_root.stat().st_mode & 0o777
    runs_root.chmod(0o500)
    try:
        first = cleanup_ticket(installed_cleanup_commands, launched)
    finally:
        runs_root.chmod(original_mode)

    assert first.returncode == 1
    assert yaml.safe_load(first.stdout)["evidence"]["completed_actions"] == [
        "worktree-removed",
        "aliases-removed",
        "branch-removed",
    ]
    assert launched.worktree.parent.is_dir()

    repeated = cleanup_ticket(installed_cleanup_commands, launched)

    assert repeated.returncode == 0, repeated.stderr
    assert yaml.safe_load(repeated.stdout)["cleanup_status"] == "already-cleaned"
    assert not launched.worktree.parent.exists()
    assert not runs_root.exists()


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
        launched.state_root
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
            launched.state_root
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
    common_git = Path(
        git_output(launched.primary, "rev-parse", "--git-common-dir")
    )
    if not common_git.is_absolute():
        common_git = launched.primary / common_git
    hook = common_git / "hooks" / "reference-transaction"
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


def test_installed_cleanup_removes_aliases_across_engineer_tiers(
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
    senior_document = yaml.safe_load(
        launched.batch_file.read_text(encoding="utf-8")
    )
    senior_document["tasks"][0]["role"] = "engineer-senior"
    senior_batch.write_text(
        yaml.safe_dump(senior_document, sort_keys=False),
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
    senior_session = launched.session_directory.parent / senior_alias
    wait_for_file(senior_session / "turn.yml")

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 0, result.stderr
    assert set(yaml.safe_load(result.stdout)["aliases_removed"]) == {
        launched.alias,
        senior_alias,
    }
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
    failed_environment["FAKE_CODEX_EVENTS"] = "[]"
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
    failed_trace = (
        launched.state_root
        / launched.run_id
        / "tickets"
        / launched.worktree.name
        / "traces"
        / failed_alias
        / "turn-1"
        / "events.jsonl"
    )
    assert failed_trace.is_file() and failed_trace.stat().st_size == 0

    result = cleanup_ticket(installed_cleanup_commands, launched)

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(result.stdout)["aliases_removed"] == [
        launched.alias,
        failed_alias,
    ]
    assert not launched.session_directory.exists()
    assert not failed_session.exists()


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
        launched.state_root
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
    state_root = launched.state_root
    run_root = state_root / launched.run_id
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
