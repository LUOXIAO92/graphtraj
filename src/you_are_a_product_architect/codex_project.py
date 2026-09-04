"""Install the accepted root-owned Codex Runtime resources."""

from __future__ import annotations

import json
import os
import shlex
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Callable, Dict, Optional

from .runner_models import managed_runtime_policy_matches


RESOURCE_PATHS = (
    "config.toml",
    "agents/delivery-state.toml",
    "agents/engineer-expert.toml",
    "agents/engineer-junior.toml",
    "agents/engineer-senior.toml",
    "agents/merge-resolver.toml",
    "agents/spec-reviewer.toml",
    "agents/standards-reviewer.toml",
    "hooks/worktree_guard.py",
)


class CodexProjectError(Exception):
    """Accepted Codex Runtime files could not be installed."""


def runtime_resource_matches(
    relative_path: str, configured: bytes, packaged: bytes
) -> bool:
    """Compare managed TOML policy and exact non-TOML Runtime resources."""
    if not relative_path.endswith(".toml"):
        return configured == packaged
    try:
        configured_document = tomllib.loads(configured.decode())
        packaged_document = tomllib.loads(packaged.decode())
    except (UnicodeError, tomllib.TOMLDecodeError):
        return False
    return managed_runtime_policy_matches(configured_document, packaged_document)


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
        root = resources.files("you_are_a_product_architect.resources").joinpath(
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
        include_document_views: bool,
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
        if include_document_views:
            self._ensure_link(
                integration_worktree,
                "CONTEXT.md",
                harness_root / "CONTEXT.md",
                on_action_complete,
            )
            self._ensure_link(
                integration_worktree,
                "docs",
                documents_directory,
                on_action_complete,
            )
        self._ensure_links_are_ignored(common_git_directory, on_action_complete)

    @staticmethod
    def link_text(
        integration_worktree: Path,
        target: Path,
    ) -> str:
        """Return the stable repository-local link text setup will install."""

        return os.path.relpath(target, integration_worktree)

    def runtime_resources(self, runtime_store: Path) -> Dict[str, bytes]:
        """Return the root-owned resources rendered for this Runtime Store."""
        rendered = dict(self.resources_by_path)
        relative_path = "agents/merge-resolver.toml"
        packaged_command = (
            b'command = \'python3 "$(git rev-parse --show-toplevel)/.codex/'
            b'hooks/worktree_guard.py"\''
        )
        guard_command = "python3 {0}".format(
            shlex.quote(str(runtime_store / "hooks" / "worktree_guard.py"))
        )
        rendered[relative_path] = rendered[relative_path].replace(
            packaged_command,
            "command = {0}".format(json.dumps(guard_command)).encode(),
        )
        return rendered

    def _write_resources(
        self,
        runtime_store: Path,
        on_action_complete: Optional[Callable[[str], None]],
    ) -> None:
        for relative_path, content in self.runtime_resources(runtime_store).items():
            target = runtime_store / relative_path
            if target.exists():
                if target.is_file() and runtime_resource_matches(
                    relative_path, target.read_bytes(), content
                ):
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
    ) -> None:
        link = integration_worktree / name
        if os.path.lexists(str(link)):
            if link.is_symlink() and link.resolve() == target.resolve():
                return
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

    @staticmethod
    def _ensure_links_are_ignored(
        common_git_directory: Path,
        on_action_complete: Optional[Callable[[str], None]],
    ) -> None:
        exclude_file = common_git_directory / "info" / "exclude"
        exclude_file.parent.mkdir(parents=True, exist_ok=True)
        existing = (
            exclude_file.read_text(encoding="utf-8")
            if exclude_file.exists()
            else ""
        )
        missing = [
            path
            for path in ("/.state", "/.scratch", "/CONTEXT.md", "/docs")
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
