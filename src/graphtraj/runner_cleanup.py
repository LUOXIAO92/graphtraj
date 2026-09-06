"""Fail-closed cleanup for one integrated Ticket Worktree."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .runner_batch import valid_ticket_id
from .runner_models import CleanupResponse, Project, RunnerError
from .runner_project import discover_project, git_succeeds, registered_worktrees, run_git
from .ticket_graph import _load_states


@dataclass(frozen=True)
class CleanupTarget:
    """The canonical disposable resources for one integrated Ticket."""

    project: Project
    ticket_id: str
    ticket_name: str
    worktree: Path
    branch: str
    status: str


def cleanup_ticket(cwd: Path, ticket_id: str) -> CleanupResponse:
    """Remove one integrated Ticket's disposable resources by Ticket identity."""

    if not valid_ticket_id(ticket_id):
        raise RunnerError(
            "TICKET_ID_INVALID",
            "ticket_id must be 1-32 ASCII letters, digits, dots, underscores, or hyphens.",
        )
    project = discover_project(cwd, require_clean_integration=False)
    target = _target(project, ticket_id)
    if isinstance(target, CleanupResponse):
        return target
    try:
        return _cleanup(target)
    except RunnerError as error:
        return _refused(
            target,
            "cleanup-failed",
            "A required cleanup operation could not be verified.",
            {"cause": error.as_document()["code"]},
        )


def _target(project: Project, ticket_id: str) -> CleanupTarget | CleanupResponse:
    try:
        states = _load_states(project.state_directory / "tickets")
    except (OSError, UnicodeError, ValueError, yaml.YAMLError):
        return _unknown_refusal(
            ticket_id,
            "cleanup-ownership-mismatch",
            "The canonical Ticket state cannot be verified.",
            {"ticket": "invalid"},
        )
    if ticket_id not in states:
        return _unknown_refusal(
            ticket_id,
            "cleanup-ownership-mismatch",
            "No canonical Ticket belongs to the supplied identity.",
            {"ticket": "not-found"},
        )
    _, state = states[ticket_id]
    ticket_name = state["ticket_name"]
    worktree = project.worktree_root / (ticket_id + "-" + ticket_name)
    branch = "agent/" + ticket_id + "-" + ticket_name
    try:
        relative_worktree = worktree.relative_to(project.harness_root).as_posix()
    except ValueError:
        return _unknown_refusal(
            ticket_id,
            "cleanup-ownership-mismatch",
            "The canonical Ticket state cannot be verified.",
            {"ticket": "invalid"},
        )
    if state["worktree"] != relative_worktree or state["branch"] != branch:
        return _unknown_refusal(
            ticket_id,
            "cleanup-ownership-mismatch",
            "The canonical Ticket resources do not match its current state.",
            {"ticket": "coordinates-mismatch"},
        )
    return CleanupTarget(
        project=project,
        ticket_id=ticket_id,
        ticket_name=ticket_name,
        worktree=worktree,
        branch=branch,
        status=state["status"],
    )


def _cleanup(target: CleanupTarget) -> CleanupResponse:
    if target.status != "integrated":
        return _refused(
            target,
            "cleanup-not-integrated",
            "The Ticket has not completed validated integration.",
            {"ticket_status": target.status},
        )

    mappings, mapping_errors, busy_aliases = _ticket_mappings(target)
    if mapping_errors:
        return _refused(
            target,
            "cleanup-ownership-mismatch",
            "The live Runner mappings cannot be attributed safely.",
            {"mapping_mismatches": mapping_errors},
        )
    if busy_aliases:
        return _refused(
            target,
            "worktree-busy",
            "The Ticket Worktree has an executing Agent.",
            {"aliases": busy_aliases},
        )

    expected_ref = "refs/heads/" + target.branch
    records = registered_worktrees(target.project.repository)
    path_records = [
        record for record in records if record.get("worktree") == str(target.worktree)
    ]
    branch_records = [
        record for record in records if record.get("branch") == expected_ref
    ]
    branch_exists = git_succeeds(
        target.project.repository,
        "show-ref",
        "--verify",
        "--quiet",
        expected_ref,
    )
    worktree_exists = os.path.lexists(str(target.worktree))
    if not branch_exists and not worktree_exists and not path_records and not branch_records:
        if mappings:
            return _refused(
                target,
                "cleanup-ownership-mismatch",
                "The live Runner mappings outlast their canonical Ticket resources.",
                {"mappings": [path.name for path in mappings]},
            )
        return _already_cleaned(target)
    if (
        not branch_exists
        or not worktree_exists
        or target.worktree.is_symlink()
        or not target.worktree.is_dir()
        or len(path_records) != 1
        or path_records[0].get("branch") != expected_ref
        or len(branch_records) != 1
    ):
        return _refused(
            target,
            "cleanup-ownership-mismatch",
            "The canonical Ticket Worktree and branch cannot be verified.",
            {"worktree": str(target.worktree), "branch": target.branch},
        )

    status = run_git(
        target.worktree, "status", "--porcelain", "--untracked-files=all"
    ).splitlines()
    if status:
        return _refused(
            target,
            "cleanup-dirty",
            "The Ticket Worktree is not clean.",
            {"worktree_status": status},
        )
    ticket_commit = run_git(target.project.repository, "rev-parse", target.branch)
    if not git_succeeds(
        target.project.repository,
        "merge-base",
        "--is-ancestor",
        target.branch,
        target.project.dev_commit,
    ):
        return _refused(
            target,
            "cleanup-not-integrated",
            "The Ticket branch is not merged into registered dev.",
            {
                "integration_branch": target.project.integration_branch,
                "integration_commit": target.project.dev_commit,
                "ticket_commit": ticket_commit,
            },
        )

    completed_actions: list[str] = []
    try:
        run_git(target.project.repository, "worktree", "remove", str(target.worktree))
        if os.path.lexists(str(target.worktree)):
            raise OSError("Ticket Worktree path still exists")
        completed_actions.append("worktree-removed")
        for mapping in mappings:
            shutil.rmtree(mapping)
        completed_actions.append("mappings-removed")
        _delete_branch_if_dev_unchanged(target, ticket_commit)
        completed_actions.append("branch-removed")
    except (OSError, RunnerError, shutil.Error):
        return _refused(
            target,
            "cleanup-failed",
            "The integrated Ticket Worktree could not be cleaned up.",
            {"completed_actions": completed_actions},
        )
    return CleanupResponse(
        document={
            "ticket_id": target.ticket_id,
            "cleanup_status": "cleaned",
            "worktree_path": str(target.worktree),
            "branch": target.branch,
            "aliases_removed": [mapping.name for mapping in mappings],
            "evidence": {
                "integration_branch": target.project.integration_branch,
                "integration_commit": target.project.dev_commit,
                "ticket_commit": ticket_commit,
            },
        },
        succeeded=True,
    )


