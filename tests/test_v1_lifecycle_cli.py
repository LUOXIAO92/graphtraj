from __future__ import annotations

import json
import time
from pathlib import Path

import yaml

from conftest import FakeCodex, InstalledCommands, run_process
from test_project_setup import (
    git_output,
    install_user_skills,
    run_ready_setup as run_setup,
    setup_environment,
)


def wait_for_idle_outcome(
    installed_commands: InstalledCommands,
    *,
    harness_root: Path,
    environment: dict[str, str],
    alias: str,
    outcome: str,
) -> None:
    expected = {
        "aliases": [
            {
                "alias": alias,
                "activity": "idle",
                "last_outcome": outcome,
            }
        ]
    }
    deadline = time.monotonic() + 5.0
    last_document: object = None
    while time.monotonic() < deadline:
        result = run_process(
            [str(installed_commands.runner), "status", alias],
            cwd=harness_root,
            env=environment,
        )
        assert result.returncode == 0, result.stderr
        last_document = yaml.safe_load(result.stdout)
        if last_document == expected:
            return
        time.sleep(0.01)
    raise AssertionError(
        "Timed out waiting for {0} to become idle with {1}: {2}".format(
            alias,
            outcome,
            last_document,
        )
    )


def test_pinned_install_exercises_the_complete_v1_delivery_lifecycle(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    integration = harness_root / ".graphtraj" / ".agent-worktrees" / "dev"
    state = harness_root / ".graphtraj" / "state"
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    environment = setup_environment(user_home, fake_codex)

    setup = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="y\n",
    )

    assert setup.returncode == 0, setup.stderr
    assert integration.is_dir()

    ticket_file = harness_root / "v1-lifecycle.md"
    ticket_file.write_text("# Representative V1 ticket\n", encoding="utf-8")
    run_id = "20260814-v1-lifecycle"
    batch_file = harness_root / "batch.yml"
    batch_file.write_text(
        yaml.safe_dump(
            {
                "run_id": run_id,
                "tasks": [
                    {
                        "ticket_id": "15",
                        "ticket_name": "v1-lifecycle",
                        "role": "engineer-expert",
                        "ticket_file": str(ticket_file),
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    release_file = tmp_path / "allow-initial-turn-to-finish"
    session = "fake-v1-lifecycle-session"
    initial_events = [{"type": "thread.started", "thread_id": session}]

    launch = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch_file)],
        cwd=harness_root,
        env={
            **environment,
            "FAKE_CODEX_EVENTS": json.dumps(initial_events),
            "FAKE_CODEX_RELEASE_FILE": str(release_file),
        },
        timeout=10,
    )

    assert launch.returncode == 0, launch.stderr
    task = yaml.safe_load(launch.stdout)["tasks"][0]
    assert task["launch_status"] == "launched"
    ticket_worktree = Path(task["worktree_path"])
    alias = task["alias"]
    assert ticket_worktree.is_dir()

    running = run_process(
        [str(installed_commands.runner), "status", alias],
        cwd=harness_root,
        env=environment,
    )
    assert running.returncode == 0, running.stderr
    assert yaml.safe_load(running.stdout)["aliases"][0]["activity"] == "running"

    interrupted = run_process(
        [str(installed_commands.runner), "interrupt", alias],
        cwd=harness_root,
        env=environment,
        timeout=10,
    )
    assert interrupted.returncode == 0, interrupted.stderr
    assert yaml.safe_load(interrupted.stdout)["interrupt_status"] == "interrupted"
    wait_for_idle_outcome(
        installed_commands,
        harness_root=harness_root,
        environment=environment,
        alias=alias,
        outcome="interrupted",
    )

    resumed = run_process(
        [
            str(installed_commands.runner),
            "send",
            alias,
            "--instruction",
            "Resume and finish the ticket.",
            "--caused-by-worldline-seq",
            "1",
        ],
        cwd=harness_root,
        env={
            **environment,
            "FAKE_CODEX_LIFECYCLE_ACTION": "deliver-representative-ticket",
            "FAKE_CODEX_EVENTS": json.dumps(
                [
                    {"type": "thread.started", "thread_id": session},
                    {"type": "turn.started"},
                    {
                        "type": "turn.completed",
                        "usage": {
                            "cached_input_tokens": 0,
                            "input_tokens": 1,
                            "output_tokens": 1,
                        },
                    },
                ]
            ),
        },
        timeout=10,
    )
    assert resumed.returncode == 0, resumed.stderr
    assert yaml.safe_load(resumed.stdout)["send_status"] == "sent"
    wait_for_idle_outcome(
        installed_commands,
        harness_root=harness_root,
        environment=environment,
        alias=alias,
        outcome="completed",
    )

    delivered = ticket_worktree / "V1_DELIVERED.txt"
    candidate = git_output(ticket_worktree, "rev-parse", "HEAD")
    evidence = state / run_id / "tickets" / ticket_worktree.name
    assert delivered.is_file()
    assert (evidence / "result.md").is_file()
    assert (evidence / "validation.md").is_file()

    reviews = evidence / "reviews"
    reviewer_launches = []
    for ordinal, (axis, role) in enumerate(
        (
            ("standards", "standards-reviewer"),
            ("spec", "spec-reviewer"),
        ),
        start=1,
    ):
        reviewer_alias = "{0}@r{1}".format(ticket_worktree.name, ordinal)
        report = reviews / "{0}-r1-{1}.md".format(reviewer_alias, axis)
        review_batch = harness_root / "{0}-review.yml".format(axis)
        report_file = str(Path(".state/reviews") / report.name)
        review_batch.write_text(
            yaml.safe_dump(
                {
                    "run_id": run_id,
                    "tasks": [
                        {
                            "ticket_id": "15",
                            "ticket_name": "v1-lifecycle",
                            "role": role,
                            "review_round": 1,
                            "ticket_file": str(ticket_file),
                            "instruction": "Review the candidate.",
                            "report_file": report_file,
                        }
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        review = run_process(
            [str(installed_commands.runner), "--batch-input", str(review_batch)],
            cwd=harness_root,
            env={
                **environment,
                "FAKE_CODEX_EVENTS": json.dumps(
                    [
                        {
                            "type": "thread.started",
                            "thread_id": "fake-v1-{0}-review".format(axis),
                        },
                        {"type": "turn.started"},
                        {
                            "type": "turn.completed",
                            "usage": {
                                "cached_input_tokens": 0,
                                "input_tokens": 1,
                                "output_tokens": 1,
                            },
                        },
                    ]
                ),
                "FAKE_CODEX_LIFECYCLE_ACTION": "review-representative-candidate",
                "FAKE_CODEX_REVIEW_AXIS": axis,
                "FAKE_CODEX_REVIEW_CANDIDATE": candidate,
                "FAKE_CODEX_REVIEW_REPORT": str(report),
            },
            timeout=10,
        )
        assert review.returncode == 0, review.stderr
        review_task = yaml.safe_load(review.stdout)["tasks"][0]
        assert review_task["alias"] == reviewer_alias
        assert Path(review_task["worktree_path"]) == ticket_worktree
        wait_for_idle_outcome(
            installed_commands,
            harness_root=harness_root,
            environment=environment,
            alias=review_task["alias"],
            outcome="completed",
        )
        assert report.is_file()
        reviewer_launches.append((role, reviewer_alias, report))

    assert git_output(ticket_worktree, "rev-parse", "HEAD") == candidate
    assert git_output(ticket_worktree, "status", "--porcelain") == ""

    merged = run_process(
        ["git", "merge", "--no-ff", candidate, "-m", "Integrate candidate"],
        cwd=integration,
    )
    assert merged.returncode == 0, merged.stderr
    validation = run_process(
        ["git", "diff", "--check", "HEAD^", "HEAD"],
        cwd=integration,
    )
    assert validation.returncode == 0, validation.stderr
    assert (integration / delivered.name).is_file()

    cleanup = run_process(
        [
            str(installed_commands.runner),
            "cleanup",
            "--run-id",
            run_id,
            "--ticket-id",
            "15",
        ],
        cwd=harness_root,
        env=environment,
        timeout=10,
    )
    assert cleanup.returncode == 0, cleanup.stderr
    assert yaml.safe_load(cleanup.stdout)["cleanup_status"] == "cleaned"
    assert not ticket_worktree.exists()
    assert (evidence / "result.md").is_file()
    assert (evidence / "validation.md").is_file()
    assert (evidence / "metadata.yml").is_file()
    assert all(report.is_file() for _role, _alias, report in reviewer_launches)
    metadata = yaml.safe_load(
        (evidence / "metadata.yml").read_text(encoding="utf-8")
    )
    for role, reviewer_alias, _report in reviewer_launches:
        launch = next(
            launch
            for launch in metadata["launches"]
            if launch["alias"] == reviewer_alias
        )
        assert launch["alias"] == reviewer_alias
        assert launch["role"] == role
        assert launch["model"] == "gpt-5.6-sol"
