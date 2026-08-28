"""Small durable-file primitives shared by Runner processes."""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import secrets
import stat
import tempfile
from pathlib import Path
from typing import Any, NamedTuple

import yaml


ACTIVE_TURN_KEY = re.compile(r"^[0-9a-f]{64}$")
REVIEWER_ROLES = frozenset({"standards-reviewer", "spec-reviewer"})


class ActiveTurnReservation(NamedTuple):
    """Identity of one atomically created active-ticket reservation."""

    key: str
    device: int
    inode: int
    role: str | None = None


class ActiveTurnBusyError(FileExistsError):
    """The project-wide Ticket Worktree reservation already exists."""

    def __init__(self, active_alias: str | None = None) -> None:
        super().__init__(active_alias)
        self.active_alias = active_alias

    @property
    def message(self) -> str:
        """Describe the active reservation without trusting partial state."""

        if self.active_alias is None:
            return "The Ticket Worktree already has an active Engineer turn."
        return (
            "The Ticket Worktree already has an active Engineer turn under "
            "alias {0}.".format(self.active_alias)
        )


class ActiveTurnReservationError(Exception):
    """The project-wide Ticket Worktree reservation could not be created."""


def active_turn_key(ticket_id: str) -> str:
    """Return the project-wide reservation key for one validated ticket ID."""

    return hashlib.sha256(ticket_id.encode("ascii")).hexdigest()


