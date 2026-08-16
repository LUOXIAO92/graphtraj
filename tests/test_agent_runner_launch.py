from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import tomllib
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
from test_project_setup import git_output, install_user_skills, run_setup


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


def test_alias_mapping_durability_syncs_file_and_every_directory_entry(
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
        ("directory", mapping.parent.parent.parent),
    ]


def test_active_reservation_is_an_atomically_owned_regular_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_ROOT / "src"))
    from you_are_a_product_architect.runner_io import (
        create_active_turn_reservation,
        release_active_turn,
    )

    runner_directory = tmp_path / "agent-runner"
    runner_directory.mkdir()
    owner = {
        "activity": "starting",
        "run_id": "20260813-atomic-reservation",
        "ticket_id": "14",
        "worktree_path": str(tmp_path / "worktree"),
    }

    reservation = create_active_turn_reservation(
        runner_directory,
        owner["ticket_id"],
        owner,
    )
    reservation_file = (
        runner_directory / "active-worktrees" / reservation.key
    )
    identity = reservation_file.stat()

    assert reservation_file.is_file()
    assert yaml.safe_load(reservation_file.read_text(encoding="utf-8")) == owner
    assert (reservation.device, reservation.inode) == (
        identity.st_dev,
        identity.st_ino,
    )
    assert release_active_turn(runner_directory, reservation)
    assert not reservation_file.exists()


def test_active_reservation_release_preserves_a_final_path_replacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_ROOT / "src"))
    from you_are_a_product_architect import runner_io

    runner_directory = tmp_path / "agent-runner"
    runner_directory.mkdir()
    owner = {
        "activity": "cleanup",
        "run_id": "20260813-release-race",
        "ticket_id": "14",
        "worktree_path": str(tmp_path / "worktree"),
    }
    reservation = runner_io.create_active_turn_reservation(
        runner_directory, owner["ticket_id"], owner
    )
    active_root = runner_directory / "active-worktrees"
    reservation_file = active_root / reservation.key
    retained = active_root / "retained-original"
    replacement = b"replacement: preserve\n"
    real_stat = os.stat
    real_rename = os.rename
    injected = False

    def replace_after_validation(
        path: str,
        *args: object,
        **kwargs: object,
    ) -> os.stat_result:
        nonlocal injected
        identity = real_stat(path, *args, **kwargs)
        if path == reservation.key and not injected:
            injected = True
            real_rename(str(reservation_file), str(retained))
            reservation_file.write_bytes(replacement)
        return identity

    monkeypatch.setattr(runner_io.os, "stat", replace_after_validation)

    assert not runner_io.release_active_turn(runner_directory, reservation)
    assert retained.is_file()
    assert yaml.safe_load(retained.read_text(encoding="utf-8")) == owner
    assert replacement in [path.read_bytes() for path in active_root.iterdir()]


