"""Fail-closed lifecycle cleanup for one integrated Ticket Worktree."""

from __future__ import annotations

import errno
import hashlib
import os
import re
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from .runner_batch import (
    valid_run_id,
    valid_ticket_id,
    valid_ticket_name,
)
from .runner_io import (
    ActiveTurnReservation,
    active_turn_key,
    create_active_turn_reservation,
    directory_open_flags,
    release_active_turn,
)
from .runner_models import (
    ROLE_ALIAS_MARKERS,
    CleanupResponse,
    Project,
    RunnerError,
    ticket_id_stem_prefix,
    ticket_stem,
)
from .runner_project import (
    discover_project,
    git_succeeds,
    registered_worktrees,
    run_git,
)
from .runner_transport import (
    RUNTIME_DIAGNOSTIC_FILES,
    valid_runtime_turn_outcome,
    valid_terminal_launch_failure,
)


class _RegistrationError(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class CleanupTarget:
    """One canonical cleanup target with its stable ownership context."""

    project: Project
    run_id: str
    ticket_id: str
    registration: Dict[str, Any]
    worktree: Path
    branch: str


@dataclass(frozen=True)
class BoundAlias:
    """One validated live alias tied to its captured directory identity."""

    path: Path
    device: int
    inode: int
    entries: Tuple["BoundAliasEntry", ...]
    turn: int


@dataclass(frozen=True)
class BoundAliasEntry:
    """One captured diagnostic entry within a validated live alias."""

    name: str
    device: int
    inode: int
    mode: int
    size: int
    modified_ns: int
    changed_ns: int
    digest: str | None


@dataclass(frozen=True)
class SessionSnapshot:
    """Captured identity and complete entry set for the sessions root."""

    path: Path
    device: int
    inode: int
    names: Tuple[str, ...]


def cleanup_ticket(cwd: Path, run_id: str, ticket_id: str) -> CleanupResponse:
    """Remove only disposable state for one safely integrated ticket."""

    if not valid_run_id(run_id):
        raise RunnerError(
            "RUN_ID_INVALID",
            (
                "run_id must use YYYYMMDD-short-name form with a semantic "
                "short name of at most 48 ASCII characters and at most 64 "
                "characters overall."
            ),
        )
    if not valid_ticket_id(ticket_id):
        raise RunnerError(
            "TICKET_ID_INVALID",
            "ticket_id must be 1-32 ASCII letters, digits, dots, underscores, or hyphens.",
        )

    project = discover_project(
        cwd,
        require_clean_integration=False,
        require_runtime_executable=False,
    )
    try:
        registration = _resolve_registration(project, run_id, ticket_id)
    except _RegistrationError as error:
        return CleanupResponse(
            document={
                "run_id": run_id,
                "ticket_id": ticket_id,
                "cleanup_status": "refused",
                "error": {
                    "code": "cleanup-ownership-mismatch",
                    "message": error.message,
                },
                "evidence": {"registration": error.reason},
            },
            succeeded=False,
        )
    branch = registration["branch"]
    worktree = Path(registration["worktree_path"])
    target = CleanupTarget(
        project=project,
        run_id=run_id,
        ticket_id=ticket_id,
        registration=registration,
        worktree=worktree,
        branch=branch,
    )
    try:
        git_state_absent = _disposable_git_state_absent(project, worktree, branch)
        bound_aliases, alias_errors, _session_snapshot = _inspect_aliases(
            target,
            allow_foreign=git_state_absent,
        )
    except RunnerError as error:
        return _refused(
            target=target,
            code="cleanup-failed",
            message="A required cleanup operation could not be verified.",
            evidence={"cause": error.as_document()["code"]},
        )
    active_turn, active_turn_invalid = _active_turn(project, ticket_id)
    if active_turn_invalid:
        return _refused(
            target=target,
            code="cleanup-ownership-mismatch",
            message="The active-turn reservation cannot be attributed safely.",
            evidence={"active_turn": "invalid"},
        )
    orphaned_turn, orphan_scan_invalid = _orphaned_active_turn(
        project, run_id, ticket_id, worktree
    )
    if orphan_scan_invalid:
        return _refused(
            target=target,
            code="cleanup-ownership-mismatch",
            message="The active-turn reservation cannot be attributed safely.",
            evidence={"active_turn": "invalid"},
        )
    if orphaned_turn:
        return _refused(
            target=target,
            code="cleanup-ownership-mismatch",
            message="A prior cleanup reservation remains unresolved.",
            evidence={"active_turn": "orphaned"},
        )
    if (
        not bound_aliases
        and not alias_errors
        and (
            active_turn is None
            or active_turn.get("run_id") != run_id
        )
        and git_state_absent
    ):
        return _already_cleaned(target)
    reservation, competing_turn, reservation_invalid = _reserve_cleanup(
        project, run_id, ticket_id, worktree
    )
    if reservation_invalid:
        return _refused(
            target=target,
            code="cleanup-ownership-mismatch",
            message="The active-turn reservation cannot be attributed safely.",
            evidence={"active_turn": "invalid"},
        )
    if competing_turn is not None:
        return _refused(
            target=target,
            code="worktree-busy",
            message="The Ticket Worktree has an active Engineer turn.",
            evidence={"active_turn": _active_turn_evidence(competing_turn)},
        )
    if reservation is None:
        return _refused(
            target=target,
            code="cleanup-failed",
            message="The Ticket Worktree could not be reserved for cleanup.",
            evidence={"reservation": "failed"},
        )

    runner_directory = project.runner_directory
    released = False
    try:
        try:
            response = _cleanup_reserved(target)
        except RunnerError as error:
            response = _refused(
                target=target,
                code="cleanup-failed",
                message="A required cleanup operation could not be verified.",
                evidence={"cause": error.as_document()["code"]},
            )
    finally:
        released = release_active_turn(runner_directory, reservation)
    if not released:
        return _refused(
            target=target,
            code="cleanup-failed",
            message="The cleanup reservation could not be released safely.",
            evidence={"reservation": "release-failed"},
        )
    return response


def _cleanup_reserved(target: CleanupTarget) -> CleanupResponse:
    project = target.project
    run_id = target.run_id
    ticket_id = target.ticket_id
    worktree = target.worktree
    branch = target.branch
    ownership_errors = _ownership_errors(target)
    git_state_absent = _disposable_git_state_absent(project, worktree, branch)
    bound_aliases, alias_errors, session_snapshot = _inspect_aliases(
        target,
        allow_foreign=git_state_absent,
    )
    worktree_registered = _canonical_worktree_registered(
        project, worktree, branch
    )
    if not bound_aliases and not alias_errors and git_state_absent:
        return _already_cleaned(target)
    registered_alias = target.registration.get("alias")
    if (
        worktree_registered
        and not alias_errors
        and not any(
            alias.path.name == registered_alias for alias in bound_aliases
        )
    ):
        ownership_errors.append("registered-alias-missing")
    ownership_errors.extend(alias_errors)
    ownership_errors.extend(
        _persistent_evidence_errors(target, bound_aliases)
    )
    if ownership_errors:
        return _refused(
            target=target,
            code="cleanup-ownership-mismatch",
            message=(
                "The registered Ticket Worktree does not belong to the supplied "
                "run and ticket identities."
            ),
            evidence={"ownership_mismatches": ownership_errors},
        )

    if worktree_registered:
        worktree_status = run_git(
            worktree, "status", "--porcelain", "--untracked-files=all"
        ).splitlines()
        if worktree_status:
            return _refused(
                target=target,
                code="cleanup-dirty",
                message="The Ticket Worktree is not clean.",
                evidence={"worktree_status": worktree_status},
            )

    branch_exists = git_succeeds(
        project.repository,
        "show-ref",
        "--verify",
        "--quiet",
        "refs/heads/{0}".format(branch),
    )
    if not branch_exists and bound_aliases:
        return _refused(
            target=target,
            code="cleanup-not-merged",
            message=(
                "The Ticket branch is unavailable, so integration cannot be "
                "verified."
            ),
            evidence={
                "integration_branch": project.integration_branch,
                "integration_commit": project.dev_commit,
                "ticket_branch": "absent",
                "worktree": "absent",
            },
        )
    ticket_commit = None
    if branch_exists:
        ticket_commit = run_git(project.repository, "rev-parse", branch)
        if not git_succeeds(
            project.repository,
            "merge-base",
            "--is-ancestor",
            branch,
            project.dev_commit,
        ):
            return _refused(
                target=target,
                code="cleanup-not-merged",
                message="The Ticket branch is not merged into registered dev.",
                evidence={
                    "integration_branch": project.integration_branch,
                    "integration_commit": project.dev_commit,
                    "ticket_commit": ticket_commit,
                },
            )

    unsafe_alias_entries = _unsafe_alias_entries(bound_aliases)
    if unsafe_alias_entries:
        return _refused(
            target=target,
            code="cleanup-failed",
            message="The bound alias diagnostics cannot be removed safely.",
            evidence={"unsafe_alias_entries": unsafe_alias_entries},
        )

    completed_actions = []
    try:
        if worktree_registered:
            run_git(project.repository, "worktree", "remove", str(worktree))
            if os.path.lexists(str(worktree)):
                raise OSError("Ticket Worktree path still exists")
            completed_actions.append("worktree-removed")

        _remove_aliases(bound_aliases, session_snapshot)
        completed_actions.append("aliases-removed")

        if branch_exists:
            assert ticket_commit is not None
            _delete_ticket_branch_if_dev_unchanged(project, branch, ticket_commit)
            if git_succeeds(
                project.repository,
                "show-ref",
                "--verify",
                "--quiet",
                "refs/heads/{0}".format(branch),
            ):
                raise OSError("Ticket branch still exists")
            completed_actions.append("branch-removed")

        _prune_worktree_ancestors(target)
    except (OSError, RunnerError):
        return _refused(
            target=target,
            code="cleanup-failed",
            message="The integrated Ticket Worktree could not be cleaned up.",
            evidence={"completed_actions": completed_actions},
        )

    success_evidence = {
        "integration_branch": project.integration_branch,
        "integration_commit": project.dev_commit,
    }
    if ticket_commit is not None:
        success_evidence["ticket_commit"] = ticket_commit
    return CleanupResponse(
        document={
            "run_id": run_id,
            "ticket_id": ticket_id,
            "cleanup_status": "cleaned",
            "worktree_path": str(worktree),
            "branch": branch,
            "aliases_removed": [alias.path.name for alias in bound_aliases],
            "evidence": success_evidence,
        },
        succeeded=True,
    )


def _resolve_registration(
    project: Project,
    run_id: str,
    ticket_id: str,
) -> Dict[str, Any]:
    ticket_root = project.state_directory / run_id / "tickets"
    prefix = ticket_id_stem_prefix(ticket_id)
    current = project.state_directory
    for component in (run_id, "tickets"):
        current = current / component
        if os.path.lexists(str(current)) and current.is_symlink():
            raise _RegistrationError(
                "invalid",
                "The canonical ticket registration is invalid.",
            )
    if not ticket_root.exists():
        raise _RegistrationError(
            "not-found",
            "No canonical ticket registration belongs to the supplied identities.",
        )
    try:
        if ticket_root.is_symlink() or not ticket_root.is_dir():
            raise OSError("ticket evidence root is invalid")
        candidates = [
            path
            for path in ticket_root.iterdir()
            if path.name.startswith(prefix)
        ]
    except OSError as error:
        raise _RegistrationError(
            "invalid",
            "The canonical ticket registration is invalid.",
        ) from error
    if not candidates:
        raise _RegistrationError(
            "not-found",
            "No canonical ticket registration belongs to the supplied identities.",
        )
    if len(candidates) > 1:
        raise _RegistrationError(
            "ambiguous",
            "No unique canonical ticket registration belongs to the supplied identities.",
        )
    evidence = candidates[0]
    metadata_file = evidence / "metadata.yml"
    try:
        if evidence.is_symlink() or not evidence.is_dir():
            raise OSError("ticket evidence directory is invalid")
        if metadata_file.is_symlink() or not metadata_file.is_file():
            raise OSError("metadata is invalid")
        metadata = yaml.safe_load(metadata_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise _RegistrationError(
            "invalid",
            "The canonical ticket registration is invalid.",
        ) from error
    if not isinstance(metadata, dict):
        raise _RegistrationError(
            "invalid",
            "The canonical ticket registration is invalid.",
        )

    ticket_name = metadata.get("ticket_name")
    expected_stem = ticket_stem(ticket_id, str(ticket_name))
    expected_branch = "agent/{0}/{1}".format(run_id, expected_stem)
    expected_worktree = (
        project.worktree_root / "runs" / run_id / expected_stem
    )
    if (
        metadata.get("run_id") != run_id
        or metadata.get("ticket_id") != ticket_id
        or not valid_ticket_name(ticket_name)
        or evidence.name != expected_stem
        or metadata.get("branch") != expected_branch
        or metadata.get("worktree_path") != str(expected_worktree)
    ):
        raise _RegistrationError(
            "invalid",
            "The canonical ticket registration does not match the supplied identities.",
        )
    if not _ticket_file_is_safe(
        project, expected_worktree, metadata.get("ticket_file")
    ):
        raise _RegistrationError(
            "invalid",
            "The canonical ticket registration is invalid.",
        )
    return metadata


def _disposable_git_state_absent(
    project: Project,
    worktree: Path,
    branch: str,
) -> bool:
    expected_branch = "refs/heads/{0}".format(branch)
    if os.path.lexists(str(worktree)) or git_succeeds(
        project.repository,
        "show-ref",
        "--verify",
        "--quiet",
        expected_branch,
    ):
        return False
    return all(
        _registered_worktree_path(record) != worktree
        and record.get("branch") != expected_branch
        for record in registered_worktrees(project.repository)
    )


def _reserve_cleanup(
    project: Project,
    run_id: str,
    ticket_id: str,
    worktree: Path,
) -> Tuple[
    ActiveTurnReservation | None,
    Dict[str, str] | None,
    bool,
]:
    runner_directory = project.runner_directory
    for _attempt in range(2):
        try:
            reservation = create_active_turn_reservation(
                runner_directory,
                ticket_id,
                {
                    "activity": "cleanup",
                    "run_id": run_id,
                    "ticket_id": ticket_id,
                    "worktree_path": str(worktree),
                    "cleanup_pid": os.getpid(),
                },
            )
        except FileExistsError:
            competing, invalid = _active_turn(project, ticket_id)
            if invalid:
                return None, None, True
            if competing is None:
                continue
            return None, competing, False
        except (OSError, ValueError, yaml.YAMLError):
            return None, None, False
        return reservation, None, False
    return None, None, False


def _active_turn(
    project: Project,
    ticket_id: str,
) -> Tuple[Dict[str, str] | None, bool]:
    key = active_turn_key(ticket_id)
    runner_directory = project.runner_directory
    reservation = runner_directory / "active-worktrees" / key
    if runner_directory.is_symlink():
        return None, True
    if not os.path.lexists(str(reservation)):
        return None, False
    flags = directory_open_flags()
    try:
        runner_descriptor = os.open(str(runner_directory), flags)
        try:
            active_descriptor = os.open(
                "active-worktrees", flags, dir_fd=runner_descriptor
            )
        finally:
            os.close(runner_descriptor)
        try:
            document = _read_active_turn_at(active_descriptor, key)
        finally:
            os.close(active_descriptor)
    except (OSError, UnicodeError, yaml.YAMLError):
        return None, True
    active = _valid_active_turn_owner(document)
    if (
        active is None
        or active["ticket_id"] != ticket_id
        or not _active_turn_path_is_canonical(project, active)
    ):
        return None, True
    return active, False


def _orphaned_active_turn(
    project: Project,
    run_id: str,
    ticket_id: str,
    worktree: Path,
) -> Tuple[bool, bool]:
    runner_directory = project.runner_directory
    active_root = runner_directory / "active-worktrees"
    if not os.path.lexists(str(active_root)):
        return False, False
    flags = directory_open_flags()
    try:
        runner_descriptor = os.open(str(runner_directory), flags)
        try:
            active_descriptor = os.open(
                "active-worktrees", flags, dir_fd=runner_descriptor
            )
        finally:
            os.close(runner_descriptor)
    except OSError:
        return False, True
    canonical_key = active_turn_key(ticket_id)
    try:
        for name in os.listdir(active_descriptor):
            if name == canonical_key:
                continue
            try:
                owner = _read_active_turn_at(active_descriptor, name)
            except (OSError, UnicodeError, yaml.YAMLError):
                return False, True
            active = _valid_active_turn_owner(owner)
            if active is None or not _active_turn_path_is_canonical(
                project, active
            ):
                return False, True
            expected_key = active_turn_key(active["ticket_id"])
            if name != expected_key:
                if (
                    active["ticket_id"] == ticket_id
                    or active["worktree_path"] == str(worktree)
                ):
                    return True, False
                return False, True
            if (
                active["ticket_id"] == ticket_id
                or active["worktree_path"] == str(worktree)
            ):
                return False, True
    except OSError:
        return False, True
    finally:
        os.close(active_descriptor)
    return False, False


def _valid_active_turn_owner(document: Any) -> Dict[str, str] | None:
    if not isinstance(document, dict):
        return None
    activity = document.get("activity")
    run_id = document.get("run_id")
    ticket_id = document.get("ticket_id")
    worktree_path = document.get("worktree_path")
    alias = document.get("alias")
    if (
        not isinstance(activity, str)
        or activity not in {"starting", "running", "cleanup"}
        or not isinstance(run_id, str)
        or not valid_run_id(run_id)
        or not valid_ticket_id(ticket_id)
        or not isinstance(worktree_path, str)
        or not Path(worktree_path).is_absolute()
        or (activity == "running" and not isinstance(alias, str))
    ):
        return None
    active = {
        "activity": activity,
        "run_id": run_id,
        "ticket_id": ticket_id,
        "worktree_path": worktree_path,
    }
    if isinstance(alias, str):
        active["alias"] = alias
    return active


def _active_turn_path_is_canonical(
    project: Project,
    active: Dict[str, str],
) -> bool:
    raw_path = active["worktree_path"]
    worktree = Path(raw_path)
    expected_parent = project.worktree_root / "runs" / active["run_id"]
    try:
        resolved = worktree.resolve(strict=False)
        canonical_parent = expected_parent.resolve(strict=False)
    except (OSError, RuntimeError):
        return False
    return (
        str(worktree) == raw_path
        and str(resolved) == raw_path
        and worktree.parent == canonical_parent
        and worktree.name.startswith(
            ticket_id_stem_prefix(active["ticket_id"])
        )
    )


def _read_active_turn_at(active_descriptor: int, name: str) -> Any:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(name, flags, dir_fd=active_descriptor)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise OSError("active-turn reservation is not a regular file")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            content = stream.read()
        after = os.fstat(descriptor)
        before_identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if before_identity != after_identity:
            raise OSError("active-turn reservation changed while being read")
        return yaml.safe_load(content.decode("utf-8"))
    finally:
        os.close(descriptor)


def _active_turn_evidence(active_turn: Dict[str, str]) -> Dict[str, str]:
    return {
        key: active_turn[key]
        for key in ("activity", "alias", "worktree_path")
        if key in active_turn
    }


def _ownership_errors(target: CleanupTarget) -> List[str]:
    project = target.project
    worktree = target.worktree
    branch = target.branch
    expected_branch = "refs/heads/{0}".format(branch)
    branch_exists = git_succeeds(
        project.repository,
        "show-ref",
        "--verify",
        "--quiet",
        expected_branch,
    )
    matching_path = None
    matching_branches = []
    for record in registered_worktrees(project.repository):
        record_path = _registered_worktree_path(record)
        if record_path == worktree:
            matching_path = record
        if record.get("branch") == expected_branch:
            matching_branches.append(record)
    errors = []
    path_exists = os.path.lexists(str(worktree))
    if matching_path is not None and matching_path.get("branch") != expected_branch:
        errors.append("canonical-worktree-branch-mismatch")
    if any(
        _registered_worktree_path(record) != worktree
        for record in matching_branches
    ):
        errors.append("ticket-branch-registered-at-noncanonical-path")
    if len(matching_branches) > 1:
        errors.append("ticket-branch-registered-multiple-times")
    if matching_path is None and matching_branches:
        errors.insert(0, "canonical-worktree-not-registered")
    elif matching_path is not None and not matching_branches:
        errors.append("ticket-branch-worktree-not-registered")
    elif matching_path is None and not matching_branches and path_exists:
        errors.append("canonical-worktree-path-unregistered")
    if not branch_exists and (matching_path is not None or matching_branches):
        errors.append("ticket-branch-ref-missing")
    if branch_exists and git_succeeds(
        project.repository,
        "symbolic-ref",
        "--quiet",
        expected_branch,
    ):
        errors.append("ticket-branch-symbolic")
    if target.registration.get("run_id") != target.run_id:
        errors.append("metadata-run-mismatch")
    if target.registration.get("ticket_id") != target.ticket_id:
        errors.append("metadata-ticket-mismatch")
    return errors


def _canonical_worktree_registered(
    project: Project,
    worktree: Path,
    branch: str,
) -> bool:
    expected_branch = "refs/heads/{0}".format(branch)
    return any(
        _registered_worktree_path(record) == worktree
        and record.get("branch") == expected_branch
        for record in registered_worktrees(project.repository)
    )


def _inspect_aliases(
    target: CleanupTarget,
    *,
    allow_foreign: bool,
) -> Tuple[List[BoundAlias], List[str], SessionSnapshot | None]:
    project = target.project
    run_id = target.run_id
    ticket_id = target.ticket_id
    registration = target.registration
    worktree = target.worktree
    branch = target.branch
    runner_directory = project.runner_directory
    session_root = runner_directory / "sessions"
    if runner_directory.is_symlink():
        return [], ["session-root-invalid"], None
    if not os.path.lexists(str(session_root)):
        if allow_foreign:
            return [], [], None
        return [], ["session-root-missing"], None
    stem = worktree.name
    evidence = project.state_directory / run_id / "tickets" / stem
    flags = directory_open_flags()
    try:
        runner_descriptor = os.open(str(runner_directory), flags)
        try:
            session_descriptor = os.open(
                "sessions", flags, dir_fd=runner_descriptor
            )
        finally:
            os.close(runner_descriptor)
        session_identity = os.fstat(session_descriptor)
        names = tuple(sorted(os.listdir(session_descriptor)))
        session_snapshot = SessionSnapshot(
            path=session_root,
            device=session_identity.st_dev,
            inode=session_identity.st_ino,
            names=names,
        )
    except OSError:
        return [], ["session-root-invalid"], None

    bound = []
    errors = []
    try:
        for name in names:
            if not name.startswith("{0}@".format(stem)):
                continue
            directory = session_root / name
            try:
                alias_descriptor = os.open(
                    name, flags, dir_fd=session_descriptor
                )
            except OSError:
                errors.append("alias-mapping-invalid")
                continue
            try:
                identity = os.fstat(alias_descriptor)
                entries = _capture_alias_entries(alias_descriptor)
                mapping = _read_alias_mapping(alias_descriptor, entries)
                if not isinstance(mapping, dict):
                    raise OSError("alias mapping is invalid")
                references_ticket = (
                    mapping.get("run_id") == run_id
                    and mapping.get("ticket_id") == ticket_id
                )
                references_resources = any(
                    (
                        mapping.get("branch") == branch,
                        mapping.get("worktree_path") == str(worktree),
                        mapping.get("evidence_path") == str(evidence),
                    )
                )
                if not references_ticket and not references_resources:
                    continue
                checks = (
                    ("alias", name, "alias-name-mismatch"),
                    ("runtime", "codex", "alias-runtime-mismatch"),
                    ("run_id", run_id, "alias-run-mismatch"),
                    ("ticket_id", ticket_id, "alias-ticket-mismatch"),
                    (
                        "ticket_name",
                        registration.get("ticket_name"),
                        "alias-name-mismatch",
                    ),
                    ("branch", branch, "alias-branch-mismatch"),
                    (
                        "worktree_path",
                        str(worktree),
                        "alias-worktree-mismatch",
                    ),
                    (
                        "evidence_path",
                        str(evidence),
                        "alias-evidence-mismatch",
                    ),
                )
                error_count = len(errors)
                for key, expected, error in checks:
                    if mapping.get(key) != expected:
                        errors.append(error)
                if not _ticket_file_is_safe(
                    project, worktree, mapping.get("ticket_file")
                ):
                    errors.append("alias-ticket-file-unsafe")
                if not _alias_terminal_outcome_is_valid(
                    alias_descriptor, entries
                ):
                    errors.append("alias-terminal-outcome-missing")
                role = mapping.get("role")
                turn = mapping.get("turn")
                if (
                    not isinstance(turn, int)
                    or isinstance(turn, bool)
                    or turn < 1
                ):
                    errors.append("alias-turn-invalid")
                resume_entry = next(
                    (
                        entry
                        for entry in entries
                        if entry.name == "resume.yml"
                    ),
                    None,
                )
                if resume_entry is not None:
                    resume = _read_yaml_at(
                        alias_descriptor,
                        "resume.yml",
                        expected=resume_entry,
                    )
                    resumed_mapping = (
                        resume.get("mapping")
                        if isinstance(resume, dict)
                        else None
                    )
                    resumed_turn = (
                        resumed_mapping.get("turn")
                        if isinstance(resumed_mapping, dict)
                        else None
                    )
                    identity_fields = (
                        "alias",
                        "runtime",
                        "run_id",
                        "ticket_id",
                        "ticket_name",
                        "role",
                        "branch",
                        "worktree_path",
                        "ticket_file",
                        "evidence_path",
                        "session",
                    )
                    if (
                        not isinstance(turn, int)
                        or isinstance(turn, bool)
                        or not isinstance(resumed_turn, int)
                        or isinstance(resumed_turn, bool)
                        or resumed_turn < turn
                        or any(
                            resumed_mapping.get(field) != mapping.get(field)
                            for field in identity_fields
                        )
                    ):
                        errors.append("alias-turn-invalid")
                    else:
                        turn = resumed_turn
                if (
                    not isinstance(role, str)
                    or role not in ROLE_ALIAS_MARKERS
                    or (
                        mapping.get("alias") == name
                        and not _role_alias_is_valid(role, stem, name)
                    )
                ):
                    errors.append("alias-role-mismatch")
                current_entries = _capture_alias_entries(alias_descriptor)
                if entries != current_entries:
                    errors.append("alias-directory-identity-changed")
                if len(errors) == error_count:
                    bound.append(
                        BoundAlias(
                            path=directory,
                            device=identity.st_dev,
                            inode=identity.st_ino,
                            entries=entries,
                            turn=turn,
                        )
                    )
            except (OSError, UnicodeError, yaml.YAMLError):
                errors.append("alias-mapping-invalid")
            finally:
                os.close(alias_descriptor)
    finally:
        os.close(session_descriptor)
    return bound, errors, session_snapshot


def _capture_alias_entries(
    directory_descriptor: int,
) -> Tuple[BoundAliasEntry, ...]:
    entries = []
    for name in sorted(os.listdir(directory_descriptor)):
        identity = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        digest = None
        if stat.S_ISREG(identity.st_mode):
            digest = _digest_file_at(
                directory_descriptor,
                name,
                identity,
            )
        entries.append(
            BoundAliasEntry(
                name=name,
                device=identity.st_dev,
                inode=identity.st_ino,
                mode=identity.st_mode,
                size=identity.st_size,
                modified_ns=identity.st_mtime_ns,
                changed_ns=identity.st_ctime_ns,
                digest=digest,
            )
        )
    return tuple(entries)


def _read_alias_mapping(
    directory_descriptor: int,
    entries: Tuple[BoundAliasEntry, ...],
) -> Any:
    by_name = {entry.name: entry for entry in entries}
    if "mapping.yml" in by_name:
        return _read_yaml_at(
            directory_descriptor,
            "mapping.yml",
            expected=by_name["mapping.yml"],
        )

    launch = _read_yaml_at(
        directory_descriptor,
        "launch.yml",
        expected=by_name.get("launch.yml"),
    )
    if not isinstance(launch, dict) or not isinstance(launch.get("mapping"), dict):
        raise OSError("alias launch mapping is invalid")
    return launch["mapping"]


def _ticket_file_is_safe(
    project: Project,
    worktree: Path,
    value: Any,
) -> bool:
    if not isinstance(value, str):
        return False
    ticket_file = Path(value)
    try:
        if (
            not ticket_file.is_absolute()
            or ticket_file.is_symlink()
            or not ticket_file.is_file()
        ):
            return False
        resolved = ticket_file.resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    destructive_roots = (
        project.common_directory,
        project.runner_directory,
        project.worktree_root / "runs",
    )
    return all(root not in (resolved, *resolved.parents) for root in destructive_roots)


def _alias_terminal_outcome_is_valid(
    directory_descriptor: int,
    entries: Tuple[BoundAliasEntry, ...],
) -> bool:
    by_name = {entry.name: entry for entry in entries}
    turn_exists = "turn.yml" in by_name
    error_exists = "launch-error.yml" in by_name
    if turn_exists == error_exists:
        return False
    name = "turn.yml" if turn_exists else "launch-error.yml"
    try:
        outcome = _read_yaml_at(
            directory_descriptor,
            name,
            expected=by_name[name],
        )
    except (OSError, UnicodeError, yaml.YAMLError):
        return False
    if turn_exists:
        return valid_runtime_turn_outcome(outcome)
    return valid_terminal_launch_failure(outcome)


def _read_yaml_at(
    directory_descriptor: int,
    name: str,
    *,
    expected: BoundAliasEntry | None = None,
) -> Any:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(name, flags, dir_fd=directory_descriptor)
    try:
        identity = os.fstat(descriptor)
        if not stat.S_ISREG(identity.st_mode):
            raise OSError("diagnostic is not a regular file")
        if expected is not None and not _bound_entry_matches(
            expected, identity
        ):
            raise OSError("diagnostic identity changed")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            content = stream.read()
        current = os.fstat(descriptor)
        if expected is not None and not _bound_entry_matches(
            expected, current
        ):
            raise OSError("diagnostic changed while being read")
        if expected is not None and hashlib.sha256(content).hexdigest() != (
            expected.digest
        ):
            raise OSError("diagnostic content changed")
        return yaml.safe_load(content.decode("utf-8"))
    finally:
        os.close(descriptor)


def _role_alias_is_valid(role: Any, stem: str, alias: str) -> bool:
    marker = ROLE_ALIAS_MARKERS.get(role) if isinstance(role, str) else None
    return marker is not None and re.fullmatch(
        r"{0}@{1}[1-9][0-9]*".format(re.escape(stem), marker), alias
    ) is not None


def _unsafe_alias_entries(bound_aliases: List[BoundAlias]) -> List[str]:
    unsafe = []
    flags = directory_open_flags()
    for alias in bound_aliases:
        directory = alias.path
        try:
            descriptor = os.open(str(directory), flags)
        except OSError:
            unsafe.append("{0}/<unreadable>".format(directory.name))
            continue
        try:
            if not _bound_alias_matches(alias, os.fstat(descriptor)):
                unsafe.append("{0}/<replaced>".format(directory.name))
                continue
            try:
                current_entries = _capture_alias_entries(descriptor)
            except OSError:
                unsafe.append("{0}/<changed>".format(directory.name))
                continue
            if current_entries != alias.entries:
                unsafe.append("{0}/<changed>".format(directory.name))
                continue
            for entry in current_entries:
                if (
                    entry.name not in RUNTIME_DIAGNOSTIC_FILES
                    or not stat.S_ISREG(entry.mode)
                ):
                    unsafe.append(
                        "{0}/{1}".format(directory.name, entry.name)
                    )
        finally:
            os.close(descriptor)
    return unsafe


def _remove_aliases(
    bound_aliases: List[BoundAlias],
    session_snapshot: SessionSnapshot | None,
) -> None:
    if session_snapshot is None:
        if bound_aliases:
            raise OSError("sessions root was not captured")
        return
    session_root = session_snapshot.path
    if any(alias.path.parent != session_root for alias in bound_aliases):
        raise OSError("bound aliases do not share one session root")
    flags = directory_open_flags()
    runner_descriptor = os.open(str(session_root.parent), flags)
    try:
        session_descriptor = os.open(
            session_root.name,
            flags,
            dir_fd=runner_descriptor,
        )
        try:
            session_identity = os.fstat(session_descriptor)
            if (
                session_identity.st_dev != session_snapshot.device
                or session_identity.st_ino != session_snapshot.inode
                or tuple(sorted(os.listdir(session_descriptor)))
                != session_snapshot.names
            ):
                raise OSError("sessions root changed after inspection")
            remaining_names = list(session_snapshot.names)
            for alias in bound_aliases:
                alias_descriptor = os.open(
                    alias.path.name,
                    flags,
                    dir_fd=session_descriptor,
                )
                try:
                    if not _bound_alias_matches(
                        alias, os.fstat(alias_descriptor)
                    ):
                        raise OSError("bound alias identity changed")
                    remaining = list(alias.entries)
                    while remaining:
                        if not _bound_alias_matches(
                            alias, os.fstat(alias_descriptor)
                        ):
                            raise OSError("bound alias identity changed")
                        if tuple(remaining) != _capture_alias_entries(
                            alias_descriptor
                        ):
                            raise OSError("alias diagnostics changed")
                        entry = remaining.pop(0)
                        if entry.name not in RUNTIME_DIAGNOSTIC_FILES:
                            raise OSError("alias entry is not Runner transport state")
                        current_entry = os.stat(
                            entry.name,
                            dir_fd=alias_descriptor,
                            follow_symlinks=False,
                        )
                        if not _bound_entry_matches(entry, current_entry):
                            raise OSError("alias entry is not a regular file")
                        quarantine = _quarantine_name()
                        os.rename(
                            entry.name,
                            quarantine,
                            src_dir_fd=alias_descriptor,
                            dst_dir_fd=alias_descriptor,
                        )
                        quarantined = os.stat(
                            quarantine,
                            dir_fd=alias_descriptor,
                            follow_symlinks=False,
                        )
                        if not _bound_entry_object_matches(
                            entry, quarantined
                        ):
                            os.fsync(alias_descriptor)
                            raise OSError(
                                "alias entry changed during retirement"
                            )
                        os.unlink(quarantine, dir_fd=alias_descriptor)
                    if os.listdir(alias_descriptor):
                        raise OSError("alias diagnostics changed")
                    os.fsync(alias_descriptor)
                finally:
                    os.close(alias_descriptor)
                current = os.stat(
                    alias.path.name,
                    dir_fd=session_descriptor,
                    follow_symlinks=False,
                )
                if not _bound_alias_matches(alias, current):
                    raise OSError("bound alias identity changed")
                quarantine = _quarantine_name()
                os.rename(
                    alias.path.name,
                    quarantine,
                    src_dir_fd=session_descriptor,
                    dst_dir_fd=session_descriptor,
                )
                quarantined = os.stat(
                    quarantine,
                    dir_fd=session_descriptor,
                    follow_symlinks=False,
                )
                if not _bound_alias_matches(alias, quarantined):
                    os.fsync(session_descriptor)
                    raise OSError("bound alias changed during retirement")
                os.rmdir(quarantine, dir_fd=session_descriptor)
                remaining_names.remove(alias.path.name)
                if tuple(sorted(os.listdir(session_descriptor))) != tuple(
                    remaining_names
                ):
                    raise OSError("sessions root changed during cleanup")
            os.fsync(session_descriptor)
        finally:
            os.close(session_descriptor)
    finally:
        os.close(runner_descriptor)


def _bound_alias_matches(
    alias: BoundAlias,
    identity: os.stat_result,
) -> bool:
    return (
        stat.S_ISDIR(identity.st_mode)
        and identity.st_dev == alias.device
        and identity.st_ino == alias.inode
    )


def _bound_entry_matches(
    entry: BoundAliasEntry,
    identity: os.stat_result,
) -> bool:
    return (
        identity.st_dev == entry.device
        and identity.st_ino == entry.inode
        and identity.st_mode == entry.mode
        and identity.st_size == entry.size
        and identity.st_mtime_ns == entry.modified_ns
        and identity.st_ctime_ns == entry.changed_ns
    )


def _bound_entry_object_matches(
    entry: BoundAliasEntry,
    identity: os.stat_result,
) -> bool:
    return (
        stat.S_ISREG(identity.st_mode)
        and identity.st_dev == entry.device
        and identity.st_ino == entry.inode
    )


def _quarantine_name() -> str:
    return ".runner-retired-{0}".format(secrets.token_hex(16))


def _digest_file_at(
    directory_descriptor: int,
    name: str,
    expected: os.stat_result,
) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(name, flags, dir_fd=directory_descriptor)
    try:
        before = os.fstat(descriptor)
        if not _stat_identity_matches(expected, before):
            raise OSError("diagnostic changed before hashing")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            digest = hashlib.sha256(stream.read()).hexdigest()
        after = os.fstat(descriptor)
        if not _stat_identity_matches(expected, after):
            raise OSError("diagnostic changed while hashing")
        return digest
    finally:
        os.close(descriptor)


def _stat_identity_matches(
    first: os.stat_result,
    second: os.stat_result,
) -> bool:
    return (
        first.st_dev == second.st_dev
        and first.st_ino == second.st_ino
        and first.st_mode == second.st_mode
        and first.st_size == second.st_size
        and first.st_mtime_ns == second.st_mtime_ns
        and first.st_ctime_ns == second.st_ctime_ns
    )


def _persistent_evidence_errors(
    target: CleanupTarget, bound_aliases: List[BoundAlias]
) -> List[str]:
    run_root = target.project.state_directory / target.run_id
    ticket_root = run_root / "tickets" / target.worktree.name
    worktree_roots = [target.worktree]
    worktree_roots.extend(
        _registered_worktree_path(record)
        for record in registered_worktrees(target.project.repository)
    )
    if any(
        _paths_overlap(target.project.state_directory, worktree)
        for worktree in worktree_roots
    ):
        return ["persistent-evidence-invalid"]
    retained_files = (
        run_root / "worldline.jsonl",
        run_root / "ledger.yml",
        run_root / "task-map.mmd",
        ticket_root / "metadata.yml",
        ticket_root / "result.md",
        ticket_root / "validation.md",
    )
    for path in retained_files:
        if os.path.lexists(str(path)) and (
            path.is_symlink() or not path.is_file()
        ):
            return ["persistent-evidence-invalid"]
    try:
        retained_batches = [
            path
            for path in run_root.iterdir()
            if re.fullmatch(
                r"batch(?:-(?:[2-9]|[1-9][0-9]+))?\.yml", path.name
            )
        ]
    except OSError:
        return ["persistent-evidence-invalid"]
    if not retained_batches or any(
        path.is_symlink() or not path.is_file() for path in retained_batches
    ):
        return ["persistent-evidence-invalid"]
    reviews = ticket_root / "reviews"
    if os.path.lexists(str(reviews)):
        try:
            if reviews.is_symlink() or not reviews.is_dir():
                return ["persistent-evidence-invalid"]
            if any(path.is_symlink() or not path.is_file() for path in reviews.iterdir()):
                return ["persistent-evidence-invalid"]
        except OSError:
            return ["persistent-evidence-invalid"]
    trace_root = ticket_root / "traces"
    if trace_root.is_symlink() or not trace_root.is_dir():
        return ["persistent-evidence-invalid"]
    for alias in bound_aliases:
        alias_root = trace_root / alias.path.name
        if alias_root.is_symlink() or not alias_root.is_dir():
            return ["persistent-evidence-invalid"]
        requires_nonempty_trace = any(
            entry.name == "turn.yml" for entry in alias.entries
        )
        for turn in range(1, alias.turn + 1):
            turn_root = alias_root / "turn-{0}".format(turn)
            trace = turn_root / "events.jsonl"
            try:
                if (
                    turn_root.is_symlink()
                    or not turn_root.is_dir()
                    or trace.is_symlink()
                    or not trace.is_file()
                    or (
                        requires_nonempty_trace
                        and trace.stat().st_size == 0
                    )
                ):
                    return ["persistent-evidence-invalid"]
            except OSError:
                return ["persistent-evidence-invalid"]
    return []


def _delete_ticket_branch_if_dev_unchanged(
    project: Project,
    branch: str,
    ticket_commit: str,
) -> None:
    transaction = (
        "option no-deref\n"
        "start\n"
        "verify refs/heads/{0} {1}\n"
        "delete refs/heads/{2} {3}\n"
        "prepare\n"
        "commit\n"
    ).format(project.integration_branch, project.dev_commit, branch, ticket_commit)
    run_git(project.repository, "update-ref", "--stdin", input_text=transaction)


def _prune_worktree_ancestors(target: CleanupTarget) -> None:
    for directory in (
        target.worktree.parent,
        target.project.worktree_root / "runs",
    ):
        try:
            directory.rmdir()
        except FileNotFoundError:
            continue
        except OSError as error:
            if error.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
                raise


def _registered_worktree_path(record: Dict[str, str]) -> Path:
    value = record.get("worktree")
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise RunnerError("GIT_FAILED", "A required Git operation failed.")
    try:
        return Path(value).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise RunnerError(
            "GIT_FAILED", "A required Git operation failed."
        ) from error


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _refused(
    *,
    target: CleanupTarget,
    code: str,
    message: str,
    evidence: Dict[str, Any],
) -> CleanupResponse:
    return CleanupResponse(
        document={
            "run_id": target.run_id,
            "ticket_id": target.ticket_id,
            "cleanup_status": "refused",
            "worktree_path": str(target.worktree),
            "branch": target.branch,
            "error": {"code": code, "message": message},
            "evidence": evidence,
        },
        succeeded=False,
    )


def _already_cleaned(target: CleanupTarget) -> CleanupResponse:
    return CleanupResponse(
        document={
            "run_id": target.run_id,
            "ticket_id": target.ticket_id,
            "cleanup_status": "already-cleaned",
            "worktree_path": str(target.worktree),
            "branch": target.branch,
            "aliases_removed": [],
            "evidence": {"disposable_state": "absent"},
        },
        succeeded=True,
    )
