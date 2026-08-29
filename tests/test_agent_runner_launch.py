from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from conftest import (
    PROJECT_ROOT,
    FakeCodex,
    InstalledCommands,
    run_process,
    wait_for_file,
)
from test_project_setup import (
    git_output,
    install_user_skills,
    run_ready_setup as run_setup,
)


def test_installed_runner_launches_one_isolated_engineer_and_returns_early(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    worktree_root = harness_root / ".agent-worktrees"
    integration = worktree_root / "integration"
    state = harness_root / "state"
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)

    setup_result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(temporary_git_repository.name),
    )
    assert setup_result.returncode == 0, setup_result.stderr
    dev_head = git_output(integration, "rev-parse", "HEAD")

    ticket_directory = harness_root / "tickets"
    ticket_directory.mkdir()
    ticket_file = ticket_directory / "10-launch-engineer.md"
    ticket_content = (
        "# Launch one isolated Codex Engineer\n\n"
        "Implement the accepted one-task Agent Runner tracer.\n\n"
        "## Acceptance\n\n"
        "- Launch in a derived Ticket Worktree.\n"
        "- Preserve durable mechanical evidence.\n"
    )
    ticket_file.write_text(ticket_content, encoding="utf-8")

    run_id = "20260813-v1-implementation"
    instruction = "Pay special attention to the durable alias mapping."
    batch_file = harness_root / "launch-batch.yml"
    batch_content = yaml.safe_dump(
        {
            "run_id": run_id,
            "runtime": "codex",
            "tasks": [
                {
                    "ticket_id": "10",
                    "ticket_name": "launch-engineer",
                    "role": "engineer-expert",
                    "ticket_file": str(ticket_file),
                    "instruction": instruction,
                }
            ],
        },
        sort_keys=False,
    )
    batch_file.write_text(batch_content, encoding="utf-8")

    release_file = tmp_path / "allow-fake-codex-to-finish"
    events = [
        {"type": "thread.started", "thread_id": "thread-ticket-10"},
        {"type": "turn.started"},
        {
            "type": "turn.completed",
            "usage": {
                "cached_input_tokens": 0,
                "input_tokens": 11,
                "output_tokens": 7,
            },
        },
    ]
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(user_home),
            "FAKE_CODEX_LOG": str(fake_codex.log_file),
            "FAKE_CODEX_EVENTS": json.dumps(events),
            "FAKE_CODEX_CAPTURE_STDIN": "1",
            "FAKE_CODEX_RELEASE_FILE": str(release_file),
        }
    )

    alias = "2-10-launch-engineer@e1"
    session_directory = (
        harness_root / ".codex" / "agent-runner" / "sessions" / alias
    )

    try:
        launch_result = run_process(
            [
                str(installed_commands.runner),
                "--batch-input",
                str(batch_file),
            ],
            cwd=harness_root,
            env=environment,
            timeout=5,
        )

        assert launch_result.returncode == 0, launch_result.stderr
        assert launch_result.stderr == ""
        document = yaml.safe_load(launch_result.stdout)

        ticket_worktree = (
            worktree_root
            / "runs"
            / run_id
            / "2-10-launch-engineer"
        ).resolve()
        branch = "agent/{0}/2-10-launch-engineer".format(run_id)
        retained_batch = state / run_id / "batch.yml"
        evidence = (
            state
            / run_id
            / "tickets"
            / "2-10-launch-engineer"
        ).resolve()
        task = document["tasks"][0]
        assert document["run_id"] == run_id
        assert document["runtime"] == "codex"
        assert task["launch_status"] == "launched"
        assert task["worktree_path"] == str(ticket_worktree)
        assert task["alias"] == alias
        assert task["session"] == "thread-ticket-10"

        assert retained_batch.read_bytes() == batch_content.encode("utf-8")

        scoped_state = ticket_worktree / ".state"
        assert scoped_state.is_symlink()
        assert scoped_state.resolve() == evidence
        assert (ticket_worktree / ".scratch").is_dir()

        assert git_output(ticket_worktree, "branch", "--show-current") == branch
        assert git_output(ticket_worktree, "rev-parse", "HEAD") == dev_head

        runtime_call = json.loads(fake_codex.log_file.read_text(encoding="utf-8"))
        assert runtime_call["cwd"] == str(ticket_worktree)
        assert runtime_call["stdin"].startswith(ticket_content)
        assert runtime_call["stdin"].find(instruction, len(ticket_content)) != -1

        mapping_file = session_directory / "mapping.yml"
        assert mapping_file.is_file()
        mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
        assert mapping["alias"] == alias
        assert mapping["session"] == "thread-ticket-10"
        assert Path(mapping["worktree_path"]) == ticket_worktree
        assert Path(mapping["evidence_path"]) == evidence
    finally:
        release_file.touch()
        turn_file = session_directory / "turn.yml"
        if session_directory.exists():
            wait_for_file(turn_file)


