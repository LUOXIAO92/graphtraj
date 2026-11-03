"""A Task created by graph revision dispatches; a launch that crashed reads as stopped (442)."""

import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, run_process, runner_operation
from runner_fixtures import configure_harness
from test_agent_runner_cleanup import DeliveredTask, _cleanup, _deliver_task, _task_mappings
from test_task_graph import _register, _run, _revised, _task, _write


# The tail the Worker wrote when member registration raised outside its handled errors.
CRASH = (
    "Traceback (most recent call last):\n"
    '  File "runner_worker.py", line 450, in _register_created_member\n'
    "    predecessor = next(\n"
    "StopIteration\n"
)


def test_a_task_created_by_graph_revision_dispatches_without_a_status_change(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """Member registration finds the revision event that created the Task."""
    root, _, _, env = configure_harness(installed_commands, temporary_git_repository, fake_codex, tmp_path)
    _register(installed_commands, root, _task("1", "earlier-task"))
    (root / "revision-evidence.md").write_text("Main split the work into a new Task.\n", encoding="utf-8")
    revision = _write(root / "revision.yml", {
        "product_preserving": True,
        "caused_by_event_ids": [],
        "evidence_refs": ["revision-evidence.md"],
        "tasks": [_revised(_task("148", "revised-task"), None)],
    })
    revised = _run(installed_commands, root, "revise", "--revision-file", str(revision))
    assert revised.returncode == 0, revised.stderr

    batch = root / "batch.yml"
    batch.write_text('tasks:\n  - task_id: "148"\n    task_name: revised-task\n    role: coding-team.team-leader\n')
    launched = run_process(
        [str(installed_commands.runner), "--swarm-input", str(batch)], cwd=root, env=env, timeout=45,
    )

    assert launched.returncode == 0, launched.stdout + launched.stderr
    alias = yaml.safe_load(launched.stdout)["tasks"][0]["alias"]
    directory = root / ".graphtraj/runner/sessions" / alias
    assert "StopIteration" not in (directory / "worker-stderr.log").read_text()
    team = yaml.safe_load((root / ".graphtraj/state/tasks/148-revised-task/teams/1/team.yml").read_text())
    assert [member["session_ref"] for member in team["members"].values()] == [alias]


def _crash_after_creation(directory: Path, worker_pid: int | None = None) -> dict:
    """Reshape an ended Session into the record a Worker leaves when it crashes in record_created.

    That Worker had written mapping.yml without ``execution_id`` and its heartbeat
    with the execution and the confirmed native process end, then died before any
    terminal record. A later abnormal response had already claimed it and stopped it.
    """
    mapping = yaml.safe_load((directory / "mapping.yml").read_text())
    execution_id = mapping.pop("execution_id")
    mapping.pop("last_outcome", None)
    if worker_pid is not None:
        mapping["worker_pid"] = mapping["runtime_pid"] = worker_pid
    (directory / "mapping.yml").write_text(yaml.safe_dump(mapping, sort_keys=False))
    (directory / "execution.yml").unlink()
    for receipt in directory.glob("terminal-confirmation-*.yml"):
        receipt.unlink()
    (directory / "heartbeat.yml").write_text(yaml.safe_dump({
        "alias": mapping["alias"], "worker_pid": mapping["worker_pid"], "runtime_pid": mapping["runtime_pid"],
        "execution_id": execution_id, "control_directory": mapping["control_directory"],
        "process_outcome": {"terminal_confirmed": True, "runtime_exit_code": 143},
        "updated_at": time.time() - 60,
    }))
    (directory / "worker-stderr.log").write_text(CRASH)
    (directory / "stop.yml").write_text(yaml.safe_dump({"alias": mapping["alias"]}))
    (directory / "abnormal-response.yml").write_text('{"alias": "%s", "at": 1}\n' % mapping["alias"])
    return mapping


def _operation(task: DeliveredTask, *arguments: str) -> subprocess.CompletedProcess:
    return run_process(runner_operation(task.commands, *arguments), cwd=task.root, env=task.environment, timeout=60)


@pytest.fixture
def delivered_task(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> DeliveredTask:
    return _deliver_task(installed_commands, temporary_git_repository, fake_codex, tmp_path, integrate=False)


@pytest.fixture
def integrated_task(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> DeliveredTask:
    return _deliver_task(installed_commands, temporary_git_repository, fake_codex, tmp_path, integrate=True)


def test_a_crashed_launch_reads_and_interrupts_as_stopped_and_keeps_its_cause(delivered_task: DeliveredTask) -> None:
    """Status and interrupt answer normally once the Worker and native process are gone."""
    directory = _task_mappings(delivered_task)[0]
    mapping = _crash_after_creation(directory)
    alias = mapping["alias"]

    status = _operation(delivered_task, "status", alias)
    assert status.returncode == 0, status.stdout + status.stderr
    document = yaml.safe_load(status.stdout)["aliases"][0]
    assert document["activity"] == "idle"
    assert document["last_outcome"] == "runtime-error"
    assert "StopIteration" in document["crash"]["message"]

    interrupted = _operation(delivered_task, "interrupt", alias)
    assert interrupted.returncode == 0, interrupted.stdout + interrupted.stderr
    stopped = yaml.safe_load(interrupted.stdout)
    assert stopped["interrupt_status"] == "interrupted"
    assert [(item["alias"], item["interrupt_status"]) for item in stopped["members"]] == [(alias, "stopped")]

    # The crash cause stays where the Worker left it.
    assert (directory / "worker-stderr.log").read_text() == CRASH
    assert "execution_id" not in yaml.safe_load((directory / "mapping.yml").read_text())

    retired = _operation(delivered_task, "retire", alias)
    assert retired.returncode == 0, retired.stdout + retired.stderr
    assert yaml.safe_load(retired.stdout)["retire_status"] == "retired"


def test_a_crashed_launch_whose_worker_still_holds_ownership_is_not_stopped(delivered_task: DeliveredTask) -> None:
    """The heartbeat's terminal flag alone does not certify the end of a live owner."""
    directory = _task_mappings(delivered_task)[0]
    ready = directory.parent.parent / "owner-ready"
    owner = subprocess.Popen([sys.executable, "-c", (
        "import fcntl, os, sys, time; from pathlib import Path\n"
        "d = Path(sys.argv[1]); s = open(d / f'owner-{os.getpid()}.lock', 'a+b')\n"
        "fcntl.flock(s, fcntl.LOCK_EX); Path(sys.argv[2]).touch(); time.sleep(60)\n"
    ), str(directory), str(ready)])
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        mapping = _crash_after_creation(directory, owner.pid)
        status = _operation(delivered_task, "status", mapping["alias"])
        document = yaml.safe_load(status.stdout)["aliases"][0]
        assert document.get("activity") != "idle", status.stdout
    finally:
        owner.terminate()
        owner.wait(timeout=5)


def test_cleanup_treats_a_crashed_launch_as_stopped(integrated_task: DeliveredTask) -> None:
    """An integrated Task whose crashed launch is confirmed ended can be cleaned up."""
    directory = _task_mappings(integrated_task)[0]
    _crash_after_creation(directory)

    result = _cleanup(integrated_task)

    assert result.returncode == 0, result.stdout + result.stderr
    assert yaml.safe_load(result.stdout)["cleanup_status"] == "cleaned"
    assert not integrated_task.worktree.exists()
