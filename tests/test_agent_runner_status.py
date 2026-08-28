from __future__ import annotations

import json
import hashlib
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Mapping

import pytest
import yaml

from conftest import (
    PROJECT_ROOT,
    FakeCodex,
    InstalledCommands,
    run_process,
)
from test_project_setup import git_output, install_user_skills, run_setup


def wait_for_file(path: Path, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for {0}".format(path))


@pytest.fixture
def installed_worktree_commands(tmp_path: Path) -> InstalledCommands:
    environment_directory = tmp_path / "installed-runner"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "venv",
            "--system-site-packages",
            str(environment_directory),
        ],
        check=True,
    )
    python = environment_directory / "bin" / "python"
    result = run_process(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-build-isolation",
            str(PROJECT_ROOT),
        ],
        cwd=PROJECT_ROOT,
    )
    result.check_returncode()
    return InstalledCommands(
        product=environment_directory / "bin" / "you-are-a-product-architect",
        runner=environment_directory / "bin" / "agent-runner",
    )


def wait_for_process_exit(pid: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for worker {0} to exit".format(pid))


def process_contains_exact_argument(process: str, argument: str) -> bool:
    return re.search(
        r"(?<!\S){0}(?=\s|$)".format(re.escape(argument)), process
    ) is not None


def assert_no_resident_runner_processes(runner: Path) -> None:
    try:
        processes = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.splitlines()
    except PermissionError:
        pytest.skip(
            "Process-table inspection is unavailable; cannot validate no "
            "resident Runner daemon."
        )
    runner_path = str(runner)
    worker_python = str(runner.parent / "python")
    runner_processes = [
        process
        for process in processes
        if process_contains_exact_argument(process, runner_path)
        or (
            process_contains_exact_argument(process, worker_python)
            and process_contains_exact_argument(
                process, "you_are_a_product_architect.runner_worker"
            )
        )
    ]
    assert runner_processes == []


def test_no_resident_runner_assertion_detects_this_runner_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = tmp_path / "installed-runner" / "bin" / "agent-runner"
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=(
                "{0} --batch-input launch.yml\n".format(runner)
            ),
        ),
    )

    with pytest.raises(AssertionError):
        assert_no_resident_runner_processes(runner)


def test_no_resident_runner_assertion_detects_this_worker_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = tmp_path / "installed-runner" / "bin" / "agent-runner"
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=(
                "{0} -m ".format(runner.parent / "python")
                + "you_are_a_product_architect.runner_worker launch.yml\n"
            ),
        ),
    )

    with pytest.raises(AssertionError):
        assert_no_resident_runner_processes(runner)


def test_no_resident_runner_assertion_ignores_another_installation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = tmp_path / "installed-runner" / "bin" / "agent-runner"
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=(
                "/tmp/another-runner/bin/agent-runner --batch-input launch.yml\n"
                "/tmp/another-runner/bin/python -m "
                "you_are_a_product_architect.runner_worker launch.yml\n"
                "{0}-other --batch-input launch.yml\n"
                "{1}-other -m "
                "you_are_a_product_architect.runner_worker launch.yml\n"
            ).format(runner, runner.parent / "python"),
        ),
    )

    assert_no_resident_runner_processes(runner)


def configured_runner(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, dict[str, str]]:
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

    runner_directory = harness_root / ".codex" / "agent-runner"
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(user_home),
            "FAKE_CODEX_LOG": str(fake_codex.log_file),
        }
    )
    return harness_root, integration, runner_directory, user_home, environment


