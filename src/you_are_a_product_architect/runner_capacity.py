"""Immediate, project-wide capacity acquisition using worker-held OS locks."""

from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from typing import Iterator, BinaryIO

from .runner_models import Project, RunnerError


@contextmanager
def capacity_positions(
    project: Project, count: int, inherited_fd: int | None = None,
) -> Iterator[list[BinaryIO]]:
    """Acquire the whole set or release it; inherited positions keep their lock."""
    positions = []
    try:
        if inherited_fd is not None:
            positions.append(os.fdopen(inherited_fd, "rb"))
        directory = project.harness_root / ".graphtraj" / "runner" / "capacity"
        directory.mkdir(parents=True, exist_ok=True)
        for index in range(project.max_concurrency):
            if len(positions) == count:
                break
            stream = (directory / str(index)).open("a+b")
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                stream.close()
            else:
                positions.append(stream)
        if len(positions) != count:
            raise RunnerError(
                "insufficient-capacity",
                "The complete Batch needs {0} available capacity positions (project maximum: {1}). No task started.".format(count, project.max_concurrency),
            )
        yield positions
    finally:
        # Close rather than unlock: a worker may have inherited this open file.
        for stream in positions:
            stream.close()
