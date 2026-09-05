"""Git mechanics for one selected Source Repository."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class GitRepositoryError(Exception):
    """A Source Repository does not satisfy setup or a Git operation failed."""


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        message = (
            result.stderr.strip()
            or result.stdout.strip()
            or "Git command failed."
        )
        raise GitRepositoryError(message)
    return result.stdout.strip()


def _git_succeeds(repository: Path, *arguments: str) -> bool:
    return (
        subprocess.run(
            ["git", *arguments],
            cwd=repository,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def _git_bytes(repository: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        message = (
            result.stderr.decode(errors="replace").strip()
            or result.stdout.decode(errors="replace").strip()
            or "Git command failed."
        )
        raise GitRepositoryError(message)
    return result.stdout


@dataclass(frozen=True)
class GitTreeEntry:
    """One exact path observed without checking out a Git tree."""

    kind: str
    content: Optional[bytes] = None


@dataclass(frozen=True)
class SourceRepository:
    """The narrow Git interface needed to establish an Integration Worktree."""

    primary_worktree: Path

    @classmethod
    def from_root(cls, root: Path) -> "SourceRepository":
        """Return the current directory when it is an existing Git root."""

        repository = root.resolve()
        if not os.path.lexists(str(repository / ".git")):
            raise GitRepositoryError(
                "Setup must be run from an existing Git repository root."
            )
        top_level = Path(_git(repository, "rev-parse", "--show-toplevel")).resolve()
        if top_level != repository:
            raise GitRepositoryError(
                "Setup must be run from the root of the existing Git repository."
            )
        return cls(primary_worktree=repository)

    @classmethod
    def from_primary(
        cls,
        harness_root: Path,
        selected_worktree: Path,
    ) -> "SourceRepository":
        primary = selected_worktree.resolve()
        if primary.parent != harness_root:
            raise GitRepositoryError(
                "The Primary Worktree must be an existing direct child of the "
                "Harness Project Root."
            )
        top_level = Path(_git(primary, "rev-parse", "--show-toplevel")).resolve()
        if top_level != primary:
            raise GitRepositoryError(
                "The selected directory must be the root of the Primary Worktree."
            )
        repository = cls(primary_worktree=primary)
        repository.require_main()
        return repository

    def require_main(self) -> None:
        """Require the Primary Worktree to remain on its accepted main branch."""

        if _git(self.primary_worktree, "branch", "--show-current") != "main":
            raise GitRepositoryError(
                "The selected Primary Worktree must remain checked out on main."
            )

    @property
    def common_directory(self) -> Path:
        common = Path(
            _git(self.primary_worktree, "rev-parse", "--git-common-dir")
        )
        if not common.is_absolute():
            common = self.primary_worktree / common
        return common.resolve()

    @property
    def head(self) -> str:
        return _git(self.primary_worktree, "rev-parse", "HEAD")

    def revision(self, ref: str) -> str:
        return _git(self.primary_worktree, "rev-parse", ref)

    def branch_exists(self, branch: str) -> bool:
        return _git_succeeds(
            self.primary_worktree,
            "show-ref",
            "--verify",
            "--quiet",
            "refs/heads/{0}".format(branch),
        )

    def worktree_for_branch(self, branch: str) -> Optional[Path]:
        for record in self._worktrees():
            if record.get("branch") == "refs/heads/{0}".format(branch):
                return Path(record["worktree"]).resolve()
        return None

    def create_branch(self, branch: str, base: str) -> None:
        """Create one branch as a separately reportable Git mutation."""

        _git(
            self.primary_worktree,
            "branch",
            branch,
            base,
        )

    def add_existing_branch_worktree(self, branch: str, worktree: Path) -> None:
        _git(
            self.primary_worktree,
            "worktree",
            "add",
            str(worktree),
            branch,
        )

    def tree_entry(self, revision: str, relative_path: str) -> Optional[GitTreeEntry]:
        """Read one exact path from a revision without materializing a Worktree."""

        output = _git_bytes(
            self.primary_worktree,
            "ls-tree",
            "-z",
            revision,
            "--",
            relative_path,
        )
        records = tuple(record for record in output.split(b"\0") if record)
        if not records:
            return None

        metadata, separator, encoded_path = records[0].partition(b"\t")
        if not separator or encoded_path.decode() != relative_path:
            return None
        mode, object_type, _object_id = metadata.decode().split(" ", maxsplit=2)
        if object_type == "tree":
            return GitTreeEntry(kind="directory")
        content = _git_bytes(
            self.primary_worktree,
            "show",
            "{0}:{1}".format(revision, relative_path),
        )
        if mode == "120000":
            return GitTreeEntry(kind="symlink", content=content)
        if object_type == "blob":
            return GitTreeEntry(kind="file", content=content)
        return GitTreeEntry(kind="other")

    def tree_paths(self, revision: str, relative_root: str) -> Tuple[str, ...]:
        """List every descendant path in one fixed Git tree."""

        output = _git_bytes(
            self.primary_worktree,
            "ls-tree",
            "-r",
            "-t",
            "-z",
            revision,
            "--",
            relative_root,
        )
        paths = []
        for record in output.split(b"\0"):
            if not record:
                continue
            _metadata, separator, encoded_path = record.partition(b"\t")
            if separator:
                paths.append(encoded_path.decode())
        return tuple(paths)

    def _worktrees(self) -> List[Dict[str, str]]:
        records: List[Dict[str, str]] = []
        record: Dict[str, str] = {}
        output = _git(self.primary_worktree, "worktree", "list", "--porcelain")
        for line in output.splitlines():
            if not line:
                if record:
                    records.append(record)
                    record = {}
                continue
            key, separator, value = line.partition(" ")
            record[key] = value if separator else ""
        if record:
            records.append(record)
        return records
