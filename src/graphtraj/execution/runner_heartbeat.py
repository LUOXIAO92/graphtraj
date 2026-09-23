"""Durable Worker heartbeat and ownership lock for one held Session."""

from __future__ import annotations

import fcntl
import os
import time
from pathlib import Path
from typing import IO, Any

import yaml

from graphtraj.execution.runner_io import write_yaml_durably


HEARTBEAT_FILE_NAME = "heartbeat.yml"

# The owning Worker refreshes its record at this interval for as long as it
# holds the Session, including through every normal wait. It is short enough to
# show a stop within about a second and cheap enough to rewrite the small
# record for the whole lifetime of one execution.
HEARTBEAT_INTERVAL_SECONDS = 0.5


def execution_start_lock(runner_directory: Path) -> IO[bytes]:
    """Serialize execution startup with publication of a subtree stop.

    Hold until the new execution's mapping is durable, or startup has failed.
    Closing the returned stream releases the lock.
    """
    # ponytail: serialize project startup only; use branch locks if startup
    # throughput becomes a measured problem. Running Turns never hold this.
    runner_directory.mkdir(parents=True, exist_ok=True)
    stream = (runner_directory / "execution-start.lock").open("a+b")
    fcntl.flock(stream, fcntl.LOCK_EX)
    return stream


def write_heartbeat(directory: Path, record: dict[str, Any]) -> None:
    """Publish which entity the current process still holds and when.

    Parameters
    ----------
    directory
        Session directory of the execution the caller owns.
    record
        Ownership facts: ``alias``, optional ``execution_id`` and
        ``worker_pid``. The publication time is added as ``updated_at``.
    """
    write_yaml_durably(
        directory / HEARTBEAT_FILE_NAME,
        {**record, "updated_at": time.time()},
    )


def read_heartbeat(directory: Path) -> dict[str, Any] | None:
    """Return the last published heartbeat, or None when none is usable.

    The record is evidence of which Session, execution and process last held
    the execution, and of the moment that was last true. Its age alone decides
    nothing: a reader compares the ownership lock instead.
    """
    path = directory / HEARTBEAT_FILE_NAME
    if path.is_symlink() or not path.is_file():
        return None
    try:
        record = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return None
    if not isinstance(record, dict) or not _is_process_id(record.get("worker_pid")):
        return None
    return record


def hold_ownership(directory: Path, pid: int) -> IO[bytes]:
    """Hold the ownership lock naming one Worker and return its held stream.

    The lock lives in the Session directory and stays held for as long as the
    process owns the Session. The operating system releases it when the
    process ends, including after a kill, so a process identifier that was
    reused later cannot present an earlier owner's lock.
    """
    stream = _lock_path(directory, pid).open("a+b")
    fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
    return stream


def ownership_is_held(directory: Path, pid: int) -> bool:
    """Return whether a live process still holds the recorded owner's lock."""

    path = _lock_path(directory, pid)
    if path.is_symlink() or not path.is_file():
        return False
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
    except OSError:
        return False
    try:
        # A shared attempt fails while any owner holds the lock and never
        # blocks an owner that is starting.
        fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except OSError:
        return True
    finally:
        os.close(descriptor)
    return False


def _lock_path(directory: Path, pid: int) -> Path:
    return directory / "owner-{0}.lock".format(pid)


def _is_process_id(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
