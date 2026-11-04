"""Cross-process exclusive locks on dedicated lock files.

Data files are never locked themselves; they are replaced atomically, so
readers on any platform see either the old or the new document.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

if os.name != "nt":
    import fcntl
else:
    import msvcrt


@contextmanager
def exclusive(path: Path) -> Iterator[None]:
    """Hold an exclusive lock on ``path`` (created if missing) for the block.

    POSIX ``flock`` locks belong to the open file, so separate threads of one
    process exclude each other just like separate processes.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if os.name != "nt":
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        else:
            # ponytail: msvcrt.locking retries for about 10 s and then raises;
            # no Windows host uses this core yet.
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            if os.name != "nt":
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            else:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
