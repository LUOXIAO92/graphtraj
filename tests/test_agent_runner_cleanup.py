from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from conftest import runner_operation, FakeCodex, InstalledCommands, run_process, wait_for_file
from runner_fixtures import configure_harness
from test_task_graph import _change_status, _register, _task
from test_task_recovery import installed_commands
from test_pi_runtime import pi_environment

# Pi's structured termination facts for a startup that never bound or prompted (291882a).
PI_STARTUP_FACTS = {'wrapper_exited': True, 'owned_process_group_exited': True,
                    'native_session_bound': False, 'prompt_started': False}


@pytest.mark.parametrize('worker_case', ['absent', 'waiting', 'foreign-group', 'runtime-artifact'])
def test_native_interrupt_confirms_only_pre_runtime_allocations(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    worker_case: str,
) -> None:
    """Exact native process identity and the startup barrier precede cleanup."""
    task = _deliver_task(installed_commands, temporary_git_repository, fake_codex,
                             tmp_path, integrate=True, terminal_failed_start=True)
    sessions = task.root / '.graphtraj/runner/sessions'
    original = sessions / task.failed_start_aliases[0]
    launch = yaml.safe_load((original / 'launch.yml').read_text())
    alias = '85-cleanup_integrated_task-handover0-failed_start@before_start'
    directory = sessions / alias
    directory.mkdir()
    trace = task.task_directory / 'teams/1/traces' / alias / 'events.jsonl'
    trace.parent.mkdir()
    trace.touch()
    launch['mapping'].update(alias=alias, trace_file=str(trace))
    (directory / 'launch.yml').write_text(yaml.safe_dump(launch))
    (directory / 'events.jsonl').write_text(
        '{"type":"runtime","runtime":"codex"}\n{"type":"runner-execution-start"}\n')
    (directory / 'worker-stderr.log').touch()
    if worker_case == 'runtime-artifact':
        (directory / 'owner-123.lock').touch()
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    worker = None
    waiter = None
    try:
        if worker_case in {'waiting', 'foreign-group'}:
            worker = subprocess.Popen(
                [str(installed_commands.runner.with_name('python')), '-I', '-m',
                 'graphtraj.execution.runner_worker', str(directory / 'launch.yml')],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=task.environment, start_new_session=worker_case == 'waiting',
            )
            # The spawning parent reaps its own child while the public Runner
            # confirms the recorded process group's exit.
            waiter = threading.Thread(target=worker.wait)
            waiter.start()
        result = run_process(runner_operation(installed_commands, 'interrupt', alias),
                             cwd=task.root, env=task.environment, timeout=20)
        if worker_case in {'foreign-group', 'runtime-artifact'}:
            assert result.returncode == 1, result.stdout + result.stderr
            assert {path.name: path.read_bytes() for path in directory.iterdir()} == before
            if worker is not None:
                assert worker.poll() is None
            return
        assert result.returncode == 0, result.stdout + result.stderr
        result_document = yaml.safe_load(result.stdout)
        assert result_document['interrupt_status'] == 'stopped'
        assert result_document['evidence']['worker_pids'] == ([] if worker is None else [worker.pid])
        if worker is not None:
            assert worker.poll() is not None
        failure = yaml.safe_load((directory / 'launch-error.yml').read_text())
        assert failure['terminal_confirmed'] is True
        assert json.loads(failure['diagnostic']) == result_document['evidence']
        assert all((directory / name).read_bytes() == content for name, content in before.items())
        if worker_case == 'absent':
            # A parent that was about to spawn at the observation cannot start
            # native work after the stop barrier has been published.
            late = subprocess.run(
                [str(installed_commands.runner.with_name('python')), '-I', '-m',
                 'graphtraj.execution.runner_worker', str(directory / 'launch.yml')],
                input='A late launch must not run.', text=True, capture_output=True,
                env=task.environment, timeout=10,
            )
            assert late.returncode != 0
            assert not (directory / 'mapping.yml').exists()
            assert trace.read_bytes() == b''
            failure = yaml.safe_load((directory / 'launch-error.yml').read_text())
            assert failure['code'] == 'subtree-stopped'
            assert failure['terminal_confirmed'] is True
        cleaned = _cleanup(task)
        assert cleaned.returncode == 0, cleaned.stdout + cleaned.stderr
        retained = trace.parent / 'runner'
        assert all((retained / name).read_bytes() == content for name, content in before.items())
    finally:
        if worker is not None:
            if worker.poll() is None:
                worker.terminate()
            worker.wait(timeout=5)
            assert worker.stdin is not None
            worker.stdin.close()
        if waiter is not None:
            waiter.join(timeout=5)


@dataclass(frozen=True)
class DeliveredTask:
    root: Path
    repository: Path
    state: Path
    worktree: Path
    branch: str
    task_id: str
    task_name: str
    task_directory: Path
    environment: dict[str, str]
    commands: InstalledCommands
    failed_start_aliases: tuple[str, ...]


