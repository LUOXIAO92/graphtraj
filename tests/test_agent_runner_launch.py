from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import time
import tomllib
from pathlib import Path

import pytest
import yaml

from conftest import PROJECT_ROOT, FakeCodex, InstalledCommands, run_process
from test_project_setup import git_output, install_user_skills, run_setup


def wait_for_file(path: Path, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for {0}".format(path))


def test_background_worker_keeps_codex_process_protocol_inside_adapter() -> None:
    worker_file = (
        PROJECT_ROOT / "src" / "you_are_a_product_architect" / "runner_worker.py"
    )
    adapter_file = (
        PROJECT_ROOT / "src" / "you_are_a_product_architect" / "codex_adapter.py"
    )
    worker_source = worker_file.read_text(encoding="utf-8")
    adapter_source = adapter_file.read_text(encoding="utf-8")
    worker_imports = {
        alias.name
        for node in ast.walk(ast.parse(worker_source))
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert "subprocess" not in worker_imports
    assert "json" not in worker_imports
    assert "thread.started" not in worker_source
    assert "subprocess" in adapter_source
    assert "thread.started" in adapter_source


def test_alias_mapping_durability_syncs_file_alias_then_sessions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module_spec = importlib.util.spec_from_file_location(
        "tested_runner_io",
        PROJECT_ROOT / "src" / "you_are_a_product_architect" / "runner_io.py",
    )
    assert module_spec is not None and module_spec.loader is not None
    runner_io = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(runner_io)
    mapping = tmp_path / "sessions" / "ticket@e1" / "mapping.yml"
    mapping.parent.mkdir(parents=True)
    mapping.write_text("session: opaque\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        runner_io,
        "_sync_file",
        lambda path: calls.append(("file", path)),
    )
    monkeypatch.setattr(
        runner_io,
        "_sync_directory",
        lambda path: calls.append(("directory", path)),
    )

    runner_io.confirm_alias_mapping_durable(mapping)

    assert calls == [
        ("file", mapping),
        ("directory", mapping.parent),
        ("directory", mapping.parent.parent),
    ]


def test_installed_runner_launches_one_isolated_engineer_and_returns_early(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    primary = temporary_git_repository
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
        answers="{0}\ny\n".format(primary.name),
    )
    assert setup_result.returncode == 0, setup_result.stderr
    run_process(["git", "add", ".codex"], cwd=integration).check_returncode()
    run_process(
        ["git", "commit", "-m", "Configure Codex on dev"],
        cwd=integration,
    ).check_returncode()
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
    ticket_before = ticket_file.read_bytes()

    run_id = "20260813-v1-implementation"
    instruction = "Pay special attention to the durable alias mapping."
    batch_file = harness_root / "launch-batch.yml"
    batch_content = yaml.safe_dump(
        {
            "run_id": run_id,
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
    common_directory = Path(git_output(primary, "rev-parse", "--git-common-dir"))
    if not common_directory.is_absolute():
        common_directory = primary / common_directory
    common_directory = common_directory.resolve()
    session_directory = common_directory / "agent-runner" / "sessions" / alias

    try:
        launch_result = run_process(
            [
                str(installed_commands.runner),
                "--batch-input",
                str(batch_file),
            ],
            cwd=integration,
            env=environment,
            timeout=5,
        )

        assert launch_result.returncode == 0, launch_result.stderr
        assert launch_result.stderr == ""
        documents = list(yaml.safe_load_all(launch_result.stdout))
        assert len(documents) == 1

        ticket_worktree = (
            worktree_root
            / "runs"
            / run_id
            / "2-10-launch-engineer"
        ).resolve()
        branch = "agent/{0}/2-10-launch-engineer".format(run_id)
        retained_batch = state / "task-delivery" / run_id / "batch.yml"
        evidence = (
            state
            / "task-delivery"
            / run_id
            / "tickets"
            / "2-10-launch-engineer"
        ).resolve()
        assert documents == [
            {
                "run_id": run_id,
                "retained_batch_file": str(retained_batch.resolve()),
                "tasks": [
                    {
                        "ticket_id": "10",
                        "ticket_name": "launch-engineer",
                        "role": "engineer-expert",
                        "launch_status": "launched",
                        "worktree_path": str(ticket_worktree),
                        "ticket_file": str(ticket_file.resolve()),
                        "alias": alias,
                        "session": "thread-ticket-10",
                    }
                ],
            }
        ]

        assert retained_batch.read_bytes() == batch_content.encode("utf-8")
        assert ticket_file.read_bytes() == ticket_before
        assert [path.name for path in evidence.parent.iterdir()] == [
            "2-10-launch-engineer"
        ]
        assert sorted(path.name for path in evidence.iterdir()) == ["metadata.yml"]

        scoped_scratch = ticket_worktree / ".scratch" / "task-delivery"
        assert scoped_scratch.is_symlink()
        assert scoped_scratch.resolve() == evidence
        assert not (ticket_worktree / ticket_file.name).exists()

        assert git_output(primary, "branch", "--show-current") == "main"
        assert git_output(integration, "branch", "--show-current") == "dev"
        assert git_output(ticket_worktree, "branch", "--show-current") == branch
        assert git_output(ticket_worktree, "rev-parse", "HEAD") == dev_head
        assert git_output(integration, "rev-parse", "HEAD") == dev_head
        assert git_output(primary, "rev-parse", "HEAD") != dev_head

        runtime_call = json.loads(fake_codex.log_file.read_text(encoding="utf-8"))
        expected_task = (
            ticket_content
            + "\n## Additional instruction from Main\n\n"
            + instruction
            + "\n"
        )
        assert runtime_call["cwd"] == str(ticket_worktree)
        assert runtime_call["stdin"] == expected_task
        runtime_argv = runtime_call["argv"]
        assert runtime_argv[:10] == [
                "exec",
                "-C",
                str(ticket_worktree),
                "--add-dir",
                str(evidence),
                "--model",
                "gpt-5.6-sol",
                "--sandbox",
                "workspace-write",
                "--dangerously-bypass-hook-trust",
        ]
        assert runtime_argv[-2:] == ["--json", "-"]
        assert runtime_argv.count("--add-dir") == 1
        assert "--profile" not in runtime_argv

        config_argv = runtime_argv[10:-2]
        assert config_argv[::2] == ["-c", "-c", "-c", "-c"]
        parsed_overrides = {}
        for override in config_argv[1::2]:
            parsed_overrides.update(tomllib.loads(override))
        role_config = tomllib.loads(
            (
                ticket_worktree
                / ".codex"
                / "agents"
                / "engineer-expert.toml"
            ).read_text(encoding="utf-8")
        )
        assert parsed_overrides == {
            "model_reasoning_effort": role_config["model_reasoning_effort"],
            "developer_instructions": role_config["developer_instructions"],
            "hooks": role_config["hooks"],
            "agents": role_config["agents"],
        }
        assert role_config["name"] not in runtime_argv
        assert role_config["description"] not in runtime_argv

        mapping_file = session_directory / "mapping.yml"
        assert mapping_file.is_file()
        mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
        assert mapping["alias"] == alias
        assert mapping["runtime"] == "codex"
        assert mapping["session"] == "thread-ticket-10"
        assert mapping["run_id"] == run_id
        assert mapping["ticket_id"] == "10"
        assert mapping["role"] == "engineer-expert"
        assert mapping["branch"] == branch
        assert Path(mapping["worktree_path"]) == ticket_worktree
        assert Path(mapping["ticket_file"]) == ticket_file.resolve()
        assert Path(mapping["evidence_path"]) == evidence
        os.kill(mapping["worker_pid"], 0)
        os.kill(mapping["runtime_pid"], 0)

        second_launch = run_process(
            [
                str(installed_commands.runner),
                "--batch-input",
                str(batch_file),
            ],
            cwd=integration,
            env=environment,
            timeout=5,
        )
        assert second_launch.returncode == 1
        assert yaml.safe_load(second_launch.stdout) == {
            "run_id": run_id,
            "retained_batch_file": str(retained_batch.resolve()),
            "tasks": [
                {
                    "ticket_id": "10",
                    "ticket_name": "launch-engineer",
                    "role": "engineer-expert",
                    "worktree_path": str(ticket_worktree),
                    "ticket_file": str(ticket_file.resolve()),
                    "launch_status": "failed",
                    "error": {
                        "code": "WORKTREE_TURN_ACTIVE",
                        "message": (
                            "The Ticket Worktree already has an active Engineer turn."
                        ),
                    },
                }
            ],
        }
        assert second_launch.stderr == (
            "The Ticket Worktree already has an active Engineer turn.\n"
        )
        assert not (
            common_directory
            / "agent-runner"
            / "sessions"
            / "2-10-launch-engineer@e2"
        ).exists()
        assert yaml.safe_load(mapping_file.read_text(encoding="utf-8")) == mapping

        metadata = yaml.safe_load(
            (evidence / "metadata.yml").read_text(encoding="utf-8")
        )
        assert metadata == {
            "run_id": run_id,
            "ticket_id": "10",
            "ticket_name": "launch-engineer",
            "alias": alias,
            "role": "engineer-expert",
            "runtime": "codex",
            "session": "thread-ticket-10",
            "branch": branch,
            "worktree_path": str(ticket_worktree),
            "ticket_file": str(ticket_file.resolve()),
        }

        event_lines = (session_directory / "events.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        assert [json.loads(line) for line in event_lines] == [events[0]]
        assert not (session_directory / "turn.yml").exists()
        assert not release_file.exists()
    finally:
        release_file.touch()
        turn_file = session_directory / "turn.yml"
        if session_directory.exists():
            wait_for_file(turn_file)
    active_root = common_directory / "agent-runner" / "active-worktrees"
    assert list(active_root.iterdir()) == []


@pytest.mark.parametrize(
    ("mutation", "expected_code", "expected_message"),
    (
        (
            "unsupported-role-key",
            "ROLE_CONFIG_UNSUPPORTED",
            "The configured Codex role uses an unsupported top-level schema.",
        ),
        (
            "changed-hook-command",
            "ROLE_HOOK_MISMATCH",
            "The configured Codex role does not contain the packaged Worktree Guard hooks.",
        ),
        (
            "changed-guard-script",
            "ROLE_GUARD_MISMATCH",
            "The project Worktree Guard does not match the installed resource.",
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

    role_file = integration / ".codex" / "agents" / "engineer-expert.toml"
    guard_file = integration / ".codex" / "hooks" / "worktree_guard.py"
    if mutation == "unsupported-role-key":
        role_file.write_text(
            role_file.read_text(encoding="utf-8").replace(
                "\nmodel = ", "\nunsupported_setting = true\n\nmodel = ", 1
            ),
            encoding="utf-8",
        )
    elif mutation == "changed-hook-command":
        role_file.write_text(
            role_file.read_text(encoding="utf-8").replace(
                'command = \'python3 "$(git rev-parse --show-toplevel)/.codex/hooks/worktree_guard.py"\'',
                "command = 'python3 unvetted-hook.py'",
                1,
            ),
            encoding="utf-8",
        )
    else:
        guard_file.write_text(
            guard_file.read_text(encoding="utf-8") + "\n# unvetted change\n",
            encoding="utf-8",
        )
    run_process(["git", "add", ".codex"], cwd=integration).check_returncode()
    run_process(
        ["git", "commit", "-m", "Mutate the selected role"], cwd=integration
    ).check_returncode()

    ticket_file = harness_root / "ticket.md"
    ticket_file.write_text("# Canonical ticket\n", encoding="utf-8")
    batch_file = harness_root / "batch.yml"
    batch_file.write_text(
        yaml.safe_dump(
            {
                "run_id": "20260813-security-check",
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
        cwd=integration,
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
    assert "launch_status" not in result.stdout
    assert not fake_codex.log_file.exists()
    assert not (
        harness_root
        / ".agent-worktrees"
        / "runs"
        / "20260813-security-check"
    ).exists()
    assert not (
        harness_root / "state" / "task-delivery" / "20260813-security-check"
    ).exists()


def test_installed_runner_rejects_invalid_logical_input_without_launch_artifacts(
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
    run_process(["git", "add", ".codex"], cwd=integration).check_returncode()
    run_process(
        ["git", "commit", "-m", "Configure Codex on dev"], cwd=integration
    ).check_returncode()
    ticket_file = harness_root / "ticket.md"
    ticket_file.write_text("# Canonical ticket\n", encoding="utf-8")
    base_task = {
        "ticket_id": "10",
        "ticket_name": "launch-engineer",
        "role": "engineer-expert",
        "ticket_file": str(ticket_file),
    }
    cases = (
        (
            {"run_id": "not-a-dated-run", "tasks": [base_task]},
            "RUN_ID_INVALID",
            "run_id must be at most 64 ASCII characters in YYYYMMDD-short-name form.",
        ),
        (
            {
                "run_id": "20260813-invalid-ticket-id",
                "tasks": [{**base_task, "ticket_id": "invalid/ticket"}],
            },
            "TICKET_ID_INVALID",
            "ticket_id must be 1-32 ASCII letters, digits, dots, underscores, or hyphens.",
        ),
        (
            {
                "run_id": "20260813-invalid-ticket-name",
                "tasks": [{**base_task, "ticket_name": "Launch-Engineer"}],
            },
            "TICKET_NAME_INVALID",
            "ticket_name must be 1-64 ASCII lowercase kebab-case characters.",
        ),
        (
            {
                "run_id": "20260813-invalid-role",
                "tasks": [{**base_task, "role": "engineer-principal"}],
            },
            "ROLE_NOT_CONFIGURED",
            "The selected logical Engineer role is not configured.",
        ),
        (
            {
                "run_id": "20260813-physical-input",
                "tasks": [{**base_task, "worktree_path": "/tmp/main-selected"}],
            },
            "TASK_SCHEMA_INVALID",
            "A task must contain ticket identity, role, and ticket_file only.",
        ),
        (
            {
                "run_id": "20260813-multiple-tasks",
                "tasks": [base_task, {**base_task, "ticket_id": "11"}],
            },
            "TASK_COUNT_UNSUPPORTED",
            "This Runner release accepts exactly one task per batch.",
        ),
    )
    environment = os.environ.copy()
    environment.update(
        {"HOME": str(user_home), "FAKE_CODEX_LOG": str(fake_codex.log_file)}
    )

    for ordinal, (batch, code, message) in enumerate(cases, start=1):
        batch_file = harness_root / "invalid-{0}.yml".format(ordinal)
        batch_file.write_text(
            yaml.safe_dump(batch, sort_keys=False), encoding="utf-8"
        )

        result = run_process(
            [str(installed_commands.runner), "--batch-input", str(batch_file)],
            cwd=integration,
            env=environment,
        )

        assert result.returncode == 1, code
        assert list(yaml.safe_load_all(result.stdout)) == [
            {"error": {"code": code, "message": message}}
        ]
        assert result.stderr == message + "\n"

    assert not fake_codex.log_file.exists()
    assert not (harness_root / ".agent-worktrees" / "runs").exists()
    assert not (harness_root / "state" / "task-delivery").exists()


def test_installed_runner_separates_ambiguous_ticket_identity_pairs(
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
    run_process(["git", "add", ".codex"], cwd=integration).check_returncode()
    run_process(
        ["git", "commit", "-m", "Configure Codex on dev"], cwd=integration
    ).check_returncode()

    run_id = "20260813-identity-boundary"
    environment = os.environ.copy()
    environment.update(
        {"HOME": str(user_home), "FAKE_CODEX_LOG": str(fake_codex.log_file)}
    )
    cases = (
        ("a-b", "c", "3-a-b-c"),
        ("a", "b-c", "1-a-b-c"),
    )
    results = []
    for ordinal, (ticket_id, ticket_name, expected_stem) in enumerate(
        cases, start=1
    ):
        ticket_file = harness_root / "ticket-{0}.md".format(ordinal)
        ticket_file.write_text("# Canonical ticket {0}\n".format(ordinal))
        batch_file = harness_root / "batch-{0}.yml".format(ordinal)
        batch_file.write_text(
            yaml.safe_dump(
                {
                    "run_id": run_id,
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
            cwd=integration,
            env=environment,
        )

        assert result.returncode == 0, result.stderr
        task = yaml.safe_load(result.stdout)["tasks"][0]
        assert Path(task["worktree_path"]).name == expected_stem
        assert task["alias"] == "{0}@e1".format(expected_stem)
        assert git_output(
            Path(task["worktree_path"]), "branch", "--show-current"
        ) == "agent/{0}/{1}".format(run_id, expected_stem)
        results.append(task)

    assert results[0]["worktree_path"] != results[1]["worktree_path"]
    evidence_root = (
        harness_root / "state" / "task-delivery" / run_id / "tickets"
    )
    assert sorted(path.name for path in evidence_root.iterdir()) == [
        "1-a-b-c",
        "3-a-b-c",
    ]


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
    run_process(["git", "add", ".codex"], cwd=integration).check_returncode()
    run_process(
        ["git", "commit", "-m", "Configure Codex on dev"], cwd=integration
    ).check_returncode()

    ticket_file = harness_root / "ticket.md"
    ticket_file.write_text("# Canonical ticket\n", encoding="utf-8")
    run_id = "20260813-concurrent-launch"
    batch_file = harness_root / "batch.yml"
    batch_file.write_text(
        yaml.safe_dump(
            {
                "run_id": run_id,
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
            cwd=integration,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(2)
    ]
    common_directory = Path(
        git_output(temporary_git_repository, "rev-parse", "--git-common-dir")
    )
    if not common_directory.is_absolute():
        common_directory = temporary_git_repository / common_directory
    runner_directory = common_directory.resolve() / "agent-runner"
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
        failed_task = yaml.safe_load(failures[0][0])["tasks"][0]
        assert failed_task["launch_status"] == "failed"
        assert failed_task["error"] == {
            "code": "WORKTREE_TURN_ACTIVE",
            "message": "The Ticket Worktree already has an active Engineer turn.",
        }
        assert failures[0][1] == (
            "The Ticket Worktree already has an active Engineer turn.\n"
        )

        active = list((runner_directory / "active-worktrees").iterdir())
        assert len(active) == 1
        reservation = yaml.safe_load(
            (active[0] / "reservation.yml").read_text(encoding="utf-8")
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
    assert list((runner_directory / "active-worktrees").iterdir()) == []


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
    run_process(["git", "add", ".codex"], cwd=integration).check_returncode()
    run_process(
        ["git", "commit", "-m", "Configure Codex on dev"], cwd=integration
    ).check_returncode()

    ticket_file = harness_root / "ticket.md"
    ticket_file.write_text("# Canonical ticket\n", encoding="utf-8")
    run_id = "20260813-termination-order"
    batch_file = harness_root / "batch.yml"
    batch_file.write_text(
        yaml.safe_dump(
            {
                "run_id": run_id,
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
        cwd=integration,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    common_directory = Path(
        git_output(temporary_git_repository, "rev-parse", "--git-common-dir")
    )
    if not common_directory.is_absolute():
        common_directory = temporary_git_repository / common_directory
    active_root = common_directory.resolve() / "agent-runner" / "active-worktrees"
    evidence = (
        harness_root
        / "state"
        / "task-delivery"
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
            common_directory.resolve()
            / "agent-runner"
            / "sessions"
            / "2-10-launch-engineer@e1"
            / "mapping.yml"
        )
        wait_for_file(mapping_file)
        wait_for_file(termination_seen)
        assert first.poll() is None
        assert len(list(active_root.iterdir())) == 1

        second = run_process(command, cwd=integration, env=environment, timeout=5)

        assert second.returncode == 1
        assert yaml.safe_load(second.stdout)["tasks"][0]["error"] == {
            "code": "WORKTREE_TURN_ACTIVE",
            "message": "The Ticket Worktree already has an active Engineer turn.",
        }
        assert len(list(active_root.iterdir())) == 1
    finally:
        termination_release.touch()

    first_stdout, first_stderr = first.communicate(timeout=12)
    assert first.returncode == 1
    assert yaml.safe_load(first_stdout)["tasks"][0]["error"] == {
        "code": "METADATA_WRITE_FAILED",
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
    third = run_process(command, cwd=integration, env=clean_environment, timeout=5)
    assert third.returncode == 0, third.stderr
    assert yaml.safe_load(third.stdout)["tasks"][0]["alias"] == (
        "2-10-launch-engineer@e2"
    )
