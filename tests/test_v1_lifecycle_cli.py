from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import yaml

from conftest import FakeCodex, InstalledCommands, run_process
from test_project_setup import (
    CORE_SKILL_NAMES,
    git_output,
    run_setup,
    setup_environment,
    tree_contents,
    worktree_contents,
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


def test_operator_guide_covers_the_complete_v1_lifecycle() -> None:
    guide = (Path(__file__).resolve().parents[1] / "README.md").read_text(
        encoding="utf-8"
    )

    for required_text in (
        "Pinned installation",
        "Harness Project Root",
        "Primary Worktree",
        "Integration Worktree",
        "Harness State Directory",
        "you-are-a-product-architect doctor",
        "you-are-a-product-architect setup",
        "Review and commit",
        "agent-runner --batch-input",
        "agent-runner status",
        "agent-runner send",
        "agent-runner interrupt",
        "agent-runner cleanup",
        "state/task-delivery",
        "manually delete",
        "GitHub, GitLab, local Markdown",
        "Codex-only",
        "name-only",
        "duplicate Skill names",
        "scheduler or queue",
        "automatic state watcher",
        "multiple Source Repositories",
        "automatic promotion from `dev` to `main`",
    ):
        assert required_text in guide


def test_pinned_install_exercises_the_complete_v1_delivery_lifecycle(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    primary = temporary_git_repository
    integration = harness_root / ".agent-worktrees" / "integration"
    state = harness_root / "state"
    target_validation = primary / "validate_v1_delivery.py"
    target_validation.write_text(
        """\
from pathlib import Path


assert Path("V1_DELIVERED.txt").read_text(encoding="utf-8") == (
    "representative delivery\\n"
)
print("target validation passed")
""",
        encoding="utf-8",
    )
    run_process(
        ["git", "add", target_validation.name], cwd=primary
    ).check_returncode()
    run_process(
        ["git", "commit", "-m", "Add target validation command"],
        cwd=primary,
    ).check_returncode()
    user_home = tmp_path / "operator-home"
    (user_home / ".codex").mkdir(parents=True)
    (user_home / ".codex" / "config.toml").write_text(
        "operator_owned = true\n", encoding="utf-8"
    )
    (user_home / ".codex" / "credentials.json").write_text(
        "{\"credential\": \"unchanged\"}\n", encoding="utf-8"
    )
    primary_before = worktree_contents(primary)
    user_before = tree_contents(user_home)
    main_before = git_output(primary, "rev-parse", "main")
    environment = setup_environment(user_home, fake_codex)

    before_setup = run_process(
        [str(installed_commands.product), "doctor"],
        cwd=harness_root,
        env=environment,
    )
    assert before_setup.returncode == 1
    assert "implement: MISSING" in before_setup.stdout

    setup = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\ny\n".format(primary.name),
    )

    assert setup.returncode == 0, setup.stderr
    assert "Harness Runtime Store installed at {0}/.codex.".format(
        harness_root
    ) in setup.stdout
    assert git_output(primary, "branch", "--show-current") == "main"
    assert git_output(primary, "rev-parse", "HEAD") == main_before
    assert git_output(primary, "status", "--porcelain") == ""
    assert worktree_contents(primary) == primary_before
    assert tree_contents(user_home) == user_before
    assert integration.is_dir()
    assert git_output(integration, "branch", "--show-current") == "dev"
    assert (integration / ".scratch").resolve() == state.resolve()
    assert {
        path.name for path in (harness_root / ".agents" / "skills").iterdir()
    } == set(CORE_SKILL_NAMES)
    for resource in (
        harness_root / ".codex" / "config.toml",
        harness_root / ".codex" / "hooks" / "worktree_guard.py",
        harness_root / ".codex" / "agents" / "engineer-junior.toml",
        harness_root / ".codex" / "agents" / "engineer-senior.toml",
        harness_root / ".codex" / "agents" / "engineer-expert.toml",
        harness_root / ".codex" / "agents" / "standards-reviewer.toml",
        harness_root / ".codex" / "agents" / "spec-reviewer.toml",
        harness_root / ".codex" / "agents" / "merge-resolver.toml",
        harness_root / ".codex" / "agents" / "delivery-state.toml",
    ):
        assert resource.is_file()
    assert not (integration / ".codex").exists()
    assert not (integration / ".agents").exists()

    after_setup = run_process(
        [str(installed_commands.product), "doctor"],
        cwd=harness_root,
        env=environment,
    )
    assert after_setup.returncode == 0, after_setup.stderr
    for name in CORE_SKILL_NAMES:
        assert "{0}: OK".format(name) in after_setup.stdout

    assert git_output(integration, "status", "--porcelain") == ""

    ticket_file = harness_root / "tickets" / "15-v1-lifecycle.md"
    ticket_file.parent.mkdir()
    ticket_content = "# Representative V1 ticket\n\nWrite one delivery marker.\n"
    ticket_file.write_text(ticket_content, encoding="utf-8")
    ticket_before = ticket_file.read_bytes()
    run_id = "20260814-v1-lifecycle"
    batch_file = harness_root / "batch.yml"
    batch_content = yaml.safe_dump(
        {
            "run_id": run_id,
            "runtime": "codex",
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
    )
    batch_file.write_text(batch_content, encoding="utf-8")
    release_file = tmp_path / "allow-initial-turn-to-finish"
    session = "fake-v1-lifecycle-session"
    launch_environment = {
        **environment,
        "FAKE_CODEX_EVENTS": json.dumps(
            [{"type": "thread.started", "thread_id": session}]
        ),
        "FAKE_CODEX_RELEASE_FILE": str(release_file),
    }

    launch = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch_file)],
        cwd=harness_root,
        env=launch_environment,
        timeout=10,
    )

    assert launch.returncode == 0, launch.stderr
    launch_document = yaml.safe_load(launch.stdout)
    task = launch_document["tasks"][0]
    assert task["launch_status"] == "launched"
    assert task["session"] == session
    assert ticket_file.read_bytes() == ticket_before
    ticket_worktree = Path(task["worktree_path"])
    alias = task["alias"]
    assert ticket_worktree.name == "2-15-v1-lifecycle"
    assert alias == "2-15-v1-lifecycle@e1"
    ticket_branch = "agent/{0}/2-15-v1-lifecycle".format(run_id)
    assert git_output(ticket_worktree, "branch", "--show-current") == ticket_branch
    evidence = state / "task-delivery" / run_id / "tickets" / ticket_worktree.name
    retained_batch = Path(launch_document["retained_batch_file"])
    assert retained_batch.read_bytes() == batch_content.encode("utf-8")
    assert (ticket_worktree / ".scratch" / "task-delivery").resolve() == evidence.resolve()
    assert not (ticket_worktree / ".codex").exists()
    assert not (ticket_worktree / ".agents").exists()

    running = run_process(
        [str(installed_commands.runner), "status", alias],
        cwd=harness_root,
        env=environment,
    )
    assert running.returncode == 0, running.stderr
    assert yaml.safe_load(running.stdout) == {
        "aliases": [{"alias": alias, "activity": "running"}]
    }

    interrupted = run_process(
        [str(installed_commands.runner), "interrupt", alias],
        cwd=harness_root,
        env=environment,
        timeout=10,
    )
    assert interrupted.returncode == 0, interrupted.stderr
    assert yaml.safe_load(interrupted.stdout) == {
        "alias": alias,
        "interrupt_status": "interrupted",
    }
    wait_for_idle_outcome(
        installed_commands,
        harness_root=harness_root,
        environment=environment,
        alias=alias,
        outcome="interrupted",
    )

    instruction = "Resume this representative ticket and finish it."
    resumed = run_process(
        [
            str(installed_commands.runner),
            "send",
            alias,
            "--instruction",
            instruction,
        ],
        cwd=harness_root,
        env={
                **environment,
                "FAKE_CODEX_CAPTURE_STDIN": "1",
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
    assert yaml.safe_load(resumed.stdout) == {"alias": alias, "send_status": "sent"}
    wait_for_idle_outcome(
        installed_commands,
        harness_root=harness_root,
        environment=environment,
        alias=alias,
        outcome="completed",
    )
    runtime_record = json.loads(fake_codex.log_file.read_text(encoding="utf-8"))
    assert runtime_record["stdin"] == instruction
    assert "resume" in runtime_record["argv"]
    assert session in runtime_record["argv"]
    assert runtime_record["cwd"] == str(ticket_worktree)

    delivered = ticket_worktree / "V1_DELIVERED.txt"
    assert delivered.read_text(encoding="utf-8") == "representative delivery\n"
    candidate = git_output(ticket_worktree, "rev-parse", "HEAD")
    reviews = evidence / "reviews"
    assert (evidence / "result.md").read_text(encoding="utf-8") == (
        "Candidate commit: {0}\n"
        "Outcome: representative ticket delivered.\n"
        "Outstanding concern: Main must adjudicate the raw reviews.\n"
    ).format(candidate)
    assert (evidence / "validation.md").read_text(encoding="utf-8") == (
        "Candidate commit: {0}\n"
        "Command: git diff --check HEAD^ HEAD\n"
        "Result: passed.\n"
    ).format(candidate)
    reviewer_evidence = []
    review_processes = []
    review_release = tmp_path / "allow-reviews-to-finish"
    for axis, role in (
        ("standards", "standards-reviewer"),
        ("spec", "spec-reviewer"),
    ):
        report = reviews / "{0}-r1-{1}.md".format(alias, axis)
        review_batch = harness_root / "{0}-review.yml".format(axis)
        review_batch.write_text(
            yaml.safe_dump(
                {
                    "run_id": run_id,
                    "runtime": "codex",
                    "tasks": [
                        {
                            "ticket_id": "15",
                            "ticket_name": "v1-lifecycle",
                            "role": role,
                            "ticket_file": str(ticket_file),
                            "instruction": (
                                "Review candidate {0} against {1}; write only {2}."
                            ).format(candidate, main_before, report),
                        }
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        review_session = "fake-v1-{0}-review-session".format(axis)
        review_processes.append(
            (
                axis,
                role,
                report,
                subprocess.Popen(
                    [
                        str(installed_commands.runner),
                        "--batch-input",
                        str(review_batch),
                    ],
                    cwd=harness_root,
                    env={
                        **environment,
                        "FAKE_CODEX_EVENTS": json.dumps(
                            [
                                {
                                    "type": "thread.started",
                                    "thread_id": review_session,
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
                        "FAKE_CODEX_LIFECYCLE_ACTION": (
                            "review-representative-candidate"
                        ),
                        "FAKE_CODEX_REVIEW_AXIS": axis,
                        "FAKE_CODEX_REVIEW_CANDIDATE": candidate,
                        "FAKE_CODEX_REVIEW_REPORT": str(report),
                        "FAKE_CODEX_RELEASE_FILE": str(review_release),
                    },
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                ),
            )
        )

    review_tasks = []
    for axis, role, report, process in review_processes:
        review_stdout, review_stderr = process.communicate(timeout=10)
        assert process.returncode == 0, review_stderr
        review_task = yaml.safe_load(review_stdout)["tasks"][0]
        reviewer_alias = review_task["alias"]
        running_review = run_process(
            [str(installed_commands.runner), "status", reviewer_alias],
            cwd=harness_root,
            env=environment,
        )
        assert running_review.returncode == 0, running_review.stderr
        assert yaml.safe_load(running_review.stdout) == {
            "aliases": [{"alias": reviewer_alias, "activity": "running"}]
        }
        review_tasks.append((axis, role, report, review_task))

    engineer_while_reviewing = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch_file)],
        cwd=harness_root,
        env=environment,
        timeout=10,
    )
    assert engineer_while_reviewing.returncode == 1
    assert yaml.safe_load(engineer_while_reviewing.stdout)["error"]["code"] == (
        "worktree-busy"
    )

    review_release.touch()
    for axis, role, report, review_task in review_tasks:
        reviewer_alias = review_task["alias"]
        wait_for_idle_outcome(
            installed_commands,
            harness_root=harness_root,
            environment=environment,
            alias=reviewer_alias,
            outcome="completed",
        )
        assert review_task["role"] == role
        assert review_task["worktree_path"] == str(ticket_worktree)
        assert git_output(ticket_worktree, "rev-parse", "HEAD") == candidate
        assert git_output(ticket_worktree, "status", "--porcelain") == ""
        assert report.read_text(encoding="utf-8") == (
            "Raw {0} review for candidate {1}.\n"
            "Main must adjudicate this evidence.\n"
        ).format(axis.title(), candidate)
        reviewer_evidence.append(
            {
                "alias": reviewer_alias,
                "role": role,
                "runtime": "codex",
                "model": "gpt-5.6-sol",
            }
        )

    metadata = yaml.safe_load(
        (evidence / "metadata.yml").read_text(encoding="utf-8")
    )
    recorded_reviews = [
        {
            key: launch[key]
            for key in ("alias", "role", "runtime", "model")
        }
        for launch in metadata["launches"][-2:]
    ]
    assert sorted(recorded_reviews, key=lambda review: review["role"]) == sorted(
        reviewer_evidence, key=lambda review: review["role"]
    )
    evidence_before_cleanup = tree_contents(evidence)
    retained_batch_before_cleanup = retained_batch.read_bytes()

    merged = run_process(
        ["git", "merge", "--no-ff", candidate, "-m", "Integrate representative ticket"],
        cwd=integration,
    )
    assert merged.returncode == 0, merged.stderr
    validation = run_process(
        ["git", "diff", "--check", "HEAD^", "HEAD"], cwd=integration
    )
    assert validation.returncode == 0, validation.stderr
    assert (integration / delivered.name).read_text(encoding="utf-8") == (
        "representative delivery\n"
    )
    validated = run_process(
        [sys.executable, target_validation.name], cwd=integration
    )
    assert validated.returncode == 0, validated.stderr
    assert validated.stdout == "target validation passed\n"
    assert git_output(primary, "rev-parse", "main") == main_before
    assert not (primary / delivered.name).exists()

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
    cleanup_document = yaml.safe_load(cleanup.stdout)
    assert cleanup_document["cleanup_status"] == "cleaned"
    assert cleanup_document["aliases_removed"][0] == alias
    assert set(cleanup_document["aliases_removed"][1:]) == {
        reviewer["alias"] for reviewer in reviewer_evidence
    }
    assert not ticket_worktree.exists()
    branch_gone = run_process(
        [
            "git",
            "show-ref",
            "--verify",
            "--quiet",
            "refs/heads/{0}".format(ticket_branch),
        ],
        cwd=integration,
    )
    assert branch_gone.returncode == 1
    alias_gone = run_process(
        [str(installed_commands.runner), "status", alias],
        cwd=harness_root,
        env=environment,
    )
    alias_not_found = "The requested Engineer alias was not found."
    assert alias_gone.returncode == 1
    assert yaml.safe_load(alias_gone.stdout) == {
        "aliases": [
            {
                "alias": alias,
                "error": {
                    "code": "alias-not-found",
                    "message": alias_not_found,
                },
            }
        ]
    }
    assert alias_gone.stderr == alias_not_found + "\n"
    assert tree_contents(evidence) == evidence_before_cleanup
    assert retained_batch.read_bytes() == retained_batch_before_cleanup

    repeated_cleanup = run_process(
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
    assert repeated_cleanup.returncode == 0, repeated_cleanup.stderr
    assert yaml.safe_load(repeated_cleanup.stdout)["cleanup_status"] == "already-cleaned"
    assert tree_contents(evidence) == evidence_before_cleanup
    assert retained_batch.read_bytes() == retained_batch_before_cleanup
    assert git_output(primary, "branch", "--show-current") == "main"
    assert git_output(primary, "rev-parse", "HEAD") == main_before
    assert git_output(primary, "status", "--porcelain") == ""
    assert worktree_contents(primary) == primary_before
    assert tree_contents(user_home) == user_before
