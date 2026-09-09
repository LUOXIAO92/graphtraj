"""Install the accepted root-owned Codex Runtime resources."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Callable, Dict, Optional

RESOURCE_PATHS = (
    "hooks/worktree_guard.py",
)


class CodexProjectError(Exception):
    """Accepted Codex Runtime files could not be installed."""


@dataclass(frozen=True)
class CodexProjectFiles:
    """A preloaded release resource set that configures one Harness Project."""

    resources_by_path: Dict[str, bytes]

    @staticmethod
    def resource_action(runtime_store: Path, relative_path: str) -> str:
        """Describe one exact Codex Runtime file mutation."""

        return "Harness Runtime resource: {0}".format(
            runtime_store / relative_path
        )

    @staticmethod
    def link_action(
        integration_worktree: Path,
        name: str,
        target: Path,
    ) -> str:
        """Describe one Integration Worktree symlink mutation."""

        return "Integration {0} link: {1} -> {2}".format(
            name.removeprefix("."),
            integration_worktree / name,
            target,
        )

    @staticmethod
    def exclude_action(common_git_directory: Path) -> str:
        """Describe the machine-local Git exclude registration."""

        return "Ignore Worktree views in {0}".format(
            common_git_directory / "info" / "exclude"
        )

    @classmethod
    def load(cls) -> "CodexProjectFiles":
        root = resources.files("graphtraj.resources").joinpath(
            "codex"
        )
        return cls(
            resources_by_path={
                relative_path: root.joinpath(
                    *relative_path.split("/")
                ).read_bytes()
                for relative_path in RESOURCE_PATHS
            }
        )

    def install_setup_resources(
        self,
        *,
        harness_root: Path,
        integration_worktree: Path,
        state_directory: Path,
        documents_directory: Path,
        common_git_directory: Path,
        on_action_complete: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Install Runtime resources without creating a Runner configuration."""

        runtime_store = harness_root / ".codex"
        self._write_resources(runtime_store, on_action_complete)
        self._ensure_link(
            integration_worktree,
            ".state",
            state_directory,
            on_action_complete,
        )
        created_documents = []
        if self._ensure_link(
            integration_worktree,
            "CONTEXT.md",
            harness_root / "CONTEXT.md",
            on_action_complete,
        ):
            created_documents.append("CONTEXT.md")
        if self._ensure_link(
            integration_worktree,
            "docs",
            documents_directory,
            on_action_complete,
        ):
            created_documents.append("docs")
        self._ensure_links_are_ignored(
            common_git_directory, on_action_complete,
            integration_worktree, created_documents,
        )

    @staticmethod
    def link_text(
        integration_worktree: Path,
        target: Path,
    ) -> str:
        """Return the stable repository-local link text setup will install."""

        return os.path.relpath(target, integration_worktree)

    def runtime_resources(self, runtime_store: Path) -> Dict[str, bytes]:
        """Return the root-owned resources rendered for this Runtime Store."""
        return dict(self.resources_by_path)

    def _write_resources(
        self,
        runtime_store: Path,
        on_action_complete: Optional[Callable[[str], None]],
    ) -> None:
        for relative_path, content in self.runtime_resources(runtime_store).items():
            target = runtime_store / relative_path
            if target.exists():
                if target.is_file() and target.read_bytes() == content:
                    continue
                raise CodexProjectError(
                    "Runtime resource already exists with different content: "
                    "{0}".format(target)
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            if on_action_complete is not None:
                on_action_complete(
                    self.resource_action(runtime_store, relative_path)
                )

    @staticmethod
    def _ensure_link(
        integration_worktree: Path,
        name: str,
        target: Path,
        on_action_complete: Optional[Callable[[str], None]],
    ) -> bool:
        link = integration_worktree / name
        if os.path.lexists(str(link)):
            if (name == "docs" and (link.is_dir() or link.is_symlink())) or (
                name == "CONTEXT.md" and (link.is_file() or link.is_symlink())
            ):
                return False
            if link.is_symlink() and link.resolve() == target.resolve():
                return False
            raise CodexProjectError(
                "Integration {0} does not resolve to its Harness Directory.".format(
                    name
                )
            )
        link.symlink_to(
            CodexProjectFiles.link_text(
                integration_worktree,
                target,
            ),
            target_is_directory=target.is_dir(),
        )
        if on_action_complete is not None:
            on_action_complete(
                CodexProjectFiles.link_action(
                    integration_worktree,
                    name,
                    target,
                )
            )
        if link.resolve() != target.resolve():
            raise CodexProjectError(
                "Integration {0} does not resolve to its Harness Directory.".format(
                    name
                )
            )

        return True

    @staticmethod
    def _ensure_links_are_ignored(
        common_git_directory: Path,
        on_action_complete: Optional[Callable[[str], None]],
        worktree: Path,
        created_documents: list[str],
    ) -> None:
        exclude_file = common_git_directory / "info" / "exclude"
        exclude_file.parent.mkdir(parents=True, exist_ok=True)
        existing = (
            exclude_file.read_text(encoding="utf-8")
            if exclude_file.exists()
            else ""
        )
        # The old installer emitted this complete sequence without a marker.
        # Leave isolated matching rules alone: they may belong to the user.
        legacy = "/.state\n/.scratch\n/CONTEXT.md\n/docs\n"
        updated = ("\n" + existing).replace(
            "\n" + legacy, "\n/.state\n/.scratch\n"
        )[1:]
        migrated = updated != existing
        if migrated:
            exclude_file.write_text(updated, encoding="utf-8")
            existing = updated
            for name in ("CONTEXT.md", "docs"):
                if (worktree / name).is_symlink() and name not in created_documents:
                    created_documents.append(name)
        ignore_worktree_documents(worktree, created_documents)
        missing = [
            path
            for path in ("/.state", "/.scratch")
            if path not in existing.splitlines()
        ]
        if not missing:
            return
        separator = "" if not existing or existing.endswith("\n") else "\n"
        with exclude_file.open("a", encoding="utf-8") as stream:
            stream.write("{0}{1}\n".format(separator, "\n".join(missing)))
        if on_action_complete is not None:
            on_action_complete(
                CodexProjectFiles.exclude_action(common_git_directory)
            )


def ignore_worktree_documents(worktree: Path, created: list[str]) -> None:
    """Keep generated document links out of this Worktree's status only."""
    def git(*arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(worktree), *arguments],
            text=True, capture_output=True,
        )
        if result.returncode and not (arguments[0] == "config" and result.returncode == 1):
            raise CodexProjectError(result.stderr.strip())
        return result.stdout.strip()

    git_directory = Path(git("rev-parse", "--absolute-git-dir"))
    exclude = git_directory / "graphtraj-document-exclude"
    marker = "# GraphTraj generated document links\n"
    previous = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    previous_rules = previous.partition(marker)[2].splitlines()
    names = [name for name in ("CONTEXT.md", "docs")
             if (name in created or "/" + name in previous_rules)
             and (worktree / name).is_symlink()
             and not git("ls-files", "--", name)]
    if not names and not previous:
        return
    current = git("config", "--path", "--get", "core.excludesFile")
    if current != str(exclude):
        # Retain the effective user ignore file as the base of our local copy.
        original = current or str(Path(os.environ.get(
            "XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "git/ignore")
        if git("config", "--bool", "--get", "extensions.worktreeConfig") != "true":
            git("config", "extensions.worktreeConfig", "true")
        git("config", "--worktree", "graphtraj.originalExcludesFile", original)
    else:
        original = git("config", "--worktree", "--path", "--get", "graphtraj.originalExcludesFile")
    source = Path(original)
    if not source.is_absolute():
        source = worktree / source
    base = source.read_text(encoding="utf-8") if source.is_file() else ""
    content = base + ("\n" if base and not base.endswith("\n") else "")
    content += marker + "".join("/" + name + "\n" for name in names)
    if content != previous:
        exclude.write_text(content, encoding="utf-8")
    git("config", "--worktree", "core.excludesFile", str(exclude))