def _ticket_mappings(
    target: CleanupTarget,
) -> tuple[list[Path], list[str], list[str]]:
    sessions = target.project.runner_directory / "sessions"
    if not os.path.lexists(str(sessions)):
        return [], [], []
    if sessions.is_symlink() or not sessions.is_dir():
        raise RunnerError("GIT_FAILED", "A required cleanup operation failed.")
    mappings: list[Path] = []
    errors: list[str] = []
    busy: list[str] = []
    prefix = re.compile(
        re.escape(target.ticket_id + "-" + target.ticket_name)
        + r"(?:-team[1-9][0-9]*)?@"
    )
    for directory in sessions.iterdir():
        alias_candidate = prefix.match(directory.name) is not None
        mapping_file = directory / "mapping.yml"
        if not directory.is_dir() or directory.is_symlink():
            if alias_candidate:
                errors.append(directory.name)
            continue
        if not mapping_file.is_file() or mapping_file.is_symlink():
            if alias_candidate:
                errors.append(directory.name)
            continue
        try:
            mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            if alias_candidate:
                errors.append(directory.name)
            continue
        if not isinstance(mapping, dict):
            if alias_candidate:
                errors.append(directory.name)
            continue
        if mapping.get("ticket_id") != target.ticket_id or "run_id" in mapping:
            if alias_candidate:
                errors.append(directory.name)
            continue
        if not alias_candidate or not _valid_mapping(
            mapping, directory.name, target.ticket_id
        ):
            errors.append(directory.name)
            continue
        mappings.append(directory)
        if _process_alive(mapping["worker_pid"]) or _process_alive(
            mapping["runtime_pid"]
        ):
            busy.append(directory.name)
    return mappings, errors, busy


def _valid_mapping(mapping: dict[str, Any], alias: str, ticket_id: str) -> bool:
    strings = ("alias", "runtime", "session", "ticket_id", "role", "retained_batch_file")
    return (
        all(isinstance(mapping.get(key), str) and mapping[key] for key in strings)
        and mapping["alias"] == alias
        and mapping["ticket_id"] == ticket_id
        and isinstance(mapping.get("team_generation"), int)
        and not isinstance(mapping["team_generation"], bool)
        and mapping["team_generation"] > 0
        and all(
            isinstance(mapping.get(key), int)
            and not isinstance(mapping[key], bool)
            and mapping[key] > 0
            for key in ("worker_pid", "runtime_pid")
        )
    )


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _delete_branch_if_dev_unchanged(
    target: CleanupTarget, ticket_commit: str
) -> None:
    project = target.project
    transaction = (
        "option no-deref\n"
        "start\n"
        "verify refs/heads/{0} {1}\n"
        "delete refs/heads/{2} {3}\n"
        "prepare\n"
        "commit\n"
    ).format(
        project.integration_branch,
        project.dev_commit,
        target.branch,
        ticket_commit,
    )
    run_git(project.repository, "update-ref", "--stdin", input_text=transaction)


def _refused(
    target: CleanupTarget,
    code: str,
    message: str,
    evidence: dict[str, Any],
) -> CleanupResponse:
    return CleanupResponse(
        document={
            "ticket_id": target.ticket_id,
            "cleanup_status": "refused",
            "worktree_path": str(target.worktree),
            "branch": target.branch,
            "error": {"code": code, "message": message},
            "evidence": evidence,
        },
        succeeded=False,
    )


def _unknown_refusal(
    ticket_id: str,
    code: str,
    message: str,
    evidence: dict[str, Any],
) -> CleanupResponse:
    return CleanupResponse(
        document={
            "ticket_id": ticket_id,
            "cleanup_status": "refused",
            "error": {"code": code, "message": message},
            "evidence": evidence,
        },
        succeeded=False,
    )


def _already_cleaned(target: CleanupTarget) -> CleanupResponse:
    return CleanupResponse(
        document={
            "ticket_id": target.ticket_id,
            "cleanup_status": "already-cleaned",
            "worktree_path": str(target.worktree),
            "branch": target.branch,
            "aliases_removed": [],
            "evidence": {"disposable_state": "absent"},
        },
        succeeded=True,
    )
