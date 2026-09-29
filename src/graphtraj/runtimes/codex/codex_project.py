"""Install the accepted root-owned Codex Runtime resources."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, Optional


class CodexProjectError(Exception):
    """Accepted Codex Runtime files could not be installed."""


class CodexProjectFiles:
    """Detect and clean up root-owned Codex project support files."""

    @classmethod
    def load(cls) -> "CodexProjectFiles":
        return cls()

    @staticmethod
    def runtime_store(harness_root: Path) -> Path:
        """Keep Codex resources at their existing project location."""
        return harness_root / ".codex"

    @classmethod
    def for_project(
        cls, harness_root: Path, runtimes: Iterable[str],
    ) -> "CodexProjectFiles | None":
        """Prepare Codex support only for selected or existing Codex projects."""
        store = cls.runtime_store(harness_root)
        if "codex" in runtimes or store.exists() or store.is_symlink():
            return cls.load()
        return None

    @staticmethod
    def obsolete_guard(runtime_store: Path) -> Path:
        """Return the former GraphTraj-owned Guard installation path."""

        return runtime_store / "hooks" / "worktree_guard.py"

    @staticmethod
    def obsolete_guard_action(runtime_store: Path) -> str:
        """Describe removal of the former GraphTraj-owned Guard."""

        return "Remove obsolete Harness Runtime resource: {0}".format(
            CodexProjectFiles.obsolete_guard(runtime_store)
        )

    @classmethod
    def has_obsolete_guard(cls, runtime_store: Path) -> bool:
        guard = cls.obsolete_guard(runtime_store)
        return guard.is_file() and not guard.is_symlink()

    def remove_obsolete_guard(
        self,
        runtime_store: Path,
        on_action_complete: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Remove the former GraphTraj-owned Guard if it is installed."""

        if not self.has_obsolete_guard(runtime_store):
            return
        self.obsolete_guard(runtime_store).unlink()
        if on_action_complete is not None:
            on_action_complete(self.obsolete_guard_action(runtime_store))
