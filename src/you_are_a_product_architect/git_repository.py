"""Git mechanics for one selected Source Repository."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


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
        message = result.stderr.strip() or result.stdout.strip() or "Git command failed."
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


@dataclass(frozen=True)
class SourceRepository:
    """The narrow Git interface needed to establish an Integration Worktree."""

    primary_worktree: Path

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
        if _git(primary, "branch", "--show-current") != "main":
            raise GitRepositoryError(
                "The selected Primary Worktree must remain checked out on main."
            )
        return cls(primary_worktree=primary)

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

    def add_new_branch_worktree(
        self,
        branch: str,
        worktree: Path,
        base: str,
    ) -> None:
        _git(
            self.primary_worktree,
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree),
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
