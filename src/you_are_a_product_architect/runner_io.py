"""Small durable-file primitives shared by Runner processes."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml


ACTIVE_TURN_KEY = re.compile(r"^[0-9a-f]{64}$")


class ActiveTurnBusyError(Exception):
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


def reserve_active_turn(
    runner_directory: Path,
    key: str,
    starting: dict[str, Any],
) -> None:
    """Atomically reserve one Ticket Worktree for a new Engineer turn."""

    active_root = runner_directory / "active-worktrees"
    try:
        if active_root.is_symlink():
            raise OSError("active-turn root is a symlink")
        active_root.mkdir(parents=True, exist_ok=True)
        reservation = active_turn_directory(runner_directory, key)
        reservation.mkdir(mode=0o700)
    except FileExistsError as error:
        raise ActiveTurnBusyError(_read_reserved_alias(reservation)) from error
    except (OSError, ValueError) as error:
        raise ActiveTurnReservationError from error

    try:
        write_yaml_durably(
            reservation / "reservation.yml",
            {"activity": "starting", **starting},
        )
    except (OSError, yaml.YAMLError) as error:
        release_active_turn(runner_directory, key)
        raise ActiveTurnReservationError from error


def confirm_alias_mapping_durable(mapping_file: Path) -> None:
    """Sync a mapping and every new directory entry before launch success."""

    if mapping_file.is_symlink() or not mapping_file.is_file():
        raise OSError("alias mapping is not a regular file")
    _sync_file(mapping_file)
    _sync_directory(mapping_file.parent)
    _sync_directory(mapping_file.parent.parent)
    _sync_directory(mapping_file.parent.parent.parent)


def release_active_turn(runner_directory: Path, key: str) -> None:
    """Release only an empty, known-shape active-turn reservation."""

    try:
        reservation = active_turn_directory(runner_directory, key)
    except ValueError:
        return
    owner = reservation / "reservation.yml"
    try:
        if owner.is_symlink() or (owner.exists() and not owner.is_file()):
            return
        owner.unlink(missing_ok=True)
        reservation.rmdir()
        _sync_directory(reservation.parent)
    except OSError:
        # A stale reservation fails closed on later launches. Never recurse or
        # remove an unexpected entry from machine-local Runner state.
        return


def _read_reserved_alias(reservation: Path) -> str | None:
    owner = reservation / "reservation.yml"
    try:
        if (
            reservation.is_symlink()
            or not reservation.is_dir()
            or owner.is_symlink()
            or not owner.is_file()
        ):
            return None
        document = yaml.safe_load(owner.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return None
    if not isinstance(document, dict) or document.get("activity") not in {
        "starting",
        "running",
    }:
        return None
    alias = document.get("alias")
    return alias if isinstance(alias, str) and alias else None


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