def write_yaml_durably(path: Path, document: Any) -> None:
    """Atomically replace one YAML document and sync its directory entry."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=".{0}.".format(path.name),
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            yaml.safe_dump(document, stream, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary), str(path))
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def active_turn_directory(runner_directory: Path, key: str) -> Path:
    """Resolve one validated reservation key below Runner-owned state."""

    if not ACTIVE_TURN_KEY.fullmatch(key):
        raise ValueError("invalid active-turn reservation key")
    return runner_directory / "active-worktrees" / key


def create_active_turn_reservation(
    runner_directory: Path,
    ticket_id: str,
    owner: Any,
) -> ActiveTurnReservation:
    """Atomically reserve one ticket and durably record its current owner."""

    key = active_turn_key(ticket_id)
    flags = directory_open_flags()
    runner_descriptor = os.open(str(runner_directory), flags)
    try:
        try:
            os.mkdir("active-worktrees", mode=0o700, dir_fd=runner_descriptor)
        except FileExistsError:
            pass
        active_descriptor = os.open("active-worktrees", flags, dir_fd=runner_descriptor)
        try:
            try:
                reservation_descriptor = os.open(
                    key,
                    os.O_RDWR
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=active_descriptor,
                )
                created = True
            except FileExistsError:
                reservation_descriptor = os.open(
                    key,
                    os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=active_descriptor,
                )
                created = False
            try:
                fcntl.flock(reservation_descriptor, fcntl.LOCK_EX)
                identity = os.fstat(reservation_descriptor)
                if not stat.S_ISREG(identity.st_mode):
                    raise OSError("active-turn reservation is not a regular file")
                role = owner.get("role") if isinstance(owner, dict) else None
                if not created:
                    current = _read_yaml_from_descriptor(reservation_descriptor)
                    reviewers = _reviewer_owners(current)
                    if (
                        role not in REVIEWER_ROLES
                        or reviewers is None
                        or any(item.get("role") == role for item in reviewers)
                    ):
                        raise ActiveTurnBusyError(_reserved_alias(current))
                    owner = {"reviewers": [*reviewers, owner]}
                reservation = ActiveTurnReservation(
                    key=key,
                    device=identity.st_dev,
                    inode=identity.st_ino,
                    role=role if role in REVIEWER_ROLES else None,
                )
                _write_yaml_to_descriptor(reservation_descriptor, owner)
                os.fsync(active_descriptor)
            finally:
                os.close(reservation_descriptor)
        finally:
            os.close(active_descriptor)
    finally:
        os.close(runner_descriptor)
    return reservation


def write_active_turn_owner(
    runner_directory: Path,
    reservation: ActiveTurnReservation,
    owner: Any,
) -> None:
    """Replace one reservation owner only through its captured directory."""

    runner_descriptor, active_descriptor, reservation_descriptor = (
        _open_active_turn(runner_directory, reservation)
    )
    try:
        fcntl.flock(reservation_descriptor, fcntl.LOCK_EX)
        if reservation.role in REVIEWER_ROLES:
            current = _read_yaml_from_descriptor(reservation_descriptor)
            reviewers = _reviewer_owners(current)
            if reviewers is None:
                raise OSError("active reviewer reservation is malformed")
            updated = [
                owner if item.get("role") == reservation.role else item
                for item in reviewers
            ]
            if all(item.get("role") != reservation.role for item in reviewers):
                raise OSError("active reviewer reservation is missing")
            _write_yaml_to_descriptor(
                reservation_descriptor,
                _reviewer_document(updated),
            )
        else:
            _write_yaml_to_descriptor(reservation_descriptor, owner)
    finally:
        os.close(reservation_descriptor)
        os.close(active_descriptor)
        os.close(runner_descriptor)


def confirm_alias_mapping_durable(mapping_file: Path) -> None:
    """Sync a mapping and every new directory entry before launch success."""

    if mapping_file.is_symlink() or not mapping_file.is_file():
        raise OSError("alias mapping is not a regular file")
    _sync_file(mapping_file)
    _sync_directory(mapping_file.parent)
    _sync_directory(mapping_file.parent.parent)
    _sync_directory(mapping_file.parent.parent.parent)


def release_active_turn(
    runner_directory: Path,
    reservation: ActiveTurnReservation,
) -> bool:
    """Release only the caller's identity-bound active-turn lease."""

    try:
        runner_descriptor, active_descriptor, reservation_descriptor = (
            _open_active_turn(runner_directory, reservation)
        )
    except (OSError, ValueError):
        return False
    try:
        fcntl.flock(reservation_descriptor, fcntl.LOCK_EX)
        current = os.stat(
            reservation.key,
            dir_fd=active_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(current.st_mode)
            or current.st_dev != reservation.device
            or current.st_ino != reservation.inode
        ):
            return False
        if reservation.role in REVIEWER_ROLES:
            document = _read_yaml_from_descriptor(reservation_descriptor)
            reviewers = _reviewer_owners(document)
            if reviewers is None or all(
                item.get("role") != reservation.role for item in reviewers
            ):
                return False
            remaining = [
                item
                for item in reviewers
                if item.get("role") != reservation.role
            ]
            if remaining:
                _write_yaml_to_descriptor(
                    reservation_descriptor,
                    _reviewer_document(remaining),
                )
                return True
        quarantine = _quarantine_name()
        os.rename(
            reservation.key,
            quarantine,
            src_dir_fd=active_descriptor,
            dst_dir_fd=active_descriptor,
        )
        quarantined = os.stat(
            quarantine,
            dir_fd=active_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(quarantined.st_mode)
            or quarantined.st_dev != reservation.device
            or quarantined.st_ino != reservation.inode
        ):
            os.fsync(active_descriptor)
            return False
        os.unlink(quarantine, dir_fd=active_descriptor)
        os.fsync(active_descriptor)
        return True
    except OSError:
        # A stale reservation fails closed on later launches. Never recurse or
        # remove an unexpected entry from machine-local Runner state.
        return False
    finally:
        os.close(reservation_descriptor)
        os.close(active_descriptor)
        os.close(runner_descriptor)