def test_installed_runner_launches_a_standards_reviewer_for_a_fixed_candidate(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    integration = harness_root / ".agent-worktrees" / "integration"
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    setup = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(temporary_git_repository.name),
    )
    assert setup.returncode == 0, setup.stderr

    candidate_file = integration / "candidate.txt"
    candidate_file.write_text("fixed candidate\n", encoding="utf-8")
    run_process(
        ["git", "add", "AGENTS.md", candidate_file.name], cwd=integration
    ).check_returncode()
    run_process(
        ["git", "commit", "-m", "Create fixed review candidate"], cwd=integration
    ).check_returncode()
    candidate = git_output(integration, "rev-parse", "HEAD")
    comparison = git_output(integration, "rev-parse", "HEAD^")

    ticket_file = harness_root / "review-ticket.md"
    ticket_content = "# Review the fixed candidate\n"
    ticket_file.write_text(ticket_content, encoding="utf-8")
    instruction = (
        "Review candidate {0} against {1}. Write the raw report to "
        ".state/reviews/candidate-r1-standards.md."
    ).format(
        candidate,
        comparison,
    )
    batch_file = harness_root / "review-batch.yml"
    batch_file.write_text(
        yaml.safe_dump(
            {
                "run_id": "20260818-review-candidate",
                "runtime": "codex",
                "tasks": [
                    {
                        "ticket_id": "50",
                        "ticket_name": "review-candidate",
                        "role": "standards-reviewer",
                        "review_round": 1,
                        "ticket_file": str(ticket_file),
                        "instruction": instruction,
                        "report_file": (
                            ".state/reviews/"
                            "candidate-r1-standards.md"
                        ),
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
            "FAKE_CODEX_CAPTURE_STDIN": "1",
        }
    )

    result = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch_file)],
        cwd=harness_root,
        env=environment,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    task = yaml.safe_load(result.stdout)["tasks"][0]
    assert task["role"] == "standards-reviewer"
    assert task["alias"] == "2-50-review-candidate@r1"
    worktree = Path(task["worktree_path"])
    evidence = (
        harness_root
        / "state"
        / "20260818-review-candidate"
        / "tickets"
        / "2-50-review-candidate"
    )
    session = (
        harness_root
        / ".codex"
        / "agent-runner"
        / "sessions"
        / task["alias"]
    )
    wait_for_file(session / "turn.yml")

    runtime_call = json.loads(fake_codex.log_file.read_text(encoding="utf-8"))
    assert runtime_call["cwd"] == str(worktree)
    assert git_output(worktree, "rev-parse", "HEAD") == candidate
    assert git_output(worktree, "status", "--short") == ""

    report = evidence / "reviews" / "candidate-r1-standards.md"
    report.write_text("earlier report\n", encoding="utf-8")
    repeated = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch_file)],
        cwd=harness_root,
        env=environment,
        timeout=5,
    )
    assert repeated.returncode == 1
    assert yaml.safe_load(repeated.stdout)["tasks"][0]["error"]["code"] == (
        "invalid-input"
    )
    assert report.read_text(encoding="utf-8") == "earlier report\n"