def launch_turn(
    installed_commands: InstalledCommands,
    harness_root: Path,
    integration: Path,
    environment: Mapping[str, str],
    *,
    ticket_id: str,
    ticket_name: str,
    role: str,
    run_id: str,
) -> tuple[str, Path]:
    ticket_file = harness_root / "ticket-{0}.md".format(ticket_id)
    ticket_file.write_text("# Canonical ticket {0}\n".format(ticket_id))
    batch_file = harness_root / "batch-{0}.yml".format(ticket_id)
    batch_file.write_text(
        yaml.safe_dump(
            {
                "run_id": run_id,
                "runtime": "codex",
                "tasks": [
                    {
                        "ticket_id": ticket_id,
                        "ticket_name": ticket_name,
                        "role": role,
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
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    task = yaml.safe_load(result.stdout)["tasks"][0]
    return task["alias"], ticket_file


def status(
    installed_commands: InstalledCommands,
    integration: Path,
    environment: Mapping[str, str],
    *aliases: str,
):
    return run_process(
        [str(installed_commands.runner), "status", *aliases],
        cwd=integration.parents[1],
        env=environment,
        timeout=5,
    )


def test_installed_status_observes_only_explicit_aliases_through_worker_exit(
    installed_worktree_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    (
        harness_root,
        integration,
        runner_directory,
        _,
        environment,
    ) = configured_runner(
        installed_worktree_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    release_file = tmp_path / "allow-runtime-to-finish"
    running_environment = {
        **environment,
        "FAKE_CODEX_RELEASE_FILE": str(release_file),
    }
    run_id = "20260813-status-observation"
    expert_alias, _ = launch_turn(
        installed_worktree_commands,
        harness_root,
        integration,
        {
            **running_environment,
            "FAKE_CODEX_EVENTS": json.dumps(
                [{"type": "thread.started", "thread_id": "thread-10"}]
            ),
        },
        ticket_id="10",
        ticket_name="status-expert",
        role="engineer-expert",
        run_id=run_id,
    )
    senior_alias, _ = launch_turn(
        installed_worktree_commands,
        harness_root,
        integration,
        {
            **running_environment,
            "FAKE_CODEX_EVENTS": json.dumps(
                [{"type": "thread.started", "thread_id": "thread-11"}]
            ),
        },
        ticket_id="11",
        ticket_name="status-senior",
        role="engineer-senior",
        run_id=run_id,
    )
    session_root = runner_directory / "sessions"
    expert_session = session_root / expert_alias
    senior_session = session_root / senior_alias

    try:
        explicit_only = status(
            installed_worktree_commands,
            integration,
            environment,
            senior_alias,
        )
        assert explicit_only.returncode == 0, explicit_only.stderr
        assert yaml.safe_load(explicit_only.stdout) == {
            "aliases": [{"alias": senior_alias, "activity": "running"}]
        }
        running = status(
            installed_worktree_commands,
            integration,
            environment,
            expert_alias,
            senior_alias,
        )
        assert running.returncode == 0, running.stderr
        assert running.stderr == ""
        assert yaml.safe_load(running.stdout) == {
            "aliases": [
                {"alias": expert_alias, "activity": "running"},
                {"alias": senior_alias, "activity": "running"},
            ]
        }
    finally:
        release_file.touch()

    expert_turn = expert_session / "turn.yml"
    senior_turn = senior_session / "turn.yml"
    wait_for_file(expert_turn)
    wait_for_file(senior_turn)
    expert_mapping = yaml.safe_load(
        (expert_session / "mapping.yml").read_text(encoding="utf-8")
    )
    senior_mapping = yaml.safe_load(
        (senior_session / "mapping.yml").read_text(encoding="utf-8")
    )
    wait_for_process_exit(expert_mapping["worker_pid"])
    wait_for_process_exit(senior_mapping["worker_pid"])

    idle = status(
        installed_worktree_commands,
        integration,
        environment,
        senior_alias,
        expert_alias,
    )
    assert idle.returncode == 0, idle.stderr
    assert idle.stderr == ""
    assert yaml.safe_load(idle.stdout) == {
        "aliases": [
            {
                "alias": senior_alias,
                "activity": "idle",
                "last_outcome": "completed",
            },
            {
                "alias": expert_alias,
                "activity": "idle",
                "last_outcome": "completed",
            },
        ]
    }
    assert list((runner_directory / "active-worktrees").iterdir()) == []
    assert_no_resident_runner_processes(installed_worktree_commands.runner)


@pytest.mark.parametrize(
    ("terminal_mode", "expected_outcome"),
    (("runtime-error", "runtime-error"), ("interrupted", "interrupted")),
)
def test_installed_status_reports_terminal_transport_outcomes(
    installed_worktree_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    terminal_mode: str,
    expected_outcome: str,
) -> None:
    (
        harness_root,
        integration,
        runner_directory,
        _,
        environment,
    ) = configured_runner(
        installed_worktree_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    turn_environment = {
        **environment,
        "FAKE_CODEX_EVENTS": json.dumps(
            [{"type": "thread.started", "thread_id": "thread-10"}]
        ),
    }
    if terminal_mode == "runtime-error":
        turn_environment["FAKE_CODEX_EXIT_CODE"] = "23"
    else:
        turn_environment["FAKE_CODEX_RELEASE_FILE"] = str(
            tmp_path / "allow-interrupt"
        )
    alias, _ = launch_turn(
        installed_worktree_commands,
        harness_root,
        integration,
        turn_environment,
        ticket_id="10",
        ticket_name="terminal-outcome",
        role="engineer-expert",
        run_id="20260813-terminal-outcome",
    )
    session_directory = runner_directory / "sessions" / alias
    turn_file = session_directory / "turn.yml"
    if terminal_mode == "interrupted":
        mapping = yaml.safe_load(
            (session_directory / "mapping.yml").read_text(encoding="utf-8")
        )
        os.kill(mapping["worker_pid"], signal.SIGTERM)
    wait_for_file(turn_file)

    observed = status(installed_worktree_commands, integration, environment, alias)
    assert observed.returncode == 0, observed.stderr
    assert observed.stderr == ""
    assert yaml.safe_load(observed.stdout) == {
        "aliases": [
            {
                "alias": alias,
                "activity": "idle",
                "last_outcome": expected_outcome,
            }
        ]
    }


def test_installed_worker_owns_an_unconfirmed_runtime_until_it_is_terminal(
    installed_worktree_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    (
        _,
        integration,
        runner_directory,
        _,
        environment,
    ) = configured_runner(
        installed_worktree_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    alias = "2-10-recovery@e1"
    ticket_id = "10"
    reservation_key = hashlib.sha256(ticket_id.encode("ascii")).hexdigest()
    session_directory = runner_directory / "sessions" / alias
    session_directory.mkdir(parents=True)
    reservation_file = runner_directory / "active-worktrees" / reservation_key
    reservation_file.parent.mkdir(parents=True)
    reservation_file.write_text(
        yaml.safe_dump(
            {
                "activity": "starting",
                "run_id": "20260813-recovery",
                "ticket_id": ticket_id,
                "worktree_path": str(integration),
            }
        ),
        encoding="utf-8",
    )
    reservation_identity = reservation_file.stat()
    launch_file = session_directory / "launch.yml"
    launch_file.write_text(
        yaml.safe_dump(
            {
                "runtime": "codex",
                "adapter_request": {},
                "active_turn_key": reservation_key,
                "active_turn_device": reservation_identity.st_dev,
                "active_turn_inode": reservation_identity.st_ino,
                "mapping": {
                    "alias": alias,
                    "runtime": "codex",
                    "run_id": "20260813-recovery",
                    "ticket_id": ticket_id,
                    "ticket_name": "recovery",
                    "role": "engineer-expert",
                    "branch": "agent/2-10-recovery",
                    "worktree_path": str(integration),
                    "ticket_file": str(tmp_path / "ticket.md"),
                    "evidence_path": str(
                        tmp_path
                        / "state"
                        / "task-delivery"
                        / "20260813-recovery"
                        / "tickets"
                        / "2-10-recovery"
                    ),
                    "turn": 1,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    recovery_started = tmp_path / "recovery-started"
    recovery_release = tmp_path / "recovery-release"
    worker_program = """
import os
import sys
import time
from pathlib import Path

from you_are_a_product_architect import runner_worker
from you_are_a_product_architect.runtime_adapter import RuntimeAdapterError


class RecoveringTurn:
    def run(self):
        raise RuntimeAdapterError(
            "TEST_RUNTIME_FAILURE",
            "The synthetic Runtime stopped reporting progress.",
            terminal_confirmed=False,
        )

    def terminate(self):
        return False

    def terminate_until_terminal(self):
        Path(os.environ["RECOVERY_STARTED"]).touch()
        while not Path(os.environ["RECOVERY_RELEASE"]).exists():
            time.sleep(0.01)


class RecoveringAdapter:
    def __call__(self, request, prompt, session_directory, session_started):
        session_started("synthetic-session", os.getpid())
        return RecoveringTurn()


runner_worker.ADAPTERS = {"codex": RecoveringAdapter()}
raise SystemExit(runner_worker.run(Path(sys.argv[1])))
"""
    worker = subprocess.Popen(
        [
            str(installed_worktree_commands.runner.parent / "python"),
            "-c",
            worker_program,
            str(launch_file),
        ],
        cwd=integration,
        env={
            **environment,
            "RECOVERY_STARTED": str(recovery_started),
            "RECOVERY_RELEASE": str(recovery_release),
        },
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert worker.stdin is not None
    worker.stdin.close()

    try:
        wait_for_file(session_directory / "mapping.yml")
        wait_for_file(recovery_started)
        assert worker.poll() is None
        observed = status(
            installed_worktree_commands,
            integration,
            environment,
            alias,
        )
        assert observed.returncode == 0, observed.stderr
        assert yaml.safe_load(observed.stdout) == {
            "aliases": [{"alias": alias, "activity": "running"}]
        }
        assert not (session_directory / "turn.yml").exists()
    finally:
        recovery_release.touch()

    assert worker.wait(timeout=5) == 0
    assert worker.stdout is not None
    assert worker.stderr is not None
    assert worker.stdout.read() == ""
    assert worker.stderr.read() == ""
    assert yaml.safe_load((session_directory / "turn.yml").read_text()) == {
        "outcome": "runtime-error"
    }
    assert list((runner_directory / "active-worktrees").iterdir()) == []


def test_installed_status_returns_stable_errors_for_unknown_and_corrupt_mappings(
    installed_worktree_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    (
        harness_root,
        integration,
        runner_directory,
        _,
        environment,
    ) = configured_runner(
        installed_worktree_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    alias, _ = launch_turn(
        installed_worktree_commands,
        harness_root,
        integration,
        environment,
        ticket_id="10",
        ticket_name="corrupt-mapping",
        role="engineer-expert",
        run_id="20260813-corrupt-mapping",
    )
    mapping_file = runner_directory / "sessions" / alias / "mapping.yml"
    wait_for_file(runner_directory / "sessions" / alias / "turn.yml")
    mapping_file.write_text("not: a durable alias mapping\n", encoding="utf-8")

    result = status(
        installed_worktree_commands,
        integration,
        environment,
        "2-99-unknown@e1",
        alias,
    )
    assert result.returncode == 1
    assert yaml.safe_load(result.stdout) == {
        "aliases": [
            {
                "alias": "2-99-unknown@e1",
                "error": {
                    "code": "alias-not-found",
                    "message": "The requested Engineer alias was not found.",
                },
            },
            {
                "alias": alias,
                "error": {
                    "code": "operation-failed",
                    "message": "The requested Engineer alias mapping is invalid.",
                },
            },
        ]
    }
    assert result.stderr == (
        "The requested Engineer alias was not found.\n"
        "The requested Engineer alias mapping is invalid.\n"
    )


def test_installed_status_reads_terminal_mapping_without_launch_preflight(
    installed_worktree_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    (
        harness_root,
        integration,
        runner_directory,
        _,
        environment,
    ) = configured_runner(
        installed_worktree_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    alias, _ = launch_turn(
        installed_worktree_commands,
        harness_root,
        integration,
        environment,
        ticket_id="10",
        ticket_name="durable-status",
        role="engineer-expert",
        run_id="20260813-durable-status",
    )
    wait_for_file(runner_directory / "sessions" / alias / "turn.yml")
    (integration / "uncommitted-status-marker").write_text("dirty\n")
    fake_codex.executable.unlink()

    observed = status(installed_worktree_commands, integration, environment, alias)

    assert observed.returncode == 0, observed.stderr
    assert observed.stderr == ""
    assert yaml.safe_load(observed.stdout) == {
        "aliases": [
            {
                "alias": alias,
                "activity": "idle",
                "last_outcome": "completed",
            }
        ]
    }
