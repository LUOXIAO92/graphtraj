"""Batch launch application service for Agent Runner."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

from .codex_adapter import CodexAdapterError, CodexRole, resolve_codex_role
from .runner_batch import prepare_evidence, read_batch, retain_batch
from .runner_io import (
    ActiveTurnBusyError,
    ActiveTurnReservationError,
    active_turn_key,
    confirm_alias_mapping_durable,
    release_active_turn,
    reserve_active_turn,
    write_yaml_durably,
)
from .runner_models import LaunchResponse, Project, RunnerError, Task
from .runner_process import OPERATION_TIMEOUT_SECONDS, stop_worker
from .runner_project import (
    discover_project,
    preflight_worktree,
    provision_worktree,
)


ROLE_ALIAS = {
    "engineer-junior": "j",
    "engineer-senior": "s",
    "engineer-expert": "e",
}
LAUNCH_TIMEOUT_SECONDS = OPERATION_TIMEOUT_SECONDS


@dataclass
class _TaskLaunchPlan:
    task: Task
    binding: str
    branch: str
    worktree: Path
    active_turn_key: Optional[str] = None


def launch_batch(batch_file: Path, cwd: Path) -> LaunchResponse:
    """Preflight and independently launch the exact supplied batch."""

    project = discover_project(cwd)
    batch = read_batch(batch_file, cwd, project.role_bindings)
    launch_plans = []
    for task in batch.tasks:
        branch, worktree = _task_coordinates(project, batch.run_id, task)
        launch_plans.append(
            _TaskLaunchPlan(
                task=task,
                binding=project.role_bindings[task.role],
                branch=branch,
                worktree=worktree,
            )
        )
    _preflight_plan_collisions(project, launch_plans)
    for plan in launch_plans:
        _resolve_role(project.integration_worktree, plan.binding)
        exists = preflight_worktree(
            project,
            plan.task,
            plan.branch,
            plan.worktree,
        )
        if exists:
            _resolve_role(plan.worktree, plan.binding)

    try:
        for plan in launch_plans:
            plan.active_turn_key = _reserve_active_turn(
                project, batch.run_id, plan.task, plan.worktree
            )
        retained_batch = retain_batch(project.state_directory, batch)
    except RunnerError:
        for plan in launch_plans:
            if plan.active_turn_key is not None:
                release_active_turn(
                    project.common_directory / "agent-runner",
                    plan.active_turn_key,
                )
        raise

    results = []
    succeeded = True
    for plan in launch_plans:
        result = _launch_task(project, batch.run_id, plan)
        results.append(result)
        if result["launch_status"] != "launched":
            succeeded = False

    return LaunchResponse(
        document={
            "run_id": batch.run_id,
            "retained_batch_file": str(retained_batch),
            "tasks": results,
        },
        succeeded=succeeded,
    )


def _launch_task(
    project: Project,
    run_id: str,
    plan: _TaskLaunchPlan,
) -> Dict[str, Any]:
    """Attempt one preflighted task without affecting later attempts."""

    active_turn_key = plan.active_turn_key
    if active_turn_key is None:
        raise AssertionError("launch task was not reserved")
    task = plan.task
    result = {
        "ticket_id": task.ticket_id,
        "ticket_name": task.ticket_name,
        "role": task.role,
        "worktree_path": str(plan.worktree),
        "ticket_file": str(task.ticket_file),
    }

    mapping: Optional[Dict[str, Any]] = None
    try:
        evidence = prepare_evidence(project.state_directory, run_id, task)
        provision_worktree(project, task, plan.branch, plan.worktree)
        _ensure_scoped_scratch(plan.worktree, evidence)
        role = _resolve_role(plan.worktree, plan.binding)
        alias, mapping = _start_turn(
            project=project,
            run_id=run_id,
            task=task,
            role=role,
            branch=plan.branch,
            worktree=plan.worktree,
            evidence=evidence,
            active_turn_key=active_turn_key,
        )
        _write_metadata(
            evidence=evidence,
            run_id=run_id,
            task=task,
            alias=alias,
            session=mapping["session"],
            branch=plan.branch,
            worktree=plan.worktree,
        )
    except RunnerError as error:
        release_reservation = error.release_reservation
        if mapping is not None:
            worker_pid = mapping.get("worker_pid")
            if isinstance(worker_pid, int):
                stop_worker(worker_pid)
            release_reservation = False
        if release_reservation:
            release_active_turn(
                project.common_directory / "agent-runner", active_turn_key
            )
        result["launch_status"] = "failed"
        result["error"] = error.as_document()
        return _ordered_task_result(result)

    result.update(
        {
            "launch_status": "launched",
            "alias": alias,
            "session": mapping["session"],
        }
    )
    return _ordered_task_result(result)


def _task_coordinates(
    project: Project, run_id: str, task: Task
) -> Tuple[str, Path]:
    worktree = (
        project.worktree_root / "runs" / run_id / task.stem
    ).resolve()
    branch = "agent/{0}/{1}".format(run_id, task.stem)
    return branch, worktree


def _preflight_plan_collisions(
    project: Project, launch_plans: list[_TaskLaunchPlan]
) -> None:
    case_insensitive = _filesystem_is_case_insensitive(
        project.integration_worktree
    )
    worktrees = set()
    for plan in launch_plans:
        key = str(plan.worktree)
        if case_insensitive:
            key = key.casefold()
        if key in worktrees:
            raise RunnerError(
                "WORKTREE_CONFLICT",
                "Two tasks derive the same Ticket Worktree path.",
            )
        worktrees.add(key)


def _filesystem_is_case_insensitive(existing_path: Path) -> bool:
    alternate = existing_path.with_name(existing_path.name.swapcase())
    try:
        return alternate.samefile(existing_path)
    except OSError:
        return False


def _ordered_task_result(result: Dict[str, Any]) -> Dict[str, Any]:
    fields = [
        "ticket_id",
        "ticket_name",
        "role",
        "launch_status",
        "worktree_path",
        "ticket_file",
    ]
    if result["launch_status"] == "launched":
        fields.extend(("alias", "session"))
    else:
        fields.append("error")
    return {key: result[key] for key in fields}


def _reserve_active_turn(
    project: Project,
    run_id: str,
    task: Task,
    worktree: Path,
) -> str:
    runner_directory = project.common_directory / "agent-runner"
    key = active_turn_key(task.ticket_id)
    try:
        reserve_active_turn(
            runner_directory,
            key,
            {
                "run_id": run_id,
                "ticket_id": task.ticket_id,
                "worktree_path": str(worktree),
                "launcher_pid": os.getpid(),
            },
        )
    except ActiveTurnBusyError as error:
        raise RunnerError(
            "WORKTREE_TURN_ACTIVE",
            "The Ticket Worktree already has an active Engineer turn.",
        ) from error
    except ActiveTurnReservationError as error:
        raise RunnerError(
            "ACTIVE_TURN_RESERVATION_FAILED",
            "The Ticket Worktree could not be reserved for an Engineer turn.",
        ) from error
    return key


def _ensure_scoped_scratch(worktree: Path, evidence: Path) -> None:
    scratch = worktree / ".scratch"
    scoped = scratch / "task-delivery"
    try:
        if scratch.is_symlink():
            raise OSError(".scratch must not be a symlink")
        scratch.mkdir(exist_ok=True)
        if os.path.lexists(str(scoped)):
            if scoped.is_symlink() and scoped.resolve() == evidence:
                return
            raise OSError("scoped scratch already points elsewhere")
        scoped.symlink_to(
            os.path.relpath(evidence, scratch),
            target_is_directory=True,
        )
        if scoped.resolve() != evidence:
            raise OSError("scoped scratch does not resolve to evidence")
    except OSError as error:
        raise RunnerError(
            "SCRATCH_LINK_FAILED",
            "The Ticket Worktree scoped scratch link could not be established.",
        ) from error


def _start_turn(
    *,
    project: Project,
    run_id: str,
    task: Task,
    role: CodexRole,
    branch: str,
    worktree: Path,
    evidence: Path,
    active_turn_key: str,
) -> Tuple[str, Dict[str, Any]]:
    session_root = project.common_directory / "agent-runner" / "sessions"
    try:
        session_root.mkdir(parents=True, exist_ok=True)
        alias, session_directory = _reserve_alias(
            session_root, task, ROLE_ALIAS[task.role]
        )
        mapping = {
            "alias": alias,
            "runtime": "codex",
            "run_id": run_id,
            "ticket_id": task.ticket_id,
            "ticket_name": task.ticket_name,
            "role": task.role,
            "branch": branch,
            "worktree_path": str(worktree),
            "ticket_file": str(task.ticket_file),
            "evidence_path": str(evidence),
        }
        launch_file = session_directory / "launch.yml"
        write_yaml_durably(
            launch_file,
            {
                "runtime": "codex",
                "adapter_request": role.launch_request(
                    executable=project.runtime_executable,
                    worktree=worktree,
                    evidence=evidence,
                    git_common_directory=project.common_directory,
                ),
                "active_turn_key": active_turn_key,
                "mapping": mapping,
            },
        )
        worker_stderr = session_directory / "worker-stderr.log"
        prompt = _task_prompt(task)
        with worker_stderr.open("w", encoding="utf-8") as diagnostics:
            worker = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "you_are_a_product_architect.runner_worker",
                    str(launch_file),
                ],
                cwd=worktree,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=diagnostics,
                text=True,
                start_new_session=True,
            )
            assert worker.stdin is not None
            worker.stdin.write(prompt)
            worker.stdin.close()
    except RunnerError:
        raise
    except (OSError, BrokenPipeError, yaml.YAMLError) as error:
        worker_started = "worker" in locals()
        if worker_started:
            stop_worker(worker.pid)
        raise RunnerError(
            "RUNTIME_WORKER_START_FAILED",
            "The internal Runtime worker could not be started.",
            release_reservation=not worker_started,
        ) from error

    mapping_file = session_directory / "mapping.yml"
    error_file = session_directory / "launch-error.yml"
    deadline = time.monotonic() + LAUNCH_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if mapping_file.is_file():
            try:
                durable_mapping = yaml.safe_load(
                    mapping_file.read_text(encoding="utf-8")
                )
            except (OSError, UnicodeError, yaml.YAMLError) as error:
                stop_worker(worker.pid)
                raise RunnerError(
                    "RUNTIME_MAPPING_INVALID",
                    "The Runtime session mapping could not be read.",
                    release_reservation=False,
                ) from error
            if (
                not isinstance(durable_mapping, dict)
                or not isinstance(durable_mapping.get("session"), str)
                or not durable_mapping["session"]
            ):
                stop_worker(worker.pid)
                raise RunnerError(
                    "RUNTIME_MAPPING_INVALID",
                    "The Runtime session mapping is invalid.",
                    release_reservation=False,
                )
            try:
                confirm_alias_mapping_durable(mapping_file)
            except OSError as error:
                stop_worker(worker.pid)
                raise RunnerError(
                    "RUNTIME_MAPPING_INVALID",
                    "The Runtime session mapping is not crash-durable.",
                    release_reservation=False,
                ) from error
            return alias, durable_mapping
        if error_file.is_file():
            try:
                failure = yaml.safe_load(error_file.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, yaml.YAMLError):
                failure = None
            if not isinstance(failure, dict):
                raise RunnerError(
                    "RUNTIME_LAUNCH_FAILED",
                    "The Codex Runtime launch failed.",
                    release_reservation=False,
                )
            raise RunnerError(
                str(failure.get("code", "RUNTIME_LAUNCH_FAILED")),
                str(failure.get("message", "The Codex Runtime launch failed.")),
                release_reservation=False,
            )
        if worker.poll() is not None:
            raise RunnerError(
                "RUNTIME_LAUNCH_FAILED",
                "The Codex Runtime worker exited before launch completed.",
                release_reservation=False,
            )
        time.sleep(0.01)
    stop_worker(worker.pid)
    raise RunnerError(
        "RUNTIME_LAUNCH_TIMEOUT",
        "Codex did not report a Runtime session before the launch timeout.",
        release_reservation=False,
    )


def _reserve_alias(session_root: Path, task: Task, tier: str) -> Tuple[str, Path]:
    for ordinal in range(1, 10000):
        alias = "{0}@{1}{2}".format(task.stem, tier, ordinal)
        directory = session_root / alias
        try:
            directory.mkdir()
        except FileExistsError:
            continue
        return alias, directory
    raise RunnerError(
        "ALIAS_ALLOCATION_FAILED",
        "A fresh semantic session alias could not be allocated.",
    )


def _task_prompt(task: Task) -> str:
    if task.instruction is None:
        return task.ticket_content
    return (
        task.ticket_content
        + "\n## Additional instruction from Main\n\n"
        + task.instruction
        + "\n"
    )


def _write_metadata(
    *,
    evidence: Path,
    run_id: str,
    task: Task,
    alias: str,
    session: str,
    branch: str,
    worktree: Path,
) -> None:
    try:
        write_yaml_durably(
            evidence / "metadata.yml",
            {
                "run_id": run_id,
                "ticket_id": task.ticket_id,
                "ticket_name": task.ticket_name,
                "alias": alias,
                "role": task.role,
                "runtime": "codex",
                "session": session,
                "branch": branch,
                "worktree_path": str(worktree),
                "ticket_file": str(task.ticket_file),
            },
        )
    except (OSError, yaml.YAMLError) as error:
        raise RunnerError(
            "METADATA_WRITE_FAILED",
            "The Runner could not persist mechanical ticket metadata.",
        ) from error


def _resolve_role(worktree: Path, binding: str) -> CodexRole:
    try:
        return resolve_codex_role(worktree, binding)
    except CodexAdapterError as error:
        raise RunnerError(error.code, error.message) from error