def _deliver_task(
    commands: InstalledCommands,
    repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    *,
    integrate: bool,
    failed_start: bool = False,
    terminal_failed_start: bool = False,
    pi_startup: dict | None = None,
    pi_interrupt: bool = False,
    pi_crash: bool = False,
) -> DeliveredTask:
    root, worktrees, _, environment = configure_harness(
        commands, repository, fake_codex, tmp_path
    )
    roles_file = root / '.graphtraj/roles.yml'
    roles = yaml.safe_load(roles_file.read_text())
    roles['roles']['failed_start'] = dict(roles['roles']['coding_team']['engineer'])
    if pi_startup is not None:
        roles['roles']['failed_start'] = {
            'runtime': 'pi', 'model': 'deepseek/deepseek-flash', 'pi': pi_startup,
        }
    roles['role_tree'] = {'coding-team.engineer': {}, 'failed_start': {}}
    roles_file.write_text(yaml.safe_dump(roles))
    task_id = "85"
    task_name = "cleanup-integrated-task"
    _register(commands, root, _task(task_id, task_name))
    _change_status(commands, root, task_id, "ready")
    batch = root / "team-batch.yml"
    batch.write_text(
        yaml.safe_dump(
            {
                "tasks": [
                    {
                        "task_id": task_id,
                        "task_name": task_name,
                        "role": "coding-team.engineer",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    failed_start_aliases: tuple[str, ...] = ()
    if failed_start or terminal_failed_start:
        if pi_startup is not None:
            environment['PI_FIXTURE_UNESTABLISHED'] = '1'
            if pi_crash:
                environment['PI_FIXTURE_STARTUP_FAILURE'] = '1'
        if failed_start:
            environment["FAKE_CODEX_UNSUPPORTED"] = "1"
        else:
            environment.update(FAKE_CODEX_EVENTS="[]", FAKE_CODEX_EXIT_CODE="1")
        if terminal_failed_start:
            failed_batch = yaml.safe_load(batch.read_text())
            failed_batch['tasks'][0]['role'] = 'failed_start'
            batch.write_text(yaml.safe_dump(failed_batch))
        launch_command = [str(commands.runner), "--swarm-input", str(batch)]
        if pi_interrupt:
            ready = tmp_path / 'pi-startup-ready'
            environment['PI_FIXTURE_STARTUP_READY'] = str(ready)
            with subprocess.Popen(launch_command, cwd=root, env=environment, text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) as launching:
                wait_for_file(ready)
                allocation = next((root / '.graphtraj/runner/sessions').iterdir())
                interrupted = run_process(runner_operation(commands, 'interrupt', allocation.name),
                                          cwd=root, env=environment, timeout=15)
                assert interrupted.returncode == 0, interrupted.stdout + interrupted.stderr
                assert yaml.safe_load(interrupted.stdout)['interrupt_status'] == 'interrupted'
                stdout, stderr = launching.communicate(timeout=15)
                failed = subprocess.CompletedProcess(launch_command, launching.returncode, stdout, stderr)
        else:
            failed = run_process(launch_command, cwd=root, env=environment, timeout=15)
        assert failed.returncode == 1
        if terminal_failed_start:
            failed_batch['tasks'][0]['role'] = 'coding-team.engineer'
            batch.write_text(yaml.safe_dump(failed_batch))
        sessions = root / ".graphtraj" / "runner" / "sessions"
        if failed_start:
            assert not sessions.exists() or not list(sessions.iterdir())
            # Preserve coverage for historical allocations from before preflight
            # moved ahead of reservation; new unsupported Runtimes leave none.
            historical = sessions / "85-cleanup_integrated_task-handover0-team_leader@unstarted"
            historical.mkdir(parents=True)
            (historical / "events.jsonl").touch()
            traces = (root / ".graphtraj/state/tasks/85-cleanup-integrated-task"
                      / "teams/1/traces" / historical.name)
            traces.mkdir(parents=True)
            (traces / "events.jsonl").touch()
        failed_start_aliases = tuple(
            directory.name for directory in sessions.iterdir() if directory.is_dir()
        )
        assert failed_start_aliases
        if failed_start:
            environment.pop("FAKE_CODEX_UNSUPPORTED")
        else:
            environment.pop("FAKE_CODEX_EVENTS")
            environment.pop("FAKE_CODEX_EXIT_CODE")
        environment.pop('PI_FIXTURE_UNESTABLISHED', None)
        environment.pop('PI_FIXTURE_STARTUP_READY', None)
        environment.pop('PI_FIXTURE_STARTUP_FAILURE', None)
    environment.update(
        FAKE_CODEX_LIFECYCLE_ACTION="complete-team-round",
        GRAPHTRAJ_AGENT_RUNNER=str(commands.runner),
    )
    launched = run_process(
        [str(commands.runner), "--swarm-input", str(batch)],
        cwd=root,
        env=environment,
        timeout=15,
    )
    assert launched.returncode == 0, launched.stdout + launched.stderr
    alias = yaml.safe_load(launched.stdout)['tasks'][0]['alias']
    wait_for_file(root / '.graphtraj/runner/sessions' / alias / 'execution.yml')
    reported = run_process([str(commands.runner), 'reports', alias], cwd=root, env=environment)
    submission = yaml.safe_load(reported.stdout)['submissions'][-1]
    accepted = run_process([
        str(commands.runner), 'decide-result', '--submission-id', submission['event_id'],
        '--commit', submission['candidate'], '--decision', 'accepted', '--reason', 'Fixture task completed',
        '--evidence-ref', submission['evidence_refs'][0],
    ], cwd=root, env=environment)
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr

    state = root / ".graphtraj" / "state"
    task_directory = state / "tasks" / (task_id + "-" + task_name)
    worktree = worktrees / (task_id + "-" + task_name)
    branch = "agent/" + task_id + "-" + task_name
    status = yaml.safe_load((task_directory / "task.yml").read_text())
    assert status["status"] == "awaiting-integration"
    assert run_process(["git", "status", "--porcelain"], cwd=worktree).stdout == ""

    if integrate:
        integrated = run_process(
            [
                str(commands.product),
                "task",
                "integrate",
                "--task-id",
                task_id,
                "--",
                sys.executable,
                "-c",
                "pass",
            ],
            cwd=root,
            env=environment,
            timeout=15,
        )
        assert integrated.returncode == 0, integrated.stderr
        status = yaml.safe_load((task_directory / "task.yml").read_text())
        assert status["status"] == "integrated"

    return DeliveredTask(
        root=root,
        repository=repository,
        state=state,
        worktree=worktree,
        branch=branch,
        task_id=task_id,
        task_name=task_name,
        task_directory=task_directory,
        environment=environment,
        commands=commands,
        failed_start_aliases=failed_start_aliases,
    )


@pytest.fixture
def integrated_task(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> DeliveredTask:
    return _deliver_task(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
        integrate=True,
    )


def _cleanup(task: DeliveredTask, *arguments: str):
    """Exercise cleanup through the installed CLI in this isolated fixture."""
    return run_process(
        [str(task.commands.runner), "cleanup", "--task-id", task.task_id, *arguments],
        cwd=task.root, env=task.environment, timeout=15,
    )


def _task_mappings(task: DeliveredTask) -> list[Path]:
    sessions = task.root / ".graphtraj" / "runner" / "sessions"
    mappings = []
    for directory in sessions.iterdir():
        mapping_file = directory / "mapping.yml"
        if mapping_file.is_file():
            mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
            if mapping.get("task_id") == task.task_id and "run_id" not in mapping:
                mappings.append(directory)
    return mappings


def _durable_contents(task: DeliveredTask) -> dict[str, bytes]:
    roots = (
        task.task_directory,
        task.state / "batches",
        task.state / "worldline",
    )
    return {
        path.relative_to(task.root).as_posix(): path.read_bytes()
        for root in roots
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def _assert_durable_contents(task: DeliveredTask, before: dict[str, bytes]) -> None:
    """Keep all evidence; only current member references and appended events change."""
    after = _durable_contents(task)
    for name, content in before.items():
        if name.endswith('/team.yml'):
            original = yaml.safe_load(content)
            current = yaml.safe_load(after[name])
            assert {**original, 'members': current['members']} == current
            assert {name: member['role'] for name, member in original['members'].items()} == {
                name: member['role'] for name, member in current['members'].items()
            }
        elif '/worldline/' in name:
            assert after[name].startswith(content)
        else:
            assert after[name] == content


def _append_worldline_reference(task: DeliveredTask, evidence: Path) -> dict:
    event = task.root / "cleanup-evidence.yml"
    event.write_text(
        yaml.safe_dump(
            {
                "event": "cleanup-evidence-recorded",
                "caused_by_event_ids": [],
                "evidence_refs": [evidence.relative_to(task.root).as_posix()],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    appended = run_process(
        [str(task.commands.product), "worldline", "append", "--event-file", str(event)],
        cwd=task.root,
        env=task.environment,
    )
    assert appended.returncode == 0, appended.stderr
    return yaml.safe_load(appended.stdout)


def test_installed_cleanup_uses_only_task_identity_and_preserves_trajectory(
    integrated_task: DeliveredTask,
) -> None:
    task = integrated_task
    help_result = run_process(
        [str(task.commands.runner), "cleanup", "--help"], cwd=task.root
    )
    assert help_result.returncode == 0, help_result.stderr
    assert "--task-id" in help_result.stdout
    assert "--run-id" not in help_result.stdout

    historical_run = task.state / "20260101-historical-delivery-run"
    historical_run.mkdir()
    historical_marker = historical_run / "evidence.md"
    historical_marker.write_text("historical evidence\n", encoding="utf-8")
    durable_before = _durable_contents(task)
    mappings = _task_mappings(task)
    assert mappings
    from agent_swarm.sessions.archive import JsonlSessionStore, SessionArchive, archive_path

    archives = {}
    for directory in mappings:
        mapping = yaml.safe_load((directory / 'mapping.yml').read_text())
        root = task.root / '.graphtraj/swarm'
        path = archive_path(root, SessionArchive(root).native_id('codex', mapping['session']))
        archives[path] = JsonlSessionStore(path).page()

    cleaned = _cleanup(task)

    assert cleaned.returncode == 0, cleaned.stderr
    document = yaml.safe_load(cleaned.stdout)
    assert document["task_id"] == task.task_id
    assert document["cleanup_status"] == "cleaned"
    assert "run_id" not in document
    assert not task.worktree.exists()
    assert run_process(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/" + task.branch],
        cwd=task.repository,
    ).returncode == 1
    # Task completion keeps its stopped members as standby Agents.
    assert all((path / "mapping.yml").exists() for path in mappings)
    _assert_durable_contents(task, durable_before)
    for path, expected in archives.items():
        assert JsonlSessionStore(path).page() == expected
    assert historical_marker.read_text(encoding="utf-8") == "historical evidence\n"

    repeated = _cleanup(task)

    assert repeated.returncode == 0, repeated.stderr
    repeated_document = yaml.safe_load(repeated.stdout)
    assert repeated_document["cleanup_status"] == "already-cleaned"
    assert "run_id" not in repeated_document
    _assert_durable_contents(task, durable_before)
    assert historical_marker.read_text(encoding="utf-8") == "historical evidence\n"


@pytest.mark.parametrize("residual", [
    "unchanged", "changed-branch", "registered", "dirty-path", "unmerged-dev",
])
def test_installed_cleanup_retries_reference_failure(
    integrated_task: DeliveredTask, residual: str,
) -> None:
    """A real Git lock failure leaves a retryable, exactly attributed branch."""
    task = integrated_task
    durable_before = _durable_contents(task)
    sessions = task.root / ".graphtraj/runner/sessions"
    commit = run_process(["git", "rev-parse", task.branch], cwd=task.repository).stdout.strip()
    ref_path = run_process(
        ["git", "rev-parse", "--git-path", "refs/heads/" + task.branch],
        cwd=task.repository,
    ).stdout.strip()
    lock = Path(str(task.repository / ref_path) + ".lock")
    lock.write_text("controlled cleanup lock\n")
    try:
        failed = _cleanup(task)
        document = yaml.safe_load(failed.stdout)
        assert failed.returncode == 1, failed.stdout + failed.stderr
        assert document["error"]["code"] == "cleanup-failed"
        assert document["evidence"]["completed_actions"] == ["worktree-removed"]
        assert "exited 128" in document["evidence"]["cause"]["message"]
        assert "lock file already exists" in document["evidence"]["cause"]["message"]
        assert not task.worktree.exists()
        assert all((path / "mapping.yml").exists() for path in _task_mappings(task))
        assert run_process(["git", "rev-parse", task.branch], cwd=task.repository).stdout.strip() == commit
        remaining_sessions = sorted(path.name for path in sessions.iterdir())
        retired_before = {path: path.read_bytes() for path in sessions.rglob("session.yml")}
        assert retired_before

        # Retry while the real fault persists, without retiring any member.
        retry_failed = yaml.safe_load(_cleanup(task).stdout)
        assert retry_failed["error"]["code"] == "cleanup-failed"
        assert retry_failed["evidence"]["completed_actions"] == []
    finally:
        lock.unlink()

    if residual == "changed-branch":
        # Even another already-merged commit is not this Task's accepted ref.
        changed = run_process(["git", "update-ref", "refs/heads/" + task.branch, commit + "^"],
                              cwd=task.repository)
        assert changed.returncode == 0, changed.stderr
    elif residual == "registered":
        registered = run_process(["git", "worktree", "add", str(task.root / "foreign"), task.branch],
                                 cwd=task.repository)
        assert registered.returncode == 0, registered.stderr
    elif residual == "dirty-path":
        task.worktree.mkdir()
        (task.worktree / "user-data").write_text("preserve me\n")
    elif residual == "unmerged-dev":
        run_process(["git", "update-ref", "refs/heads/dev", commit + "^"],
                    cwd=task.repository).check_returncode()

    retried = _cleanup(task)
    result = yaml.safe_load(retried.stdout)
    if residual == "unchanged":
        assert retried.returncode == 0, retried.stdout + retried.stderr
        assert result["cleanup_status"] == "cleaned"
        assert result["aliases_removed"] == []
        assert result["evidence"]["task_commit"] == commit
        repeated = _cleanup(task)
        assert repeated.returncode == 0, repeated.stdout + repeated.stderr
        assert yaml.safe_load(repeated.stdout)["cleanup_status"] == "already-cleaned"
    else:
        assert retried.returncode == 1, retried.stdout + retried.stderr
        assert result["error"]["code"] == (
            "cleanup-not-integrated" if residual == "unmerged-dev"
            else "cleanup-ownership-mismatch"
        )
        assert run_process(["git", "show-ref", "--verify", "refs/heads/" + task.branch],
                           cwd=task.repository).returncode == 0
        if residual == "dirty-path":
            assert (task.worktree / "user-data").read_text() == "preserve me\n"
    assert sorted(path.name for path in sessions.iterdir()) == remaining_sessions
    assert {path: path.read_bytes() for path in retired_before} == retired_before
    _assert_durable_contents(task, durable_before)


def test_installed_cleanup_allows_missing_worldline_evidence(
    integrated_task: DeliveredTask,
) -> None:
    task = integrated_task
    mappings = _task_mappings(task)
    event = _append_worldline_reference(task, mappings[0] / "mapping.yml")

    result = _cleanup(task)

    assert result.returncode == 0, result.stderr
    document = yaml.safe_load(result.stdout)
    assert document["cleanup_status"] == "cleaned"
    assert not task.worktree.exists()
    assert all((path / "mapping.yml").exists() for path in mappings)
    read_after_cleanup = run_process(
        [str(task.commands.product), "worldline", "read"],
        cwd=task.root,
        env=task.environment,
    )
    assert read_after_cleanup.returncode == 0, read_after_cleanup.stderr
    assert event in [json.loads(line) for line in read_after_cleanup.stdout.splitlines()]
    new_evidence = task.root / "new-evidence.md"
    new_evidence.write_text("new evidence\n", encoding="utf-8")
    appended = _append_worldline_reference(task, new_evidence)
    assert appended in [
        json.loads(line)
        for line in run_process(
            [str(task.commands.product), "worldline", "read"],
            cwd=task.root,
            env=task.environment,
        ).stdout.splitlines()
    ]


def test_installed_cleanup_removes_historical_preflight_allocation_after_integration(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    task = _deliver_task(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
        integrate=True,
        failed_start=True,
    )
    sessions = task.root / ".graphtraj" / "runner" / "sessions"
    failed_sessions = [sessions / alias for alias in task.failed_start_aliases]
    assert len(failed_sessions) == 1
    failed_session = failed_sessions[0]
    events = failed_session / "events.jsonl"
    trace = (
        task.task_directory
        / "teams"
        / "1"
        / "traces"
        / failed_session.name
        / "events.jsonl"
    )
    assert not (failed_session / "mapping.yml").exists()
    # Historical preflight residue has empty Session and Trace entries.
    assert events.is_file() and events.read_bytes() == b""
    assert trace.is_file() and not trace.is_symlink()
    assert trace.read_bytes() == b""
    durable_before = _durable_contents(task)
    mappings = _task_mappings(task)

    cleaned = _cleanup(task)

    assert cleaned.returncode == 0, cleaned.stderr
    document = yaml.safe_load(cleaned.stdout)
    assert document["cleanup_status"] == "cleaned"
    assert set(task.failed_start_aliases) <= set(document["aliases_removed"])
    assert not task.worktree.exists()
    assert run_process(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/" + task.branch],
        cwd=task.repository,
    ).returncode == 1
    assert all(not session.exists() for session in failed_sessions)
    assert all((mapping / "mapping.yml").exists() for mapping in mappings
               if mapping not in failed_sessions)
    assert trace.read_bytes() == b""
    _assert_durable_contents(task, durable_before)

    repeated = _cleanup(task)

    assert repeated.returncode == 0, repeated.stderr
    assert yaml.safe_load(repeated.stdout)["cleanup_status"] == "already-cleaned"


@pytest.mark.parametrize("failure_case", ("confirmed", "uncertain", "foreign", "missing"))
def test_installed_cleanup_retains_a_terminal_unmapped_startup_failure_after_integration(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    failure_case: str,
) -> None:
    """Cleanup reports retained proof, refusing uncertain or foreign allocations."""
    task = _deliver_task(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
        integrate=True,
        terminal_failed_start=True,
    )
    sessions = task.root / ".graphtraj" / "runner" / "sessions"
    failed_sessions = [sessions / alias for alias in task.failed_start_aliases]
    assert len(failed_sessions) == 1
    failed_session = failed_sessions[0]
    trace = (
        task.task_directory
        / "teams"
        / "1"
        / "traces"
        / failed_session.name
        / "events.jsonl"
    )
    launch = yaml.safe_load((failed_session / "launch.yml").read_text(encoding="utf-8"))
    failure = yaml.safe_load(
        (failed_session / "launch-error.yml").read_text(encoding="utf-8")
    )
    assert not (failed_session / "mapping.yml").exists()
    assert launch["mapping"]["alias"] == failed_session.name
    assert launch["mapping"]["task_id"] == task.task_id
    assert Path(launch["mapping"]["retained_batch_file"]).is_file()
    assert failure["terminal_confirmed"] is True
    assert (failed_session / "worker-stderr.log").is_file()
    # The Runner keeps its own records in the Session directory, while this
    # Runtime failure left the Trace entry empty and unlinked.
    session_records = (failed_session / "events.jsonl").read_text(encoding="utf-8")
    assert '"type":"runtime"' in session_records
    assert '"type": "runner-execution-start"' in session_records
    assert trace.is_file() and not trace.is_symlink()
    assert trace.read_bytes() == b""
    if failure_case == "uncertain":
        failure["terminal_confirmed"] = False
        failure["message"] = "private startup diagnostic fixture-secret"
        failure["diagnostic"] = {"process": {"runtime_pid": 123, "secret": "fixture-secret"}}
        (failed_session / "launch-error.yml").write_text(yaml.safe_dump(failure))
        (failed_session / "pi-process.json").write_text(json.dumps({
            "policy": "fixture-secret", "argv": ["pi", "--session",
            str(trace.with_suffix(".pi") / "session.jsonl"), "--private", "fixture-secret"],
        }))
    elif failure_case == "foreign":
        launch["mapping"]["task_id"] = "another-task"
        (failed_session / "launch.yml").write_text(yaml.safe_dump(launch))
    elif failure_case == "missing":
        # Retained launches can predate any Worker ownership or failure record.
        # Their launch binding remains inspectable, but cannot certify a stop.
        (failed_session / "launch-error.yml").unlink()
        (failed_session / "heartbeat.yml").unlink()
    durable_before = _durable_contents(task)
    allocation_before = {path.name: path.read_bytes() for path in failed_session.iterdir()
                         if path.is_file() and not path.is_symlink()}

    cleaned = _cleanup(task)

    if failure_case != "confirmed":
        assert cleaned.returncode == 1, cleaned.stdout + cleaned.stderr
        document = yaml.safe_load(cleaned.stdout)
        assert document["error"]["code"] == "cleanup-ownership-mismatch"
        proof = document["evidence"]["allocation_failures"][failed_session.name]
        assert {key: proof[key] for key in (
            "trace_valid", "launch_matches_task", "terminal_confirmed",
        )} == {
            "trace_valid": True,
            "launch_matches_task": failure_case != "foreign",
            "terminal_confirmed": None if failure_case == "missing" else failure_case != "uncertain",
        }
        if failure_case == "uncertain":
            artifacts = proof["artifacts"]
            relative = failed_session.relative_to(task.root).as_posix()
            assert artifacts[relative + "/mapping.yml"] == {"status": "absent"}
            assert artifacts[relative + "/launch.yml"]["identity_fields"] == []
            assert artifacts[relative + "/heartbeat.yml"]["identity_fields"] == ["worker_pid"]
            assert artifacts[trace.relative_to(task.root).as_posix()]["bytes"] == 0
            failure_info = artifacts[relative + "/launch-error.yml"]
            assert failure_info["field_types"] == {
                "code": "str", "message": "str", "diagnostic": "dict", "terminal_confirmed": "bool",
            }
            assert failure_info["other_field_count"] == 0
            process_info = artifacts[relative + "/pi-process.json"]
            assert process_info["field_types"] == {"policy": "str", "argv": "list"}
            assert process_info["other_field_count"] == 0
            assert process_info["argv_strings"] is True
            assert process_info["requested_session_matches_trace"] is True
        elif failure_case == "missing":
            artifacts = proof["artifacts"]
            relative = failed_session.relative_to(task.root).as_posix()
            for name in ("mapping.yml", "session.yml", "heartbeat.yml", "launch-error.yml"):
                assert artifacts[relative + "/" + name] == {"status": "absent"}
            assert artifacts[relative + "/launch.yml"]["status"] == "file"
        else:
            assert "artifacts" not in proof
        assert "fixture-secret" not in cleaned.stdout
        refused_stop = run_process(runner_operation(task.commands, 'interrupt', failed_session.name),
                                   cwd=task.root, env=task.environment)
        assert refused_stop.returncode == 1, refused_stop.stdout + refused_stop.stderr
        assert task.worktree.is_dir()
        assert {path.name: path.read_bytes() for path in failed_session.iterdir()
                if path.is_file() and not path.is_symlink()} == allocation_before
        assert _durable_contents(task) == durable_before
        return

    assert cleaned.returncode == 0, cleaned.stderr
    document = yaml.safe_load(cleaned.stdout)
    assert document["cleanup_status"] == "cleaned"
    assert set(task.failed_start_aliases) <= set(document["aliases_removed"])
    assert all(not session.exists() for session in failed_sessions)
    _assert_durable_contents(task, durable_before)


@pytest.mark.parametrize('interrupt_startup', (False, True))
def test_pi_failed_creation_retains_owned_process_and_native_stop(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    pi_environment: dict,
    interrupt_startup: bool,
) -> None:
    """Public Runner retains pre-Session process ownership and verified native shutdown."""
    task = _deliver_task(installed_commands, temporary_git_repository, fake_codex, tmp_path,
                             integrate=True, terminal_failed_start=True, pi_startup=pi_environment,
                             pi_interrupt=interrupt_startup)
    alias = task.failed_start_aliases[0]
    directory = task.root / '.graphtraj/runner/sessions' / alias
    heartbeat = yaml.safe_load((directory / 'heartbeat.yml').read_text())
    failure = yaml.safe_load((directory / 'launch-error.yml').read_text())
    assert heartbeat['runtime_pid'] > 0
    assert heartbeat['execution_id']
    assert heartbeat['control_directory']
    # The outcome also carries Pi's structured termination facts (291882a).
    outcome = dict(heartbeat['process_outcome'])
    outcome.pop('runtime_execution_id')
    assert outcome == {'terminal_confirmed': True, 'runtime_exit_code': 0, 'native_idle_confirmed': True,
                       **PI_STARTUP_FACTS}
    assert failure['code'] == ('RUNTIME_EXECUTION_INTERRUPTED' if interrupt_startup else 'RUNTIME_SESSION_MISSING')
    assert failure['terminal_confirmed'] is True
    assert not (directory / 'mapping.yml').exists()
    assert not (directory / 'session.yml').exists()
    original_failure = (directory / 'launch-error.yml').read_bytes()
    stopped = run_process(runner_operation(task.commands, 'interrupt', alias),
                          cwd=task.root, env=task.environment)
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr
    assert yaml.safe_load(stopped.stdout)['interrupt_status'] == 'stopped'
    cleaned = _cleanup(task)
    assert cleaned.returncode == 0, cleaned.stdout + cleaned.stderr
    retained = task.task_directory / 'teams/1/traces' / alias / 'runner'
    assert (retained / 'launch-error.yml').read_bytes() == original_failure
    assert not task.worktree.exists()


def test_pi_crashed_creation_retains_binding_without_certifying_tool_stop(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    pi_environment: dict,
) -> None:
    """A reaped transport without native stop proof remains unconfirmed."""
    task = _deliver_task(installed_commands, temporary_git_repository, fake_codex, tmp_path,
                             integrate=True, terminal_failed_start=True, pi_startup=pi_environment,
                             pi_crash=True)
    alias = task.failed_start_aliases[0]
    directory = task.root / '.graphtraj/runner/sessions' / alias
    heartbeat = yaml.safe_load((directory / 'heartbeat.yml').read_text())
    assert heartbeat['runtime_pid'] > 0
    outcome = dict(heartbeat['process_outcome'])
    outcome.pop('runtime_execution_id')
    assert outcome == {'terminal_confirmed': False, 'runtime_exit_code': 71, 'native_idle_confirmed': False,
                       **PI_STARTUP_FACTS}
    original_failure = (directory / 'launch-error.yml').read_bytes()
    assert yaml.safe_load(original_failure)['terminal_confirmed'] is False
    stopped = run_process(runner_operation(task.commands, 'interrupt', alias),
                          cwd=task.root, env=task.environment)
    assert stopped.returncode == 1, stopped.stdout + stopped.stderr
    cleaned = _cleanup(task)
    assert cleaned.returncode == 1, cleaned.stdout + cleaned.stderr
    assert yaml.safe_load(cleaned.stdout)['error']['code'] == 'cleanup-ownership-mismatch'
    assert (directory / 'launch-error.yml').read_bytes() == original_failure
    assert task.worktree.is_dir()


def test_installed_cleanup_refuses_an_unattributed_session_record_without_partial_cleanup(
    integrated_task: DeliveredTask,
) -> None:
    task = integrated_task
    sessions = task.root / ".graphtraj" / "runner" / "sessions"
    record = sessions / (task.task_id + "-" + task.task_name + "@e99")
    record.mkdir()
    (record / "events.jsonl").write_text(
        '{"type":"runtime","runtime":"codex"}\n', encoding="utf-8"
    )
    trace = (
        task.task_directory
        / "teams"
        / "1"
        / "traces"
        / record.name
        / "events.jsonl"
    )
    trace.parent.mkdir()
    trace.touch()
    mappings = _task_mappings(task)

    result = _cleanup(task)

    assert result.returncode == 1
    document = yaml.safe_load(result.stdout)
    assert document["cleanup_status"] == "refused"
    assert document["error"]["code"] == "cleanup-ownership-mismatch"
    assert task.worktree.is_dir()
    assert record.is_dir()
    assert all(path.is_dir() for path in mappings)
    assert run_process(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/" + task.branch],
        cwd=task.repository,
    ).returncode == 0


def test_installed_cleanup_refuses_a_task_without_validated_integration(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    task = _deliver_task(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
        integrate=False,
    )
    mappings = _task_mappings(task)

    result = _cleanup(task)

    assert result.returncode == 1
    document = yaml.safe_load(result.stdout)
    assert document["cleanup_status"] == "refused"
    assert document["error"]["code"] == "cleanup-not-integrated"
    assert task.worktree.is_dir()
    assert all(path.is_dir() for path in mappings)
    assert run_process(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/" + task.branch],
        cwd=task.repository,
    ).returncode == 0


def test_installed_cleanup_refuses_a_branch_that_is_no_longer_integrated(
    integrated_task: DeliveredTask,
) -> None:
    task = integrated_task
    later = task.worktree / "later-work.txt"
    later.write_text("not part of the validated candidate\n", encoding="utf-8")
    run_process(["git", "add", later.name], cwd=task.worktree).check_returncode()
    run_process(
        ["git", "commit", "-m", "Later Task work"], cwd=task.worktree
    ).check_returncode()
    mappings = _task_mappings(task)

    result = _cleanup(task)

    assert result.returncode == 1
    document = yaml.safe_load(result.stdout)
    assert document["cleanup_status"] == "refused"
    assert document["error"]["code"] == "cleanup-not-integrated"
    assert task.worktree.is_dir()
    assert all(path.is_dir() for path in mappings)
    assert run_process(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/" + task.branch],
        cwd=task.repository,
    ).returncode == 0


def test_installed_cleanup_refuses_a_dirty_task_without_partial_cleanup(
    integrated_task: DeliveredTask,
) -> None:
    task = integrated_task
    dirty = task.worktree / "unfinished.txt"
    dirty.write_text("uncommitted work\n", encoding="utf-8")
    mappings = _task_mappings(task)

    result = _cleanup(task)

    assert result.returncode == 1
    document = yaml.safe_load(result.stdout)
    assert document["cleanup_status"] == "refused"
    assert document["error"]["code"] == "cleanup-dirty"
    assert dirty.read_text(encoding="utf-8") == "uncommitted work\n"
    assert all(path.is_dir() for path in mappings)
    assert run_process(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/" + task.branch],
        cwd=task.repository,
    ).returncode == 0


def test_installed_cleanup_refuses_an_executing_task_agent_without_partial_cleanup(
    integrated_task: DeliveredTask,
) -> None:
    task = integrated_task
    mapping_directory = _task_mappings(task)[0]
    mapping_file = mapping_directory / "mapping.yml"
    mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
    agent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    mapping["worker_pid"] = agent.pid
    mapping["runtime_pid"] = agent.pid
    mapping_file.write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8")
    try:
        result = _cleanup(task)
    finally:
        agent.terminate()
        agent.wait(timeout=5)

    assert result.returncode == 1
    document = yaml.safe_load(result.stdout)
    assert document["cleanup_status"] == "refused"
    assert document["error"]["code"] == "worktree-busy"
    assert task.worktree.is_dir()
    assert mapping_directory.is_dir()
    assert run_process(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/" + task.branch],
        cwd=task.repository,
    ).returncode == 0


@pytest.mark.parametrize("change", ("worktree", "branch"))
def test_installed_cleanup_refuses_noncanonical_task_resources_without_partial_cleanup(
    change: str,
    integrated_task: DeliveredTask,
) -> None:
    task = integrated_task
    mappings = _task_mappings(task)
    if change == "worktree":
        moved = task.worktree.with_name("moved-by-operator")
        run_process(
            ["git", "worktree", "move", str(task.worktree), str(moved)],
            cwd=task.repository,
        ).check_returncode()
        retained_worktree = moved
    else:
        run_process(
            ["git", "switch", "-c", "operator-cleanup-branch"],
            cwd=task.worktree,
        ).check_returncode()
        retained_worktree = task.worktree

    result = _cleanup(task)

    assert result.returncode == 1
    document = yaml.safe_load(result.stdout)
    assert document["cleanup_status"] == "refused"
    assert document["error"]["code"] == "cleanup-ownership-mismatch"
    assert retained_worktree.is_dir()
    assert all(path.is_dir() for path in mappings)
    assert run_process(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/" + task.branch],
        cwd=task.repository,
    ).returncode == 0


def test_installed_cleanup_removes_an_integrated_worktree_on_its_named_branch_and_keeps_both(
    integrated_task: DeliveredTask,
) -> None:
    """A Worktree moved to an adoption branch is removed only by naming that branch."""
    task = integrated_task
    mappings = _task_mappings(task)

    def branch_exists(name: str) -> bool:
        return run_process(["git", "show-ref", "--verify", "--quiet", "refs/heads/" + name],
                           cwd=task.repository).returncode == 0

    def refusal(*arguments: str) -> str:
        result = _cleanup(task, *arguments)
        assert result.returncode == 1, result.stdout
        assert task.worktree.is_dir()
        return yaml.safe_load(result.stdout)["error"]["code"]

    run_process(["git", "switch", "-c", "older-line", "HEAD~1"], cwd=task.worktree).check_returncode()
    assert refusal("--worktree-branch", "older-line") == "cleanup-ownership-mismatch"
    run_process(["git", "switch", "-c", "adoption-line", task.branch],
                cwd=task.worktree).check_returncode()
    assert refusal() == "cleanup-ownership-mismatch"
    assert refusal("--worktree-branch", "older-line") == "cleanup-ownership-mismatch"
    dirty = task.worktree / "unfinished.txt"
    dirty.write_text("uncommitted work\n", encoding="utf-8")
    assert refusal("--worktree-branch", "adoption-line") == "cleanup-dirty"
    dirty.unlink()

    cleaned = _cleanup(task, "--worktree-branch", "adoption-line")

    assert cleaned.returncode == 0, cleaned.stderr
    document = yaml.safe_load(cleaned.stdout)
    assert document["cleanup_status"] == "cleaned"
    assert document["evidence"]["branches_kept"] == [task.branch, "adoption-line"]
    assert not task.worktree.exists()
    assert branch_exists(task.branch) and branch_exists("adoption-line")
    assert all((path / "mapping.yml").exists() for path in mappings)
    repeated = _cleanup(task, "--worktree-branch", "adoption-line")
    assert yaml.safe_load(repeated.stdout)["cleanup_status"] == "already-cleaned"


def test_cleanup_preserves_shared_worktree_with_another_task_execution(
    integrated_task: DeliveredTask,
) -> None:
    """An unrelated active mapping using the same Worktree prevents deletion."""
    task = integrated_task
    original = _task_mappings(task)[0]
    mapping = yaml.safe_load((original / 'mapping.yml').read_text())
    alias = '86-other_task-handover0-researcher@shared'
    foreign = original.parent / alias
    foreign.mkdir()
    mapping.update(alias=alias, task_id='86', parent=None,
                   worktree_path=str(task.worktree), worker_pid=os.getpid(), runtime_pid=os.getpid())
    (foreign / 'mapping.yml').write_text(yaml.safe_dump(mapping))
    before = (foreign / 'mapping.yml').read_bytes()

    result = _cleanup(task)

    assert result.returncode == 1, result.stdout + result.stderr
    assert yaml.safe_load(result.stdout)['error']['code'] == 'worktree-busy'
    assert task.worktree.is_dir()
    assert (foreign / 'mapping.yml').read_bytes() == before
    assert not (foreign / 'stop.yml').exists()
    assert all((directory / 'mapping.yml').exists() for directory in _task_mappings(task))