def test_active_reservation_is_project_wide_for_ticket_across_delivery_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_ROOT / "src"))
    from you_are_a_product_architect.runner_io import release_active_turn
    from you_are_a_product_architect.runner_launch import _reserve_active_turn
    from you_are_a_product_architect.runner_models import (
        Batch,
        Project,
        RunnerError,
        Task,
    )

    common_directory = tmp_path / "git-common"
    runner_directory = tmp_path / ".codex" / "agent-runner"
    runner_directory.mkdir(parents=True)
    project = Project(
        harness_root=tmp_path,
        repository=tmp_path / "repository",
        common_directory=common_directory,
        runner_directory=runner_directory,
        worktree_root=tmp_path / "worktrees",
        state_directory=tmp_path / "state",
        integration_branch="dev",
        integration_worktree=tmp_path / "integration",
        dev_commit="0" * 40,
        runtime_executable=tmp_path / "codex",
        role_bindings={"engineer-expert": "engineer-expert"},
    )
    task = Task(
        ticket_id="10",
        ticket_name="launch-engineer",
        role="engineer-expert",
        ticket_file=tmp_path / "ticket.md",
        ticket_content="# Launch Engineer\n",
        instruction=None,
    )
    first_batch = Batch(
        run_id="20260813-first-run",
        tasks=(task,),
        source_bytes=b"first",
    )
    second_batch = Batch(
        run_id="20260813-second-run",
        tasks=(task,),
        source_bytes=b"second",
    )
    first_worktree = project.worktree_root / "runs" / first_batch.run_id / task.stem
    second_worktree = (
        project.worktree_root / "runs" / second_batch.run_id / task.stem
    )

    reservation = _reserve_active_turn(
        project, first_batch.run_id, task, first_worktree
    )
    try:
        with pytest.raises(RunnerError) as raised:
            _reserve_active_turn(
                project, second_batch.run_id, task, second_worktree
            )

        assert raised.value.code == "WORKTREE_TURN_ACTIVE"
        owner = yaml.safe_load(
            (
                runner_directory / "active-worktrees"
                / reservation.key
            ).read_text(encoding="utf-8")
        )
        assert owner["run_id"] == first_batch.run_id
        assert owner["worktree_path"] == str(first_worktree)
    finally:
        release_active_turn(
            runner_directory, reservation
        )


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
    repository_skills = integration / ".agents" / "skills"
    for name in ("repo-selected", "repo-disabled"):
        document = repository_skills / name / "SKILL.md"
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_text(
            "---\nname: {0}\ndescription: Repository test Skill.\n---\n".format(
                name
            ),
            encoding="utf-8",
        )
    run_process(["git", "add", ".agents"], cwd=integration).check_returncode()
    run_process(
        ["git", "commit", "-m", "Add repository Skills"],
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
                        "skills": ["repo-selected"],
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
        assert runtime_argv[:12] == [
                "exec",
                "-C",
                str(ticket_worktree),
                "--add-dir",
                str(evidence),
                "--add-dir",
                str(common_directory),
                "--model",
                "gpt-5.6-sol",
                "--sandbox",
                "workspace-write",
                "--dangerously-bypass-hook-trust",
        ]
        assert runtime_argv[-2:] == ["--json", "-"]
        assert runtime_argv.count("--add-dir") == 2
        assert "--profile" not in runtime_argv

        config_argv = runtime_argv[12:-2]
        assert config_argv[::2] == ["-c"] * 6
        parsed_overrides = {}
        for override in config_argv[1::2]:
            parsed_overrides.update(tomllib.loads(override))
        role_config = tomllib.loads(
            (
                harness_root
                / ".codex"
                / "agents"
                / "engineer-expert.toml"
            ).read_text(encoding="utf-8")
        )
        expected_role_overrides = {
            "model_reasoning_effort": role_config["model_reasoning_effort"],
            "agents": role_config["agents"],
        }
        for key, value in expected_role_overrides.items():
            assert parsed_overrides[key] == value
        assert parsed_overrides["projects"] == {
            str(ticket_worktree): {"trust_level": "untrusted"}
        }
        configured_skills = {
            entry["path"]: entry["enabled"]
            for entry in parsed_overrides["skills"]["config"]
        }
        assert configured_skills[
            str(ticket_worktree / ".agents" / "skills" / "repo-selected" / "SKILL.md")
        ] is True
        assert configured_skills[
            str(ticket_worktree / ".agents" / "skills" / "repo-disabled" / "SKILL.md")
        ] is False
        assert all(
            configured_skills[
                str(user_home / ".agents" / "skills" / name / "SKILL.md")
            ]
            is True
            for name in ("implement", "ponytail", "tdd", "code-review")
        )
        for event in ("PreToolUse", "SubagentStart"):
            for entry in parsed_overrides["hooks"][event]:
                for hook in entry["hooks"]:
                    assert str(
                        harness_root / ".codex" / "hooks" / "worktree_guard.py"
                    ) in hook["command"]
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
            cwd=harness_root,
            env=environment,
            timeout=5,
        )
        assert second_launch.returncode == 1
        assert yaml.safe_load(second_launch.stdout) == {
            "error": {
                "code": "worktree-busy",
                "message": (
                    "The Ticket Worktree already has an active Engineer turn under "
                    "alias 2-10-launch-engineer@e1."
                ),
            }
        }
        assert second_launch.stderr == (
            "The Ticket Worktree already has an active Engineer turn under "
            "alias 2-10-launch-engineer@e1.\n"
        )
        assert not (
            harness_root
            / ".codex"
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
            "aliases": [alias],
            "role": "engineer-expert",
            "runtime": "codex",
            "session": "thread-ticket-10",
            "branch": branch,
            "worktree_path": str(ticket_worktree),
            "ticket_file": str(ticket_file.resolve()),
            "requested_skills": ["repo-selected"],
            "effective_skills": [
                {
                    "name": name,
                    "path": str(
                        user_home / ".agents" / "skills" / name / "SKILL.md"
                    ),
                    "enabled": True,
                    "source": "runtime-user",
                }
                for name in ("implement", "ponytail", "tdd", "code-review")
            ]
            + [
                {
                    "name": "repo-disabled",
                    "path": str(
                        ticket_worktree
                        / ".agents"
                        / "skills"
                        / "repo-disabled"
                        / "SKILL.md"
                    ),
                    "enabled": False,
                    "source": "repository",
                },
                {
                    "name": "repo-selected",
                    "path": str(
                        ticket_worktree
                        / ".agents"
                        / "skills"
                        / "repo-selected"
                        / "SKILL.md"
                    ),
                    "enabled": True,
                    "source": "repository",
                },
            ],
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
    active_root = harness_root / ".codex" / "agent-runner" / "active-worktrees"
    assert list(active_root.iterdir()) == []


def test_installed_runner_rejects_invalid_skills_before_starting_any_task(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root = temporary_git_repository.parent
    primary = temporary_git_repository
    integration = harness_root / ".agent-worktrees" / "integration"
    user_home = tmp_path / "operator-home"
    install_user_skills(user_home)
    setup = run_setup(
        installed_commands,
        harness_root=harness_root,
        user_home=user_home,
        fake_codex=fake_codex,
        answers="{0}\ny\n".format(primary.name),
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

    message = (
        "The requested Repository Skill missing-skill was not found in the "
        "Ticket Worktree."
    )
    assert rejected.returncode == 1
    assert yaml.safe_load(rejected.stdout) == {
        "error": {"code": "invalid-input", "message": message}
    }
    assert rejected.stderr == message + "\n"
    assert not fake_codex.log_file.exists()
    assert not (harness_root / ".agent-worktrees" / "runs").exists()


@pytest.mark.parametrize(
    ("mutation", "expected_code", "expected_message"),
    (
        (
            "unsupported-role-key",
            "invalid-config",
            "The configured Codex role uses an unsupported top-level schema.",
        ),
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
        (
            "changed-project-config",
            "invalid-config",
            "The Harness Codex config does not match the installed resource.",
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
    config_file = harness_root / ".codex" / "config.toml"
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
    elif mutation == "changed-guard-script":
        guard_file.write_text(
            guard_file.read_text(encoding="utf-8") + "\n# unvetted change\n",
            encoding="utf-8",
        )
    else:
        config_file.write_text(
            config_file.read_text(encoding="utf-8").replace(
                'sandbox_mode = "workspace-write"',
                'sandbox_mode = "read-only"',
                1,
            ),
            encoding="utf-8",
        )
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
    base_task = {
        "ticket_id": "10",
        "ticket_name": "launch-engineer",
        "role": "engineer-expert",
        "ticket_file": str(ticket_file),
    }
    cases = (
        (
            {
                "run_id": "20260813-" + "a" * 49,
                "tasks": [base_task],
            },
            "invalid-input",
            (
                "run_id must use YYYYMMDD-short-name form with a semantic "
                "short name of at most 48 ASCII characters and at most 64 "
                "characters overall."
            ),
        ),
        (
            {"run_id": "not-a-dated-run", "tasks": [base_task]},
            "invalid-input",
            (
                "run_id must use YYYYMMDD-short-name form with a semantic "
                "short name of at most 48 ASCII characters and at most 64 "
                "characters overall."
            ),
        ),
        (
            {
                "run_id": "20260813-invalid-ticket-id",
                "tasks": [{**base_task, "ticket_id": "invalid/ticket"}],
            },
            "invalid-input",
            "ticket_id must be 1-32 ASCII letters, digits, dots, underscores, or hyphens.",
        ),
        (
            {
                "run_id": "20260813-invalid-ticket-name",
                "tasks": [{**base_task, "ticket_name": "Launch-Engineer"}],
            },
            "invalid-input",
            "ticket_name must be 1-64 ASCII lowercase kebab-case characters.",
        ),
        (
            {
                "run_id": "20260813-invalid-role",
                "tasks": [{**base_task, "role": "engineer-principal"}],
            },
            "invalid-input",
            "The selected logical Engineer role is not configured.",
        ),
        (
            {
                "run_id": "20260813-physical-input",
                "tasks": [{**base_task, "worktree_path": "/tmp/main-selected"}],
            },
            "invalid-input",
            "A task must contain ticket identity, role, ticket_file, and optional instruction and Skills only.",
        ),
        (
            {
                "run_id": "20260813-multiple-tasks",
                "tasks": [
                    base_task,
                    {**base_task, "ticket_id": "11"},
                    {**base_task, "ticket_id": "12"},
                    {**base_task, "ticket_id": "13"},
                    {**base_task, "ticket_id": "14"},
                ],
            },
            "invalid-input",
            "A batch must contain between one and four tasks.",
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
            cwd=harness_root,
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


def test_installed_runner_rejects_preexisting_ticket_branch_off_validated_dev(
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
    dev_head = git_output(integration, "rev-parse", "HEAD")
    run_process(
        ["git", "commit", "--allow-empty", "-m", "Advance primary"],
        cwd=temporary_git_repository,
    ).check_returncode()
    main_head = git_output(temporary_git_repository, "rev-parse", "main")
    assert main_head != dev_head

    run_id = "20260813-conflicting-ticket-branch"
    branch = "agent/{0}/2-10-launch-engineer".format(run_id)
    run_process(
        ["git", "branch", branch, main_head], cwd=integration
    ).check_returncode()
    ticket_file = harness_root / "ticket.md"
    ticket_file.write_text("# Canonical ticket\n", encoding="utf-8")
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
    error = {
        "code": "worktree-conflict",
        "message": (
            "The existing Ticket branch is not at the current validated dev state."
        ),
    }
    assert yaml.safe_load(result.stdout) == {"error": error}
    assert result.stderr == error["message"] + "\n"
    assert not (
        harness_root
        / ".agent-worktrees"
        / "runs"
        / run_id
        / "2-10-launch-engineer"
    ).exists()
    assert git_output(integration, "rev-parse", branch) == main_head
    assert not fake_codex.log_file.exists()


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
            cwd=harness_root,
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
