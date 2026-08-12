"""Install the accepted Codex and machine-local Runner configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Dict

import yaml


RUNNER_CONFIG_VERSION = 1
ROLE_BINDINGS = {
    "engineer-junior": "engineer-junior",
    "engineer-senior": "engineer-senior",
    "engineer-expert": "engineer-expert",
}
RESOURCE_PATHS = (
    "config.toml",
    "agents/delivery-state.toml",
    "agents/engineer-expert.toml",
    "agents/engineer-junior.toml",
    "agents/engineer-senior.toml",
    "agents/merge-resolver.toml",
    "hooks/worktree_guard.py",
)


class CodexProjectError(Exception):
    """Accepted Codex or machine-local Runner files could not be installed."""


@dataclass(frozen=True)
class CodexProjectFiles:
    """A preloaded release resource set that configures one Harness Project."""

    resources_by_path: Dict[str, bytes]

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
        integration_worktree: Path,
        state_directory: Path,
        common_git_directory: Path,
        worktree_root: Path,
        runtime_executable: Path,
    ) -> None:
        self._write_resources(integration_worktree)
        self._ensure_scratch_link(integration_worktree, state_directory)
        self._ensure_scratch_is_ignored(common_git_directory)
        self._write_runner_config(
            common_git_directory,
            worktree_root,
            runtime_executable,
        )

    def _write_resources(self, integration_worktree: Path) -> None:
        for relative_path, content in self.resources_by_path.items():
            target = integration_worktree / ".codex" / relative_path
            if target.exists():
                if target.is_file() and target.read_bytes() == content:
                    continue
                raise CodexProjectError(
                    "Runtime resource already exists with different content: "
                    "{0}".format(target)
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

    @staticmethod
    def _ensure_scratch_link(
        integration_worktree: Path,
        state_directory: Path,
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
            os.path.relpath(state_directory, integration_worktree),
            target_is_directory=True,
        )
        if scratch.resolve() != state_directory.resolve():
            raise CodexProjectError(
                "Integration .scratch does not resolve to the Harness State "
                "Directory."
            )

    @staticmethod
    def _ensure_scratch_is_ignored(common_git_directory: Path) -> None:
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

    @staticmethod
    def _write_runner_config(
        common_git_directory: Path,
        worktree_root: Path,
        runtime_executable: Path,
    ) -> None:
        config = {
            "version": RUNNER_CONFIG_VERSION,
            "default_runtime": "codex",
            "worktree_root": str(worktree_root.resolve()),
            "integration_branch": "dev",
            "runtimes": {
                "codex": {
                    "executable": str(runtime_executable.resolve()),
                    "roles": ROLE_BINDINGS,
                }
            },
        }
        content = yaml.safe_dump(config, sort_keys=False)
        config_file = common_git_directory / "agent-runner" / "config.yml"
        if config_file.exists():
            if (
                config_file.is_file()
                and config_file.read_text(encoding="utf-8") == content
            ):
                return
            raise CodexProjectError(
                "Project Runner Config already exists with different content: "
                "{0}".format(config_file)
            )
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(content, encoding="utf-8")
