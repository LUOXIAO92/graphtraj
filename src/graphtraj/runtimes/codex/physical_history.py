"""Exact physical history lookup within one already verified Codex connection."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import os
from pathlib import Path
import stat
from typing import BinaryIO, Iterator
from uuid import UUID


def rollout_identity(path: Path) -> tuple[str, str]:
    """Read Codex's documented logical/physical IDs from a canonical basename.

    This is only one check: native metadata and the actual first header must
    independently agree before any bounded content acquisition is allowed.
    """
    name = path.name
    if not name.startswith('rollout-') or not name.endswith('.jsonl'):
        raise ValueError('Declared physical source lacks a canonical uncompressed rollout name.')
    core = name[8:-6]
    try:
        datetime.strptime(core[:19], '%Y-%m-%dT%H-%M-%S')
        if core[19:20] != '-':
            raise ValueError
        ids = core[20:].split('_')
        if len(ids) not in (1, 2):
            raise ValueError
        return str(UUID(ids[0])), str(UUID(ids[-1]))
    except (ValueError, IndexError):
        raise ValueError('Invalid canonical logical/physical rollout identity.') from None


@contextmanager
def _directory(path: Path) -> Iterator[int]:
    """Open an absolute directory by descriptors, rejecting every symlink component."""
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('The owning sessions directory must be absolute without traversal.')
    descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def locate_physical_rollout(codex_home: Path, physical_id: str) -> Path:
    """Enumerate names only below sessions; require one exact canonical physical ID.

    No file contents are read here. Symlink directories are not traversed and
    matching symlink files or compressed sources are explicitly refused.
    """
    if str(UUID(physical_id)) != physical_id:
        raise ValueError('Declared physical identity must be a canonical UUID.')
    root = codex_home / 'sessions'
    matches = []
    with _directory(root) as descriptor:
        def fail(error: OSError) -> None:
            """Do not claim uniqueness when part of the authorized directory is unreadable."""
            raise error

        for directory, _, names, directory_fd in os.fwalk(
                '.', dir_fd=descriptor, follow_symlinks=False, onerror=fail):
            for name in names:
                plain_name = name[:-4] if name.endswith('.jsonl.zst') else name
                try:
                    _, candidate_id = rollout_identity(Path(plain_name))
                except ValueError:
                    continue
                if candidate_id != physical_id:
                    continue
                mode = os.stat(name, dir_fd=directory_fd, follow_symlinks=False).st_mode
                if not stat.S_ISREG(mode) or name != plain_name:
                    raise ValueError('Matching physical source is not a regular uncompressed file.')
                matches.append(root / directory / name)
    if len(matches) != 1:
        raise ValueError(f'Expected exactly one physical source in owning sessions; found {len(matches)}.')
    return matches[0]


@contextmanager
def open_physical_rollout(codex_home: Path, source: Path) -> Iterator[BinaryIO]:
    """Read a matched regular file without following any directory or file symlink."""
    root = codex_home / 'sessions'
    relative = source.relative_to(root)
    if '..' in relative.parts:
        raise ValueError('Physical source escapes the owning sessions directory.')
    with _directory(source.parent) as directory_fd:
        descriptor = os.open(source.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        with os.fdopen(descriptor, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError('Physical source is not a regular file.')
            yield stream
