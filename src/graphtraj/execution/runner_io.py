"""Small durable-file primitives shared by Runner processes."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml


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
            yaml.safe_dump(document, stream, sort_keys=False, allow_unicode=True)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == 'nt':
            _replace_windows(temporary, path)
        else:
            os.replace(str(temporary), str(path))
            _sync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def confirm_alias_mapping_durable(mapping_file: Path) -> None:
    """Sync a mapping and every new directory entry before launch success."""

    if mapping_file.is_symlink() or not mapping_file.is_file():
        raise OSError("alias mapping is not a regular file")
    _sync_file(mapping_file)
    _sync_directory(mapping_file.parent)
    _sync_directory(mapping_file.parent.parent)
    _sync_directory(mapping_file.parent.parent.parent)


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


def _replace_windows(source: Path, destination: Path) -> None:
    """Replace a flushed sibling file with Windows write-through semantics.

    Windows cannot open a directory with os.open for the POSIX fsync step.
    No copy/delete fallback is allowed; both paths are on the same volume.
    """
    import ctypes
    from ctypes import wintypes

    move = ctypes.WinDLL('kernel32', use_last_error=True).MoveFileExW
    move.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    move.restype = wintypes.BOOL
    # MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH
    if not move(str(source), str(destination), 0x1 | 0x8):
        raise ctypes.WinError(ctypes.get_last_error())
