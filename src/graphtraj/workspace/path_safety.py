"""Shared path expansion used by setup preflight and mutation checks."""

from pathlib import Path
from typing import Tuple


def relative_parent_paths(relative_path: str) -> Tuple[str, ...]:
    """Return every non-empty parent of a normalized relative path."""

    parts = Path(relative_path).parts
    return tuple(Path(*parts[:index]).as_posix() for index in range(1, len(parts)))
