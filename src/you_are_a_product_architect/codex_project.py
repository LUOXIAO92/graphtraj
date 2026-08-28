"""Install the accepted root-owned Codex and Runner configuration."""

from __future__ import annotations

import json
import os
import shlex
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Callable, Dict, Optional

import yaml

from .runner_models import (
    LOGICAL_ROLES,
    RUNNER_CONFIG_VERSION,
    managed_runtime_policy_matches,
)


ROLE_BINDINGS = {role: role for role in LOGICAL_ROLES}
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
    """Accepted Codex or machine-local Runner files could not be installed."""


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
    def scratch_action(
        integration_worktree: Path,
        state_directory: Path,
    ) -> str:
        """Describe the Integration scratch symlink mutation."""

        return "Integration scratch link: {0} -> {1}".format(
            integration_worktree / ".scratch",
            state_directory,
        )

    @staticmethod
    def exclude_action(common_git_directory: Path) -> str:
        """Describe the machine-local Git exclude registration."""

        return "Ignore Integration .scratch in {0}".format(
            common_git_directory / "info" / "exclude"
        )

    @staticmethod
    def runner_config_action(runtime_store: Path) -> str:
        """Describe the machine-local Runner configuration write."""

        return "Harness Runner Config: {0}".format(
            runtime_store / "agent-runner" / "config.yml"
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

    def install(
        self,
        *,
        harness_root: Path,
        source_repository: Path,
        integration_worktree: Path,
        state_directory: Path,
        common_git_directory: Path,
        worktree_root: Path,
        runtime_executable: Path,
        on_action_complete: Optional[Callable[[str], None]] = None,
    ) -> None:
        runtime_store = harness_root / ".codex"
        self._write_resources(runtime_store, on_action_complete)
        self._ensure_scratch_link(
            integration_worktree,
            state_directory,
            on_action_complete,
        )
        self._ensure_scratch_is_ignored(
            common_git_directory,
            on_action_complete,
        )
        self._write_runner_config(
            runtime_store,
            harness_root,
            source_repository,
            common_git_directory,
            worktree_root,
            runtime_executable,
            on_action_complete,
        )

    @staticmethod
    def scratch_link_text(
        integration_worktree: Path,
        state_directory: Path,
    ) -> str:
        """Return the stable repository-local link text setup will install."""

        return os.path.relpath(state_directory, integration_worktree)

    @staticmethod
    def runner_config_content(
        harness_root: Path,
        source_repository: Path,
        common_git_directory: Path,
        worktree_root: Path,
        runtime_executable: Path,
    ) -> str:
        """Render the exact machine-local Runner registration."""

        config = {
            "version": RUNNER_CONFIG_VERSION,
            "harness_root": str(harness_root.resolve()),
            "repository": str(source_repository.resolve()),
            "common_directory": str(common_git_directory.resolve()),
            "default_runtime": "codex",
            "worktree_root": str(worktree_root.resolve()),
            "integration_branch": "dev",
            "runtimes": {
                "codex": {
                    "executable": str(runtime_executable.resolve()),
                    "roles": ROLE_BINDINGS,
                }
            },
            "repository_skill_allowlist": [],
        }
        return yaml.safe_dump(config, sort_keys=False)

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
    def _ensure_scratch_link(
        integration_worktree: Path,
        state_directory: Path,
        on_action_complete: Optional[Callable[[str], None]],
    ) -> None:
        scratch = integration_worktree / ".scratch"
        if os.path.lexists(str(scratch)):
            if scratch.is_symlink() and scratch.resolve() == state_directory.resolve():
                return
            raise CodexProjectError(
                "Integration .scratch does not resolve to the Harness State "
                "Directory."
            )
        scratch.symlink_to(
            CodexProjectFiles.scratch_link_text(
                integration_worktree,
                state_directory,
            ),
            target_is_directory=True,
        )
        if on_action_complete is not None:
            on_action_complete(
                CodexProjectFiles.scratch_action(
                    integration_worktree,
                    state_directory,
                )
            )
        if scratch.resolve() != state_directory.resolve():
            raise CodexProjectError(
                "Integration .scratch does not resolve to the Harness State "
                "Directory."
            )

    @staticmethod
    def _ensure_scratch_is_ignored(
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
        if "/.scratch" in existing.splitlines():
            return
        separator = "" if not existing or existing.endswith("\n") else "\n"
        with exclude_file.open("a", encoding="utf-8") as stream:
            stream.write("{0}/.scratch\n".format(separator))
        if on_action_complete is not None:
            on_action_complete(
                CodexProjectFiles.exclude_action(common_git_directory)
            )

    @staticmethod
    def _write_runner_config(
        runtime_store: Path,
        harness_root: Path,
        source_repository: Path,
        common_git_directory: Path,
        worktree_root: Path,
        runtime_executable: Path,
        on_action_complete: Optional[Callable[[str], None]],
    ) -> None:
        content = CodexProjectFiles.runner_config_content(
            harness_root,
            source_repository,
            common_git_directory,
            worktree_root,
            runtime_executable,
        )
        config_file = runtime_store / "agent-runner" / "config.yml"
        if config_file.exists():
            if (
                config_file.is_file()
                and config_file.read_text(encoding="utf-8") == content
            ):
                return
            raise CodexProjectError(
                "Harness Runner Config already exists with different content: "
                "{0}".format(config_file)
            )
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(content, encoding="utf-8")
        if on_action_complete is not None:
            on_action_complete(
                CodexProjectFiles.runner_config_action(runtime_store)
            )