def test_installed_runner_rejects_invalid_skills_before_starting_any_task(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    integration = harness_root / ".agent-worktrees" / "integration"
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    setup = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(temporary_git_repository.name),
    )
    assert setup.returncode == 0, setup.stderr

    selected = integration / ".agents" / "skills" / "repo-selected" / "SKILL.md"
    selected.parent.mkdir(parents=True)
    selected.write_text(
        "---\nname: repo-selected\ndescription: Selected test Skill.\n---\n",
        encoding="utf-8",
    )
    run_process(["git", "add", ".agents"], cwd=integration).check_returncode()
    run_process(
        ["git", "commit", "-m", "Add selected repository Skill"],
        cwd=integration,
    ).check_returncode()

    ticket_root = harness_root / "tickets"
    ticket_root.mkdir()
    first_ticket = ticket_root / "first.md"
    second_ticket = ticket_root / "second.md"
    first_ticket.write_text("# First ticket\n", encoding="utf-8")
    second_ticket.write_text("# Second ticket\n", encoding="utf-8")
    batch_file = harness_root / "invalid-skill-batch.yml"
    batch_file.write_text(
        yaml.safe_dump(
            {
                "run_id": "20260816-skill-preflight",
                "runtime": "codex",
                "tasks": [
                    {
                        "ticket_id": "16.1",
                        "ticket_name": "valid-first-task",
                        "role": "engineer-expert",
                        "ticket_file": str(first_ticket),
                        "skills": ["repo-selected"],
                    },
                    {
                        "ticket_id": "16.2",
                        "ticket_name": "invalid-second-task",
                        "role": "engineer-expert",
                        "ticket_file": str(second_ticket),
                        "skills": ["missing-skill"],
                    },
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

    rejected = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch_file)],
        cwd=harness_root,
        env=environment,
    )

    assert rejected.returncode == 1
    assert yaml.safe_load(rejected.stdout)["error"]["code"] == "invalid-input"
    assert not fake_codex.log_file.exists()


@pytest.mark.parametrize(
    ("mutation", "expected_code", "expected_message"),
    (
        (
            "changed-hook-command",
            "invalid-config",
            "The configured Codex role does not contain the packaged Worktree Guard hooks.",
        ),
        (
            "changed-guard-script",
            "invalid-config",
            "The Harness Worktree Guard does not match the installed resource.",
        ),
    ),
)
def test_installed_runner_rejects_unvetted_role_or_guard_before_runtime_launch(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    mutation: str,
    expected_code: str,
    expected_message: str,
) -> None:
    harness_root = temporary_git_repository.parent
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    setup_result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(temporary_git_repository.name),
    )
    assert setup_result.returncode == 0, setup_result.stderr

    role_file = harness_root / ".codex" / "agents" / "engineer-expert.toml"
    guard_file = harness_root / ".codex" / "hooks" / "worktree_guard.py"
    if mutation == "changed-hook-command":
        role_file.write_text(
            role_file.read_text(encoding="utf-8").replace(
                'command = \'python3 "$(git rev-parse --show-toplevel)/.codex/hooks/worktree_guard.py"\'',
                "command = 'python3 unvetted-hook.py'",
                1,
            ),
            encoding="utf-8",
        )
    elif mutation == "changed-guard-script":
        guard_file.write_text(
            guard_file.read_text(encoding="utf-8") + "\n# unvetted change\n",
            encoding="utf-8",
        )
    ticket_file = harness_root / "ticket.md"
    ticket_file.write_text("# Canonical ticket\n", encoding="utf-8")
    batch_file = harness_root / "batch.yml"
    batch_file.write_text(
        yaml.safe_dump(
            {
                "run_id": "20260813-security-check",
                "runtime": "codex",
                "tasks": [
                    {
                        "ticket_id": "10",
                        "ticket_name": "launch-engineer",
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
        {"HOME": str(user_home), "FAKE_CODEX_LOG": str(fake_codex.log_file)}
    )

    result = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch_file)],
        cwd=harness_root,
        env=environment,
    )

    assert result.returncode == 1
    assert list(yaml.safe_load_all(result.stdout)) == [
        {
            "error": {
                "code": expected_code,
                "message": expected_message,
            }
        }
    ]
    assert result.stderr == expected_message + "\n"
    assert not fake_codex.log_file.exists()
    assert not (
        harness_root
        / ".agent-worktrees"
        / "runs"
        / "20260813-security-check"
    ).exists()
    assert not (
        harness_root / "state" / "20260813-security-check"
    ).exists()


def test_read_batch_rejects_physical_task_input(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_ROOT / "src"))
    from you_are_a_product_architect.runner_batch import read_batch
    from you_are_a_product_architect.runner_models import RunnerError

    ticket_file = tmp_path / "ticket.md"
    ticket_file.write_text("# Canonical ticket\n", encoding="utf-8")
    batch_file = tmp_path / "batch.yml"
    batch_file.write_text(
        yaml.safe_dump(
            {
                "run_id": "20260813-physical-input",
                "runtime": "codex",
                "tasks": [
                    {
                        "ticket_id": "10",
                        "ticket_name": "launch-engineer",
                        "role": "engineer-expert",
                        "ticket_file": str(ticket_file),
                        "worktree_path": "/tmp/main-selected",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(RunnerError) as raised:
        read_batch(batch_file, tmp_path)

    assert raised.value.code == "TASK_SCHEMA_INVALID"


def test_installed_runner_separates_ambiguous_ticket_identity_pairs(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    setup_result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(temporary_git_repository.name),
    )
    assert setup_result.returncode == 0, setup_result.stderr

    run_id = "20260813-identity-boundary"
    environment = os.environ.copy()
    environment.update(
        {"HOME": str(user_home), "FAKE_CODEX_LOG": str(fake_codex.log_file)}
    )
    cases = (
        ("a-b", "c"),
        ("a", "b-c"),
    )
    results = []
    for ordinal, (ticket_id, ticket_name) in enumerate(cases, start=1):
        ticket_file = harness_root / "ticket-{0}.md".format(ordinal)
        ticket_file.write_text("# Canonical ticket {0}\n".format(ordinal))
        batch_file = harness_root / "batch-{0}.yml".format(ordinal)
        batch_file.write_text(
            yaml.safe_dump(
                {
                    "run_id": run_id,
                    "runtime": "codex",
                    "tasks": [
                        {
                            "ticket_id": ticket_id,
                            "ticket_name": ticket_name,
                            "role": "engineer-expert",
                            "ticket_file": str(ticket_file),
                        }
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

        assert result.returncode == 0, result.stderr
        task = yaml.safe_load(result.stdout)["tasks"][0]
        results.append(task)

    assert results[0]["worktree_path"] != results[1]["worktree_path"]
    assert results[0]["alias"] != results[1]["alias"]


def test_concurrent_runner_processes_atomically_reserve_one_ticket_worktree(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    integration = harness_root / ".agent-worktrees" / "integration"
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    setup_result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(temporary_git_repository.name),
    )
    assert setup_result.returncode == 0, setup_result.stderr

    ticket_file = harness_root / "ticket.md"
    ticket_file.write_text("# Canonical ticket\n", encoding="utf-8")
    run_id = "20260813-concurrent-launch"
    batch_file = harness_root / "batch.yml"
    batch_file.write_text(
        yaml.safe_dump(
            {
                "run_id": run_id,
                "runtime": "codex",
                "tasks": [
                    {
                        "ticket_id": "10",
                        "ticket_name": "launch-engineer",
                        "role": "engineer-expert",
                        "ticket_file": str(ticket_file),
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    release_file = tmp_path / "allow-runtime-to-finish"
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(user_home),
            "FAKE_CODEX_LOG": str(fake_codex.log_file),
            "FAKE_CODEX_RELEASE_FILE": str(release_file),
        }
    )
    command = [str(installed_commands.runner), "--batch-input", str(batch_file)]
    processes = [
        subprocess.Popen(
            command,
            cwd=harness_root,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(2)
    ]
    runner_directory = harness_root / ".codex" / "agent-runner"
    session_directory = (
        runner_directory / "sessions" / "2-10-launch-engineer@e1"
    )

    try:
        completed = [
            process.communicate(timeout=5) + (process.returncode,)
            for process in processes
        ]
        successes = [result for result in completed if result[2] == 0]
        failures = [result for result in completed if result[2] == 1]
        assert len(successes) == 1, completed
        assert len(failures) == 1, completed
        assert yaml.safe_load(successes[0][0])["tasks"][0]["alias"] == (
            "2-10-launch-engineer@e1"
        )
        assert yaml.safe_load(failures[0][0]) == {
            "error": {
                "code": "worktree-busy",
                "message": "The Ticket Worktree already has an active Engineer turn.",
            }
        }
        assert failures[0][1] == (
            "The Ticket Worktree already has an active Engineer turn.\n"
        )

        active = list((runner_directory / "active-worktrees").iterdir())
        assert len(active) == 1
        reservation = yaml.safe_load(
            active[0].read_text(encoding="utf-8")
        )
        assert reservation["activity"] == "running"
        assert reservation["alias"] == "2-10-launch-engineer@e1"
        assert [path.name for path in (runner_directory / "sessions").iterdir()] == [
            "2-10-launch-engineer@e1"
        ]
    finally:
        release_file.touch()
        for process in processes:
            if process.poll() is None:
                process.kill()
        if session_directory.exists():
            wait_for_file(session_directory / "turn.yml")


def test_failed_launch_retains_reservation_until_worker_and_runtime_terminate(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    integration = harness_root / ".agent-worktrees" / "integration"
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    setup_result = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(temporary_git_repository.name),
    )
    assert setup_result.returncode == 0, setup_result.stderr

    ticket_file = harness_root / "ticket.md"
    ticket_file.write_text("# Canonical ticket\n", encoding="utf-8")
    run_id = "20260813-termination-order"
    batch_file = harness_root / "batch.yml"
    batch_file.write_text(
        yaml.safe_dump(
            {
                "run_id": run_id,
                "runtime": "codex",
                "tasks": [
                    {
                        "ticket_id": "10",
                        "ticket_name": "launch-engineer",
                        "role": "engineer-expert",
                        "ticket_file": str(ticket_file),
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    termination_seen = tmp_path / "runtime-saw-sigterm"
    termination_release = tmp_path / "runtime-may-terminate"
    termination_ready = tmp_path / "runtime-handler-ready"
    mapping_release = tmp_path / "runtime-may-report-session"
    event_release = tmp_path / "runtime-may-complete"
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(user_home),
            "FAKE_CODEX_LOG": str(fake_codex.log_file),
            "FAKE_CODEX_TERMINATION_SEEN": str(termination_seen),
            "FAKE_CODEX_TERMINATION_RELEASE": str(termination_release),
            "FAKE_CODEX_TERMINATION_READY": str(termination_ready),
            "FAKE_CODEX_MAPPING_RELEASE": str(mapping_release),
            "FAKE_CODEX_EVENT_RELEASE": str(event_release),
        }
    )
    command = [str(installed_commands.runner), "--batch-input", str(batch_file)]
    first = subprocess.Popen(
        command,
        cwd=harness_root,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    active_root = harness_root / ".codex" / "agent-runner" / "active-worktrees"
    evidence = (
        harness_root
        / "state"
        / run_id
        / "tickets"
        / "2-10-launch-engineer"
    )
    metadata_conflict = evidence / "metadata.yml"

    try:
        wait_for_file(termination_ready)
        metadata_conflict.mkdir()
        mapping_release.touch()
        mapping_file = (
            harness_root
            / ".codex"
            / "agent-runner"
            / "sessions"
            / "2-10-launch-engineer@e1"
            / "mapping.yml"
        )
        wait_for_file(mapping_file)
        wait_for_file(termination_seen)
        assert first.poll() is None
        assert len(list(active_root.iterdir())) == 1

        second = run_process(command, cwd=harness_root, env=environment, timeout=5)

        assert second.returncode == 1
        assert yaml.safe_load(second.stdout) == {
            "error": {
                "code": "worktree-busy",
                "message": (
                    "The Ticket Worktree already has an active Engineer turn under "
                    "alias 2-10-launch-engineer@e1."
                ),
            }
        }
        assert len(list(active_root.iterdir())) == 1
    finally:
        termination_release.touch()

    first_stdout, first_stderr = first.communicate(timeout=12)
    assert first.returncode == 1
    assert yaml.safe_load(first_stdout)["tasks"][0]["error"] == {
        "code": "launch-failed",
        "message": "The Runner could not persist mechanical ticket metadata.",
    }
    assert first_stderr == (
        "The Runner could not persist mechanical ticket metadata.\n"
    )
    assert list(active_root.iterdir()) == []

    metadata_conflict.rmdir()
    clean_environment = dict(environment)
    for name in (
        "FAKE_CODEX_TERMINATION_SEEN",
        "FAKE_CODEX_TERMINATION_RELEASE",
        "FAKE_CODEX_TERMINATION_READY",
        "FAKE_CODEX_MAPPING_RELEASE",
        "FAKE_CODEX_EVENT_RELEASE",
    ):
        clean_environment.pop(name)
    third = run_process(command, cwd=harness_root, env=clean_environment, timeout=5)
    assert third.returncode == 0, third.stderr
    assert yaml.safe_load(third.stdout)["tasks"][0]["alias"] == (
        "2-10-launch-engineer@e2"
    )
