from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, run_process, wait_for_file
from test_project_setup import install_user_skills, run_ready_setup as run_setup


def configure_harness(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> tuple[Path, Path, Path, dict[str, str]]:
    harness_root = temporary_git_repository.parent
    worktree_root = harness_root / ".graphtraj" / ".agent-worktrees"
    integration = worktree_root / "dev"
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
    return harness_root, worktree_root, integration, environment


def test_installed_runner_launches_four_exact_main_selected_tasks_in_order(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root, worktree_root, integration, environment = configure_harness(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    run_id = "20260813-four-engineers"
    requested = (
        ("11", "first-ticket", "engineer-junior", "Keep the first note exact."),
        ("12", "second-ticket", "engineer-senior", None),
        ("13", "third-ticket", "engineer-expert", "Preserve Issue."),
        ("14", "fourth-ticket", "engineer-expert", None),
    )
    task_documents = []
    ticket_files = []
    for ticket_id, ticket_name, role, instruction in requested:
        ticket_file = harness_root / "tickets" / "{0}.md".format(ticket_id)
        ticket_file.parent.mkdir(exist_ok=True)
        ticket_file.write_text(
            "# Ticket {0}\n\nImplement only this ticket.\n".format(ticket_id),
            encoding="utf-8",
        )
        ticket_files.append(ticket_file.resolve())
        task = {
            "ticket_id": ticket_id,
            "ticket_name": ticket_name,
            "role": role,
            "ticket_file": str(ticket_file),
        }
        if instruction is not None:
            task["instruction"] = instruction
        task_documents.append(task)

    batch_file = harness_root / "four-task-batch.yml"
    batch_bytes = yaml.safe_dump(
        {"run_id": run_id, "runtime": "codex", "tasks": task_documents},
        sort_keys=False,
    ).encode("utf-8")
    batch_file.write_bytes(batch_bytes)

    result = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch_file)],
        cwd=harness_root,
        env=environment,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    documents = list(yaml.safe_load_all(result.stdout))
    assert len(documents) == 1
    document = documents[0]
    retained = (
        harness_root / ".graphtraj" / "state" / run_id / "batch.yml"
    ).resolve()
    assert document["run_id"] == run_id
    assert document["runtime"] == "codex"
    assert document["retained_batch_file"] == str(retained)
    assert retained.read_bytes() == batch_bytes
    assert [task["ticket_id"] for task in document["tasks"]] == [
        item[0] for item in requested
    ]
    assert [task["role"] for task in document["tasks"]] == [
        item[2] for item in requested
    ]

    aliases = []
    for task, requested_task, ticket_file in zip(
        document["tasks"], requested, ticket_files, strict=True
    ):
        ticket_id, ticket_name, role, _ = requested_task
        tier = {
            "engineer-junior": "j",
            "engineer-senior": "s",
            "engineer-expert": "e",
        }[role]
        stem = "{0}-{1}-{2}".format(len(ticket_id), ticket_id, ticket_name)
        worktree = (worktree_root / "runs" / run_id / stem).resolve()
        alias = "{0}@{1}1".format(stem, tier)
        aliases.append(alias)
        assert task == {
            "ticket_id": ticket_id,
            "ticket_name": ticket_name,
            "role": role,
            "launch_status": "launched",
            "worktree_path": str(worktree),
            "ticket_file": str(ticket_file),
            "alias": alias,
            "session": "fake-thread",
        }

    for alias in aliases:
        wait_for_file(
            harness_root
            / ".codex"
            / "agent-runner"
            / "sessions"
            / alias
            / "turn.yml"
        )


def test_installed_runner_rejects_duplicate_ticket_ids_before_any_start(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root, _, _, environment = configure_harness(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    ticket_file = harness_root / "ticket.md"
    ticket_file.write_text("# Canonical ticket\n", encoding="utf-8")
    run_id = "20260813-duplicate-identity"
    batch_file = harness_root / "duplicate-batch.yml"
    batch_file.write_text(
        yaml.safe_dump(
            {
                "run_id": run_id,
                "runtime": "codex",
                "tasks": [
                    {
                        "ticket_id": "11",
                        "ticket_name": "first-name",
                        "role": "engineer-junior",
                        "ticket_file": str(ticket_file),
                    },
                    {
                        "ticket_id": "11",
                        "ticket_name": "second-name",
                        "role": "engineer-expert",
                        "ticket_file": str(ticket_file),
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch_file)],
        cwd=harness_root,
        env=environment,
    )

    assert result.returncode == 1
    assert yaml.safe_load(result.stdout)["error"]["code"] == "invalid-input"
    assert not fake_codex.log_file.exists()


def test_installed_runner_rejects_intra_batch_worktree_collision_before_any_start(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root, worktree_root, integration, environment = configure_harness(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    alternate_root = worktree_root.with_name(worktree_root.name.swapcase())
    try:
        case_insensitive = alternate_root.samefile(worktree_root)
    except FileNotFoundError:
        case_insensitive = False
    if not case_insensitive:
        pytest.skip("requires a case-insensitive Worktree filesystem")

    ticket_file = harness_root / "ticket.md"
    ticket_file.write_text("# Canonical ticket\n", encoding="utf-8")
    run_id = "20260813-colliding-coordinates"
    batch_file = harness_root / "colliding-batch.yml"
    batch_file.write_text(
        yaml.safe_dump(
            {
                "run_id": run_id,
                "runtime": "codex",
                "tasks": [
                    {
                        "ticket_id": "A",
                        "ticket_name": "same-name",
                        "role": "engineer-junior",
                        "ticket_file": str(ticket_file),
                    },
                    {
                        "ticket_id": "a",
                        "ticket_name": "same-name",
                        "role": "engineer-expert",
                        "ticket_file": str(ticket_file),
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch_file)],
        cwd=harness_root,
        env=environment,
    )

    message = "Two tasks derive the same Ticket Worktree path."
    assert result.returncode == 1
    assert yaml.safe_load(result.stdout) == {
        "error": {"code": "worktree-conflict", "message": message}
    }
    assert result.stderr == message + "\n"
    assert not fake_codex.log_file.exists()
    assert not (worktree_root / "runs" / run_id).exists()
    assert not (
        harness_root / ".graphtraj" / "state" / run_id
    ).exists()


def test_installed_runner_preflights_later_worktree_conflict_before_any_start(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root, _, _, environment = configure_harness(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    run_id = "20260813-global-conflict"
    first_ticket = harness_root / "first.md"
    second_ticket = harness_root / "second.md"
    first_ticket.write_text("# First ticket\n", encoding="utf-8")
    second_ticket.write_text("# Second ticket\n", encoding="utf-8")
    conflicting_branch = "agent/{0}/2-12-second-ticket".format(run_id)
    run_process(
        ["git", "commit", "--allow-empty", "-m", "Advance primary"],
        cwd=temporary_git_repository,
    ).check_returncode()
    main_commit = run_process(
        ["git", "rev-parse", "main"], cwd=temporary_git_repository
    ).stdout.strip()
    run_process(
        ["git", "branch", conflicting_branch, main_commit],
        cwd=temporary_git_repository,
    ).check_returncode()
    batch_file = harness_root / "conflicting-batch.yml"
    batch_file.write_text(
        yaml.safe_dump(
            {
                "run_id": run_id,
                "runtime": "codex",
                "tasks": [
                    {
                        "ticket_id": "11",
                        "ticket_name": "first-ticket",
                        "role": "engineer-junior",
                        "ticket_file": str(first_ticket),
                    },
                    {
                        "ticket_id": "12",
                        "ticket_name": "second-ticket",
                        "role": "engineer-senior",
                        "ticket_file": str(second_ticket),
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch_file)],
        cwd=harness_root,
        env=environment,
    )

    assert result.returncode == 1
    assert yaml.safe_load(result.stdout)["error"]["code"] == "worktree-conflict"
    assert not fake_codex.log_file.exists()


@pytest.mark.parametrize("live_worktree_state", ["detached", "rebranched"])
def test_installed_runner_rejects_later_live_ticket_without_expected_branch(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    live_worktree_state: str,
) -> None:
    harness_root, worktree_root, integration, environment = configure_harness(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    ticket_file = harness_root / "live.md"
    ticket_file.write_text("# Live ticket\n", encoding="utf-8")
    live_run = "20260813-existing-{0}".format(live_worktree_state)
    live_stem = "2-11-live-ticket"
    live_branch = "agent/{0}/{1}".format(live_run, live_stem)
    live_worktree = worktree_root / "runs" / live_run / live_stem
    run_process(
        [
            "git",
            "worktree",
            "add",
            "-b",
            live_branch,
            str(live_worktree),
            "dev",
        ],
        cwd=temporary_git_repository,
    ).check_returncode()
    if live_worktree_state == "detached":
        state_result = run_process(
            ["git", "switch", "--detach"], cwd=live_worktree
        )
    else:
        state_result = run_process(
            ["git", "switch", "-c", "unexpected-live-branch"],
            cwd=live_worktree,
        )
    state_result.check_returncode()

    first_ticket = harness_root / "first.md"
    first_ticket.write_text("# Must not start\n", encoding="utf-8")
    run_id = "20260813-reject-{0}".format(live_worktree_state)
    batch_file = harness_root / "reject-{0}.yml".format(live_worktree_state)
    batch_file.write_text(
        yaml.safe_dump(
            {
                "run_id": run_id,
                "runtime": "codex",
                "tasks": [
                    {
                        "ticket_id": "20",
                        "ticket_name": "must-not-start",
                        "role": "engineer-junior",
                        "ticket_file": str(first_ticket),
                    },
                    {
                        "ticket_id": "11",
                        "ticket_name": "live-ticket",
                        "role": "engineer-expert",
                        "ticket_file": str(ticket_file),
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch_file)],
        cwd=harness_root,
        env=environment,
    )

    message = "This ticket already has a live Ticket Worktree in another Run."
    assert result.returncode == 1
    assert yaml.safe_load(result.stdout) == {
        "error": {"code": "ticket-already-live", "message": message}
    }
    assert result.stderr == message + "\n"
    assert not fake_codex.log_file.exists()
    assert not (
        worktree_root / "runs" / run_id / "2-20-must-not-start"
    ).exists()
    assert not (
        harness_root / ".graphtraj" / "state" / run_id
    ).exists()


def test_installed_runner_reports_mixed_post_preflight_launch_outcomes(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root, worktree_root, integration, environment = configure_harness(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    run_id = "20260813-mixed-launch"
    task_documents = []
    for ticket_id, ticket_name, role in (
        ("11", "first-ticket", "engineer-junior"),
        ("12", "broken-ticket", "engineer-senior"),
        ("13", "last-ticket", "engineer-expert"),
    ):
        ticket_file = harness_root / "{0}.md".format(ticket_id)
        ticket_file.write_text(
            "# Ticket {0}\n".format(ticket_id), encoding="utf-8"
        )
        task_documents.append(
            {
                "ticket_id": ticket_id,
                "ticket_name": ticket_name,
                "role": role,
                "ticket_file": str(ticket_file),
            }
        )
    broken_evidence = (
        harness_root
        / ".graphtraj"
        / "state"
        / run_id
        / "tickets"
        / "2-12-broken-ticket"
    )
    (broken_evidence / "metadata.yml").mkdir(parents=True)
    batch_file = harness_root / "mixed-batch.yml"
    batch_bytes = yaml.safe_dump(
        {"run_id": run_id, "runtime": "codex", "tasks": task_documents},
        sort_keys=False,
    ).encode("utf-8")
    batch_file.write_bytes(batch_bytes)

    result = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch_file)],
        cwd=harness_root,
        env=environment,
        timeout=10,
    )

    failure_message = "The Runner could not persist mechanical ticket metadata."
    assert result.returncode == 1
    assert result.stderr == failure_message + "\n"
    documents = list(yaml.safe_load_all(result.stdout))
    assert len(documents) == 1
    document = documents[0]
    retained = (
        harness_root / ".graphtraj" / "state" / run_id / "batch.yml"
    ).resolve()
    assert document["run_id"] == run_id
    assert document["runtime"] == "codex"
    assert document["retained_batch_file"] == str(retained)
    assert retained.read_bytes() == batch_bytes
    assert [task["ticket_id"] for task in document["tasks"]] == [
        "11",
        "12",
        "13",
    ]
    assert [task["launch_status"] for task in document["tasks"]] == [
        "launched",
        "failed",
        "launched",
    ]
    assert document["tasks"][1] == {
        "ticket_id": "12",
        "ticket_name": "broken-ticket",
        "role": "engineer-senior",
        "launch_status": "failed",
        "worktree_path": str(
            (worktree_root / "runs" / run_id / "2-12-broken-ticket").resolve()
        ),
        "ticket_file": str((harness_root / "12.md").resolve()),
        "error": {"code": "launch-failed", "message": failure_message},
    }
    assert document["tasks"][0]["alias"] == "2-11-first-ticket@j1"
    assert document["tasks"][2]["alias"] == "2-13-last-ticket@e1"
    assert Path(document["tasks"][0]["worktree_path"]).is_dir()
    assert Path(document["tasks"][2]["worktree_path"]).is_dir()


def test_installed_runner_rejects_later_busy_or_already_live_ticket_globally(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root, _, _, environment = configure_harness(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    live_ticket = harness_root / "live.md"
    live_ticket.write_text("# Live ticket\n", encoding="utf-8")
    release_file = tmp_path / "release-live-runtime"
    live_environment = dict(environment)
    live_environment.update(
        {
            "FAKE_CODEX_CAPTURE_STDIN": "1",
            "FAKE_CODEX_RELEASE_FILE": str(release_file),
        }
    )
    live_batch = harness_root / "live-batch.yml"
    live_batch.write_text(
        yaml.safe_dump(
            {
                "run_id": "20260813-live-ticket",
                "runtime": "codex",
                "tasks": [
                    {
                        "ticket_id": "11",
                        "ticket_name": "live-ticket",
                        "role": "engineer-expert",
                        "ticket_file": str(live_ticket),
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    live_result = run_process(
        [str(installed_commands.runner), "--batch-input", str(live_batch)],
        cwd=harness_root,
        env=live_environment,
        timeout=5,
    )
    assert live_result.returncode == 0, live_result.stderr
    runtime_log_before = fake_codex.log_file.read_bytes()

    new_ticket = harness_root / "new.md"
    new_ticket.write_text("# Must not start\n", encoding="utf-8")
    same_run_batch = harness_root / "same-run-busy-batch.yml"
    same_run_batch.write_text(
        yaml.safe_dump(
            {
                "run_id": "20260813-live-ticket",
                "runtime": "codex",
                "tasks": [
                    {
                        "ticket_id": "20",
                        "ticket_name": "must-not-start",
                        "role": "engineer-junior",
                        "ticket_file": str(new_ticket),
                    },
                    {
                        "ticket_id": "11",
                        "ticket_name": "live-ticket",
                        "role": "engineer-expert",
                        "ticket_file": str(live_ticket),
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    try:
        busy_result = run_process(
            [str(installed_commands.runner), "--batch-input", str(same_run_batch)],
            cwd=harness_root,
            env=live_environment,
            timeout=5,
        )
        assert busy_result.returncode == 1
        assert yaml.safe_load(busy_result.stdout)["error"]["code"] == "worktree-busy"
        assert fake_codex.log_file.read_bytes() == runtime_log_before
    finally:
        release_file.touch()
        wait_for_file(
            harness_root
            / ".codex"
            / "agent-runner"
            / "sessions"
            / "2-11-live-ticket@e1"
            / "turn.yml"
        )


def test_installed_runner_rejects_global_file_runtime_and_integration_failures(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root, _, integration, environment = configure_harness(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    valid_ticket = harness_root / "valid.md"
    valid_ticket.write_text("# Valid ticket\n", encoding="utf-8")
    base_task = {
        "ticket_id": "11",
        "ticket_name": "valid-ticket",
        "role": "engineer-expert",
        "ticket_file": str(valid_ticket),
    }
    runtime_run = "20260813-unknown-runtime"
    runtime_batch = harness_root / "unknown-runtime-batch.yml"
    runtime_batch.write_text(
        yaml.safe_dump(
            {
                "run_id": runtime_run,
                "runtime": "unknown-runtime",
                "tasks": [base_task],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    runtime_result = run_process(
        [str(installed_commands.runner), "--batch-input", str(runtime_batch)],
        cwd=harness_root,
        env=environment,
    )
    assert runtime_result.returncode == 1
    assert yaml.safe_load(runtime_result.stdout)["error"]["code"] == "unsupported-runtime"

    dirty_run = "20260813-dirty-integration"
    dirty_batch = harness_root / "dirty-integration-batch.yml"
    dirty_batch.write_text(
        yaml.safe_dump(
            {"run_id": dirty_run, "runtime": "codex", "tasks": [base_task]},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    dirty_file = integration / "uncommitted.txt"
    dirty_file.write_text("not validated\n", encoding="utf-8")
    try:
        dirty_result = run_process(
            [str(installed_commands.runner), "--batch-input", str(dirty_batch)],
            cwd=harness_root,
            env=environment,
        )
    finally:
        dirty_file.unlink()
    assert dirty_result.returncode == 1
    assert yaml.safe_load(dirty_result.stdout)["error"]["code"] == "integration-not-ready"

    assert not fake_codex.log_file.exists()


def test_installed_runner_uses_only_allowlisted_built_in_runtime_adapters(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root, worktree_root, integration, environment = configure_harness(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    ticket_file = harness_root / "ticket.md"
    ticket_file.write_text("# Canonical ticket\n", encoding="utf-8")
    unapproved_run = "20260813-unapproved-runtime"
    unapproved_batch = harness_root / "unapproved-runtime-batch.yml"
    unapproved_batch.write_text(
        yaml.safe_dump(
            {
                "run_id": unapproved_run,
                "runtime": "unapproved",
                "tasks": [
                    {
                        "ticket_id": "11",
                        "ticket_name": "unapproved-runtime",
                        "role": "engineer-expert",
                        "ticket_file": str(ticket_file),
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    unapproved = run_process(
        [str(installed_commands.runner), "--batch-input", str(unapproved_batch)],
        cwd=harness_root,
        env=environment,
    )
    assert unapproved.returncode == 1
    assert yaml.safe_load(unapproved.stdout) == {
        "error": {
            "code": "unsupported-runtime",
            "message": "The selected Agent Runtime is not supported by this Runner.",
        }
    }
    assert not (harness_root / ".codex" / "agent-runner" / "config.yml").exists()
    assert not fake_codex.log_file.exists()
    for run_id in (unapproved_run,):
        assert not (worktree_root / "runs" / run_id).exists()
        assert not (harness_root / ".graphtraj" / "state" / run_id).exists()