def _open_active_turn(
    runner_directory: Path,
    reservation: ActiveTurnReservation,
) -> tuple[int, int, int]:
    if not ACTIVE_TURN_KEY.fullmatch(reservation.key):
        raise ValueError("invalid active-turn reservation key")
    flags = directory_open_flags()
    runner_descriptor = os.open(str(runner_directory), flags)
    try:
        active_descriptor = os.open(
            "active-worktrees", flags, dir_fd=runner_descriptor
        )
    except OSError:
        os.close(runner_descriptor)
        raise
    try:
        reservation_descriptor = os.open(
            reservation.key,
            os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=active_descriptor,
        )
    except OSError:
        os.close(active_descriptor)
        os.close(runner_descriptor)
        raise
    identity = os.fstat(reservation_descriptor)
    if (
        not stat.S_ISREG(identity.st_mode)
        or identity.st_dev != reservation.device
        or identity.st_ino != reservation.inode
    ):
        os.close(reservation_descriptor)
        os.close(active_descriptor)
        os.close(runner_descriptor)
        raise OSError("active-turn reservation identity changed")
    return runner_descriptor, active_descriptor, reservation_descriptor


def _write_yaml_to_descriptor(descriptor: int, document: Any) -> None:
    """Persist YAML in place without transferring reservation identity."""

    content = yaml.safe_dump(document, sort_keys=False).encode("utf-8")
    os.lseek(descriptor, 0, os.SEEK_SET)
    os.ftruncate(descriptor, 0)
    offset = 0
    while offset < len(content):
        offset += os.write(descriptor, content[offset:])
    os.fsync(descriptor)


def _read_yaml_from_descriptor(descriptor: int) -> Any:
    os.lseek(descriptor, 0, os.SEEK_SET)
    with os.fdopen(os.dup(descriptor), "r", encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def _reviewer_owners(document: Any) -> list[dict[str, Any]] | None:
    if not isinstance(document, dict):
        return None
    reviewers = document.get("reviewers")
    if reviewers is None:
        reviewers = [document]
    if (
        not isinstance(reviewers, list)
        or not reviewers
        or any(
            not isinstance(owner, dict)
            or owner.get("role") not in REVIEWER_ROLES
            for owner in reviewers
        )
    ):
        return None
    return reviewers


def _reviewer_document(reviewers: list[dict[str, Any]]) -> dict[str, Any]:
    return reviewers[0] if len(reviewers) == 1 else {"reviewers": reviewers}


def _reserved_alias(document: Any) -> str | None:
    reviewers = _reviewer_owners(document)
    if reviewers is not None:
        aliases = [owner.get("alias") for owner in reviewers]
        return next(
            (alias for alias in aliases if isinstance(alias, str) and alias),
            None,
        )
    if not isinstance(document, dict):
        return None
    alias = document.get("alias")
    return alias if isinstance(alias, str) and alias else None


def _quarantine_name() -> str:
    """Return an unpublished pathname for identity-bound retirement."""

    return ".runner-retired-{0}".format(secrets.token_hex(16))


def directory_open_flags() -> int:
    """Return the shared no-follow flags for an owned directory."""

    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def read_active_turn_owner(runner_directory: Path, key: str) -> dict[str, Any]:
    """Read one regular-file reservation without following redirected state."""

    reservation = active_turn_directory(runner_directory, key)
    try:
        if reservation.is_symlink() or not reservation.is_file():
            raise OSError("active-turn reservation is not a regular file")
        document = yaml.safe_load(reservation.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise OSError("active-turn reservation is unreadable") from error
    if not isinstance(document, dict):
        raise OSError("active-turn reservation is malformed")
    return document


def active_turn_alias_released(
    runner_directory: Path, key: str, alias: str
) -> bool:
    """Return whether one alias no longer owns its active-turn lease."""

    if not os.path.lexists(str(active_turn_directory(runner_directory, key))):
        return True
    try:
        document = read_active_turn_owner(runner_directory, key)
    except OSError:
        return False
    reviewers = _reviewer_owners(document)
    return reviewers is not None and all(
        owner.get("alias") != alias for owner in reviewers
    )


def _sync_file(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(str(path), flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
